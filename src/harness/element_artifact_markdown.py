"""Source scanning for Markdown identity declarations and references."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass

from kernel.element_ids import decimal_to_int
from kernel.task_contract import parse_task_rows

from harness.element_artifacts import (
    ArtifactDiagnostic,
    ArtifactSpan,
    ElementDeclaration,
    ElementReference,
)


_NUMERIC_OR_COMPOSITE = r"[0-9]+(?:[A-Za-z][A-Za-z0-9_-]*)?"
_TASK_VALUE = rf"(?:{_NUMERIC_OR_COMPOSITE}|S[0-9]{{2}}[A-Za-z]?)"
_ID_CORE = rf"(?:(?:AC|FR|NFR|ISS|U|A)-{_NUMERIC_OR_COMPOSITE}|T-{_TASK_VALUE})"
_ID_RE = re.compile(rf"(?<!\w){_ID_CORE}(?!\w)")
_HEADING_RE = re.compile(
    rf"^(?P<marks>#{{1,6}})[ \t]+(?P<id>{_ID_CORE})[ \t]*:[ \t]*(?P<caption>.*?)[ \t]*$",
    re.ASCII,
)
_ANY_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*$")
_LOOSE_HEADING_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marks>#{1,6})[ \t]+"
    r"(?P<id>(?:(?:AC|FR|NFR|ISS|U|A)-[0-9][^\s:]*|"
    r"T-(?:[0-9][^\s:]*|S[0-9][^\s:]*)))(?P<rest>.*)$"
)
_BULLET_RE = re.compile(
    rf"^(?P<indent>[ \t]*)(?P<marker>[-*+])[ \t]+(?P<open>\*\*|`)?(?P<id>{_ID_CORE})(?P<close>\*\*|`)?[ \t]*:[ \t]*(?P<caption>.*?)[ \t]*$",
    re.ASCII,
)
_LOOSE_BULLET_RE = re.compile(
    rf"^(?P<indent>[ \t]*)[-*+][ \t]+(?P<wrap>\*\*|`)(?P<id>{_ID_CORE})(?P=wrap)(?P<rest>.*)$"
)
_TASK_LIKE_RE = re.compile(rf"^- \[[ xX]\][ \t]+(?P<id>T-{_TASK_VALUE})\b")
_ANY_TASK_LIKE_RE = re.compile(r"^- \[[ xX]\][ \t]+(?P<id>T-[A-Za-z0-9_-]+)\b")
_TASK_TITLE_RE = re.compile(r"^[ \t]+\*\*Title:\*\*[ \t]*(?P<title>.+?)[ \t]*$")
_FENCE_OPEN_RE = re.compile(r"^[ ]{0,3}(?P<delim>`{3,}|~{3,})[^\r\n]*$")
_QUALIFIED_PATH_RE = re.compile(
    rf"(?<![\w.-])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+#{_ID_CORE}(?!\w)"
)
_QUALIFIED_SCOPE_RE = re.compile(
    rf"(?<![\w.-])[A-Za-z0-9][A-Za-z0-9_.-]*::{_ID_CORE}(?!\w)"
)
_RANGE_PAIR_RE = re.compile(
    rf"(?<!\w)(?P<first>{_ID_CORE})(?P<sep>[ \t]*(?:–|—|\.\.)[ \t]*|[ \t]+-[ \t]+)(?P<last>{_ID_CORE})(?!\w)"
)
_DANGLING_RANGE_RE = re.compile(
    rf"(?<!\w)(?P<first>{_ID_CORE})(?P<sep>[ \t]*(?:–|—|\.\.)[ \t]*)(?!{_ID_CORE})"
)
_NUMERIC_ID_RE = re.compile(r"^(?P<kind>AC|FR|NFR|ISS|U|A|T)-(?P<number>[0-9]+)$", re.ASCII)

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


def _owned_list_continuation(index: int, lines: list[_Line]) -> bool:
    body = lines[index].body
    if body.startswith("\t"):
        return False
    indentation = len(body) - len(body.lstrip(" "))
    if indentation < 4 or indentation >= 6:
        return False
    for candidate in reversed(lines[:index]):
        if not candidate.body.strip():
            continue
        candidate_indent = len(candidate.body) - len(candidate.body.lstrip(" "))
        if candidate_indent >= indentation:
            continue
        return re.match(r"^[ ]{0,3}[-*+][ \t]+", candidate.body) is not None
    return False


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

    in_fence: tuple[str, int, int] | None = None
    in_comment: int | None = None
    for index, line in enumerate(lines[first_available:], start=first_available):
        if in_fence is not None:
            char, length, _opener = in_fence
            _mark_inactive(active, line.start, line.end)
            if re.fullmatch(rf"[ ]{{0,3}}{re.escape(char)}{{{length},}}[ \t]*", line.body):
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
        fence = _FENCE_OPEN_RE.match(visible)
        if fence is not None:
            delimiter = fence.group("delim")
            in_fence = (delimiter[0], len(delimiter), line.start)
            _mark_inactive(active, line.start, line.end)
            continue
        if (
            re.match(r"^[ ]{0,3}>", visible)
            or visible.startswith("\t")
            or (visible.startswith("    ") and not _owned_list_continuation(index, lines))
        ):
            _mark_inactive(active, line.start, line.end)

    if in_fence is not None:
        opener = in_fence[2]
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
            code = None
            detail = None
            if not rest.startswith(":"):
                code = "unsupported_declaration"
                detail = "ID-bearing bullet does not use the supported declaration syntax"
            if code is not None:
                label_start = line.start + loose_bullet.start("id")
                diagnostics.append(ArtifactDiagnostic(
                    code,
                    _span(label_start, label_start + len(loose_bullet.group("id")), line_starts),
                    detail,
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

    for pattern in (_QUALIFIED_PATH_RE, _QUALIFIED_SCOPE_RE):
        for match in pattern.finditer(text):
            if not _is_active(active, match.start(), match.end()):
                continue
            blocked.append((match.start(), match.end()))
            diagnostics.append(ArtifactDiagnostic(
                "unsupported_qualified_reference", _span(match.start(), match.end(), line_starts),
                "qualified cross-spec references require a future namespace resolver",
            ))

    for match in _RANGE_PAIR_RE.finditer(text):
        if not _is_active(active, match.start(), match.end()) or _overlaps(match.start(), match.end(), blocked):
            continue
        blocked.append((match.start(), match.end()))
        first = match.group("first")
        last = match.group("last")
        first_numeric = _NUMERIC_ID_RE.fullmatch(first)
        last_numeric = _NUMERIC_ID_RE.fullmatch(last)
        valid = (
            first_numeric is not None and last_numeric is not None
            and first_numeric.group("kind") == last_numeric.group("kind")
            and decimal_to_int(first_numeric.group("number")) <= decimal_to_int(last_numeric.group("number"))
        )
        if valid:
            relation, owner_id = _reference_context(
                match.start(), match.end(), relation_regions, role, declarations
            )
            references.append(ElementReference(
                first, last, _span(match.start(), match.end(), line_starts),
                owner_id, relation,
            ))
        else:
            diagnostics.append(ArtifactDiagnostic(
                "invalid_range", _span(match.start(), match.end(), line_starts),
                "ranges require nondecreasing same-kind numeric endpoints",
            ))

    for match in _DANGLING_RANGE_RE.finditer(text):
        if not _is_active(active, match.start(), match.end()) or _overlaps(match.start(), match.end(), blocked):
            continue
        blocked.append((match.start(), match.end()))
        diagnostics.append(ArtifactDiagnostic(
            "invalid_range", _span(match.start(), match.end(), line_starts),
            "range separator requires a supported endpoint",
        ))

    for match in _ID_RE.finditer(text):
        if not _is_active(active, match.start(), match.end()) or _overlaps(match.start(), match.end(), blocked):
            continue
        relation, owner_id = _reference_context(
            match.start(), match.end(), relation_regions, role, declarations
        )
        references.append(ElementReference(
            match.group(0), None, _span(match.start(), match.end(), line_starts),
            owner_id, relation,
        ))
    references.sort(key=lambda item: (item.span.start, item.span.end))
    return references, diagnostics


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < other_end and end > other_start for other_start, other_end in spans)


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
