"""Compatibility tests for captured graph-source text parsers."""

from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
from unittest.mock import patch

import harness.canonical_requirements as requirements
import harness.deferred_scope as deferred_scope
import harness.verified_fulfillment_ledger as verified_ledger
import pytest


class _TextSubclass(str):
    pass


def test_requirement_capture_survives_later_file_change(tmp_path):
    path = tmp_path / "spec.md"
    text = "- **FR-000001**: Keep the scene.\r\n"
    path.write_bytes(text.encode("utf-8"))
    expected = [
        requirements.CanonicalRequirement(
            "FR-000001",
            "spec",
            "spec.md",
            1,
            "- **FR-000001**: Keep the scene.",
        )
    ]
    assert requirements.extract_canonical_requirements(tmp_path) == expected
    captured = path.read_bytes().decode("utf-8")
    path.write_text("- **FR-000002**: Different scene.\n", encoding="utf-8")

    assert (
        requirements.extract_canonical_requirements_from_texts(spec_text=captured)
        == expected
    )


def test_deferred_scope_capture_survives_later_file_change(tmp_path):
    path = tmp_path / deferred_scope.LEDGER_FILENAME
    text = (
        '{"schema_version":1,"entries":[{"entry_id":"defer-001",'
        '"status":"deferred","selected_ids":["FR-000001"],'
        '"derived_task_ids":["T-000001"],'
        '"prior_task_statuses":{"T-000001":"pending"},'
        '"reason":"Owner decision","deferred_at":"2026-09-13T08:00:00+00:00",'
        '"planned_at":null}]}'
    )
    path.write_text(text, encoding="utf-8")
    expected = deferred_scope.DeferredScopeLedger(
        entries=(
            deferred_scope.DeferredScopeEntry(
                entry_id="defer-001",
                status="deferred",
                selected_ids=("FR-000001",),
                derived_task_ids=("T-000001",),
                prior_task_statuses=(("T-000001", "PENDING"),),
                reason="Owner decision",
                deferred_at="2026-09-13T08:00:00+00:00",
                planned_at=None,
            ),
        )
    )
    assert deferred_scope.read_ledger(tmp_path) == expected
    captured = path.read_text(encoding="utf-8")
    path.write_text('{"schema_version":1,"entries":[]}', encoding="utf-8")

    assert deferred_scope.parse_deferred_scope_ledger(captured) == expected


def test_verified_ledger_capture_survives_later_file_change(tmp_path):
    path = tmp_path / "verified-fulfillment-ledger.json"
    text = (
        '{"schema_version":2,"rows":[{"requirement_id":"FR-000001",'
        '"status":"implemented","evidence_refs":["src/scene.py"],'
        '"verified_commit":"abc123","verified_at":"2026-09-13T08:00:00+00:00",'
        '"spec_input_hash":"spec-a","implementation_input_hash":"impl-a",'
        '"artifact_hashes":{"src/scene.py":"artifact-a"},'
        '"verifier_version":"verify-v2","verify_scope":"full",'
        '"source_report_path":"runs/verify/fulfillment-report.md",'
        '"receipt_refs":[{"path":"runs/verify/receipt.json",'
        '"receipt_sha256":"receipt-a","evidence_sha256":"evidence-a"}],'
        '"candidate_content_fingerprint":"candidate-a","contract_hash":"contract-a",'
        '"requirement_set_fingerprint":"requirements-a",'
        '"selected_evidence":["src/scene.py"]}]}'
    )
    path.write_text(text, encoding="utf-8")
    expected = verified_ledger.VerifiedFulfillmentLedger(
        rows=(
            verified_ledger.VerifiedLedgerRow(
                requirement_id="FR-000001",
                status="IMPLEMENTED",
                evidence_refs=("src/scene.py",),
                verified_commit="abc123",
                verified_at="2026-09-13T08:00:00+00:00",
                spec_input_hash="spec-a",
                implementation_input_hash="impl-a",
                artifact_hashes={"src/scene.py": "artifact-a"},
                verifier_version="verify-v2",
                verify_scope="full",
                source_report_path="runs/verify/fulfillment-report.md",
                receipt_refs=(
                    {
                        "path": "runs/verify/receipt.json",
                        "receipt_sha256": "receipt-a",
                        "evidence_sha256": "evidence-a",
                    },
                ),
                candidate_content_fingerprint="candidate-a",
                contract_hash="contract-a",
                requirement_set_fingerprint="requirements-a",
                selected_evidence=("src/scene.py",),
            ),
        )
    )
    assert verified_ledger.read_verified_ledger(path) == expected
    captured = path.read_text(encoding="utf-8")
    path.write_text('{"schema_version":2,"rows":[]}', encoding="utf-8")

    assert verified_ledger.parse_verified_ledger(captured) == expected


