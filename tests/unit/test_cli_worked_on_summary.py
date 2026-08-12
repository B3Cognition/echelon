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
    def fake_handler(_args: object) -> None:
        if handler == "_cmd_spec_run":
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            state["phase"] = "phase3-plan"
            (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    monkeypatch.setattr(f"echelon.cli.{handler}", fake_handler)
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
        with worked_on_scope("spec continue", tmp_path):
            raise SystemExit(7)

    assert exc.value.code == 7
    assert "WORKED ON" in capsys.readouterr().out


def test_delivery_scope_summarizes_failure_before_build_state_exists(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        with worked_on_scope("delivery run", tmp_path, spec_id="014-session-security"):
            raise SystemExit(2)

    assert exc.value.code == 2
    output = capsys.readouterr().err
    assert "WORKED ON" in output
    assert "014-session-security" in output


def test_deferred_delivery_scope_persists_early_failure_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "child-summary.json"
    monkeypatch.setenv("ECHELON_WORKED_ON_SUMMARY", "defer")
    monkeypatch.setenv("ECHELON_WORKED_ON_SUMMARY_FILE", str(evidence_path))

    with pytest.raises(SystemExit):
        with worked_on_scope("delivery run", tmp_path, spec_id="014-session-security"):
            raise SystemExit(2)

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["blocker"] == "delivery stopped before build state was created"


def test_deferred_rich_evidence_is_not_overwritten_by_scope_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence_path = tmp_path / "child-summary.json"
    monkeypatch.setenv("ECHELON_WORKED_ON_SUMMARY", "defer")
    monkeypatch.setenv("ECHELON_WORKED_ON_SUMMARY_FILE", str(evidence_path))
    rich = WorkedOnEvidence(
        command="delivery run",
        status="blocked",
        completed_tasks=("T-001",),
        verification="failed",
        blocker="verification failed",
    )

    with worked_on_scope("delivery run", tmp_path, spec_id="014-session-security"):
        attach_to_terminal_fields([], rich, project_root=tmp_path)

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["completed_tasks"] == ["T-001"]
    assert payload["verification"] == "failed"


def test_new_spec_preflight_failure_does_not_summarize_stale_prior_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "runs" / "spec-old"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-old", encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "spec_id": "001-old-work",
                "user_message": "Old work",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit):
        with worked_on_scope("spec run", tmp_path):
            raise SystemExit(2)

    output = capsys.readouterr().out
    assert "WORKED ON" in output
    assert "Old work" not in output
    assert "spec run stopped before new run state was created" in output


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

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Worked on" in output
    assert "Worked through 2 phases toward Add sessions." in output


def test_phase_a_banner_shows_provider_limit_beside_controller_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _print_squad_summary

    squad_dir = tmp_path / "runs" / "spec-20260812-120000-000001"
    squad_dir.mkdir(parents=True)
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase3-plan",
                "blocked_reason": "controller_state_contract_validation_failed",
                "provider_limit_message": (
                    "You've hit your session limit · resets 4am (Europe/Prague)"
                ),
            }
        ),
        encoding="utf-8",
    )

    _print_squad_summary(
        tmp_path,
        squad_dir,
        SimpleNamespace(status="blocked", phase="phase3-plan"),
        mode="semi",
        message="Implement provider model resolution",
    )

    output = capsys.readouterr().out
    assert "stopped    controller_state_contract_validation_failed" in output
    assert "provider   You've hit your session limit" in output


@pytest.mark.parametrize(
    ("argv", "handler"),
    [
        (["delivery", "run", "014-session-security"], "_cmd_harness_run"),
        (["delivery", "continue", "014-session-security"], "_cmd_harness_continue"),
        (
            ["delivery", "resume", "014-session-security", "Use option A"],
            "_cmd_harness_resume",
        ),
    ],
)
def test_delivery_lifecycle_callbacks_emit_one_summary_for_persisted_run(
    argv: list[str],
    handler: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runs = tmp_path / "runs"
    state_dir = runs / "build-20260812-120000-000001" / "state"
    state_dir.mkdir(parents=True)
    (runs / ".current-build-014-session-security").write_text(
        "build-20260812-120000-000001",
        encoding="utf-8",
    )
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "termination_reason": "build_incomplete",
                "completed_task_ids": ["T-001", "T-002"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(f"echelon.cli.{handler}", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("echelon.wiki.service.capture_input_snapshot", lambda _root: None)
    monkeypatch.setattr(
        "echelon.wiki.service.refresh_after_changed_command",
        lambda _root, _before: None,
    )

    assert run(argv) is None

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert output.count("WORKED ON") == 1
    assert "Worked through 2 tasks toward 014-session-security." in output
    assert "echelon delivery continue 014-session-security" in output
