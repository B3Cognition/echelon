from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

import harness.re_v2.protocol_25 as protocol_25
import harness.re_v2.protocol_25.recovery as recovery_module
from harness.re_v2.events import EventStore
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.baseline import (
    ArtifactAcceptanceReceiptV2,
    CandidateAssessmentReceiptV1,
    CertificationKeyV2,
    CertificationReceiptV2,
    certify_deterministic_artifact,
)
from harness.re_v2.protocol_22.artifacts import DeterministicAssessmentInputV2
from harness.re_v2.protocol_22.execution import (
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    plan_next_v2,
)
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_25.adoption import (
    ParentAuthorityBundleV2,
    ParentSemanticAuthorityV1,
)
from harness.re_v2.protocol_25.artifacts import (
    AuditCandidateV1,
    SemanticCertificationReceiptV1,
    SemanticResolutionOverlayV1,
)
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
from harness.re_v2.protocol_25.inputs import ValidatedProtocol25Inputs
from harness.re_v2.protocol_25.ledger import Protocol25Ledger
from harness.re_v2.protocol_25.recovery import (
    Protocol25RunContext,
    publish_audit_epoch,
    reconstruct_accepted_audit_results,
    recover_protocol_25_run,
)
from harness.re_v2.protocol_25.controller import (
    Protocol25Controller,
    Protocol25ControllerActionV1,
    Protocol25ControllerStateV1,
    SemanticSourceCycleStateV1,
    SemanticTargetControllerStateV1,
    plan_next_protocol_25,
)
from harness.re_v2.protocol_22.model import WorkItemV2
from tests.re_v2_protocol_22_fixtures import digest
from harness.re_v2.protocol_25.runtime import Protocol25DeterministicRuntime
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_25_fixtures import lower_parent_authority_bundle_v1
from tests.re_v2_protocol_25_fixtures import audit_target_v1
from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs
from tests.unit.test_re_v2_protocol_25_graph import _fixture as _graph_fixture
from tests.unit.test_re_v2_protocol_25_runtime import (
    _certified_audit,
    _certified_closure,
    _certified_resolution,
    _context as _semantic_context,
    _runtime as _semantic_runtime,
)
from tests.unit.test_re_v2_protocol_22_artifacts import _zero_debt
from tests.unit.test_re_v2_protocol_22_ledger import _provider_authority, _verifier


class _SnapshotReader:
    def read_file(self, *_args: object) -> bytes:
        raise AssertionError("context-construction test must not read the snapshot")


def _context(tmp_path):  # type: ignore[no-untyped-def]
    graph, graph_inputs, _authority, _parent, _accepted = _graph_fixture()
    parent = ParentAuthorityBundleV2(
        schema_version=2,
        parent_layer="L2",
        parent_state="complete",
        source_snapshot_id=graph_inputs.workspace_partition.snapshot_id,
        selection_id=graph.manifest.selection.identity,
        lower_authority_bundle=lower_parent_authority_bundle_v1(),
        semantic_authority=ParentSemanticAuthorityV1.empty(),
    )
    semantic_inputs = ValidatedProtocol25Inputs(
        workspace_partition=graph_inputs.workspace_partition,
        artifact_policy=graph_inputs.artifact_policy,
        executor_contract=graph_inputs.executor_contract,
        audit_policy=graph_inputs.audit_policy,
        parent_authority_bundle=parent,
        immutable_objects=graph_inputs.immutable_objects,
        frozen_audit_epoch=None,
        human_guidance=None,
    )
    run_dir = tmp_path / graph.manifest.run_id
    paths = ReV2Paths.for_run(run_dir)
    paths.root.mkdir(parents=True)
    paths.objects.mkdir()
    paths.manifest.write_bytes(canonical_json_bytes(graph.manifest.to_json_dict()))
    objects = ObjectStore(paths.objects)
    return Protocol25RunContext(
        paths=paths,
        inputs=graph.inputs,
        graph=graph.prerequisite_graph,
        event_store=EventStore(paths, protocol=PROTOCOL_25_EVENTS),
        object_store=objects,
        ledger=Protocol25Ledger(paths, objects),
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=_registry_from_inputs(graph.inputs),
        dependencies_for=lambda *_args: (_ for _ in ()).throw(
            AssertionError("context-construction test must not resolve execution")
        ),
        executors=MappingProxyType({}),
        producers=MappingProxyType({}),
        verifiers=MappingProxyType({}),
        semantic_inputs=semantic_inputs,
        semantic_graph=graph,
        semantic_runtime=Protocol25DeterministicRuntime(
            verifier_authority_hash=graph_inputs.executor_contract.semantic_entries[
                0
            ].verifier.implementation_digest,
            snapshot_reader=_SnapshotReader(),
            artifact_policy=graph_inputs.artifact_policy,
        ),
    )


