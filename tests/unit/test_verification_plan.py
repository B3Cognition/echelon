"""Unit tests for sandbox-owned verification planning."""

from __future__ import annotations

import json
from pathlib import Path

from harness.config import _parse_config
from harness.verification_plan import build_verification_plan


def test_default_verification_plan_uses_sandbox_execution(tmp_path: Path) -> None:
    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.execution == "sandbox"


def test_pinned_playwright_dependency_selects_matching_image(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "1.62.1"}}),
        encoding="utf-8",
    )

    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.image == "mcr.microsoft.com/playwright:v1.62.1-noble"
    assert plan.browser_requirement == "chromium"
    assert plan.bootstrap_commands == ()


def test_ranged_playwright_dependency_bootstraps_inside_sandbox(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"devDependencies": {"@playwright/test": "^1.62.0"}}),
        encoding="utf-8",
    )

    plan = build_verification_plan(tmp_path, _parse_config({"provider": "docker"}))

    assert plan.image == "node:20-slim"
    assert plan.bootstrap_commands == (
        "pnpm exec playwright install --with-deps chromium",
    )
