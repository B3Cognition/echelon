"""Tests for deterministic fulfillment-gap reopen planning."""
from __future__ import annotations

from pathlib import Path

from harness.reopen_planner import plan_reopen_gaps


def _tasks_md() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=core req=FR-021 depends=none
  **Title:** Planned player hand UI

- [ ] T-095 complexity=standard phase=fulfillment-gap req=FR-004 depends=none
  **Title:** FG-T4.1 - Add failing test for key card type from deck draw

- [ ] T-096 complexity=standard phase=fulfillment-gap req=FR-004 depends=T-095
  **Title:** FG-T4.2 - Implement key card type from deck draw
"""


def _gaps_md() -> str:
    return """# Fulfillment Gaps

## PARTIAL Gaps (specific missing element per item)

### Engine Layer

| ID | What Is Missing | Next Action |
|----|----------------|-------------|
| FR-004 | Awarded key card type hardcoded to `.gonio` | Award key by drawing from DeckDisposition |
| FR-007 | `deploy_targets_offered` event not defined | Add event and wire SettlerLogic |
| US1-AC3 | `deploy_targets_offered` event absent | See FR-007 next action |
| TASK-PROGRESS | 0/157 marked complete | Reconcile task progress |

## MISSING Gaps (grouped by implementation phase)

### Phase 3 — UI Layer

| ID | What Is Missing | Next Action |
|----|----------------|-------------|
| FR-021 | No UI renders player hand | Implement hand view |

## UNVERIFIED Gaps (positive guard required)

| ID | Status | What Is Missing | Next Action |
|----|--------|----------------|-------------|
| FR-046 | UNVERIFIED | No positive CI gate | Add static-analysis CI gate |
"""


def _write_inputs(tmp_path: Path, gaps: str | None = None) -> tuple[Path, Path, Path]:
    tasks_path = tmp_path / "tasks.md"
    gaps_path = tmp_path / "fulfillment-gaps.md"
    out_dir = tmp_path / "out"
    tasks_path.write_text(_tasks_md(), encoding="utf-8")
    gaps_path.write_text(gaps if gaps is not None else _gaps_md(), encoding="utf-8")
    return gaps_path, tasks_path, out_dir


def test_plans_only_new_root_cause_clusters_and_dedupes_existing_work(
    tmp_path: Path,
) -> None:
    gaps_path, tasks_path, out_dir = _write_inputs(tmp_path)

    result = plan_reopen_gaps(
        gaps_path=gaps_path,
        tasks_path=tasks_path,
        existing_reopen_paths=[],
        out_plan_json=out_dir / "reopen-plan.json",
        out_plan_md=out_dir / "reopen-plan.md",
    )

    assert result.status == "ready"
    assert [cluster["primary_req"] for cluster in result.clusters] == [
        "FR-007",
        "TASK-PROGRESS",
        "FR-046",
    ]
    assert [task["task_id"] for task in result.proposed_tasks] == [
        "T-097",
        "T-098",
        "T-099",
        "T-100",
        "T-101",
        "T-102",
        "T-103",
    ]
    assert result.proposed_tasks[1]["row"].endswith("depends=T-097")
    assert result.proposed_tasks[3]["row"] == (
        "- [ ] T-100 complexity=standard phase=fulfillment-gap "
        "req=TASK-PROGRESS depends=none"
    )
    assert all(cluster["primary_req"] != "FR-004" for cluster in result.clusters)
    assert all(cluster["primary_req"] != "US1-AC3" for cluster in result.clusters)
    assert all(cluster["primary_req"] != "FR-021" for cluster in result.clusters)
    assert {
        "id": "US1-AC3",
        "section": "Engine Layer",
        "reason": "cross-reference row folded into controlling gap",
    } in result.skipped
    plan_md = (out_dir / "reopen-plan.md").read_text(encoding="utf-8")
    assert "covered by existing fulfillment-gap task" in plan_md
    assert "planned work already exists" in plan_md


def test_oversized_plan_is_manual_review_and_appends_no_tasks(tmp_path: Path) -> None:
    rows = "\n".join(
        f"| FR-{i:03d} | Missing behavior {i} | Implement behavior {i} |"
        for i in range(1, 25)
    )
    gaps = (
        "# Fulfillment Gaps\n\n"
        "## PARTIAL Gaps\n\n"
        "| ID | What Is Missing | Next Action |\n"
        "|----|----------------|-------------|\n"
        f"{rows}\n"
    )
    gaps_path, tasks_path, out_dir = _write_inputs(tmp_path, gaps)

    result = plan_reopen_gaps(
        gaps_path=gaps_path,
        tasks_path=tasks_path,
        existing_reopen_paths=[],
        out_plan_json=out_dir / "reopen-plan.json",
        out_plan_md=out_dir / "reopen-plan.md",
    )

    assert result.status == "manual_review"
    assert result.task_rows_to_append == 0
    assert "exceeds safety cap" in result.reason


def test_existing_reopen_summary_covers_matching_requirement(tmp_path: Path) -> None:
    gaps_path, tasks_path, out_dir = _write_inputs(tmp_path)
    reopen = tmp_path / "reopen-1.md"
    reopen.write_text("| FG-T3 | Gap 1-C | FR-007 | Event wiring |\n", encoding="utf-8")

    result = plan_reopen_gaps(
        gaps_path=gaps_path,
        tasks_path=tasks_path,
        existing_reopen_paths=[reopen],
        out_plan_json=out_dir / "reopen-plan.json",
        out_plan_md=out_dir / "reopen-plan.md",
    )

    assert [cluster["primary_req"] for cluster in result.clusters] == [
        "TASK-PROGRESS",
        "FR-046",
    ]
    plan_md = (out_dir / "reopen-plan.md").read_text(encoding="utf-8")
    assert "covered by existing reopen summary" in plan_md


def test_manual_decision_rows_do_not_generate_tasks(tmp_path: Path) -> None:
    gaps = """# Fulfillment Gaps

| ID | What Is Missing | Next Action |
|----|----------------|-------------|
| FR-006 | Arrival radius divergence: code uses 0.163 ly, spec says 0.05 ly | CARTOGRAPHER decision before implementation |
"""
    gaps_path, tasks_path, out_dir = _write_inputs(tmp_path, gaps)

    result = plan_reopen_gaps(
        gaps_path=gaps_path,
        tasks_path=tasks_path,
        existing_reopen_paths=[],
        out_plan_json=out_dir / "reopen-plan.json",
        out_plan_md=out_dir / "reopen-plan.md",
    )

    assert result.status == "manual_review"
    assert result.clusters == []
    assert result.proposed_tasks == []
    assert result.task_rows_to_append == 0
    assert result.manual_followups == [
        {
            "id": "FR-006",
            "section": "",
            "reason": "manual spec/code decision required",
            "missing": "Arrival radius divergence: code uses 0.163 ly, spec says 0.05 ly",
            "next_action": "CARTOGRAPHER decision before implementation",
        }
    ]
