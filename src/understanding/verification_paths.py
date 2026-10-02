"""Trace links and criterion wording without making a testability verdict.

This is a diagnostic companion to the existing quality metrics, not a gate.
Links expose a possible verification approach; they do not establish that an
AC adequately verifies its FR/NFR or that the described check was executed.
Input is the canonical spec projection, not the separate derived lexicon file.
"""

import re

from .constraint_metrics import ConstraintAnalyzer
from .requirement_projection import RequirementProjection


_SCENARIO_RE = re.compile(
    r"^given\s+(?P<given>.+?)[,;]\s*when\s+(?P<when>.+?)[,;]\s*"
    r"then\s+(?P<then>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_LEXICON_CLAUSE_RE = re.compile(r"^\s*(GIVEN|WHEN|THEN):\s*(.+?)\s*$", re.IGNORECASE)
_SUBJECTIVE_WORDS = (
    *ConstraintAnalyzer.SOFT_CONSTRAINT_KEYWORDS,
    "good",
    "nice",
    "beautiful",
)
_SUBJECTIVE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(word) for word in _SUBJECTIVE_WORDS) + r")\b",
    re.IGNORECASE,
)


def _criterion_path(criterion: RequirementProjection) -> dict[str, object]:
    text = criterion.normative_text.strip()
    clauses: dict[str, str] = {}
    if criterion.original_text.lstrip().upper().startswith("REQ:"):
        for line in criterion.original_text.splitlines():
            if match := _LEXICON_CLAUSE_RE.match(line):
                clauses[match.group(1).lower()] = match.group(2).strip()
    scenario = _SCENARIO_RE.match(text) if not clauses else None
    given = clauses.get("given") or (
        scenario.group("given").strip() if scenario else None
    )
    when = clauses.get("when") or (
        scenario.group("when").strip() if scenario else None
    )
    then = (
        clauses.get("then") or (scenario.group("then") if scenario else text)
    ).rstrip(" .;:").strip()
    # Inspection and analysis criteria need not use Given/When/Then syntax.
    flags: list[str] = []
    for match in _SUBJECTIVE_RE.finditer(then):
        flag = f"subjective_expected_outcome:{match.group(0).lower()}"
        if flag not in flags:
            flags.append(flag)
    return {
        "requirement_id": criterion.requirement_id,
        "source_location": {
            "line_start": criterion.source_location.line_start,
            "line_end": criterion.source_location.line_end,
        },
        "given": given,
        "when": when,
        "then": then,
        "review_flags": flags,
    }


# Research rationale: NASA recommends identifying a verification approach for
# each requirement and tracing acceptance criteria to requirements and methods.
# Ricca et al. found that acceptance tests can clarify requirements; research
# on requirement smells motivates flagging subjective outcome wording.
# None of these sources validates this heuristic as a pass/fail classifier:
# keep it shadow-only, and leave semantic alignment explicitly unassessed.
# https://www.nasa.gov/reference/appendix-d-requirements-verification-matrix/
# https://swehb.nasa.gov/spaces/SWEHBVD/pages/102695413/SWE-034%2B-%2BAcceptance%2BCriteria
# https://doi.org/10.1016/j.infsof.2008.01.007
# https://arxiv.org/abs/2403.17479
def assess_verification_paths(
    projections: tuple[RequirementProjection, ...],
) -> dict[str, dict[str, object]]:
    """Collect AC evidence for each FR/NFR, with no score or pass/fail state."""
    criteria = [item for item in projections if item.requirement_id.startswith("AC-")]
    result: dict[str, dict[str, object]] = {}
    for obligation in projections:
        if not obligation.requirement_id.startswith(("FR-", "NFR-")):
            continue
        linked = [
            criterion
            for criterion in criteria
            if obligation.requirement_id in criterion.traceability_references
            or criterion.requirement_id in obligation.traceability_references
        ]
        result[obligation.requirement_id] = {
            "mode": "shadow",
            "semantic_alignment": "not_assessed",
            "linked_acceptance_criteria": [_criterion_path(criterion) for criterion in linked],
            "review_flags": [] if linked else ["no_linked_acceptance_criterion"],
        }
    return result
