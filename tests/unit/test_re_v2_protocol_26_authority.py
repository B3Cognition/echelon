from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.execution import Protocol22ExecutionStore
from harness.re_v2.protocol_22.graph import build_protocol_22_graph
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.recovery import (
    Protocol22RunContext,
    recover_protocol_22_run,
)
from harness.re_v2.protocol_26.authority import resolve_run_authority
from harness.re_v2.protocol_26.events import protocol_26_events_for
from harness.re_v2.protocol_26.inputs import (
    Protocol26InputSet,
    create_protocol_26_run_store,
    load_protocol_26_inputs,
)
from harness.re_v2.protocol_26.model import (
    LayerExecutionContractV1,
    RunManifestV5,
)
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_24.inputs import Protocol24InputSet
from harness.re_v2.run_store import load_run_manifest
from tests.integration.test_re_v2_protocol_24_controller import _child_context
from tests.integration.test_re_v2_protocol_25_recovery import _context as _l3_context
from tests.re_v2_protocol_26_fixtures import checkpoint_selection_bundle_v1
from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs
from tests.unit.test_re_v2_protocol_26_inputs import _protocol26_input_fixture


def _l1_context(tmp_path: Path) -> tuple[Protocol22RunContext, object]:
    supplied = _protocol26_input_fixture("L1")
    paths = create_protocol_26_run_store(
        tmp_path / supplied.manifest.run_id,
        supplied.manifest,
        supplied,
    )
    outer = load_protocol_26_inputs(paths, supplied.manifest)
    inputs = outer.layer_inputs
    layer_manifest = outer.layer_execution_contract.layer_manifest
    graph = build_protocol_22_graph(layer_manifest, inputs)
    objects = ObjectStore(paths.objects)

    def no_dependencies(*_args: object) -> object:
        raise AssertionError("authority test stops before execution preparation")

    context = Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=protocol_26_events_for("L1")),
        object_store=objects,
        ledger=Protocol22Ledger(paths, objects),
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=_registry_from_inputs(inputs),
        dependencies_for=no_dependencies,
        executors=MappingProxyType({}),
        producers=MappingProxyType({}),
        verifiers=MappingProxyType({}),
        clock=lambda: "2026-08-28T10:00:00Z",
    )
    return context, outer


@pytest.mark.unit
def test_schema5_resolves_existing_l1_layer_graph(tmp_path: Path) -> None:
    context, outer = _l1_context(tmp_path)

    authority = resolve_run_authority(context)

    assert authority.active_manifest == outer.manifest
    assert authority.layer_manifest == outer.layer_execution_contract.layer_manifest
    assert authority.shared_inputs == context.inputs
    assert authority.shared_graph == context.graph
    assert authority.semantic_inputs is None
    assert authority.semantic_graph is None


@pytest.mark.unit
def test_schema5_recovery_creates_outer_run_identity_before_planning(
    tmp_path: Path,
) -> None:
    context, outer = _l1_context(tmp_path)

    with pytest.raises(AssertionError, match="stops before execution"):
        recover_protocol_22_run(context)

    event = context.event_store.replay()[0]
    assert event.type == "run_created"
    assert event.payload["run_manifest_id"] == outer.manifest.run_manifest_id


def _empty_selection(manifest: object, target_layer: str):  # type: ignore[no-untyped-def]
    base = checkpoint_selection_bundle_v1()
    selection_id = (
        manifest.selection.identity
        if hasattr(manifest, "selection")
        else base.target_selection_id
    )
    return replace(
        base,
        source_snapshot_id=manifest.source_snapshot_id,
        partition_manifest_id=manifest.partition_manifest_id,
        target_layer=target_layer,
        target_selection_id=selection_id,
        selected=(),
        origin_manifest_hashes=(),
        origin_event_prefix_hashes=(),
        origin_ledger_prefix_hashes=(),
        copied_receipt_ids=(),
        copied_work_item_ids=(),
        copied_object_ids=(),
        copied_byte_count=0,
    )


