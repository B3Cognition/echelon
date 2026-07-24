import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest
import yaml

from harness.squad import SquadController


@pytest.mark.parametrize(
    ("phase", "next_phase"),
    [
        ("phase3-plan", "phase3-tasks-lexicon"),
        ("phase3-tasks-lexicon", "phase3-understanding"),
        ("phase3-tasks-lexicon", "phase3-plan"),
        ("phase3-consensus", "phase3-consensus-tasks-lexicon"),
        ("phase3-consensus-tasks-lexicon", "checkpoint-plan"),
        ("phase3-consensus-tasks-lexicon", "phase3-plan"),
        ("phase3-consensus-tasks-lexicon", "terminal-blocked"),
    ],
)
def test_tasks_lexicon_nodes_use_normal_phase_checkpoints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    phase: str,
    next_phase: str,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "harness.squad.create_phase_checkpoint",
        lambda **kwargs: calls.append(kwargs),
    )
    controller = object.__new__(SquadController)
    controller._project_root = tmp_path
    controller._squad_dir = tmp_path / "runs" / "run-test"
    controller._state_store = MagicMock()
    controller._state_store.load.return_value = {
        "run_id": "run-test",
        "spec_id": "001-demo",
        "spec_dir": "specs/001-demo",
    }
    (tmp_path / "specs" / "001-demo").mkdir(parents=True)

    assert controller._checkpoint_successful_phase(phase, next_phase) is True
    assert calls == [{
        "project_root": tmp_path,
        "spec_dir": tmp_path / "specs" / "001-demo",
        "phase": phase,
        "next_phase": next_phase,
        "run_id": "run-test",
        "spec_id": "001-demo",
        "additional_spec_dirs": (),
        "additional_owned_paths": (),
    }]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_tasks_lexicon_report_is_in_real_phase_checkpoint_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / ".gitignore").write_text(
        "/specs/*/.echelon/checkpoints.json\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# Repository\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    report = '{"schema_version":1,"ok":false,"findings":[]}\n'
    (spec_dir / "tasks-lexicon-report.json").write_text(report, encoding="utf-8")
    state_store = MagicMock()
    state_store.load.return_value = {
        "run_id": "run-test",
        "spec_id": "001-demo",
        "spec_dir": "specs/001-demo",
    }
    controller = object.__new__(SquadController)
    controller._project_root = repo
    controller._squad_dir = repo / "runs" / "run-test"
    controller._state_store = state_store

    assert controller._checkpoint_successful_phase(
        "phase3-tasks-lexicon",
        "phase3-plan",
    ) is True

    ledger = json.loads(
        (spec_dir / ".echelon/checkpoints.json").read_text(encoding="utf-8")
    )
    checkpoint = ledger["checkpoints"][-1]
    assert checkpoint["phase"] == "phase3-tasks-lexicon"
    assert checkpoint["next_phase"] == "phase3-plan"
    assert checkpoint["commit"] == _git(repo, "rev-parse", "HEAD")
    assert (
        _git(
            repo,
            "show",
            f"{checkpoint['commit']}:specs/001-demo/tasks-lexicon-report.json",
        )
        + "\n"
        == report
    )


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
