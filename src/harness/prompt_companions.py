"""Inline package-owned Markdown resources referenced by neutral prompts."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Iterable

from harness.prompt_markdown import read_prompt_markdown


_COMPANION_REFERENCE = re.compile(
    r"`((?:agents|commands|subagents|workflow)/[^`\s]+\.md)`"
)


def append_prompt_companions(body: str, roots: Iterable[Path]) -> str:
    """Append each referenced package Markdown resource once."""
    resolved_roots = tuple(root.resolve() for root in roots if root.is_dir())
    pending = list(_COMPANION_REFERENCE.findall(body))
    seen_references: set[str] = set()
    companion_sections: list[str] = []

    while pending:
        reference = pending.pop(0)
        if reference in seen_references or not _is_safe_reference(reference):
            continue
        seen_references.add(reference)
        companion = _resolve_reference(reference, resolved_roots)
        if companion is None:
            continue
        companion_body = read_prompt_markdown(companion).body
        companion_sections.append(
            f"---\n# Companion resource: {reference}\n\n{companion_body}"
        )
        pending.extend(_COMPANION_REFERENCE.findall(companion_body))

    if not companion_sections:
        return body
    return "\n\n".join([body, *companion_sections])


def prompt_package_roots(path: Path) -> tuple[Path, ...]:
    """Return sibling Prosaic/runtime roots for a bundled prompt path."""
    resolved = path.resolve()
    for ancestor in resolved.parents:
        if ancestor.name == "prosaic":
            return ancestor, ancestor.parent / "runtime"
        if ancestor.name == "runtime":
            return ancestor, ancestor.parent / "prosaic"
    return ()


def _is_safe_reference(reference: str) -> bool:
    path = PurePosixPath(reference)
    return not path.is_absolute() and ".." not in path.parts


def _resolve_reference(reference: str, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        candidate = (root / reference).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return None
