"""Lexicon observability gate — computes O(A).

A normative unit (a REQ) requires an observable outcome: an ``OUTPUT:`` line.
Without it the requirement states an obligation with nothing a test or user can
observe. O(A) = reqs_with_output / reqs. (Applied to SPEC artifacts; STORY REQ
blocks intentionally omit OUTPUT.)
"""

from __future__ import annotations

from lark.exceptions import LarkError

from .linter import Finding
from .parser import parse


def _reqs(text: str):
    try:
        tree = parse(text)
    except LarkError:
        return []
    return list(tree.find_data("req"))


def _has_output(req) -> bool:
    return any(getattr(child, "data", None) == "output" for child in req.children)


def missing_output_findings(text: str) -> list[Finding]:
    """Flag every REQ block that lacks an OUTPUT line."""
    findings: list[Finding] = []
    for req in _reqs(text):
        if not _has_output(req):
            id_tok = req.children[0]  # the REQ id token
            findings.append(
                Finding(
                    code="missing-output",
                    message="REQ has no OUTPUT (observable result)",
                    line=id_tok.line,
                    span=str(id_tok),
                )
            )
    return findings


def observability(text: str) -> float:
    """O(A): fraction of REQ blocks that carry an OUTPUT line.

    No REQ blocks -> vacuously observable (1.0)."""
    reqs = _reqs(text)
    if not reqs:
        return 1.0
    return sum(1 for req in reqs if _has_output(req)) / len(reqs)
