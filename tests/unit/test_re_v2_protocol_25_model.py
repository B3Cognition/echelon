from __future__ import annotations

import importlib
import json
from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.model import (
    ArtifactKeyV2,
    ArtifactScope,
    BudgetPolicyV2,
    WorkTemplateV2,
)
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_24.model import ParentLineageV1, SelectionScopeV1
from tests.re_v2_protocol_22_fixtures import digest


def test_protocol_25_registers_schema_4_constants() -> None:
    try:
        protocol = importlib.import_module("harness.re_v2.protocol_25")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 package is not registered")

    assert protocol.PROTOCOL_VERSION == "2.5"
    assert protocol.RUN_MANIFEST_SCHEMA_VERSION == 4


def test_shared_work_values_accept_registered_l3_authority() -> None:
    scope = ArtifactScope("api", digest("orders-domain"), digest("orders-content"))
    key = ArtifactKeyV2(
        identity_schema_version=2,
        scope=scope,
        partition_id=digest("partition"),
        artifact_kind="semantic-resolution-overlay",
        layer="L3",
        producer_protocol_version="2.5",
        layer_policy_hash=digest("l3-policy"),
        dependency_hashes=(digest("audit-epoch"),),
    )
    template = WorkTemplateV2(
        identity_schema_version=2,
        goal_id="semantic-audit-closure",
        scope=scope,
        artifact_kind=key.artifact_kind,
        layer=key.layer,
        producer_id="semantic-resolver-v1",
        producer_family="semantic-resolution",
        producer_protocol_version="2.5",
        layer_policy_hash=key.layer_policy_hash,
        required_template_ids=(),
        executor_contract_hash=digest("executor"),
        verifier_id="semantic-verifier-v1",
        verifier_version="1",
        verifier_implementation_digest=digest("verifier"),
        result_contract_id="semantic-resolution-v1",
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_semantic_rounds=3,
        max_result_contract_retries=1,
        max_shared_retries=1,
        max_artifact_contract_retries=1,
    )

    assert key.layer == "L3"
    assert template.goal_id == "semantic-audit-closure"


def test_runwide_budget_uses_existing_fixed_provider_attempt_tuple() -> None:
    policy = BudgetPolicyV2.for_goal(
        "semantic-audit-closure",
        token_limit=1_000_000,
        active_ms_limit=3_600_000,
    )

    assert policy.matches_goal("semantic-audit-closure")
    assert tuple(getattr(policy, field) for field in policy.ATTEMPT_FIELDS) == (
        2,
        2,
        0,
        1,
        1,
        1,
    )


def _protocol_25_model():  # type: ignore[no-untyped-def]
    try:
        return importlib.import_module("harness.re_v2.protocol_25.model")
    except ModuleNotFoundError:
        pytest.fail("protocol 2.5 model is not registered")


def _reference(seed: str, path: str):  # type: ignore[no-untyped-def]
    from harness.re_v2.protocol_22.model import CatalogReferenceV1

    return CatalogReferenceV1(digest(seed), path)


def _semantic_policy():  # type: ignore[no-untyped-def]
    model = _protocol_25_model()
    return model.SemanticClosurePolicyV1(
        schema_version=1,
        token_limit=500_000,
        active_ms_limit=1_800_000,
        max_rounds_per_target=3,
        consecutive_no_reduction_limit=2,
        provider_attempt_limit=2,
        contract_retry_limit=1,
        unknown_usage_policy="shared-conservative-reservation-v1",
    )


