import os
from pathlib import Path
import subprocess
import sys

from kernel.fulfillment import (
    apply_deferred_scope_to_report,
    NON_STRICT_BLOCKING,
    STRICT_BLOCKING,
    blocking_statuses,
    fulfillment_report_is_current,
    fulfillment_table_ids,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    make_verify_spec_run_dir,
    stamp_fulfillment_report,
    validate_fulfillment_artifacts,
    validate_deferred_scope_rows,
)
from harness.deferred_scope import apply_defer, apply_restore


def _run_harness(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.run(
        [sys.executable, "-m", "harness", *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_active_run_path_uses_runs_current(tmp_path):
    run_dir = tmp_path / "runs" / "run-20260602"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("run-20260602")

    assert (
        make_verify_spec_run_dir(tmp_path, "payments")
        == run_dir / "verify-spec" / "payments"
    )


def test_standalone_verification_path_uses_timestamp(tmp_path):
    assert (
        make_verify_spec_run_dir(tmp_path, "payments", timestamp="20260602-151500")
        == tmp_path / "runs" / "verify-spec-payments-20260602-151500"
    )


def test_latest_report_returns_newest_fulfillment_report(tmp_path):
    older = tmp_path / "fulfillment-report.md"
    newer = tmp_path / "fulfillment-report-2.md"
    ignored = tmp_path / "other-report.md"
    older.write_text("older")
    newer.write_text("newer")
    ignored.write_text("ignored")
    os.utime(older, (100, 100))
    os.utime(newer, (200, 200))

    assert latest_fulfillment_report(tmp_path) == newer


def test_latest_report_returns_none_when_absent(tmp_path):
    assert latest_fulfillment_report(tmp_path) is None


def test_missing_is_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| Requirement | Status |\n"
        "| --- | --- |\n"
        "| REQ-001 | MISSING |\n"
    )

    assert fulfillment_has_blocking_gaps(report)


def test_unverified_only_blocks_in_strict_mode(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| Requirement | Status |\n"
        "| --- | --- |\n"
        "| REQ-001 | UNVERIFIED |\n"
    )

    assert not fulfillment_has_blocking_gaps(report)
    assert fulfillment_has_blocking_gaps(report, strict=True)


def test_prose_status_words_do_not_count_as_matrix_statuses(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "No MISSING requirements remain in the final audit notes.\n"
    )

    assert not fulfillment_has_blocking_gaps(report)


def test_summary_table_status_counts_do_not_count_as_requirement_statuses(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| Status | Count |\n"
        "| --- | ---: |\n"
        "| MISSING | 0 |\n"
        "| PARTIAL | 0 |\n"
        "| DEVIATED | 0 |\n"
    )

    assert not fulfillment_has_blocking_gaps(report)


def test_nonzero_summary_table_status_counts_are_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| Status | Count | Percentage |\n"
        "|--------|------:|-----------:|\n"
        "| IMPLEMENTED | 68 | 39% |\n"
        "| PARTIAL | 42 | 24% |\n"
        "| UNVERIFIED | 1 | 1% |\n"
        "| MISSING | 47 | 27% |\n"
        "| DEVIATED | 0 | 0% |\n"
    )

    assert fulfillment_has_blocking_gaps(report)


def test_nonzero_fulfillment_summary_counts_are_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "**Verdict: SPEC_PARTIALLY_FULFILLED**\n\n"
        "- Checklist: **137 items** extracted from `spec.md` / `plan.md`\n"
        "- IMPLEMENTED 57 (42%) · PARTIAL 27 (20%) · UNVERIFIED 1 · "
        "MISSING 46 (34%) · DEVIATED 0 · OBSOLETE_SPEC 6\n"
    )

    assert fulfillment_has_blocking_gaps(report)


def test_equals_style_fulfillment_summary_counts_are_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "**Fulfillment status (170 checklist items)**: "
        "IMPLEMENTED=80, PARTIAL=31, UNVERIFIED=5, MISSING=53, "
        "DEVIATED=1, OBSOLETE_SPEC=0\n"
    )

    assert fulfillment_has_blocking_gaps(report)


def test_non_fr_requirement_table_ids_are_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Basis |\n"
        "| --- | --- | --- |\n"
        "| US1 | PARTIAL | full E2E absent |\n"
        "| SC-014 | MISSING | cloud billing absent |\n"
    )

    assert fulfillment_has_blocking_gaps(report)


def test_zero_fulfillment_summary_counts_are_not_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "**Verdict: SPEC_FULFILLED**\n\n"
        "- IMPLEMENTED: 137\n"
        "- PARTIAL: 0\n"
        "- MISSING: 0\n"
        "- DEVIATED: 0\n"
    )

    assert not fulfillment_has_blocking_gaps(report)


def test_blocking_statuses_returns_expected_sets():
    assert blocking_statuses() == NON_STRICT_BLOCKING
    assert blocking_statuses(strict=True) == STRICT_BLOCKING


def test_deferred_scope_replaces_only_ledger_backed_requirement_rows(tmp_path: Path):
    spec_dir = tmp_path / "specs" / "906-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("NFR-008\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        encoding="utf-8",
    )
    apply_defer(spec_dir, ["NFR-008"], reason="contradictory contrast rule")
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence |\n| --- | --- | --- |\n"
        "| NFR-008 | DEVIATED | no valid palette |\n",
        encoding="utf-8",
    )

    changed = apply_deferred_scope_to_report(report, spec_dir)

    assert changed == ("NFR-008",)
    assert "| NFR-008 | DEFERRED_SCOPE | defer:defer-001: contradictory contrast rule |" in report.read_text(encoding="utf-8")
    assert fulfillment_has_blocking_gaps(report) is False
    assert validate_deferred_scope_rows(report, spec_dir) == []


