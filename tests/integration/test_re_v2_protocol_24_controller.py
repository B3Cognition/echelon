from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import MappingProxyType

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.controller import Protocol22Controller
from harness.re_v2.protocol_22.controller import accepted_dependencies_for
from harness.re_v2.protocol_22.execution import (
    DeterministicExecutionDependenciesV1,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
)
from harness.re_v2.protocol_22.graph import AcceptedArtifactV2
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import (
    CatalogReferenceV1,
    DeterministicInvocationInputV1,
    DeterministicInvocationV1,
)
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_24.adoption import (
    ValidatedParentV1,
    build_parent_authority_bundle,
    import_parent_acceptance_closure,
)
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_24.events import PROTOCOL_24_EVENTS
from harness.re_v2.protocol_24.controller import Protocol24Controller
from harness.re_v2.protocol_24.graph import build_protocol_24_graph
from harness.re_v2.protocol_24.inputs import (
    Protocol24InputSet,
    create_protocol_24_run_store,
    load_protocol_24_inputs,
)
from harness.re_v2.protocol_24.policies import build_deepening_v1_policy_catalog
from harness.re_v2.protocol_24.runtime import Protocol24DeterministicRuntime
from harness.re_v2.run_store import load_run_manifest
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_22_controller import (
    _ScriptedProvider,
    _SnapshotReader,
    _baseline_context,
)
from tests.unit.test_re_v2_protocol_22_provider import _tokenizer
from tests.unit.test_re_v2_protocol_24_prosaic import _role_artifact


CHILD_NOW = "2026-08-24T13:00:00Z"


def _completed_parent(
    tmp_path: Path,
    *,
    provider_mode: str = "api",
) -> ValidatedParentV1:
    context, _provider = _baseline_context(
        tmp_path / "parent",
        provider_mode=provider_mode,
    )
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


def _child_context(
    tmp_path: Path,
    *,
    paused: bool,
    provider_mode: str = "api",
) -> tuple[Protocol22RunContext, _ScriptedProvider | None]:
    parent = _completed_parent(tmp_path, provider_mode=provider_mode)
    bundle, authority_objects = build_parent_authority_bundle(parent)
    policy = build_deepening_v1_policy_catalog()
    deepener_bytes = canonical_prosaic_agent_bytes(_role_artifact())
    deepener_hash = content_digest(deepener_bytes)
    executors = build_deepening_executor_catalog(
        parent.inputs.executor_contract,
        deepener_hash,
    )
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
            executors.identity,
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
        executor_contract=executors,
        immutable_objects={
            **dict(parent.inputs.immutable_objects),
            **dict(authority_objects),
            deepener_hash: deepener_bytes,
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
    if paused:
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
    registry = _registry(parent)
    provider = None if paused else _NovelL2Provider()
    snapshot_payloads = {
        (source.source_id, record.source_relative_path): b"print('ok')\n"
        for source in inputs.workspace_partition.sources
        for record in source.files
    }
    adopted_payloads = {
        (
            template.scope.source_id,
            template.scope.domain_key,
            template.layer,
            template.artifact_kind,
        ): objects.read_blob(artifact.artifact_hash)
        for template, artifact in parent.accepted_parent.values()
    }
    runtime = Protocol24DeterministicRuntime(
        inputs,
        _SnapshotReader(inputs.workspace_partition, snapshot_payloads),
        adopted_payloads,
    )
    context_ref: dict[str, Protocol22RunContext] = {}

    def dependencies_for(item: object, _attempt_kind: str) -> object:
        accepted = accepted_dependencies_for(context_ref["context"], item)
        executor = inputs.executor_contract.entry_for(item.producer_family)
        if executor.execution_mode in {"api", "cli"}:
            renderer = executor.request_renderer
            assert renderer is not None
            schema_hash = next(
                reference.schema_hash
                for reference in renderer.response_schemas
                if reference.artifact_kind == item.output_key.artifact_kind
            )
            return ProviderExecutionDependenciesV1(
                executor=executor,
                registry=registry,
                agent_bytes=objects.read_blob(renderer.agent_contract_hash),
                context_bytes=accepted.payload_for_role("context_bundle"),
                response_schema_bytes=objects.read_blob(schema_hash),
                tokenizer=(
                    _tokenizer(executor, 100)
                    if executor.execution_mode == "api"
                    else None
                ),
            )
        return DeterministicExecutionDependenciesV1(
            executor=executor,
            registry=registry,
            invocation=DeterministicInvocationV1(
                schema_version=1,
                producer_family=item.producer_family,
                output_key=item.output_key,
                artifact_policy_hash=item.output_key.layer_policy_hash,
                inputs=tuple(
                    DeterministicInvocationInputV1(
                        role=role,
                        object_hash=value.artifact_hash,
                    )
                    for role, value in accepted.by_role.items()
                ),
            ),
            workspace_partition_hash=None,
            referenced_objects=dict(accepted.payloads_by_hash),
        )

    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=events,
        object_store=objects,
        ledger=ledger,
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=registry,
        dependencies_for=(
            (lambda _item, _attempt: (_ for _ in ()).throw(
                AssertionError("paused composition must not prepare execution")
            ))
            if paused
            else dependencies_for
        ),
        executors=MappingProxyType(
            {}
            if provider is None
            else {
                inputs.executor_contract.entry_for("compact-deepening").adapter_id: provider
            }
        ),
        producers=MappingProxyType(
            {
                entry.producer_family: runtime
                for entry in inputs.executor_contract.entries
                if entry.execution_mode == "in_process"
            }
        ),
        verifiers=MappingProxyType(
            {
                entry.verifier.verifier_id: runtime
                for entry in inputs.executor_contract.entries
            }
        ),
        clock=lambda: CHILD_NOW,
    )
    context_ref["context"] = context
    return context, provider


