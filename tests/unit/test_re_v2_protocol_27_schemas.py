from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_27.policies import SYNTHESIS_GENERATED_KINDS


@pytest.mark.unit
def test_every_synthesis_kind_has_one_closed_canonical_schema() -> None:
    from harness.re_v2.protocol_27.schemas import (
        canonical_synthesis_response_schema_bytes,
        synthesis_response_schema,
    )

    identities = set()
    for kind in SYNTHESIS_GENERATED_KINDS:
        schema = synthesis_response_schema(kind)

        assert schema["additionalProperties"] is False
        assert set(schema["required"]) >= {
            "artifact_kind",
            "scope",
            "sections",
            "claims",
            "input_quality",
            "debt_refs",
        }
        payload = canonical_synthesis_response_schema_bytes(kind)
        assert payload == canonical_json_bytes(schema)
        identities.add(content_digest(payload))

    assert len(identities) == len(SYNTHESIS_GENERATED_KINDS)


@pytest.mark.unit
def test_unknown_synthesis_kind_has_no_fallback_schema() -> None:
    from harness.re_v2.protocol_27.schemas import (
        Protocol27SchemaContractError,
        synthesis_response_schema,
    )

    with pytest.raises(Protocol27SchemaContractError, match="unsupported"):
        synthesis_response_schema("invented-kind")


@pytest.mark.unit
def test_candidate_contract_rejects_extra_fields_and_duplicate_claims() -> None:
    from harness.re_v2.protocol_27.runtime import (
        Protocol27RuntimeError,
        SynthesisCandidateV1,
    )
    from tests.unit.test_re_v2_protocol_27_runtime import _candidate

    raw = _candidate().to_json_dict()
    raw["unexpected"] = True
    with pytest.raises(Protocol27RuntimeError, match="fields"):
        SynthesisCandidateV1.from_json_dict(raw)

    candidate = _candidate()
    with pytest.raises(Protocol27RuntimeError, match="claim.*unique"):
        replace(candidate, claims=(candidate.claims[0], candidate.claims[0]))
