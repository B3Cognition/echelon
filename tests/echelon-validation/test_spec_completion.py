"""Tests for spec completion tracking.

5 tests:
- state-schema.json has spec_status with full lifecycle enum
- state-schema.json has build object with tasks_completed_pct
- phase1-what.md sets spec_status to planned after CARTOGRAPHER (LLM-owned)
- cli.py writes "In Progress" to spec frontmatter at harness run start (Python-owned)
- coordinator.py writes "Implemented" to spec frontmatter on convergence (Python-owned)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ECHELON = Path(__file__).parent.parent.parent / "extension"
SCHEMA_DIR = Path(__file__).parent.parent.parent / "templates"
SRC = Path(__file__).parent.parent.parent / "src"


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
        # phase1-what.md remains LLM-owned (squad phase, not harness)
        content = (ECHELON / "workflow/phases/phase1-what.md").read_text()
        assert re.search(r"spec_status.*planned", content)
        assert re.search(r"Status.*Planned", content)

    def test_cli_writes_in_progress_at_harness_run_start(self) -> None:
        # Python-owned: cli.py calls write_status("In Progress") before run()
        content = (SRC / "echelon" / "cli.py").read_text()
        assert re.search(r'write_spec_status\(spec_dir,\s*"In Progress"\)', content)

    def test_coordinator_writes_implemented_on_convergence(self) -> None:
        # Python-owned: coordinator.py calls write_status("Implemented") when converged
        content = (SRC / "harness" / "coordinator.py").read_text()
        assert re.search(r'write_spec_status\(_spec_dir,\s*"Implemented"\)', content)
        assert re.search(r'result\.status\s*==\s*"converged"', content)
