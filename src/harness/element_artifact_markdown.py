"""Source scanning for Markdown identity declarations and references."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from kernel.task_contract import parse_task_rows

from harness.element_artifact_reference_tokens import (
    _ID_CORE,
    _NUMERIC_OR_COMPOSITE,
    _TASK_VALUE,
    scan_reference_tokens,
)

from harness.element_artifacts import (
    ArtifactDiagnostic,
    ArtifactSpan,
    ElementDeclaration,
    ElementReference,
)


_HEADING_RE = re.compile(
    rf"^(?P<marks>#{{1,6}})[ \t]+(?P<id>{_ID_CORE})[ \t]*:[ \t]*(?P<caption>.*?)[ \t]*$",
    re.ASCII,
)
_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*$")
_DECLARATION_LABEL = r"(?:AC|FR|NFR|ISS|U|A|T)-[A-Za-z0-9][^\s:]*"
_LOOSE_HEADING_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marks>#{1,6})[ \t]+"
    rf"(?P<id>{_DECLARATION_LABEL})(?P<rest>.*)$"
)
_BULLET_RE = re.compile(
    rf"^(?P<indent>[ \t]*)(?P<marker>[-*+])[ \t]+(?P<open>\*\*|`)?(?P<id>{_ID_CORE})(?P<close>\*\*|`)?[ \t]*:[ \t]*(?P<caption>.*?)[ \t]*$",
    re.ASCII,
)
_LOOSE_BULLET_RE = re.compile(
    # Match enclosing delimiters separately: internal wrapper-like characters
    # still belong to an unsupported explicit label and its diagnostic span.
    rf"^(?P<indent>[ \t]*)[-*+][ \t]+(?P<wrap>\*\*|`)?"
    rf"(?P<id>{_DECLARATION_LABEL})(?(wrap)(?P=wrap))(?P<rest>.*)$"
)
_TASK_LIKE_RE = re.compile(rf"^- \[[ xX]\][ \t]+(?P<id>T-{_TASK_VALUE})\b")
_ANY_TASK_LIKE_RE = re.compile(r"^- \[[ xX]\][ \t]+(?P<id>T-[A-Za-z0-9_-]+)\b")
_TASK_TITLE_RE = re.compile(r"^[ \t]+\*\*Title:\*\*[ \t]*(?P<title>.+?)[ \t]*$")
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<delim>`{3,}|~{3,})[^\r\n]*$")
_LIST_MARKER_RE = re.compile(
    r"^(?P<indent> *)(?P<marker>[-*+])(?P<spacing>[ \t]{1,4})(?=\S)"
)

_ROLE_KINDS = {
    "unknowns": frozenset({"U"}),
    "assumptions": frozenset({"A"}),
    "requirements": frozenset({"FR", "NFR", "AC"}),
    "tasks": frozenset({"T"}),
    "issues": frozenset({"ISS"}),
}
_ROLE_DISPOSITION = {
    "unknowns": "definition",
    "assumptions": "definition",
    "requirements": "definition",
    "tasks": "definition",
    "issues": "occurrence",
}


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    body: str


@dataclass(frozen=True)
class _ContainerLine:
    content_indent: int
    blockquote: bool = False
    indented_code: bool = False


class _ContainerState:
    """Track bounded unordered-list content columns for source classification."""

    def __init__(self) -> None:
        self._content_indents: list[int] = []

    def classify(self, body: str) -> _ContainerLine:
        if not body.strip():
            content_indent = self._content_indents[-1] if self._content_indents else 0
            return _ContainerLine(content_indent)
        if body.startswith("\t"):
            return _ContainerLine(0, indented_code=True)

        indentation = len(body) - len(body.lstrip(" "))
        while self._content_indents and indentation < self._content_indents[-1]:
            self._content_indents.pop()

        parent_indent = self._content_indents[-1] if self._content_indents else 0
        relative = _relative_body(body, parent_indent)
        if re.match(r"^[ ]{0,3}>", relative):
            return _ContainerLine(parent_indent, blockquote=True)

        marker = _LIST_MARKER_RE.match(body)
        if marker is not None:
            marker_indent = len(marker.group("indent"))
            if marker_indent >= parent_indent + 4:
                return _ContainerLine(parent_indent, indented_code=True)
            content_indent = marker.end()
            self._content_indents.append(content_indent)
            return _ContainerLine(parent_indent)

        if self._content_indents:
            content_indent = self._content_indents[-1]
            return _ContainerLine(
                content_indent,
                indented_code=indentation >= content_indent + 4,
            )
        return _ContainerLine(0, indented_code=indentation >= 4)


def parse_markdown_source(text: str, role: str):
    """Return declarations, references, and diagnostics found in Markdown."""
    lines = _lines(text)
    line_starts = [line.start for line in lines]
    active, diagnostics = _active_source(text, lines, line_starts)
    declarations, declaration_diagnostics = _declarations(
        text, role, lines, line_starts, active
    )
    diagnostics.extend(declaration_diagnostics)
    unsupported_spans = [
        (diagnostic.span.start, diagnostic.span.end)
        for diagnostic in declaration_diagnostics
        if diagnostic.code in {"ambiguous_block_boundary", "unsupported_declaration"}
    ]
    references, reference_diagnostics = _references(
        text, role, line_starts, active, declarations, unsupported_spans
    )
    diagnostics.extend(reference_diagnostics)
    diagnostics.extend(_duplicate_diagnostics(declarations))
    diagnostics.sort(key=lambda item: (item.span.start, item.span.end, item.code))
    return declarations, references, diagnostics


def _lines(text: str) -> list[_Line]:
    result: list[_Line] = []
    offset = 0
    for raw in text.splitlines(keepends=True):
        if raw.endswith("\r\n"):
            body = raw[:-2]
        elif raw.endswith(("\n", "\r")):
            body = raw[:-1]
        else:
            body = raw
        result.append(_Line(offset, offset + len(raw), body))
        offset += len(raw)
    return result


def _span(start: int, end: int, line_starts: list[int]) -> ArtifactSpan:
    line = bisect.bisect_right(line_starts, start) if line_starts else 1
    return ArtifactSpan(start=start, end=end, line=max(line, 1))


def _is_active(active: bytearray, start: int, end: int) -> bool:
    return start < end and all(active[index] for index in range(start, end))


def _mark_inactive(active: bytearray, start: int, end: int) -> None:
    active[start:end] = b"\0" * (end - start)


def _visible_body(line: _Line, active: bytearray) -> str:
    return "".join(
        character if active[line.start + offset] else " "
        for offset, character in enumerate(line.body)
    )


def _relative_body(body: str, content_indent: int) -> str:
    prefix = " " * content_indent
    return body[content_indent:] if content_indent and body.startswith(prefix) else body


def _active_source(text: str, lines: list[_Line], line_starts: list[int]):
    active = bytearray(b"\1" * len(text))
    diagnostics: list[ArtifactDiagnostic] = []
    first_available = 0
    if lines and lines[0].start == 0 and lines[0].body == "---":
        close = next(
            (
                index
                for index in range(1, len(lines))
                if lines[index].body == "---"
            ),
            None,
        )
        if close is None:
            _mark_inactive(active, 0, len(text))
            diagnostics.append(ArtifactDiagnostic(
                "unterminated_frontmatter", _span(0, len(text), line_starts),
                "frontmatter opener has no closing delimiter",
            ))
            return active, diagnostics
        _mark_inactive(active, 0, lines[close].end)
        first_available = close + 1

    in_fence: tuple[str, int, int, int] | None = None
    in_comment: int | None = None
    containers = _ContainerState()
    for line in lines[first_available:]:
        if in_fence is not None:
            char, length, content_indent, _opener = in_fence
            _mark_inactive(active, line.start, line.end)
            relative = _relative_body(line.body, content_indent)
            if re.fullmatch(
                rf"[ ]{{0,3}}{re.escape(char)}{{{length},}}[ \t]*", relative
            ):
                in_fence = None
            continue

        body_end = line.start + len(line.body)
        cursor = line.start
        if in_comment is not None:
            close = text.find("-->", cursor, body_end)
            if close < 0:
                _mark_inactive(active, line.start, line.end)
                continue
            _mark_inactive(active, line.start, close + 3)
            in_comment = None
            cursor = close + 3

        container = containers.classify(_visible_body(line, active))
        if container.blockquote or container.indented_code:
            _mark_inactive(active, line.start, line.end)
            continue

        while cursor < body_end:
            opener = text.find("<!--", cursor, body_end)
            if opener < 0:
                break
            close = text.find("-->", opener + 4, body_end)
            if close < 0:
                _mark_inactive(active, opener, line.end)
                in_comment = opener
                break
            _mark_inactive(active, opener, close + 3)
            cursor = close + 3

        visible = _visible_body(line, active)
        if not visible.strip():
            continue
        relative = _relative_body(visible, container.content_indent)
        fence = _FENCE_OPEN_RE.match(relative)
        if fence is not None:
            delimiter = fence.group("delim")
            in_fence = (
                delimiter[0], len(delimiter), container.content_indent, line.start
            )
            _mark_inactive(active, line.start, line.end)

    if in_fence is not None:
        opener = in_fence[3]
        diagnostics.append(ArtifactDiagnostic(
            "unterminated_fence", _span(opener, len(text), line_starts),
            "fenced code opener has no matching closing delimiter",
        ))
    if in_comment is not None:
        diagnostics.append(ArtifactDiagnostic(
            "unterminated_comment", _span(in_comment, len(text), line_starts),
            "HTML comment opener has no closing delimiter",
        ))
    return active, diagnostics


def _declarations(
    text: str,
    role: str,
    lines: list[_Line],
    line_starts: list[int],
    active: bytearray,
):
    declarations: list[ElementDeclaration] = []
    diagnostics: list[ArtifactDiagnostic] = []
    allowed = _ROLE_KINDS.get(role, frozenset())

    for index, line in enumerate(lines):
        body = _visible_body(line, active)
        if not body.strip():
            continue
        heading = _HEADING_RE.match(body)
        if heading is not None:
            element_id = heading.group("id")
            kind = _kind(element_id)
            label_start = line.start + heading.start("id")
            label_span = _span(label_start, label_start + len(element_id), line_starts)
            exact_level_required = role in {"unknowns", "assumptions", "issues"}
            if (
                kind not in allowed
                or role == "tasks"
                or (exact_level_required and len(heading.group("marks")) != 3)
            ):
                diagnostics.append(ArtifactDiagnostic(
                    "unexpected_definition", label_span,
                    f"{element_id} heading cannot define an element in role {role}",
                ))
                continue
            block_end = _heading_end(index, heading.group("marks"), role, lines, active)
            declarations.append(ElementDeclaration(
                element_id, kind, heading.group("caption"), text[line.start:block_end],
                _span(line.start, block_end, line_starts), label_span,
                _ROLE_DISPOSITION[role],
            ))
            continue

        loose_heading = _LOOSE_HEADING_RE.match(body)
        if loose_heading is not None:
            label_start = line.start + loose_heading.start("id")
            label_end = line.start + loose_heading.end("id")
            code = (
                "ambiguous_block_boundary"
                if loose_heading.group("indent")
                else "unsupported_declaration"
            )
            diagnostics.append(ArtifactDiagnostic(
                code,
                _span(label_start, label_end, line_starts),
                "indented ID-bearing heading has ambiguous declaration ownership"
                if loose_heading.group("indent")
                else "ID-bearing heading does not use the supported declaration syntax",
            ))
            continue

        bullet = _BULLET_RE.match(body)
        if bullet is not None:
            element_id = bullet.group("id")
            kind = _kind(element_id)
            label_start = line.start + bullet.start("id")
            label_span = _span(label_start, label_start + len(element_id), line_starts)
            balanced = bool(bullet.group("open")) == bool(bullet.group("close")) and (
                not bullet.group("open") or bullet.group("open") == bullet.group("close")
            )
            if role != "requirements" or kind not in allowed or not balanced:
                diagnostics.append(ArtifactDiagnostic(
                    "unexpected_definition", label_span,
                    f"{element_id} bullet cannot define an element in role {role}",
                ))
                continue
            block_end = _indented_block_end(
                index, lines, len(bullet.group("indent"))
            )
            declarations.append(ElementDeclaration(
                element_id, kind, bullet.group("caption"), text[line.start:block_end],
                _span(line.start, block_end, line_starts), label_span, "definition",
            ))

        task_like = _TASK_LIKE_RE.match(body)
        if task_like is not None and role == "tasks":
            block_end = _indented_block_end(index, lines, 0)
            block = text[line.start:block_end]
            parsed = parse_task_rows(body + "\n")
            label_start = line.start + task_like.start("id")
            label_span = _span(label_start, label_start + len(task_like.group("id")), line_starts)
            if len(parsed) != 1:
                diagnostics.append(ArtifactDiagnostic(
                    "malformed_task", _span(line.start, line.end, line_starts),
                    "task-looking row does not satisfy the canonical task row contract",
                ))
                continue
            titles = []
            for title_line in lines[index + 1:]:
                if title_line.start >= block_end:
                    break
                title_body = _visible_body(title_line, active)
                if not title_body.strip():
                    continue
                title_match = _TASK_TITLE_RE.match(title_body)
                if title_match is not None:
                    titles.append(title_match.group("title"))
            if not titles:
                diagnostics.append(ArtifactDiagnostic(
                    "missing_task_title", label_span,
                    "canonical task row requires one subordinate **Title:** field",
                ))
                continue
            if len(titles) > 1:
                diagnostics.append(ArtifactDiagnostic(
                    "duplicate_task_title", label_span,
                    "canonical task row has more than one subordinate **Title:** field",
                ))
                continue
            declarations.append(ElementDeclaration(
                parsed[0].task_id, "T", titles[0], block,
                _span(line.start, block_end, line_starts), label_span, "definition",
            ))
        elif task_like is not None and role != "tasks":
            label_start = line.start + task_like.start("id")
            diagnostics.append(ArtifactDiagnostic(
                "unexpected_definition",
                _span(label_start, label_start + len(task_like.group("id")), line_starts),
                f"task row cannot define an element in role {role}",
            ))

        broad_task = _ANY_TASK_LIKE_RE.match(body)
        if role == "tasks" and task_like is None and broad_task is not None:
            diagnostics.append(ArtifactDiagnostic(
                "malformed_task", _span(line.start, line.end, line_starts),
                "task-looking row uses an unsupported task label or row syntax",
            ))

        loose_bullet = _LOOSE_BULLET_RE.match(body)
        if loose_bullet is not None and bullet is None:
            rest = loose_bullet.group("rest").lstrip()
            if loose_bullet.group("wrap") or rest.startswith(":"):
                label_start = line.start + loose_bullet.start("id")
                diagnostics.append(ArtifactDiagnostic(
                    "unsupported_declaration",
                    _span(label_start, label_start + len(loose_bullet.group("id")), line_starts),
                    "ID-bearing bullet does not use the supported declaration syntax",
                ))

    declarations.sort(key=lambda item: item.span.start)
    return declarations, diagnostics


def _heading_end(
    index: int,
    marks: str,
    role: str,
    lines: list[_Line],
    active: bytearray,
) -> int:
    level = len(marks)
    companion_seen = False
    for candidate in lines[index + 1:]:
        body = _visible_body(candidate, active)
        if not body.strip():
            continue
        heading = _ANY_HEADING_RE.match(body)
        if heading is None or len(heading.group("marks")) > level:
            continue
        if (
            role == "issues" and not companion_seen
            and len(heading.group("marks")) == level
            and heading.group("title").strip().casefold() == "resolution guidance"
        ):
            companion_seen = True
            continue
        return candidate.start
    return lines[-1].end if lines else 0


def _indented_block_end(index: int, lines: list[_Line], base_indent: int) -> int:
    end = lines[index].end
    pending_blanks: list[_Line] = []
    for candidate in lines[index + 1:]:
        if not candidate.body.strip():
            pending_blanks.append(candidate)
            continue
        indentation = len(candidate.body) - len(candidate.body.lstrip(" \t"))
        if indentation > base_indent:
            if pending_blanks:
                end = pending_blanks[-1].end
                pending_blanks.clear()
            end = candidate.end
            continue
        break
    return end


def _references(
    text: str,
    role: str,
    line_starts: list[int],
    active: bytearray,
    declarations: list[ElementDeclaration],
    excluded_spans: list[tuple[int, int]] | None = None,
):
    references: list[ElementReference] = []
    diagnostics: list[ArtifactDiagnostic] = []
    relation_regions = _task_relation_regions(text, declarations)
    blocked = [
        (declaration.label_span.start, declaration.label_span.end)
        for declaration in declarations
    ]
    blocked.extend(excluded_spans or ())

    for token in scan_reference_tokens(text, active=active, excluded_spans=blocked):
        span = _span(token.start, token.end, line_starts)
        if token.diagnostic_code is not None:
            diagnostics.append(ArtifactDiagnostic(token.diagnostic_code, span, token.detail))
            continue
        relation, owner_id = _reference_context(
            token.start, token.end, relation_regions, role, declarations
        )
        references.append(ElementReference(
            token.target_id, token.range_end_id, span,
            owner_id, relation,
        ))
    return references, diagnostics


def _task_relation_regions(
    text: str, declarations: list[ElementDeclaration]
) -> list[tuple[int, int, str, str]]:
    regions: list[tuple[int, int, str, str]] = []
    for declaration in declarations:
        if declaration.kind != "T":
            continue
        first_line_end = text.find("\n", declaration.span.start, declaration.span.end)
        if first_line_end < 0:
            first_line_end = declaration.span.end
        row = text[declaration.span.start:first_line_end].rstrip("\r")
        for field, relation in (("req", "requires"), ("depends", "depends")):
            field_match = re.search(
                rf"\b{field}=(?P<value>[A-Za-z0-9_,.-]+)", row
            )
            if field_match is None:
                continue
            regions.append((
                declaration.span.start + field_match.start("value"),
                declaration.span.start + field_match.end("value"),
                relation,
                declaration.element_id,
            ))
    return regions


def _reference_context(
    start: int,
    end: int,
    relation_regions: list[tuple[int, int, str, str]],
    role: str,
    declarations: list[ElementDeclaration],
) -> tuple[str, str | None]:
    for region_start, region_end, relation, owner_id in relation_regions:
        if region_start <= start and end <= region_end:
            return relation, owner_id
    return _default_relation(role), _owner_id(start, declarations)


def _owner_id(offset: int, declarations: list[ElementDeclaration]) -> str | None:
    owners = [
        declaration
        for declaration in declarations
        if declaration.span.start <= offset < declaration.span.end
    ]
    if not owners:
        return None
    return max(owners, key=lambda item: (item.span.start, -item.span.end)).element_id


def _kind(element_id: str) -> str:
    return element_id.split("-", 1)[0]


def _default_relation(role: str) -> str:
    return "evidence" if role in {"investigation", "evidence"} else "reference"


def _duplicate_diagnostics(declarations: list[ElementDeclaration]) -> list[ArtifactDiagnostic]:
    seen: set[str] = set()
    diagnostics: list[ArtifactDiagnostic] = []
    for declaration in declarations:
        if declaration.element_id in seen:
            code = {
                "definition": "duplicate_definition",
                "projection": "duplicate_projection",
                "occurrence": "duplicate_occurrence",
            }[declaration.disposition]
            diagnostics.append(ArtifactDiagnostic(
                code, declaration.label_span,
                f"repeated {declaration.disposition} label {declaration.element_id}",
            ))
        seen.add(declaration.element_id)
    return diagnostics