class _NovelL2Provider(_ScriptedProvider):
    def execute(self, *args: object, **kwargs: object):
        result = super().execute(*args, **kwargs)
        candidate_root = args[-2]
        candidate_path = candidate_root / "baseline.json"
        raw = json.loads(candidate_path.read_bytes())
        for surface in raw["surfaces"].values():
            for claim in surface["items"]:
                claim["statement"] = f"L2 deepening: {claim['statement']}"
        candidate_path.write_bytes(canonical_json_bytes(raw))
        return result


def _registry(parent: ValidatedParentV1):
    from dataclasses import replace

    from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs

    registry = _registry_from_inputs(parent.inputs)
    return replace(
        registry,
        agent_contracts={
            **dict(registry.agent_contracts),
            "echelon.re-deepener": content_digest(
                canonical_prosaic_agent_bytes(_role_artifact())
            ),
        },
    )


@pytest.mark.integration
def test_protocol_24_child_composes_with_inherited_controller_recovery(
    tmp_path: Path,
) -> None:
    context, provider = _child_context(tmp_path, paused=True)

    result = Protocol24Controller(context).run_until_stopped()

    assert provider is None
    assert result.status == "paused"
    assert result.ledger is not None
    assert len(result.ledger.accepted_artifacts) == len(
        context.inputs.parent_authority_bundle.artifacts
    )
    assert any(event.type == "artifact_adopted" for event in result.events)


@pytest.mark.integration
@pytest.mark.parametrize("provider_mode", ("api", "cli"))
def test_protocol_24_child_completes_selected_l2_through_shared_execution(
    tmp_path: Path,
    provider_mode: str,
) -> None:
    context, provider = _child_context(
        tmp_path,
        paused=False,
        provider_mode=provider_mode,
    )
    assert provider is not None

    result = Protocol24Controller(context).run_until_stopped()

    assert result.status == "completed"
    assert result.ledger is not None
    l2_templates = [item for item in context.graph.templates if item.layer == "L2"]
    assert provider.calls == 2
    assert len(result.ledger.accepted_artifacts) == len(context.graph.templates)
    assert all(
        result.ledger.artifact_for_key(
            next(
                work.output_key.identity
                for work in result.ledger.certification_work_items.values()
                if work.template_id == template.template_id
            )
        )
        is not None
        for template in l2_templates
    )


@pytest.mark.integration
def test_protocol_24_controller_is_a_narrow_frozen_controller_extension() -> None:
    assert issubclass(Protocol24Controller, Protocol22Controller)
    assert Protocol24Controller.run_until_stopped is Protocol22Controller.run_until_stopped
    assert Protocol24Controller._execute_provider is Protocol22Controller._execute_provider
    assert (
        Protocol24Controller._materialize_accepted_l1
        is not Protocol22Controller._materialize_accepted_l1
    )
    assert (
        Protocol24Controller._certify_provider_candidate
        is not Protocol22Controller._certify_provider_candidate
    )
