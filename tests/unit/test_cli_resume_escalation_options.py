"""Regression tests for executable squad escalation options."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest


def _write_blocked_run(tmp_path: Path, options: list[dict]) -> Path:
    run_dir = tmp_path / "runs" / "spec-20260619-111111-000001"
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "status": "blocked",
                "phase": "checkpoint-assess",
                "autonomy_mode": "semi",
                "user_message": "make ascii art",
                "staging_dir": str(staging_dir),
                "blocked_reason": "checkpoint-assess human gate",
                "escalation_question": "A: return to WHAT\nB: proceed",
                "escalation_options": options,
                "completed_phases": ["phase1-constitution", "phase1-what", "phase1-why2"],
            }
        ),
        encoding="utf-8",
    )
    return run_dir


def _patch_resume_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    config_mod = types.ModuleType("harness.config")
    config_mod.load_config = lambda *a, **k: {}
    config_mod.get_full_resolved_config = lambda *a, **k: {}

    phase_graph_mod = types.ModuleType("harness.phase_graph")

    class FakePhaseGraph:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def all_phase_ids(self) -> list[str]:
            return [
                "phase1-constitution",
                "phase1-what",
                "phase1-why2",
                "checkpoint-assess",
                "phase2-decide",
                "DONE",
            ]

    phase_graph_mod.PhaseGraph = FakePhaseGraph

    provider_mod = types.ModuleType("harness.squad_provider")

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

    provider_mod.SquadCliProvider = FakeProvider

    squad_mod = types.ModuleType("harness.squad")

    class FakeSquadController:
        def __init__(self, **kwargs) -> None:
            self._state_store = kwargs["state_store"]

        def run(self, user_message: str = "", mode: str = "semi", next_phase_override: str = ""):
            state = self._state_store.load()
            return SimpleNamespace(
                status=state.get("status", "running"),
                phase=state.get("phase", "?"),
                run_id=state.get("run_id", ""),
            )

    squad_mod.SquadController = FakeSquadController

    monkeypatch.setitem(sys.modules, "harness.config", config_mod)
    monkeypatch.setitem(sys.modules, "harness.phase_graph", phase_graph_mod)
    monkeypatch.setitem(sys.modules, "harness.squad_provider", provider_mod)
    monkeypatch.setitem(sys.modules, "harness.squad", squad_mod)


def test_resume_option_a_routes_to_offered_next_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_back_to_what",
                "label": "Return to WHAT",
                "next_phase": "phase1-what",
            },
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            },
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(["A"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase1-what"
    assert state["escalation_resolved"] is True
    assert state["escalation_selected_option"] == "route_back_to_what"
    assert state["resume_metadata"]["answer_type"] == "choice"
    assert state["resume_metadata"]["selected_option_id"] == "route_back_to_what"
    assert state["resume_metadata"]["blocked_phase"] == "checkpoint-assess"
    assert state["resume_metadata"]["resumed_phase"] == "phase1-what"
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["blocked_decision"]["resolved_by"] == "user"
    assert state["escalation_question"] is None


def test_resume_rejects_option_with_invalid_next_phase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_to_nowhere",
                "label": "Return to missing phase",
                "next_phase": "phase-does-not-exist",
            }
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["A"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert exc.value.code == 1
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "checkpoint-assess"
    assert state["escalation_question"] == "A: return to WHAT\nB: proceed"
    captured = capsys.readouterr()
    assert "not an executable phase" in captured.err


def test_resume_rejects_unmatched_answer_when_structured_options_exist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "route_back_to_what",
                "label": "Return to WHAT",
                "next_phase": "phase1-what",
            },
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            },
        ],
    )
    _patch_resume_dependencies(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        _cmd_resume(["surprise third path"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    assert exc.value.code == 1
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "checkpoint-assess"
    assert "escalation_selected_option" not in state
    captured = capsys.readouterr()
    assert "does not match any executable escalation option" in captured.err


def test_resume_accepts_free_text_decision_without_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, options=[])
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(
        ["Use a narrower audience and keep missions under 10 minutes."],
        project_root=tmp_path,
        ext_dir=Path.cwd() / "extension",
    )

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "checkpoint-assess"
    assert state["escalation_question"] is None
    assert state["blocked_decision"]["answer_type"] == "free_text"
    assert state["blocked_decision"]["status"] == "resolved"
    assert state["resume_metadata"]["answer_type"] == "free_text"
    assert state["resume_metadata"]["answer_text"] == (
        "Use a narrower audience and keep missions under 10 minutes."
    )


def test_resume_uses_existing_blocked_decision_after_process_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(
        tmp_path,
        [
            {
                "id": "proceed_anyway",
                "label": "Proceed to DECIDE",
                "next_phase": "phase2-decide",
            }
        ],
    )
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["blocked_decision"] = {
        "schema_version": 1,
        "status": "pending",
        "answer_type": "choice",
        "question": state["escalation_question"],
        "blocked_reason": state["blocked_reason"],
        "blocked_phase": state["phase"],
        "blocked_at": "2026-06-23T10:00:00+00:00",
        "options": state["escalation_options"],
        "recommended_answer": "proceed_anyway",
        "default_answer": "proceed_anyway",
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)

    _cmd_resume(["proceed_anyway"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed["phase"] == "phase2-decide"
    assert resumed["blocked_decision"]["blocked_at"] == "2026-06-23T10:00:00+00:00"
    assert resumed["blocked_decision"]["status"] == "resolved"
    assert resumed["resume_metadata"]["selected_option_id"] == "proceed_anyway"


def test_resume_terminal_block_delegates_to_continue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon.cli import _cmd_resume

    run_dir = _write_blocked_run(tmp_path, options=[])
    state_path = run_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["phase"] = "terminal-blocked"
    state["blocked_decision"] = {
        "schema_version": 1,
        "status": "pending",
        "answer_type": "free_text",
        "question": state["escalation_question"],
        "blocked_reason": state["blocked_reason"],
        "blocked_phase": state["phase"],
        "blocked_at": "2026-06-23T10:00:00+00:00",
        "options": [],
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")
    _patch_resume_dependencies(monkeypatch)

    calls: list[tuple[list[str], Path, Path]] = []

    def fake_continue(args, project_root, ext_dir):
        calls.append((args, project_root, ext_dir))

    monkeypatch.setattr("echelon.cli._cmd_continue", fake_continue)

    _cmd_resume(["retry with narrower scope"], project_root=tmp_path, ext_dir=Path.cwd() / "extension")

    resumed = json.loads(state_path.read_text(encoding="utf-8"))
    assert resumed["status"] == "running"
    assert resumed["phase"] == "terminal-blocked"
    assert resumed["blocked_reason"] is None
    assert resumed["blocked_decision"]["status"] == "resolved"
    assert calls == [([], tmp_path, Path.cwd() / "extension")]