def _outer_manifest(manifest: object, target_layer: str, contract, selection):  # type: ignore[no-untyped-def]
    return RunManifestV5(
        schema_version=5,
        engine="re-v2",
        engine_protocol_version="2.6",
        run_id=manifest.run_id,
        created_at=manifest.created_at,
        source_snapshot_id=manifest.source_snapshot_id,
        source_snapshot_kind=manifest.source_snapshot_kind,
        partition_manifest_id=manifest.partition_manifest_id,
        target_layer=target_layer,
        layer_execution_contract=CatalogReferenceV1(
            contract.identity,
            "layer-execution-contract.json",
        ),
        checkpoint_selection=CatalogReferenceV1(
            selection.identity,
            "checkpoint-selection.json",
        ),
    )


@pytest.mark.unit
def test_schema5_resolves_existing_l2_layer_graph(tmp_path: Path) -> None:
    legacy, _provider = _child_context(tmp_path / "legacy", paused=True)
    manifest = load_run_manifest(legacy.paths.root.parent)
    inputs = legacy.inputs
    raw = Protocol24InputSet(
        inputs.workspace_partition,
        inputs.artifact_policy,
        inputs.executor_contract,
        inputs.immutable_objects,
        inputs.parent_authority_bundle,
    )
    contract = LayerExecutionContractV1.from_layer_manifest(manifest)
    selection = _empty_selection(manifest, "L2")
    outer = _outer_manifest(manifest, "L2", contract, selection)
    supplied = Protocol26InputSet(outer, contract, raw, selection, {})
    paths = create_protocol_26_run_store(
        tmp_path / "schema5" / manifest.run_id,
        outer,
        supplied,
    )
    loaded = load_protocol_26_inputs(paths, outer)
    objects = ObjectStore(paths.objects)
    context = replace(
        legacy,
        paths=paths,
        inputs=loaded.layer_inputs,
        event_store=EventStore(paths, protocol=protocol_26_events_for("L2")),
        object_store=objects,
        ledger=Protocol22Ledger(paths, objects),
        execution_store=Protocol22ExecutionStore(paths, objects),
    )

    authority = resolve_run_authority(context)

    assert authority.active_manifest == outer
    assert authority.layer_manifest == manifest
    assert authority.shared_graph == legacy.graph


@pytest.mark.unit
def test_schema5_resolves_existing_l3_layer_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.re_v2.protocol_26 import authority as authority_module

    legacy = _l3_context(tmp_path / "legacy")
    manifest = legacy.semantic_graph.manifest
    contract = LayerExecutionContractV1.from_layer_manifest(manifest)
    selection = _empty_selection(manifest, "L3")
    outer = _outer_manifest(manifest, "L3", contract, selection)
    legacy.paths.manifest.write_bytes(canonical_json_bytes(outer.to_json_dict()))
    monkeypatch.setattr(
        authority_module,
        "load_protocol_26_inputs",
        lambda _paths, _manifest: SimpleNamespace(
            layer_execution_contract=contract,
            layer_inputs=legacy.semantic_inputs,
        ),
    )

    authority = resolve_run_authority(legacy)

    assert authority.active_manifest == outer
    assert authority.layer_manifest == manifest
    assert authority.semantic_inputs == legacy.semantic_inputs
    assert authority.semantic_graph == legacy.semantic_graph


@pytest.mark.unit
def test_schema5_l3_recovery_uses_outer_identity_and_layer_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.re_v2.protocol_25.recovery import recover_protocol_25_run
    from harness.re_v2.protocol_26 import authority as authority_module

    legacy = _l3_context(tmp_path)
    manifest = legacy.semantic_graph.manifest
    contract = LayerExecutionContractV1.from_layer_manifest(manifest)
    selection = _empty_selection(manifest, "L3")
    outer = _outer_manifest(manifest, "L3", contract, selection)
    legacy.paths.manifest.write_bytes(canonical_json_bytes(outer.to_json_dict()))
    context = replace(
        legacy,
        event_store=EventStore(
            legacy.paths,
            protocol=protocol_26_events_for("L3"),
        ),
    )
    monkeypatch.setattr(
        authority_module,
        "load_protocol_26_inputs",
        lambda _paths, _manifest: SimpleNamespace(
            layer_execution_contract=contract,
            layer_inputs=context.semantic_inputs,
        ),
    )
    context.event_store.append(
        "run_created",
        {"run_manifest_id": outer.run_manifest_id},
        occurred_at=outer.created_at,
    )

    recovered = recover_protocol_25_run(context)

    assert recovered.events[0].payload["run_manifest_id"] == outer.run_manifest_id
    assert recovered.controller_state.prerequisites_complete is False
