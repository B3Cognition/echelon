from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    DeterministicAssessmentInputV2,
    certify_deterministic_artifact,
)
from harness.re_v2.protocol_22.executors import VerifierAuthorityV1
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1
from harness.re_v2.protocol_26.model import (
    CheckpointManifestV1,
    CheckpointRankV1,
    CheckpointSelectionBundleV1,
    CheckpointSelectionEntryV1,
    LayerExecutionContractV1,
    RunManifestV5,
)
from tests.re_v2_protocol_22_fixtures import digest, manifest_v2, work_item_v2
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.re_v2_protocol_25_fixtures import manifest_v4


@dataclass(frozen=True, slots=True)
class OriginCheckpointFixtureV1:
    run_dir: Path
    accepted_key_id: str | None


@dataclass(slots=True)
class CheckpointWorkspace:
    root: Path

    @classmethod
    def create(cls, root: Path) -> "CheckpointWorkspace":
        root.mkdir(parents=True)
        (root / "runs").mkdir()
        return cls(root)

    def origin_with_one_accepted_domain(
        self, origin_state: str
    ) -> OriginCheckpointFixtureV1:
        from harness.re_v2.protocol_22.controller import Protocol22Controller
        from tests.unit.test_re_v2_protocol_22_controller import _inventory_context

        context = _inventory_context(self.root / "runs")

        def stop_after_acceptance(stage: str) -> None:
            if stage.startswith("artifact_accepted:"):
                raise RuntimeError("checkpoint fixture stop")

        try:
            Protocol22Controller(context, stop_after_acceptance).run_until_stopped()
        except RuntimeError as exc:
            if str(exc) != "checkpoint fixture stop":
                raise
        accepted = context.ledger.replay().accepted_artifacts
        assert len(accepted) == 1
        if origin_state == "paused":
            context.event_store.append(
                "operator_pause_requested",
                {"reason": "checkpoint fixture", "requested_by": "test"},
                occurred_at=context.clock(),
            )
            context.event_store.append(
                "run_paused",
                {"reason": "checkpoint fixture", "reason_code": "operator_pause"},
                occurred_at=context.clock(),
            )
        elif origin_state == "complete":
            context.event_store.append(
                "run_completed",
                {"reason": "checkpoint fixture"},
                occurred_at=context.clock(),
            )
        elif origin_state == "blocked":
            (context.paths.root.parent / "state.json").write_text(
                json.dumps({"status": "blocked"}) + "\n",
                encoding="utf-8",
            )
        elif origin_state != "active":
            raise ValueError(f"unsupported fixture origin state: {origin_state}")
        return OriginCheckpointFixtureV1(
            run_dir=context.paths.root.parent,
            accepted_key_id=next(iter(accepted)),
        )

    def origin_with_certification_only(self) -> OriginCheckpointFixtureV1:
        from harness.re_v2.protocol_22.controller import Protocol22Controller
        from tests.unit.test_re_v2_protocol_22_controller import _inventory_context

        context = _inventory_context(self.root / "runs")

        def stop_after_certification(stage: str) -> None:
            if stage.startswith("certification_receipt:"):
                raise RuntimeError("checkpoint fixture stop")

        try:
            Protocol22Controller(context, stop_after_certification).run_until_stopped()
        except RuntimeError as exc:
            if str(exc) != "checkpoint fixture stop":
                raise
        return OriginCheckpointFixtureV1(
            run_dir=context.paths.root.parent,
            accepted_key_id=None,
        )


def layer_manifest(target_layer: str, *, run_id: str = "re-checkpoint-child"):
    if target_layer == "L1":
        return manifest_v2(run_id=run_id)
    if target_layer == "L2":
        return manifest_v3(run_id=run_id)
    if target_layer == "L3":
        return manifest_v4(run_id=run_id)
    raise ValueError(f"unsupported fixture layer: {target_layer}")


def layer_execution_contract_v1(
    target_layer: str = "L1",
    *,
    run_id: str = "re-checkpoint-child",
) -> LayerExecutionContractV1:
    return LayerExecutionContractV1.from_layer_manifest(
        layer_manifest(target_layer, run_id=run_id)
    )


def checkpoint_rank_v1() -> CheckpointRankV1:
    return CheckpointRankV1(
        schema_version=1,
        policy_id="deterministic-pass-v1",
        policy_hash=digest("deterministic-pass-rank-policy"),
        vector=(1,),
    )


