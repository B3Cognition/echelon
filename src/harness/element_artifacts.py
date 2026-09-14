"""Typed, source-preserving identity facts parsed from controller-owned artifacts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath


_ROLES = frozenset(
    {
        "unknowns",
        "assumptions",
        "requirements",
        "tasks",
        "issues",
        "lexicon",
        "lexicon_projection",
        "investigation",
        "evidence",
        "references",
        "intent",
    }
)


@dataclass(frozen=True)
class ArtifactSpan:
    start: int
    end: int
    line: int


@dataclass(frozen=True)
class ElementDeclaration:
    element_id: str
    kind: str
    caption: str
    content: str
    span: ArtifactSpan
    label_span: ArtifactSpan
    disposition: str


@dataclass(frozen=True)
class ElementReference:
    target_id: str
    range_end_id: str | None
    span: ArtifactSpan
    owner_id: str | None
    relation: str


@dataclass(frozen=True)
class ArtifactDiagnostic:
    code: str
    span: ArtifactSpan
    detail: str


@dataclass(frozen=True)
class ParsedIdentityArtifact:
    path: str
    role: str
    content_sha256: str
    declarations: tuple[ElementDeclaration, ...]
    references: tuple[ElementReference, ...]
    diagnostics: tuple[ArtifactDiagnostic, ...]


def parse_identity_artifact(*, path: str, role: str, text: str) -> ParsedIdentityArtifact:
    """Parse identity facts without opening ``path`` or mutating any storage."""
    _validate_input(path=path, role=role, text=text)
    if role in {"lexicon", "lexicon_projection"}:
        from harness.element_artifact_lexicon import parse_lexicon_source

        declarations, references, diagnostics = parse_lexicon_source(text, role)
    else:
        from harness.element_artifact_markdown import parse_markdown_source

        declarations, references, diagnostics = parse_markdown_source(text, role)
    return ParsedIdentityArtifact(
        path=path,
        role=role,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        declarations=tuple(declarations),
        references=tuple(references),
        diagnostics=tuple(diagnostics),
    )


def _validate_input(*, path: str, role: str, text: str) -> None:
    if type(path) is not str:
        raise ValueError("path must be a string")
    if type(role) is not str:
        raise ValueError("role must be a string")
    if type(text) is not str:
        raise ValueError("text must be a string")
    if role not in _ROLES:
        raise ValueError(f"role must be one of {sorted(_ROLES)}")
    if not path or "\\" in path or "\x00" in path:
        raise ValueError("path must be a canonical relative POSIX path")
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or parsed.as_posix() != path
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ValueError("path must be a canonical relative POSIX path")
    if "\x00" in text:
        raise ValueError("text contains NUL")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be UTF-8 encodable") from exc


__all__ = [
    "ArtifactDiagnostic",
    "ArtifactSpan",
    "ElementDeclaration",
    "ElementReference",
    "ParsedIdentityArtifact",
    "parse_identity_artifact",
]
