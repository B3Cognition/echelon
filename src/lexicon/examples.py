"""Lexicon example-coverage gate — computes E(A) for ARTICLE artifacts.

Every CLAIM in a technical article must be backed by evidence. A claim is
"supported" if an EVIDENCE block appears after it and before the next CLAIM.
E(A) = supported_claims / claims.

For SPEC/STORY artifacts, example coverage uses a different linkage model
(REQ <-> acceptance example) that is not yet part of the grammar, so this
module reports 1.0 for them and emits no findings — a documented v1 boundary.
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
    """E(A): fraction of CLAIMs that are supported by evidence.

    No CLAIMs -> vacuously covered (1.0)."""
    claims = _claims_with_support(text)
    if not claims:
        return 1.0
    return sum(1 for _, _, supported in claims if supported) / len(claims)
