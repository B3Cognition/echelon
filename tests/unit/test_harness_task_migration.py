"""Harness-facing migration for legacy tasks.md files."""

from __future__ import annotations

from harness.task_migration import migrate_tasks_markdown
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


def test_migrate_legacy_task_headings_to_canonical_rows() -> None:
    migrated = migrate_tasks_markdown(
        """
# Tasks

### T-001: Create shell

- Add the main screen.

### T-002: Wire actions

**Acceptance Criteria:**
- [ ] User can save
"""
    )

    tasks = parse_task_rows(migrated)

    assert [task.task_id for task in tasks] == ["T-001", "T-002"]
    assert all(task.complexity == "standard" for task in tasks)
    assert all(task.phase == "legacy" for task in tasks)
    assert all(task.requirements == ["UNMAPPED"] for task in tasks)
    assert all(task.dependencies == [] for task in tasks)
    assert "**Title:** Create shell" in migrated
    assert "**Title:** Wire actions" in migrated
    assert "- Add the main screen." in migrated
    assert "- [ ] User can save" in migrated
    assert validate_tasks_markdown(migrated).valid is True


def test_migrate_legacy_checkbox_rows_to_canonical_rows() -> None:
    migrated = migrate_tasks_markdown(
        """
## Implementation

- [ ] T-010 Build parser
- [x] T-011 Test parser
"""
    )

    tasks = parse_task_rows(migrated)

    assert [task.task_id for task in tasks] == ["T-010", "T-011"]
    assert tasks[0].status == " "
    assert tasks[1].status == "x"
    assert "**Title:** Build parser" in migrated
    assert "**Title:** Test parser" in migrated


def test_migrate_leaves_existing_canonical_rows_unchanged() -> None:
    source = "- [ ] T-001 complexity=standard phase=foundation req=FR-001 depends=none\n"

    assert migrate_tasks_markdown(source) == source
