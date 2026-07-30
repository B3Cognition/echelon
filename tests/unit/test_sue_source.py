"""Unit tests for immutable SUE source-bundle primitives."""
from __future__ import annotations

import importlib.util
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
