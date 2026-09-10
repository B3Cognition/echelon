"""Tests for deterministic fulfillment-gap reopen planning."""
from __future__ import annotations

from pathlib import Path
import pytest

from harness.reopen_planner import plan_reopen_gaps
from harness.task_targets import analyze_task_targets


def _tasks_md() -> str:
    return """# Tasks

- [ ] T-001 complexity=standard phase=core req=FR-021 depends=none
  **Title:** Planned player hand UI

- [ ] T-095 complexity=standard phase=fulfillment-gap req=FR-004 depends=none
  **Title:** FG-T4.1 - Add failing test for key card type from deck draw

- [ ] T-096 complexity=standard phase=fulfillment-gap req=FR-004 depends=T-095
  **Title:** FG-T4.2 - Implement key card type from deck draw
"""


def test_reopened_tasks_inherit_unique_requirement_owner(tmp_path):
    gaps, tasks, out = _write_inputs(tmp_path, gaps="""# Gaps
| ID | Missing | Next Action |
| --- | --- | --- |
| FR-007 | Assertion missing | Add assertion |
""")
    tasks.write_text(
        "- [x] T-001 complexity=standard phase=core req=FR-007 depends=none target=sources/game\n"
        "- [x] T-002 complexity=standard phase=core req=FR-008 depends=none target=sources/other\n")
    result = plan_reopen_gaps(gaps_path=gaps, tasks_path=tasks, existing_reopen_paths=[],
                             out_plan_json=out / "plan.json", out_plan_md=out / "plan.md")
    assert result.status == "ready"
    ownership = analyze_task_targets("\n".join(task["row"] for task in result.proposed_tasks))
    assert ownership.unowned_tasks == ()
    assert ownership.target_tasks == {"sources/game": ("T-003", "T-004", "T-005")}


def test_reopen_does_not_guess_ambiguous_workspace_target(tmp_path):
    gaps, tasks, out = _write_inputs(tmp_path, gaps="""# Gaps
| ID | Missing | Next Action |
| --- | --- | --- |
| FR-007 | Assertion missing | Add assertion |
""")
    tasks.write_text(
        "- [x] T-001 complexity=standard phase=core req=FR-007 depends=none target=sources/game\n"
        "- [x] T-002 complexity=standard phase=core req=FR-007 depends=none target=sources/other\n")
    result = plan_reopen_gaps(gaps_path=gaps, tasks_path=tasks, existing_reopen_paths=[],
                             out_plan_json=out / "plan.json", out_plan_md=out / "plan.md")
    assert result.status == "manual_review"
    assert result.proposed_tasks == []
    assert "target" in result.manual_followups[0]["reason"]


@pytest.mark.parametrize("declared, rows, expected", [
    (["sources/game"], "", "sources/game"),
    (["sources/game", "sources/other"], "", None),
    (["sources/game", "sources/other"], "- [x] T-001 complexity=standard phase=core req=FR-009 depends=none target=sources/game\n", None),
    ([], "- [x] T-001 complexity=standard phase=core req=FR-009 depends=none target=sources/game\n", "sources/game"),
    (["sources/game"], "- [x] T-001 complexity=standard phase=core req=FR-007 depends=none target=sources/other\n", None),
])
def test_reopen_respects_declared_target_scope(tmp_path, declared, rows, expected):
    gaps, tasks, out = _write_inputs(tmp_path, "| FR-007 | Missing assertion | Add assertion |\n")
    tasks.write_text(rows)
    (tmp_path / "spec.md").write_text("---\ntargets: " + str(declared) + "\n---\n")
    result = plan_reopen_gaps(gaps_path=gaps, tasks_path=tasks, existing_reopen_paths=[],
                             out_plan_json=out / "plan.json", out_plan_md=out / "plan.md")
    if expected is None:
        assert result.status == "manual_review"
        assert result.proposed_tasks == []
    else:
        assert result.status == "ready"
        assert all(f"target={expected}" in task["row"] for task in result.proposed_tasks)


@pytest.mark.parametrize("files", ["sources/other/test.ts", "sources/game/test.ts, sources/other/test.ts"])
def test_reopen_does_not_inherit_conflicting_source_ownership(tmp_path, files):
    gaps, tasks, out = _write_inputs(tmp_path, "| FR-007 | Missing assertion | Add assertion |\n")
    tasks.write_text(
        "- [x] T-001 complexity=standard phase=core req=FR-007 depends=none target=sources/game\n"
        f"  **Files:**\n  {files}\n")
    result = plan_reopen_gaps(gaps_path=gaps, tasks_path=tasks, existing_reopen_paths=[],
                             out_plan_json=out / "plan.json", out_plan_md=out / "plan.md")
    assert result.status == "manual_review"
    assert result.proposed_tasks == []


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
