"""Tests for echelon spec continue phase selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.cli import _cmd_continue, _next_continue_phase


@pytest.fixture(autouse=True)
def _git_backed_workspace(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()


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
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReal project rules.\n",
        encoding="utf-8",
    )

    assert _next_continue_phase(tmp_path) is None


def test_continue_ignores_stale_ready_files_when_solution_phases_were_skipped(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "done",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": [
                "init",
                "phase1-constitution",
                "phase1-what",
                "phase1-why2",
                "phase2-decide",
                "phase2-strategic-overview",
                "phase2-tracker-alignment",
                "phase4-document",
            ],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    (spec_dir / "constitution.md").write_text("# Constitution\n\nReal project rules.\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# stale {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase3-specialists"


def test_continue_resumes_next_missing_solution_phase_even_with_ready_files(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "done",
            "spec_id": "001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": [
                "phase1-constitution",
                "phase2-tracker-alignment",
                "phase3-specialists",
                "phase4-document",
            ],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    (spec_dir / "constitution.md").write_text("# Constitution\n\nReal project rules.\n")
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# stale {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase3-how"


def test_continue_reopens_done_run_to_publish_complete_run_local_artifacts(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001",
            "spec_dir": "runs/spec-test/specs/001",
            "completed_phases": ["phase1-constitution"],
        },
    )
    active_spec_dir = run_dir / "specs" / "001"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-themed-ascii-animation"
    published_spec_dir.mkdir(parents=True)
    (published_spec_dir / "spec.md").write_text("# stale published spec\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase4-document"


def test_continue_reopens_done_run_when_explicit_run_local_spec_has_unpublished_artifact(
    tmp_path: Path,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "spec_id": "001-demo",
            "spec_dir": "runs/spec-test/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "completed_phases": ["phase1-constitution"],
        },
    )
    active_spec_dir = run_dir / "specs" / "001-demo"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (active_spec_dir / "user-intent.md").write_text("# User Intent\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-demo"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (published_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) == "phase4-document"


def test_continue_does_not_apply_retired_re_generation_recovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "re_generation_mismatch",
            "spec_id": "001-demo",
            "spec_dir": "runs/spec-test/specs/001-demo",
            "published_spec_dir": "specs/001-demo",
            "re_generation": 0,
            "re_generation_expected": 0,
            "re_generation_actual": 1,
            "completed_phases": ["phase1-constitution"],
            "user_message": "build the dashboard",
            "autonomy_mode": "banzai",
        },
    )
    (tmp_path / "re").mkdir()
    (tmp_path / "re" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generation": 1,
                "publication_status": "partial",
                "published_at": "2026-07-15T12:00:00+00:00",
                "published_from_run": run_dir.name,
                "sources": {},
                "workspace": {
                    "manifest": "re/workspace/manifest.json",
                    "overview": "re/workspace/overview.md",
                    "relationships": "re/workspace/relationships.md",
                    "contracts": "re/workspace/contracts.md",
                },
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    active_spec_dir = run_dir / "specs" / "001-demo"
    active_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (active_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    (active_spec_dir / "user-intent.md").write_text("# User Intent\n", encoding="utf-8")

    published_spec_dir = tmp_path / "specs" / "001-demo"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
    ):
        (published_spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "blocked"
    assert state["phase"] == "terminal-blocked"
    assert state["re_generation"] == 0
    assert state["blocked_reason"] == "re_generation_mismatch"
    assert calls == []


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
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")
    published_spec_dir = tmp_path / "specs" / "071-rule-studio-narrative"
    published_spec_dir.mkdir(parents=True)
    for name in (
        "spec.md", "plan.md", "research.md", "data-model.md", "tasks.md",
        "test-strategy.md", "test-architecture.md", "coverage-map.md",
    ):
        (published_spec_dir / name).write_text(f"# published {name}\n", encoding="utf-8")
    (published_spec_dir / "constitution.md").write_text(
        "# Constitution\n\nReal project rules.\n",
        encoding="utf-8",
    )

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
    assert 'echelon spec rewind phase3-sentinel' in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


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
            "implementation_targets": [
                "sources/pressbox-search",
                "sources/pressbox-search-api",
            ],
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
    assert calls == [[
        "make terminal ascii art",
        "--mode",
        "semi",
        "--target",
        "sources/pressbox-search",
        "--target",
        "sources/pressbox-search-api",
    ]]


def test_continue_provider_session_limit_retries_incomplete_phase(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "provider_session_limit",
            "provider_limit_message": "You've hit your session limit · resets 4am (Europe/Prague)",
            "last_dispatch": {"phase_id": "phase3-consensus"},
            "completed_phases": ["phase1-constitution", "phase3-plan"],
            "user_message": "style the CLI output",
            "autonomy_mode": "banzai",
        },
    )

    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    captured = capsys.readouterr()
    assert calls == [["style the CLI output", "--mode", "banzai"]]
    assert "Retrying incomplete phase" in captured.out


def test_continue_blocks_new_branchless_workspace(
    tmp_path: Path,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        _cmd_continue(["--mode", "banzai"], project_root=tmp_path, ext_dir=tmp_path)

    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err
    assert "echelon spec continue --mode banzai" in err


def test_continue_allows_legacy_branchless_running_recovery(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    _write_run_state(
        tmp_path,
        {
            "status": "running",
            "phase": "phase1-what",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
        },
    )

    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path)

    assert calls == [["build the dashboard", "--mode", "semi"]]
    err = capsys.readouterr().err
    assert "legacy branchless run detected; continuing for recovery only" in err


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
    assert 'echelon spec resume "<your answer>"' not in captured.out
    assert calls == [["make terminal ascii art", "--mode", "semi"]]


def test_continue_ignores_legacy_nested_re_state_during_outer_escalation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "escalation_question": "Possible routing loop. How should I proceed?",
            "last_dispatch": {"phase_id": "phase1-discover"},
            "completed_phases": ["init"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "banzai",
        },
    )
    re_state = run_dir / "re" / "state.json"
    re_state.parent.mkdir(parents=True)
    re_state.write_text(
        json.dumps(
            {
                "status": "blocked",
                "phase": "re-extract-2-specify",
                "blocked_reason": "re_quality_repair_modified_non_target_output",
            }
        ),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_cmd_run(args, project_root, ext_dir):
        calls.append(args)

    monkeypatch.setattr("echelon.cli._cmd_run", fake_cmd_run)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "terminal-blocked"
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "phase_dispatch_limit"
    assert 'echelon spec resume "<your answer>"' in capsys.readouterr().out
    assert calls == []


def test_continue_explains_how_to_recover_from_phase_dispatch_limit(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "phase_dispatch_limit",
            "escalation_question": (
                "Phase 'phase1-what' has been dispatched 6 times (limit 5) "
                "without converging or advancing. Possible routing loop. "
                "How should I proceed?"
            ),
            "phase_dispatch_limit_phase": "phase1-what",
            "phase_dispatch_limit": 5,
            "phase_dispatch_counts": {"phase1-what": 6},
            "last_dispatch": {"phase_id": "phase1-why2"},
            "completed_phases": ["init"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "semi",
        },
    )

    monkeypatch.setattr("echelon.cli._cmd_run", lambda *args, **kwargs: None)

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    output = capsys.readouterr().out
    assert "authorize one targeted retry of phase1-what" in output.lower()
    assert "latest issues.md findings" in output
    assert 'echelon spec resume "Authorize one targeted retry of phase1-what' in output


def test_continue_ignores_legacy_nested_re_state_for_active_spec_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "running",
            "phase": "phase1-what",
            "blocked_reason": None,
            "completed_phases": ["init", "phase1-constitution"],
            "user_message": "reverse engineer the workspace",
            "autonomy_mode": "banzai",
        },
    )
    re_state = run_dir / "re" / "state.json"
    re_state.parent.mkdir(parents=True)
    re_state.write_text(
        json.dumps({"status": "blocked", "phase": "re-extract-2-specify"}),
        encoding="utf-8",
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "echelon.cli._cmd_run",
        lambda args, project_root, ext_dir: calls.append(args),
    )

    _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path / ".specify/extensions/echelon")

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["phase"] == "phase1-what"
    assert calls == [["reverse engineer the workspace", "--mode", "banzai"]]


def test_continue_blocks_branchless_completed_run_from_starting_new_phase(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    (tmp_path / ".git").rmdir()
    source = tmp_path / "og-platform"
    source.mkdir()
    (source / ".git").mkdir()
    (source / "package.json").write_text("{}", encoding="utf-8")
    _write_real_constitution(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "DONE",
            "user_message": "build the dashboard",
            "autonomy_mode": "semi",
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

    with pytest.raises(SystemExit) as exc:
        _cmd_continue([], project_root=tmp_path, ext_dir=tmp_path)

    assert exc.value.code == 2
    assert calls == []
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"
    err = capsys.readouterr().err
    assert "workspace root is not a Git repo" in err


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
    assert "echelon spec rewind phase3-sentinel" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


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
    assert "inspect echelon spec status, then choose a recovery action" in captured.out
    assert 'echelon spec resume "<your answer>"' not in captured.out


def test_continue_retries_external_blocker_phase_after_fix(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "blocked_reason": "Understanding extension unavailable — required for WHY2/WHY3 spec validation",
            "last_dispatch": {"phase_id": "phase1-why2"},
            "completed_phases": ["phase1-constitution", "phase1-what"],
            "user_message": "build search dashboard",
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
    assert state["phase"] == "phase1-why2"
    assert state["status"] == "running"
    assert state["blocked_reason"] is None
    assert "Retrying incomplete phase phase1-why2" in captured.out
    assert calls == [["build search dashboard", "--mode", "semi"]]


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
