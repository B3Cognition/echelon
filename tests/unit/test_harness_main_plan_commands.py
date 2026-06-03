"""Tests for python -m harness plan commands."""

from __future__ import annotations

from unittest.mock import patch

import pytest


VALID_PLAN = """
# Implementation Plan: Demo

## Summary
Demo.

## Technical Context
### Stack
Swift.

## Architecture Decisions
- ADR-001: Swift.

## Project Structure
```text
src/
```

## Implementation Phases
### Phase 1: Foundation

## Testing Strategy
- Unit tests.

## Risks
- None.

## Constitution Check
| Principle | Compliance |
| --- | --- |
| Local-first | PASS |
"""


@pytest.mark.unit
class TestHarnessMainPlanCommands:
    def test_validate_plan_exits_zero_for_valid_file(self, tmp_path, capsys) -> None:
        plan = tmp_path / "plan.md"
        plan.write_text(VALID_PLAN, encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-plan", str(plan)]):
            main()

        assert "OK: canonical plan.md" in capsys.readouterr().out

    def test_validate_plan_exits_nonzero_for_missing_section(self, tmp_path, capsys) -> None:
        plan = tmp_path / "plan.md"
        plan.write_text("# Implementation Plan: Demo\n\n## Summary\n", encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "validate-plan", str(plan)]), \
             pytest.raises(SystemExit) as exc:
            main()

        assert exc.value.code == 1
        assert "invalid plan.md" in capsys.readouterr().err

    def test_migrate_plan_dry_run_prints_without_editing_file(self, tmp_path, capsys) -> None:
        plan = tmp_path / "plan.md"
        original = "# Architecture Plan: Demo\n\n## Summary\nDemo.\n"
        plan.write_text(original, encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "migrate-plan", str(plan)]):
            main()

        assert "## Architecture Decisions" in capsys.readouterr().out
        assert plan.read_text(encoding="utf-8") == original

    def test_migrate_plan_write_updates_file_and_reports_validation(self, tmp_path, capsys) -> None:
        plan = tmp_path / "plan.md"
        plan.write_text("# Architecture Plan: Demo\n\n## Summary\nDemo.\n", encoding="utf-8")

        from harness.__main__ import main

        with patch("sys.argv", ["python -m harness", "migrate-plan", str(plan), "--write"]):
            main()

        assert "## Constitution Check" in plan.read_text(encoding="utf-8")
        assert "OK: migrated canonical plan.md" in capsys.readouterr().out