def checkpoint_manifest_v1() -> CheckpointManifestV1:
    item = work_item_v2()
    artifact_hash = digest("accepted-artifact")
    certification = certify_deterministic_artifact(
        item,
        artifact_hash,
        DeterministicAssessmentInputV2(
            canonical_schema_valid=True,
            dependency_closure_valid=True,
            policy_conformance_valid=True,
            depth_debt=None,
            normalized_diagnostics=(),
        ),
        VerifierAuthorityV1(
            verifier_id=item.verifier_id,
            verifier_version=item.verifier_version,
            implementation_digest=item.verifier_implementation_digest,
        ),
    )
    acceptance = ArtifactAcceptanceReceiptV2(
        schema_version=2,
        artifact_key=item.output_key,
        artifact_hash=artifact_hash,
        certification_receipt_id=certification.identity,
    )
    authority = AdoptedArtifactAuthorityV1(
        schema_version=1,
        artifact_key_id=item.output_key.identity,
        artifact_hash=artifact_hash,
        dependency_hashes=item.output_key.dependency_hashes,
        certification_receipt_id=certification.identity,
        candidate_assessment_id=None,
        artifact_acceptance_receipt_id=acceptance.identity,
        source_run_id="re-origin",
        source_ledger_entry_hash=digest("acceptance-ledger-entry"),
    )
    rank = checkpoint_rank_v1()
    return CheckpointManifestV1(
        schema_version=1,
        origin_run_id="re-origin",
        origin_manifest_hash=digest("origin-manifest"),
        origin_engine_protocol_version="2.2",
        origin_run_schema_version=2,
        origin_acceptance_event_hash=digest("acceptance-event"),
        origin_event_prefix_hash=digest("acceptance-event-prefix"),
        origin_ledger_record_hash=digest("acceptance-ledger-entry"),
        origin_ledger_prefix_hash=digest("acceptance-ledger-prefix"),
        work_item=item,
        artifact_key_id=item.output_key.identity,
        artifact_hash=artifact_hash,
        certification_receipt=certification,
        candidate_assessment=None,
        artifact_acceptance_receipt=acceptance,
        adopted_artifact_authority=authority,
        accepted_artifact_dependencies=(),
        non_artifact_dependency_hashes=(),
        immutable_object_hashes=tuple(
            sorted(
                {
                    artifact_hash,
                    certification.identity,
                    acceptance.identity,
                    item.work_item_id,
                }
            )
        ),
        audit_epoch_id=None,
        semantic_authority_ids=(),
        rank=rank,
        rank_policy_hash=rank.policy_hash,
    )


def checkpoint_selection_bundle_v1() -> CheckpointSelectionBundleV1:
    checkpoint = checkpoint_manifest_v1()
    entry = CheckpointSelectionEntryV1(
        schema_version=1,
        expected_work_item_id=checkpoint.work_item.work_item_id,
        source_kind="workspace_checkpoint",
        checkpoint_manifest_id=checkpoint.identity,
        adopted_artifact_authority=checkpoint.adopted_artifact_authority,
        dependency_artifact_key_ids=(),
        copied_object_ids=checkpoint.immutable_object_hashes,
        copied_byte_count=4096,
        rank=checkpoint.rank,
        origin_run_id=checkpoint.origin_run_id,
        selection_reason="checkpoint_rank_winner",
    )
    return CheckpointSelectionBundleV1(
        schema_version=1,
        source_snapshot_id=checkpoint.work_item.output_key.scope.content_id,
        partition_manifest_id=digest("partition-manifest"),
        target_layer="L1",
        target_selection_id=digest("target-selection"),
        target_graph_id=digest("target-graph"),
        cache_generation_id=digest("cache-generation"),
        selected=(entry,),
        origin_manifest_hashes=(checkpoint.origin_manifest_hash,),
        origin_event_prefix_hashes=(checkpoint.origin_event_prefix_hash,),
        origin_ledger_prefix_hashes=(checkpoint.origin_ledger_prefix_hash,),
        copied_receipt_ids=tuple(
            sorted(
                {
                    checkpoint.certification_receipt.identity,
                    checkpoint.artifact_acceptance_receipt.identity,
                }
            )
        ),
        copied_work_item_ids=(checkpoint.work_item.work_item_id,),
        copied_object_ids=checkpoint.immutable_object_hashes,
        copied_byte_count=4096,
        alternatives=(),
        rejected=(),
        quarantined=(),
    )


def manifest_v5(
    target_layer: str = "L1",
    *,
    run_id: str = "re-checkpoint-child",
) -> RunManifestV5:
    inner = layer_manifest(target_layer, run_id=run_id)
    return RunManifestV5(
        schema_version=5,
        engine="re-v2",
        engine_protocol_version="2.6",
        run_id=run_id,
        created_at=inner.created_at,
        source_snapshot_id=inner.source_snapshot_id,
        source_snapshot_kind=inner.source_snapshot_kind,
        partition_manifest_id=inner.partition_manifest_id,
        target_layer=target_layer,
        layer_execution_contract=CatalogReferenceV1(
            digest(f"{target_layer}-layer-execution-contract"),
            "layer-execution-contract.json",
        ),
        checkpoint_selection=CatalogReferenceV1(
            digest(f"{target_layer}-checkpoint-selection"),
            "checkpoint-selection.json",
        ),
    )


__all__ = (
    "CheckpointWorkspace",
    "OriginCheckpointFixtureV1",
    "checkpoint_manifest_v1",
    "checkpoint_rank_v1",
    "checkpoint_selection_bundle_v1",
    "layer_execution_contract_v1",
    "layer_manifest",
    "manifest_v5",
)
