"""Tests for echelon continue phase selection."""

from __future__ import annotations

import json
from pathlib import Path

from echelon.cli import _cmd_continue, _next_continue_phase


def _write_run_state(project_root: Path, state: dict) -> Path:
    run_dir = project_root / "runs" / "spec-test"
    run_dir.mkdir(parents=True)
    (project_root / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir


def _write_real_constitution(project_root: Path) -> None:
    const = project_root / ".specify" / "memory" / "constitution.md"
    const.parent.mkdir(parents=True)
    const.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")


def test_continue_routes_to_constitution_without_phase_provenance(tmp_path: Path) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "completed_phases": ["phase1-what", "phase1-why2"],
        },
    )

    assert _next_continue_phase(tmp_path) == "phase1-constitution"


def test_continue_allows_ready_spec_after_constitution_provenance(tmp_path: Path) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) is None


def test_continue_does_not_honor_stale_recommendation_when_build_is_ready(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "terminal-blocked",
            "spec_id": "071-rule-studio-narrative",
            "completed_phases": ["phase1-constitution"],
            "convergence_forced": True,
            "phase_recommendation": "advance_past_consensus_to_delivery",
        },
    )
    spec_dir = tmp_path / "runs" / "spec-test" / "specs" / "071-rule-studio-narrative"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n"
        "## Verdict: FAIL\n\n"
        "| Gate | Score | Threshold | Status | Notes |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Structure | 0.677 | 0.75 | FAIL | not borderline |\n",
        encoding="utf-8",
    )
    for name in ("spec.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) is None


def test_continue_reopens_completed_run_in_same_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-how"
    assert state["spec_dir"] == "runs/spec-test/specs/001-demo"
    assert state["published_spec_dir"] == "specs/001-demo"
    assert state["spec_id"] == "001-demo"
    assert (run_dir / "specs" / "001-demo" / "quality-gates.md").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_sets_active_run_spec_context_for_phase3_resume_from_published_spec(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_dir": "specs/007-american-football-element",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "007-american-football-element"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n", encoding="utf-8")
    for name in ("plan.md", "research.md", "data-model.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase3-plan"
    assert state["status"] == "running"
    assert state["spec_dir"] == "runs/spec-test/specs/007-american-football-element"
    assert state["published_spec_dir"] == "specs/007-american-football-element"
    assert state["spec_id"] == "007-american-football-element"
    assert (run_dir / "specs" / "007-american-football-element" / "plan.md").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_does_not_guess_latest_spec_when_multiple_specs_exist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "007-american-football-element",
            "completed_phases": ["phase1-constitution"],
        },
    )
    selected = tmp_path / "specs" / "007-american-football-element"
    selected.mkdir(parents=True)
    (selected / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n", encoding="utf-8")
    newer = tmp_path / "specs" / "999-unrelated-latest"
    newer.mkdir(parents=True)
    for name in ("quality-gates.md", "plan.md", "research.md", "data-model.md", "tasks.md"):
        (newer / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase3-how"
    assert state["spec_dir"] == "runs/spec-test/specs/007-american-football-element"
    assert state["spec_id"] == "007-american-football-element"
    assert not (run_dir / "specs" / "999-unrelated-latest").exists()
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_repairs_tracker_done_before_missing_how_artifacts(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-decide",
                "phase2-tracker-alignment",
            ],
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    (spec_dir / "intent-alignment-check.md").write_text(
        "# Intent Alignment\n\n- Verdict: ALIGNED\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) == "phase3-specialists"


def test_cmd_continue_resumes_tracker_repair_at_specialists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
            "spec_id": "001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-decide",
                "phase2-tracker-alignment",
            ],
        },
    )
    spec_dir = run_dir / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "quality-gates.md").write_text(
        "# Quality Gates\n\n## Verdict: PASS\n",
        encoding="utf-8",
    )
    (spec_dir / "intent-alignment-check.md").write_text(
        "# Intent Alignment\n\n- Verdict: ALIGNED\n",
        encoding="utf-8",
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-specialists"
    assert calls == [["build the dashboard", "--mode", "semi"]]


def test_continue_blocked_non_escalation_run_points_to_rewind(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_echelon_result",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "completed_phases": ["phase1-constitution", "phase3-how"],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert 'echelon rewind phase3-sentinel' in captured.out
    assert 'echelon resume "<your answer>"' not in captured.out


def test_continue_retries_incomplete_phase_before_constitution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "missing_echelon_result",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    assert _next_continue_phase(tmp_path) == "phase1-discover"

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert state["escalation_question"] is None
    assert calls == [["make terminal ascii art", "--mode", "semi"]]


def test_continue_retries_timeout_without_resume_dead_end(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "agent_timeout",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert 'echelon resume "<your answer>"' not in captured.out
    assert calls == [["make terminal ascii art", "--mode", "semi"]]


def test_continue_points_retryable_phase3_failure_to_rewind(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "agent_exit_code_1",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "completed_phases": ["phase1-constitution", "phase3-how"],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "echelon rewind phase3-sentinel" in captured.out
    assert 'echelon resume "<your answer>"' not in captured.out


def test_continue_manual_block_does_not_claim_human_resume(
    tmp_path: Path,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_a_readiness_failed",
            "completed_phases": ["phase1-constitution"],
        },
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert "Manual recovery required" in captured.out
    assert "fix the blocker, then echelon continue" in captured.out
    assert 'echelon resume "<your answer>"' not in captured.out


def test_continue_retries_interrupted_phase(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "interrupted",
            "phase": "phase1-discover",
            "interrupted_phase": "phase1-discover",
            "completed_phases": ["init"],
            "user_message": "make terminal ascii art",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-discover"
    assert state["status"] == "running"
    assert calls == [["make terminal ascii art", "--mode", "semi"]]