def test_requirement_texts_preserve_all_sources_precedence_and_legacy_ids(
    tmp_path,
):
    very_wide_id = "FR-" + "9" * 5000
    spec_text = (
        "Reference FR-1000000 and FR-999999.\r\n"
        "- **AC-000001**: Café naïve.\r\n"
        "Range endpoints FR-001..FR-006 stay visible.\r\n"
        "- **FR-016b**: Suffixed legacy requirement.\r\n"
        "- **EDGE-LEGACY**: Historical edge family.\r\n"
    )
    plan_text = (
        "# Plan\n"
        "- **FR-1000000**: Explicit million definition.\n"
        "Composite REQ-ALPHA:2_BETA remains observable.\n"
        "- **US-LEGACY**: Historical story family.\n"
    )
    coverage_text = (
        "- **FR-999999**: Coverage supplies the explicit definition.\n"
        "References FR-10000000 and FR-999999.\n"
        "- **NFR-LEGACY**: Historical quality family.\n"
    )
    tasks_text = (
        f"- [ ] T-1 req=FR-10000000,UNMAPPED,NOPE-1,{very_wide_id} depends=none\n"
        "- [ ] T-2 req=AC-000001,FR-000001,SC-HIST.2 depends=none\n"
    )
    expected = [
        requirements.CanonicalRequirement(
            "AC-000001", "spec", "spec.md", 2, "- **AC-000001**: Café naïve."
        ),
        requirements.CanonicalRequirement(
            "EDGE-LEGACY",
            "spec",
            "spec.md",
            5,
            "- **EDGE-LEGACY**: Historical edge family.",
        ),
        requirements.CanonicalRequirement(
            "FR-000001",
            "task_metadata",
            "tasks.md",
            2,
            "- [ ] T-2 req=AC-000001,FR-000001,SC-HIST.2 depends=none",
        ),
        requirements.CanonicalRequirement(
            "FR-001",
            "spec",
            "spec.md",
            3,
            "Range endpoints FR-001..FR-006 stay visible.",
        ),
        requirements.CanonicalRequirement(
            "FR-006",
            "spec",
            "spec.md",
            3,
            "Range endpoints FR-001..FR-006 stay visible.",
        ),
        requirements.CanonicalRequirement(
            "FR-999999",
            "coverage",
            "coverage-map.md",
            1,
            "- **FR-999999**: Coverage supplies the explicit definition.",
        ),
        requirements.CanonicalRequirement(
            "FR-1000000",
            "plan",
            "plan.md",
            2,
            "- **FR-1000000**: Explicit million definition.",
        ),
        requirements.CanonicalRequirement(
            "FR-10000000",
            "coverage",
            "coverage-map.md",
            2,
            "References FR-10000000 and FR-999999.",
        ),
        requirements.CanonicalRequirement(
            very_wide_id,
            "task_metadata",
            "tasks.md",
            1,
            f"- [ ] T-1 req=FR-10000000,UNMAPPED,NOPE-1,{very_wide_id} depends=none",
        ),
        requirements.CanonicalRequirement(
            "FR-016b",
            "spec",
            "spec.md",
            4,
            "- **FR-016b**: Suffixed legacy requirement.",
        ),
        requirements.CanonicalRequirement(
            "NFR-LEGACY",
            "coverage",
            "coverage-map.md",
            3,
            "- **NFR-LEGACY**: Historical quality family.",
        ),
        requirements.CanonicalRequirement(
            "REQ-ALPHA:2_BETA",
            "plan",
            "plan.md",
            3,
            "Composite REQ-ALPHA:2_BETA remains observable.",
        ),
        requirements.CanonicalRequirement(
            "SC-HIST.2",
            "task_metadata",
            "tasks.md",
            2,
            "- [ ] T-2 req=AC-000001,FR-000001,SC-HIST.2 depends=none",
        ),
        requirements.CanonicalRequirement(
            "US-LEGACY",
            "plan",
            "plan.md",
            4,
            "- **US-LEGACY**: Historical story family.",
        ),
    ]

    assert requirements.extract_canonical_requirements_from_texts(
        spec_text=spec_text,
        plan_text=plan_text,
        coverage_text=coverage_text,
        tasks_text=tasks_text,
    ) == expected

    (tmp_path / "spec.md").write_bytes(spec_text.encode("utf-8"))
    (tmp_path / "plan.md").write_text(plan_text, encoding="utf-8")
    (tmp_path / "coverage-map.md").write_text(coverage_text, encoding="utf-8")
    (tmp_path / "tasks.md").write_text(tasks_text, encoding="utf-8")
    assert requirements.extract_canonical_requirements(tmp_path) == expected


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("spec_text", b"FR-001"),
        ("plan_text", Path("plan.md")),
        ("coverage_text", _TextSubclass("FR-002")),
        ("tasks_text", 7),
    ],
)
def test_requirement_texts_reject_non_exact_strings(parameter, value):
    with pytest.raises(TypeError, match=rf"^{parameter} must be str or None$"):
        requirements.extract_canonical_requirements_from_texts(**{parameter: value})


