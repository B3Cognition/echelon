from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.model import (
    ArtifactKeyV2,
    ArtifactScope,
    BudgetPolicyV2,
    CatalogReferenceV1,
    DeterministicInvocationInputV1,
    DeterministicInvocationV1,
    ExecutionCaptureCommitV1,
    ExecutionCaptureV1,
    ExecutionInputV1,
    PersistedCandidateV2,
    ProviderGenerationV1,
    ProviderMessageV1,
    ProviderRequestEnvelopeV1,
    ProviderResponseFormatV1,
    RunManifestV2,
    WorkItemV2,
    WorkTemplateV2,
    instantiate_work_item_v2,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    load_canonical_object,
)
from tests.re_v2_protocol_22_fixtures import (
    artifact_key_v2,
    artifact_scope_v2,
    budget_policy_v2,
    digest,
    manifest_v2,
    manifest_v2_dict,
    work_item_v2,
    work_template_v2,
)


def provider_envelope_v1() -> ProviderRequestEnvelopeV1:
    return ProviderRequestEnvelopeV1(
        schema_version=1,
        dispatch_id="dispatch-1",
        work_item_id=digest("provider-work-item"),
        executor_contract_hash=digest("provider-executor"),
        target_artifact_kind="domain-baseline",
        provider_id="bounded-api",
        model_id="gpt-example",
        model_revision="gpt-example-2026-08-01",
        reasoning_effort=None,
        messages=(
            ProviderMessageV1(role="system", content_utf8="Pinned agent contract.\n"),
            ProviderMessageV1(role="user", content_utf8='{"context":"bounded"}\n'),
        ),
        response_format=ProviderResponseFormatV1(
            kind="json_schema",
            schema_name="echelon_compact_baseline_v1",
            strict=True,
            schema_hash=digest("domain-response-schema"),
        ),
        generation=ProviderGenerationV1(
            temperature_micros=0,
            top_p_micros=1_000_000,
            seed=None,
            max_completion_tokens=4096,
        ),
        tools=(),
        tool_choice="none",
        stream=False,
    )


def deterministic_invocation_v1() -> DeterministicInvocationV1:
    return DeterministicInvocationV1(
        schema_version=1,
        producer_family="inventory",
        output_key=artifact_key_v2(),
        artifact_policy_hash=digest("inventory-policy"),
        inputs=(
            DeterministicInvocationInputV1(
                role="workspace_partition",
                object_hash=digest("workspace-partition-catalog"),
            ),
        ),
    )


def provider_execution_input_v1() -> ExecutionInputV1:
    envelope = provider_envelope_v1()
    return ExecutionInputV1(
        schema_version=1,
        dispatch_id=envelope.dispatch_id,
        work_item_id=envelope.work_item_id,
        attempt_kind="initial_generation",
        executor_contract_hash=envelope.executor_contract_hash,
        agent_contract_hash=digest("agent-contract"),
        context_bundle_hash=digest("context-bundle"),
        provider_request_envelope_hash=envelope.identity,
        deterministic_invocation=None,
    )


def provider_execution_capture_v1() -> ExecutionCaptureV1:
    stdout = b"echelon_result:\n  outcome: candidate_ready\n"
    stdout_hash = content_digest(stdout)
    execution_input = provider_execution_input_v1()
    return ExecutionCaptureV1(
        schema_version=1,
        dispatch_id=execution_input.dispatch_id,
        work_item_id=execution_input.work_item_id,
        execution_input_hash=execution_input.identity,
        executor_contract_hash=execution_input.executor_contract_hash,
        execution_mode="api",
        result_kind="provider_candidate",
        candidate_inventory_hash=digest("candidate-inventory"),
        deterministic_artifact_hash=None,
        stdout_digest=stdout_hash,
        stdout_blob_hash=stdout_hash,
        stdout_byte_count=len(stdout),
        stdout_retained_byte_count=len(stdout),
        stdout_capture="complete",
        stderr_digest=None,
        provider_usage_blob_hash=digest("provider-usage"),
        started_at="2026-08-22T09:00:00Z",
        ended_at="2026-08-22T09:00:01Z",
        duration_ms=1000,
        exit_code=0,
        timed_out=False,
        output_truncated=False,
        provider_name="bounded-api",
        resolved_model_revision="gpt-example-2026-08-01",
    )


def test_manifest_v2_rejects_schema_1_provider_maps() -> None:
    raw = manifest_v2_dict()
    raw["provider_contract"] = {"provider": "fake"}

    with pytest.raises(Protocol22SchemaError, match="unknown fields"):
        RunManifestV2.from_json_dict(raw)


