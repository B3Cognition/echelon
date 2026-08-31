"""Tests for the Phase B delivery status CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_delivery_state(project_root: Path, *, strategy: str = "default") -> Path:
    state_dir = project_root / "runs" / "build-20260710-101500-000000" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{strategy}.json"
    state_file.write_text(
        json.dumps(
            {
                "spec_id": "001",
                "strategy_id": strategy,
                "status": "blocked",
                "mode": "banzai",
                "outer_iter": 2,
                "inner_iter": 1,
                "tokens_used": 1200,
                "token_budget": 4000,
                "termination_reason": "blocker_escalation",
                "build_status": "needs_answer",
                "build_reason": "Pick a provider.",
                "salvage_commit": "abcdef1234567890",
                "salvage_branch": "harness/001-salvage",
                "checkpoint_commits": [{"commit": "1234567890abcdef", "phase": "build"}],
                "escalation_file": "runs/build-20260710-101500-000000/escalation.md",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return state_file


def _write_spec(project_root: Path) -> Path:
    spec_dir = project_root / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "harness-run-history.json").write_text(
        json.dumps({"runs": [{"status": "blocked", "finished_at": "2026-07-10T10:20:00Z"}]}),
        encoding="utf-8",
    )
    return spec_dir


def _write_target_delivery_state(project_root: Path) -> Path:
    state_dir = (
        project_root
        / "runs"
        / "targets"
        / "browser-3d-game"
        / "runs"
        / "build-20260711-101500-000000"
        / "state"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "default.json"
    state_file.write_text(
        json.dumps(
            {
                "spec_id": "001",
                "strategy_id": "default",
                "status": "blocked",
                "target_repo": "browser-3d-game",
                "implementation_target": "sources/browser-3d-game",
                "outer_iter": 3,
                "inner_iter": 2,
                "tokens_used": 3939746,
                "termination_reason": "blocker_escalation",
                "build_status": "blocked",
                "build_reason": "same_failure_repeat",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return state_file


@pytest.mark.unit
def test_delivery_status_prints_latest_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_delivery_state(tmp_path)
    _write_spec(tmp_path)

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "DELIVERY STATUS" in out
    assert "Phase B delivery" in out
    assert "001" in out
    assert "blocked" in out
    assert "blocker_escalation" in out
    assert "ready_to_land" in out
    assert "echelon delivery resume 001" in out
    assert str(state_file) in out


@pytest.mark.unit
def test_delivery_status_json_filters_strategy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from echelon.cli import _cmd_delivery_status

    _write_delivery_state(tmp_path, strategy="default")
    _write_delivery_state(tmp_path, strategy="codegen")

    _cmd_delivery_status(["001", "--strategy", "codegen", "--json"], project_root=tmp_path)

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["latest"]["spec_id"] == "001"
    assert payload["latest"]["strategy"] == "codegen"
    assert payload["latest"]["next"] == 'echelon delivery resume 001 "<answer>"'
    assert len(payload["states"]) == 1


@pytest.mark.unit
def test_delivery_status_without_state_points_to_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "No delivery runs found" in out
    assert "echelon delivery run 001" in out


@pytest.mark.unit
def test_delivery_status_discovers_target_delivery_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon.cli import _cmd_delivery_status

    state_file = _write_target_delivery_state(tmp_path)
    _write_spec(tmp_path)

    _cmd_delivery_status(["001"], project_root=tmp_path)

    out = capsys.readouterr().out
    assert "browser-3d-game" in out
    assert "blocker_escalation" in out
    assert str(state_file) in out
