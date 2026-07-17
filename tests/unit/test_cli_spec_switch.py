"""Tests for switching away from a completed Phase A spec run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.cli import USAGE, _cmd_spec, _next_continue_phase, _select_squad_dir
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS


def test_ready_spec_can_be_preserved_while_a_different_spec_run_starts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    old_run = tmp_path / "runs" / "spec-old"
    old_run.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-old\n", encoding="utf-8")

    old_state = {
        "status": "done",
        "phase": "DONE",
        "spec_id": "001-first-spec",
        "published_spec_dir": "specs/001-first-spec",
        "user_message": "build the first feature",
        "completed_phases": [
            "phase1-constitution",
            "phase2-tracker-alignment",
            "phase3-specialists",
            "phase3-how",
            "phase3-sentinel",
            "phase3-plan",
            "phase3-consensus",
            "phase4-document",
        ],
    }
    (old_run / "state.json").write_text(json.dumps(old_state), encoding="utf-8")

    constitution = "# Constitution\n\nReal project rules.\n"
    memory_dir = tmp_path / ".specify" / "memory"
    memory_dir.mkdir(parents=True)
    (memory_dir / "constitution.md").write_text(constitution, encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-first-spec"
    spec_dir.mkdir(parents=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        content = constitution if name == "constitution.md" else f"# {name}\n"
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None

    monkeypatch.setattr("harness.paths.make_spec_run_id", lambda: "spec-new")

    new_run, is_fresh = _select_squad_dir(tmp_path, "build the second feature")

    assert is_fresh is True
    assert new_run == tmp_path / "runs" / "spec-new"
    assert (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip() == "spec-new"
    assert (new_run / "staging").is_dir()
    assert json.loads((old_run / "state.json").read_text(encoding="utf-8")) == old_state


def test_spec_help_documents_checkpoint_gated_switch_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _cmd_spec(["--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "switch <spec-or-run-id>" in output
    assert "--stash | --discard --confirm" in output
    assert "--restore-stash" in output
    assert "spec switch <spec-or-run-id>" in USAGE


def test_spec_switch_dispatches_to_deterministic_presenter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], Path]] = []

    def fake_command(args, *, project_root, **_kwargs):
        calls.append((args, project_root))
        return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "echelon.spec_switch_cli.run_spec_switch_command",
        fake_command,
    )

    _cmd_spec(["switch", "run-b", "--stash"])

    assert calls == [(["run-b", "--stash"], tmp_path)]
