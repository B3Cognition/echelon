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


def test_terminal_task_summary_uses_first_non_empty_bounded_line() -> None:
    from echelon.cli import _terminal_task_summary

    message = "\n   Implement   provider-owned model selection.   \n" + ("ignored " * 50)
    assert _terminal_task_summary(message) == "Implement provider-owned model selection."

    long_message = "  " + ("deterministic provider resolution " * 10) + "\nignored"
    summary = _terminal_task_summary(long_message)
    assert len(summary) <= 160
    assert summary.endswith("…")
    assert "\n" not in summary


@pytest.mark.parametrize(
    "message",
    (
        "\x1b[31m\x1b[0m\nImplement provider-owned model selection.",
        "\x00\x07\x1f\nImplement provider-owned model selection.",
        "\x1b[31mImplement\x1b[0m provider-owned model selection.",
    ),
)
def test_terminal_task_summary_strips_controls_before_selecting_line(
    message: str,
) -> None:
    from echelon.cli import _terminal_task_summary

    assert _terminal_task_summary(message) == "Implement provider-owned model selection."


@pytest.mark.parametrize("escape_only", ("\x1bc", "\x1b(0"))
def test_terminal_task_summary_strips_non_csi_escape_only_lines(
    escape_only: str,
) -> None:
    from echelon.cli import _terminal_task_summary

    assert _terminal_task_summary(
        f"{escape_only}\nImplement provider-owned model selection."
    ) == "Implement provider-owned model selection."


def test_terminal_task_summary_preserves_normal_unicode_after_escape_cleaning() -> None:
    from echelon.cli import _terminal_task_summary

    assert _terminal_task_summary("Žluťoučký kůň 🧪") == "Žluťoučký kůň 🧪"


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
        duration="4m 12s",
        outcomes=("Implemented the session resolver.",),
        commits=("abcdef123456 — feat: implement session resolver",),
        completed_tasks=("T-001",),
        verification="failed",
        blocker="verification failed",
        provider_limit_message="Session limit resets at 17:00.",
        next_note="Retry verification after the reset.",
    )

    with worked_on_scope("delivery run", tmp_path, spec_id="014-session-security"):
        attach_to_terminal_fields([], rich, project_root=tmp_path)

    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["completed_tasks"] == ["T-001"]
    assert payload["verification"] == "failed"
    assert payload["duration"] == "4m 12s"
    assert payload["outcomes"] == ["Implemented the session resolver."]
    assert payload["commits"] == [
        "abcdef123456 — feat: implement session resolver"
    ]
    assert payload["provider_limit_message"] == "Session limit resets at 17:00."
    assert payload["next_note"] == "Retry verification after the reset."


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
    constitution = tmp_path / ".echelon" / "constitution.md"
    constitution.parent.mkdir(parents=True)
    constitution.write_text("# Constitution\n\nReady.\n", encoding="utf-8")
    spec_dir = tmp_path / "specs" / "014-session-security"
    spec_dir.mkdir(parents=True)
    for name in (
        "00-overview.md",
        "requirements-overview.md",
        "spec.md",
        "plan.md",
        "plan-conformance.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
        "constitution.md",
    ):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "plan-conformance.json").write_text(
        json.dumps(
            {
                "status": "pass",
                "findings": [],
                "sources": [
                    "spec.md",
                    "requirements-overview.md",
                    "plan.md",
                    "tasks.md",
                ],
            }
        ),
        encoding="utf-8",
    )
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "done",
                "spec_id": "014-session-security",
                "spec_dir": "specs/014-session-security",
                "user_message": "Add sessions",
                "phase": "terminal-done",
                "completed_phases": [
                    "phase1-constitution",
                    "phase1-what",
                    "phase3-plan",
                ],
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
    assert "Worked through 3 phases toward Add sessions." in output
    assert output.count("SQUAD SUMMARY") == 1
    assert output.count("Worked on") == 1
    assert "echelon · NEXT STEP" not in output
    assert "\n  next\n  ────\n" in output
    assert "echelon delivery run 014-session-security" in output
    assert output.index("Worked on") < output.index("\n  next\n")


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


def test_reported_phase_a_provider_transcript_has_one_lifecycle_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _print_squad_summary

    full_multiline_task = (
        "Replace provider-owned model selection with a proportional configuration "
        "contract while preserving every supported backend and generated artifact.\n"
        "Define deterministic precedence, validation, migration, and lossy-provider "
        "behavior for the supported providers.\n"
        "Add focused verification for configuration resolution and generated outputs."
    )
    completed_phases = [
        "phase1-constitution",
        "phase1-discover",
        "phase1-synthesize",
        "phase1-model",
        "phase1-what",
        "phase1-why1",
        "phase1-gate",
        "phase1-understanding",
        "phase1-why2",
        "checkpoint-assess",
        "phase2-architect",
        "phase2-investigate",
        "phase2-guard",
        "phase2-benchmark",
        "phase2-advocate",
        "phase2-oracle",
        "phase2-maverick",
        "phase2-consensus",
        "phase2-sentinel",
        "phase3-orchestrate",
        "phase3-verify",
        "phase3-plan",
    ]
    squad_dir = tmp_path / "runs" / "spec-20260812-120000-000001"
    squad_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(
        squad_dir.name,
        encoding="utf-8",
    )
    (squad_dir / "state.json").write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "phase3-plan",
                "user_message": full_multiline_task,
                "completed_phases": completed_phases,
                "blocked_reason": "controller_state_contract_validation_failed",
                "provider_limit_message": (
                    "You've hit your session limit · resets 5pm (Europe/Prague)"
                ),
                "recovery_instruction": {
                    "schema_version": 1,
                    "kind": "sync_runtime_then_retry",
                    "reason_code": "controller_state_contract_validation_failed",
                    "phase": "phase3-plan",
                    "requires_human_input": False,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "echelon.cli._runtime_bundle_compatibility",
        lambda _project_root: SimpleNamespace(
            compatible=True,
            command="",
            note="runtime extension is compatible",
        ),
    )

    _print_squad_summary(
        tmp_path,
        squad_dir,
        SimpleNamespace(status="blocked", phase="phase3-plan"),
        mode="semi",
        message=full_multiline_task,
    )

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert output.count("echelon · SQUAD SUMMARY") == 1
    assert "echelon · NEXT STEP" not in output
    assert "stopped    controller_state_contract_validation_failed" in output
    assert (
        "provider   You've hit your session limit · resets 5pm (Europe/Prague)"
        in output
    )
    assert full_multiline_task not in output
    assert output.casefold().count("worked on") == 1

    worked_on_heading = "\n  Worked on\n  ─────────\n"
    next_heading = "\n  next\n  ────\n"
    assert worked_on_heading in output
    assert next_heading in output
    narrative = output.split(worked_on_heading, 1)[1].split(next_heading, 1)[0]
    narrative_lines = [
        line[2:] if line.startswith("  ") else line
        for line in narrative.splitlines()
        if line.strip()
    ]
    assert 4 <= len(narrative_lines) <= 8
    assert all(
        not line.startswith(("•", "- ", "* "))
        for line in narrative_lines
    )

    embedded_next = output.split(next_heading, 1)[1]
    assert "echelon spec continue" in embedded_next


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
