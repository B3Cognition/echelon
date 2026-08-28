from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from tests.unit.test_re_v2_protocol_27_inputs import _input_set
from tests.unit.test_re_v2_protocol_27_runtime import _runtime_case
from tests.unit.test_re_v2_protocol_27_runtime import _candidate


NOW = "2026-08-29T10:00:00Z"


def _record_nonterminal_origin(tmp_path: Path):
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    inputs, item, context, candidate, runtime = _runtime_case(tmp_path)
    result = runtime.certify_candidate(
        item,
        context,
        canonical_json_bytes(candidate.to_json_dict()),
    )
    ledger = Protocol27Ledger(inputs)
    ledger.record_candidate_assessment(result.assessment)
    ledger.record_synthesis_certification(result.certification)
    ledger.record_synthesis_acceptance(result.acceptance)
    events = EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS)
    events.append(
        "run_created",
        {"run_manifest_id": inputs.manifest.run_manifest_id},
        occurred_at=NOW,
    )
    events.append(
        "synthesis_request_frozen",
        {"request_id": inputs.manifest.request_id},
        occurred_at=NOW,
    )
    for receipt in inputs.manifest.partial_acceptances:
        events.append(
            "partial_source_accepted",
            {
                "receipt_id": receipt.receipt_id,
                "request_id": receipt.operation_id,
                "source_id": receipt.source_id,
            },
            occurred_at=NOW,
        )
    events.append(
        "work_planned",
        {"work_item_ids": [item.work_item_id]},
        occurred_at=NOW,
    )
    events.append(
        "dispatch_started",
        {
            "active_ms_reservation": 100,
            "attempt_index": 1,
            "attempt_kind": "initial_generation",
            "billable_token_reservation": 1000,
            "dispatch_id": "dispatch-1",
            "execution_input_hash": content_digest(b"execution"),
            "executor_contract_hash": item.executor_contract_hash,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    capture = content_digest(b"capture")
    events.append(
        "dispatch_observed",
        {
            "active_usage_status": "trusted_exact",
            "dispatch_id": "dispatch-1",
            "execution_capture_hash": capture,
            "observed_active_ms": 10,
            "raw_result_contract_status": "valid",
            "reported_token_usage": 10,
            "token_usage_status": "trusted_exact",
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    events.append(
        "candidate_persisted",
        {
            "candidate_id": result.assessment.candidate_hash,
            "candidate_inventory_hash": content_digest(b"inventory"),
            "dispatch_id": "dispatch-1",
            "execution_capture_hash": capture,
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    events.append(
        "synthesis_candidate_certified",
        {
            "artifact_hash": result.acceptance.artifact_hash,
            "artifact_key_id": result.acceptance.artifact_key.artifact_key_id,
            "candidate_assessment_id": result.assessment.identity,
            "candidate_id": result.assessment.candidate_hash,
            "certification_id": result.certification.identity,
            "generated_dependency_key_ids": [],
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    events.append(
        "synthesis_artifact_accepted",
        {
            "acceptance_receipt_id": result.acceptance.identity,
            "adopted": False,
            "artifact_hash": result.acceptance.artifact_hash,
            "artifact_key_id": result.acceptance.artifact_key.artifact_key_id,
            "certification_id": result.certification.identity,
            "generated_dependency_key_ids": [],
            "work_item_id": item.work_item_id,
        },
        occurred_at=NOW,
    )
    return inputs, item, result


def _record_chain_origin(tmp_path: Path):
    from harness.re_v2.protocol_27.context import build_synthesis_context
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger
    from harness.re_v2.protocol_27.runtime import Protocol27DeterministicRuntime
    from tests.unit.test_re_v2_protocol_27_context import _validated_inputs

    inputs = _validated_inputs(tmp_path)
    runtime = Protocol27DeterministicRuntime(ObjectStore(inputs.paths.objects))
    accepted_nodes: dict[str, str] = {}
    results = []
    for kind in ("source-architecture", "source-components", "source-contracts"):
        item = next(
            value
            for value in inputs.graph.ready_work_items(accepted_nodes)
            if value.output_key.scope.source_id == "api"
            and value.output_key.artifact_kind == kind
        )
        context = build_synthesis_context(inputs, item)
        candidate = _candidate(
            kind=kind,
            source_id="api",
            input_quality=context.input_quality,
            debt_refs=context.debt_refs,
            authority_id=context.dependency_artifacts[0].artifact_hash,
        )
        result = runtime.certify_candidate(
            item, context, canonical_json_bytes(candidate.to_json_dict())
        )
        accepted_nodes[inputs.graph.node_for_work_item(item).node_id] = result.acceptance.artifact_hash
        results.append((item, result))
    item = next(
        value
        for value in inputs.graph.ready_work_items(accepted_nodes)
        if value.output_key.scope.kind == "workspace-domain"
        and value.output_key.artifact_kind == "workspace-domain-summary"
        and set(
            inputs.graph.node_for_work_item(value).generated_dependency_node_ids
        )
        == set(accepted_nodes)
    )
    context = build_synthesis_context(inputs, item)
    candidate = _candidate(
        kind="workspace-domain-summary",
        source_id="api",
        input_quality=context.input_quality,
        debt_refs=context.debt_refs,
        authority_id=context.dependency_artifacts[0].artifact_hash,
    )
    candidate = replace(candidate, scope=item.output_key.scope)
    result = runtime.certify_candidate(
        item, context, canonical_json_bytes(candidate.to_json_dict())
    )
    results.append((item, result))

    ledger = Protocol27Ledger(inputs)
    for _item, value in results:
        ledger.record_candidate_assessment(value.assessment)
        ledger.record_synthesis_certification(value.certification)
        ledger.record_synthesis_acceptance(value.acceptance)
    events = EventStore(inputs.paths, protocol=PROTOCOL_27_EVENTS)
    events.append("run_created", {"run_manifest_id": inputs.manifest.run_manifest_id}, occurred_at=NOW)
    events.append("synthesis_request_frozen", {"request_id": inputs.manifest.request_id}, occurred_at=NOW)
    for receipt in inputs.manifest.partial_acceptances:
        events.append(
            "partial_source_accepted",
            {"receipt_id": receipt.receipt_id, "request_id": receipt.operation_id, "source_id": receipt.source_id},
            occurred_at=NOW,
        )
    events.append(
        "work_planned",
        {"work_item_ids": sorted(item.work_item_id for item, _result in results)},
        occurred_at=NOW,
    )
    accepted_keys: set[str] = set()
    fixed_keys = {item.identity for item in inputs.source_overview_catalog.projections}
    for index, (work_item, value) in enumerate(results, 1):
        dispatch_id = f"dispatch-{index}"
        capture = content_digest(f"capture-{index}".encode())
        generated = sorted(set(work_item.dependency_key_ids) - fixed_keys)
        events.append(
            "dispatch_started",
            {
                "active_ms_reservation": 100,
                "attempt_index": 1,
                "attempt_kind": "initial_generation",
                "billable_token_reservation": 1000,
                "dispatch_id": dispatch_id,
                "execution_input_hash": content_digest(f"execution-{index}".encode()),
                "executor_contract_hash": work_item.executor_contract_hash,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=NOW,
        )
        events.append(
            "dispatch_observed",
            {
                "active_usage_status": "trusted_exact",
                "dispatch_id": dispatch_id,
                "execution_capture_hash": capture,
                "observed_active_ms": 10,
                "raw_result_contract_status": "valid",
                "reported_token_usage": 10,
                "token_usage_status": "trusted_exact",
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=NOW,
        )
        events.append(
            "candidate_persisted",
            {
                "candidate_id": value.assessment.candidate_hash,
                "candidate_inventory_hash": content_digest(f"inventory-{index}".encode()),
                "dispatch_id": dispatch_id,
                "execution_capture_hash": capture,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=NOW,
        )
        assert set(generated) <= accepted_keys
        events.append(
            "synthesis_candidate_certified",
            {
                "artifact_hash": value.acceptance.artifact_hash,
                "artifact_key_id": value.acceptance.artifact_key.artifact_key_id,
                "candidate_assessment_id": value.assessment.identity,
                "candidate_id": value.assessment.candidate_hash,
                "certification_id": value.certification.identity,
                "generated_dependency_key_ids": generated,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=NOW,
        )
        events.append(
            "synthesis_artifact_accepted",
            {
                "acceptance_receipt_id": value.acceptance.identity,
                "adopted": False,
                "artifact_hash": value.acceptance.artifact_hash,
                "artifact_key_id": value.acceptance.artifact_key.artifact_key_id,
                "certification_id": value.certification.identity,
                "generated_dependency_key_ids": generated,
                "work_item_id": work_item.work_item_id,
            },
            occurred_at=NOW,
        )
        accepted_keys.add(value.acceptance.artifact_key.artifact_key_id)
    return inputs, results


@pytest.mark.unit
def test_nonterminal_origin_artifact_is_immediately_eligible(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.checkpoints import reconstruct_synthesis_checkpoints

    inputs, _item, _result = _record_nonterminal_origin(tmp_path)

    inventory = reconstruct_synthesis_checkpoints(tmp_path)

    manifests = inventory.by_origin[inputs.manifest.run_id]
    assert len(manifests) == 1
    assert manifests[0].artifact_kind == "source-contracts"
    assert manifests[0].identity in inventory.authority_objects


@pytest.mark.unit
def test_selection_prefers_direct_parent_and_stages_exact_closure(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.checkpoints import (
        SynthesisCheckpointInventoryV1,
        reconstruct_synthesis_checkpoints,
        select_synthesis_checkpoints,
        stage_synthesis_checkpoint_selection,
    )

    inputs, _item, _result = _record_nonterminal_origin(tmp_path)
    inventory = reconstruct_synthesis_checkpoints(tmp_path)
    direct = inventory.only_origin(inputs.manifest.run_id)

    selection = select_synthesis_checkpoints(inputs.graph, direct, inventory)
    copied = stage_synthesis_checkpoint_selection(tmp_path / "unpublished", selection)

    assert selection.entries[0].source_kind == "direct_parent"
    assert selection.entries[0].artifact_kind == "source-contracts"
    assert set(copied) == set(selection.copied_object_ids)
    assert all(content_digest(payload) == object_id for object_id, payload in copied.items())


@pytest.mark.unit
def test_selection_builds_maximal_dependency_ordered_closure(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.checkpoints import (
        SynthesisCheckpointInventoryV1,
        reconstruct_synthesis_checkpoints,
        select_synthesis_checkpoints,
    )

    inputs, results = _record_chain_origin(tmp_path)
    inventory = reconstruct_synthesis_checkpoints(tmp_path)
    selection = select_synthesis_checkpoints(
        inputs.graph,
        SynthesisCheckpointInventoryV1.empty(),
        inventory,
    )

    assert len(selection.entries) == len(results) == 4
    assert selection.entries[-1].artifact_kind == "workspace-domain-summary"
    assert set(selection.entries[-1].dependency_artifact_key_ids) == {
        entry.artifact_key_id for entry in selection.entries[:-1]
    }


@pytest.mark.unit
def test_frozen_child_is_origin_independent_and_corruption_is_terminal(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.checkpoints import (
        Protocol27CheckpointError,
        reconstruct_synthesis_checkpoints,
        select_synthesis_checkpoints,
        stage_synthesis_checkpoint_selection,
        adopt_synthesis_checkpoints,
    )
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    origin_inputs, _item, _result = _record_nonterminal_origin(tmp_path)
    inventory = reconstruct_synthesis_checkpoints(tmp_path)
    selection = select_synthesis_checkpoints(
        origin_inputs.graph,
        inventory.only_origin(origin_inputs.manifest.run_id),
        inventory,
    )
    checkpoint_objects = stage_synthesis_checkpoint_selection(
        tmp_path / "unpublished",
        selection,
    )
    child_dir = tmp_path / "runs" / "re-checkpoint-child"
    supplied = _input_set(child_dir.name)
    supplied = replace(
        supplied,
        checkpoint_selection_bytes=canonical_json_bytes(selection.to_json_dict()),
        checkpoint_objects=checkpoint_objects,
    )
    create_protocol_27_run_store(child_dir, supplied)
    loaded = load_protocol_27_inputs(child_dir)
    events = EventStore(loaded.paths, protocol=PROTOCOL_27_EVENTS)
    events.append(
        "run_created",
        {"run_manifest_id": loaded.manifest.run_manifest_id},
        occurred_at=NOW,
    )
    events.append(
        "synthesis_request_frozen",
        {"request_id": loaded.manifest.request_id},
        occurred_at=NOW,
    )
    for receipt in loaded.manifest.partial_acceptances:
        events.append(
            "partial_source_accepted",
            {
                "receipt_id": receipt.receipt_id,
                "request_id": receipt.operation_id,
                "source_id": receipt.source_id,
            },
            occurred_at=NOW,
        )
    events.append(
        "work_planned",
        {"work_item_ids": [entry.work_item_id for entry in selection.entries]},
        occurred_at=NOW,
    )
    report = adopt_synthesis_checkpoints(loaded)
    assert report.work_item_ids == tuple(entry.work_item_id for entry in selection.entries)
    from harness.re_v2.protocol_27.budget import evaluate_synthesis_budget
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    decision = evaluate_synthesis_budget(
        loaded.manifest,
        events.replay(),
        Protocol27Ledger(loaded).replay(),
    )
    assert decision.provider_attempts == 0
    assert decision.charged_tokens == 0
    event_bytes = loaded.paths.events.read_bytes()
    assert adopt_synthesis_checkpoints(loaded) == report
    assert loaded.paths.events.read_bytes() == event_bytes

    # The adopted child replays without its origin or any workspace cache.
    origin_dir = origin_inputs.paths.root.parent
    renamed = tmp_path / "detached-origin"
    origin_dir.rename(renamed)
    reloaded = load_protocol_27_inputs(child_dir)
    assert reloaded.checkpoint_selection == selection
    exported = reconstruct_synthesis_checkpoints(tmp_path)
    assert exported.by_origin[child_dir.name][0].artifact_hash == selection.entries[0].artifact_hash

    # A selected immutable object changing after freeze is terminal; generation
    # is not a permitted fallback for the now-frozen work item.
    object_id = selection.entries[0].checkpoint_manifest_id
    suffix = object_id.removeprefix("sha256:")
    object_path = child_dir / "v2" / "objects" / "sha256" / suffix[:2] / suffix[2:]
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt")
    with pytest.raises(Protocol27CheckpointError, match="post-freeze"):
        adopt_synthesis_checkpoints(reloaded)


@pytest.mark.unit
def test_adoption_recovers_after_checkpoint_event_before_acceptance_event(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.checkpoints import (
        adopt_synthesis_checkpoints,
        reconstruct_synthesis_checkpoints,
        select_synthesis_checkpoints,
        stage_synthesis_checkpoint_selection,
    )
    from harness.re_v2.protocol_27.events import PROTOCOL_27_EVENTS
    from harness.re_v2.protocol_27.inputs import create_protocol_27_run_store, load_protocol_27_inputs
    from harness.re_v2.protocol_27.ledger import Protocol27Ledger

    origin, _item, _result = _record_nonterminal_origin(tmp_path)
    inventory = reconstruct_synthesis_checkpoints(tmp_path)
    selection = select_synthesis_checkpoints(
        origin.graph,
        inventory.only_origin(origin.manifest.run_id),
        inventory,
    )
    child_dir = tmp_path / "runs" / "re-crash-child"
    supplied = replace(
        _input_set(child_dir.name),
        checkpoint_selection_bytes=canonical_json_bytes(selection.to_json_dict()),
        checkpoint_objects=stage_synthesis_checkpoint_selection(
            tmp_path / "unpublished", selection
        ),
    )
    create_protocol_27_run_store(child_dir, supplied)
    loaded = load_protocol_27_inputs(child_dir)
    events = EventStore(loaded.paths, protocol=PROTOCOL_27_EVENTS)
    events.append("run_created", {"run_manifest_id": loaded.manifest.run_manifest_id}, occurred_at=NOW)
    events.append("synthesis_request_frozen", {"request_id": loaded.manifest.request_id}, occurred_at=NOW)
    for receipt in loaded.manifest.partial_acceptances:
        events.append(
            "partial_source_accepted",
            {"receipt_id": receipt.receipt_id, "request_id": receipt.operation_id, "source_id": receipt.source_id},
            occurred_at=NOW,
        )
    events.append(
        "work_planned",
        {"work_item_ids": [entry.work_item_id for entry in selection.entries]},
        occurred_at=NOW,
    )

    class _CrashBetweenEvents:
        def __init__(self, delegate):
            self.delegate = delegate
            self.failed = False

        def replay(self):
            return self.delegate.replay()

        def append(self, event_type, payload, *, occurred_at):
            if event_type == "synthesis_artifact_accepted" and not self.failed:
                self.failed = True
                raise RuntimeError("simulated event-boundary crash")
            return self.delegate.append(event_type, payload, occurred_at=occurred_at)

    ledger = Protocol27Ledger(loaded)
    with pytest.raises(RuntimeError, match="event-boundary"):
        adopt_synthesis_checkpoints(
            SimpleNamespace(
                inputs=loaded,
                ledger=ledger,
                event_store=_CrashBetweenEvents(events),
                clock=lambda: NOW,
            )
        )
    report = adopt_synthesis_checkpoints(
        SimpleNamespace(
            inputs=loaded,
            ledger=ledger,
            event_store=events,
            clock=lambda: NOW,
        )
    )
    assert report.work_item_ids == tuple(entry.work_item_id for entry in selection.entries)
    assert [event.type for event in events.replay()].count("checkpoint_adopted") == 1
    assert [event.type for event in events.replay()].count("synthesis_artifact_accepted") == 1
