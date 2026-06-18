"""Lexicon grammar parser — computes P(A), the parse-pass hard gate."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from lark import Lark, Tree
from lark.exceptions import LarkError

_GRAMMAR_PATH = Path(__file__).with_name("grammar.lark")


@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(
        _GRAMMAR_PATH.read_text(encoding="utf-8"),
        parser="lalr",
        start="start",
    )


def _normalize(text: str) -> str:
    """Ensure the document ends with a newline so the final block's trailing
    _NL is present (the grammar terminates every line with _NL)."""
    return text if text.endswith("\n") else text + "\n"


def parse(text: str) -> Tree:
    """Parse ``text`` and return the lark parse tree. Raises ``LarkError`` on a
    structural violation."""
    return _parser().parse(_normalize(text))


def parse_pass(text: str) -> bool:
    """Return True iff ``text`` parses under the Lexicon grammar (P(A) == 1)."""
    try:
        parse(text)
    except LarkError:
        return False
    return True


def artifact_type(text: str) -> str | None:
    """Return the declared artifact type ('SPEC'|'STORY'|'ARTICLE'), or None
    if the text does not parse / has no header."""
    try:
        tree = parse(text)
    except LarkError:
        return None
    for header in tree.find_data("header"):
        for child in header.children:
            if getattr(child, "type", None) == "TYPE":
                return str(child)
    return None