@pytest.mark.integration
def test_protocol_25_context_reuses_the_shared_run_context_contract() -> None:
    assert issubclass(Protocol25RunContext, Protocol22RunContext)
    assert callable(recover_protocol_25_run)
    assert protocol_25.Protocol25RunContext is Protocol25RunContext
    assert protocol_25.publish_audit_epoch is publish_audit_epoch
    assert protocol_25.recover_protocol_25_run is recover_protocol_25_run


@pytest.mark.integration
def test_protocol_25_context_accepts_registered_additive_event_protocol(
    tmp_path,
) -> None:
    context = _context(tmp_path)

    assert context.event_store.protocol is PROTOCOL_25_EVENTS


@pytest.mark.integration
def test_recovery_derives_prerequisite_state_without_semantic_projection(
    tmp_path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )

    result = recover_protocol_25_run(context)

    assert result.controller_state.prerequisites_complete is False
    assert result.controller_state.targets == ()
    assert result.events[-1].type == "run_created"
    assert result.ledger.semantic_records == {}


@pytest.mark.integration
def test_terminal_reconciliation_is_idempotent(tmp_path) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    context.event_store.append(
        "executor_failed",
        {
            "executor_contract_hash": digest("failed-executor"),
            "executor_failure_receipt_id": digest("failure-receipt"),
            "trigger_work_item_id": digest("failed-audit-work"),
        },
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    action = Protocol25ControllerActionV1(kind="terminal_blocked_incomplete")

    context.apply_controller_action(action)
    context.apply_controller_action(action)

    events = context.event_store.replay()
    assert [item.type for item in events].count("run_failed") == 1
    assert events[-1].payload["reason"] == "semantic closure is incomplete"


class _InjectedCrash(RuntimeError):
    pass


def _epoch_publication_fixture(tmp_path):  # type: ignore[no-untyped-def]
    context = _context(tmp_path)
    context = replace(context, semantic_runtime=_semantic_runtime())
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    result = _certified_audit(verdict="PASS")
    capture_hash = context.object_store.put_blob(b"captured provider execution\n")
    result = replace(
        result,
        candidate_assessment=replace(
            result.candidate_assessment,
            execution_capture_hash=capture_hash,
        ),
    )
    assert context.object_store.put_blob(result.artifact_bytes) == result.artifact.identity
    context.object_store.put_blob(result.normalized_authorial_payload_bytes)
    context.ledger.record_semantic_certification(result.certification)
    context.ledger.record_candidate_assessment(result.candidate_assessment)
    context.ledger.record_artifact_acceptance(result.acceptance)
    context.event_store.append(
        "audit_candidate_accepted",
        {
            "audit_candidate_authority_id": result.artifact.identity,
            "audit_target_id": result.artifact.audit_target_id,
        },
        occurred_at=context.clock(),
    )
    root_hash = context.object_store.put_blob(b"accepted L2 root\n")
    return context, result, (root_hash,)


def _semantic_audit_work_item(context, result):  # type: ignore[no-untyped-def]
    template = context.semantic_graph.audit_templates[0]
    return WorkItemV2(
        identity_schema_version=2,
        template_id=template.template_id,
        goal_id=template.goal_id,
        output_key=result.acceptance.artifact_key,
        required_artifact_hashes=result.acceptance.artifact_key.dependency_hashes,
        producer_id=template.producer_id,
        producer_family=template.producer_family,
        producer_protocol_version=template.producer_protocol_version,
        executor_contract_hash=template.executor_contract_hash,
        verifier_id=template.verifier_id,
        verifier_version=template.verifier_version,
        verifier_implementation_digest=template.verifier_implementation_digest,
        result_contract_id=template.result_contract_id,
        max_provider_attempts=template.max_provider_attempts,
        max_generation_attempts=template.max_generation_attempts,
        max_semantic_rounds=template.max_semantic_rounds,
        max_result_contract_retries=template.max_result_contract_retries,
        max_shared_retries=template.max_shared_retries,
        max_artifact_contract_retries=template.max_artifact_contract_retries,
    )


def _semantic_result_work_item(context, result):  # type: ignore[no-untyped-def]
    key = result.acceptance.artifact_key
    family = {
        "semantic-resolution-overlay": "semantic-resolution",
        "target-closure-assessment": "closure-recheck",
        "source-composition-assessment": "source-composition-guard",
    }[key.artifact_kind]
    executor = context.semantic_inputs.executor_contract.entry_for(family)
    return WorkItemV2(
        identity_schema_version=2,
        template_id=digest(f"template:{family}"),
        goal_id="semantic-audit-closure",
        output_key=key,
        required_artifact_hashes=key.dependency_hashes,
        producer_id=(
            "echelon.re-resolver"
            if family == "semantic-resolution"
            else "echelon.re-validator"
        ),
        producer_family=family,
        producer_protocol_version=executor.producer_protocol_version,
        executor_contract_hash=executor.executor_contract_hash,
        verifier_id=executor.verifier.verifier_id,
        verifier_version=executor.verifier.verifier_version,
        verifier_implementation_digest=executor.verifier.implementation_digest,
        result_contract_id=executor.result_contract_id,
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_semantic_rounds=0,
        max_result_contract_retries=1,
        max_shared_retries=1,
        max_artifact_contract_retries=1,
    )


class _AvailableBudget:
    @staticmethod
    def item_attempt_available(_item: object) -> bool:
        return True


def _accept_every_prerequisite(context: Protocol25RunContext):  # type: ignore[no-untyped-def]
    _fixture_item, compact_certification, _assessment, _acceptance = (
        _provider_authority(context.object_store)
    )
    compact_assessment = compact_certification.assessment
    for _round in range(16):
        decision = plan_next_v2(
            context.semantic_graph.prerequisite_graph,
            context.ledger.replay(),
            _AvailableBudget(),
        )
        if not decision.ready:
            break
        for item in decision.ready:
            payload = canonical_json_bytes({"work_item_id": item.work_item_id})
            artifact_hash = context.object_store.put_blob(payload)
            if item.output_key.artifact_kind in {"domain-baseline", "source-overview"}:
                certification = CertificationReceiptV2(
                    schema_version=2,
                    certification_key=CertificationKeyV2(
                        identity_schema_version=2,
                        artifact_hash=artifact_hash,
                        artifact_key=item.output_key,
                        verifier_id=item.verifier_id,
                        verifier_version=item.verifier_version,
                        verifier_implementation_digest=item.verifier_implementation_digest,
                        scoped_content_id=item.output_key.scope.content_id,
                        audit_epoch_id=None,
                    ),
                    verdict="accepted",
                    assessment=compact_assessment,
                )
            else:
                certification = certify_deterministic_artifact(
                    item,
                    artifact_hash,
                    DeterministicAssessmentInputV2(
                        canonical_schema_valid=True,
                        dependency_closure_valid=True,
                        policy_conformance_valid=True,
                        depth_debt=(
                            _zero_debt()
                            if item.output_key.artifact_kind
                            in {
                                "source-evidence-pack",
                                "domain-evidence-pack",
                                "domain-context-bundle",
                                "source-overview-context-bundle",
                            }
                            else None
                        ),
                        normalized_diagnostics=(),
                    ),
                    _verifier(item),
                )
            acceptance = ArtifactAcceptanceReceiptV2(
                schema_version=2,
                artifact_key=item.output_key,
                artifact_hash=artifact_hash,
                certification_receipt_id=certification.identity,
            )
            context.ledger.record_certification(certification, item)
            if item.output_key.artifact_kind in {"domain-baseline", "source-overview"}:
                capture_hash = context.object_store.put_blob(
                    f"prerequisite-capture:{item.work_item_id}\n".encode()
                )
                context.ledger.record_candidate_assessment(
                    CandidateAssessmentReceiptV1(
                        schema_version=1,
                        candidate_id=content_digest(
                            {"prerequisite-candidate": item.work_item_id}
                        ),
                        work_item_id=item.work_item_id,
                        execution_capture_hash=capture_hash,
                        normalized_authorial_payload_hash=artifact_hash,
                        artifact_hash=artifact_hash,
                        certification_receipt_id=certification.identity,
                        outcome="certified",
                        normalized_diagnostics=(),
                    )
                )
            context.ledger.record_artifact_acceptance(acceptance)
    assert not plan_next_v2(
        context.semantic_graph.prerequisite_graph,
        context.ledger.replay(),
        _AvailableBudget(),
    ).ready


def _accept_every_audit(
    context: Protocol25RunContext,
    *,
    limit: int | None = None,
) -> None:
    ledger = context.ledger.replay()
    accepted = {}
    for receipt in ledger.accepted_artifacts.values():
        item = ledger.certification_work_items.get(receipt.certification_receipt_id)
        if item is not None:
            accepted[item.template_id] = AcceptedArtifactV2(
                receipt.artifact_key.identity,
                receipt.artifact_hash,
            )
    targets = context.semantic_graph.ready_audit_targets(accepted)
    for index, (target, template) in enumerate(zip(
        targets,
        context.semantic_graph.audit_templates,
        strict=True,
    )):
        if limit is not None and index >= limit:
            break
        dependencies = {
            item: accepted[item] for item in template.required_template_ids
        }
        work_item = context.semantic_graph.instantiate_audit_item(
            template,
            target,
            dependencies,
        )
        artifact = AuditCandidateV1(
            schema_version=1,
            audit_target=target,
            artifact_key=work_item.output_key,
            audit_epoch_id=None,
            verdict="PASS",
            findings=(),
        )
        artifact_bytes = canonical_json_bytes(artifact.to_json_dict())
        artifact_hash = context.object_store.put_blob(artifact_bytes)
        normalized = canonical_json_bytes(
            {
                "schema_version": 1,
                "audit_target_id": target.identity,
                "verdict": "PASS",
                "findings": [],
            }
        )
        normalized_hash = context.object_store.put_blob(normalized)
        certification = SemanticCertificationReceiptV1(
            schema_version=1,
            artifact_key_id=work_item.output_key.identity,
            artifact_hash=artifact_hash,
            verifier_authority_hash=context.semantic_runtime.verifier_authority_hash,
            audit_epoch_id=None,
            audit_target_id=target.identity,
            evidence_scope_hash=content_digest({"audit_target_id": target.identity}),
            verdict="accepted",
            normalized_diagnostics=(),
        )
        capture_hash = context.object_store.put_blob(
            f"capture:{work_item.work_item_id}\n".encode()
        )
        assessment = CandidateAssessmentReceiptV1(
            schema_version=1,
            candidate_id=content_digest({"candidate": work_item.work_item_id}),
            work_item_id=work_item.work_item_id,
            execution_capture_hash=capture_hash,
            normalized_authorial_payload_hash=normalized_hash,
            artifact_hash=artifact_hash,
            certification_receipt_id=certification.identity,
            outcome="certified",
            normalized_diagnostics=(),
        )
        acceptance = ArtifactAcceptanceReceiptV2(
            schema_version=2,
            artifact_key=work_item.output_key,
            artifact_hash=artifact_hash,
            certification_receipt_id=certification.identity,
        )
        context.ledger.record_semantic_certification(certification)
        context.ledger.record_candidate_assessment(assessment)
        context.ledger.record_artifact_acceptance(acceptance)
        context.event_store.append(
            "audit_candidate_accepted",
            {
                "audit_candidate_authority_id": artifact.identity,
                "audit_target_id": target.identity,
            },
            occurred_at=context.clock(),
        )


@pytest.mark.integration
def test_blocked_pre_epoch_parent_exports_retained_audit_successor_authority(
    tmp_path,
) -> None:
    """Catch retained audit siblings being lost across immutable resume."""
    from harness.re_v2.protocol_25.lifecycle import (
        export_protocol_25_parent,
        prepare_guided_successor,
    )

    context = _context(tmp_path / "parent")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context, limit=1)
    context.event_store.append(
        "executor_failed",
        {
            "executor_contract_hash": digest("failed-audit-executor"),
            "executor_failure_receipt_id": digest("failed-audit-receipt"),
            "trigger_work_item_id": digest("missing-audit-work"),
        },
        occurred_at=context.clock(),
    )
    context.event_store.append(
        "run_failed",
        {"reason": "semantic closure is incomplete"},
        occurred_at=context.clock(),
    )

    exported = export_protocol_25_parent(context)
    prepared = prepare_guided_successor(
        parent=exported.parent,
        parent_manifest=exported.manifest,
        parent_inputs=exported.inputs,
        accepted_parent=exported.accepted_parent,
        parent_objects=exported.immutable_objects,
        answer="Retry the missing audit target with the retained sibling.",
        created_at="2026-08-26T13:00:00Z",
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        semantic_token_limit=1_000_000,
        semantic_active_ms_limit=1_800_000,
    )
    assert prepared.manifest.run_mode == "audit-successor"
    assert prepared.manifest.parent_run_id == context.semantic_graph.manifest.run_id
    assert len(exported.parent.adopted_audit_candidate_hashes) == 1
    assert len(exported.parent.remaining_audit_target_ids) == 1
    assert prepared.inputs.parent_authority_bundle.semantic_authority == (
        exported.parent.candidate.semantic_authority
    )