def test_requirement_texts_treat_none_and_empty_as_captured_absence_or_empty():
    assert requirements.extract_canonical_requirements_from_texts() == []
    assert requirements.extract_canonical_requirements_from_texts(spec_text="") == []


def test_deferred_parser_preserves_complete_entries_statuses_and_order():
    text = (
        '{"schema_version":1,"ignored":"legacy-compatible","entries":['
        '{"entry_id":" defer-002 ","status":"deferred",'
        '"selected_ids":["FR-002","",7],"derived_task_ids":["T-002","T-001"],'
        '"prior_task_statuses":{"T-002":"pending"," T-001 ":"done"},'
        '"reason":" owner choice ","deferred_at":" time-a ","planned_at":null},'
        '{"entry_id":"defer-001","status":"planned","selected_ids":["NFR-001"],'
        '"derived_task_ids":[],"prior_task_statuses":{},"reason":"restored",'
        '"deferred_at":"time-b","planned_at":" time-c "}]}'
    )
    expected = deferred_scope.DeferredScopeLedger(
        entries=(
            deferred_scope.DeferredScopeEntry(
                entry_id="defer-002",
                status="deferred",
                selected_ids=("FR-002", "7"),
                derived_task_ids=("T-002", "T-001"),
                prior_task_statuses=(("T-001", "DONE"), ("T-002", "PENDING")),
                reason="owner choice",
                deferred_at="time-a",
                planned_at=None,
            ),
            deferred_scope.DeferredScopeEntry(
                entry_id="defer-001",
                status="planned",
                selected_ids=("NFR-001",),
                derived_task_ids=(),
                prior_task_statuses=(),
                reason="restored",
                deferred_at="time-b",
                planned_at="time-c",
            ),
        )
    )

    assert deferred_scope.parse_deferred_scope_ledger(text) == expected


def test_deferred_parser_rejects_duplicate_entry_ids():
    text = (
        '{"schema_version":1,"entries":['
        '{"entry_id":"same","status":"deferred","selected_ids":[],'
        '"derived_task_ids":[],"prior_task_statuses":{},"reason":"one",'
        '"deferred_at":"time","planned_at":null},'
        '{"entry_id":"same","status":"planned","selected_ids":[],'
        '"derived_task_ids":[],"prior_task_statuses":{},"reason":"two",'
        '"deferred_at":"time","planned_at":"later"}]}'
    )

    with pytest.raises(
        deferred_scope.DeferredScopeError,
        match="^duplicate deferred-scope entry id$",
    ):
        deferred_scope.parse_deferred_scope_ledger(text)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "invalid deferred-scope ledger: Expecting value: line 1 column 1 (char 0)"),
        ("[]", "unsupported deferred-scope ledger schema"),
        ('{"schema_version":2,"entries":[]}', "unsupported deferred-scope ledger schema"),
        (
            '{"schema_version":1,"entries":{}}',
            "deferred-scope ledger entries must be a list",
        ),
    ],
)
def test_deferred_parser_preserves_malformed_text_and_shape_errors(text, message):
    with pytest.raises(deferred_scope.DeferredScopeError) as exc_info:
        deferred_scope.parse_deferred_scope_ledger(text)

    assert str(exc_info.value) == message


