"""Extension registry sync checks migrated from shell tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _extension(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / "extension/extension.yml").read_text(encoding="utf-8"))


def _definition(root: Path) -> dict[str, Any]:
    return yaml.safe_load(
        (root / "extension/workflow/definition.yaml").read_text(encoding="utf-8")
    )


def _commands(root: Path) -> list[dict[str, Any]]:
    return list((_extension(root).get("provides") or {}).get("commands") or [])


def registered_agent_files(root: Path) -> list[str]:
    """Agent prompt files registered in extension.yml."""
    files: list[str] = []
    for command in _commands(root):
        file_ref = str(command.get("file") or "")
        if file_ref.startswith("agents/"):
            files.append(f"extension/{file_ref}")
    return sorted(files)


def actual_agent_prompt_files(root: Path) -> list[str]:
    """Agent prompt files on disk, excluding reference appendices/templates."""
    agent_root = root / "extension/agents"
    files: list[str] = []
    for path in agent_root.rglob("*.md"):
        parts = set(path.relative_to(agent_root).parts)
        if "appendices" in parts or "templates" in parts:
            continue
        files.append(str(path.relative_to(root)))
    return sorted(files)


def unregistered_agent_prompt_files(root: Path) -> list[str]:
    registered = set(registered_agent_files(root))
    return [path for path in actual_agent_prompt_files(root) if path not in registered]


def missing_registered_agent_files(root: Path) -> list[str]:
    actual = set(actual_agent_prompt_files(root))
    return [path for path in registered_agent_files(root) if path not in actual]


def _re_phases(root: Path) -> list[dict[str, Any]]:
    definition = _definition(root)
    phases: list[dict[str, Any]] = []
    for section in ("re_extraction", "re_retarget", "re_planning"):
        phases.extend((definition.get(section) or {}).get("phases") or [])
    return phases


def re_phase_count(root: Path) -> int:
    return len(_re_phases(root))


def missing_re_agent_phase_files(root: Path) -> list[str]:
    missing: list[str] = []
    for section in ("re_extraction", "re_planning"):
        for phase in (_definition(root).get(section) or {}).get("phases") or []:
            if phase.get("type") != "agent":
                continue
            agent = str(phase.get("agent") or "")
            if "-re-" not in agent:
                continue
            name = agent.split("-re-", 1)[1]
            path = root / "extension/agents/re" / f"{name}.md"
            if not path.exists():
                missing.append(str(path.relative_to(root)))
    return sorted(missing)


def re_agent_entry_count(root: Path) -> int:
    return sum(
        1
        for command in _commands(root)
        if "re-" in str(command.get("name") or "")
        and (command.get("behavior") or {}).get("execution") == "agent"
    )


def neutral_re_command_count(root: Path) -> int:
    return sum(
        1
        for command in _commands(root)
        if "re-" in str(command.get("name") or "")
        and (command.get("behavior") or {}).get("execution") != "agent"
        and "behavior" not in command
    )