@pytest.mark.integration
def test_audit_epoch_publication_recovers_object_before_ledger(tmp_path) -> None:
    context, result, roots = _epoch_publication_fixture(tmp_path)

    def crash(boundary: str) -> None:
        if boundary.startswith("audit_epoch_object:"):
            raise _InjectedCrash(boundary)

    with pytest.raises(_InjectedCrash, match="audit_epoch_object"):
        publish_audit_epoch(context, (result,), roots, fault_hook=crash)

    assert context.ledger.replay().audit_epochs == {}
    first = publish_audit_epoch(context, (result,), roots)
    second = publish_audit_epoch(context, (result,), roots)

    assert first == second
    assert context.object_store.read_blob(first.identity) == canonical_json_bytes(
        first.to_json_dict()
    )
    assert tuple(context.ledger.replay().audit_epochs) == (first.identity,)
    assert [item.type for item in context.event_store.replay()].count(
        "audit_epoch_frozen"
    ) == 1


@pytest.mark.integration
def test_accepted_audit_result_reconstructs_without_provider_state(tmp_path) -> None:
    context, result, _roots = _epoch_publication_fixture(tmp_path)

    reconstructed = reconstruct_accepted_audit_results(context)

    assert reconstructed == (result,)


@pytest.mark.integration
def test_controller_persists_certified_audit_through_shared_receipt_chain(
    tmp_path,
) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    result = _certified_audit(verdict="PASS")
    item = _semantic_audit_work_item(context, result)
    capture_hash = context.object_store.put_blob(b"semantic capture\n")
    result = replace(
        result,
        candidate_assessment=replace(
            result.candidate_assessment,
            work_item_id=item.work_item_id,
            execution_capture_hash=capture_hash,
        ),
    )
    dispatch_id = "semantic-dispatch-1"
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
            "execution_input_hash": digest("semantic-execution-input"),
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
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
            "candidate_inventory_hash": digest("semantic-inventory"),
            "dispatch_id": dispatch_id,
            "execution_capture_hash": capture_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=occurred_at,
    )

    Protocol25Controller(context)._record_semantic_result(
        item,
        result.candidate_assessment.candidate_id,
        result,
    )

    ledger = context.ledger.replay()
    assert ledger.semantic_certifications[result.certification.identity] == result.certification
    assert ledger.candidate_assessments[result.candidate_assessment.identity] == result.candidate_assessment
    assert ledger.accepted_artifacts[result.acceptance.artifact_key.identity] == result.acceptance
    event_types = [event.type for event in context.event_store.replay()]
    assert event_types[-3:] == [
        "candidate_certified",
        "artifact_accepted",
        "audit_candidate_accepted",
    ]


