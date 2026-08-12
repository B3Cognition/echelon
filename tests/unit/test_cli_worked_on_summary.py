from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from echelon.cli_app import run
from harness.worked_on_summary import (
    WorkedOnEvidence,
    attach_to_terminal_fields,
    worked_on_scope,
)


@pytest.mark.parametrize(
    ("argv", "handler"),
    [
        (["spec", "run", "Add sessions"], "_cmd_spec_run"),
        (["spec", "continue"], "_cmd_spec_continue"),
        (["spec", "resume", "Use option A"], "_cmd_spec_resume"),
    ],
)
def test_phase_a_lifecycle_callbacks_emit_one_summary_for_persisted_run(
    argv: list[str],
    handler: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260812-120000-000001"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "spec_id": "014-session-security",
                "user_message": "Add sessions",
                "status": "blocked",
                "phase": "terminal-blocked",
                "blocked_reason": "provider unavailable",
                "completed_phases": ["phase1-what"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(f"echelon.cli.{handler}", lambda _args: None)
    monkeypatch.setattr(
        "echelon.wiki.service.capture_input_snapshot",
        lambda _root: None,
    )
    monkeypatch.setattr(
        "echelon.wiki.service.refresh_after_changed_command",
        lambda _root, _before: None,
    )

    assert run(argv) is None

    output = capsys.readouterr().out
    assert output.count("WORKED ON") == 1
    assert "Worked through 1 phases toward Add sessions." in output
    assert "provider unavailable" in output


def test_nested_scope_and_rich_banner_emit_exactly_once(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = WorkedOnEvidence(
        command="spec run",
        status="done",
        goal="Add sessions",
        completed_phases=("phase1-what",),
    )

    with worked_on_scope("spec resume", tmp_path):
        with worked_on_scope("spec continue", tmp_path):
            fields = attach_to_terminal_fields([], evidence, project_root=tmp_path)
            from echelon.ui import banner

            banner("SQUAD SUMMARY", fields)

    output = capsys.readouterr().out
    assert output.count("Worked on") == 1
    assert "WORKED ON" not in output


def test_scope_preserves_original_system_exit_code(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "runs" / "spec-20260812-120000-000001"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps({"status": "failed", "blocked_reason": "bad config"}),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        with worked_on_scope("spec run", tmp_path):
            raise SystemExit(7)

    assert exc.value.code == 7
    assert "WORKED ON" in capsys.readouterr().out


def test_phase_a_banner_adds_narrative_worked_on_field(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _print_squad_summary

    squad_dir = tmp_path / "runs" / "spec-20260812-120000-000001"
    squad_dir.mkdir(parents=True)
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "spec_id": "014-session-security",
                "user_message": "Add sessions",
                "phase": "terminal-done",
                "completed_phases": ["phase1-what", "phase3-plan"],
            }
        ),
        encoding="utf-8",
    )

    _print_squad_summary(
        tmp_path,
        squad_dir,
        SimpleNamespace(status="done", phase="terminal-done"),
        mode="semi",
        message="Add sessions",
    )

    output = capsys.readouterr().out
    assert "Worked on" in output
    assert "Worked through 2 phases toward Add sessions." in output
