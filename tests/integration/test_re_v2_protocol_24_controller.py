from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_22.execution import Protocol22ExecutionStore
from harness.re_v2.protocol_22.graph import AcceptedArtifactV2
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_24.adoption import (
    ValidatedParentV1,
    build_parent_authority_bundle,
    import_parent_acceptance_closure,
)
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_24.graph import build_protocol_24_graph
from harness.re_v2.protocol_24.inputs import (
    Protocol24InputSet,
    create_protocol_24_run_store,
    load_protocol_24_inputs,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from harness.re_v2.run_store import load_run_manifest
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_controller import _baseline_context


CHILD_NOW = "2026-08-24T13:00:00Z"


def _completed_parent(tmp_path: Path) -> ValidatedParentV1:
    context, _provider = _baseline_context(tmp_path / "parent")
    result = Protocol22Controller(context).run_until_stopped()
    assert result.status == "completed"
    assert result.ledger is not None
    history, ledger = context.ledger.replay_with_history()
    manifest = load_run_manifest(context.paths.root.parent)
    accepted_parent = {}
    for template in context.graph.templates:
        work_item = next(
            item
            for item in ledger.certification_work_items.values()
            if item.template_id == template.template_id
        )
        artifact = ledger.artifact_for_key(work_item.output_key.identity)
        assert artifact is not None
        accepted_parent[template.template_id] = (template, artifact)
    return ValidatedParentV1(
        run_dir=context.paths.root.parent,
        paths=context.paths,
        manifest=manifest,
        inputs=context.inputs,
        graph=context.graph,
        events=result.events,
        ledger=ledger,
        ledger_history=history,
        manifest_bytes=context.paths.manifest.read_bytes(),
        event_chain_bytes=context.paths.events.read_bytes(),
        ledger_chain_bytes=context.paths.ledger.read_bytes(),
        accepted_parent=accepted_parent,
        ancestor_objects={},
    )


def _paused_child_context(tmp_path: Path) -> Protocol22RunContext:
    parent = _completed_parent(tmp_path)
    bundle, authority_objects = build_parent_authority_bundle(parent)
    policy = build_deepening_v1_policy_catalog()
    source = parent.inputs.workspace_partition.sources[0]
    domain = source.domains[0]
    base = manifest_v3(run_id="re-child-controller")
    manifest = replace(
        base,
        source_snapshot_id=parent.inputs.workspace_partition.snapshot_id,
        partition_manifest_id=parent.manifest.partition_manifest_id,
        workspace_partition_catalog=CatalogReferenceV1(
            parent.inputs.workspace_partition.identity,
            "workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            policy.identity,
            "artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            parent.inputs.executor_contract.identity,
            "executor-contract.json",
        ),
        parent_authority_bundle=CatalogReferenceV1(
            bundle.identity,
            "parent-authority.json",
        ),
        parent_lineage=replace(
            base.parent_lineage,
            direct_parent_run_id=parent.manifest.run_id,
            direct_parent_manifest_hash=content_digest(parent.manifest_bytes),
            direct_parent_terminal_event_hash=parent.events[-1].event_hash,
            lineage_root_run_id=parent.manifest.run_id,
            lineage_root_manifest_hash=content_digest(parent.manifest_bytes),
        ),
        selection=replace(
            base.selection,
            source_ids=(source.source_id,),
            domain_keys=(domain.domain_key,),
        ),
    )
    input_set = Protocol24InputSet(
        workspace_partition=parent.inputs.workspace_partition,
        artifact_policy=policy,
        executor_contract=parent.inputs.executor_contract,
        immutable_objects={
            **dict(parent.inputs.immutable_objects),
            **dict(authority_objects),
        },
        parent_authority_bundle=bundle,
    )
    paths = create_protocol_24_run_store(
        tmp_path / "runs" / manifest.run_id,
        manifest,
        input_set,
    )
    inputs = load_protocol_24_inputs(paths, manifest)
    graph = build_protocol_24_graph(manifest, inputs, parent.accepted_parent)
    objects = ObjectStore(paths.objects)
    ledger = Protocol22Ledger(paths, objects)
    import_parent_acceptance_closure(parent, objects, ledger)
    events = EventStore(paths, protocol=PROTOCOL_24_EVENTS)
    events.append(
        "run_created",
        {"run_manifest_id": manifest.run_manifest_id},
        occurred_at=manifest.created_at,
    )
    by_certification = {
        value.certification_receipt_id: value for value in bundle.artifacts
    }
    for certification_id, work_item in sorted(
        ledger.replay().certification_work_items.items()
    ):
        authority = by_certification[certification_id]
        events.append(
            "artifact_adopted",
            {
                "adopted_artifact_authority": authority.to_json_dict(),
                "parent_authority_bundle_hash": bundle.identity,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=CHILD_NOW,
        )
    events.append(
        "operator_pause_requested",
        {"reason": "composition boundary", "requested_by": "test"},
        occurred_at=CHILD_NOW,
    )
    events.append(
        "run_paused",
        {"reason": "composition boundary", "reason_code": "operator_pause"},
        occurred_at=CHILD_NOW,
    )
    return Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=events,
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=_registry(parent),
        dependencies_for=lambda _item, _attempt: (_ for _ in ()).throw(
            AssertionError("paused composition must not prepare execution")
        ),
        executors={},
        producers={},
        verifiers={},
        clock=lambda: CHILD_NOW,
    )


def _registry(parent: ValidatedParentV1):
    from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs

    return _registry_from_inputs(parent.inputs)


@pytest.mark.integration
def test_protocol_24_child_composes_with_unchanged_controller_recovery(
    tmp_path: Path,
) -> None:
    context = _paused_child_context(tmp_path)

    result = Protocol22Controller(context).run_until_stopped()

    assert result.status == "paused"
    assert result.ledger is not None
    assert len(result.ledger.accepted_artifacts) == len(
        context.inputs.parent_authority_bundle.artifacts
    )
    assert any(event.type == "artifact_adopted" for event in result.events)