@pytest.mark.parametrize(
    "relative_path",
    (
        "/absolute.json",
        "../escape.json",
        "nested/../x.json",
        "./x.json",
        "nested//x.json",
        "nested\\x.json",
        "",
    ),
)
def test_catalog_reference_rejects_unsafe_relative_path(relative_path: str) -> None:
    with pytest.raises(Protocol22SchemaError, match="relative_path"):
        CatalogReferenceV1(object_hash=digest("catalog"), relative_path=relative_path)


@pytest.mark.parametrize("goal", ("baseline", "inventory"))
def test_manifest_budget_must_match_selected_goal(goal: str) -> None:
    raw = manifest_v2_dict(goal=goal)
    raw["initial_budget_policy"] = budget_policy_v2(
        goal="inventory" if goal == "baseline" else "baseline"
    ).to_json_dict()

    with pytest.raises(Protocol22SchemaError, match="selected goal"):
        RunManifestV2.from_json_dict(raw)


def test_domain_artifact_requires_domain_key() -> None:
    key = artifact_key_v2(artifact_kind="source-inventory")

    with pytest.raises(Protocol22SchemaError, match="domain_key"):
        replace(key, artifact_kind="domain-baseline", layer="L1")


def test_source_artifact_forbids_domain_key() -> None:
    key = artifact_key_v2(domain=True, artifact_kind="domain-inventory")

    with pytest.raises(Protocol22SchemaError, match="domain_key"):
        replace(key, artifact_kind="source-overview", layer="L1")


def test_identity_schema_version_is_literal_two() -> None:
    with pytest.raises(Protocol22SchemaError, match="identity_schema_version"):
        replace(artifact_key_v2(), identity_schema_version=1)
    with pytest.raises(Protocol22SchemaError, match="identity_schema_version"):
        replace(work_template_v2(), identity_schema_version=1)


def test_boolean_cannot_masquerade_as_integer() -> None:
    raw = budget_policy_v2().to_json_dict()
    raw["provider_attempt_limit"] = True

    with pytest.raises(Protocol22SchemaError, match="provider_attempt_limit"):
        BudgetPolicyV2.from_json_dict(raw)


def test_work_template_requires_sorted_unique_dependency_templates() -> None:
    high = digest("z-template")
    low = digest("a-template")

    with pytest.raises(Protocol22SchemaError, match="sorted and unique"):
        replace(work_template_v2(), required_template_ids=(high, low))
    with pytest.raises(Protocol22SchemaError, match="sorted and unique"):
        replace(work_template_v2(), required_template_ids=(low, low))


def test_instantiate_work_item_copies_every_template_contract_field() -> None:
    template = work_template_v2()
    output_key = artifact_key_v2()

    item = instantiate_work_item_v2(template, output_key, ())

    for field in WorkItemV2.COPIED_TEMPLATE_FIELDS:
        assert getattr(item, field) == getattr(template, field)
    assert item.template_id == template.template_id
    assert item.output_key == output_key


def test_instantiate_work_item_rejects_template_key_mismatch() -> None:
    template = work_template_v2()
    mismatched = replace(artifact_key_v2(), layer_policy_hash=digest("other-policy"))

    with pytest.raises(Protocol22SchemaError, match="layer_policy_hash"):
        instantiate_work_item_v2(template, mismatched, ())


def test_work_item_requires_dependency_hashes_to_match_output_key() -> None:
    item = work_item_v2(dependency_hashes=(digest("dependency"),))
    raw = item.to_json_dict()
    raw["required_artifact_hashes"] = []

    with pytest.raises(Protocol22SchemaError, match="dependency_hashes"):
        WorkItemV2.from_json_dict(raw)


def test_provider_envelope_requires_literal_message_order() -> None:
    envelope = provider_envelope_v1()

    with pytest.raises(Protocol22SchemaError, match="system.*user"):
        replace(envelope, messages=tuple(reversed(envelope.messages)))


def test_provider_envelope_rejects_implicit_generation_controls() -> None:
    raw = provider_envelope_v1().to_json_dict()
    generation = raw["generation"]
    assert isinstance(generation, dict)
    generation.pop("top_p_micros")

    with pytest.raises(Protocol22SchemaError, match="missing fields"):
        ProviderRequestEnvelopeV1.from_json_dict(raw)


def test_execution_input_requires_exactly_one_execution_branch() -> None:
    provider_input = provider_execution_input_v1()

    with pytest.raises(Protocol22SchemaError, match="exactly one"):
        replace(provider_input, deterministic_invocation=deterministic_invocation_v1())

    with pytest.raises(Protocol22SchemaError, match="exactly one"):
        replace(
            provider_input,
            agent_contract_hash=None,
            context_bundle_hash=None,
            provider_request_envelope_hash=None,
        )


