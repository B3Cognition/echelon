"""Integration tests for `echelon kb` CLI commands."""

from __future__ import annotations

from typer.testing import CliRunner

from echelon.cli_app import app


runner = CliRunner()


def test_kb_validate_reports_missing_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "validate", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert "proposals: 0" in result.stdout
    assert "status: degraded" in result.stdout


def test_kb_apply_writes_report_for_empty_run(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["kb", "apply", "--run-id", "squad-001"])

    assert result.exit_code == 0
    assert (tmp_path / "runs" / "squad-001" / "kb-apply-report.yaml").exists()
    assert "kb_apply_status: degraded" in result.stdout
