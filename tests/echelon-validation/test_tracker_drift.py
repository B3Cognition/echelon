"""Tests for TRACKER drift severity classification and correction gate (gap 5).

5 tests:
- tracker.md output format defines drift_severity field with all severity levels
- tracker.md defines 20% severity threshold
- echelon.build.md has a severity-tiered drift gate
- echelon.build.md dispatches CHANGE CONTROLLER on MAJOR_DRIFT (non-banzai)
- echelon.build.md sets requires_human_review on MAJOR_DRIFT in banzai mode
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
PROSAIC_SUBAGENTS = ROOT / "prosaic" / "subagents"
RUNTIME = ROOT / "runtime"


@pytest.mark.unit
class TestTrackerDrift:
    def test_tracker_md_defines_drift_severity_field(self) -> None:
        content = (PROSAIC_SUBAGENTS / "echelon.tracker.md").read_text()
        assert "drift_severity" in content
        assert "ALIGNED" in content
        assert "MINOR_DRIFT" in content
        assert "MAJOR_DRIFT" in content

    def test_tracker_md_defines_20_percent_threshold(self) -> None:
        content = (PROSAIC_SUBAGENTS / "echelon.tracker.md").read_text()
        assert re.search(r"20%|0\.20", content)

    def test_build_md_has_severity_tiered_drift_gate(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (RUNTIME / "workflow/phases/build-8-finalize.md").read_text()
        assert "MAJOR_DRIFT" in content
        assert "MINOR_DRIFT" in content

    def test_build_md_dispatches_change_controller_on_major_drift(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (RUNTIME / "workflow/phases/build-8-finalize.md").read_text()
        assert re.search(
            r"MAJOR_DRIFT[\s\S]{0,500}CHANGE CONTROLLER|CHANGE CONTROLLER[\s\S]{0,200}MAJOR_DRIFT",
            content,
            re.IGNORECASE,
        )

    def test_build_md_sets_requires_human_review_in_banzai_mode(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (RUNTIME / "workflow/phases/build-8-finalize.md").read_text()
        assert "requires_human_review" in content
        assert "drift-escalation.md" in content
