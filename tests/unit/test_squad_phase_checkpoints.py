from pathlib import Path
from unittest.mock import MagicMock

from harness.squad import SquadController


def test_squad_records_checkpoint_after_successful_advance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []

    def fake_checkpoint(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr("harness.squad.create_phase_checkpoint", fake_checkpoint)

    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    controller._squad_dir = tmp_path / "runs" / "spec-run"
    controller._state_store = MagicMock()
    controller._state_store.load.return_value = {
        "run_id": "squad-1",
        "spec_dir": "specs/001-demo",
    }

    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)

    controller._checkpoint_successful_phase("phase3-plan", "phase3-consensus")

    assert calls[0]["project_root"] == tmp_path
    assert calls[0]["spec_dir"] == spec_dir
    assert calls[0]["phase"] == "phase3-plan"
    assert calls[0]["next_phase"] == "phase3-consensus"
    assert calls[0]["run_id"] == "squad-1"
