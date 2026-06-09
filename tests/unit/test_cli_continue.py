"""Tests for echelon continue phase selection."""

from __future__ import annotations

import json
from pathlib import Path

from echelon.cli import _next_continue_phase


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
            "completed_phases": ["phase1-constitution"],
        },
    )
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "quality-gates.md").write_text("# Quality Gates\n\n## Verdict: PASS\n")
    for name in ("plan.md", "research.md", "data-model.md", "tasks.md"):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    assert _next_continue_phase(tmp_path) is None
