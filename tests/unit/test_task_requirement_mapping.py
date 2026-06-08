"""Tests for deterministic task requirement metadata mapping."""
from __future__ import annotations

import json
from pathlib import Path

from harness.task_requirement_mapping import apply_task_requirement_mapping


def _tasks_md() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=engine req=UNMAPPED depends=none
  **Status:** PENDING
  **Title:** Implement formula

- [ ] T-002 [P] complexity=standard phase=engine req=UNMAPPED depends=T-001
  **Status:** PENDING
  **Title:** Implement grid
"""


def _write_inputs(tmp_path: Path, candidate: dict[str, object]) -> tuple[Path, Path, Path]:
    tasks_path = tmp_path / "tasks.md"
    candidate_path = tmp_path / "task-requirement-map.candidates.json"
    out_dir = tmp_path / "out"
    tasks_path.write_text(_tasks_md(), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    return tasks_path, candidate_path, out_dir


def test_dry_run_writes_plan_without_mutating_tasks(tmp_path: Path) -> None:
    candidate = {
        "task_requirement_mappings": [
            {
                "task_id": "T-001",
                "requirements": ["FR-001", "US1-AC1"],
                "evidence": "tasks.md T-001 files + fulfillment-report.md FR-001",
                "reason": "Task owns CourseFormula implementation",
            }
        ]
    }
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, candidate)

    result = apply_task_requirement_mapping(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "task-requirement-map-plan.json",
        out_plan_md=out_dir / "task-requirement-map-plan.md",
        dry_run=True,
    )

    assert result.safe_count == 1
    assert result.applied_count == 0
    assert "req=UNMAPPED" in tasks_path.read_text(encoding="utf-8")
    plan_md = (out_dir / "task-requirement-map-plan.md").read_text(encoding="utf-8")
    assert "T-001" in plan_md
    assert "FR-001,US1-AC1" in plan_md


def test_apply_updates_req_metadata_and_preserves_progress(tmp_path: Path) -> None:
    candidate = {
        "task_requirement_mappings": [
            {
                "task_id": "T-001",
                "requirements": ["FR-001"],
                "evidence": "fulfillment-report.md#FR-001",
                "reason": "Implemented formula task",
            },
            {
                "task_id": "T-002",
                "requirements": ["FR-003", "EDGE-003"],
                "evidence": "fulfillment-report.md#FR-003",
                "reason": "Grid task owns crossing requirements",
            },
        ]
    }
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, candidate)

    result = apply_task_requirement_mapping(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "task-requirement-map-plan.json",
        out_plan_md=out_dir / "task-requirement-map-plan.md",
        out_applied_json=out_dir / "task-requirement-map-applied.json",
        out_applied_md=out_dir / "task-requirement-map-applied.md",
        dry_run=False,
    )

    assert result.safe_count == 2
    assert result.applied_count == 2
    text = tasks_path.read_text(encoding="utf-8")
    assert "- [ ] T-001 complexity=standard phase=engine req=FR-001 depends=none" in text
    assert "- [ ] T-002 [P] complexity=standard phase=engine req=FR-003,EDGE-003 depends=T-001" in text
    assert "**Status:** PENDING" in text


def test_skips_unknown_task_and_invalid_requirement(tmp_path: Path) -> None:
    candidate = {
        "task_requirement_mappings": [
            {
                "task_id": "T-999",
                "requirements": ["FR-001"],
                "evidence": "fulfillment-report.md#FR-001",
                "reason": "Unknown task",
            },
            {
                "task_id": "T-001",
                "requirements": ["not a requirement"],
                "evidence": "fulfillment-report.md#FR-001",
                "reason": "Bad requirement id",
            },
        ]
    }
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, candidate)

    result = apply_task_requirement_mapping(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "task-requirement-map-plan.json",
        out_plan_md=out_dir / "task-requirement-map-plan.md",
        out_applied_json=out_dir / "task-requirement-map-applied.json",
        out_applied_md=out_dir / "task-requirement-map-applied.md",
        dry_run=False,
    )

    assert result.applied_count == 0
    assert "req=UNMAPPED" in tasks_path.read_text(encoding="utf-8")
    applied_md = (out_dir / "task-requirement-map-applied.md").read_text(
        encoding="utf-8"
    )
    assert "unknown task id" in applied_md
    assert "invalid requirement id" in applied_md
