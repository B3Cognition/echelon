from __future__ import annotations

import unicodedata

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_25.lifecycle import (
    guidance_id_for,
    normalize_guidance_answer,
    semantic_request_id_v2,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import manifest_v4


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
