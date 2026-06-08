"""Prompt contract tests for reopen safety."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REOPEN_PHASE = ROOT / "extension" / "workflow" / "phases" / "reopen-1-apply-gaps.md"


def test_reopen_phase_forbids_per_row_gap_expansion() -> None:
    text = REOPEN_PHASE.read_text(encoding="utf-8")

    assert "NEVER create one task sequence per fulfillment-report row" in text
    assert "Cluster rows by root cause" in text
    assert "future planned-phase missing work is not a fulfillment-gap task" in text


def test_reopen_phase_stops_when_existing_reopen_covers_gaps() -> None:
    text = REOPEN_PHASE.read_text(encoding="utf-8")

    assert "STOP without mutating `tasks.md`" in text
    assert "existing `reopen-*.md`" in text
    assert "no new actionable root-cause clusters" in text


def test_reopen_phase_has_task_append_safety_cap() -> None:
    text = REOPEN_PHASE.read_text(encoding="utf-8")

    assert "maximum of 20 new root-cause sequences" in text
    assert "maximum of 60 executable task rows" in text
    assert "write `reopen-{n}.md` as a no-op/manual-review summary" in text


def test_reopen_phase_requires_deterministic_planner_before_mutation() -> None:
    text = REOPEN_PHASE.read_text(encoding="utf-8")

    assert "python -m harness plan-reopen-gaps" in text
    assert "Read `{spec_dir}/reopen-plan/reopen-plan.json`" in text
    assert "Treat it as authoritative" in text
    assert "append only the exact `proposed_tasks[*].row` rows" in text
    assert "If `status` is `manual_review`, do not append tasks" in text
