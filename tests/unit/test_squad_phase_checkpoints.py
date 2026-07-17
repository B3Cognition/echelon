from pathlib import Path
from unittest.mock import MagicMock

import yaml

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
    assert calls[0]["spec_id"] == "001-demo"


def test_squad_checkpoints_staging_spec_with_state_spec_id(
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
        "spec_id": "001-simple-notes",
        "spec_dir": "runs/spec-run/staging",
    }

    spec_dir = tmp_path / "runs" / "spec-run" / "staging"
    spec_dir.mkdir(parents=True)

    controller._checkpoint_successful_phase("phase1-why1", "phase1-why1")

    assert calls[0]["spec_dir"] == spec_dir
    assert calls[0]["spec_id"] == "001-simple-notes"


def test_squad_checkpoints_published_spec_with_full_directory_id(
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
        "spec_id": "001",
        "spec_dir": "specs/001-prose-distribution-engine",
    }

    spec_dir = tmp_path / "specs" / "001-prose-distribution-engine"
    spec_dir.mkdir(parents=True)

    controller._checkpoint_successful_phase("phase3-how", "phase3-sentinel")

    assert calls[0]["spec_dir"] == spec_dir
    assert calls[0]["spec_id"] == "001-prose-distribution-engine"


def test_squad_terminal_phase4_checkpoint_includes_published_spec(
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
        "spec_id": "001-demo",
        "spec_dir": "runs/spec-run/specs/001-demo",
        "published_spec_dir": "specs/001-demo",
    }
    active = tmp_path / "runs" / "spec-run" / "specs" / "001-demo"
    published = tmp_path / "specs" / "001-demo"
    active.mkdir(parents=True)
    published.mkdir(parents=True)

    controller._checkpoint_successful_phase("phase4-document", "done")

    assert calls[0]["additional_spec_dirs"] == (published,)


def test_squad_terminal_phase4_checkpoint_includes_accepted_kb_targets(
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
        "run_id": "spec-run",
        "spec_id": "001-demo",
        "spec_dir": "runs/spec-run/specs/001-demo",
        "published_spec_dir": "specs/001-demo",
    }
    active = tmp_path / "runs" / "spec-run" / "specs" / "001-demo"
    published = tmp_path / "specs" / "001-demo"
    accepted_target = tmp_path / "knowledge-base" / "sage-decisions.yaml"
    active.mkdir(parents=True)
    published.mkdir(parents=True)
    accepted_target.parent.mkdir(parents=True)
    accepted_target.write_text("entries: []\n", encoding="utf-8")
    report = tmp_path / "runs" / "spec-run" / "kb-apply-report.yaml"
    report.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "run_id": "spec-run",
                "status": "applied",
                "outcomes": [
                    {
                        "proposal_id": "sage-1",
                        "outcome": "accepted",
                        "targets": ["knowledge-base/sage-decisions.yaml"],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    controller._checkpoint_successful_phase("phase4-document", "done")

    assert calls[0]["additional_owned_paths"] == (accepted_target,)
