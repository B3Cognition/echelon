"""Deterministic Docker-backed app runtime profile detection."""

from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - harness config already depends on yaml
    yaml = None  # type: ignore[assignment]


@dataclass(frozen=True)
class AppRuntimeDetectionResult:
    """A high-confidence harness.app profile, or the reason none was selected."""

    profile: dict[str, Any] | None
    confidence: str
    evidence: list[str] = field(default_factory=list)
    reason: str = ""


_COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
)
_DB_COMPOSE_FILES = (
    "compose.db.yml",
    "compose.db.yaml",
    "docker-compose.db.yml",
    "docker-compose.db.yaml",
)

def detect_app_runtime(repo_path: Path) -> AppRuntimeDetectionResult:
    """Detect a Docker-backed app runtime profile for browser screenshots.

    This intentionally detects only obvious cases. Ambiguous multi-app compose
    files and non-Docker dev-server scripts are left for manual configuration.
    """
    repo = Path(repo_path)

    compose = _detect_compose(repo)
    if compose.confidence in ("high", "ambiguous"):
        return compose

    dockerfile = _detect_dockerfile(repo)
    if dockerfile.confidence == "high":
        return dockerfile

    nx = _detect_nx_browser_app(repo)
    if nx.confidence in ("high", "ambiguous"):
        return nx

    return AppRuntimeDetectionResult(
        profile=None,
        confidence="none",
        reason="no high-confidence Docker app runtime detected",
    )


