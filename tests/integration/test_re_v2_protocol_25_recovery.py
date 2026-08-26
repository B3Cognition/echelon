from __future__ import annotations

from types import MappingProxyType

import pytest

import harness.re_v2.protocol_25 as protocol_25
from harness.re_v2.events import EventStore
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.execution import Protocol22ExecutionStore
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_25.adoption import (
    ParentAuthorityBundleV2,
    ParentSemanticAuthorityV1,
)
from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
from harness.re_v2.protocol_25.inputs import ValidatedProtocol25Inputs
from harness.re_v2.protocol_25.ledger import Protocol25Ledger
from harness.re_v2.protocol_25.recovery import (
    Protocol25RunContext,
    recover_protocol_25_run,
)
from harness.re_v2.protocol_25.controller import Protocol25ControllerActionV1
from tests.re_v2_protocol_22_fixtures import digest
from harness.re_v2.protocol_25.runtime import Protocol25DeterministicRuntime
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_25_fixtures import lower_parent_authority_bundle_v1
from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs
from tests.unit.test_re_v2_protocol_25_graph import _fixture as _graph_fixture


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
