"""Lexicon example-coverage gate — computes E(A) for ARTICLE artifacts.

Every CLAIM in a technical article must be backed by evidence. A claim is
"supported" if an EVIDENCE block appears after it and before the next CLAIM.
E(A) = supported_claims / claims.

For SPEC/STORY artifacts, example coverage means every REQ links at least one
acceptance criterion via an ``EXAMPLE: <AC-id>`` ref that resolves to a real AC
block. E(A) = covered REQs / REQs.
"""

from __future__ import annotations

from lark.exceptions import LarkError

from .linter import Finding
from .parser import parse


def _ordered_blocks(text: str):
    """Return the inner block subtrees in document order."""
    try:
        tree = parse(text)
    except LarkError:
        return []
    blocks = []
    for node in tree.children:
        if getattr(node, "data", None) == "block":
            blocks.append(node.children[0])
    return blocks


def _claims_with_support(text: str):
    """Return (claim_id, line, supported) for each CLAIM block."""
    blocks = _ordered_blocks(text)
    results = []
    for i, block in enumerate(blocks):
        if block.data != "claim":
            continue
        id_tok = block.children[0]
        supported = False
        for follower in blocks[i + 1 :]:
            if follower.data == "claim":
                break  # window for this claim ends at the next claim
            if follower.data == "evidence":
                supported = True
                break
        results.append((str(id_tok), id_tok.line, supported))
    return results


def _ac_ids(text: str) -> set[str]:
    """The set of AC block ids declared in the document."""
    try:
        tree = parse(text)
    except LarkError:
        return set()
    return {str(node.children[0]) for node in tree.find_data("ac")}


def _reqs_with_example_refs(text: str):
    """Return (req_id, line, [example_ac_refs]) for each REQ block."""
    try:
        tree = parse(text)
    except LarkError:
        return []
    out = []
    for req in tree.find_data("req"):
        id_tok = req.children[0]
        refs = [
            str(c.children[0]).strip()
            for c in req.children
            if getattr(c, "data", None) == "example"
        ]
        out.append((str(id_tok), id_tok.line, refs))
    return out


def missing_example_findings(text: str) -> list[Finding]:
    """Flag every REQ that lacks a resolvable EXAMPLE ref to an AC block.

    For SPEC/STORY artifacts, example coverage means each requirement is tied to
    at least one acceptance criterion via `EXAMPLE: <AC-id>`. A REQ with no
    EXAMPLE ref is `missing-example`; a ref to a non-existent AC is
    `unresolved-example`."""
    ac_ids = _ac_ids(text)
    findings: list[Finding] = []
    for req_id, line, refs in _reqs_with_example_refs(text):
        if not refs:
            findings.append(
                Finding(
                    code="missing-example",
                    message=f"REQ {req_id} has no EXAMPLE ref to an acceptance criterion",
                    line=line,
                    span=req_id,
                )
            )
            continue
        for ref in refs:
            if ref not in ac_ids:
                findings.append(
                    Finding(
                        code="unresolved-example",
                        message=f"REQ {req_id} EXAMPLE ref {ref!r} matches no AC block",
                        line=line,
                        span=req_id,
                    )
                )
    return findings


def unsupported_claim_findings(text: str) -> list[Finding]:
    """Flag every CLAIM not followed by an EVIDENCE block before the next CLAIM."""
    return [
        Finding(
            code="unsupported-claim",
            message=f"CLAIM {cid} has no supporting EVIDENCE",
            line=line,
            span=cid,
        )
        for cid, line, supported in _claims_with_support(text)
        if not supported
    ]


def example_coverage(text: str) -> float:
    """E(A): example coverage.

    SPEC/STORY (has REQ blocks): fraction of REQs with at least one EXAMPLE ref
    that resolves to a real AC block. ARTICLE (has CLAIM blocks): fraction of
    CLAIMs supported by evidence. Neither -> vacuously covered (1.0)."""
    reqs = _reqs_with_example_refs(text)
    if reqs:
        ac_ids = _ac_ids(text)
        covered = sum(1 for _id, _line, refs in reqs if any(r in ac_ids for r in refs))
        return covered / len(reqs)
    claims = _claims_with_support(text)
    if not claims:
        return 1.0
    return sum(1 for _, _, supported in claims if supported) / len(claims)