@pytest.mark.integration
def test_controller_publishes_resolution_with_operation_specific_authority(
    tmp_path,
) -> None:
    context = _context(tmp_path)
    audit, epoch, _semantic_context_value, result = _certified_resolution()
    assert isinstance(result.artifact, SemanticResolutionOverlayV1)
    item = _semantic_result_work_item(context, result)
    capture_hash = context.object_store.put_blob(b"semantic resolution capture\n")
    result = replace(
        result,
        candidate_assessment=replace(
            result.candidate_assessment,
            work_item_id=item.work_item_id,
            execution_capture_hash=capture_hash,
        ),
    )
    occurred_at = context.clock()
    dispatch_id = "semantic-resolution-dispatch-1"
    source_id = digest("semantic-source")
    source_cycle_id = "cycle-semantic-resolution-1"
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=occurred_at,
    )
    context.event_store.append(
        "audit_candidate_accepted",
        {
            "audit_candidate_authority_id": audit.artifact.identity,
            "audit_target_id": audit.artifact.audit_target_id,
        },
        occurred_at=occurred_at,
    )
    context.event_store.append(
        "audit_epoch_frozen",
        {
            "audit_epoch_id": epoch.identity,
            "audit_target_ids": [audit.artifact.audit_target_id],
        },
        occurred_at=occurred_at,
    )
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
            "execution_input_hash": digest("resolution-execution-input"),
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=occurred_at,
    )
    context.event_store.append(
        "semantic_resolution_started",
        {
            "audit_target_id": audit.artifact.audit_target_id,
            "dispatch_id": dispatch_id,
            "semantic_round": 1,
            "source_cycle_id": source_cycle_id,
            "source_id": source_id,
            "work_item_id": item.work_item_id,
        },
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
            "candidate_inventory_hash": digest("resolution-inventory"),
            "dispatch_id": dispatch_id,
            "execution_capture_hash": capture_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=occurred_at,
    )

    Protocol25Controller(context)._record_semantic_result(
        item,
        result.candidate_assessment.candidate_id,
        result,
    )

    events = context.event_store.replay()
    assert events[-1].type == "semantic_resolution_accepted"
    assert events[-1].payload == {
        "audit_target_id": audit.artifact.audit_target_id,
        "resolution_overlay_id": result.artifact.identity,
        "semantic_round": 1,
        "source_cycle_id": source_cycle_id,
        "source_id": source_id,
        "work_item_id": item.work_item_id,
    }


