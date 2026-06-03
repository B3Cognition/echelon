"""Harness-facing validation for canonical tasks.md files."""

from __future__ import annotations

import pytest

from harness.task_validation import TaskValidationError, count_tasks_for_spec, validate_tasks_file


def _write_spec(tmp_path, tasks_text: str):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    tasks_path = spec_dir / "tasks.md"
    tasks_path.write_text(tasks_text, encoding="utf-8")
    return tasks_path


@pytest.mark.unit
class TestHarnessTaskValidation:
    def test_count_tasks_for_spec_uses_canonical_rows(self, tmp_path) -> None:
        _write_spec(
            tmp_path,
            """
- [ ] T-001 [P] complexity=standard phase=foundation req=INFRA depends=none

  **Acceptance Criteria:**
  - [ ] scaffold exists

- [ ] T-002 complexity=complex phase=core req=FR-001 depends=T-001
""",
        )

        assert count_tasks_for_spec("001", tmp_path) == 2

    def test_validate_tasks_file_rejects_acceptance_checkbox_only_file(self, tmp_path) -> None:
        tasks_path = _write_spec(
            tmp_path,
            """
# Tasks

**Acceptance Criteria:**
- [ ] user can log in
- [ ] user can log out
""",
        )

        with pytest.raises(TaskValidationError, match="no canonical task rows found"):
            validate_tasks_file(tasks_path)

    def test_count_tasks_for_spec_returns_zero_when_tasks_missing(self, tmp_path) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

        assert count_tasks_for_spec("001", tmp_path) == 0