def test_deferred_scope_row_without_active_ledger_entry_is_invalid(tmp_path: Path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence |\n| --- | --- | --- |\n"
        "| NFR-008 | DEFERRED_SCOPE | defer:defer-001: reason |\n",
        encoding="utf-8",
    )

    assert validate_deferred_scope_rows(report, tmp_path) == [
        "NFR-008 has no active defer entry"
    ]


def test_planning_deferred_scope_restores_the_original_fulfillment_gap(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "906-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("NFR-008\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
        encoding="utf-8",
    )
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence |\n| --- | --- | --- |\n"
        "| NFR-008 | DEVIATED | src/a.py |\n",
        encoding="utf-8",
    )

    apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
    apply_deferred_scope_to_report(report, spec_dir)
    assert fulfillment_has_blocking_gaps(report) is False

    apply_restore(spec_dir, ["NFR-008"])
    report.write_text(
        "| ID | Status | Evidence |\n| --- | --- | --- |\n"
        "| NFR-008 | DEVIATED | src/a.py |\n",
        encoding="utf-8",
    )

    assert fulfillment_has_blocking_gaps(report) is True


def test_stamp_fulfillment_report_records_commit_metadata(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text("# Fulfillment\n", encoding="utf-8")

    stamp_fulfillment_report(report, spec_id="001", commit="abc123", run_id="run-1")

    text = report.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "spec_id: '001'" in text
    assert "verified_commit: abc123" in text
    assert "verify_run_id: run-1" in text
    assert "# Fulfillment" in text


def test_fulfillment_report_is_current_rejects_stale_commit(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text("# Fulfillment\n", encoding="utf-8")
    stamp_fulfillment_report(report, spec_id="001", commit="old", run_id="run-1")

    assert fulfillment_report_is_current(report, current_commit="old") is True
    assert fulfillment_report_is_current(report, current_commit="new") is False
    assert STRICT_BLOCKING == NON_STRICT_BLOCKING | {"UNVERIFIED"}


def test_fulfillment_table_ids_ignores_status_summary_tables():
    markdown = (
        "## Summary\n\n"
        "| Status | Count |\n"
        "| --- | ---: |\n"
        "| IMPLEMENTED | 130 |\n"
        "| PARTIAL | 0 |\n"
        "| UNVERIFIED | 0 |\n"
        "| MISSING | 0 |\n"
        "| DEVIATED | 0 |\n\n"
        "## Per-Requirement Verdicts\n\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
        "| US-001-AC-1 | OBSOLETE_SPEC | scope.md | high | deferred |\n"
        "| TASK-PROGRESS | PARTIAL | tasks.md | high | bookkeeping |\n"
    )

    assert fulfillment_table_ids(markdown) == {
        "FR-001",
        "US-001-AC-1",
        "TASK-PROGRESS",
    }


def test_validate_fulfillment_artifacts_allows_status_summary_table(tmp_path):
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | FR | spec.md | Build one thing | Test one thing |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| Status | Count |\n"
        "| --- | ---: |\n"
        "| IMPLEMENTED | 1 |\n"
        "| MISSING | 0 |\n\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
        encoding="utf-8",
    )

    result = validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
    )

    assert result.ok is True
    assert result.audit_count == 1
    assert result.report_count == 1


def test_validate_fulfillment_artifacts_prefers_canonical_inventory(tmp_path):
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
        encoding="utf-8",
    )
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category |\n"
        "| --- | --- |\n"
        "| FR-001 | functional |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status |\n"
        "| --- | --- |\n"
        "| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )

    result = validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=inventory,
    )

    assert result.ok is False
    assert result.audit_count == 2
    assert result.missing_in_report == ("FR-002",)


def test_validate_fulfillment_artifacts_accepts_python_assembled_report(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | impl |\n"
        "| FR-002 | MISSING | |\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}',
        encoding="utf-8",
    )
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category |\n"
        "| --- | --- |\n"
        "| FR-001 | functional |\n"
        "| FR-002 | functional |\n",
        encoding="utf-8",
    )

    result = validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=inventory,
    )

    assert result.ok is True


def test_validate_fulfillment_artifacts_rejects_summary_count_mismatch(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "**Fulfillment verdict**: IMPLEMENTED=1, PARTIAL=3, UNVERIFIED=0\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | source_and_test |\n"
        "| FR-002 | PARTIAL | partial |\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}',
        encoding="utf-8",
    )
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category |\n"
        "| --- | --- |\n"
        "| FR-001 | functional |\n"
        "| FR-002 | functional |\n",
        encoding="utf-8",
    )

    result = validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=inventory,
    )

    assert result.ok is False
    assert result.summary_count_mismatches == (
        "PARTIAL reported 3 but requirement rows contain 1",
    )


def test_validate_fulfillment_artifacts_cli_reports_missing_rows(tmp_path):
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
        encoding="utf-8",
    )
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category |\n"
        "| --- | --- |\n"
        "| FR-001 | functional |\n"
        "| FR-002 | functional |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status |\n"
        "| --- | --- |\n"
        "| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )

    completed = _run_harness(
        [
            "validate-fulfillment-artifacts",
            str(audit),
            str(report),
            str(inventory),
        ]
    )

    assert completed.returncode == 1
    assert "missing_in_report: FR-002" in completed.stderr
    assert "extra_in_report" not in completed.stderr
