"""Validated source projection for explicit Lexicon identity artifacts."""

from __future__ import annotations

import re

from lark.exceptions import LarkError, UnexpectedInput

from lexicon.parser import parse

from harness.element_artifacts import (
    ArtifactDiagnostic,
    ElementDeclaration,
    ElementReference,
)
from harness.element_artifact_markdown import (
    _ID_CORE,
    _NUMERIC_OR_COMPOSITE,
    _duplicate_diagnostics,
    _lines,
    _references,
    _span,
)


_ANY_BLOCK_RE = re.compile(
    r"^[ \t]*(?:REQ|AC|ERROR|RULE|INPUT|CLAIM|EVIDENCE|LIMIT|TBR):"
)
_GRAMMAR_BLOCK_RE = re.compile(
    r"^[ \t]*(?P<type>REQ|AC|ERROR|RULE|INPUT|CLAIM|EVIDENCE|LIMIT|TBR):[ \t]*(?P<id>[A-Za-z][A-Za-z0-9_-]*)[ \t]*$",
    re.ASCII,
)
_MANAGED_ID_RE = re.compile(rf"^{_ID_CORE}$", re.ASCII)
_REQ_ID_RE = re.compile(rf"^(?:FR|NFR)-{_NUMERIC_OR_COMPOSITE}$", re.ASCII)
_AC_ID_RE = re.compile(rf"^AC-{_NUMERIC_OR_COMPOSITE}$", re.ASCII)


def parse_lexicon_source(text: str, role: str):
    """Validate the whole grammar, then project each REQ/AC source block."""
    lines = _lines(text)
    line_starts = [line.start for line in lines]
    try:
        parse(text)
    except LarkError as exc:
        offset = _error_offset(exc, text)
        end = min(len(text), offset + 1)
        return [], [], [ArtifactDiagnostic(
            "invalid_lexicon", _span(offset, end, line_starts),
            f"Lexicon grammar rejected the document: {type(exc).__name__}",
        )]

    declarations: list[ElementDeclaration] = []
    diagnostics: list[ArtifactDiagnostic] = []
    excluded_reference_spans: list[tuple[int, int]] = []
    disposition = "definition" if role == "lexicon" else "projection"
    starts = [index for index, line in enumerate(lines) if _ANY_BLOCK_RE.match(line.body)]
    for index, line in enumerate(lines):
        managed_match = _GRAMMAR_BLOCK_RE.match(line.body)
        if managed_match is None:
            continue
        block_type = managed_match.group("type")
        element_id = managed_match.group("id")
        label_start = line.start + managed_match.start("id")
        label_span = _span(label_start, label_start + len(element_id), line_starts)
        supported = (
            block_type == "REQ" and _REQ_ID_RE.fullmatch(element_id) is not None
        ) or (block_type == "AC" and _AC_ID_RE.fullmatch(element_id) is not None)
        if block_type in {"REQ", "AC"} and not supported:
            diagnostics.append(ArtifactDiagnostic(
                "unsupported_lexicon_id", label_span,
                f"{block_type} cannot declare managed label {element_id}",
            ))
            excluded_reference_spans.append((label_span.start, label_span.end))
            continue
        if block_type not in {"REQ", "AC"} and _MANAGED_ID_RE.fullmatch(element_id):
            diagnostics.append(ArtifactDiagnostic(
                "unexpected_definition", label_span,
                f"{block_type} blocks cannot declare managed label {element_id}",
            ))
            excluded_reference_spans.append((label_span.start, label_span.end))
            continue
        if block_type not in {"REQ", "AC"}:
            continue
        later_starts = [candidate for candidate in starts if candidate > index]
        block_end = lines[later_starts[0]].start if later_starts else len(text)
        caption = _then_caption(lines, index, block_end)
        declarations.append(ElementDeclaration(
            element_id=element_id,
            kind=element_id.split("-", 1)[0],
            caption=caption,
            content=text[line.start:block_end],
            span=_span(line.start, block_end, line_starts),
            label_span=label_span,
            disposition=disposition,
        ))

    active = bytearray(b"\1" * len(text))
    references, reference_diagnostics = _references(
        text, "references", line_starts, active, declarations,
        excluded_spans=excluded_reference_spans,
    )
    references = [_lexicon_relation(reference, lines) for reference in references]
    diagnostics.extend(reference_diagnostics)
    diagnostics.extend(_duplicate_diagnostics(declarations))
    diagnostics.sort(key=lambda item: (item.span.start, item.span.end, item.code))
    return declarations, references, diagnostics


def _then_caption(lines, block_index: int, block_end: int) -> str:
    for line in lines[block_index + 1:]:
        if line.start >= block_end:
            break
        body = line.body.lstrip(" \t")
        if body.startswith("THEN:"):
            return body[len("THEN:"):].strip()
    return ""


def _lexicon_relation(reference: ElementReference, lines) -> ElementReference:
    containing_line = next(
        (line for line in lines if line.start <= reference.span.start < line.end), None
    )
    if containing_line is None or not containing_line.body.lstrip(" \t").startswith(
        "DEPENDS:"
    ):
        return reference
    return ElementReference(
        target_id=reference.target_id,
        range_end_id=reference.range_end_id,
        span=reference.span,
        owner_id=reference.owner_id,
        relation="depends",
    )


def _error_offset(exc: LarkError, text: str) -> int:
    if isinstance(exc, UnexpectedInput):
        position = getattr(exc, "pos_in_stream", None)
        if isinstance(position, int):
            return max(0, min(position, len(text)))
    return 0
