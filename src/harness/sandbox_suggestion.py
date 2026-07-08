"""Deterministic sandbox suggestion reports for harness initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.app_runtime_detection import AppRuntimeDetectionResult, detect_app_runtime
from harness.verify_detection import VerifyDetectionResult, detect_verify_command


@dataclass(frozen=True)
class SandboxSuggestionReport:
    """Evidence-backed recommendation presented before risky setup actions."""

    confidence: str
    confidence_score: float
    detected_evidence: list[str] = field(default_factory=list)
    suggested_strategy: str = ""
    suggested_commands: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    human_approval_point: str = ""
    fallback_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "detected_evidence": self.detected_evidence,
            "suggested_strategy": self.suggested_strategy,
            "suggested_commands": self.suggested_commands,
            "risks": self.risks,
            "human_approval_point": self.human_approval_point,
            "fallback_path": self.fallback_path,
        }


_REPO_MARKERS = (
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    ".devcontainer/devcontainer.json",
    ".devcontainer/docker-compose.yml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "go.mod",
    "Cargo.toml",
    "Makefile",
    "README.md",
)


def detect_sandbox_suggestion(
    repo_path: Path,
    *,
    verify_detection: VerifyDetectionResult | None = None,
    app_detection: AppRuntimeDetectionResult | None = None,
) -> SandboxSuggestionReport:
    """Build a deterministic sandbox suggestion report for *repo_path*."""
    repo = Path(repo_path)
    verify = verify_detection or detect_verify_command(repo)
    app = app_detection or detect_app_runtime(repo)

    evidence = _dedupe(
        _marker_evidence(repo)
        + _readme_setup_evidence(repo)
        + _ci_evidence(repo)
        + verify.evidence
        + app.evidence
    )

    ambiguous = verify.confidence == "ambiguous" or app.confidence == "ambiguous"
    has_container = _has_container_marker(repo) or app.confidence in {"high", "existing"}
    has_verify = verify.command is not None and verify.confidence in {"high", "existing"}
    has_app = app.profile is not None and app.confidence in {"high", "existing"}

    if ambiguous:
        confidence = "manual_review"
        confidence_score = 0.55
        strategy = "Review conflicting repository signals before choosing a sandbox plan."
        commands: list[str] = []
    elif has_container and (has_verify or has_app):
        confidence = "high"
        confidence_score = 0.95
        strategy = "Use the Docker-backed harness sandbox."
        commands = _suggested_commands(verify, app)
    elif has_container or has_verify or has_app:
        confidence = "medium"
        confidence_score = 0.75 if has_container else 0.65
        strategy = "Use the Docker-backed harness sandbox after reviewing missing setup details."
        commands = _suggested_commands(verify, app)
    else:
        confidence = "low"
        confidence_score = 0.30
        strategy = "Do not auto-install dependencies or execute the app until setup is configured."
        commands = []

    return SandboxSuggestionReport(
        confidence=confidence,
        confidence_score=confidence_score,
        detected_evidence=evidence,
        suggested_strategy=strategy,
        suggested_commands=commands,
        risks=_risks(ambiguous=ambiguous, has_verify=has_verify, has_app=has_app),
        human_approval_point=(
            "Before dependency install or app execution, approve the sandbox plan, "
            "suggested commands, and bind-mount risk."
        ),
        fallback_path=(
            "If approval is withheld or confidence is not high, review and edit "
            ".echelon/config.yml with explicit "
            "verify_command, base_image, and harness.app settings, then rerun "
            "echelon delivery init."
        ),
    )


def render_sandbox_suggestion_markdown(report: SandboxSuggestionReport) -> str:
    """Render a stable human-readable sandbox suggestion report."""
    return "\n".join(
        [
            "## Sandbox Suggestion Report",
            "",
            f"**Confidence:** {report.confidence} ({report.confidence_score:.2f})",
            "",
            "### Detected Evidence",
            *_bullets(report.detected_evidence),
            "",
            "### Suggested Commands / Strategy",
            f"- Strategy: {report.suggested_strategy}",
            *_bullets(report.suggested_commands),
            "",
            "### Risks",
            *_bullets(report.risks),
            "",
            "### Human Approval Point",
            f"- {report.human_approval_point}",
            "",
            "### Fallback Path",
            f"- {report.fallback_path}",
        ]
    )


def _marker_evidence(repo: Path) -> list[str]:
    return [marker for marker in _REPO_MARKERS if (repo / marker).exists()]


def _readme_setup_evidence(repo: Path) -> list[str]:
    readme = repo / "README.md"
    if not readme.exists():
        return []
    try:
        text = readme.read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return []

    setup_markers = (
        "## setup",
        "## installation",
        "## getting started",
        "npm install",
        "npm ci",
        "pnpm install",
        "yarn install",
        "pip install",
        "uv sync",
        "mvn install",
        "gradle build",
        "go test",
        "cargo test",
    )
    if any(marker in text for marker in setup_markers):
        return ["README.md setup instructions"]
    return []


def _ci_evidence(repo: Path) -> list[str]:
    workflows = repo / ".github" / "workflows"
    if not workflows.exists():
        return []
    return [
        str(path.relative_to(repo))
        for path in sorted(workflows.glob("*.y*ml"))
        if path.is_file()
    ]


def _has_container_marker(repo: Path) -> bool:
    return any(
        (repo / marker).exists()
        for marker in (
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
            ".devcontainer/devcontainer.json",
            ".devcontainer/docker-compose.yml",
        )
    )


def _suggested_commands(
    verify: VerifyDetectionResult,
    app: AppRuntimeDetectionResult,
) -> list[str]:
    commands: list[str] = []
    if verify.command:
        commands.append(verify.command)
    if app.profile:
        commands.append(_app_command_summary(app.profile))
    return _dedupe(commands)


def _app_command_summary(profile: dict[str, Any]) -> str:
    mode = profile.get("mode")
    if mode == "docker_compose":
        compose_file = profile.get("compose_file", "docker-compose.yml")
        service = profile.get("service", "app")
        url = profile.get("url", "configured app URL")
        return f"Run {service} with docker compose -f {compose_file}; target {url}."
    if mode == "dockerfile":
        url = profile.get("url", "configured app URL")
        return f"Build/run app from Dockerfile; target {url}."
    if mode == "command":
        start = profile.get("start_commands") or []
        if isinstance(start, list) and start:
            return "; ".join(str(command) for command in start)
    return "Use configured harness.app runtime commands."


def _risks(*, ambiguous: bool, has_verify: bool, has_app: bool) -> list[str]:
    risks = [
        "Sandbox bind mounts can modify the target worktree.",
        "Dependency installation may execute package lifecycle hooks.",
    ]
    if has_app:
        risks.append("App runtime execution may expose local ports or start background services.")
    if not has_verify:
        risks.append("No high-confidence verify command was selected.")
    if ambiguous:
        risks.append("Ambiguous repository signals require human review before execution.")
    return risks


def _bullets(items: list[str]) -> list[str]:
    if not items:
        return ["- None."]
    return [f"- {item}" for item in items]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result