def _manifest_v4(*, run_mode: str = "new-audit-epoch"):  # type: ignore[no-untyped-def]
    model = _protocol_25_model()
    successor = run_mode != "new-audit-epoch"
    return model.RunManifestV4(
        schema_version=4,
        engine="re-v2",
        engine_protocol_version="2.5",
        run_id="re-l3-child",
        created_at="2026-08-26T12:00:00Z",
        source_snapshot_id=digest("workspace-snapshot"),
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=digest("partition-manifest"),
        workspace_partition_catalog=_reference(
            "workspace-partition", "workspace-partition.json"
        ),
        artifact_policy_catalog=_reference(
            "artifact-policy", "artifact-policy.json"
        ),
        executor_contract_catalog=_reference(
            "executor-contract", "executor-contract.json"
        ),
        audit_policy_catalog=_reference("audit-policy", "audit-policy.json"),
        parent_authority_bundle=_reference(
            "parent-authority-v2", "parent-authority-v2.json"
        ),
        parent_lineage=ParentLineageV1(
            schema_version=1,
            direct_parent_run_id="re-parent",
            direct_parent_manifest_hash=digest("parent-manifest"),
            direct_parent_terminal_event_hash=digest("parent-terminal"),
            lineage_root_run_id="re-root",
            lineage_root_manifest_hash=digest("root-manifest"),
        ),
        requested_goals=("semantic-audit-closure",),
        target_layer="L3",
        selection=SelectionScopeV1(
            schema_version=1,
            all_sources=False,
            source_ids=("api",),
            domain_keys=(digest("orders-domain"),),
        ),
        run_mode=run_mode,
        frozen_audit_epoch=(
            _reference("audit-epoch", "audit-epoch.json")
            if run_mode == "closure-successor"
            else None
        ),
        human_guidance=(
            _reference("human-guidance", "human-guidance.json")
            if successor
            else None
        ),
        semantic_request_id=digest("semantic-request-v2"),
        initial_budget_policy=BudgetPolicyV2.for_goal(
            "semantic-audit-closure", 1_000_000, 3_600_000
        ),
        semantic_closure_policy=_semantic_policy(),
    )


def test_semantic_closure_policy_round_trips_with_fixed_limits() -> None:
    model = _protocol_25_model()
    policy = _semantic_policy()
    payload = canonical_json_bytes(policy.to_json_dict())

    assert load_canonical_object(
        payload, model.SemanticClosurePolicyV1.from_json_dict
    ) == policy
    for field in (
        "max_rounds_per_target",
        "consecutive_no_reduction_limit",
        "provider_attempt_limit",
        "contract_retry_limit",
    ):
        with pytest.raises(model.Protocol25SchemaError, match=field):
            replace(policy, **{field: getattr(policy, field) + 1})


@pytest.mark.parametrize(
    "run_mode",
    ("new-audit-epoch", "audit-successor", "closure-successor"),
)
def test_schema_4_manifest_round_trips_canonically(run_mode: str) -> None:
    model = _protocol_25_model()
    manifest = _manifest_v4(run_mode=run_mode)
    payload = canonical_json_bytes(manifest.to_json_dict())

    assert load_canonical_object(payload, model.RunManifestV4.from_json_dict) == manifest
    assert manifest.parent_run_id == "re-parent"
    assert manifest.run_manifest_id == manifest.identity


def test_schema_4_manifest_rejects_mode_authority_mismatch() -> None:
    model = _protocol_25_model()

    with pytest.raises(model.Protocol25SchemaError, match="guidance"):
        replace(
            _manifest_v4(run_mode="new-audit-epoch"),
            human_guidance=_reference("guidance", "guidance.json"),
        )
    with pytest.raises(model.Protocol25SchemaError, match="frozen audit epoch"):
        replace(
            _manifest_v4(run_mode="closure-successor"),
            frozen_audit_epoch=None,
        )
    with pytest.raises(model.Protocol25SchemaError, match="frozen audit epoch"):
        replace(
            _manifest_v4(run_mode="audit-successor"),
            frozen_audit_epoch=_reference("epoch", "epoch.json"),
        )


def test_schema_4_manifest_rejects_unknown_fields() -> None:
    model = _protocol_25_model()
    raw = _manifest_v4().to_json_dict()
    raw["mutable_status"] = "complete"

    with pytest.raises(model.Protocol25SchemaError, match="fields"):
        model.RunManifestV4.from_json_dict(json.loads(canonical_json_bytes(raw)))


def test_schema_4_decoder_translates_nested_schema_errors() -> None:
    model = _protocol_25_model()
    raw = _manifest_v4().to_json_dict()
    raw["selection"]["unexpected"] = True

    with pytest.raises(model.Protocol25SchemaError, match="SelectionScopeV1"):
        model.RunManifestV4.from_json_dict(raw)
