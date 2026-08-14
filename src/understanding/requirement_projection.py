"""Canonical, deterministic projection of formal requirement evidence."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re


_CONVENTIONAL_REQUIREMENT_ID = r"[A-Z]{1,5}-\d{3,4}"
_REFERENCE_ID = r"(?:[A-Z][A-Z0-9]*(?:-\d+)+|[A-Z]+\d+)"
_INLINE_REFERENCE_RE = re.compile(
    rf"\b({_CONVENTIONAL_REQUIREMENT_ID})\b", re.IGNORECASE
)
_METADATA_REFERENCE_RE = re.compile(rf"\b({_REFERENCE_ID})\b", re.IGNORECASE)
_BULLET_RE = re.compile(
    rf"^\s*[-*+]\s+\*\*({_CONVENTIONAL_REQUIREMENT_ID})\*\*(?:\s*\([^)]*\))?\s*:\s*(.+\S)\s*$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(rf"^\s*#{{1,6}}\s+({_CONVENTIONAL_REQUIREMENT_ID})\b", re.IGNORECASE)
_STATEMENT_RE = re.compile(r"^\s*[-*+]\s+\*\*Statement\*\*\s*:\s*(.+\S)\s*$", re.IGNORECASE)
_FIELD_RE = re.compile(
    r"^\s*[-*+]\s+\*\*(Constraints?|Verified\s+by|Traceability|Depends)\*\*\s*:\s*(.+\S)\s*$",
    re.IGNORECASE,
)
_INLINE_METADATA_RE = re.compile(
    r"(?:^|\s)(Constraints?|Verified\s+by|Traceability|Depends)\s*:\s*",
    re.IGNORECASE,
)
_LEXICON_ID_RE = re.compile(r"^\s*REQ:\s*(\S+)\s*$", re.IGNORECASE)
_LEXICON_FIELD_RE = re.compile(
    r"^\s*(GIVEN|WHEN|THEN|OUTPUT|CONSTRAINT|CONSTRAINTS|VERIFIED\s+BY|TRACEABILITY|DEPENDS)\s*:\s*(.+\S)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceLocation:
    line_start: int
    line_end: int


@dataclass(frozen=True)
class RequirementProjection:
    requirement_id: str
    original_text: str
    normative_text: str
    traceability_references: tuple[str, ...]
    constraints: tuple[str, ...]
    source_location: SourceLocation


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _unique_references(
    inline_text: str, metadata_text: str, requirement_id: str
) -> tuple[str, ...]:
    own_id = requirement_id.upper()
    references: list[str] = []
    for pattern, text in (
        (_INLINE_REFERENCE_RE, inline_text),
        (_METADATA_REFERENCE_RE, metadata_text),
    ):
        for match in pattern.finditer(text):
            reference = match.group(1).upper()
            if reference != own_id and reference not in references:
                references.append(reference)
    return tuple(references)


def _split_inline_metadata(text: str) -> tuple[str, tuple[str, ...], str]:
    """Return normative prose, constraints, and metadata prose from one field."""
    matches = list(_INLINE_METADATA_RE.finditer(text))
    if not matches:
        return _normalise_text(text), (), ""

    normative = text[: matches[0].start()].strip()
    constraints: list[str] = []
    metadata: list[str] = []
    for index, match in enumerate(matches):
        value_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[match.end() : value_end].strip()
        if not value:
            continue
        label = match.group(1).lower()
        if label.startswith("constraint"):
            constraints.append(_normalise_text(value))
        else:
            metadata.append(value)
    return _normalise_text(normative), tuple(constraints), " ".join(metadata)


def _make_projection(
    requirement_id: str,
    original_text: str,
    normative_text: str,
    constraints: tuple[str, ...],
    source_location: SourceLocation,
    reference_text: str | None = None,
    metadata_reference_text: str = "",
) -> RequirementProjection:
    requirement_id = requirement_id.upper()
    references = _unique_references(
        reference_text or normative_text,
        metadata_reference_text,
        requirement_id,
    )
    return RequirementProjection(
        requirement_id=requirement_id,
        original_text=original_text,
        normative_text=_normalise_text(normative_text),
        traceability_references=references,
        constraints=constraints,
        source_location=source_location,
    )


def _project_conventional(lines: list[str]) -> list[RequirementProjection]:
    projections: list[RequirementProjection] = []
    seen_ids: set[str] = set()
    for index, line in enumerate(lines):
        match = _BULLET_RE.match(line)
        if not match:
            continue
        requirement_id, body = match.groups()
        requirement_id = requirement_id.upper()
        if requirement_id in seen_ids:
            continue
        normative, constraints, metadata = _split_inline_metadata(body)
        projections.append(
            _make_projection(
                requirement_id,
                body.strip(),
                normative,
                constraints,
                SourceLocation(index + 1, index + 1),
                normative,
                metadata,
            )
        )
        seen_ids.add(requirement_id)

    for index, line in enumerate(lines):
        heading = _HEADING_RE.match(line)
        if not heading:
            continue
        requirement_id = heading.group(1).upper()
        if requirement_id in seen_ids:
            continue
        statement_index: int | None = None
        statement: str | None = None
        fields: list[tuple[str, str]] = []
        field_indexes: list[int] = []
        unknown_prose: list[str] = []
        for candidate_index in range(index + 1, len(lines)):
            candidate = lines[candidate_index]
            if _HEADING_RE.match(candidate):
                break
            if not candidate.strip() and statement is not None:
                break
            statement_match = _STATEMENT_RE.match(candidate)
            if statement_match and statement is None:
                statement_index = candidate_index
                statement = statement_match.group(1)
                continue
            field = _FIELD_RE.match(candidate)
            if field:
                fields.append((field.group(1), field.group(2)))
                field_indexes.append(candidate_index)
            elif statement is not None and candidate.strip():
                unknown_prose.append(_normalise_text(candidate))
                field_indexes.append(candidate_index)
        if statement is None or statement_index is None:
            continue
        normative, inline_constraints, inline_metadata = _split_inline_metadata(statement)
        constraints = list(inline_constraints)
        metadata = [inline_metadata]
        for label, value in fields:
            if label.lower().startswith("constraint"):
                constraints.append(_normalise_text(value))
            else:
                metadata.append(value)
        source_end = max([statement_index, *field_indexes])
        original_parts = lines[statement_index : source_end + 1]
        if unknown_prose:
            normative = " ".join([normative, *unknown_prose])
        projections.append(
            _make_projection(
                requirement_id,
                "\n".join(original_parts),
                normative,
                tuple(constraints),
                SourceLocation(index + 1, source_end + 1),
                normative,
                " ".join(metadata),
            )
        )
        seen_ids.add(requirement_id)
    return projections


def _project_lexicon(lines: list[str]) -> list[RequirementProjection]:
    projections: list[RequirementProjection] = []
    for start, line in enumerate(lines):
        requirement = _LEXICON_ID_RE.match(line)
        if not requirement:
            continue
        end = start
        fields: dict[str, list[str]] = {}
        for index in range(start + 1, len(lines)):
            if _LEXICON_ID_RE.match(lines[index]):
                break
            if not lines[index].strip():
                break
            end = index
            field = _LEXICON_FIELD_RE.match(lines[index])
            if field:
                fields.setdefault(field.group(1).upper(), []).append(field.group(2).strip())
        then = fields.get("THEN", [])
        if not then:
            continue
        head: list[str] = []
        if fields.get("GIVEN"):
            head.append(f"Given {fields['GIVEN'][0].rstrip('.')}")
        if fields.get("WHEN"):
            head.append(f"when {fields['WHEN'][0].rstrip('.')}")
        head.append(then[0].rstrip("."))
        normative = ", ".join(head) + "."
        for output in fields.get("OUTPUT", []):
            normative += f" {output.rstrip('.')}" + "."
        constraints = tuple(fields.get("CONSTRAINT", []) + fields.get("CONSTRAINTS", []))
        original_lines = lines[start : end + 1]
        projections.append(
            _make_projection(
                requirement.group(1),
                "\n".join(original_lines),
                normative,
                constraints,
                SourceLocation(start + 1, end + 1),
                normative,
                " ".join(
                    value
                    for name in ("VERIFIED BY", "TRACEABILITY", "DEPENDS")
                    for value in fields.get(name, [])
                ),
            )
        )
    return projections


def project_requirements(spec_text: str) -> tuple[RequirementProjection, ...]:
    """Project each formal requirement into evidence for its metric family."""
    lines = spec_text.splitlines()
    projections = _project_conventional(lines) + _project_lexicon(lines)
    projections.sort(key=lambda projection: projection.source_location.line_start)
    known_ids = {projection.requirement_id for projection in projections}
    return tuple(
        replace(
            projection,
            traceability_references=tuple(
                reference
                for reference in projection.traceability_references
                if reference in known_ids or _INLINE_REFERENCE_RE.fullmatch(reference)
            ),
        )
        for projection in projections
    )
