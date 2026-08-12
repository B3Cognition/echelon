"""Tests for switching away from a completed Phase A spec run."""

from __future__ import annotations

import json
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from echelon.cli import USAGE, _cmd_spec, _next_continue_phase, _select_squad_dir
from harness.phase_a_readiness import REQUIRED_PHASE_A_BUILD_INPUTS


def test_active_run_prompt_can_continue_current_spec_before_creating_sibling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_run = tmp_path / "runs" / "spec-active"
    active_run.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-active\n", encoding="utf-8")
    (active_run / "state.json").write_text(
        json.dumps(
            {
                "status": "running",
                "user_message": "Build audit logging",
                "feature_branch": "001-build-audit-logging",
            }
        ),
        encoding="utf-8",
    )

    class TtyInput(io.StringIO):
        def isatty(self) -> bool:
            return True

    class TtyOutput(io.StringIO):
        def isatty(self) -> bool:
            return True

    stdin = TtyInput("c\n")
    stdout = TtyOutput()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(
        "echelon.phase_a_start.start_phase_a_spec",
        lambda *_args, **_kwargs: pytest.fail("should not create a sibling spec"),
    )

    run_dir, is_fresh = _select_squad_dir(tmp_path, "Add report export")

    assert run_dir == active_run
    assert is_fresh is False
    assert "Continue current" in stdout.getvalue()


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
    constitution_path = tmp_path / ".echelon" / "constitution.md"
    constitution_path.parent.mkdir(parents=True)
    constitution_path.write_text(constitution, encoding="utf-8")

    spec_dir = tmp_path / "specs" / "001-first-spec"
    spec_dir.mkdir(parents=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        if name == "constitution.md":
            content = constitution
        elif name == "plan-conformance.json":
            content = (
                '{\n'
                '  "status": "pass",\n'
                '  "findings": [],\n'
                '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
                '}\n'
            )
        else:
            content = f"# {name}\n"
        (spec_dir / name).write_text(content, encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None

    monkeypatch.setattr("harness.paths.make_spec_run_id", lambda: "spec-new")

    def fake_start(_root, run_id, description, **_kwargs):
        assert run_id == "spec-new"
        assert description == "build the second feature"
        new_run = tmp_path / "runs" / run_id
        new_run.mkdir()
        (new_run / "staging").mkdir()
        (tmp_path / "runs" / ".current").write_text(f"{run_id}\n", encoding="utf-8")
        return SimpleNamespace(run_dir=new_run)

    monkeypatch.setattr("echelon.phase_a_start.start_phase_a_spec", fake_start)

    new_run, is_fresh = _select_squad_dir(tmp_path, "build the second feature")

    assert is_fresh is True
    assert new_run == tmp_path / "runs" / "spec-new"
    assert (tmp_path / "runs" / ".current").read_text(encoding="utf-8").strip() == "spec-new"
    assert (new_run / "staging").is_dir()
    assert json.loads((old_run / "state.json").read_text(encoding="utf-8")) == old_state


def test_manual_next_phase_reuses_a_blocked_run(tmp_path: Path, monkeypatch) -> None:
    active_run = tmp_path / "runs" / "spec-blocked"
    active_run.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-blocked\n", encoding="utf-8")
    (active_run / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "user_message": "Build audit logging",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "echelon.phase_a_start.start_phase_a_spec",
        lambda *_args, **_kwargs: pytest.fail("manual recovery must not create a run"),
    )

    run_dir, is_fresh = _select_squad_dir(
        tmp_path,
        "",
        manual_recovery=True,
    )

    assert run_dir == active_run
    assert is_fresh is False


def test_manual_next_phase_reuses_a_human_blocked_run(tmp_path: Path, monkeypatch) -> None:
    active_run = tmp_path / "runs" / "spec-blocked"
    active_run.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-blocked\n", encoding="utf-8")
    (active_run / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "terminal-blocked",
                "user_message": "Build audit logging",
                "escalation_question": "Choose a repair strategy.",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "echelon.phase_a_start.start_phase_a_spec",
        lambda *_args, **_kwargs: pytest.fail("manual recovery must not create a run"),
    )

    run_dir, is_fresh = _select_squad_dir(tmp_path, "", manual_recovery=True)

    assert run_dir == active_run
    assert is_fresh is False


def test_spec_help_documents_checkpoint_gated_switch_flags(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _cmd_spec(["--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "switch <spec-or-run-id>" in output
    assert "--stash | --discard --confirm" in output
    assert "--restore-stash" in output
    assert "spec switch <spec-or-run-id>" in USAGE


def test_spec_help_documents_perfectionist_authoring_mode(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        _cmd_spec(["--help"])

    output = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "run <description>" in output
    assert "--perfectionist" in output
    assert "Exhaustive Cartographer authoring" in output
    assert "--perfectionist" in USAGE


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


def test_first_cli_selector_creates_runs_directory_and_echelon_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Echelon Tests"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "echelon@example.test"], cwd=tmp_path, check=True
    )
    (tmp_path / ".gitignore").write_text("/runs/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True
    )
    monkeypatch.setattr("harness.paths.make_spec_run_id", lambda: "run-first")

    run_dir, is_fresh = _select_squad_dir(tmp_path, "Build audit logging")

    assert is_fresh is True
    assert run_dir == tmp_path / "runs" / "run-first"
    assert (tmp_path / "runs" / ".gitignore").exists()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert branch == "001-build-audit-logging"
    assert (tmp_path / "runs" / ".current").read_text().strip() == "run-first"
