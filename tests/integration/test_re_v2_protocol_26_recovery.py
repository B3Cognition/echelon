from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

import pytest

from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.execution import Protocol22ExecutionStore
from harness.re_v2.protocol_22.graph import build_protocol_22_graph
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.recovery import Protocol22RunContext
from harness.re_v2.protocol_26.adoption import initialize_protocol_26_run
from harness.re_v2.protocol_26.events import protocol_26_events_for
from harness.re_v2.protocol_26.inputs import (
    create_protocol_26_run_store,
    load_protocol_26_inputs,
)
from harness.re_v2.run_store import load_run_manifest
from tests.unit.test_re_v2_protocol_22_recovery import _registry_from_inputs
from tests.unit.test_re_v2_protocol_26_inputs import _protocol26_input_fixture


def _context(tmp_path: Path) -> Protocol22RunContext:
    supplied = _protocol26_input_fixture("L1")
    paths = create_protocol_26_run_store(
        tmp_path / supplied.manifest.run_id,
        supplied.manifest,
        supplied,
    )
    outer = load_protocol_26_inputs(paths, supplied.manifest)
    inputs = outer.layer_inputs
    manifest = outer.layer_execution_contract.layer_manifest
    graph = build_protocol_22_graph(manifest, inputs)
    objects = ObjectStore(paths.objects)
    return Protocol22RunContext(
        paths=paths,
        inputs=inputs,
        graph=graph,
        event_store=EventStore(paths, protocol=protocol_26_events_for("L1")),
        object_store=objects,
        ledger=Protocol22Ledger(paths, objects),
        execution_store=Protocol22ExecutionStore(paths, objects),
        installed_authorities=_registry_from_inputs(inputs),
        dependencies_for=lambda *_args: (_ for _ in ()).throw(
            AssertionError("checkpoint initialization must not plan or dispatch")
        ),
        executors=MappingProxyType({}),
        producers=MappingProxyType({}),
        verifiers=MappingProxyType({}),
        clock=lambda: "2026-08-28T10:00:00Z",
    )


@pytest.mark.integration
def test_checkpoint_initialization_imports_before_any_dispatch(tmp_path: Path) -> None:
    context = _context(tmp_path)

    report = initialize_protocol_26_run(context)

    events = context.event_store.replay()
    assert events[0].type == "run_created"
    assert [event.type for event in events[1:]] == [
        "checkpoint_artifact_adopted"
    ] * len(report.imports)
    assert not any(event.type.startswith("dispatch_") for event in events)
    assert set(report.artifact_key_ids) <= set(
        context.ledger.replay().accepted_artifacts
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "seam",
    ("run_created", "checkpoint_receipts_imported", "checkpoint_events_appended"),
)
def test_checkpoint_initialization_recovers_exactly_after_crash(
    tmp_path: Path,
    seam: str,
) -> None:
    context = _context(tmp_path)
    crashed = False

    def crash(boundary: str) -> None:
        nonlocal crashed
        if not crashed and boundary == seam:
            crashed = True
            raise RuntimeError(f"crash:{seam}")

    with pytest.raises(RuntimeError, match=f"crash:{seam}"):
        initialize_protocol_26_run(context, fault_hook=crash)
    report = initialize_protocol_26_run(context)
    event_bytes = context.paths.events.read_bytes()
    ledger_bytes = context.paths.ledger.read_bytes()

    assert initialize_protocol_26_run(context) == report
    assert context.paths.events.read_bytes() == event_bytes
    assert context.paths.ledger.read_bytes() == ledger_bytes


@pytest.mark.integration
def test_checkpoint_initialization_rejects_dispatch_before_adoption(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)
    outer = load_protocol_26_inputs(
        context.paths,
        load_run_manifest(context.paths.root.parent),
    )
    selected = outer.checkpoint_selection.selected[0]
    context.event_store.append(
        "run_created",
        {"run_manifest_id": outer.manifest.run_manifest_id},
        occurred_at=outer.manifest.created_at,
    )
    context.event_store.append(
        "dispatch_leased",
        {"dispatch_id": "early", "work_item_id": selected.expected_work_item_id},
        occurred_at=outer.manifest.created_at,
    )

    with pytest.raises(Exception, match="precede|dispatch"):
        initialize_protocol_26_run(context)
