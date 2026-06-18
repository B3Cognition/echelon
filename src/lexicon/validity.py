"""Lexicon validity aggregator — the hard gate Valid_k(A).

Composes the static hard gates: parse-pass P(A), banned-word linting, term
resolution T(A), determinism D(A), completeness C(A), observability O(A), and
example coverage E(A). Valid is binary: accepted only if every applicable gate
holds. A soft quality score (e.g. the `understanding` CLI) is never part of
this gate — it only orders repairs.

Gates are applied per artifact type (detected from the ARTIFACT header):
  SPEC    — P, banned, T, D, C, O
  STORY   — P, banned, T, D, C            (REQ blocks legitimately omit OUTPUT)
  ARTICLE — P, banned, T, C, E            (CLAIM/EVIDENCE coverage)

X (executable-example pass rate) is intentionally out of scope: it requires
running examples and belongs to the harness test phase, so it stays X == 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lark.exceptions import LarkError

from .completeness import completeness, placeholder_findings
from .determinism import determinism, modal_findings
from .examples import example_coverage, unsupported_claim_findings
from .linter import Finding, banned_word_findings
from .observability import missing_output_findings, observability
from .parser import artifact_type as _detect_type
from .parser import parse
from .resolver import term_resolution, unresolved_terms


@dataclass
class Report:
    ok: bool
    parse_pass: bool
    artifact_type: str | None
    term_resolution: float
    determinism: float
    completeness: float
    observability: float
    example_coverage: float
    findings: list[Finding] = field(default_factory=list)


def validate(
    text: str,
    glossary: set[str] | None = None,
    artifact_type: str | None = None,
) -> Report:
    """Run the static hard-gate stack over ``text``.

    ``artifact_type`` overrides header detection (e.g. from the CLI ``--type``);
    when omitted it is read from the ARTIFACT header."""
    glossary = glossary or set()
    findings: list[Finding] = []

    try:
        parse(text)
        parse_pass = True
    except LarkError as exc:
        parse_pass = False
        findings.append(
            Finding(
                code="parse-error",
                message=f"does not parse under the Lexicon grammar: {exc.__class__.__name__}",
                line=getattr(exc, "line", 0) or 0,
                span="",
            )
        )

    kind = (artifact_type or _detect_type(text) or "SPEC").upper()

    # Gates applicable to every artifact type.
    findings.extend(banned_word_findings(text))
    findings.extend(unresolved_terms(text, glossary))
    findings.extend(modal_findings(text))
    findings.extend(placeholder_findings(text))

    # Type-specific gates.
    if kind == "SPEC":
        findings.extend(missing_output_findings(text))
    if kind == "ARTICLE":
        findings.extend(unsupported_claim_findings(text))

    return Report(
        ok=not findings,
        parse_pass=parse_pass,
        artifact_type=_detect_type(text),
        term_resolution=term_resolution(text, glossary),
        determinism=determinism(text),
        completeness=completeness(text),
        observability=observability(text),
        example_coverage=example_coverage(text),
        findings=findings,
    )
