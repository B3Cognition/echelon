"""Canonical Prosaic prose and runtime workflow sync checks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from harness.prompt_markdown import read_prompt_markdown


_AGENT_ID_RE = re.compile(r"echelon\.[a-z0-9-]+")


def _definition(root: Path) -> dict[str, Any]:
    return yaml.safe_load(
        (root / "runtime/workflow/definition.yaml").read_text(encoding="utf-8")
    )


def _collect_agent_ids(value: object) -> set[str]:
    agents: set[str] = set()
    if isinstance(value, dict):
        for field in ("agent", "id"):
            agent_id = value.get(field)
            if isinstance(agent_id, str) and _AGENT_ID_RE.fullmatch(agent_id):
                agents.add(agent_id)
        for child in value.values():
            agents.update(_collect_agent_ids(child))
    elif isinstance(value, list):
        for child in value:
            agents.update(_collect_agent_ids(child))
    return agents


def workflow_agent_ids(root: Path) -> list[str]:
    """Neutral subagent IDs dispatched by the canonical runtime workflow."""
    return sorted(_collect_agent_ids(_definition(root)))


def missing_workflow_agent_prompt_files(root: Path) -> list[str]:
    missing: list[str] = []
    for agent_id in workflow_agent_ids(root):
        path = root / "prosaic/subagents" / f"{agent_id}.md"
        if not path.is_file():
            missing.append(str(path.relative_to(root)))
    return missing


def invalid_subagent_frontmatter_names(root: Path) -> list[str]:
    invalid: list[str] = []
    for path in sorted((root / "prosaic/subagents").glob("*.md")):
        metadata = read_prompt_markdown(path).metadata
        if metadata.get("name") != path.stem:
            invalid.append(str(path.relative_to(root)))
    return invalid


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
    for phase in _re_phases(root):
        if phase.get("type") != "agent":
            continue
        agent = str(phase.get("agent") or "")
        path = root / "prosaic/subagents" / f"{agent}.md"
        if not path.is_file():
            missing.append(str(path.relative_to(root)))
    return sorted(missing)


def re_agent_entry_count(root: Path) -> int:
    return sum(1 for phase in _re_phases(root) if phase.get("type") == "agent")


def neutral_re_command_count(root: Path) -> int:
    return len(list((root / "prosaic/commands").glob("echelon.re-*.md")))
