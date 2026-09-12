"""Pure, source-preserving whole-token classification of visible references."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from kernel.element_ids import decimal_to_int


_NUMERIC_OR_COMPOSITE = r"[0-9]+(?:[A-Za-z][A-Za-z0-9_-]*)?"
_TASK_VALUE = rf"(?:{_NUMERIC_OR_COMPOSITE}|S[0-9]{{2}}[A-Za-z]?)"
_ID_CORE = rf"(?:(?:AC|FR|NFR|ISS|U|A)-{_NUMERIC_OR_COMPOSITE}|T-{_TASK_VALUE})"
_SUPPORTED = re.compile(_ID_CORE)
_SHAPED = re.compile(r"(?<!\w)[`*_]*(?:AC|FR|NFR|ISS|U|A|T)-[A-Za-z0-9]")
_NUMERIC = re.compile(r"(?P<kind>AC|FR|NFR|ISS|U|A|T)-(?P<number>[0-9]+)")
_LOCAL = re.compile(rf"investigation/(?P<id>{_ID_CORE})\.md")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
_DELIMITERS = frozenset(',;:!?()[]{}<>\"\'|=')
_RUNS = re.compile(r"`+|\*{1,2}|_{1,2}")


@dataclass(frozen=True)
class ReferenceToken:
    start: int
    end: int
    target_id: str | None = None
    range_end_id: str | None = None
    diagnostic_code: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class _Lexeme:
    start: int
    end: int
    separator: bool = False


def _boundary(text: str, index: int) -> bool:
    if index < 0 or index >= len(text):
        return True
    if text[index] == ".":
        return (
            index + 1 == len(text) or text[index + 1].isspace()
            or text[index + 1] in _DELIMITERS or text[index + 1] == "."
            or (index > 0 and text[index - 1] == ".")
        )
    return text[index].isspace() or text[index] in _DELIMITERS or text[index] in "–—"


def _wrapper_masks(
    text: str, active: bytearray, excluded_spans: Sequence[tuple[int, int]],
) -> tuple[bytearray, bytearray, list[tuple[int, int]]]:
    """Mark only paired enclosing syntax; code closers use the exact run length."""
    syntax = bytearray(len(text))
    literal = bytearray(len(text))
    enclosures: list[tuple[int, int]] = []
    runs = list(_RUNS.finditer(text))
    for index, opener in enumerate(runs):
        start, end = opener.span()
        code = opener.group()[0] == "`"
        if syntax[start] or literal[start] or not (_boundary(text, start - 1) or syntax[start - 1]):
            continue
        if start and text[start - 1] in ":?=":
            prefix_start = start - 1
            while (
                prefix_start and not syntax[prefix_start - 1]
                and not text[prefix_start - 1].isspace()
                and (text[prefix_start - 1] not in _DELIMITERS or text[prefix_start - 1] in ":?=")
            ):
                prefix_start -= 1
            prefix = text[prefix_start:start - 1]
            if _qualified(prefix) or (text[start - 1] == ":" and _SCHEME.fullmatch(prefix)):
                continue
        if end == len(text) or (not code and text[end].isspace()):
            continue
        for closer in runs[index + 1:]:
            if closer.group() != opener.group():
                continue
            enclosing_close = _boundary(text, closer.end()) or syntax[closer.end()]
            if not enclosing_close or (not code and text[closer.start() - 1].isspace()):
                continue
            if not all(active[start:closer.end()]):
                continue
            if any(start < right and closer.end() > left for left, right in excluded_spans):
                continue
            # Emphasis cannot enclose a blank line. Inline code may cross lines.
            if not code and "\n\n" in text[end:closer.start()]:
                break
            syntax[start:end] = b"\1" * (end - start)
            syntax[closer.start():closer.end()] = b"\1" * len(closer.group())
            enclosures.append((start, closer.start()))
            if code:
                literal[end:closer.start()] = b"\1" * (closer.start() - end)
            break
    return syntax, literal, enclosures


def _qualified(value: str) -> bool:
    return any(mark in value for mark in ("/", "\\", "#", ":", ".md", "?"))


def _lexemes(text: str, syntax: bytearray, literal: bytearray) -> list[_Lexeme]:
    result: list[_Lexeme] = []
    cursor = 0
    while cursor < len(text):
        if syntax[cursor] or text[cursor].isspace():
            cursor += 1
            continue
        start = cursor
        if text[cursor] in "–—" or (text.startswith("..", cursor) and not text.startswith("../", cursor)):
            cursor += 2 if text.startswith("..", cursor) else 1
            result.append(_Lexeme(start, cursor, True))
            continue
        if text[cursor] == "-" and cursor > 0 and text[cursor - 1].isspace() and (cursor + 1 == len(text) or text[cursor + 1].isspace()):
            cursor += 1
            result.append(_Lexeme(start, cursor, True))
            continue
        while cursor < len(text) and not syntax[cursor] and not text[cursor].isspace():
            char = text[cursor]
            if char in "–—" or (text.startswith("..", cursor) and not text.startswith("../", cursor)):
                break
            if char in _DELIMITERS:
                if char == ":" and text.startswith("::", cursor):
                    cursor += 2
                    continue
                if char == ":" and text.startswith("://", cursor):
                    cursor += 3
                    continue
                if char == ":" and _SCHEME.fullmatch(text[start:cursor]) and cursor + 1 < len(text) and not text[cursor + 1].isspace():
                    cursor += 1
                    continue
                if char in ":?=" and _qualified(text[start:cursor]):
                    cursor += 1
                    continue
                break
            cursor += 1
        if cursor == start:
            cursor += 1
            continue
        end = cursor
        if text[end - 1] == "." and not literal[end - 1] and (end < 2 or text[end - 2] != "."):
            end -= 1
        if start < end:
            result.append(_Lexeme(start, end))
    return result


def _diagnostic(start: int, end: int, code: str) -> ReferenceToken:
    detail = {
        "unsupported_reference": "reference requires a complete supported identity label",
        "unsupported_qualified_reference": "qualified references require a future namespace resolver",
        "invalid_range": "ranges require exactly two nondecreasing same-kind numeric endpoints",
    }[code]
    return ReferenceToken(start, end, diagnostic_code=code, detail=detail)


def scan_reference_tokens(
    text: str, *, active: bytearray,
    excluded_spans: Sequence[tuple[int, int]],
) -> tuple[ReferenceToken, ...]:
    """Classify complete visible references without IO or source mutation."""
    syntax, literal, enclosures = _wrapper_masks(text, active, excluded_spans)
    lexemes = _lexemes(text, syntax, literal)
    result: list[ReferenceToken] = []

    def visible(start: int, end: int) -> bool:
        return (
            all(active[start:end])
            and not any(start < right and end > left for left, right in excluded_spans)
            # A hidden source boundary cannot terminate a successful prefix.
            and (start == 0 or active[start - 1] or text[start - 1].isspace())
            and (end == len(text) or active[end] or text[end].isspace())
        )

    def adjacent(left: _Lexeme, right: _Lexeme) -> bool:
        # A wrapper around a complete expression separates outside prose;
        # wrappers around its individual endpoints remain part of its span.
        if any(
            (right.separator and left.end <= opening < right.start)
            or (left.separator and left.end <= closing < right.start)
            for opening, closing in enclosures
        ):
            return False
        return all(text[i] in " \t" or syntax[i] for i in range(left.end, right.start))

    def shaped(item: _Lexeme) -> bool:
        # Leading unmatched wrappers are retained in the diagnostic spelling.
        return _SHAPED.search(text[item.start:item.end]) is not None

    index = 0
    while index < len(lexemes):
        first = lexemes[index]
        group = [first]
        following = index + 1
        while following < len(lexemes):
            previous, current = group[-1], lexemes[following]
            if not adjacent(previous, current) or (not previous.separator and not current.separator):
                break
            separator = previous if previous.separator else current
            if text[separator.start:separator.end] == "-":
                # A spaced ASCII dash followed by prose never begins an interval.
                # Once started, repeated separators and malformed endpoints belong
                # to the same rejected expression and cannot expose singletons.
                if not any(item.separator for item in group):
                    right = lexemes[following + 1] if following + 1 < len(lexemes) else None
                    if not shaped(previous):
                        break
                    if right is not None and adjacent(separator, right) and not right.separator and not shaped(right):
                        break
                elif len(group) == 1:
                    # A leading list marker is not an identity interval.
                    break
            group.append(current)
            following += 1
        index = following
        start, end = first.start, group[-1].end
        if not any(shaped(item) for item in group if not item.separator) or not visible(start, end):
            continue
        endpoints = [item for item in group if not item.separator]
        values = [text[item.start:item.end] for item in endpoints]
        if any(item.separator for item in group):
            if any(_qualified(value) for value in values):
                result.append(_diagnostic(start, end, "unsupported_qualified_reference"))
                continue
            numbers = [_NUMERIC.fullmatch(value) for value in values]
            if len(group) == 3 and not first.separator and len(numbers) == 2 and all(numbers):
                left, right = numbers
                if left.group("kind") == right.group("kind") and decimal_to_int(left.group("number")) <= decimal_to_int(right.group("number")):
                    result.append(ReferenceToken(start, end, values[0], values[1]))
                    continue
            result.append(_diagnostic(start, end, "invalid_range"))
            continue
        value = values[0]
        local = _LOCAL.fullmatch(value)
        if local:
            result.append(ReferenceToken(start + local.start("id"), start + local.end("id"), local.group("id")))
        elif _qualified(value):
            result.append(_diagnostic(start, end, "unsupported_qualified_reference"))
        elif _SUPPORTED.fullmatch(value):
            result.append(ReferenceToken(start, end, value))
        else:
            result.append(_diagnostic(start, end, "unsupported_reference"))
    return tuple(result)
