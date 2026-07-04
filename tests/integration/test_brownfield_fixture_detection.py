"""Brownfield fixture tests for deterministic harness detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.app_runtime_detection import detect_app_runtime
from harness.verify_detection import detect_verify_command


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _empty_repo(root: Path) -> Path:
    root.mkdir()
    return root


def _python_uv_repo(root: Path) -> Path:
    (root / "tests").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    (root / "uv.lock").write_text("", encoding="utf-8")
    (root / "tests" / "test_api.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return root


def _compose_web_repo(root: Path) -> Path:
    root.mkdir()
    _write_json(root / "package.json", {"scripts": {"test": "vitest run"}})
    (root / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    (root / "docker-compose.yml").write_text(
        """
services:
  web:
    image: node:20
    ports:
      - "3100:3000"
  db:
    image: postgres:16
""".lstrip(),
        encoding="utf-8",
    )
    return root


def _ambiguous_nx_repo(root: Path) -> Path:
    _write_json(root / "package.json", {"scripts": {"test": "vitest run"}})
    _write_json(
        root / "nx.json",
        {
            "projects": {
                "frontend": "cpp/frontend",
                "config-tool": "cpp/config-tool",
            }
        },
    )
    _write_json(
        root / "cpp" / "frontend" / "project.json",
        {
            "name": "frontend",
            "projectType": "application",
            "targets": {
                "serve": {
                    "options": {"command": "next dev --port 3000"},
                }
            },
        },
    )
    _write_json(
        root / "cpp" / "config-tool" / "project.json",
        {
            "name": "config-tool",
            "projectType": "application",
            "targets": {
                "serve": {
                    "options": {"command": "next dev --port 8080"},
                }
            },
        },
    )
    return root


@pytest.mark.integration
@pytest.mark.parametrize(
    ("factory", "verify_confidence", "verify_command", "app_confidence"),
    [
        (_empty_repo, "none", None, "none"),
        (_ambiguous_nx_repo, "high", "npm test", "ambiguous"),
        (_python_uv_repo, "high", "uv run pytest", "none"),
        (_compose_web_repo, "high", "pnpm test", "high"),
    ],
)
def test_brownfield_fixture_detection_summary(
    tmp_path: Path,
    factory,
    verify_confidence: str,
    verify_command: str | None,
    app_confidence: str,
) -> None:
    repo = factory(tmp_path / factory.__name__)

    verify = detect_verify_command(repo)
    app = detect_app_runtime(repo)

    assert verify.confidence == verify_confidence
    assert verify.command == verify_command
    assert app.confidence == app_confidence


@pytest.mark.integration
def test_compose_web_runtime_profile(tmp_path: Path) -> None:
    repo = _compose_web_repo(tmp_path / "compose-web-runtime")

    result = detect_app_runtime(repo)

    assert result.profile == {
        "enabled": True,
        "mode": "docker_compose",
        "compose_file": "docker-compose.yml",
        "service": "web",
        "url": "http://localhost:3100",
    }


@pytest.mark.integration
def test_ambiguous_nx_browser_apps(tmp_path: Path) -> None:
    repo = _ambiguous_nx_repo(tmp_path / "ambiguous-nx")

    result = detect_app_runtime(repo)

    assert result.profile is None
    assert result.confidence == "ambiguous"
    assert "cpp/frontend/project.json serve target uses next dev on port 3000" in result.evidence
    assert any(
        item.startswith("cpp/config-tool")
        and item.endswith("project.json serve target uses next dev on port 8080")
        for item in result.evidence
    )