def _detect_compose(repo: Path) -> AppRuntimeDetectionResult:
    if yaml is None:
        return AppRuntimeDetectionResult(
            profile=None,
            confidence="none",
            reason="PyYAML unavailable; compose files cannot be parsed",
        )

    for filename in _COMPOSE_FILES:
        compose_file = repo / filename
        if not compose_file.exists():
            continue

        try:
            data = yaml.safe_load(compose_file.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            return AppRuntimeDetectionResult(
                profile=None,
                confidence="none",
                reason=f"{filename} could not be parsed: {exc}",
            )

        services = data.get("services")
        if not isinstance(services, dict):
            return AppRuntimeDetectionResult(
                profile=None,
                confidence="none",
                reason=f"{filename} has no services mapping",
            )

        candidates: list[tuple[str, int]] = []
        for service_name, service in services.items():
            if not isinstance(service, dict):
                continue
            host_port = _first_host_port(service.get("ports"))
            if host_port is not None:
                candidates.append((str(service_name), host_port))

        if not candidates:
            return AppRuntimeDetectionResult(
                profile=None,
                confidence="none",
                reason=f"{filename} has no service with host port mapping",
            )

        selected = _select_compose_candidate(candidates)
        if selected is None:
            return AppRuntimeDetectionResult(
                profile=None,
                confidence="ambiguous",
                evidence=[f"{name}:{port}" for name, port in candidates],
                reason="multiple compose services expose host ports; set harness.app manually",
            )

        service_name, host_port = selected
        return AppRuntimeDetectionResult(
            profile={
                "enabled": True,
                "mode": "docker_compose",
                "compose_file": filename,
                "service": service_name,
                "url": f"http://localhost:{host_port}",
            },
            confidence="high",
            evidence=[f"{filename} service {service_name} port {host_port}"],
        )

    return AppRuntimeDetectionResult(profile=None, confidence="none")


def _select_compose_candidate(candidates: list[tuple[str, int]]) -> tuple[str, int] | None:
    if len(candidates) == 1:
        return candidates[0]
    return None


def _first_host_port(ports: Any) -> int | None:
    if not isinstance(ports, list):
        return None

    for item in ports:
        port = _parse_port_mapping(item)
        if port is not None:
            return port
    return None


def _parse_port_mapping(item: Any) -> int | None:
    if isinstance(item, int):
        return item

    if isinstance(item, dict):
        published = item.get("published")
        if isinstance(published, int):
            return published
        if isinstance(published, str) and published.isdigit():
            return int(published)
        return None

    if not isinstance(item, str):
        return None

    parts = item.split(":")
    if len(parts) == 1:
        return int(parts[0]) if parts[0].isdigit() else None

    host = parts[-2] if len(parts) >= 2 else ""
    return int(host) if host.isdigit() else None


def _detect_dockerfile(repo: Path) -> AppRuntimeDetectionResult:
    dockerfile = repo / "Dockerfile"
    if not dockerfile.exists():
        return AppRuntimeDetectionResult(profile=None, confidence="none")

    try:
        text = dockerfile.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return AppRuntimeDetectionResult(
            profile=None,
            confidence="none",
            reason="Dockerfile is unreadable",
        )

    match = re.search(r"(?im)^\s*EXPOSE\s+(\d+)(?:/(?:tcp|udp))?\b", text)
    if match is None:
        return AppRuntimeDetectionResult(
            profile=None,
            confidence="none",
            reason="Dockerfile has no EXPOSE port",
        )

    port = int(match.group(1))
    return AppRuntimeDetectionResult(
        profile={
            "enabled": True,
            "mode": "dockerfile",
            "dockerfile": "Dockerfile",
            "container_port": port,
            "url": f"http://localhost:{port}",
        },
        confidence="high",
        evidence=[f"Dockerfile EXPOSE {port}"],
    )


def _detect_nx_browser_app(repo: Path) -> AppRuntimeDetectionResult:
    if not (repo / "nx.json").exists():
        return AppRuntimeDetectionResult(profile=None, confidence="none")

    candidates: list[dict[str, Any]] = []
    for project_file in sorted((repo / "apps").glob("*/project.json")):
        candidate = _nx_browser_candidate(repo, project_file)
        if candidate is not None:
            candidates.append(candidate)

    if len(candidates) == 1:
        candidate = candidates[0]
        name = candidate["name"]
        port = candidate["port"]
        db_compose = _detect_db_compose_file(repo)
        api = _detect_single_nx_api_app(repo)
        setup_commands: list[str] = []
        start_commands: list[str] = []
        stop_commands: list[str] = []

        if db_compose:
            setup_commands.append(f"docker compose -f {db_compose} up -d")
            stop_commands.append(f"docker compose -f {db_compose} down")
        if api:
            start_commands.append(f"npx nx serve {api}")
        start_commands.append(f"npx nx dev {name}")
        if db_compose or api:
            stop_commands.append("npx nx reset")

        profile: dict[str, Any] = {
            "enabled": True,
            "mode": "command",
            "app": name,
            "start_commands": start_commands,
            "url": f"http://localhost:{port}",
            "readiness_timeout_ms": 120000,
        }
        if setup_commands:
            profile["setup_commands"] = setup_commands
        if stop_commands:
            profile["stop_commands"] = stop_commands

        return AppRuntimeDetectionResult(
            profile=profile,
            confidence="high",
            evidence=[
                e for e in [
                    candidate["evidence"],
                    f"{db_compose} detected" if db_compose else "",
                    f"Nx API app {api} detected" if api else "",
                ]
                if e
            ],
        )

    if len(candidates) > 1:
        return AppRuntimeDetectionResult(
            profile=None,
            confidence="ambiguous",
            evidence=[c["evidence"] for c in candidates],
            reason="multiple Nx browser app candidates found; set harness.app manually",
        )

    return AppRuntimeDetectionResult(profile=None, confidence="none")


def _nx_browser_candidate(repo: Path, project_file: Path) -> dict[str, Any] | None:
    try:
        project = json.loads(project_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if project.get("projectType") != "application":
        return None

    name = project.get("name") or project_file.parent.name
    targets = project.get("targets")
    if not isinstance(targets, dict):
        return None

    dev = targets.get("dev")
    if not isinstance(dev, dict):
        return None

    options = dev.get("options")
    if not isinstance(options, dict):
        return None

    command = str(options.get("command", ""))
    if "next dev" not in command:
        return None

    port = _nx_target_port(dev) or _next_config_port(project_file.parent) or 3000
    rel_project = project_file.relative_to(repo).as_posix()
    return {
        "name": str(name),
        "port": int(port),
        "evidence": f"{rel_project} dev target uses next dev on port {port}",
    }


def _nx_target_port(target: dict[str, Any]) -> int | None:
    options = target.get("options")
    if isinstance(options, dict):
        port = options.get("port")
        if isinstance(port, int):
            return port
        if isinstance(port, str) and port.isdigit():
            return int(port)

        command = options.get("command")
        if isinstance(command, str):
            match = re.search(r"(?:--port|-p)\s+(\d+)", command)
            if match:
                return int(match.group(1))

    return None


def _detect_db_compose_file(repo: Path) -> str | None:
    for filename in _DB_COMPOSE_FILES:
        if (repo / filename).exists():
            return filename
    return None


def _detect_single_nx_api_app(repo: Path) -> str | None:
    candidates: list[str] = []
    for project_file in sorted((repo / "apps").glob("*/project.json")):
        try:
            project = json.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue

        if project.get("projectType") != "application":
            continue
        name = str(project.get("name") or project_file.parent.name)
        targets = project.get("targets")
        if not isinstance(targets, dict) or "serve" not in targets:
            continue
        lowered_name = name.lower()
        if lowered_name == "api" or lowered_name.endswith("-api") or "api" in project_file.parts:
            candidates.append(name)

    return candidates[0] if len(candidates) == 1 else None


def _next_config_port(project_dir: Path) -> int | None:
    for filename in ("next.config.js", "next.config.mjs", "next.config.ts"):
        path = project_dir / filename
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        match = re.search(r"\bport\s*:\s*(\d+)", text)
        if match:
            return int(match.group(1))
    return None