def test_deferred_reader_distinguishes_missing_empty_and_bad_utf8(tmp_path):
    assert deferred_scope.read_ledger(tmp_path) == deferred_scope.DeferredScopeLedger(
        entries=()
    )

    path = tmp_path / deferred_scope.LEDGER_FILENAME
    path.write_text("", encoding="utf-8")
    with pytest.raises(deferred_scope.DeferredScopeError) as empty_exc:
        deferred_scope.read_ledger(tmp_path)
    assert str(empty_exc.value) == (
        "invalid deferred-scope ledger: Expecting value: line 1 column 1 (char 0)"
    )

    path.write_bytes(b"\xff")
    with pytest.raises(deferred_scope.DeferredScopeError) as unicode_exc:
        deferred_scope.read_ledger(tmp_path)
    assert str(unicode_exc.value).startswith("invalid deferred-scope ledger: ")
    assert "can't decode byte 0xff" in str(unicode_exc.value)


def test_verified_parser_preserves_v2_v1_defaults_duplicates_and_row_order():
    text = (
        '{"schema_version":2,"rows":['
        '{"requirement_id":"FR-001","status":"implemented",'
        '"evidence_refs":["src/a.py",7],"verified_commit":"abc",'
        '"verified_at":"time","spec_input_hash":"spec",'
        '"implementation_input_hash":"impl",'
        '"artifact_hashes":{"src/a.py":"hash-a","7":8},'
        '"verifier_version":"verify-v2","verify_scope":"targeted",'
        '"source_report_path":"report.md",'
        '"receipt_refs":[{"path":"receipt.json","attempt":1},"ignored"],'
        '"candidate_content_fingerprint":"candidate",'
        '"contract_hash":"contract","requirement_set_fingerprint":"requirements",'
        '"selected_evidence":["tests/a.py",9]},'
        '"ignored-row",'
        '{"requirement_id":"FR-001","status":"partial",'
        '"evidence_refs":["legacy/a.py"],"verified_commit":"old",'
        '"verified_at":"old-time","spec_input_hash":"old-spec",'
        '"implementation_input_hash":"old-impl",'
        '"artifact_hashes":{"legacy/a.py":"old-hash"},'
        '"verifier_version":"verify-v1","verify_scope":"full",'
        '"source_report_path":"legacy.md"},{}]}'
    )
    expected = verified_ledger.VerifiedFulfillmentLedger(
        rows=(
            verified_ledger.VerifiedLedgerRow(
                requirement_id="FR-001",
                status="IMPLEMENTED",
                evidence_refs=("src/a.py", "7"),
                verified_commit="abc",
                verified_at="time",
                spec_input_hash="spec",
                implementation_input_hash="impl",
                artifact_hashes={"src/a.py": "hash-a", "7": "8"},
                verifier_version="verify-v2",
                verify_scope="targeted",
                source_report_path="report.md",
                receipt_refs=({"path": "receipt.json", "attempt": "1"},),
                candidate_content_fingerprint="candidate",
                contract_hash="contract",
                requirement_set_fingerprint="requirements",
                selected_evidence=("tests/a.py", "9"),
            ),
            verified_ledger.VerifiedLedgerRow(
                requirement_id="FR-001",
                status="PARTIAL",
                evidence_refs=("legacy/a.py",),
                verified_commit="old",
                verified_at="old-time",
                spec_input_hash="old-spec",
                implementation_input_hash="old-impl",
                artifact_hashes={"legacy/a.py": "old-hash"},
                verifier_version="verify-v1",
                verify_scope="full",
                source_report_path="legacy.md",
            ),
            verified_ledger.VerifiedLedgerRow(
                requirement_id="",
                status="",
                evidence_refs=(),
                verified_commit="",
                verified_at="",
                spec_input_hash="",
                implementation_input_hash="",
                artifact_hashes={},
                verifier_version="",
                verify_scope="",
                source_report_path="",
            ),
        )
    )

    assert verified_ledger.parse_verified_ledger(text) == expected


def test_verified_parser_returns_fresh_nested_mappings_without_rebinding_evidence():
    text = (
        '{"rows":[{"requirement_id":"FR-001","status":"implemented",'
        '"evidence_refs":["src/old.py"],'
        '"artifact_hashes":{"src/old.py":"old-hash"},'
        '"receipt_refs":[{"path":"old-receipt.json"}],'
        '"selected_evidence":["src/old.py"]},'
        '{"requirement_id":"FR-002","status":"implemented",'
        '"evidence_refs":["src/new.py"],'
        '"artifact_hashes":{"src/new.py":"new-hash"},'
        '"receipt_refs":[{"path":"new-receipt.json"}],'
        '"selected_evidence":["src/new.py"]}]}'
    )

    first = verified_ledger.parse_verified_ledger(text)
    second = verified_ledger.parse_verified_ledger(text)
    assert type(first.rows[0].artifact_hashes) is dict
    assert type(first.rows[0].receipt_refs[0]) is dict
    first.rows[0].artifact_hashes["src/old.py"] = "changed"
    first.rows[0].receipt_refs[0]["path"] = "changed.json"

    assert second.rows[0].artifact_hashes == {"src/old.py": "old-hash"}
    assert second.rows[0].receipt_refs == ({"path": "old-receipt.json"},)
    assert second.rows[0].evidence_refs == ("src/old.py",)
    assert second.rows[0].selected_evidence == ("src/old.py",)
    assert second.rows[1].evidence_refs == ("src/new.py",)
    assert json.loads(text)["rows"][0]["artifact_hashes"] == {
        "src/old.py": "old-hash"
    }


