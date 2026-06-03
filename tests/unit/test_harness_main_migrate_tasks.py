"""Tests for python -m harness migrate-tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestHarnessMainMigrateTasks:
    def test_migrate_tasks_dry_run_prints_migrated_text_without_editing_file(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        original = "### T-001: Build shell\n"
        tasks.write_text(original, encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "migrate-tasks", str(tasks)]):
            main()

        out = capsys.readouterr().out
        assert "- [ ] T-001 complexity=standard phase=legacy req=UNMAPPED depends=none" in out
        assert "**Title:** Build shell" in out
        assert tasks.read_text(encoding="utf-8") == original

    def test_migrate_tasks_write_updates_file_and_reports_validation(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        tasks.write_text("### T-001: Build shell\n", encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "migrate-tasks", str(tasks), "--write"]):
            main()

        text = tasks.read_text(encoding="utf-8")
        assert "- [ ] T-001 complexity=standard phase=legacy req=UNMAPPED depends=none" in text
        out = capsys.readouterr().out
        assert "OK: migrated 1 canonical tasks" in out

    def test_migrate_tasks_write_refuses_invalid_migration_without_editing_file(self, tmp_path, capsys) -> None:
        tasks = tmp_path / "tasks.md"
        original = "### T-001: Build shell\n### T-001: Duplicate shell\n"
        tasks.write_text(original, encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "migrate-tasks", str(tasks), "--write"]), \
             pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        assert tasks.read_text(encoding="utf-8") == original
        err = capsys.readouterr().err
        assert "invalid migrated tasks.md" in err
        assert "duplicate task id: T-001" in err
