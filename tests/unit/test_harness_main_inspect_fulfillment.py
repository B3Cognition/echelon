from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
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


def test_inspect_fulfillment_report_reports_missing_report(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    result = _run(["inspect-fulfillment-report", str(spec_dir), "head123"])

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["exists"] is False
    assert data["report_path"] is None
    assert data["is_current"] is False
    assert data["verified_commit"] is None


def test_inspect_fulfillment_report_reports_current_metadata(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "---\n"
        "spec_id: 001-demo\n"
        "verified_commit: head123\n"
        "verified_at: '2026-07-09T10:00:00Z'\n"
        "verify_scope: full\n"
        "---\n"
        "| ID | Status |\n"
        "| --- | --- |\n"
        "| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )

    result = _run(["inspect-fulfillment-report", str(spec_dir), "head123"])

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["exists"] is True
    assert data["report_path"] == str(report)
    assert data["verified_commit"] == "head123"
    assert data["verify_scope"] == "full"
    assert data["is_current"] is True
    assert data["has_blocking_gaps"] is False
    assert data["has_strict_blocking_gaps"] is False


def test_inspect_fulfillment_report_serializes_yaml_timestamp_metadata(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        "verified_commit: head123\n"
        "verified_at: 2026-07-09T10:00:00+00:00\n"
        "---\n"
        "| ID | Status |\n"
        "| --- | --- |\n"
        "| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )

    result = _run(["inspect-fulfillment-report", str(spec_dir), "head123"])

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["verified_at"] == "2026-07-09 10:00:00+00:00"


def test_inspect_fulfillment_report_reports_stale_scoped_and_blocking(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    report = spec_dir / "fulfillment-report.md"
    report.write_text(
        "---\n"
        "verified_commit: old123\n"
        "verify_scope: scoped\n"
        "---\n"
        "**Fulfillment status**: IMPLEMENTED=1, MISSING=1, PARTIAL=0, UNVERIFIED=1\n",
        encoding="utf-8",
    )

    result = _run(["inspect-fulfillment-report", str(spec_dir), "head123"])

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["verified_commit"] == "old123"
    assert data["verify_scope"] == "scoped"
    assert data["is_current"] is False
    assert data["has_blocking_gaps"] is True
    assert data["has_strict_blocking_gaps"] is True
