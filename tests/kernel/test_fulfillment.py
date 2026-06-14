import os
from pathlib import Path

from kernel.fulfillment import (
    NON_STRICT_BLOCKING,
    STRICT_BLOCKING,
    blocking_statuses,
    fulfillment_report_is_current,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    make_verify_spec_run_dir,
    stamp_fulfillment_report,
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
