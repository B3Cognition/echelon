"""Tests for python -m harness validate-task-progress."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestHarnessMainValidateTaskProgress:
    def test_validate_task_progress_exits_zero_for_matching_state(
        self, tmp_path, capsys
    ) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "  **Status:** DONE\n",
            encoding="utf-8",
        )
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps(
                {
                    "build": {
                        "total_tasks": 1,
                        "completed_tasks": 1,
                        "tasks_completed_pct": 100,
                        "task_results": {"T-001": {"status": "DONE"}},
                    }
                }
            ),
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-task-progress", str(tasks), str(state)]):
            main()

        out = capsys.readouterr().out
        assert "OK: 1/1 tasks complete (100%)" in out

    def test_validate_task_progress_exits_nonzero_for_mismatch(
        self, tmp_path, capsys
    ) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps(
                {
                    "build": {
                        "total_tasks": 1,
                        "completed_tasks": 1,
                        "tasks_completed_pct": 100,
                    }
                }
            ),
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-task-progress", str(tasks), str(state)]), \
             pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "invalid task progress" in err
        assert "state completed_tasks=1 but tasks.md has 0 checked task rows" in err