@pytest.mark.integration
def test_audit_action_enters_inherited_single_dispatch_kernel(
    tmp_path,
    monkeypatch,
) -> None:
    context = _context(tmp_path)
    result = _certified_audit(verdict="PASS")
    item = _semantic_audit_work_item(context, result)
    semantic_context = _semantic_context()
    target_id = digest("ready-audit-target")
    state = Protocol25ControllerStateV1(
        prerequisites_complete=True,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=None,
        targets=(
            SemanticTargetControllerStateV1(
                audit_target_id=target_id,
                source_id="api",
                audit_state="pending",
            ),
        ),
    )
    recovered = recovery_module.Protocol25RecoveryResult(
        state,
        (),
        context.ledger.replay(),
    )
    executor = context.semantic_inputs.executor_contract.entry_for(
        item.producer_family
    )
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=b"prosaic agent\n",
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=b"{}\n",
        tokenizer=None,
    )
    context = replace(context, dependencies_for=lambda *_args: dependencies)
    shared_recovery = object()
    observed = []
    monkeypatch.setattr(
        recovery_module,
        "recover_protocol_25_run",
        lambda _context: recovered,
    )
    monkeypatch.setattr(
        recovery_module,
        "build_audit_dispatch_authority",
        lambda _context, _target_id: (item, semantic_context),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_semantic_provider_dependencies",
        lambda _context, _item, _semantic_context: dependencies,
    )
    monkeypatch.setattr(
        recovery_module,
        "_shared_action_recovery",
        lambda _context, _recovered: shared_recovery,
    )
    monkeypatch.setattr(
        Protocol25Controller,
        "_execute_one",
        lambda _self, selected, recovery: observed.append((selected, recovery)),
    )

    context.apply_controller_action(
        Protocol25ControllerActionV1(
            kind="audit_target",
            audit_target_id=target_id,
        )
    )

    assert observed == [(item, shared_recovery)]


