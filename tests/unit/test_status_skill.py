from pathlib import Path

import pytest

from harness.skills.status_skill import show_status


@pytest.mark.unit
def test_status_skill_corrupted_state_uses_delivery_resume_hint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state_dir = tmp_path / "runs" / "build-001" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text("{not-json", encoding="utf-8")

    result = show_status(str(tmp_path))

    assert result["strategies"]["default"]["status"] == "corrupted"
    err = capsys.readouterr().err
    assert "echelon delivery resume" in err
    assert "echelon.harness-resume" not in err
