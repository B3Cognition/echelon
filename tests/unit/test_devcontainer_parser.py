"""Tests for devcontainer.json subset parser.

6 tests covering: valid parsing, ignored fields warning, missing file,
empty file, binary file, and subset field extraction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from harness.devcontainer import DevcontainerConfig, parse_devcontainer


@pytest.mark.unit
class TestDevcontainerParser:
    """Test devcontainer.json parsing."""

    def test_full_subset_parsed(self, tmp_path: Path) -> None:
        data = {
            "image": "mcr.microsoft.com/devcontainers/python:3.12",
            "build": {"dockerfile": "Dockerfile"},
            "features": {"ghcr.io/devcontainers/features/node:1": {}},
            "forwardPorts": [3000, 8080],
            "containerEnv": {"NODE_ENV": "development"},
            "postCreateCommand": "npm install",
        }
        path = tmp_path / "devcontainer.json"
        path.write_text(json.dumps(data))

        result = parse_devcontainer(path)
        assert result is not None
        assert result.image == "mcr.microsoft.com/devcontainers/python:3.12"
        assert result.dockerfile == "Dockerfile"
        assert len(result.features) == 1
        assert result.forward_ports == [3000, 8080]
        assert result.container_env == {"NODE_ENV": "development"}
        assert result.post_create_command == "npm install"

    def test_ignored_fields_logged(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        data = {
            "image": "ubuntu:24.04",
            "customizations": {"vscode": {"extensions": ["ms-python.python"]}},
        }
        path = tmp_path / "devcontainer.json"
        path.write_text(json.dumps(data))

        with caplog.at_level(logging.WARNING):
            result = parse_devcontainer(path)

        assert result is not None
        assert "Ignoring" in caplog.text
        assert "customizations" in caplog.text

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        result = parse_devcontainer(tmp_path / "nonexistent.json")
        assert result is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "devcontainer.json"
        path.write_text("")

        result = parse_devcontainer(path)
        assert result is None

    def test_binary_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "devcontainer.json"
        path.write_bytes(b"\x00\x01\x02\xff\xfe")

        result = parse_devcontainer(path)
        assert result is None

    def test_image_only(self, tmp_path: Path) -> None:
        data = {"image": "node:20"}
        path = tmp_path / "devcontainer.json"
        path.write_text(json.dumps(data))

        result = parse_devcontainer(path)
        assert result is not None
        assert result.image == "node:20"
        assert result.dockerfile is None
        assert result.post_create_command is None
