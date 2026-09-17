from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_inventory_snapshot_does_not_infer_element_ids_from_source_strings():
    import json
    from harness.evidence_inventory import validate_evidence_inventory_text

    locator = "https://example.test/AC-1000000"
    text = json.dumps({
        "schema_version": 1,
        "sources": [{"id": "U-000001", "locator": locator, "kind": "web",
                     "status": "read", "disposition": "relevant",
                     "discovered_from": "prompt", "discovery_method": "seed"}],
        "frontier": {"disposition": "complete", "unvisited_relevant_sources": [],
                     "expanded_seed_locators": [locator]},
    })
    assert validate_evidence_inventory_text(text, required_seed_locators=(locator,)) is None
    assert validate_evidence_inventory_text(text, required_seed_locators=("missing",)) == (
        "missing declared source seed(s): missing")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SOURCE = """# Feature specification

- **FR-1000000**: Preserve source_metric at 1 unit.
- **AC-2000000**: Given a request, when processed, then the metric is visible.
- **ERROR-3000000**: If processing fails, return E300.
"""


def _derived(
    *,
    source: str = SOURCE,
    source_name: str = "spec.md",
    source_sha: str | None = None,
    term: str = "source_metric",
) -> str:
    digest = _sha256(source) if source_sha is None else source_sha
    return f"""# SOURCE: {source_name}
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Snapshot validation

REQ: FR-1000000
GIVEN: a request includes {term}
WHEN: the system processes the request
THEN: the system MUST preserve {term}
OUTPUT: preserved {term}
CONSTRAINT: {term} = 1 unit
EXAMPLE: AC-2000000

AC: AC-2000000
GIVEN: a request includes {term}
WHEN: the system processes the request
THEN: the result exposes {term}

ERROR: ERROR-3000000
WHEN: processing fails
THEN: the system returns an error
ERROR_CODE: E300
"""


def _finding_codes(report: dict[str, object]) -> list[str]:
    return [str(item["code"]) for item in report["findings"]]  # type: ignore[index]


@pytest.mark.unit
def test_lexicon_snapshot_success_has_only_immutable_report_fields() -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    derived = _derived()
    report = validate_spec_lexicon_texts(
        derived_text=derived,
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )

    assert report == {
        "schema_version": 1,
        "artifact_type": "SPEC",
        "artifact_sha256": _sha256(derived),
        "source_sha256": _sha256(SOURCE),
        "glossary_sha256": None,
        "ok": True,
        "findings": [],
    }


