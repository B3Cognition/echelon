"""Deterministic, host-independent planning for delivery verification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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


def build_verification_plan(
    worktree: Path,
    config: HarnessConfig,
    services: tuple[SandboxServiceSpec, ...] = (),
) -> VerificationPlan:
    """Resolve the verifier environment without inspecting host tool caches."""
    fingerprint = fingerprint_repo(worktree)
    version = playwright_version(worktree)
    bootstrap: tuple[str, ...] = ()
    image = config.base_image or fingerprint.image
    browser_requirement: str | None = None

    if version is not None:
        browser_requirement = "chromium"
        if version.startswith("="):
            version = version[1:]
        if _is_pinned_version(version):
            image = f"mcr.microsoft.com/playwright:v{version}-noble"
        else:
            bootstrap = ("pnpm exec playwright install --with-deps chromium",)

    selected = set(config.stacks.selected)
    if "game-persistence-postgres" in selected and not services:
        services = (SandboxServiceSpec(
            service_name="postgres",
            image="postgres:16.4-alpine",
            environment_names=("TEST_DATABASE_URL", "DATABASE_URL"),
            health_command=("pg_isready", "-U", "echelon", "-d", "echelon_verify"),
            environment=(
                ("POSTGRES_USER", "echelon"),
                ("POSTGRES_PASSWORD", "echelon"),
                ("POSTGRES_DB", "echelon_verify"),
            ),
        ),)
    return VerificationPlan(
        execution=config.verification.execution,
        image=image,
        bootstrap_commands=bootstrap,
        browser_requirement=browser_requirement,
        services=services,
    )


def _is_pinned_version(value: str) -> bool:
    parts = value.split(".")
    return len(parts) == 3 and all(part.isdigit() for part in parts)
