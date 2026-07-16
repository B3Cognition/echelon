"""Tests for canonical tasks.md progress tracking."""

from __future__ import annotations

import pytest

from harness.task_progress import (
    TaskProgressError,
    summarize_task_progress,
    update_task_progress_markdown,
)


TASKS = """# Tasks: Demo

- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none

  **Title:** Scaffold app

  **Acceptance Criteria:**
  - [ ] App target exists
  - [ ] Smoke test passes

- [ ] T-002 [P] complexity=complex phase=core req=FR-001 depends=T-001

  **Title:** Implement core flow

  **Acceptance Criteria:**
  - [ ] Core flow works
"""


@pytest.mark.unit
class TestTaskProgress:
    def test_updates_canonical_row_and_nested_checkboxes_for_done_task(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-001", "DONE")

        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in updated
        assert "  **Status:** DONE" in updated
        assert "  - [x] App target exists" in updated
        assert "  - [x] Smoke test passes" in updated
        assert "- [ ] T-002 [P] complexity=complex phase=core req=FR-001 depends=T-001" in updated
        assert "  - [ ] Core flow works" in updated

    def test_blocked_task_keeps_canonical_row_unchecked_and_records_status(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-002", "BLOCKED")

        assert "- [ ] T-002 [P] complexity=complex phase=core req=FR-001 depends=T-001" in updated
        assert "  **Status:** BLOCKED" in updated
        assert "  - [ ] Core flow works" in updated

    def test_progress_update_preserves_explicit_target_metadata(self) -> None:
        tasks = TASKS.replace(
            "depends=none",
            "depends=none target=sources/app",
            1,
        )

        updated = update_task_progress_markdown(tasks, "T-001", "DONE")

        assert (
            "- [x] T-001 complexity=standard phase=foundation req=INFRA "
            "depends=none target=sources/app"
        ) in updated

    def test_deferred_task_is_terminal_but_not_completed(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-001", "DEFERRED")

        summary = summarize_task_progress(updated)

        assert "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none" in updated
        assert "  **Status:** DEFERRED" in updated
        assert summary.completed_tasks == 0
        assert summary.deferred_tasks == 1
        assert summary.terminal_tasks == 1

    def test_update_replaces_existing_status_idempotently(self) -> None:
        first = update_task_progress_markdown(TASKS, "T-001", "DONE")
        second = update_task_progress_markdown(first, "T-001", "DEGRADED")

        assert second.count("**Status:**") == 1
        assert "  **Status:** DEGRADED" in second
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in second

    def test_update_rejects_unknown_task_id(self) -> None:
        with pytest.raises(TaskProgressError, match="task id not found: T-999"):
            update_task_progress_markdown(TASKS, "T-999", "DONE")

    def test_summarize_reconciles_tasks_md_with_state_build_object(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-001", "DONE")
        summary = summarize_task_progress(
            updated,
            {
                "total_tasks": 2,
                "completed_tasks": 1,
                "tasks_completed_pct": 50,
                "task_results": {"T-001": {"status": "DONE"}},
            },
        )

        assert summary.valid is True
        assert summary.total_tasks == 2
        assert summary.completed_tasks == 1
        assert summary.tasks_completed_pct == 50
        assert summary.errors == []

    def test_summarize_treats_done_with_concerns_as_done_outcome(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-001", "DONE")
        summary = summarize_task_progress(
            updated,
            {
                "total_tasks": 2,
                "completed_tasks": 1,
                "tasks_completed_pct": 50,
                "task_results": {"T-001": {"status": "DONE_WITH_CONCERNS"}},
            },
        )

        assert summary.valid is True
        assert summary.errors == []

    def test_summarize_ignores_fenced_task_row_examples(self) -> None:
        summary = summarize_task_progress(
            """# Tasks

```markdown
- [x] T-999 complexity=standard phase=example req=FR-999 depends=none
```

- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none
""",
            {"total_tasks": 1, "completed_tasks": 0, "tasks_completed_pct": 0},
        )

        assert summary.valid is True
        assert summary.total_tasks == 1
        assert summary.completed_tasks == 0
        assert "T-999" not in summary.task_statuses

    def test_summarize_flags_state_that_claims_more_progress_than_tasks_md(self) -> None:
        summary = summarize_task_progress(
            TASKS,
            {
                "total_tasks": 2,
                "completed_tasks": 2,
                "tasks_completed_pct": 100,
                "task_results": {
                    "T-001": {"status": "DONE"},
                    "T-002": {"status": "DONE"},
                },
            },
        )

        assert summary.valid is False
        assert "state completed_tasks=2 but tasks.md has 0 checked task rows" in summary.errors
        assert "state tasks_completed_pct=100 but tasks.md computes 0" in summary.errors

    def test_summarize_can_scope_counts_to_delivery_target(self) -> None:
        updated = update_task_progress_markdown(TASKS, "T-001", "DONE")

        summary = summarize_task_progress(
            updated,
            selected_task_ids={"T-002"},
        )

        assert summary.valid is True
        assert summary.total_tasks == 1
        assert summary.completed_tasks == 0
        assert summary.tasks_completed_pct == 0
        assert summary.task_statuses == {"T-002": "PENDING"}
