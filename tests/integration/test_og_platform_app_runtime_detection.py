"""Fixture test for og-platform brownfield app runtime detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.app_runtime_detection import detect_app_runtime


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _og_platform_fixture(root: Path) -> Path:
    root.mkdir()
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    (root / "compose.db.yml").write_text("services: {db: {image: postgres:16}}\n", encoding="utf-8")
    _write_json(root / "nx.json", {"projects": {"api": "apps/api", "frontend": "apps/frontend"}})
    _write_json(
        root / "apps" / "api" / "project.json",
        {
            "name": "api",
            "projectType": "application",
            "targets": {"serve": {"options": {"command": "node server.js"}}},
        },
    )
    _write_json(
        root / "apps" / "frontend" / "project.json",
        {
            "name": "frontend",
            "projectType": "application",
            "targets": {
                "dev": {
                    "options": {"command": "next dev --port 3000"},
                }
            },
        },
    )
    return root


@pytest.mark.integration
def test_og_platform_detects_frontend_command_profile(tmp_path: Path) -> None:
    repo = _og_platform_fixture(tmp_path / "og-platform")

    result = detect_app_runtime(repo)

    assert result.confidence == "high"
    assert result.profile is not None
    assert result.profile["mode"] == "command"
    assert result.profile["app"] == "frontend"
    assert result.profile["setup_commands"] == [
        "npm ci",
        "docker compose -f compose.db.yml up -d",
    ]
    assert result.profile["start_commands"] == [
        "npx nx serve api",
        "npx nx dev frontend",
    ]
    assert result.profile["stop_commands"] == [
        "docker compose -f compose.db.yml down",
        "npx nx reset",
    ]
    assert result.profile["url"] == "http://localhost:3000"
