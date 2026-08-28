from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_27.model import SynthesisScopeV1
from tests.re_v2_protocol_27_fixtures import digest
from tests.unit.test_re_v2_protocol_27_context import (
    _source_item,
    _validated_inputs,
)


def _candidate(
    *,
    kind: str = "source-contracts",
    source_id: str = "api",
    input_quality: str = "complete",
    debt_refs: tuple[str, ...] = (),
    authority_id: str | None = None,
):
    from harness.re_v2.protocol_27.runtime import (
        SynthesisCandidateV1,
        SynthesisClaimV1,
        SynthesisEvidenceReferenceV1,
        SynthesisSectionV1,
    )
    from harness.re_v2.protocol_27.schemas import required_section_ids

    authority = authority_id or digest(f"{source_id}:overview-markdown")
    sections = tuple(
        SynthesisSectionV1(
            section_id,
            section_id.replace("-", " ").title(),
            ("claim-1",),
        )
        for section_id in required_section_ids(kind)
    )
    return SynthesisCandidateV1(
        schema_version=1,
        artifact_kind=kind,
        scope=SynthesisScopeV1(1, "source", source_id, None, (source_id,)),
        sections=sections,
        claims=(
            SynthesisClaimV1(
                "claim-1",
                "The accepted overview establishes this contract.",
                (
                    SynthesisEvidenceReferenceV1(
                        "dependency-artifact",
                        authority,
                        source_id,
                    ),
                ),
            ),
        ),
        input_quality=input_quality,
        debt_refs=debt_refs,
    )


def _runtime_case(tmp_path: Path, source_id: str = "api"):
    from harness.re_v2.protocol_27.context import build_synthesis_context
    from harness.re_v2.protocol_27.runtime import Protocol27DeterministicRuntime

    inputs = _validated_inputs(tmp_path)
    item = _source_item(inputs, source_id)
    context = build_synthesis_context(inputs, item)
    authority_id = context.dependency_artifacts[0].artifact_hash
    candidate = _candidate(
        source_id=source_id,
        input_quality=context.input_quality,
        debt_refs=context.debt_refs,
        authority_id=authority_id,
    )
    runtime = Protocol27DeterministicRuntime(ObjectStore(inputs.paths.objects))
    return inputs, item, context, candidate, runtime


@pytest.mark.unit
def test_runtime_certifies_and_stores_canonical_candidate(tmp_path: Path) -> None:
    _inputs, item, context, candidate, runtime = _runtime_case(tmp_path)
    payload = canonical_json_bytes(candidate.to_json_dict())

    result = runtime.certify_candidate(item, context, payload)

    assert result.artifact_bytes == payload
    assert result.acceptance.artifact_key == item.output_key
    assert result.acceptance.input_quality == context.input_quality
    assert runtime.object_store.read_blob(result.acceptance.artifact_hash) == payload
    assert result.certification.identity == result.acceptance.certification_id
    assert type(result.assessment).from_json_dict(
        json.loads(canonical_json_bytes(result.assessment.to_json_dict()))
    ) == result.assessment
    assert type(result.certification).from_json_dict(
        json.loads(canonical_json_bytes(result.certification.to_json_dict()))
    ) == result.certification
    assert type(result.acceptance).from_json_dict(
        json.loads(canonical_json_bytes(result.acceptance.to_json_dict()))
    ) == result.acceptance


@pytest.mark.unit
def test_partial_candidate_cannot_claim_full_quality(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.runtime import Protocol27RuntimeError

    _inputs, item, context, candidate, runtime = _runtime_case(tmp_path, "web")
    assert context.input_quality == "partial"
    payload = canonical_json_bytes(
        replace(candidate, input_quality="complete").to_json_dict()
    )

    with pytest.raises(Protocol27RuntimeError, match="full quality"):
        runtime.certify_candidate(item, context, payload)


@pytest.mark.unit
def test_runtime_rejects_unknown_citation_and_invented_debt(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.runtime import Protocol27RuntimeError

    _inputs, item, context, candidate, runtime = _runtime_case(tmp_path)
    unknown = replace(
        candidate,
        claims=(
            replace(
                candidate.claims[0],
                evidence=(
                    replace(candidate.claims[0].evidence[0], authority_id=digest("unknown")),
                ),
            ),
        ),
    )
    with pytest.raises(Protocol27RuntimeError, match="citation"):
        runtime.certify_candidate(item, context, canonical_json_bytes(unknown.to_json_dict()))

    with pytest.raises(Protocol27RuntimeError, match="debt"):
        runtime.certify_candidate(
            item,
            context,
            canonical_json_bytes(
                replace(candidate, debt_refs=(digest("invented-debt"),)).to_json_dict()
            ),
        )


@pytest.mark.unit
def test_runtime_rejects_wrong_scope_kind_sections_and_non_strict_json(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.runtime import Protocol27RuntimeError

    _inputs, item, context, candidate, runtime = _runtime_case(tmp_path)
    wrong_scope = replace(
        candidate,
        scope=SynthesisScopeV1(1, "source", "web", None, ("web",)),
    )
    wrong_kind = replace(candidate, artifact_kind="source-architecture")
    missing_section = replace(candidate, sections=candidate.sections[:-1])

    for value, reason in (
        (wrong_scope, "scope"),
        (wrong_kind, "kind"),
        (missing_section, "sections"),
    ):
        with pytest.raises(Protocol27RuntimeError, match=reason):
            runtime.certify_candidate(
                item,
                context,
                canonical_json_bytes(value.to_json_dict()),
            )
    with pytest.raises(Protocol27RuntimeError, match="strict UTF-8 JSON"):
        runtime.certify_candidate(item, context, b'\xff')
    with pytest.raises(Protocol27RuntimeError, match="duplicate JSON key"):
        runtime.certify_candidate(item, context, b'{"schema_version":1,"schema_version":1}')


@pytest.mark.unit
def test_runtime_rejects_citation_to_another_context_source(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.runtime import Protocol27RuntimeError

    _inputs, item, context, candidate, runtime = _runtime_case(tmp_path)
    bad = replace(
        candidate,
        claims=(
            replace(
                candidate.claims[0],
                evidence=(
                    replace(candidate.claims[0].evidence[0], source_id="web"),
                ),
            ),
        ),
    )

    with pytest.raises(Protocol27RuntimeError, match="source"):
        runtime.certify_candidate(item, context, canonical_json_bytes(bad.to_json_dict()))
