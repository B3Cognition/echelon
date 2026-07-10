"""Provider-specific runtime scaffolding for delivery worktrees."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from harness.runtime_surface import DELIVERY_COMMAND_FILES


ExcludeLine = Callable[[str], None]

RUNTIME_CLAUDE_AGENT_DIRS = (
    Path("build"),
)
class ProviderRuntimeScaffolder(Protocol):
    """Materializes AI-CLI-specific helper files for a synced runtime extension."""

    def sync(
        self,
        *,
        extension_root: Path,
        worktree: Path,
        exclude_line: ExcludeLine,
    ) -> None:
        """Create provider-specific ignored files under ``worktree``."""


class NoopProviderRuntimeScaffolder:
    """Provider runtime scaffolder for providers without worktree-local shims."""

    def sync(
        self,
        *,
        extension_root: Path,
        worktree: Path,
        exclude_line: ExcludeLine,
    ) -> None:
        return


class ClaudeProviderRuntimeScaffolder:
    """Materialize Claude CLI compatibility wrappers from Echelon runtime files."""

    def sync(
        self,
        *,
        extension_root: Path,
        worktree: Path,
        exclude_line: ExcludeLine,
    ) -> None:
        self._sync_command_skills(extension_root, worktree, exclude_line)
        self._sync_agents(extension_root, worktree, exclude_line)

    @staticmethod
    def _sync_command_skills(
        extension_root: Path,
        worktree: Path,
        exclude_line: ExcludeLine,
    ) -> None:
        commands_dir = extension_root / "commands"
        if not commands_dir.exists():
            return

        for command_file in sorted(commands_dir.glob("echelon.*.md")):
            if command_file.name not in DELIVERY_COMMAND_FILES:
                continue
            command_name = command_file.stem
            skill_name = "speckit-" + command_name.replace(".", "-")
            skill_dir = worktree / ".claude" / "skills" / skill_name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                _claude_skill_from_command(command_file, skill_name),
                encoding="utf-8",
            )
            exclude_line(f".claude/skills/{skill_name}/")

    @staticmethod
    def _sync_agents(
        extension_root: Path,
        worktree: Path,
        exclude_line: ExcludeLine,
    ) -> None:
        agents_dir = extension_root / "agents"
        if not agents_dir.exists():
            return

        target = worktree / ".claude" / "agents"
        target.mkdir(parents=True, exist_ok=True)
        agent_files: list[Path] = []
        for relative_dir in RUNTIME_CLAUDE_AGENT_DIRS:
            source_dir = agents_dir / relative_dir
            if source_dir.exists():
                agent_files.extend(source_dir.rglob("*.md"))
        for agent_file in sorted(agent_files):
            agent_name = f"speckit-echelon-{agent_file.stem}"
            (target / f"{agent_name}.md").write_text(
                _claude_agent_from_runtime_agent(agent_file, agent_name),
                encoding="utf-8",
            )
        exclude_line(".claude/agents/")


def provider_runtime_scaffolder(cli: str) -> ProviderRuntimeScaffolder:
    """Return the runtime scaffolder for an AI CLI provider."""
    if cli == "claude":
        return ClaudeProviderRuntimeScaffolder()
    return NoopProviderRuntimeScaffolder()


def _claude_skill_from_command(command_file: Path, skill_name: str) -> str:
    """Create a Claude skill wrapper from a synced Echelon command file."""
    raw = command_file.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(raw)
    description = _frontmatter_value(metadata, "description") or f"Run {command_file.stem}"
    body = _prefix_runtime_paths(body)
    return (
        "---\n"
        f"name: {skill_name}\n"
        f"description: {description}\n"
        "compatibility: Requires spec-kit project structure with .specify/ directory\n"
        "metadata:\n"
        "  author: github-spec-kit\n"
        f"  source: echelon:commands/{command_file.name}\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"{body.rstrip()}\n"
    )


def _claude_agent_from_runtime_agent(agent_file: Path, agent_name: str) -> str:
    """Create a Claude custom-agent file from a synced Echelon agent prompt."""
    raw = agent_file.read_text(encoding="utf-8")
    metadata, _body = _split_frontmatter(raw)
    if _frontmatter_value(metadata, "name"):
        return raw
    description = _first_heading(raw) or f"Echelon runtime agent {agent_name}"
    return (
        "---\n"
        f"name: {agent_name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{raw.rstrip()}\n"
    )


def _first_heading(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped.removeprefix("# ").strip()
    return None


def _split_frontmatter(raw: str) -> tuple[str, str]:
    if not raw.startswith("---\n"):
        return "", raw
    end = raw.find("\n---", 4)
    if end == -1:
        return "", raw
    body_start = raw.find("\n", end + 4)
    if body_start == -1:
        return raw[4:end], ""
    return raw[4:end], raw[body_start + 1 :]


def _frontmatter_value(metadata: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", metadata, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def _prefix_runtime_paths(body: str) -> str:
    prefix = ".specify/extensions/echelon/"
    for name in (
        "agents/",
        "workflow/",
        "commands/",
        "scripts/",
        "templates/",
        "config/",
        "presets/",
        "extension.yml",
        "echelon-config.yml",
    ):
        body = body.replace(f"`{name}", f"`{prefix}{name}")
    return body
