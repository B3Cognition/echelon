from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.controller import Protocol28Controller
from harness.re_v2.protocol_28.events import PROTOCOL_28_EVENTS
from harness.re_v2.protocol_28.graph import L4RunRootV1
from tests.re_v2_protocol_28_fixtures import digest


NOW = "2026-08-31T12:00:00Z"


def _controller(
    tmp_path: Path,
    *,
    fault=None,  # type: ignore[no-untyped-def]
) -> Protocol28Controller:
    store = ObjectStore(tmp_path / "objects")
    events = EventStore(tmp_path / "events.jsonl", protocol=PROTOCOL_28_EVENTS)
    return Protocol28Controller(
        events,
        store,
        tmp_path / "projection.json",
        clock=lambda: NOW,
        fault=fault,
    )


def _bootstrap(controller: Protocol28Controller) -> None:
    controller.append_once("l4_run_created", {"run_manifest_id": digest("manifest")})
    controller.append_once(
        "l4_inputs_staged",
        {
            "coverage_proof_id": digest("coverage"),
            "exhaustive_plan_id": digest("plan"),
            "parent_authority_bundle_id": digest("parent"),
            "snapshot_evidence_catalog_id": digest("evidence"),
            "target_projection_catalog_id": digest("projections"),
        },
    )
    controller.append_once(
        "l4_activated",
        {"activation_id": digest("activation"), "planned_entry_ids": []},
    )


def _run_root() -> L4RunRootV1:
    return L4RunRootV1(
        1,
        digest("snapshot"),
        digest("partition"),
        digest("selection"),
        digest("parent"),
        digest("plan"),
        digest("policy"),
        (),
        (),
        (),
        "selected-scope",
        "complete",
    )


@pytest.mark.unit
def test_controller_append_is_idempotent_and_projection_is_rebuildable(
    tmp_path: Path,
) -> None:
    controller = _controller(tmp_path)
    _bootstrap(controller)
    before_events = controller.event_store.path.read_bytes()
    before_projection = controller.projection_path.read_bytes()

    controller.append_once(
        "l4_activated",
        {"activation_id": digest("activation"), "planned_entry_ids": []},
    )
    controller.projection_path.unlink()
    rebuilt = controller.rebuild_projection()

    assert controller.event_store.path.read_bytes() == before_events
    assert controller.projection_path.read_bytes() == before_projection
    assert rebuilt.lifecycle_state == "active"


@pytest.mark.unit
def test_root_bytes_are_durable_before_root_event(tmp_path: Path) -> None:
    seams: list[str] = []

    def fault(name: str) -> None:
        seams.append(name)
        if name == "after_root_object":
            raise RuntimeError("crash")

    controller = _controller(tmp_path, fault=fault)
    _bootstrap(controller)
    root = _run_root()

    with pytest.raises(RuntimeError, match="crash"):
        controller.record_root(root, root_kind="run")

    assert controller.object_store.read_blob(root.identity)
    assert all(
        event.type != "root_recorded" for event in controller.event_store.replay()
    )
    assert seams[-1] == "after_root_object"


@pytest.mark.unit
def test_root_event_precedes_materialization_and_completion(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    _bootstrap(controller)
    root = _run_root()

    controller.record_root(root, root_kind="run")
    projection = controller.rebuild_projection()
    assert projection.lifecycle_state == "evidence_complete"
    controller.record_materialization(root.identity)
    controller.complete_run(root.identity, closure_required=False)

    projection = controller.rebuild_projection()
    assert projection.lifecycle_state == "complete"
    assert projection.materialized_root_ids == (root.identity,)


@pytest.mark.unit
def test_closure_successor_link_is_idempotent_and_provider_free(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    _bootstrap(controller)
    root = _run_root()
    controller.record_root(root, root_kind="run")
    before = len(controller.event_store.replay())

    first = controller.link_closure_successor(
        "re-l4-closure", digest("closure-manifest"), root.identity
    )
    second = controller.link_closure_successor(
        "re-l4-closure", digest("closure-manifest"), root.identity
    )

    assert first == second
    assert len(controller.event_store.replay()) == before + 1
