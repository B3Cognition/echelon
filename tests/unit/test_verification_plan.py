"""Unit tests for sandbox-owned verification planning."""

from __future__ import annotations

import json
from pathlib import Path

from harness.config import _parse_config
from harness.verification_plan import (
    SandboxServiceSpec,
    build_verification_plan,
    materialize_services,
)


def test_default_verification_plan_uses_sandbox_execution(tmp_path: Path) -> None:
    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.execution == "sandbox"


def test_pinned_playwright_dependency_selects_matching_image(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.62.1"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.image == "mcr.microsoft.com/playwright:v1.62.1-noble"
    assert plan.browser_requirement == "chromium"
    assert plan.bootstrap_commands == ("corepack enable && pnpm install --frozen-lockfile",)


def test_ranged_playwright_dependency_bootstraps_inside_sandbox(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.62.0"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")

    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.image == "node:20-slim"
    assert plan.bootstrap_commands == (
        "corepack enable && pnpm install --frozen-lockfile",
        "pnpm exec playwright install --with-deps chromium",
    )


def test_postgres_service_credentials_are_unique_per_sandbox_attempt() -> None:
    service = SandboxServiceSpec(
        service_name="postgres",
        image="postgres:16.4-alpine",
        environment_names=("TEST_DATABASE_URL",),
    )

    first = materialize_services((service,), session_id="attempt-one")
    second = materialize_services((service,), session_id="attempt-two")

    first_environment = dict(first.services[0].environment)
    second_environment = dict(second.services[0].environment)
    assert first_environment["POSTGRES_USER"] != second_environment["POSTGRES_USER"]
    assert first_environment["POSTGRES_PASSWORD"] != second_environment["POSTGRES_PASSWORD"]
    assert dict(first.verifier_environment)["TEST_DATABASE_URL"].startswith(
        "postgresql://" + first_environment["POSTGRES_USER"] + ":"
    )
    assert first.services[0].health_command[:3] == ("pg_isready", "-h", "127.0.0.1")


def test_verification_plan_consumes_resolved_stack_services(tmp_path: Path) -> None:
    service = SandboxServiceSpec(service_name="postgres", image="postgres:16.4-alpine")
    config = _parse_config({"provider": "docker"})
    config.verification_services = [service]

    plan = build_verification_plan(tmp_path, config)

    assert plan.services == (service,)
