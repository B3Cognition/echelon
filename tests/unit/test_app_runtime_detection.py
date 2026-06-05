"""Tests for deterministic harness app runtime profile detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.app_runtime_detection import detect_app_runtime


@pytest.mark.unit
class TestAppRuntimeDetection:
    """High-confidence Docker-backed app runtime detection."""

    def test_detects_single_compose_web_service_with_host_port(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  web:
    build: .
    ports:
      - "3000:3000"
""",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile == {
            "enabled": True,
            "mode": "docker_compose",
            "compose_file": "docker-compose.yml",
            "service": "web",
            "url": "http://localhost:3000",
        }
        assert result.confidence == "high"

    def test_detects_compose_mapping_with_ip_prefix(self, tmp_path: Path) -> None:
        (tmp_path / "compose.yaml").write_text(
            """
services:
  frontend:
    image: example/frontend
    ports:
      - "127.0.0.1:8080:80"
""",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile is not None
        assert result.profile["compose_file"] == "compose.yaml"
        assert result.profile["service"] == "frontend"
        assert result.profile["url"] == "http://localhost:8080"

    def test_rejects_ambiguous_compose_services(self, tmp_path: Path) -> None:
        (tmp_path / "docker-compose.yml").write_text(
            """
services:
  web:
    ports: ["3000:3000"]
  admin:
    ports: ["4000:4000"]
""",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile is None
        assert result.confidence == "ambiguous"

    def test_detects_dockerfile_with_expose(self, tmp_path: Path) -> None:
        (tmp_path / "Dockerfile").write_text(
            "FROM node:20-slim\nEXPOSE 4173\nCMD [\"npm\", \"run\", \"preview\"]\n",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile == {
            "enabled": True,
            "mode": "dockerfile",
            "dockerfile": "Dockerfile",
            "container_port": 4173,
            "url": "http://localhost:4173",
        }
        assert result.confidence == "high"

    def test_does_not_guess_without_docker_runtime_markers(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text('{"scripts":{"dev":"vite"}}', encoding="utf-8")

        result = detect_app_runtime(tmp_path)

        assert result.profile is None
        assert result.confidence == "none"

    def test_detects_single_nx_next_frontend_dev_target(self, tmp_path: Path) -> None:
        (tmp_path / "nx.json").write_text("{}", encoding="utf-8")
        app_dir = tmp_path / "apps" / "frontend"
        app_dir.mkdir(parents=True)
        (app_dir / "project.json").write_text(
            """
{
  "name": "frontend",
  "projectType": "application",
  "targets": {
    "dev": {
      "executor": "nx:run-commands",
      "options": {
        "command": "next dev",
        "cwd": "apps/frontend"
      }
    }
  }
}
""",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile == {
            "enabled": True,
            "mode": "command",
            "app": "frontend",
            "start_commands": ["npx nx dev frontend"],
            "url": "http://localhost:3000",
            "readiness_timeout_ms": 120000,
        }
        assert result.confidence == "high"

    def test_rejects_multiple_nx_browser_app_candidates(self, tmp_path: Path) -> None:
        (tmp_path / "nx.json").write_text("{}", encoding="utf-8")
        for name in ("frontend", "admin"):
            app_dir = tmp_path / "apps" / name
            app_dir.mkdir(parents=True)
            (app_dir / "project.json").write_text(
                f"""
{{
  "name": "{name}",
  "projectType": "application",
  "targets": {{
    "dev": {{
      "executor": "nx:run-commands",
      "options": {{
        "command": "next dev",
        "cwd": "apps/{name}"
      }}
    }}
  }}
}}
""",
                encoding="utf-8",
            )

        result = detect_app_runtime(tmp_path)

        assert result.profile is None
        assert result.confidence == "ambiguous"

    def test_enriches_nx_frontend_with_api_and_db_compose_lifecycle(self, tmp_path: Path) -> None:
        (tmp_path / "nx.json").write_text("{}", encoding="utf-8")
        (tmp_path / "compose.db.yml").write_text(
            "services:\n  postgres:\n    image: postgres:16-alpine\n    ports: ['5432:5432']\n",
            encoding="utf-8",
        )
        frontend = tmp_path / "apps" / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "project.json").write_text(
            """
{
  "name": "frontend",
  "projectType": "application",
  "targets": {
    "dev": {
      "executor": "nx:run-commands",
      "options": {
        "command": "next dev",
        "cwd": "apps/frontend"
      }
    }
  }
}
""",
            encoding="utf-8",
        )
        api = tmp_path / "apps" / "api"
        api.mkdir(parents=True)
        (api / "project.json").write_text(
            """
{
  "name": "api",
  "projectType": "application",
  "targets": {
    "serve": {
      "executor": "@nx/js:node",
      "options": {
        "buildTarget": "api:build"
      }
    }
  }
}
""",
            encoding="utf-8",
        )

        result = detect_app_runtime(tmp_path)

        assert result.profile is not None
        assert result.profile["setup_commands"] == ["docker compose -f compose.db.yml up -d"]
        assert result.profile["start_commands"] == [
            "npx nx serve api",
            "npx nx dev frontend",
        ]
        assert result.profile["stop_commands"] == [
            "docker compose -f compose.db.yml down",
            "npx nx reset",
        ]
