from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_re_memory_refresh_outputs_mine_summary(monkeypatch, tmp_path: Path) -> None:
    from echelon.mempalace_re import ReMemoryMineReport

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
    from echelon.cli_app import app

    result = CliRunner().invoke(app, ["re", "memory", "refresh"])

    assert result.exit_code == 0
    assert "MemPalace RE mine complete" in result.output
    assert "artifacts=2" in result.output
    assert "written=5" in result.output

