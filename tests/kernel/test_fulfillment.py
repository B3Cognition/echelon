import os
from pathlib import Path

from kernel.fulfillment import (
    NON_STRICT_BLOCKING,
    STRICT_BLOCKING,
    blocking_statuses,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    make_verify_spec_run_dir,
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


def test_blocking_statuses_returns_expected_sets():
    assert blocking_statuses() == NON_STRICT_BLOCKING
    assert blocking_statuses(strict=True) == STRICT_BLOCKING
    assert STRICT_BLOCKING == NON_STRICT_BLOCKING | {"UNVERIFIED"}