@pytest.mark.unit
def test_lexicon_snapshot_rejects_stale_source_hash() -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    report = validate_spec_lexicon_texts(
        derived_text=_derived(source_sha="0" * 64),
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )

    assert "source-hash-mismatch" in _finding_codes(report)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "expected_code", "expected_span", "expected_line"),
    [
        ("missing-source", "source-metadata-missing", "SOURCE", 1),
        ("missing-hash", "source-metadata-missing", "SOURCE_SHA256", 1),
        ("wrong-source", "source-ref-mismatch", "other.md", 1),
    ],
)
def test_lexicon_snapshot_checks_source_metadata(
    case: str,
    expected_code: str,
    expected_span: str,
    expected_line: int,
) -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    derived = _derived()
    if case == "missing-source":
        derived = derived.replace("# SOURCE: spec.md\n", "")
    elif case == "missing-hash":
        derived = derived.replace(f"# SOURCE_SHA256: {_sha256(SOURCE)}\n", "")
    else:
        derived = derived.replace("# SOURCE: spec.md\n", "# SOURCE: other.md\n")

    report = validate_spec_lexicon_texts(
        derived_text=derived,
        source_text=SOURCE,
        source_name="folder/spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )

    finding = next(item for item in report["findings"] if item["code"] == expected_code)
    assert finding["span"] == expected_span
    assert finding["line"] == expected_line


@pytest.mark.unit
@pytest.mark.parametrize(
    ("derived", "source", "expected"),
    [
        (
            _derived().replace("FR-1000000", "FR-1000001"),
            SOURCE,
            [
                ("source-id-extra", "FR-1000001"),
                ("source-id-missing", "FR-1000000"),
            ],
        ),
        (
            _derived().replace("AC-2000000", "AC-2000001"),
            SOURCE,
            [
                ("source-id-extra", "AC-2000001"),
                ("source-id-missing", "AC-2000000"),
            ],
        ),
        (
            _derived().replace("ERROR-3000000", "ERR-3000000"),
            SOURCE,
            [
                ("source-id-extra", "ERR-3000000"),
                ("source-id-missing", "ERROR-3000000"),
            ],
        ),
    ],
)
def test_lexicon_snapshot_preserves_fr_ac_and_legacy_error_family_ids(
    derived: str,
    source: str,
    expected: list[tuple[str, str]],
) -> None:
    from lexicon.source_contract import source_contract_findings_text

    findings = source_contract_findings_text(
        derived,
        source_text=source,
        source_name="spec.md",
    )

    assert [(item.code, item.span) for item in findings] == expected


@pytest.mark.unit
def test_invalid_grammar_does_not_add_false_source_id_diff_noise() -> None:
    from lexicon.source_contract import source_contract_findings_text

    invalid = _derived().replace("THEN: the system MUST preserve source_metric\n", "")

    assert source_contract_findings_text(
        invalid,
        source_text=SOURCE,
        source_name="spec.md",
    ) == []


@pytest.mark.unit
def test_source_owned_measurable_terms_are_approved_but_unknown_terms_are_not() -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts
    from lexicon.source_contract import source_approved_terms_text

    assert source_approved_terms_text(SOURCE) == {"source_metric"}
    approved = validate_spec_lexicon_texts(
        derived_text=_derived(),
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )
    unknown = validate_spec_lexicon_texts(
        derived_text=_derived(term="unknown_metric"),
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )

    assert approved["ok"] is True
    assert any(
        item["code"] == "unresolved-term" and item["span"] == "unknown_metric"
        for item in unknown["findings"]
    )


@pytest.mark.unit
def test_glossary_text_parses_heading_bold_and_plain_line_terms() -> None:
    from lexicon.glossary import parse_glossary_terms

    text = """# Glossary
### `heading_term` (qualified heading)
Paragraph with **bold_term** and **second_term**.
plain_term
"""

    assert parse_glossary_terms(text) == {
        "heading_term",
        "bold_term",
        "second_term",
        "plain_term",
    }


@pytest.mark.unit
def test_absent_and_empty_glossary_have_distinct_snapshot_digests() -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    absent = validate_spec_lexicon_texts(
        derived_text=_derived(),
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )
    empty = validate_spec_lexicon_texts(
        derived_text=_derived(),
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text="",
        artifact_type="SPEC",
    )

    assert absent["glossary_sha256"] is None
    assert empty["glossary_sha256"] == _sha256("")
    assert absent["findings"] == empty["findings"] == []


@pytest.mark.unit
def test_exact_crlf_unicode_snapshots_are_hashed_and_source_matched() -> None:
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    source = SOURCE.replace("Feature", "Café Δ feature").replace("\n", "\r\n")
    derived = _derived(source=source).replace(
        "Snapshot validation", "Café Δ snapshot"
    ).replace("\n", "\r\n")
    report = validate_spec_lexicon_texts(
        derived_text=derived,
        source_text=source,
        source_name="not/opened/spec.md",
        glossary_text="glossary_term\r\n",
        artifact_type="SPEC",
    )

    assert report["ok"] is True
    assert report["artifact_sha256"] == _sha256(derived)
    assert report["source_sha256"] == _sha256(source)
    assert report["glossary_sha256"] == _sha256("glossary_term\r\n")


def _valid_inventory() -> dict[str, object]:
    locator = "https://example.test/root"
    return {
        "schema_version": 1,
        "sources": [
            {
                "id": "SRC-001",
                "locator": locator,
                "kind": "web",
                "status": "read",
                "disposition": "relevant",
                "discovered_from": "prompt",
                "discovery_method": "seed",
            }
        ],
        "frontier": {
            "disposition": "complete",
            "unvisited_relevant_sources": [],
            "expanded_seed_locators": [locator],
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{", "not valid JSON: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"),
        (json.dumps([]), "root must be an object"),
        (json.dumps({"schema_version": 2}), "schema_version must equal 1"),
        (
            json.dumps({"schema_version": 1, "sources": {}}),
            "missing required list: sources",
        ),
        (
            json.dumps({"schema_version": 1, "sources": []}),
            "sources must not be empty",
        ),
    ],
)
def test_inventory_snapshot_validates_json_root_version_and_sources(
    text: str,
    expected: str,
) -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    assert validate_evidence_inventory_text(text) == expected


@pytest.mark.unit
def test_inventory_snapshot_reports_source_item_shape_before_frontier() -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    payload = _valid_inventory()
    payload["sources"] = ["not-an-object"]
    payload.pop("frontier")

    assert validate_evidence_inventory_text(json.dumps(payload)) == (
        "sources[0] must be an object"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    [
        "id",
        "locator",
        "kind",
        "status",
        "disposition",
        "discovered_from",
        "discovery_method",
    ],
)
def test_inventory_snapshot_requires_each_source_string(field: str) -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    payload = _valid_inventory()
    payload["sources"][0][field] = " "  # type: ignore[index]

    assert validate_evidence_inventory_text(json.dumps(payload)) == (
        f"sources[0].{field} must be a non-empty string"
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("missing-frontier", "missing required object: frontier"),
        ("bad-disposition", "frontier.disposition must be a non-empty string"),
        (
            "bad-unvisited",
            "frontier.unvisited_relevant_sources must be a list of non-empty strings",
        ),
        (
            "bad-expanded",
            "frontier.expanded_seed_locators must be a list of non-empty strings",
        ),
    ],
)
def test_inventory_snapshot_validates_frontier(
    mutation: str,
    expected: str,
) -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    payload = _valid_inventory()
    if mutation == "missing-frontier":
        payload.pop("frontier")
    elif mutation == "bad-disposition":
        payload["frontier"]["disposition"] = ""  # type: ignore[index]
    elif mutation == "bad-unvisited":
        payload["frontier"]["unvisited_relevant_sources"] = [""]  # type: ignore[index]
    else:
        payload["frontier"]["expanded_seed_locators"] = [1]  # type: ignore[index]

    assert validate_evidence_inventory_text(json.dumps(payload)) == expected


@pytest.mark.unit
def test_inventory_snapshot_orders_missing_inventory_seed_before_missing_expansion() -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    text = json.dumps(_valid_inventory())

    assert validate_evidence_inventory_text(
        text,
        required_seed_locators=("missing-one", "missing-two"),
    ) == "missing declared source seed(s): missing-one, missing-two"


@pytest.mark.unit
def test_inventory_snapshot_requires_declared_seeds_in_expanded_frontier() -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text

    payload = _valid_inventory()
    payload["frontier"]["expanded_seed_locators"] = []  # type: ignore[index]

    assert validate_evidence_inventory_text(
        json.dumps(payload),
        required_seed_locators=("https://example.test/root",),
    ) == (
        "frontier does not account for declared source seed(s): "
        "https://example.test/root"
    )


@pytest.mark.unit
def test_inventory_path_wrapper_matches_text_validation_for_equivalent_lf_input(
    tmp_path: Path,
) -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text
    from harness.squad_executors import _validate_evidence_inventory

    path = tmp_path / "evidence-inventory.json"
    text = json.dumps(_valid_inventory(), indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="")

    assert _validate_evidence_inventory(path) == validate_evidence_inventory_text(text)
    assert _validate_evidence_inventory(tmp_path / "missing.json").startswith(
        "not valid JSON:"
    )


@pytest.mark.unit
def test_pure_snapshot_apis_do_not_access_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.evidence_inventory import validate_evidence_inventory_text
    from harness.spec_lexicon_gate import validate_spec_lexicon_texts

    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pure snapshot API accessed the filesystem")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    monkeypatch.setattr(Path, "write_text", fail)
    monkeypatch.setattr(Path, "write_bytes", fail)
    monkeypatch.setattr(Path, "is_file", fail)

    assert validate_evidence_inventory_text(json.dumps(_valid_inventory())) is None
    assert validate_spec_lexicon_texts(
        derived_text=_derived(),
        source_text=SOURCE,
        source_name="could/be/a/real/spec.md",
        glossary_text=None,
        artifact_type="SPEC",
    )["ok"] is True


@pytest.mark.unit
def test_legacy_path_gate_matches_lf_rules_and_preserves_raw_crlf_digests(
    tmp_path: Path,
) -> None:
    from harness.spec_lexicon_gate import (
        _validate_spec_lexicon_artifacts,
        validate_spec_lexicon_texts,
    )

    derived_path = tmp_path / "requirements.lexicon.md"
    source_path = tmp_path / "spec.md"
    glossary_path = tmp_path / "glossary.md"
    lf_derived = _derived()
    source_path.write_text(SOURCE, encoding="utf-8", newline="")
    derived_path.write_text(lf_derived, encoding="utf-8", newline="")
    glossary_path.write_text("", encoding="utf-8", newline="")

    path_report = _validate_spec_lexicon_artifacts(
        derived_path=derived_path,
        source_path=source_path,
        glossary_path=glossary_path,
        artifact_type="SPEC",
    )
    pure_report = validate_spec_lexicon_texts(
        derived_text=lf_derived,
        source_text=SOURCE,
        source_name="spec.md",
        glossary_text="",
        artifact_type="SPEC",
    )
    assert {
        key: value
        for key, value in path_report.items()
        if not key.endswith("_path")
    } == pure_report

    crlf_source = SOURCE.replace("\n", "\r\n")
    crlf_derived = _derived(source=SOURCE).replace("\n", "\r\n")
    source_path.write_bytes(crlf_source.encode("utf-8"))
    derived_path.write_bytes(crlf_derived.encode("utf-8"))
    crlf_report = _validate_spec_lexicon_artifacts(
        derived_path=derived_path,
        source_path=source_path,
        glossary_path=glossary_path,
        artifact_type="SPEC",
    )

    assert crlf_report["ok"] is True
    assert crlf_report["artifact_sha256"] == _sha256(crlf_derived)
    assert crlf_report["source_sha256"] == _sha256(crlf_source)
