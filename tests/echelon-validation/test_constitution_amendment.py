"""Tests for constitution amendment flow via MIRROR/VETERAN consolidation (gap 6).

5 tests:
- mirror.md produces amendment candidates in PROPOSED format
- veteran.md produces cross-run amendment candidates referencing run-history.json
- echelon.build.md has a consolidation phase writing constitution-amendment-candidates.md
- echelon.build.md appends PROPOSED blocks and tracks constitution_amendments_pending
- echelon.build.md requires human approval — no auto-amendment
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ECHELON = Path(__file__).parent.parent.parent / "extension"


@pytest.mark.unit
class TestConstitutionAmendment:
    def test_mirror_md_produces_proposed_amendment_candidates(self) -> None:
        content = (ECHELON / "agents/learning/mirror.md").read_text()
        assert re.search(r"amendment.*candidate|constitution.*amendment", content, re.IGNORECASE)
        assert "PROPOSED" in content

    def test_veteran_md_produces_cross_run_amendment_candidates(self) -> None:
        content = (ECHELON / "agents/learning/veteran.md").read_text()
        assert re.search(r"amendment.*candidate|constitution.*amendment", content, re.IGNORECASE)
        assert "PROPOSED" in content
        assert re.search(r"run-history\.json|cross-run", content, re.IGNORECASE)

    def test_build_md_has_consolidation_phase_with_candidates_file(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-8-finalize.md").read_text()
        assert re.search(r"consolidation|Consolidation", content, re.IGNORECASE)
        assert "constitution-amendment-candidates.md" in content

    def test_build_md_appends_proposed_blocks_and_tracks_pending(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-8-finalize.md").read_text()
        assert "[PROPOSED" in content
        assert "constitution_amendments_pending" in content

    def test_build_md_requires_human_approval_no_auto_amendment(self) -> None:
        # Content moved to workflow/phases/build-8-finalize.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-8-finalize.md").read_text()
        assert re.search(r"human.*review|human.*approve|speckit\.constitution", content, re.IGNORECASE)
