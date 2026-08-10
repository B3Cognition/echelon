"""Tests for Echelon task templates and fragments."""

from __future__ import annotations

from pathlib import Path

import pytest

from kernel.task_contract import parse_task_rows, validate_tasks_markdown


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "runtime" / "templates"


@pytest.mark.unit
class TestTaskTemplates:
    def test_main_tasks_template_contains_canonical_task_rows(self) -> None:
        text = (TEMPLATE_DIR / "tasks-template.md").read_text(encoding="utf-8")

        result = validate_tasks_markdown(text)

        assert result.valid is True
        assert result.task_count >= 2
        assert "## Task Row Contract" in text

    def test_task_entry_fragment_is_parseable(self) -> None:
        text = (TEMPLATE_DIR / "task-entry-fragment.md").read_text(encoding="utf-8")

        tasks = parse_task_rows(text)

        assert len(tasks) == 1
        assert tasks[0].task_id == "T-000"

    @pytest.mark.parametrize(
        ("filename", "prefix"),
        [
            ("bugfix-task-fragment.md", "BF1-T1"),
            ("review-fix-task-fragment.md", "RF1-T1"),
            ("fulfillment-gap-task-fragment.md", "FG-T1"),
        ],
    )
    def test_append_fragments_explain_canonical_row_mapping(
        self, filename: str, prefix: str
    ) -> None:
        text = (TEMPLATE_DIR / filename).read_text(encoding="utf-8")

        assert prefix in text
        assert "canonical row" in text
        assert "complexity=" in text
        assert "depends=" in text
