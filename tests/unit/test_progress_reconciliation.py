"""Tests for verify-spec progress reconciliation helpers."""
from __future__ import annotations

import json
from pathlib import Path

from harness.progress_reconciliation import reconcile_progress


def _tasks_md() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=engine req=FR-001 depends=none
  **Status:** PENDING
  **Title:** Implement formula

- [ ] T-002 complexity=standard phase=engine req=FR-002 depends=T-001
  **Status:** PENDING
  **Title:** Implement dependent rule

- [ ] T-003 complexity=standard phase=engine req=FR-003 depends=none
  **Status:** PENDING
  **Title:** Implement unknown task
"""


def _write_inputs(tmp_path: Path, candidate: dict[str, object]) -> tuple[Path, Path, Path]:
    tasks_path = tmp_path / "tasks.md"
    candidate_path = tmp_path / "candidate.json"
    out_dir = tmp_path / "out"
    tasks_path.write_text(_tasks_md(), encoding="utf-8")
    candidate_path.write_text(json.dumps(candidate), encoding="utf-8")
    return tasks_path, candidate_path, out_dir


def _candidate() -> dict[str, object]:
    return {
        "safe_task_updates": [
            {
                "task_id": "T-001",
                "status": "DONE",
                "evidence": "fulfillment-report.md#FR-001",
                "reason": "FR-001 is implemented",
            }
        ],
        "ambiguous_task_matches": [
            {
                "task_id": "T-003",
                "evidence": "implementation-map.md#FR-003",
                "reason": "Evidence is partial",
            }
        ],
        "fulfillment_gap_tasks": {
            "count": 55,
            "details": "specs/001-demo/reopen-1.md",
        },
        "manual_followups": [
            {
                "kind": "spec_plan_divergence",
                "details": "fulfillment-report.md#plan-spec-divergences",
            }
        ],
    }


def test_dry_run_writes_plan_without_mutating_tasks(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, _candidate())

    result = reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        dry_run=True,
    )

    assert result.safe_count == 1
    assert result.applied_count == 0
    assert "- [ ] T-001" in tasks_path.read_text(encoding="utf-8")
    plan_md = (out_dir / "progress-reconciliation-plan.md").read_text(encoding="utf-8")
    assert "fulfillment-report.md#plan-spec-divergences" in plan_md
    assert "specs/001-demo/reopen-1.md" in plan_md


def test_apply_marks_safe_tasks_done_and_validates(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, _candidate())

    result = reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        out_applied_json=out_dir / "progress-reconciliation-applied.json",
        out_applied_md=out_dir / "progress-reconciliation-applied.md",
        dry_run=False,
    )

    assert result.safe_count == 1
    assert result.applied_count == 1
    tasks_text = tasks_path.read_text(encoding="utf-8")
    assert "- [x] T-001" in tasks_text
    assert "**Status:** DONE" in tasks_text
    assert "- [ ] T-002" in tasks_text
    applied_md = (out_dir / "progress-reconciliation-applied.md").read_text(
        encoding="utf-8"
    )
    assert "T-001" in applied_md


def test_apply_skips_unknown_task_ids(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate["safe_task_updates"] = [
        {
            "task_id": "T-999",
            "status": "DONE",
            "evidence": "fulfillment-report.md#FR-999",
            "reason": "Unknown task",
        }
    ]
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, candidate)

    result = reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        out_applied_json=out_dir / "progress-reconciliation-applied.json",
        out_applied_md=out_dir / "progress-reconciliation-applied.md",
        dry_run=False,
    )

    assert result.applied_count == 0
    applied_md = (out_dir / "progress-reconciliation-applied.md").read_text(
        encoding="utf-8"
    )
    assert "unknown task id" in applied_md


def test_apply_skips_task_with_open_dependency(tmp_path: Path) -> None:
    candidate = _candidate()
    candidate["safe_task_updates"] = [
        {
            "task_id": "T-002",
            "status": "DONE",
            "evidence": "fulfillment-report.md#FR-002",
            "reason": "Dependency still open",
        }
    ]
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, candidate)

    result = reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        out_applied_json=out_dir / "progress-reconciliation-applied.json",
        out_applied_md=out_dir / "progress-reconciliation-applied.md",
        dry_run=False,
    )

    assert result.applied_count == 0
    assert "- [ ] T-002" in tasks_path.read_text(encoding="utf-8")
    applied_md = (out_dir / "progress-reconciliation-applied.md").read_text(
        encoding="utf-8"
    )
    assert "open dependency" in applied_md


def test_reports_ambiguous_and_manual_followup_paths(tmp_path: Path) -> None:
    tasks_path, candidate_path, out_dir = _write_inputs(tmp_path, _candidate())

    reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        dry_run=True,
    )

    plan_md = (out_dir / "progress-reconciliation-plan.md").read_text(encoding="utf-8")
    assert "Ambiguous Task Matches" in plan_md
    assert "implementation-map.md#FR-003" in plan_md
    assert "Manual Follow-Ups" in plan_md
    assert "fulfillment-report.md#plan-spec-divergences" in plan_md
