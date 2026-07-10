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


@pytest.mark.unit
class TestHarnessMainMarkTaskProgress:
    def test_mark_task_progress_updates_tasks_file(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n"
            "\n"
            "  **Acceptance Criteria:**\n"
            "  - [ ] Scaffold exists\n",
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "mark-task-progress", str(tasks), "T-001", "DONE"]):
            main()

        text = tasks.read_text(encoding="utf-8")
        assert "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none" in text
        assert "  **Status:** DONE" in text
        assert "  - [x] Scaffold exists" in text
        assert "OK: marked T-001 as DONE" in capsys.readouterr().out

    def test_mark_task_progress_exits_nonzero_for_unknown_task(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "mark-task-progress", str(tasks), "T-999", "DONE"]), \
             pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        assert "could not mark task progress" in capsys.readouterr().err


@pytest.mark.unit
class TestHarnessMainWriteProgressIntegrity:
    def test_write_progress_integrity_creates_json_and_markdown(self, tmp_path, capsys) -> None:
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
        out_json = tmp_path / "progress-integrity.json"
        out_md = tmp_path / "progress-integrity.md"

        from harness.__main__ import main

        with patch(
            "sys.argv",
            [
                "python -m harness",
                "write-progress-integrity",
                str(tasks),
                str(state),
                str(out_json),
                str(out_md),
            ],
        ):
            main()

        data = json.loads(out_json.read_text(encoding="utf-8"))
        assert data["valid"] is True
        assert data["completed_tasks"] == 1
        assert data["task_statuses"] == {"T-001": "DONE"}
        state_data = json.loads(state.read_text(encoding="utf-8"))
        assert state_data["progress_integrity"] == "valid"
        assert state_data["progress_integrity_total_tasks"] == 1
        assert state_data["progress_integrity_completed_tasks"] == 1
        markdown = out_md.read_text(encoding="utf-8")
        assert "# Progress Integrity" in markdown
        assert "| T-001 | DONE |" in markdown
        assert "OK: wrote progress integrity" in capsys.readouterr().out

    def test_write_progress_integrity_exits_nonzero_for_mismatch(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        state = tmp_path / "state.json"
        state.write_text(
            json.dumps({"build": {"total_tasks": 1, "completed_tasks": 1}}),
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch(
            "sys.argv",
            [
                "python -m harness",
                "write-progress-integrity",
                str(tasks),
                str(state),
                str(tmp_path / "out.json"),
                str(tmp_path / "out.md"),
            ],
        ), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        state_data = json.loads(state.read_text(encoding="utf-8"))
        assert state_data["progress_integrity"] == "invalid"
        assert state_data["progress_integrity_errors"] == [
            "state completed_tasks=1 but tasks.md has 0 checked task rows"
        ]
        assert "invalid task progress" in capsys.readouterr().err

    def test_write_progress_integrity_exits_before_outputs_when_state_missing(
        self, tmp_path, capsys
    ) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [x] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )
        state = tmp_path / "state.json"
        out_json = tmp_path / "progress-integrity.json"
        out_md = tmp_path / "progress-integrity.md"

        from harness.__main__ import main

        with patch(
            "sys.argv",
            [
                "python -m harness",
                "write-progress-integrity",
                str(tasks),
                str(state),
                str(out_json),
                str(out_md),
            ],
        ), pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        assert "state.json missing for verify-spec run:" in capsys.readouterr().err
        assert not out_json.exists()
        assert not out_md.exists()