@pytest.mark.integration
def test_resolution_action_enters_inherited_single_dispatch_kernel(
    tmp_path,
    monkeypatch,
) -> None:
    context = _context(tmp_path)
    audit, epoch, semantic_context, result = _certified_resolution()
    item = _semantic_result_work_item(context, result)
    finding_ids = tuple(
        finding.finding_key_id for finding in audit.normalized_findings
    )
    state = Protocol25ControllerStateV1(
        prerequisites_complete=True,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=epoch.identity,
        targets=(
            SemanticTargetControllerStateV1(
                audit_target_id=audit.artifact.audit_target_id,
                source_id="api",
                audit_state="accepted",
                frozen_finding_ids=finding_ids,
                unresolved_finding_ids=finding_ids,
            ),
        ),
    )
    action = plan_next_protocol_25(state)
    assert action is not None and action.kind == "resolve_target"
    recovered = recovery_module.Protocol25RecoveryResult(
        state,
        (),
        context.ledger.replay(),
    )
    executor = context.semantic_inputs.executor_contract.entry_for(
        "semantic-resolution"
    )
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=b"prosaic resolver\n",
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=b"{}\n",
        tokenizer=None,
    )
    context = replace(context, dependencies_for=lambda *_args: dependencies)
    shared_recovery = object()
    observed = []
    monkeypatch.setattr(
        recovery_module,
        "recover_protocol_25_run",
        lambda _context: recovered,
    )
    monkeypatch.setattr(
        recovery_module,
        "build_resolution_dispatch_authority",
        lambda _context, _action: (item, semantic_context),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_semantic_provider_dependencies",
        lambda _context, _item, _semantic_context: dependencies,
    )
    monkeypatch.setattr(
        recovery_module,
        "_shared_action_recovery",
        lambda _context, _recovered: shared_recovery,
    )
    monkeypatch.setattr(
        Protocol25Controller,
        "_execute_one",
        lambda _self, selected, recovery: observed.append((selected, recovery)),
    )

    context.apply_controller_action(action)

    assert observed == [(item, shared_recovery)]


