"""Tests for visual validation enabled by default with graceful degradation (gap 2).

3 tests:
- echelon-config.yml has visual_validation.enabled set to true
- visual-validator.md has a capability check before any work
- visual-validator.md degrades gracefully when no UI framework detected
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
PROSAIC_SUBAGENTS = ROOT / "prosaic" / "subagents"
RUNTIME = ROOT / "runtime"


@pytest.mark.unit
class TestVisualValidation:
    def test_config_has_visual_validation_enabled(self) -> None:
        raw = (RUNTIME / "echelon-config.yml").read_text()
        assert re.search(r"visual_validation:\s*\n\s*enabled:\s*true", raw)

    def test_visual_validator_has_capability_check(self) -> None:
        content = (PROSAIC_SUBAGENTS / "echelon.visual-validator.md").read_text()
        assert re.search(r"Capability Check", content, re.IGNORECASE)
        assert re.search(r"playwright.*version|npx playwright", content, re.IGNORECASE)
        assert "skipped_no_playwright" in content

    def test_visual_validator_degrades_gracefully_without_ui_framework(self) -> None:
        content = (PROSAIC_SUBAGENTS / "echelon.visual-validator.md").read_text()
        assert re.search(r"no.*browser|no.*ui.*framework|not.*browser", content, re.IGNORECASE)
        assert re.search(r"skip.*silently", content, re.IGNORECASE)
        assert re.search(r"return\s+`?COMPLETE`?", content, re.IGNORECASE)
