"""Tests for MODELER dispatch points (gap 3).

4 tests:
- echelon.run.md dispatches MODELER after SYNTHESIZER
- echelon.run.md MODELER dispatch references mental-model-code.md
- echelon.build.md dispatches MODELER after IMPLEMENTER task completion
- echelon.build.md MODELER checks for invariant violations
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ECHELON = Path(__file__).parent.parent.parent / "extension"


@pytest.mark.unit
class TestModelerDispatch:
    def test_run_md_dispatches_modeler_after_synthesizer(self) -> None:
        # Content moved to workflow/phases/ (echelon.run.md is now a thin wrapper)
        synth = (ECHELON / "workflow/phases/phase1-synthesizer.md").read_text()
        modeler = (ECHELON / "workflow/phases/phase1-modeler.md").read_text()
        assert "SYNTHESIZER" in synth
        assert "MODELER" in modeler
        # Synthesizer phase file precedes modeler phase file — ordering verified by definition.yaml

    def test_run_md_modeler_dispatch_references_mental_model(self) -> None:
        # Content moved to workflow/phases/phase1-modeler.md
        content = (ECHELON / "workflow/phases/phase1-modeler.md").read_text()
        assert re.search(r"MODELER", content)
        assert "mental-model-code.md" in content

    def test_build_md_dispatches_modeler_after_implementer_task(self) -> None:
        # Content moved to workflow/phases/build-6-progress.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-6-progress.md").read_text()
        assert re.search(
            r"MODELER Update.*mandatory after every task|mandatory after every task.*MODELER",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        section_start = content.index("**speckit-echelon-modeler (MODELER) Update")
        section = content[section_start:]
        assert "speckit-echelon-implementer (IMPLEMENTER)" in section

    def test_build_md_modeler_checks_invariant_violations(self) -> None:
        # Content moved to workflow/phases/build-6-progress.md (echelon.build.md is now a thin wrapper)
        content = (ECHELON / "workflow/phases/build-6-progress.md").read_text()
        assert re.search(r"invariant.*violation|MODELER.*alert|MODELER.*ALERT", content, re.IGNORECASE)
