"""Optional fixture test for og-platform brownfield app runtime detection."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.app_runtime_detection import detect_app_runtime


DEFAULT_OG_PLATFORM = Path("/Users/michalbachorik/work/sync/ui/og/og-platform")


@pytest.mark.integration
def test_og_platform_detects_frontend_command_profile() -> None:
    repo = Path(os.environ.get("ECHELON_OG_PLATFORM_FIXTURE", DEFAULT_OG_PLATFORM))
    if not repo.exists():
        pytest.skip(f"og-platform fixture not available: {repo}")

    result = detect_app_runtime(repo)

    assert result.confidence == "high"
    assert result.profile is not None
    assert result.profile["mode"] == "command"
    assert result.profile["app"] == "frontend"
    assert result.profile["setup_commands"] == ["docker compose -f compose.db.yml up -d"]
    assert result.profile["start_commands"] == [
        "npx nx serve api",
        "npx nx dev frontend",
    ]
    assert result.profile["stop_commands"] == [
        "docker compose -f compose.db.yml down",
        "npx nx reset",
    ]
    assert result.profile["url"] == "http://localhost:3000"
