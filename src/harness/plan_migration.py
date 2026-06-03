"""Migrate legacy plan.md files to the canonical section contract."""

from __future__ import annotations

import re

from kernel.plan_contract import REQUIRED_SECTIONS, parse_plan_sections


_ALIASES = {
    "Architecture Decision Records": "Architecture Decisions",
    "Risks Identified by ARCHITECT": "Risks",
    "Quality Checklist": "Testing Strategy",
}

_DEFAULT_BODY = {
    "Architecture Decisions": (
        "Migration note: move ADR summaries or technology decisions here. "
        "Keep detailed rationale in `research.md` when available."
    ),
    "Testing Strategy": (
        "Migration note: describe unit, integration, E2E, compliance, and "
        "manual-gated checks required by this plan."
    ),
    "Risks": "Migration note: list architectural risks, mitigations, and owner.",
    "Constitution Check": (
        "| Principle | Compliance |\n"
        "| --- | --- |\n"
        "| Project constitution | Review required after migration. |"
    ),
}


def migrate_plan_markdown(markdown: str) -> str:
    """Return markdown with required canonical plan sections present."""
    migrated = _promote_nested_project_structure(markdown)
    migrated = _rename_alias_sections(migrated)
    migrated = _append_missing_sections(migrated)
    return migrated


def _promote_nested_project_structure(markdown: str) -> str:
    if "Project Structure" in parse_plan_sections(markdown):
        return markdown
    return re.sub(
        r"^### Project Structure[ \t]*$",
        "## Project Structure",
        markdown,
        count=1,
        flags=re.MULTILINE,
    )


def _rename_alias_sections(markdown: str) -> str:
    migrated = markdown
    for old, new in _ALIASES.items():
        if new in parse_plan_sections(migrated):
            continue
        migrated = re.sub(
            rf"^## {re.escape(old)}[ \t]*$",
            f"## {new}",
            migrated,
            count=1,
            flags=re.MULTILINE,
        )
    return migrated


def _append_missing_sections(markdown: str) -> str:
    sections = set(parse_plan_sections(markdown))
    additions: list[str] = []
    for section in REQUIRED_SECTIONS:
        if section in sections:
            continue
        body = _DEFAULT_BODY.get(section, "Migration note: fill this section from existing plan context.")
        additions.append(f"## {section}\n\n{body}\n")
    if not additions:
        return markdown
    return markdown.rstrip() + "\n\n---\n\n" + "\n".join(additions)
