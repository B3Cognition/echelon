from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_spec_memory_help_is_exposed() -> None:
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "--help"])

    assert result.exit_code == 0
    assert "mine" in result.output
    assert "audit" in result.output
    assert "refresh" in result.output


@pytest.mark.unit
def test_spec_memory_audit_json_exit_zero_for_warn(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="warn",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo", "--json"])

    assert result.exit_code == 0
    assert '"status": "warn"' in result.output


@pytest.mark.unit
def test_spec_memory_audit_exit_codes(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport

    monkeypatch.chdir(tmp_path)

    def fake_audit(project_root, selector, probe_retrieval=False):
        return SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing=None,
            palace_path=None,
            status="unavailable",
            expected_count=0,
            present_current_count=0,
        )

    monkeypatch.setattr("echelon.mempalace_audit.audit_spec_memory", fake_audit, raising=False)
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "audit", "003-demo"])

    assert result.exit_code == 2


@pytest.mark.unit
def test_spec_memory_refresh_runs_mine_then_audit(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_audit import SpecMemoryAuditReport
    from echelon.mempalace_requirements import SpecMemoryMineReport

    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_requirements.mine_spec_requirements",
        lambda project_root, selector, run_id: calls.append(("mine", selector)) or SpecMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
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
        "echelon.mempalace_audit.audit_spec_memory",
        lambda project_root, selector, probe_retrieval=False: calls.append(("audit", selector)) or SpecMemoryAuditReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="pass",
            expected_count=1,
            present_current_count=1,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["spec", "memory", "refresh", "003-demo"])

    assert result.exit_code == 0
    assert calls == [("mine", "003-demo"), ("audit", "003-demo")]
