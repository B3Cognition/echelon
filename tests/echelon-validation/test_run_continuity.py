"""Tests for cross-run spec continuity via run-history.json (gap 4).

4 tests:
- run-history-schema.json exists and has required fields
- echelon.run.md reads run-history.json at INIT to skip Phase A if done
- echelon.run.md writes run-history.json at DONE (≥2 references)
- echelon.build.md appends to run-history.json and sets authoritative_run
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ECHELON = Path(__file__).parent.parent.parent / "extension"
SCHEMA_DIR = Path(__file__).parent.parent.parent / "templates"


@pytest.mark.unit
class TestRunContinuity:
    def test_run_history_schema_exists_with_required_fields(self) -> None:
        schema = json.loads((SCHEMA_DIR / "run-history-schema.json").read_text())
        assert "spec_id" in schema["properties"]
        assert "runs" in schema["properties"]
        assert "authoritative_run" in schema["properties"]
        run_item = schema["properties"]["runs"]["items"]["properties"]
        assert "run_id" in run_item
        assert "phase" in run_item
        assert "status" in run_item
        assert "timestamp" in run_item

    def test_run_md_reads_run_history_at_init_to_skip_phase_a(self) -> None:
        # Content moved to workflow/phases/init.md (echelon.run.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/init.md").read_text()
        assert "run-history.json" in content
        assert re.search(r"Phase A.*already.*done|phase.*A.*complete|skip.*phase.*A", content, re.IGNORECASE)

    def test_run_md_writes_run_history_at_done(self) -> None:
        # Content split across workflow/phases/init.md and phase4-document.md
        init = (ECHELON / "workflow/phases/init.md").read_text()
        finalize = (ECHELON / "workflow/phases/phase4-document.md").read_text()
        matches = re.findall(r"run-history\.json", init + finalize)
        assert len(matches) >= 2

    def test_build_md_appends_run_history_and_sets_authoritative_run(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-8-finalize.md").read_text()
        assert "run-history.json" in content
        assert "authoritative_run" in content
