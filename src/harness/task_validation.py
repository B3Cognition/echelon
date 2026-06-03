"""Harness-facing tasks.md validation helpers."""

from __future__ import annotations

from pathlib import Path

from harness.spec_frontmatter import find_spec_dir
from kernel.task_contract import TaskValidationResult, validate_tasks_markdown


class TaskValidationError(RuntimeError):
    """Raised when a tasks.md file does not satisfy the harness task contract."""


def validate_tasks_file(tasks_path: Path) -> TaskValidationResult:
    result = validate_tasks_markdown(
        tasks_path.read_text(encoding="utf-8", errors="replace")
    )
    if not result.valid:
        raise TaskValidationError("; ".join(result.errors))
    return result


def validate_tasks_for_spec(spec_id: str, base_dir: str | Path) -> TaskValidationResult | None:
    spec_dir = find_spec_dir(spec_id, Path(base_dir).resolve())
    if spec_dir is None:
        return None
    tasks_path = spec_dir / "tasks.md"
    if not tasks_path.exists():
        return None
    return validate_tasks_file(tasks_path)


def count_tasks_for_spec(spec_id: str, base_dir: str | Path) -> int:
    result = validate_tasks_for_spec(spec_id, base_dir)
    return result.task_count if result is not None else 0