def test_verified_parser_preserves_malformed_json_and_shape_errors():
    with pytest.raises(json.JSONDecodeError):
        verified_ledger.parse_verified_ledger("")
    with pytest.raises(AttributeError, match="has no attribute 'get'"):
        verified_ledger.parse_verified_ledger("[]")
    with pytest.raises(TypeError):
        verified_ledger.parse_verified_ledger('{"rows":null}')
    assert verified_ledger.parse_verified_ledger("{}") == (
        verified_ledger.VerifiedFulfillmentLedger(rows=())
    )


def test_verified_reader_propagates_missing_decoding_and_empty_file_errors(tmp_path):
    path = tmp_path / "ledger.json"
    with pytest.raises(FileNotFoundError):
        verified_ledger.read_verified_ledger(path)

    path.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        verified_ledger.read_verified_ledger(path)

    path.write_text("", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        verified_ledger.read_verified_ledger(path)


@pytest.mark.parametrize(
    ("parser", "value", "message"),
    [
        (deferred_scope.parse_deferred_scope_ledger, None, "text must be str"),
        (deferred_scope.parse_deferred_scope_ledger, b"{}", "text must be str"),
        (deferred_scope.parse_deferred_scope_ledger, Path("ledger.json"), "text must be str"),
        (deferred_scope.parse_deferred_scope_ledger, _TextSubclass("{}"), "text must be str"),
        (verified_ledger.parse_verified_ledger, None, "text must be str"),
        (verified_ledger.parse_verified_ledger, b"{}", "text must be str"),
        (verified_ledger.parse_verified_ledger, Path("ledger.json"), "text must be str"),
        (verified_ledger.parse_verified_ledger, _TextSubclass("{}"), "text must be str"),
    ],
)
def test_json_text_parsers_reject_non_exact_strings(parser, value, message):
    with pytest.raises(TypeError, match=rf"^{message}$"):
        parser(value)


def test_graph_source_text_parsers_do_not_touch_external_state():
    requirement_text = "- **FR-001**: Pure requirement.\n"
    deferred_text = '{"schema_version":1,"entries":[]}'
    verified_text = '{"schema_version":2,"rows":[]}'

    def deny_access(*_args, **_kwargs):
        raise AssertionError("pure parser attempted external access")

    with ExitStack() as stack:
        stack.enter_context(patch("builtins.open", side_effect=deny_access))
        stack.enter_context(patch("io.open", side_effect=deny_access))
        for method in (
            "open",
            "read_text",
            "read_bytes",
            "stat",
            "is_file",
            "exists",
            "iterdir",
            "glob",
            "rglob",
        ):
            stack.enter_context(patch.object(Path, method, deny_access))
        stack.enter_context(patch.object(os, "listdir", deny_access))
        stack.enter_context(patch.object(os, "scandir", deny_access))
        stack.enter_context(patch.object(os, "getenv", deny_access))
        for owner, name in (
            (deferred_scope, "_timestamp"),
            (deferred_scope, "extract_canonical_requirements"),
            (deferred_scope, "parse_task_rows"),
            (deferred_scope, "validate_tasks_markdown"),
            (deferred_scope, "summarize_task_progress"),
            (deferred_scope, "update_task_progress_markdown"),
            (verified_ledger, "read_fulfillment_metadata"),
        ):
            stack.enter_context(patch.object(owner, name, deny_access))

        assert [
            row.id
            for row in requirements.extract_canonical_requirements_from_texts(
                spec_text=requirement_text
            )
        ] == ["FR-001"]
        assert deferred_scope.parse_deferred_scope_ledger(
            deferred_text
        ) == deferred_scope.DeferredScopeLedger(entries=())
        assert verified_ledger.parse_verified_ledger(
            verified_text
        ) == verified_ledger.VerifiedFulfillmentLedger(rows=())
