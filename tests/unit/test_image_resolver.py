"""Tests for image resolver 4-source priority chain.

8 tests per test-strategy 3.1.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.image_resolver import ImageResolutionError, resolve_image


@pytest.mark.unit
class TestImageResolverPriorityChain:
    """Test the 4-source priority chain."""

    def test_devcontainer_is_priority_1(self, tmp_path: Path) -> None:
        """devcontainer.json > everything else."""
        # Create devcontainer
        dc_dir = tmp_path / ".devcontainer"
        dc_dir.mkdir()
        (dc_dir / "devcontainer.json").write_text(
            json.dumps({"image": "mcr.microsoft.com/devcontainers/python:3.12"})
        )
        # Also add package.json (would normally trigger fingerprint)
        (tmp_path / "package.json").write_text(json.dumps({"name": "test"}))

        result = resolve_image(tmp_path, config_base_image="override:latest")
        assert result.source == "devcontainer"
        assert result.image == "mcr.microsoft.com/devcontainers/python:3.12"

    def test_harness_dockerfile_is_priority_2(self, tmp_path: Path) -> None:
        """Harness Dockerfile > fingerprint > config."""
        (tmp_path / "package.json").write_text(json.dumps({"name": "test"}))
        dockerfile = tmp_path / "Dockerfile.harness"
        dockerfile.write_text("FROM ubuntu:24.04\n")

        result = resolve_image(tmp_path, harness_dockerfile=dockerfile)
        assert result.source == "harness_dockerfile"

    def test_fingerprint_is_priority_3(self, tmp_path: Path) -> None:
        """Fingerprint-based when no devcontainer or Dockerfile."""
        (tmp_path / "package.json").write_text(json.dumps({"name": "test"}))

        result = resolve_image(tmp_path, config_base_image="override:latest")
        assert result.source == "fingerprint"
        assert "node" in result.image

    def test_config_override_is_priority_4(self, tmp_path: Path) -> None:
        """Config base_image is last resort before error."""
        # Empty repo, no markers
        result = resolve_image(tmp_path, config_base_image="custom:latest")
        assert result.source == "config_override"
        assert result.image == "custom:latest"

    def test_no_source_raises_error(self, tmp_path: Path) -> None:
        """No image from any source -> ImageResolutionError."""
        with pytest.raises(ImageResolutionError, match="No image could be resolved"):
            resolve_image(tmp_path)

    def test_playwright_overrides_fingerprint_image(self, tmp_path: Path) -> None:
        """Playwright detection overrides node image."""
        pkg = {
            "name": "test",
            "devDependencies": {"@playwright/test": "^1.42.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        result = resolve_image(tmp_path)
        assert result.source == "fingerprint"
        assert "playwright" in result.image.lower()

    def test_devcontainer_overrides_playwright(self, tmp_path: Path) -> None:
        """devcontainer.json overrides Playwright auto-selection (FR-IMAGE-001b)."""
        dc_dir = tmp_path / ".devcontainer"
        dc_dir.mkdir()
        (dc_dir / "devcontainer.json").write_text(
            json.dumps({"image": "custom-playwright:latest"})
        )
        pkg = {
            "name": "test",
            "devDependencies": {"@playwright/test": "^1.42.0"},
        }
        (tmp_path / "package.json").write_text(json.dumps(pkg))

        result = resolve_image(tmp_path)
        assert result.source == "devcontainer"
        assert result.image == "custom-playwright:latest"

    def test_missing_devcontainer_tries_next(self, tmp_path: Path) -> None:
        """Missing devcontainer.json returns None, tries next source."""
        (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")

        result = resolve_image(tmp_path)
        assert result.source == "fingerprint"
        assert "python" in result.image
