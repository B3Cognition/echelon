from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Mapping

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.model import (
    RE_V2_ENGINE,
    RE_V2_PROTOCOL,
    ArtifactKey,
    ArtifactReceipt,
    BudgetPolicy,
    CertificationKey,
    CertificationReceipt,
    ExecutionObservation,
    ReV2ModelError,
    RunManifest,
    WorkItem,
    WorkTemplate,
)


def digest(character: str) -> str:
    return "sha256:" + character * 64


def valid_budget_policy() -> BudgetPolicy:
    return BudgetPolicy(
        token_limit=10_000,
        active_ms_limit=60_000,
        provider_attempt_limit=2,
        artifact_generation_attempt_limit=3,
        semantic_repair_round_limit=1,
        result_contract_retry_limit=1,
    )


def valid_run_manifest_dict() -> dict[str, object]:
    return {
        "schema_version": 1,
        "engine": RE_V2_ENGINE,
        "engine_protocol_version": RE_V2_PROTOCOL,
        "run_id": "re-demo",
        "created_at": "2026-08-14T12:00:00Z",
        "source_snapshot_id": digest("1"),
        "source_snapshot_kind": "git-worktree",
        "partition_manifest_id": digest("2"),
        "requested_goals": ["api", "inventory"],
        "initial_budget_policy": valid_budget_policy().to_json_dict(),
        "provider_contract": {"provider": "fake", "settings": {"tier": 1}},
        "artifact_policy_versions": {"L0": "inventory-v1"},
        "parent_run_id": None,
    }


def valid_artifact_key() -> ArtifactKey:
    return ArtifactKey(
        source_snapshot_id=digest("1"),
        partition_manifest_id=digest("2"),
        artifact_kind="source-inventory",
        layer="L0",
        producer_protocol_version="inventory-v1",
        layer_policy_hash=digest("3"),
        dependency_hashes=(),
    )


def valid_work_template() -> WorkTemplate:
    return WorkTemplate(
        goal_id="inventory",
        artifact_kind="source-inventory",
        layer="L0",
        producer_id="inventory",
        producer_protocol_version="inventory-v1",
        layer_policy_hash=digest("3"),
        required_template_ids=(),
        verifier_id="inventory-verifier",
        verifier_version="v1",
        result_contract_id="inventory-result-v1",
        max_provider_attempts=2,
        max_generation_attempts=3,
        max_semantic_rounds=1,
        max_result_contract_retries=1,
    )


def test_canonical_json_and_digest_are_stable() -> None:
    value = {"z": "ž", "a": [2, 1]}
    assert canonical_json_bytes(value) == b'{"a":[2,1],"z":"\xc5\xbe"}\n'
    assert content_digest(value) == content_digest(canonical_json_bytes(value))


def test_artifact_identity_ignores_operational_budget() -> None:
    key = valid_artifact_key()
    assert key.identity == ArtifactKey.from_json_dict(key.to_json_dict()).identity
    assert "budget" not in key.to_json_dict()


def test_run_manifest_rejects_unknown_engine() -> None:
    raw = valid_run_manifest_dict()
    raw["engine"] = "re-v3"
    with pytest.raises(ReV2ModelError, match="unsupported engine"):
        RunManifest.from_json_dict(raw)


def test_run_manifest_rejects_noninteger_schema_version() -> None:
    raw = valid_run_manifest_dict()
    raw["schema_version"] = True
    with pytest.raises(ReV2ModelError, match="schema version"):
        RunManifest.from_json_dict(raw)


