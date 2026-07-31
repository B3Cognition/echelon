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
    first_line = text.splitlines()[0]
    return source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(text),),
        units=(
            source.SourceUnit(
                id="FR-001",
                kind="requirement",
                text=first_line,
                normative_level=(
                    "must" if "MUST" in first_line else "unspecified"
                ),
                source_refs=(
                    source.SourceRef(
                        "requirements", "line-range", "L1-L1"
                    ),
                ),
                declared_relations=(),
                situation=None,
            ),
        ),
    )


def _bundle_with_declared_dependency(source_unit_id: str, target_unit_id: str):
    document = _document("Payment retry depends on payment limit.\n")
    relation = source.DeclaredRelation(
        "depends-on",
        target_unit_id,
        (source.SourceRef("requirements", "line-range", "L1-L1"),),
    )
    return source.make_bundle(
        bundle_id="payments",
        adapter_id="manifest",
        documents=(document,),
        units=(
            source.SourceUnit(
                id=source_unit_id,
                kind="rule",
                text="Payment retry depends on payment limit.",
                normative_level="must",
                source_refs=(source.SourceRef("requirements", "line-range", "L1-L1"),),
                declared_relations=(relation,),
                situation=None,
            ),
            source.SourceUnit(
                id=target_unit_id,
                kind="rule",
                text="Payment retry depends on payment limit.",
                normative_level="must",
                source_refs=(source.SourceRef("requirements", "line-range", "L1-L1"),),
                declared_relations=(),
                situation=None,
            ),
        ),
    )


def _bundle_with_glossary(canonical: str, aliases: tuple[str, ...]):
    return source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(),
        glossary=(
            source.GlossaryTerm(
                canonical,
                aliases,
                (source.SourceRef("requirements", "line-range", "L1-L1"),),
            ),
        ),
    )


def _bundle_with_two_terms_sharing_alias(alias: str):
    return source.make_bundle(
        bundle_id="checkout",
        adapter_id="manifest",
        documents=(_document(),),
        units=(),
        glossary=(
            source.GlossaryTerm(
                "audit record",
                (alias,),
                (source.SourceRef("requirements", "line-range", "L1-L1"),),
            ),
            source.GlossaryTerm(
                "payment record",
                (alias,),
                (source.SourceRef("requirements", "line-range", "L1-L1"),),
            ),
        ),
    )


def test_source_map_contains_only_declared_relations():
    bundle = _bundle_with_declared_dependency("PAYMENT-RETRY", "PAYMENT-LIMIT")
    knowledge = source.build_source_knowledge_map(bundle)
    assert tuple(knowledge.units_by_id) == ("PAYMENT-LIMIT", "PAYMENT-RETRY")
    assert knowledge.outgoing["PAYMENT-RETRY"][0].target_unit_id == "PAYMENT-LIMIT"
    assert knowledge.outgoing["PAYMENT-LIMIT"] == ()


def test_unambiguous_declared_alias_canonicalizes():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_glossary("customer", ("user", "account holder"))
    )
    assert source.canonical_glossary_match(knowledge, "users") == "customer"


def test_article_and_plural_canonical_term_canonicalizes():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_glossary("payment policy", ())
    )
    assert source.canonical_glossary_match(knowledge, "the payment policies") == "payment policy"


def test_ambiguous_alias_remains_unmatched():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_two_terms_sharing_alias("record")
    )
    assert source.canonical_glossary_match(knowledge, "record") is None


def test_source_map_indexes_are_immutable():
    knowledge = source.build_source_knowledge_map(
        _bundle_with_declared_dependency("PAYMENT-RETRY", "PAYMENT-LIMIT")
    )

    with pytest.raises(TypeError):
        knowledge.units_by_id["INFERRED-UNIT"] = _unit("INFERRED-UNIT")
    with pytest.raises(TypeError):
        knowledge.outgoing["PAYMENT-RETRY"] = ()
    with pytest.raises(TypeError):
        knowledge.glossary_by_alias["inferred"] = ("inferred",)


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
            units=(
                source.SourceUnit(
                    id="FR-001",
                    kind="requirement",
                    text="The system MUST save.",
                    normative_level="must",
                    source_refs=(
                        source.SourceRef("requirements", "line-range", locator),
                    ),
                    declared_relations=(),
                    situation=None,
                ),
            ),
        )


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
    assert bundle.units[0].text == "- **FR-001**: The system MUST save."
    assert bundle.units[0].source_refs[0].locator == "L3-L3"