@pytest.mark.integration
def test_recheck_action_enters_inherited_single_dispatch_kernel(
    tmp_path,
    monkeypatch,
) -> None:
    context = _context(tmp_path)
    audit, epoch, _base_context, _resolution, result = _certified_closure()
    item = _semantic_result_work_item(context, result)
    target_id = audit.artifact.audit_target_id
    finding_ids = tuple(
        finding.finding_key_id for finding in audit.normalized_findings
    )
    cycle = SemanticSourceCycleStateV1(
        source_id="api",
        source_cycle_id="cycle-recheck-1",
        semantic_round=1,
        participating_target_ids=(target_id,),
    )
    state = Protocol25ControllerStateV1(
        prerequisites_complete=True,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=epoch.identity,
        targets=(
            SemanticTargetControllerStateV1(
                audit_target_id=target_id,
                source_id="api",
                audit_state="accepted",
                frozen_finding_ids=finding_ids,
                unresolved_finding_ids=finding_ids,
                stage="resolution_accepted",
            ),
        ),
        source_cycles=(cycle,),
    )
    action = plan_next_protocol_25(state)
    assert action is not None and action.kind == "recheck_target"
    recovered = recovery_module.Protocol25RecoveryResult(
        state,
        (),
        context.ledger.replay(),
    )
    executor = context.semantic_inputs.executor_contract.entry_for(
        "closure-recheck"
    )
    semantic_context = _semantic_context(
        unresolved=audit.normalized_findings,
        mode="CLOSURE_RECHECK",
        overlays=(result.artifact.resolution_overlay_hash,),
        extra_authority={
            result.artifact.resolution_overlay_hash: _resolution.artifact_bytes,
        },
    )
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=b"prosaic validator\n",
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=b"{}\n",
        tokenizer=None,
    )
    context = replace(context, dependencies_for=lambda *_args: dependencies)
    shared_recovery = object()
    observed = []
    monkeypatch.setattr(
        recovery_module,
        "recover_protocol_25_run",
        lambda _context: recovered,
    )
    monkeypatch.setattr(
        recovery_module,
        "build_recheck_dispatch_authority",
        lambda _context, _action: (item, semantic_context),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_semantic_provider_dependencies",
        lambda _context, _item, _semantic_context: dependencies,
    )
    monkeypatch.setattr(
        recovery_module,
        "_shared_action_recovery",
        lambda _context, _recovered: shared_recovery,
    )
    monkeypatch.setattr(
        Protocol25Controller,
        "_execute_one",
        lambda _self, selected, recovery: observed.append((selected, recovery)),
    )

    context.apply_controller_action(action)

    assert observed == [(item, shared_recovery)]