def test_models_round_trip_and_are_immutable() -> None:
    artifact_key = valid_artifact_key()
    template = valid_work_template()
    work_item = WorkItem(
        template_id=template.template_id,
        goal_id=template.goal_id,
        output_key=artifact_key,
        required_artifact_hashes=(),
        producer_id=template.producer_id,
        producer_protocol_version=template.producer_protocol_version,
        verifier_id=template.verifier_id,
        verifier_version=template.verifier_version,
        result_contract_id=template.result_contract_id,
        max_provider_attempts=template.max_provider_attempts,
        max_generation_attempts=template.max_generation_attempts,
        max_semantic_rounds=template.max_semantic_rounds,
        max_result_contract_retries=template.max_result_contract_retries,
    )
    certification_key = CertificationKey(
        artifact_hash=digest("4"), verifier_id="inventory-verifier", verifier_version="v1",
        source_snapshot_id=digest("1"), audit_epoch_id=None,
    )
    observation = ExecutionObservation(
        started_at="2026-08-14T12:00:00Z", ended_at="2026-08-14T12:00:01Z",
        duration_ms=1000, exit_code=0, timed_out=False, output_truncated=False,
        result_contract_valid=True, token_usage=12, provider_name="fake", model_name="fake-v1",
        stderr_digest=None,
    )
    certification_receipt = CertificationReceipt(
        certification_key=certification_key, candidate_id="candidate-1", work_item_id=work_item.work_item_id,
        verdict="accepted", normalized_diagnostics=(), evidence_references=(), scope_verified=True,
        certified_at="2026-08-14T12:00:02Z",
    )
    artifact_receipt = ArtifactReceipt(
        artifact_key=artifact_key, artifact_hash=digest("4"), certification_id=certification_receipt.identity,
        candidate_id="candidate-1", work_item_id=work_item.work_item_id, accepted_at="2026-08-14T12:00:03Z",
    )
    manifest = RunManifest.from_json_dict(valid_run_manifest_dict())

    for model_type, value in (
        (ArtifactKey, artifact_key), (WorkTemplate, template), (WorkItem, work_item),
        (CertificationKey, certification_key), (ExecutionObservation, observation),
        (CertificationReceipt, certification_receipt), (ArtifactReceipt, artifact_receipt),
        (RunManifest, manifest),
    ):
        assert model_type.from_json_dict(value.to_json_dict()).to_json_dict() == value.to_json_dict()
    with pytest.raises(FrozenInstanceError):
        artifact_key.layer = "L1"  # type: ignore[misc]


def test_model_validation_rejects_noncanonical_or_invalid_values() -> None:
    with pytest.raises(ReV2ModelError, match="sorted"):
        ArtifactKey(
            source_snapshot_id=digest("1"), partition_manifest_id=digest("2"), artifact_kind="inventory",
            layer="L0", producer_protocol_version="v1", layer_policy_hash=digest("3"),
            dependency_hashes=(digest("5"), digest("4")),
        )
    with pytest.raises(ReV2ModelError, match="required_artifact_hashes"):
        WorkItem(
            template_id="template", goal_id="inventory", output_key=valid_artifact_key(),
            required_artifact_hashes=(digest("4"),), producer_id="inventory", producer_protocol_version="v1",
            verifier_id="verifier", verifier_version="v1", result_contract_id="result-v1",
            max_provider_attempts=1, max_generation_attempts=1, max_semantic_rounds=0,
            max_result_contract_retries=0,
        )
    raw = valid_run_manifest_dict()
    raw["unexpected"] = True
    with pytest.raises(ReV2ModelError, match="unknown fields"):
        RunManifest.from_json_dict(raw)


def test_manifest_defensively_copies_provider_contract() -> None:
    raw = valid_run_manifest_dict()
    contract = raw["provider_contract"]
    assert isinstance(contract, dict)
    manifest = RunManifest.from_json_dict(raw)
    identity = manifest.run_manifest_id
    contract["settings"]["tier"] = 2
    assert manifest.run_manifest_id == identity


def test_manifest_provider_contract_is_immutable() -> None:
    manifest = RunManifest.from_json_dict(valid_run_manifest_dict())
    settings = manifest.provider_contract["settings"]
    assert isinstance(settings, Mapping)
    with pytest.raises(TypeError):
        settings["tier"] = 2
