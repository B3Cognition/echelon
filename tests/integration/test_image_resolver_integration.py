"""Integration tests for image resolver against real fixture repos.

Tests T020: real fixture repos for devcontainer, Playwright, and fingerprint.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.image_resolver import resolve_image

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


class TestImageResolverIntegration:
    """Integration tests for image resolution with real fixtures."""

    def test_devcontainer_fixture_resolves(self):
        """devcontainer fixture resolves to devcontainer.json image."""
        repo = FIXTURES / "target-repo-devcontainer"
        result = resolve_image(repo)

        assert result.source == "devcontainer"
        assert "python" in result.image.lower() or "devcontainers" in result.image.lower()

    def test_playwright_fixture_resolves(self):
        """Playwright fixture resolves to Playwright image."""
        repo = FIXTURES / "target-repo-typescript-playwright"
        result = resolve_image(repo)

        assert result.source == "fingerprint"
        assert "playwright" in result.image.lower()

    def test_config_override_has_lowest_priority(self):
        """Config override image takes priority 4 (only when nothing else matches)."""
        repo = FIXTURES / "target-repo-python"
        # Python repo should resolve to fingerprint, not config override
        result = resolve_image(repo, config_base_image="custom:latest")

        assert result.source == "fingerprint"
        assert "python" in result.image.lower()
