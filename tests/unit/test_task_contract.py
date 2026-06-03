"""Tests for canonical tasks.md parsing and validation."""

from __future__ import annotations

import pytest

from kernel.task_contract import parse_task_rows, validate_tasks_markdown


CANONICAL_TASKS = """
# Tasks: Example

- [ ] T-001 [P] complexity=standard phase=foundation req=FR-001 depends=none

  **Title:** Create user repository
  **Files:**
  - `src/users/repository.py`
  **Acceptance Criteria:**
  - [ ] Repository stores users
  - [ ] Repository returns users by ID

- [ ] T-002 complexity=complex phase=core req=FR-002,FR-003 depends=T-001

  **Title:** Implement login flow
  **Files:**
  - `src/auth/login.py`
"""


@pytest.mark.unit
class TestTaskContract:
    def test_parse_task_rows_counts_only_canonical_top_level_rows(self) -> None:
        tasks = parse_task_rows(CANONICAL_TASKS)

        assert [task.task_id for task in tasks] == ["T-001", "T-002"]
        assert tasks[0].parallel is True
        assert tasks[1].parallel is False

    def test_parse_task_rows_extracts_metadata(self) -> None:
        task = parse_task_rows(CANONICAL_TASKS)[1]

        assert task.complexity == "complex"
        assert task.phase == "core"
        assert task.requirements == ["FR-002", "FR-003"]
        assert task.dependencies == ["T-001"]

    def test_validation_accepts_canonical_tasks(self) -> None:
        result = validate_tasks_markdown(CANONICAL_TASKS)

        assert result.valid is True
        assert result.task_count == 2
        assert result.errors == []

    def test_validation_rejects_acceptance_checkboxes_without_task_rows(self) -> None:
        result = validate_tasks_markdown(
            """
            # Tasks

            ## Phase 1

            **Acceptance Criteria:**
            - [ ] User can log in
            - [ ] User can log out
            """
        )

        assert result.valid is False
        assert result.task_count == 0
        assert "no canonical task rows found" in result.errors

    def test_validation_rejects_duplicate_task_ids(self) -> None:
        result = validate_tasks_markdown(
            "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n"
            "- [ ] T-001 complexity=standard phase=core req=FR-002 depends=none\n"
        )

        assert result.valid is False
        assert "duplicate task id: T-001" in result.errors

    def test_parse_task_rows_accepts_spike_task_ids(self) -> None:
        tasks = parse_task_rows(
            "- [ ] T-S01b [P] complexity=trivial phase=spike req=OQ-001 depends=none\n"
            "- [ ] T-S02 complexity=complex phase=spike req=OQ-002 depends=T-S01b\n"
        )

        assert [task.task_id for task in tasks] == ["T-S01b", "T-S02"]
        assert tasks[0].parallel is True
        assert tasks[1].dependencies == ["T-S01b"]

    def test_parse_task_rows_ignores_fenced_examples(self) -> None:
        tasks = parse_task_rows(
            """
```markdown
- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none
```

- [ ] T-002 complexity=standard phase=core req=FR-002 depends=none
"""
        )

        assert [task.task_id for task in tasks] == ["T-002"]
