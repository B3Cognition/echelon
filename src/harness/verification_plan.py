"""Deterministic, host-independent planning for delivery verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe

from harness.config import HarnessConfig
from harness.fingerprint import fingerprint_repo, playwright_version


@dataclass(frozen=True)
class SandboxServiceSpec:
    """A provider-neutral verification sidecar declaration."""

    service_name: str
    image: str
    environment_names: tuple[str, ...] = ()
    health_command: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class VerificationPlan:
    execution: str
    image: str
    bootstrap_commands: tuple[str, ...]
    browser_requirement: str | None
    services: tuple[SandboxServiceSpec, ...] = ()


@dataclass(frozen=True)
class MaterializedServices:
    """Ephemeral sidecar configuration and verifier environment for one run."""

    services: tuple[SandboxServiceSpec, ...]
    verifier_environment: tuple[tuple[str, str], ...]


def build_verification_plan(
    worktree: Path,
    config: HarnessConfig,
    services: tuple[SandboxServiceSpec, ...] = (),
) -> VerificationPlan:
    """Resolve the verifier environment without inspecting host tool caches."""
    fingerprint = fingerprint_repo(worktree)
    version = playwright_version(worktree)
    bootstrap: list[str] = []
    image = config.base_image or fingerprint.image
    browser_requirement: str | None = None

    if version is not None:
        browser_requirement = "chromium"
        if version.startswith("="):
            version = version[1:]
        if _is_pinned_version(version):
            image = f"mcr.microsoft.com/playwright:v{version}-noble"
        else:
            bootstrap.append("pnpm exec playwright install --with-deps chromium")

    install_command = _node_install_command(worktree)
    if install_command:
        bootstrap.insert(0, install_command)

    if not services:
        services = tuple(config.verification_services)
    return VerificationPlan(
        execution=config.verification.execution,
        image=image,
        bootstrap_commands=tuple(bootstrap),
        browser_requirement=browser_requirement,
        services=services,
    )


def _is_pinned_version(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)


def _node_install_command(worktree: Path) -> str | None:
    """Return the reproducible Node dependency install for a clean sandbox."""
    if (worktree / "pnpm-lock.yaml").is_file():
        # The official Node and Playwright images include Corepack, but do not
        # promise a globally-installed pnpm binary.  Enable it inside the
        # disposable sandbox before both installation and the verify command.
        return "corepack enable && pnpm install --frozen-lockfile"
    if (worktree / "package-lock.json").is_file() or (
        worktree / "npm-shrinkwrap.json"
    ).is_file():
        return "npm ci"
    if (worktree / "yarn.lock").is_file():
        return "yarn install --frozen-lockfile"
    return None


def materialize_services(
    services: tuple[SandboxServiceSpec, ...], *, session_id: str
) -> MaterializedServices:
    """Generate attempt-scoped sidecar credentials without touching the host."""
    materialized: list[SandboxServiceSpec] = []
    verifier_environment: list[tuple[str, str]] = []
    for service in services:
        if service.service_name != "postgres":
            materialized.append(service)
            continue
        username = "echelon_" + "".join(
            char for char in session_id.lower() if char.isalnum()
        )[:12]
        password = token_urlsafe(24)
        database = "echelon_verify"
        uri = f"postgresql://{username}:{password}@postgres:5432/{database}"
        materialized.append(SandboxServiceSpec(
            service_name=service.service_name,
            image=service.image,
            environment_names=service.environment_names,
            health_command=(
                "pg_isready", "-h", "127.0.0.1", "-U", username, "-d", database
            ),
            environment=(
                ("POSTGRES_USER", username),
                ("POSTGRES_PASSWORD", password),
                ("POSTGRES_DB", database),
            ),
        ))
        verifier_environment.extend((name, uri) for name in service.environment_names)
    return MaterializedServices(
        services=tuple(materialized),
        verifier_environment=tuple(verifier_environment),
    )
