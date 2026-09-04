from __future__ import annotations

from dataclasses import replace
import unicodedata

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_25.lifecycle import (
    _validate_monotonic_successor_policy_upgrade,
    guidance_id_for,
    normalize_guidance_answer,
    semantic_request_id_v2,
    semantic_request_id_v3,
)
from harness.re_v2.protocol_25.policies import build_semantic_v1_policy_catalog
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import manifest_v4


def _policy_with_source_context_ceiling(byte_ceiling: int):
    policy = build_semantic_v1_policy_catalog()
    return replace(
        policy,
        l3_entries=tuple(
            replace(item, max_context_bundle_bytes=byte_ceiling)
            if item.artifact_kind == "source-composition-assessment"
            else item
            for item in policy.l3_entries
        ),
    )


def _request(**changes: object) -> str:
    manifest = manifest_v4()
    values = {
        "lineage_root_run_id": manifest.parent_lineage.lineage_root_run_id,
        "lineage_root_manifest_hash": manifest.parent_lineage.lineage_root_manifest_hash,
        "direct_parent_run_id": manifest.parent_lineage.direct_parent_run_id,
        "direct_parent_manifest_hash": manifest.parent_lineage.direct_parent_manifest_hash,
        "direct_parent_terminal_event_hash": manifest.parent_lineage.direct_parent_terminal_event_hash,
        "source_snapshot_id": manifest.source_snapshot_id,
        "partition_manifest_id": manifest.partition_manifest_id,
        "selection": manifest.selection,
        "run_mode": "new-audit-epoch",
        "artifact_policy_hash": manifest.artifact_policy_catalog.object_hash,
        "executor_contract_hash": manifest.executor_contract_catalog.object_hash,
        "audit_policy_hash": manifest.audit_policy_catalog.object_hash,
        "accepted_audit_target_ids": (),
        "frozen_audit_epoch_id": None,
        "closure_root_hash": None,
        "guidance_hash": None,
    }
    values.update(changes)
    return semantic_request_id_v2(**values)  # type: ignore[arg-type]


def _request_v3(engine_protocol_version: str, **changes: object) -> str:
    manifest = manifest_v4()
    values = {
        "engine_protocol_version": engine_protocol_version,
        "lineage_root_run_id": manifest.parent_lineage.lineage_root_run_id,
        "lineage_root_manifest_hash": manifest.parent_lineage.lineage_root_manifest_hash,
        "direct_parent_run_id": manifest.parent_lineage.direct_parent_run_id,
        "direct_parent_manifest_hash": manifest.parent_lineage.direct_parent_manifest_hash,
        "direct_parent_terminal_event_hash": manifest.parent_lineage.direct_parent_terminal_event_hash,
        "source_snapshot_id": manifest.source_snapshot_id,
        "partition_manifest_id": manifest.partition_manifest_id,
        "selection": manifest.selection,
        "run_mode": "new-audit-epoch",
        "artifact_policy_hash": manifest.artifact_policy_catalog.object_hash,
        "executor_contract_hash": manifest.executor_contract_catalog.object_hash,
        "audit_policy_hash": manifest.audit_policy_catalog.object_hash,
        "accepted_audit_target_ids": (),
        "frozen_audit_epoch_id": None,
        "closure_root_hash": None,
        "guidance_hash": None,
    }
    values.update(changes)
    return semantic_request_id_v3(**values)  # type: ignore[arg-type]


@pytest.mark.unit
def test_semantic_request_identity_binds_authority_but_not_resource_ceiling() -> None:
    baseline = _request()

    assert baseline == _request()
    assert baseline != _request(source_snapshot_id=digest("changed-snapshot"))
    successor = _request(
        run_mode="audit-successor",
        guidance_hash=digest("guide"),
    )
    assert baseline != successor
    assert successor != _request(
        run_mode="audit-successor",
        guidance_hash=digest("guide"),
        accepted_audit_target_ids=(digest("accepted"),),
    )


@pytest.mark.unit
def test_successor_accepts_only_monotonic_capacity_policy_upgrade() -> None:
    legacy = _policy_with_source_context_ceiling(224 * 1024)
    current = build_semantic_v1_policy_catalog()

    _validate_monotonic_successor_policy_upgrade(legacy, current)

    reduced = _policy_with_source_context_ceiling(192 * 1024)
    with pytest.raises(ValueError, match="reduces a capacity ceiling"):
        _validate_monotonic_successor_policy_upgrade(legacy, reduced)

    changed_semantics = replace(
        current,
        l3_entries=tuple(
            replace(item, max_canonical_json_bytes=item.max_canonical_json_bytes + 1)
            if item.artifact_kind == "source-composition-assessment"
            else item
            for item in current.l3_entries
        ),
    )
    with pytest.raises(ValueError, match="changes semantic rules"):
        _validate_monotonic_successor_policy_upgrade(legacy, changed_semantics)


@pytest.mark.unit
def test_closure_successor_identity_allows_pre_root_execution_retry() -> None:
    request = _request(
        run_mode="closure-successor",
        guidance_hash=digest("guide"),
        frozen_audit_epoch_id=digest("epoch"),
        closure_root_hash=None,
    )

    assert request.startswith("sha256:")


@pytest.mark.unit
def test_semantic_request_v3_binds_semantic_layer_protocol() -> None:
    legacy = _request_v3("2.5")
    corrected = _request_v3("2.5.1")

    assert legacy != corrected
    assert corrected == _request_v3("2.5.1")

    with pytest.raises(ValueError, match="protocol"):
        _request_v3("2.5.2")


@pytest.mark.unit
def test_guidance_identity_binds_normalized_answer_and_blocked_parent() -> None:
    composed = "Cafe\u0301 timeout policy"
    normalized = unicodedata.normalize("NFC", composed)
    first = guidance_id_for(
        parent_manifest_hash=digest("parent-manifest"),
        parent_terminal_event_hash=digest("parent-terminal"),
        accepted_audit_candidate_hashes=(digest("candidate"),),
        unresolved_audit_target_ids=(digest("target"),),
        audit_epoch_id=None,
        closure_root_hash=None,
        unresolved_finding_ids=(),
        answer=composed,
    )
    second = guidance_id_for(
        parent_manifest_hash=digest("parent-manifest"),
        parent_terminal_event_hash=digest("parent-terminal"),
        accepted_audit_candidate_hashes=(digest("candidate"),),
        unresolved_audit_target_ids=(digest("target"),),
        audit_epoch_id=None,
        closure_root_hash=None,
        unresolved_finding_ids=(),
        answer=normalized,
    )

    assert first == second
    assert first == content_digest(
        {
            "accepted_audit_candidate_hashes": [digest("candidate")],
            "answer": normalized,
            "audit_epoch_id": None,
            "closure_root_hash": None,
            "parent_manifest_hash": digest("parent-manifest"),
            "parent_terminal_event_hash": digest("parent-terminal"),
            "schema_version": 1,
            "unresolved_audit_target_ids": [digest("target")],
            "unresolved_finding_ids": [],
        }
    )


@pytest.mark.unit
def test_guidance_answer_is_bounded_normalized_prose() -> None:
    assert normalize_guidance_answer("  retry timeout\r\n") == "retry timeout"
    with pytest.raises(ValueError, match="nonempty"):
        normalize_guidance_answer("   ")
    with pytest.raises(ValueError, match="8192"):
        normalize_guidance_answer("x" * 8193)