def test_markdown_adapter_preserves_compound_and_dotted_ids_without_colons(
        tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text(
        "- **AC-1.1** First criterion.\n"
        "- **FR-EL-001** Event log MUST render.\n"
        "- **NFR-COMPAT-002** Existing data MUST load.\n"
    )

    bundle = source.load_source_bundle(path)

    assert [unit.id for unit in bundle.units] == [
        "AC-1.1",
        "FR-EL-001",
        "NFR-COMPAT-002",
    ]
    assert [unit.source_refs[0].locator for unit in bundle.units] == [
        "L1-L1",
        "L2-L2",
        "L3-L3",
    ]
    assert not any(unit.id.startswith("requirements:L") for unit in bundle.units)


def test_markdown_explicit_unit_owns_nested_body_and_its_provenance(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text(
        "- **FR-AUTH-001** Authorization rules:\n"
        "  - create MUST reject foreign fields\n"
        "  - update MUST preserve owned fields\n"
        "- **FR-AUTH-002** Failure MUST be reported.\n"
    )

    bundle = source.load_source_bundle(path)

    assert [unit.id for unit in bundle.units] == [
        "FR-AUTH-001",
        "FR-AUTH-002",
    ]
    assert bundle.units[0].source_refs[0].locator == "L1-L3"
    assert bundle.units[0].text == (
        "- **FR-AUTH-001** Authorization rules:\n"
        "  - create MUST reject foreign fields\n"
        "  - update MUST preserve owned fields"
    )
    assert bundle.units[0].text == source.resolve_source_ref(
        bundle, bundle.units[0].source_refs[0]
    )


def test_markdown_adapter_rejects_marked_id_it_cannot_preserve(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("- **FR-AUTH/001** The request MUST be authorized.\n")

    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(path)

    assert error.value.code == "UNSUPPORTED_UNIT_ID"
    assert "FR-AUTH/001" in error.value.message


def test_markdown_adapter_unit_text_round_trips_to_source_ref(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# Requirements\n\n- **FR-001**: The system MUST save.\n")
    bundle = source.load_source_bundle(path)
    unit = bundle.units[0]
    assert unit.text == source.resolve_source_ref(bundle, unit.source_refs[0])


def test_markdown_adapter_recognizes_requirement_heading(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# FR-002: The system SHALL retain audit history.\n")
    bundle = source.load_source_bundle(path)
    assert bundle.units[0].id == "FR-002"
    assert bundle.units[0].normative_level == "must"


def test_markdown_adapter_recognizes_requirement_heading_without_colon(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# FR-002\nThe system SHALL retain audit history.\n")
    bundle = source.load_source_bundle(path)
    assert bundle.units[0].id == "FR-002"
    assert bundle.units[0].text == "# FR-002\nThe system SHALL retain audit history."
    assert bundle.units[0].source_refs[0].locator == "L1-L2"
    assert bundle.units[0].normative_level == "must"


def test_markdown_adapter_recognizes_requirement_heading_with_title(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# FR-002 Retain audit history\n")
    bundle = source.load_source_bundle(path)
    unit = bundle.units[0]
    assert unit.id == "FR-002"
    assert unit.text == source.resolve_source_ref(bundle, unit.source_refs[0])


def test_markdown_heading_sections_end_before_adjacent_requirement(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text(
        "# FR-001 Save records\n"
        "The system MUST save each record.\n"
        "# FR-002 Delete records\n"
        "The system SHOULD delete expired records.\n"
    )
    bundle = source.load_source_bundle(path)
    assert [unit.id for unit in bundle.units] == ["FR-001", "FR-002"]
    assert [ref.locator for unit in bundle.units for ref in unit.source_refs] == [
        "L1-L2",
        "L3-L4",
    ]
    assert bundle.units[0].text == (
        "# FR-001 Save records\nThe system MUST save each record."
    )
    assert bundle.units[1].normative_level == "should"


def test_markdown_heading_body_preserves_crlf(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_bytes(
        b"# FR-001 Save records\r\n"
        b"The system MUST save each record.\r\n"
        b"# FR-002 Delete records\r\n"
        b"The system MAY delete expired records.\r\n"
    )
    bundle = source.load_source_bundle(path)
    unit = bundle.units[0]
    assert unit.text == "# FR-001 Save records\r\nThe system MUST save each record."
    assert unit.text == source.resolve_source_ref(bundle, unit.source_refs[0])


def test_id_only_heading_is_inconclusive(tmp_path):
    path = tmp_path / "requirements.md"
    path.write_text("# FR-001\n")
    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(path)
    assert error.value.code == "INCONCLUSIVE_INPUT"


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


def test_lexicon_adapter_preserves_crlf_source_ref_round_trip(tmp_path):
    path = tmp_path / "rules.lex"
    path.write_bytes(
        b"REQ: REQ-001\r\n"
        b"GIVEN: an authenticated user\r\n"
        b"WHEN: the user saves\r\n"
        b"THEN: the record persists\r\n"
    )
    bundle = source.load_source_bundle(path)
    unit = bundle.units[0]
    assert unit.text == source.resolve_source_ref(bundle, unit.source_refs[0])
    assert "\r\n" in unit.text


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


@pytest.mark.parametrize("source_refs", (None, []))
def test_manifest_rejects_ungrounded_unit(tmp_path, source_refs):
    document = tmp_path / "requirements.txt"
    document.write_text("Payment retries stop after three attempts.\n")
    data = _manifest()
    if source_refs is None:
        data["units"][0].pop("source_refs")
    else:
        data["units"][0]["source_refs"] = source_refs
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(manifest, "manifest")
    assert error.value.code == "UNGROUNDED_UNIT"


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


@pytest.mark.parametrize("schema_version", (0, 2, "1", True))
def test_make_bundle_rejects_non_v1_schema(schema_version):
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(_unit(),),
            schema_version=schema_version,
        )
    assert error.value.code == "UNSUPPORTED_SCHEMA"


@pytest.mark.parametrize(
    ("field", "value"),
    (("documents", {}), ("units", {}), ("glossary", {})),
)
def test_manifest_rejects_non_list_collections(tmp_path, field, value):
    document = tmp_path / "requirements.txt"
    document.write_text("Payment retries stop after three attempts.\n")
    data = _manifest()
    data[field] = value
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(source.SUESourceError) as error:
        source.load_source_bundle(manifest, "manifest")
    assert error.value.code == "INVALID_MANIFEST"


def test_make_bundle_rejects_invalid_document_media_type():
    document = source.SourceDocument.from_text(
        id="requirements",
        source_uri="requirements.md",
        media_type="markdown",
        text="The system MUST save.\n",
    )
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(document,),
            units=(_unit(),),
        )
    assert error.value.code == "INVALID_MEDIA_TYPE"


@pytest.mark.parametrize(
    ("change", "code"),
    (
        ({"kind": "story"}, "INVALID_UNIT_KIND"),
        ({"kind": []}, "INVALID_UNIT_KIND"),
        ({"normative_level": "shall"}, "INVALID_NORMATIVE_LEVEL"),
        ({"normative_level": []}, "INVALID_NORMATIVE_LEVEL"),
        (
            {"situation": source.ControlledSituation("user", 7, "saved")},
            "INVALID_SITUATION",
        ),
    ),
)
def test_make_bundle_rejects_invalid_unit_contract(change, code):
    fields = {
        "id": "FR-001",
        "kind": "requirement",
        "text": "The system MUST save.",
        "normative_level": "must",
        "source_refs": (
            source.SourceRef("requirements", "line-range", "L1-L1"),
        ),
        "declared_relations": (),
        "situation": None,
    }
    fields.update(change)
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(source.SourceUnit(**fields),),
        )
    assert error.value.code == code


def test_make_bundle_rejects_ungrounded_unit():
    unit = source.SourceUnit(
        id="FR-001",
        kind="requirement",
        text="The system MUST save.",
        normative_level="must",
        source_refs=(),
        declared_relations=(),
        situation=None,
    )
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(unit,),
        )
    assert error.value.code == "UNGROUNDED_UNIT"


def test_make_bundle_rejects_unresolved_relation_target():
    relation = source.DeclaredRelation(
        "depends-on",
        "FR-MISSING",
        (source.SourceRef("requirements", "line-range", "L1-L1"),),
    )
    unit = source.SourceUnit(
        id="FR-001",
        kind="requirement",
        text="The system MUST save.",
        normative_level="must",
        source_refs=(source.SourceRef("requirements", "line-range", "L1-L1"),),
        declared_relations=(relation,),
        situation=None,
    )
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(unit,),
        )
    assert error.value.code == "UNRESOLVED_TARGET"


def _json_bundle(text: str):
    document = source.SourceDocument.from_text(
        id="rules",
        source_uri="rules.json",
        media_type="application/json",
        text=text,
    )
    return source.make_bundle(
        bundle_id="rules",
        adapter_id="manifest",
        documents=(document,),
        units=(),
    )


def test_json_pointer_resolves_escaped_tokens_and_array_index():
    bundle = _json_bundle(
        '{"requirements":{"save/record":{"~label":[{"text":"Save exactly."}]}}}'
    )
    ref = source.SourceRef(
        "rules",
        "json-pointer",
        "/requirements/save~1record/~0label/0/text",
    )
    assert source.resolve_source_ref(bundle, ref) == "Save exactly."


@pytest.mark.parametrize(
    ("document_text", "expected"),
    (
        ('{"value":"exact text"}', "exact text"),
        ('{"value":true}', "true"),
        ('{"value":null}', "null"),
        ('{"value":42}', "42"),
    ),
)
def test_json_pointer_uses_string_value_or_canonical_scalar_text(
    document_text, expected
):
    bundle = _json_bundle(document_text)
    ref = source.SourceRef("rules", "json-pointer", "/value")
    assert source.resolve_source_ref(bundle, ref) == expected


@pytest.mark.parametrize(
    ("locator", "code"),
    (
        ("/items/01", "INVALID_LOCATOR"),
        ("/items/x", "INVALID_LOCATOR"),
        ("/items/2", "INVALID_LOCATOR"),
        ("/bad~2escape", "INVALID_LOCATOR"),
        ("/items/0", "NON_SCALAR_LOCATOR"),
    ),
)
def test_json_pointer_rejects_invalid_path_or_non_scalar(locator, code):
    bundle = _json_bundle('{"items":[{"text":"one"}]}')
    with pytest.raises(source.SUESourceError) as error:
        source.resolve_source_ref(
            bundle, source.SourceRef("rules", "json-pointer", locator)
        )
    assert error.value.code == code


def test_manifest_json_pointer_text_must_match_resolved_scalar(tmp_path):
    document = tmp_path / "requirements.json"
    document.write_text('{"rules":{"retry":"Stop after three attempts."}}')
    data = _manifest("requirements.json")
    data["documents"][0]["media_type"] = "application/json"
    data["units"][0]["text"] = "Stop after three attempts."
    data["units"][0]["source_refs"][0] = {
        "document_id": "rules",
        "locator_kind": "json-pointer",
        "locator": "/rules/retry",
    }
    manifest = tmp_path / "requirements.sue.json"
    manifest.write_text(json.dumps(data))
    bundle = source.load_source_bundle(manifest, "manifest")
    assert bundle.units[0].text == "Stop after three attempts."


@pytest.mark.parametrize("locator_kind", ("xml-id", "page-paragraph"))
def test_make_bundle_rejects_advertised_but_unsupported_locator(locator_kind):
    unit = source.SourceUnit(
        id="FR-001",
        kind="requirement",
        text="The system MUST save.",
        normative_level="must",
        source_refs=(
            source.SourceRef("requirements", locator_kind, "requirement-1"),
        ),
        declared_relations=(),
        situation=None,
    )
    with pytest.raises(source.SUESourceError) as error:
        source.make_bundle(
            bundle_id="checkout",
            adapter_id="manifest",
            documents=(_document(),),
            units=(unit,),
        )
    assert error.value.code == "UNSUPPORTED_LOCATOR"
