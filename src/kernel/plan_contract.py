"""Canonical plan.md section contract."""

from __future__ import annotations

import re
from dataclasses import dataclass


REQUIRED_SECTIONS = (
    "Summary",
    "Technical Context",
    "Architecture Decisions",
    "Requirement Preservation",
    "Project Structure",
    "Implementation Phases",
    "Testing Strategy",
    "Risks",
    "Constitution Check",
)

_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class PlanValidationResult:
    valid: bool
    sections: list[str]
    errors: list[str]


def parse_plan_sections(markdown: str) -> list[str]:
    """Return top-level H2 section names from a plan.md document."""
    return [_normalize_section(match.group(1)) for match in _H2_RE.finditer(markdown)]


def validate_plan_markdown(markdown: str) -> PlanValidationResult:
    sections = parse_plan_sections(markdown)
    section_set = set(sections)
    errors: list[str] = []

    title = _H1_RE.search(markdown)
    if title is None or "plan" not in title.group(1).lower():
        errors.append("missing plan title")

    for section in REQUIRED_SECTIONS:
        if section not in section_set:
            errors.append(f"missing required section: {section}")

    return PlanValidationResult(
        valid=not errors,
        sections=sections,
        errors=errors,
    )


def _normalize_section(section: str) -> str:
    return section.strip().split(":", 1)[0].strip()
