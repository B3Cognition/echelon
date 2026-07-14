"""Tests for requirement-level verified fulfillment ledger planning."""

from __future__ import annotations

from pathlib import Path

from harness.verified_fulfillment_ledger import (
    build_verified_ledger,
    plan_verified_ledger_reuse,
)


def _report(path: Path) -> Path:
    path.write_text(
        "---\n"
        "spec_id: spec-001\n"
        "verified_commit: abc123\n"
        "verify_scope: full\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
        "| FR-002 | IMPLEMENTED | tests/a.test.py | high | ok |\n"
        "| FR-003 | UNVERIFIED | test-results/runtime.json | low | no artifact |\n",
        encoding="utf-8",
    )
    return path


def test_ledger_reuses_verified_rows_and_rechecks_unresolved_rows(tmp_path):
    ledger = build_verified_ledger(
        report_path=_report(tmp_path / "fulfillment-report.md"),
        spec_input_hash="spec-hash",
        implementation_input_hash="impl-hash",
        artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        verifier_version="verify-v1",
    )

    plan = plan_verified_ledger_reuse(
        ledger,
        current_spec_input_hash="spec-hash",
        current_implementation_input_hash="impl-hash",
        current_artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        current_verifier_version="verify-v1",
    )

    assert plan.reused_requirement_ids == ("FR-001", "FR-002")
    assert plan.rechecked_requirement_ids == ("FR-003",)
    assert plan.invalidated_requirement_ids == ()
    assert plan.unresolved_requirement_ids == ("FR-003",)


def test_ledger_invalidates_only_rows_with_changed_artifacts(tmp_path):
    ledger = build_verified_ledger(
        report_path=_report(tmp_path / "fulfillment-report.md"),
        spec_input_hash="spec-hash",
        implementation_input_hash="impl-hash-old",
        artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        verifier_version="verify-v1",
    )

    plan = plan_verified_ledger_reuse(
        ledger,
        current_spec_input_hash="spec-hash",
        current_implementation_input_hash="impl-hash-new",
        current_artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-b",
            "test-results/runtime.json": "runtime-a",
        },
        current_verifier_version="verify-v1",
    )

    assert plan.reused_requirement_ids == ("FR-001",)
    assert plan.invalidated_requirement_ids == ("FR-002",)
    assert plan.unresolved_requirement_ids == ("FR-003",)
    assert plan.rechecked_requirement_ids == ("FR-002", "FR-003")


def test_ledger_invalidates_all_rows_when_spec_or_verifier_policy_changes(tmp_path):
    ledger = build_verified_ledger(
        report_path=_report(tmp_path / "fulfillment-report.md"),
        spec_input_hash="spec-hash-old",
        implementation_input_hash="impl-hash",
        artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        verifier_version="verify-v1",
    )

    spec_plan = plan_verified_ledger_reuse(
        ledger,
        current_spec_input_hash="spec-hash-new",
        current_implementation_input_hash="impl-hash",
        current_artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        current_verifier_version="verify-v1",
    )
    verifier_plan = plan_verified_ledger_reuse(
        ledger,
        current_spec_input_hash="spec-hash-old",
        current_implementation_input_hash="impl-hash",
        current_artifact_hashes={
            "src/a.py": "src-a",
            "tests/a.test.py": "test-a",
            "test-results/runtime.json": "runtime-a",
        },
        current_verifier_version="verify-v2",
    )

    assert spec_plan.reused_requirement_ids == ()
    assert spec_plan.invalidated_requirement_ids == ("FR-001", "FR-002")
    assert spec_plan.unresolved_requirement_ids == ("FR-003",)
    assert spec_plan.rechecked_requirement_ids == ("FR-001", "FR-002", "FR-003")
    assert verifier_plan.rechecked_requirement_ids == ("FR-001", "FR-002", "FR-003")
