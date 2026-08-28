from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.protocol_26 import reconstruction
from harness.re_v2.protocol_26.reconstruction import reconstruct_origin_checkpoints
from tests.re_v2_protocol_26_fixtures import CheckpointWorkspace


@pytest.fixture
def checkpoint_workspace(tmp_path: Path) -> CheckpointWorkspace:
    return CheckpointWorkspace.create(tmp_path / "workspace")


@pytest.mark.parametrize("origin_state", ["active", "paused", "blocked", "complete"])
def test_durably_accepted_artifact_is_eligible_before_terminalization(
    checkpoint_workspace: CheckpointWorkspace,
    origin_state: str,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain(origin_state)

    result = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, origin.run_dir
    )

    assert len(result.manifests) == 1
    assert result.manifests[0].artifact_key_id == origin.accepted_key_id
    assert result.rejected == ()


def test_certified_but_not_accepted_artifact_is_ineligible(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_certification_only()

    result = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, origin.run_dir
    )

    assert result.manifests == ()
    assert result.rejected == ()


def test_origin_append_during_read_is_bounded_and_skipped(
    checkpoint_workspace: CheckpointWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")

    def always_changes(*_args: object, **_kwargs: object):
        return None

    monkeypatch.setattr(reconstruction, "_stable_chain_pair", always_changes)
    result = reconstruct_origin_checkpoints(
        checkpoint_workspace.root,
        origin.run_dir,
        max_stability_attempts=2,
    )

    assert result.manifests == ()
    assert result.rejected[0].reason == "checkpoint_origin_unstable"


def test_reconstruction_rejects_symlinked_origin(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    linked = checkpoint_workspace.root / "runs" / "re-linked"
    linked.symlink_to(origin.run_dir, target_is_directory=True)

    result = reconstruct_origin_checkpoints(checkpoint_workspace.root, linked)

    assert result.manifests == ()
    assert result.rejected[0].reason == "checkpoint_manifest_invalid"


def test_corrupt_artifact_object_is_quarantined(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    artifact_hash = next(
        iter(
            reconstruct_origin_checkpoints(
                checkpoint_workspace.root, origin.run_dir
            ).manifests
        )
    ).artifact_hash
    suffix = artifact_hash.removeprefix("sha256:")
    object_path = origin.run_dir / "v2" / "objects" / "sha256" / suffix[:2] / suffix[2:]
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt")

    result = reconstruct_origin_checkpoints(checkpoint_workspace.root, origin.run_dir)

    assert result.manifests == ()
    assert result.rejected[0].reason == "checkpoint_object_hash_mismatch"


def test_checkpoint_prefix_hashes_ignore_later_valid_tail_events(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    first = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, origin.run_dir
    ).manifests[0]

    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_22.events import PROTOCOL_22_EVENTS
    from harness.re_v2.run_store import ReV2Paths

    events = EventStore(ReV2Paths.for_run(origin.run_dir), protocol=PROTOCOL_22_EVENTS)
    events.append(
        "operator_pause_requested",
        {"reason": "prefix test", "requested_by": "test"},
        occurred_at="2026-08-28T12:00:00Z",
    )
    events.append(
        "run_paused",
        {"reason": "prefix test", "reason_code": "operator_pause"},
        occurred_at="2026-08-28T12:00:00Z",
    )

    second = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, origin.run_dir
    ).manifests[0]

    assert second.origin_event_prefix_hash == first.origin_event_prefix_hash
    assert second.origin_ledger_prefix_hash == first.origin_ledger_prefix_hash
    assert second.identity == first.identity


def test_l3_checkpoint_preserves_exact_epoch_authority(
    checkpoint_workspace: CheckpointWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from harness.re_v2.canonical import canonical_json_bytes
    from harness.re_v2.protocol_25.controller import Protocol25Controller
    from tests.integration.test_re_v2_protocol_25_recovery import (
        _context,
        _semantic_audit_work_item,
        _semantic_result_work_item,
    )
    from tests.re_v2_protocol_22_fixtures import digest
    from tests.unit.test_re_v2_protocol_25_runtime import _certified_resolution

    context = _context(checkpoint_workspace.root / "runs")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    audit, epoch, _semantic_context, resolution = _certified_resolution()

    def accept(  # type: ignore[no-untyped-def]
        result, item, dispatch_id: str, semantic_start: dict[str, object] | None = None
    ) -> None:
        capture_hash = context.object_store.put_blob(
            f"capture:{dispatch_id}".encode("utf-8")
        )
        result = replace(
            result,
            candidate_assessment=replace(
                result.candidate_assessment,
                work_item_id=item.work_item_id,
                execution_capture_hash=capture_hash,
            ),
        )
        occurred_at = context.clock()
        context.event_store.append(
            "dispatch_leased",
            {"dispatch_id": dispatch_id, "work_item_id": item.work_item_id},
            occurred_at=occurred_at,
        )
        context.event_store.append(
            "dispatch_started",
            {
                "active_ms_reservation": 1_000,
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "billable_token_reservation": 100,
                "dispatch_id": dispatch_id,
                "execution_input_hash": digest(f"input:{dispatch_id}"),
                "executor_contract_hash": item.executor_contract_hash,
                "work_item_id": item.work_item_id,
            },
            occurred_at=occurred_at,
        )
        if semantic_start is not None:
            context.event_store.append(
                "semantic_resolution_started",
                semantic_start,
                occurred_at=occurred_at,
            )
        context.event_store.append(
            "dispatch_observed",
            {
                "active_usage_status": "trusted_exact",
                "dispatch_id": dispatch_id,
                "execution_capture_hash": capture_hash,
                "observed_active_ms": 100,
                "raw_result_contract_status": "valid",
                "reported_token_usage": 10,
                "token_usage_status": "trusted_exact",
                "work_item_id": item.work_item_id,
            },
            occurred_at=occurred_at,
        )
        context.event_store.append(
            "candidate_persisted",
            {
                "candidate_id": result.candidate_assessment.candidate_id,
                "candidate_inventory_hash": digest(f"inventory:{dispatch_id}"),
                "dispatch_id": dispatch_id,
                "execution_capture_hash": capture_hash,
                "work_item_id": item.work_item_id,
            },
            occurred_at=occurred_at,
        )
        Protocol25Controller(context)._record_semantic_result(
            item, result.candidate_assessment.candidate_id, result
        )

    audit_item = _semantic_audit_work_item(context, audit)
    accept(audit, audit_item, "audit-dispatch")
    context.object_store.put_blob(canonical_json_bytes(epoch.to_json_dict()))
    context.object_store.put_blob(b"l2-root")
    context.ledger.record_audit_epoch(epoch)
    context.event_store.append(
        "audit_epoch_frozen",
        {
            "audit_epoch_id": epoch.identity,
            "audit_target_ids": list(epoch.audit_target_ids),
        },
        occurred_at=context.clock(),
    )
    resolution_item = _semantic_result_work_item(context, resolution)
    context.object_store.put_blob(
        canonical_json_bytes(audit.artifact.audit_target.to_json_dict())
    )
    accept(
        resolution,
        resolution_item,
        "resolution-dispatch",
        {
            "audit_target_id": audit.artifact.audit_target_id,
            "dispatch_id": "resolution-dispatch",
            "semantic_round": 1,
            "source_cycle_id": "source-cycle-1",
            "source_id": audit.artifact.audit_target.scope.source_id,
            "work_item_id": resolution_item.work_item_id,
        },
    )

    monkeypatch.setattr(
        reconstruction,
        "_semantic_work_item",
        lambda _origin, acceptance: (
            resolution_item
            if acceptance.artifact_key.artifact_kind
            == "semantic-resolution-overlay"
            else audit_item
        ),
    )
    result = reconstruct_origin_checkpoints(
        checkpoint_workspace.root, context.paths.root.parent
    )
    checkpoint = next(
        item
        for item in result.manifests
        if item.artifact_key_id == resolution_item.output_key.identity
    )

    assert checkpoint.audit_epoch_id == epoch.identity
    assert epoch.identity in checkpoint.semantic_authority_ids
    assert epoch.identity in checkpoint.immutable_object_hashes
