"""Detached declarations from the two canonical Tracker table layouts."""
import re

from harness.element_artifact_reference_tokens import _NUMERIC_OR_COMPOSITE
from harness.element_artifacts import ArtifactDiagnostic, ArtifactSpan, ElementDeclaration


_HEADERS = {
    ("id", "statement", "source / context", "priority"): "UI",
    ("id", "inference", "evidence", "confidence"): "II",
}
_LABEL = re.compile(rf"(?:UI|II)-{_NUMERIC_OR_COMPOSITE}\Z", re.ASCII)
_SHAPED_ROW = re.compile(r"^\s*\|?\s*[*_`]*(?:UI|II)-")
_SEPARATOR = re.compile(r":?-{3,}:?\Z")


def _cells(body):
    """Keep offsets; escaped pipes are text, unescaped pipes delimit cells."""
    pipes, escaped = [], False
    for offset, char in enumerate(body):
        if char == "|" and not escaped:
            pipes.append(offset)
        escaped = not escaped if char == "\\" else False
    if len(pipes) < 2 or body[:pipes[0]].strip() or body[pipes[-1] + 1:].strip():
        return None
    return [(body[left + 1:right].strip(), left + 1 + len(body[left + 1:right]) - len(body[left + 1:right].lstrip()))
        for left, right in zip(pipes, pipes[1:])]


def parse_intent_rows(text, lines, active):
    """Only the caller's active Markdown can declare; no filesystem access."""
    declarations, diagnostics = [], []
    kind, pending_header = None, None
    for number, line in enumerate(lines, 1):
        body = line.body
        # Never reconstruct partially hidden cells: their source ownership is
        # ambiguous. Fully hidden fenced/quoted/comment examples stay inert.
        visible = active[line.start:line.start + len(body)]
        if not any(visible):
            kind = pending_header = None
            continue
        span = ArtifactSpan(line.start, line.end, number)
        shaped = "|" in body and bool(_SHAPED_ROW.match(body))

        def invalid():
            diagnostics.append(ArtifactDiagnostic("unsupported_declaration", span,
                "intent rows require a matching canonical header, separator and four nonempty cells"))

        cells = _cells(body)
        if cells is None:
            if shaped or ((kind is not None or pending_header is not None) and "|" in body):
                invalid()
            kind = pending_header = None
            continue
        values = tuple(value.casefold() for value, _ in cells)
        if not all(visible):
            if kind is not None or pending_header is not None or shaped:
                invalid()
            kind = pending_header = None
            continue
        header = _HEADERS.get(values)
        if header is not None:
            kind, pending_header = None, header
            continue
        if pending_header is not None:
            kind = pending_header if len(cells) == 4 and all(_SEPARATOR.fullmatch(value) for value, _ in cells) else None
            pending_header = None
            if kind is None:
                invalid()
            continue
        if kind is None:
            if shaped: invalid()
            continue
        if (len(cells) != 4 or not all(value for value, _ in cells)
                or not _LABEL.fullmatch(cells[0][0]) or not cells[0][0].startswith(kind + "-")):
            invalid()
            continue
        label, offset = cells[0]
        declarations.append(ElementDeclaration(label, kind, cells[1][0], text[line.start:line.end],
            span, ArtifactSpan(line.start + offset, line.start + offset + len(label), number), "definition"))
    return declarations, diagnostics