@pytest.mark.integration
def test_source_guard_action_enters_inherited_single_dispatch_kernel(
    tmp_path,
    monkeypatch,
) -> None:
    context = _context(tmp_path)
    audit = _certified_audit(verdict="PASS")
    audit_item = _semantic_audit_work_item(context, audit)
    source_target = audit_target_v1(target_kind="source")
    item = recovery_module._semantic_operation_item(
        context,
        audit_item,
        source_target,
        "source-composition-assessment",
        tuple(sorted((digest("epoch"), digest("overlay"), digest("assessment")))),
    )
    target_id = digest("guard-target")
    cycle = SemanticSourceCycleStateV1(
        source_id="api",
        source_cycle_id="cycle-guard-1",
        semantic_round=1,
        participating_target_ids=(target_id,),
    )
    state = Protocol25ControllerStateV1(
        prerequisites_complete=True,
        prerequisites_failed=False,
        paused_resource=False,
        audit_epoch_id=digest("epoch"),
        targets=(
            SemanticTargetControllerStateV1(
                audit_target_id=target_id,
                source_id="api",
                audit_state="accepted",
                frozen_finding_ids=(digest("finding"),),
                unresolved_finding_ids=(digest("finding"),),
                stage="assessment_accepted",
            ),
        ),
        source_cycles=(cycle,),
    )
    action = plan_next_protocol_25(state)
    assert action is not None and action.kind == "guard_source"
    recovered = recovery_module.Protocol25RecoveryResult(
        state,
        (),
        context.ledger.replay(),
    )
    semantic_context = _semantic_context()
    executor = context.semantic_inputs.executor_contract.entry_for(
        "source-composition-guard"
    )
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=b"prosaic validator\n",
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=b"{}\n",
        tokenizer=None,
    )
    context = replace(context, dependencies_for=lambda *_args: dependencies)
    shared_recovery = object()
    observed = []
    monkeypatch.setattr(
        recovery_module,
        "recover_protocol_25_run",
        lambda _context: recovered,
    )
    monkeypatch.setattr(
        recovery_module,
        "build_source_guard_dispatch_authority",
        lambda _context, _action: (item, semantic_context),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_semantic_provider_dependencies",
        lambda _context, _item, _semantic_context: dependencies,
    )
    monkeypatch.setattr(
        recovery_module,
        "_shared_action_recovery",
        lambda _context, _recovered: shared_recovery,
    )
    monkeypatch.setattr(
        Protocol25Controller,
        "_execute_one",
        lambda _self, selected, recovery: observed.append((selected, recovery)),
    )

    context.apply_controller_action(action)

    assert observed == [(item, shared_recovery)]


@pytest.mark.integration
def test_semantic_work_item_uses_protocol_25_dependency_specialization(
    tmp_path,
    monkeypatch,
) -> None:
    context = _context(tmp_path)
    result = _certified_audit(verdict="PASS")
    item = _semantic_audit_work_item(context, result)
    semantic_context = _semantic_context()
    executor = context.semantic_inputs.executor_contract.entry_for(
        item.producer_family
    )
    expected = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=context.installed_authorities,
        agent_bytes=b"prosaic agent\n",
        context_bytes=canonical_json_bytes(semantic_context.to_json_dict()),
        response_schema_bytes=b"{}\n",
        tokenizer=None,
    )
    monkeypatch.setattr(
        recovery_module,
        "build_audit_dispatch_authority",
        lambda _context, _target_id: (item, semantic_context),
    )
    monkeypatch.setattr(
        recovery_module,
        "build_semantic_provider_dependencies",
        lambda _context, _item, _semantic_context: expected,
        raising=False,
    )

    assert context.dependencies_for(item, "initial_generation") is expected


@pytest.mark.integration
def test_semantic_dependencies_fail_closed_when_pinned_prosaic_bytes_are_absent(
    tmp_path,
) -> None:
    context = _context(tmp_path)
    result = _certified_audit(verdict="PASS")
    item = _semantic_audit_work_item(context, result)
    semantic_context = _semantic_context()

    with pytest.raises(
        recovery_module.Protocol25RecoveryError,
        match="semantic Prosaic agent or response schema is unavailable",
    ):
        recovery_module.build_semantic_provider_dependencies(
            context,
            item,
            semantic_context,
        )


@pytest.mark.integration
def test_freeze_epoch_action_reconstructs_and_publishes_at_most_once(tmp_path) -> None:
    context = _context(tmp_path)
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context)
    action = Protocol25ControllerActionV1(kind="freeze_epoch")

    context.apply_controller_action(action)
    context.apply_controller_action(action)

    events = context.event_store.replay()
    assert [item.type for item in events].count("audit_epoch_frozen") == 1
    assert len(context.ledger.replay().audit_epochs) == 1


@pytest.mark.integration
def test_audit_epoch_publication_recovers_ledger_before_event(tmp_path) -> None:
    context, result, roots = _epoch_publication_fixture(tmp_path)

    def crash(boundary: str) -> None:
        if boundary.startswith("audit_epoch_ledger:"):
            raise _InjectedCrash(boundary)

    with pytest.raises(_InjectedCrash, match="audit_epoch_ledger"):
        publish_audit_epoch(context, (result,), roots, fault_hook=crash)

    epoch_id = next(iter(context.ledger.replay().audit_epochs))
    assert "audit_epoch_frozen" not in {
        item.type for item in context.event_store.replay()
    }

    resumed = publish_audit_epoch(context, (result,), roots)

    assert resumed.identity == epoch_id
    assert [item.type for item in context.event_store.replay()].count(
        "audit_epoch_frozen"
    ) == 1
