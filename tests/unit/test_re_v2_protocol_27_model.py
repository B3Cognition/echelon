from __future__ import annotations

from dataclasses import replace
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_27.model import (
    AcceptedSourceOutcomeV1,
    Protocol27SchemaError,
    PublicationDescriptorV1,
    RunManifestV6,
    SynthesisArtifactKeyV1,
    SynthesisRootV1,
    SynthesisScopeV1,
    SynthesisWorkItemV1,
    SynthesisWorkTemplateV1,
)
from tests.re_v2_protocol_27_fixtures import (
    accepted_source_outcome_v1,
    accepted_source_overview_projection_v1,
    manifest_v6,
    publication_descriptor_v1,
    synthesis_artifact_key_v1,
    synthesis_budget_policy_v1,
    synthesis_request_v1,
    synthesis_root_v1,
    synthesis_work_item_v1,
    synthesis_work_template_v1,
)


def test_manifest_v6_round_trips_exact_protocol() -> None:
    manifest = manifest_v6()
    payload = canonical_json_bytes(manifest.to_json_dict())

    assert RunManifestV6.from_json_dict(json.loads(payload)) == manifest
    assert manifest.run_manifest_id == content_digest(payload)


def test_partial_source_requires_exact_debt() -> None:
    raw = accepted_source_outcome_v1(outcome="partial").to_json_dict()
    raw["debt_manifest_hash"] = None

    with pytest.raises(Protocol27SchemaError, match="partial.*debt"):
        AcceptedSourceOutcomeV1.from_json_dict(raw)


def test_complete_source_forbids_debt() -> None:
    raw = accepted_source_outcome_v1().to_json_dict()
    raw["debt_manifest_hash"] = content_digest(b"unexpected")

    with pytest.raises(Protocol27SchemaError, match="complete.*debt"):
        AcceptedSourceOutcomeV1.from_json_dict(raw)


def test_manifest_requires_exact_partial_acceptance_coverage() -> None:
    manifest = manifest_v6()

    with pytest.raises(Protocol27SchemaError, match="partial acceptance"):
        replace(manifest, partial_acceptances=())


def test_budget_policy_rejects_a_third_provider_attempt() -> None:
    with pytest.raises(Protocol27SchemaError, match="fixed bounded attempt policy"):
        replace(synthesis_budget_policy_v1(), provider_attempt_limit=3)


def test_request_identity_is_stable_and_budget_sensitive() -> None:
    sources = (accepted_source_outcome_v1(),)
    request = synthesis_request_v1(sources, token_limit=400_000)

    assert synthesis_request_v1(sources, token_limit=400_000).request_id == request.request_id
    assert synthesis_request_v1(sources, token_limit=500_000).request_id != request.request_id


@pytest.mark.parametrize(
    ("raw", "message"),
    (
        ({"schema_version": 1, "kind": "source", "source_id": None, "workspace_domain_id": None, "participant_ids": []}, "source"),
        ({"schema_version": 1, "kind": "workspace-domain", "source_id": None, "workspace_domain_id": None, "participant_ids": ["api"]}, "workspace-domain"),
        ({"schema_version": 1, "kind": "workspace", "source_id": "api", "workspace_domain_id": None, "participant_ids": ["api"]}, "workspace"),
    ),
)
def test_scope_rejects_wrong_cardinality(raw: dict[str, object], message: str) -> None:
    with pytest.raises(Protocol27SchemaError, match=message):
        SynthesisScopeV1.from_json_dict(raw)


def test_overview_projection_requires_content_addressed_object() -> None:
    projection = accepted_source_overview_projection_v1()

    with pytest.raises(Protocol27SchemaError, match="content_hash.*object_hash"):
        replace(projection, object_hash=content_digest(b"different"))


def test_manifest_rejects_unknown_field() -> None:
    raw = manifest_v6().to_json_dict()
    raw["new_authority"] = "not-pinned"

    with pytest.raises(Protocol27SchemaError, match="unknown fields"):
        RunManifestV6.from_json_dict(raw)


@pytest.mark.parametrize(
    ("value", "decoder"),
    (
        (synthesis_artifact_key_v1(), SynthesisArtifactKeyV1.from_json_dict),
        (synthesis_work_template_v1(), SynthesisWorkTemplateV1.from_json_dict),
        (synthesis_work_item_v1(), SynthesisWorkItemV1.from_json_dict),
        (synthesis_root_v1(), SynthesisRootV1.from_json_dict),
        (publication_descriptor_v1(), PublicationDescriptorV1.from_json_dict),
    ),
)
def test_synthesis_authority_round_trips_canonically(value: object, decoder) -> None:
    encoded = value.to_json_dict()

    assert decoder(encoded) == value
    assert value.identity == content_digest(encoded)


def test_work_item_rejects_dependency_key_mismatch() -> None:
    item = synthesis_work_item_v1()

    with pytest.raises(Protocol27SchemaError, match="dependency keys"):
        replace(item, dependency_key_ids=())


def test_synthesis_root_quality_must_match_debt() -> None:
    root = synthesis_root_v1()

    with pytest.raises(Protocol27SchemaError, match="input_quality"):
        replace(root, input_quality="complete")


def test_publication_descriptor_quality_and_generation_are_exact() -> None:
    descriptor = publication_descriptor_v1()

    with pytest.raises(Protocol27SchemaError, match="input_quality"):
        replace(descriptor, input_quality="complete")
    with pytest.raises(Protocol27SchemaError, match="generation"):
        replace(descriptor, compatibility_generation=0)
