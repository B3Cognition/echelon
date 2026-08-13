"""Inline package-owned resources referenced by neutral prompts."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Iterable

from harness.prompt_markdown import read_prompt_markdown


_COMPANION_REFERENCE = re.compile(
    r"`((?:"
    r"\.echelon/prosaic/(?:agents|commands|subagents)/[^`\s]+\.(?:md|ya?ml|json)"
    r"|\.echelon/runtime/workflow/[^`\s]+\.md"
    r"|\.echelon/runtime/(?:templates|config|presets|stacks)/[^`\s]+\.(?:md|ya?ml|json)"
    r"|(?:agents|commands|subagents)/[^`\s]+\.(?:md|ya?ml|json)"
    r"|workflow/[^`\s]+\.md"
    r"|templates/[^`\s]+\.(?:md|ya?ml|json)"
    r"))`"
)
_NEGATIVE_RESOURCE_DIRECTIVE = re.compile(
    r"\b(?:do not|never|must not)\b.*\b(?:read|load|inspect|open|use|search)\b",
    flags=re.IGNORECASE,
)


class PromptCompanionError(ValueError):
    """Raised when a prompt's declared companion cannot be embedded safely."""


def prompt_companion_references(body: str) -> tuple[str, ...]:
    """Return package-owned resource references in encounter order."""
    references: list[str] = []
    for match in _COMPANION_REFERENCE.finditer(body):
        clause_start = max(
            body.rfind(separator, 0, match.start())
            for separator in ("\n", ".", ";")
        )
        clause = body[clause_start + 1 : match.start()]
        if _NEGATIVE_RESOURCE_DIRECTIVE.search(clause):
            continue
        references.append(match.group(1))
    return tuple(references)


def append_prompt_companions(body: str, roots: Iterable[Path]) -> str:
    """Embed each referenced package resource once without filesystem hints."""
    resolved_roots = tuple(root.resolve() for root in roots if root.is_dir())
    pending = list(prompt_companion_references(body))
    labels: dict[tuple[str, PurePosixPath], str] = {}
    companion_bodies: list[tuple[str, str]] = []

    while pending:
        reference = pending.pop(0)
        location = _reference_location(reference)
        if location is None or not _is_safe_reference(location[1].as_posix()):
            raise PromptCompanionError(
                f"unsafe prompt companion reference: {reference}"
            )
        if location in labels:
            continue
        companion = _resolve_reference(reference, resolved_roots)
        if companion is None:
            raise PromptCompanionError(
                f"unresolved prompt companion reference: {reference}"
            )
        label = f"Embedded Resource {len(labels) + 1}"
        labels[location] = label
        companion_body = _read_companion(companion)
        companion_bodies.append((label, companion_body))
        pending.extend(prompt_companion_references(companion_body))

    if not companion_bodies:
        return body
    companion_sections = [
        f"---\n# {label}\n\n{_sanitize_references(content, labels)}"
        for label, content in companion_bodies
    ]
    return "\n\n".join(
        [_sanitize_references(body, labels), *companion_sections]
    )


def prompt_package_roots(path: Path) -> tuple[Path, ...]:
    """Return sibling Prosaic/runtime roots for a bundled prompt path."""
    resolved = path.resolve()
    for ancestor in resolved.parents:
        if ancestor.name == "prosaic":
            return ancestor, ancestor.parent / "runtime"
        if ancestor.name == "runtime":
            return ancestor.parent / "prosaic", ancestor
    return ()


def _is_safe_reference(reference: str) -> bool:
    path = PurePosixPath(reference)
    return not path.is_absolute() and ".." not in path.parts


def _resolve_reference(reference: str, roots: tuple[Path, ...]) -> Path | None:
    location = _reference_location(reference)
    if location is None:
        return None
    namespace, relative = location
    for root in roots:
        if root.name != namespace:
            continue
        candidate = (root / relative).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    return None


def resolve_prompt_companion_reference(
    reference: str,
    roots: Iterable[Path],
) -> Path | None:
    """Resolve one recognized package resource below its owning bundle root."""
    resolved_roots = tuple(root.resolve() for root in roots if root.is_dir())
    return _resolve_reference(reference, resolved_roots)


def _reference_location(reference: str) -> tuple[str, PurePosixPath] | None:
    prefixes = (
        (".echelon/prosaic/", "prosaic"),
        (".echelon/runtime/", "runtime"),
    )
    for prefix, namespace in prefixes:
        if reference.startswith(prefix):
            return namespace, PurePosixPath(reference.removeprefix(prefix))

    path = PurePosixPath(reference)
    if not path.parts:
        return None
    if path.parts[0] in {"agents", "commands", "subagents"}:
        return "prosaic", path
    if path.parts[0] in {"workflow", "templates"}:
        return "runtime", path
    return None


def _read_companion(path: Path) -> str:
    if path.suffix.lower() == ".md":
        return read_prompt_markdown(path).body
    return path.read_text(encoding="utf-8", errors="replace")


def _sanitize_references(
    body: str,
    labels: dict[tuple[str, PurePosixPath], str],
) -> str:
    def replace(match: re.Match[str]) -> str:
        location = _reference_location(match.group(1))
        if location is None:
            return match.group(0)
        return labels.get(location, match.group(0))

    return _COMPANION_REFERENCE.sub(replace, body)
