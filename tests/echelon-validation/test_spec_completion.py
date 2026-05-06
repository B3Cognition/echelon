"""Tests for spec completion tracking (gap 1).

5 tests:
- state-schema.json has spec_status with full lifecycle enum
- state-schema.json has build object with tasks_completed_pct
- echelon.run.md sets spec_status to planned after CARTOGRAPHER
- echelon.build.md sets spec_status to in-progress at build start
- echelon.build.md sets spec_status to implemented on VERIFICATION PASS
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ECHELON = Path(__file__).parent.parent.parent / "extension"
SCHEMA_DIR = Path(__file__).parent.parent.parent / "templates"


@pytest.mark.unit
class TestSpecCompletion:
    def test_state_schema_has_spec_status_lifecycle_enum(self) -> None:
        schema = json.loads((SCHEMA_DIR / "state-schema.json").read_text())
        prop = schema["properties"]["spec_status"]
        assert "draft" in prop["enum"]
        assert "planned" in prop["enum"]
        assert "in-progress" in prop["enum"]
        assert "implemented" in prop["enum"]
        assert prop["default"] == "draft"

    def test_state_schema_has_build_with_tasks_completed_pct(self) -> None:
        schema = json.loads((SCHEMA_DIR / "state-schema.json").read_text())
        build = schema["properties"]["build"]
        assert build is not None
        assert build["properties"]["tasks_completed_pct"]["type"] == "number"
        assert "total_tasks" in build["properties"]
        assert "completed_tasks" in build["properties"]

    def test_run_md_sets_spec_status_planned_after_cartographer(self) -> None:
        content = (ECHELON / "commands/echelon.run.md").read_text()
        assert re.search(r"spec_status.*planned", content)
        assert re.search(r"Status.*Planned", content)

    def test_build_md_sets_spec_status_in_progress_at_start(self) -> None:
        content = (ECHELON / "commands/echelon.build.md").read_text()
        assert re.search(r"spec_status.*in-progress", content)
        assert re.search(r"Status.*In Progress", content)

    def test_build_md_sets_spec_status_implemented_on_verification_pass(self) -> None:
        content = (ECHELON / "commands/echelon.build.md").read_text()
        assert re.search(r"spec_status.*implemented", content)
        assert re.search(r"Status.*Implemented", content)
        assert "tasks_completed_pct" in content
