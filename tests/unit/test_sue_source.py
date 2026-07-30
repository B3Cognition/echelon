"""Unit tests for immutable SUE source-bundle primitives."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


source = _load("sue_source")


def _document(text: str = "The system MUST save.\n"):
    return source.SourceDocument.from_text(
        id="requirements",
        source_uri="requirements.md",
        media_type="text/markdown",
        text=text,
    )


def _unit(unit_id: str = "FR-001", *, document_id: str = "requirements"):
    return source.SourceUnit(
        id=unit_id,
        kind="requirement",
        text="The system MUST save.",
        normative_level="must",
        source_refs=(source.SourceRef(document_id, "line-range", "L1-L1"),),
        declared_relations=(),
        situation=None,
    )


def _bundle_with_text(text: str):
    return source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(text),),
        units=(_unit(),),
    )


def test_bundle_digest_is_canonical_and_stable():
    bundle_a = source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(_unit(),),
    )
    bundle_b = source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(_unit(),),
    )
    assert bundle_a.snapshot_digest == bundle_b.snapshot_digest
    assert len(bundle_a.snapshot_digest) == 64


def test_line_range_resolves_exact_original_text():
    document = source.SourceDocument.from_text(
        id="requirements",
        source_uri="requirements.md",
        media_type="text/markdown",
        text="# Checkout\nLine two\nLine three\n",
    )
    bundle = source.make_bundle(
        bundle_id="checkout",
        adapter_id="markdown-lexicon",
        documents=(document,),
        units=(),
    )
    ref = source.SourceRef("requirements", "line-range", "L2-L3")
    assert source.resolve_source_ref(bundle, ref) == "Line two\nLine three"


def test_line_range_preserves_crlf_in_original_text():
    document = source.SourceDocument.from_text(
        id="requirements",
        source_uri="requirements.md",
        media_type="text/markdown",
        text="# Checkout\r\nLine two\r\nLine three\r\n",
    )
    bundle = source.make_bundle(
        bundle_id="checkout",
        adapter_id="markdown-lexicon",
        documents=(document,),
        units=(),
    )
    ref = source.SourceRef("requirements", "line-range", "L2-L3")
    assert source.resolve_source_ref(bundle, ref) == "Line two\r\nLine three"


def test_bundle_copies_caller_owned_collections_before_hashing():
    document = _document()
    documents = [document]
    unit_refs = [source.SourceRef("requirements", "line-range", "L1-L1")]
    relation_refs = [source.SourceRef("requirements", "line-range", "L1-L1")]
    relations = [source.DeclaredRelation("depends-on", "FR-001", relation_refs)]
    units = [
        source.SourceUnit(
            id="FR-001",
            kind="requirement",
            text="The system MUST save.",
            normative_level="must",
            source_refs=unit_refs,
            declared_relations=relations,
            situation=None,
        )
    ]
    aliases = ["save operation"]
    glossary_refs = [source.SourceRef("requirements", "line-range", "L1-L1")]
    glossary = [source.GlossaryTerm("save", aliases, glossary_refs)]

    bundle = source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=documents,
        units=units,
        glossary=glossary,
    )
    digest = bundle.snapshot_digest

    documents.clear()
    unit_refs.clear()
    relation_refs.clear()
    relations.clear()
    aliases.clear()
    glossary_refs.clear()
    glossary.clear()

    assert isinstance(bundle.documents, tuple)
    assert isinstance(bundle.units, tuple)
    assert isinstance(bundle.glossary, tuple)
    assert bundle.units[0].source_refs == (
        source.SourceRef("requirements", "line-range", "L1-L1"),
    )
    assert bundle.units[0].declared_relations[0].source_refs == (
        source.SourceRef("requirements", "line-range", "L1-L1"),
    )
    assert bundle.glossary[0].aliases == ("save operation",)
    assert bundle.glossary[0].source_refs == (
        source.SourceRef("requirements", "line-range", "L1-L1"),
    )
    assert bundle.snapshot_digest == digest


def test_changed_document_changes_snapshot_digest():
    first = _bundle_with_text("The system MUST save.")
    second = _bundle_with_text("The system MUST not save.")
    assert first.snapshot_digest != second.snapshot_digest


def test_unknown_document_reference_is_rejected():
    with pytest.raises(ValueError, match="unknown document"):
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(_unit(document_id="missing"),),
        )


@pytest.mark.parametrize("locator", ("L2", "Lx-L3", "L2-Ly", "L3-L2"))
def test_malformed_line_range_is_rejected(locator: str):
    with pytest.raises(ValueError, match="line-range"):
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(_unit(),),
        )
        # Exercise validation at resolution too, for refs supplied externally.
        source.resolve_source_ref(_bundle_with_text("one\ntwo\n"), source.SourceRef("requirements", "line-range", locator))


def test_out_of_range_line_is_rejected():
    with pytest.raises(ValueError, match="out of range"):
        source.resolve_source_ref(_bundle_with_text("one\ntwo\n"), source.SourceRef("requirements", "line-range", "L3-L3"))


def test_duplicate_document_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate document"):
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(), _document()),
            units=(),
        )


def test_duplicate_unit_ids_are_rejected():
    with pytest.raises(ValueError, match="duplicate unit"):
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(_unit(), _unit()),
        )


def test_markdown_adapter_preserves_explicit_requirement_id(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Requirements\n\n- **FR-001**: The system MUST save.\n")
    bundle = source.load_source_bundle(path)
    assert [unit.id for unit in bundle.units] == ["FR-001"]
    assert bundle.units[0].text == "The system MUST save."
    assert bundle.units[0].source_refs[0].locator == "L3-L3"


def test_markdown_adapter_recognizes_requirement_heading(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# FR-002: The system SHALL retain audit history.\n")
    bundle = source.load_source_bundle(path)
    assert bundle.units[0].id == "FR-002"
    assert bundle.units[0].normative_level == "must"


def test_lexicon_adapter_extracts_controlled_situation(tmp_path):
    path = tmp_path / "rules.lex"
    path.write_text(
        "REQ: REQ-001\n"
        "GIVEN: an authenticated user\n"
        "WHEN: the user saves\n"
        "THEN: the record persists\n"
    )
    bundle = source.load_source_bundle(path)
    situation = bundle.units[0].situation
    assert situation.given == "an authenticated user"
    assert situation.when == "the user saves"
    assert situation.then == "the record persists"


def test_normative_bullet_gets_locator_id(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Rules\n\n- The cache MUST expire after 10 minutes.\n")
    bundle = source.load_source_bundle(path)
    assert bundle.units[0].id.endswith(":L3-L3")
    assert bundle.units[0].normative_level == "must"


def test_unstructured_prose_is_inconclusive(tmp_path):
    path = tmp_path / "notes.md"
    path.write_text("Some thoughts about a future product.\n")
    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(path)
    assert error.value.code == "INCONCLUSIVE_INPUT"


def _manifest(document: str = "requirements.txt"):
    return {
        "schema_version": 1,
        "bundle_id": "payments",
        "documents": [{"id": "rules", "path": document, "media_type": "text/plain"}],
        "units": [{
            "id": "PAYMENT-RETRY",
            "kind": "rule",
            "text": "Payment retries stop after three attempts.",
            "normative_level": "must",
            "source_refs": [{
                "document_id": "rules", "locator_kind": "line-range", "locator": "L1-L1",
            }],
        }],
        "glossary": [],
    }


def test_manifest_accepts_non_echelon_unit_ids(tmp_path):
    document = tmp_path / "requirements.txt"
    document.write_text("Payment retries stop after three attempts.\n")
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps(_manifest()))
    bundle = source.load_source_bundle(manifest, "manifest")
    assert bundle.units[0].id == "PAYMENT-RETRY"


@pytest.mark.parametrize("change", [
    lambda data: data["documents"][0].update(path="../outside.txt"),
    lambda data: data["units"][0].update(text="Different text."),
    lambda data: data["documents"][0].update(digest="0" * 64),
    lambda data: data["units"][0]["source_refs"][0].update(document_id="missing"),
    lambda data: data["units"][0].update(declared_relations=[{
        "predicate": "depends-on", "target_unit_id": "missing", "source_refs": [],
    }]),
    lambda data: data.update(glossary=[
        {"canonical": "first", "aliases": ["shared"], "source_refs": []},
        {"canonical": "second", "aliases": ["shared"], "source_refs": []},
    ]),
])
def test_manifest_rejects_invalid_provenance_or_ambiguous_aliases(tmp_path, change):
    document = tmp_path / "requirements.txt"
    document.write_text("Payment retries stop after three attempts.\n")
    data = _manifest()
    change(data)
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(source.SUESourceError):
        source.load_source_bundle(manifest, "manifest")
