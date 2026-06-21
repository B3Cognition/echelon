"""Lexicon determinism gate — computes D(A).

A normative unit (a REQ's THEN main clause) is deterministic when it carries
exactly one uppercase modal. Uppercase modals are mandatory so their meaning
is unambiguous under RFC 8174 (e.g. ``MUST`` ≠ ``must``). Zero modals means no
normative force; two or more means an ambiguous compound obligation.

AC/ERROR/RULE THEN lines are NOT normative units — they carry observable
outcomes, recovery actions, and consequences respectively — so they are not
modal-checked here.
"""

from __future__ import annotations

import re

from lark.exceptions import LarkError

from .linter import Finding
from .parser import parse

# Longest forms first so "MUST NOT" is counted once, not as "MUST" + stray.
MODALS: tuple[str, ...] = ("MUST NOT", "SHALL NOT", "MUST", "SHALL", "SHOULD", "MAY")
_MODAL_RE = re.compile(r"\b(?:" + "|".join(m.replace(" ", r"\s+") for m in MODALS) + r")\b")


def _main_clauses(text: str) -> list[tuple[str, int]]:
    """Return (clause text, 1-based line) for every REQ main clause.

    Unparseable input has no assessable normative units (the P gate owns that
    failure), so this returns an empty list."""
    try:
        tree = parse(text)
    except LarkError:
        return []
    clauses: list[tuple[str, int]] = []
    for node in tree.find_data("main_clause"):
        token = node.children[0]  # the THEN value TEXT token
        clauses.append((str(token), token.line))
    return clauses


def _modal_count(clause: str) -> int:
    return len(_MODAL_RE.findall(clause))


def modal_findings(text: str) -> list[Finding]:
    """Flag every REQ main clause that does not carry exactly one modal."""
    findings: list[Finding] = []
    for clause, line in _main_clauses(text):
        count = _modal_count(clause)
        if count != 1:
            findings.append(
                Finding(
                    code="modal",
                    message=(
                        f"main clause must carry exactly one uppercase modal "
                        f"(found {count})"
                    ),
                    line=line,
                    span=clause.strip(),
                )
            )
    return findings


def determinism(text: str) -> float:
    """D(A): fraction of REQ main clauses carrying exactly one modal.

    No normative units -> vacuously deterministic (1.0)."""
    clauses = _main_clauses(text)
    if not clauses:
        return 1.0
    good = sum(1 for clause, _ in clauses if _modal_count(clause) == 1)
    return good / len(clauses)
