from pathlib import Path

import pytest
from typer.testing import CliRunner


@pytest.mark.unit
def test_spec_evidence_memory_refresh_outputs_mine_summary(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from echelon.mempalace_spec_evidence import SpecEvidenceMemoryMineReport

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.mempalace_spec_evidence.mine_spec_evidence_memory",
        lambda project_root, spec_selector, run_id: SpecEvidenceMemoryMineReport(
            schema_version=1,
            spec_id="003-demo",
            spec_dir=str(tmp_path / "specs" / "003-demo"),
            wing="demo-wing",
            palace_path=".mempalace",
            status="complete",
            artifact_count=3,
            expected_count=9,
            written_count=9,
            adopted_count=0,
            skipped_count=0,
            failed_count=0,
            drifted_count=0,
        ),
        raising=False,
    )
    from echelon.cli_app import app

    result = CliRunner().invoke(
        app,
        ["spec", "evidence", "memory", "refresh", "003-demo"],
    )

    assert result.exit_code == 0
    assert "MemPalace spec evidence mine complete" in result.output
    assert "artifacts=3" in result.output
    assert "written=9" in result.output

