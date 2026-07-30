from pathlib import Path
import json

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_re_memory_refresh_outputs_mine_summary(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_re import ReMemoryMineReport
    from echelon.mempalace_re import ReMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_re.mine_re_memory",
        lambda project_root, run_id: ReMemoryMineReport(
            schema_version=1,
            re_root=str(tmp_path / "re"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            artifact_count=2,
            expected_count=5,
            written_count=5,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_re.audit_re_memory",
        lambda project_root: ReMemoryAuditReport(
            schema_version=1,
            re_root=str(tmp_path / "re"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            artifact_count=2,
            expected_count=5,
            present_current_count=5,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "memory", "refresh"])

    assert result.exit_code == 0
    assert "MemPalace RE mine complete" in result.output
    assert "artifacts=2" in result.output
    assert "written=5" in result.output
    assert "# MemPalace RE Audit" in result.output


@pytest.mark.unit
def test_re_memory_audit_outputs_reconciliation(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_re import ReMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_re.audit_re_memory",
        lambda project_root: ReMemoryAuditReport(
            schema_version=1,
            re_root=str(tmp_path / "re"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="fail",
            artifact_count=2,
            expected_count=5,
            present_current_count=4,
            missing=["drawer-5"],
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "memory", "audit"])

    assert result.exit_code == 1
    assert "# MemPalace RE Audit" in result.output
    assert "Missing: 1" in result.output


@pytest.mark.unit
def test_re_memory_refresh_json_outputs_combined_report(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_re import ReMemoryAuditReport, ReMemoryMineReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_re.mine_re_memory",
        lambda project_root, run_id: ReMemoryMineReport(
            schema_version=1,
            re_root=str(tmp_path / "re"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            artifact_count=1,
            expected_count=1,
            written_count=1,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "echelon.mempalace_re.audit_re_memory",
        lambda project_root: ReMemoryAuditReport(
            schema_version=1,
            re_root=str(tmp_path / "re"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            artifact_count=1,
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "memory", "refresh", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert sorted(payload) == ["audit", "mine"]