def test_deterministic_invocation_inputs_are_sorted_and_unique_by_role() -> None:
    first = DeterministicInvocationInputV1("z-role", digest("z"))
    second = DeterministicInvocationInputV1("a-role", digest("a"))

    with pytest.raises(Protocol22SchemaError, match="sorted and unique"):
        replace(deterministic_invocation_v1(), inputs=(first, second))
    with pytest.raises(Protocol22SchemaError, match="sorted and unique"):
        replace(deterministic_invocation_v1(), inputs=(second, second))


def test_provider_capture_enforces_mode_and_result_branch() -> None:
    capture = provider_execution_capture_v1()

    with pytest.raises(Protocol22SchemaError, match="execution"):
        replace(capture, execution_mode="in_process")
    with pytest.raises(Protocol22SchemaError, match="candidate_inventory_hash"):
        replace(capture, candidate_inventory_hash=None)


def test_complete_stdout_requires_complete_blob_authority() -> None:
    capture = provider_execution_capture_v1()

    with pytest.raises(Protocol22SchemaError, match="stdout"):
        replace(capture, stdout_retained_byte_count=capture.stdout_byte_count - 1)
    with pytest.raises(Protocol22SchemaError, match="stdout"):
        replace(capture, stdout_blob_hash=digest("other-stdout"))


def test_canonical_loader_rejects_duplicate_keys() -> None:
    with pytest.raises(Protocol22SchemaError, match="duplicate key"):
        load_canonical_object(
            b'{"schema_version":2,"schema_version":2}\n',
            RunManifestV2.from_json_dict,
        )


@pytest.mark.parametrize("payload", (b"[]\n", b"1\n", b"null\n"))
def test_canonical_object_loader_rejects_non_object_roots(payload: bytes) -> None:
    with pytest.raises(Protocol22SchemaError, match="object"):
        load_canonical_object(payload, lambda value: value)


@pytest.mark.parametrize(
    ("payload", "message"),
    (
        (b'{"value":NaN}\n', "non-finite"),
        (b'{"value":"\\ud800"}\n', "Unicode"),
        (b'{"value":"\xff"}\n', "UTF-8"),
        (b'{"b":2, "a":1}\n', "canonical"),
        (b'{"a":1}', "canonical"),
    ),
)
def test_canonical_loader_rejects_invalid_or_noncanonical_bytes(
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(Protocol22SchemaError, match=message):
        load_canonical_object(payload, lambda value: value)


def test_all_protocol_models_round_trip_with_stable_canonical_identity() -> None:
    key = artifact_key_v2()
    template = work_template_v2()
    item = work_item_v2()
    envelope = provider_envelope_v1()
    invocation = deterministic_invocation_v1()
    execution_input = provider_execution_input_v1()
    capture = provider_execution_capture_v1()
    capture_commit = ExecutionCaptureCommitV1(
        schema_version=1,
        dispatch_id=capture.dispatch_id,
        work_item_id=capture.work_item_id,
        execution_input_hash=capture.execution_input_hash,
        execution_capture_hash=capture.identity,
    )
    candidate = PersistedCandidateV2(
        schema_version=2,
        dispatch_id=capture.dispatch_id,
        work_item_id=capture.work_item_id,
        execution_capture_hash=capture.identity,
        candidate_inventory_hash=capture.candidate_inventory_hash or "",
    )
    values = (
        CatalogReferenceV1(digest("catalog"), "nested/catalog.json"),
        budget_policy_v2(),
        artifact_scope_v2(),
        key,
        template,
        item,
        envelope,
        invocation,
        execution_input,
        capture,
        capture_commit,
        candidate,
        manifest_v2(),
    )

    for value in values:
        payload = canonical_json_bytes(value.to_json_dict())
        restored = load_canonical_object(payload, type(value).from_json_dict)
        assert canonical_json_bytes(restored.to_json_dict()) == payload
        if hasattr(value, "identity"):
            assert restored.identity == value.identity


def test_legal_identity_mutation_changes_identity() -> None:
    first = provider_envelope_v1()
    second = replace(first, dispatch_id="dispatch-2")

    assert first.identity != second.identity


def test_manifest_catalog_references_must_not_alias() -> None:
    raw = manifest_v2_dict()
    raw["executor_contract_catalog"] = raw["artifact_policy_catalog"]

    with pytest.raises(Protocol22SchemaError, match="distinct"):
        RunManifestV2.from_json_dict(raw)
