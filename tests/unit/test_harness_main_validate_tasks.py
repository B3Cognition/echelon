"""Tests for python -m harness validate-tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestHarnessMainValidateTasks:
    def test_validate_tasks_exits_zero_for_valid_file(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text(
            "- [ ] T-001 complexity=standard phase=foundation req=INFRA depends=none\n",
            encoding="utf-8",
        )

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-tasks", str(tasks)]):
            main()

        out = capsys.readouterr().out
        assert "OK: 1 canonical tasks" in out

    def test_validate_tasks_exits_nonzero_for_invalid_file(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text("- [ ] acceptance checkbox only\n", encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-tasks", str(tasks)]), \
             pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "invalid tasks.md" in err
        assert "no canonical task rows found" in err
