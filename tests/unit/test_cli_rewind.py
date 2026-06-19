"""Tests for safe squad rewind checkpoints."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.cli import _cmd_rewind


def _write_real_constitution(project_root: Path) -> None:
    const = project_root / ".specify" / "memory" / "constitution.md"
    const.parent.mkdir(parents=True)
    const.write_text("# Constitution\n\nReal project rules.\n", encoding="utf-8")


def _write_run_state(project_root: Path, state: dict) -> Path:
    run_dir = project_root / "runs" / "spec-20260618-073106-635192"
    run_dir.mkdir(parents=True)
    (project_root / "runs" / ".current").write_text(run_dir.name, encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return run_dir


def _write_phase3_spec(project_root: Path) -> Path:
    spec_dir = project_root / "specs" / "006-element-creator"
    contracts = spec_dir / "contracts"
    contracts.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "research.md").write_text("# Research\n", encoding="utf-8")
    (spec_dir / "data-model.md").write_text("# Data Model\n", encoding="utf-8")
    (contracts / "elements-crud.md").write_text("# Contract\n", encoding="utf-8")
    (spec_dir / "test-strategy.md").write_text("# Test Strategy\n", encoding="utf-8")
    (spec_dir / "test-architecture.md").write_text("# Test Architecture\n", encoding="utf-8")
    (spec_dir / "coverage-map.md").write_text("# Coverage Map\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text("# Tasks\n", encoding="utf-8")
    (spec_dir / "critical-path.md").write_text("# Critical Path\n", encoding="utf-8")
    (spec_dir / "risk-matrix.md").write_text("# Risk Matrix\n", encoding="utf-8")
    (spec_dir / "dependencies.md").write_text("# Dependencies\n", encoding="utf-8")
    return spec_dir


def test_rewind_phase3_sentinel_resets_state_and_cleans_downstream_artifacts(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    spec_dir = _write_phase3_spec(tmp_path)
    poisoned_spec_dir = (
        tmp_path
        / "runs"
        / "spec-20260618-073106-635192"
        / "specs"
        / "006-element-creator"
    )
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": str(poisoned_spec_dir),
            "completed_phases": [
                "phase3-how",
                "phase3-sentinel",
                "phase3-plan",
                "phase3-consensus",
                "checkpoint-plan",
                "phase4-document",
            ],
            "phase_dispatch_counts": {
                "phase3-how": 1,
                "phase3-sentinel": 2,
                "phase3-plan": 3,
                "phase3-consensus": 4,
                "checkpoint-plan": 1,
                "phase4-document": 1,
            },
        },
    )

    _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "running"
    assert state["phase"] == "phase3-sentinel"
    assert state["spec_dir"] == "specs/006-element-creator"
    assert state["completed_phases"] == ["phase3-how"]
    assert state["phase_dispatch_counts"] == {"phase3-how": 1}
    assert not (spec_dir / "test-strategy.md").exists()
    assert not (spec_dir / "test-architecture.md").exists()
    assert not (spec_dir / "coverage-map.md").exists()

    captured = capsys.readouterr()
    assert "REWIND PREPARED" in captured.out
    assert "phase3-sentinel" in captured.out
    assert "echelon continue" in captured.out


def test_rewind_phase3_sentinel_cleans_run_local_shadow_outputs(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_phase3_spec(tmp_path)
    run_dir = _write_run_state(
        tmp_path,
        {
            "status": "blocked",
            "phase": "terminal-blocked",
            "spec_dir": "specs/006-element-creator",
            "last_dispatch": {"phase_id": "phase3-sentinel"},
            "blocked_reason": "missing_echelon_result",
        },
    )
    run_shadow = run_dir / "specs" / "006-element-creator"
    run_shadow.mkdir(parents=True)
    for name in ("test-strategy.md", "test-architecture.md", "coverage-map.md"):
        (run_shadow / name).write_text(f"# {name}\n", encoding="utf-8")

    _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    assert not (run_shadow / "test-strategy.md").exists()
    assert not (run_shadow / "test-architecture.md").exists()
    assert not (run_shadow / "coverage-map.md").exists()


def test_rewind_phase3_sentinel_refuses_when_required_how_inputs_missing(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    spec_dir = tmp_path / "specs" / "006-element-creator"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": "specs/006-element-creator",
        },
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase3-sentinel"], project_root=tmp_path)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Cannot rewind to phase3-sentinel" in captured.err
    assert "plan.md" in captured.err


def test_rewind_rejects_unsupported_phase(
    tmp_path: Path,
    capsys,
) -> None:
    _write_real_constitution(tmp_path)
    _write_phase3_spec(tmp_path)
    _write_run_state(
        tmp_path,
        {
            "status": "done",
            "phase": "phase4-document",
            "spec_dir": "specs/006-element-creator",
        },
    )

    with pytest.raises(SystemExit) as exc:
        _cmd_rewind(["phase3-consensus"], project_root=tmp_path)

    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert "Unsupported rewind target" in captured.err
    assert "phase3-consensus" in captured.err
