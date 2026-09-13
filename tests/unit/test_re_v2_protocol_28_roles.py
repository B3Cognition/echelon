from __future__ import annotations

from pathlib import Path
import re

import yaml

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.protocol_22.provider import (
    canonical_prosaic_agent_bytes,
    decode_prosaic_agent_bytes,
)
from harness.re_v2.protocol_28.artifacts import (
    ExhaustiveEvidenceSliceV1,
    ExhaustiveVerificationV1,
)


ROOT = Path(__file__).resolve().parents[2]
SUBAGENTS = ROOT / "prosaic" / "subagents"
ROLES = {
    "echelon.re-exhaustive-analyst.md": (
        "echelon.re-exhaustive-analyst",
        "exhaustive-evidence-slice.json",
    ),
    "echelon.re-exhaustive-verifier.md": (
        "echelon.re-exhaustive-verifier",
        "exhaustive-verification.json",
    ),
}


def _agent(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _empty, raw, body = text.split("---", 2)
    metadata = yaml.safe_load(raw)
    assert isinstance(metadata, dict)
    return metadata, body.strip()


def test_l4_roles_are_neutral_write_only_and_pinned_independently() -> None:
    pinned: list[bytes] = []
    for filename, (agent_id, output_name) in ROLES.items():
        metadata, body = _agent(SUBAGENTS / filename)
        assert metadata == {
            "name": agent_id,
            "description": metadata["description"],
            "execution": "agent",
            "tools": "write",
            "color": "orange",
            "model_tier": "strong",
            "effort": "high",
        }
        assert output_name in body
        assert not re.search(r"\b(?:claude|codex|copilot|opencode|gpt-[\w.-]+)\b", body, re.I)
        assert body.count("ALWAYS ") == body.count("NEVER ")
        assert body.count("ALWAYS ") >= 7
        artifact = ProsaicCommandArtifact(dict(metadata), body)
        encoded = canonical_prosaic_agent_bytes(artifact)
        assert decode_prosaic_agent_bytes(encoded) == artifact
        pinned.append(encoded)

    assert pinned[0] != pinned[1]


def test_analyst_is_bounded_and_never_claims_controller_authority() -> None:
    _metadata, body = _agent(SUBAGENTS / "echelon.re-exhaustive-analyst.md")

    assert "one frozen slice" in body
    assert "live source workspace" in body
    assert "receipts, ledgers, events, roots" in body
    assert "ExhaustiveEvidenceSliceV1" in body
    assert "echelon_result:" in body
    assert "verdict: DONE" in body
    assert "absent sibling slices" in body
    assert "every claim has at least one `subject_ids` value" in body
    assert "supporting_subject_ids" in body
    assert "missing-primary-evidence-anchors" in body
    assert "Copy the nested `anchor` object for every primary evidence ID" in body


def test_verifier_uses_fresh_context_and_cannot_modify_candidate() -> None:
    _metadata, body = _agent(SUBAGENTS / "echelon.re-exhaustive-verifier.md")

    assert "fresh context" in body
    assert "producer reasoning" in body
    assert "NEVER modify" in body
    assert "PASS" in body and "REPAIR" in body
    assert "ExhaustiveVerificationV1" in body
    assert "malformed-result-contract" in body
    assert "global absence claims" in body


def test_producer_and_verifier_response_contracts_are_distinct() -> None:
    producer_fields = set(ExhaustiveEvidenceSliceV1.FIELDS)
    verifier_fields = set(ExhaustiveVerificationV1.FIELDS)

    assert {"claims", "observations", "rendered_markdown"} <= producer_fields
    assert {"verdict", "diagnostics", "candidate_id"} <= verifier_fields
    assert "verdict" not in producer_fields
    assert "claims" not in verifier_fields
