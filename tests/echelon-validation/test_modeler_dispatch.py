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
        content = (ECHELON / "commands/echelon.run.md").read_text()
        synth_idx = content.index("SYNTHESIZER")
        modeler_idx = content.index("MODELER", synth_idx)
        assert modeler_idx > synth_idx

    def test_run_md_modeler_dispatch_references_mental_model(self) -> None:
        content = (ECHELON / "commands/echelon.run.md").read_text()
        assert re.search(r"Dispatch MODELER", content)
        assert "mental-model-code.md" in content

    def test_build_md_dispatches_modeler_after_implementer_task(self) -> None:
        content = (ECHELON / "commands/echelon.build.md").read_text()
        assert re.search(
            r"MODELER Update.*mandatory after every task|mandatory after every task.*MODELER",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        impl_idx = content.index("IMPLEMENTER")
        modeler_update_idx = content.index("MODELER Update")
        assert modeler_update_idx > impl_idx

    def test_build_md_modeler_checks_invariant_violations(self) -> None:
        content = (ECHELON / "commands/echelon.build.md").read_text()
        assert re.search(r"invariant.*violation|MODELER.*alert|MODELER.*ALERT", content, re.IGNORECASE)
