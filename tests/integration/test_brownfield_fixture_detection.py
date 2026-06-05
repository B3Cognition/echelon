"""Optional brownfield fixture tests for deterministic harness detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.app_runtime_detection import detect_app_runtime
from harness.verify_detection import detect_verify_command


FIXTURES = {
    "ow-opta-widgets-v3-orig": Path("/Users/michalbachorik/work/sync/ui/ow-opta-widgets-v3-orig"),
    "cpp-monorepo": Path("/Users/michalbachorik/work/sync/ui/cpp/cpp-monorepo"),
    "baapi-basketball": Path("/Users/michalbachorik/work/sync/ui/cpp/baapi-basketball"),
    "thuuz-mmsite": Path("/Users/michalbachorik/work/sync/thuuz-mmsite"),
    "animacure": Path("/Users/michalbachorik/work/animacure"),
    "NavigationalPortal": Path("/Users/michalbachorik/work/NavigationalPortal"),
}


@pytest.mark.integration
@pytest.mark.parametrize(
    ("name", "verify_confidence", "verify_command", "app_confidence"),
    [
        ("ow-opta-widgets-v3-orig", "none", None, "none"),
        ("cpp-monorepo", "high", "npm test", "ambiguous"),
        ("baapi-basketball", "high", "uv run pytest", "none"),
        ("thuuz-mmsite", "none", None, "none"),
        ("animacure", "high", "pnpm test", "high"),
        ("NavigationalPortal", "none", None, "none"),
    ],
)
def test_brownfield_fixture_detection_summary(
    name: str,
    verify_confidence: str,
    verify_command: str | None,
    app_confidence: str,
) -> None:
    repo = FIXTURES[name]
    if not repo.exists():
        pytest.skip(f"brownfield fixture not available: {repo}")

    verify = detect_verify_command(repo)
    app = detect_app_runtime(repo)

    assert verify.confidence == verify_confidence
    assert verify.command == verify_command
    assert app.confidence == app_confidence


@pytest.mark.integration
def test_animacure_detects_compose_web_runtime() -> None:
    repo = FIXTURES["animacure"]
    if not repo.exists():
        pytest.skip(f"brownfield fixture not available: {repo}")

    result = detect_app_runtime(repo)

    assert result.profile == {
        "enabled": True,
        "mode": "docker_compose",
        "compose_file": "docker-compose.yml",
        "service": "web",
        "url": "http://localhost:3100",
    }


@pytest.mark.integration
def test_cpp_monorepo_reports_ambiguous_nx_browser_apps() -> None:
    repo = FIXTURES["cpp-monorepo"]
    if not repo.exists():
        pytest.skip(f"brownfield fixture not available: {repo}")

    result = detect_app_runtime(repo)

    assert result.profile is None
    assert result.confidence == "ambiguous"
    assert result.evidence == [
        "cpp/config-tool/project.json serve target uses next dev on port 8080",
        "cpp/frontend/project.json serve target uses next dev on port 3000",
    ]
