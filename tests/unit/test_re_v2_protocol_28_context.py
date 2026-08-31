from __future__ import annotations

from pathlib import Path
import json
import shutil

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from harness.re_v2.protocol_28.budget import L4ResourceStore
from harness.re_v2.protocol_28.context import (
    build_protocol_28_slice_context,
    Protocol28RunContext,
    initialize_protocol_28_run,
    load_protocol_28_run_context,
)
from harness.re_v2.protocol_28.planning import realize_slice
from tests.unit.test_re_v2_protocol_28_artifacts import _candidate_fixture
from harness.re_v2.protocol_28.inputs import (
    publish_protocol_28_run,
    stage_exhaustive_inputs,
)
from tests.re_v2_protocol_28_fixtures import digest
from tests.unit.test_re_v2_protocol_28_inputs import _fixture


def _published(tmp_path: Path) -> Path:
    manifest, inputs = _fixture()
    stage = tmp_path / "runs" / ".re-l4.stage"
    final = tmp_path / "runs" / manifest.run_id
    stage_exhaustive_inputs(stage, inputs)
    publish_protocol_28_run(stage, final, manifest)
    return final


@pytest.mark.unit
def test_context_load_is_read_only_and_initialize_is_idempotent(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    context = load_protocol_28_run_context(run_dir)
    assert isinstance(context, Protocol28RunContext)
    assert context.events.replay() == ()

    initialize_protocol_28_run(context)
    first = context.events.path.read_bytes()
    initialize_protocol_28_run(load_protocol_28_run_context(run_dir))

    assert context.events.path.read_bytes() == first
    projection = context.controller.rebuild_projection()
    assert projection.lifecycle_state == "active"
    assert projection.planned_slice_count == sum(
        len(target.entries) for target in context.inputs.exhaustive_plan.target_plans
    )


@pytest.mark.unit
def test_resource_store_replays_exact_durable_prefix(tmp_path: Path) -> None:
    policy = _fixture()[0].budget_policy
    path = tmp_path / "resources.jsonl"
    store = L4ResourceStore(path, policy)
    producer = DispatchReservationV1(5, 10, 100)
    verifier = DispatchReservationV1(5, 10, 100)
    pair = store.commit_pair(
        store.preview_pair(digest("slice"), 1, producer, verifier),
        producer_dispatch_id="producer-1",
        verifier_dispatch_id="verifier-1",
    )
    store.observe(
        pair.producer_dispatch_id,
        token_status="trusted_exact",
        billable_tokens=7,
        active_status="trusted_exact",
        active_ms=50,
    )

    replayed = L4ResourceStore(path, policy)
    assert replayed.records == store.records
    assert replayed.decision.charged_tokens == 17
    assert replayed.decision.open_token_reservations == 10


@pytest.mark.unit
def test_resource_store_rejects_partial_or_noncanonical_tail(tmp_path: Path) -> None:
    policy = _fixture()[0].budget_policy
    path = tmp_path / "resources.jsonl"
    path.write_bytes(b'{"type":"abandonment"}')

    with pytest.raises(ValueError, match="partial final"):
        L4ResourceStore(path, policy)


@pytest.mark.unit
def test_slice_context_uses_only_staged_authority_after_sources_disappear(
    tmp_path: Path,
) -> None:
    run_dir = _published(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    context = load_protocol_28_run_context(run_dir)
    assert isinstance(context, Protocol28RunContext)
    target = context.inputs.exhaustive_plan.target_plans[0]
    entry = target.entries[0]
    spec = realize_slice(entry, {})
    shutil.rmtree(source)

    payload = build_protocol_28_slice_context(
        context, target, entry, spec, role="producer"
    )

    assert b'"role":"producer"' in payload
    assert entry.identity.encode("ascii") in payload
    assert len(payload) <= context.inputs.exhaustive_policy.max_context_bytes


@pytest.mark.unit
def test_slice_context_supplies_exact_copyable_anchor_ids(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    context = load_protocol_28_run_context(run_dir)
    assert isinstance(context, Protocol28RunContext)
    target = context.inputs.exhaustive_plan.target_plans[0]
    entry = target.entries[0]
    spec = realize_slice(entry, {})

    payload = json.loads(
        build_protocol_28_slice_context(
            context, target, entry, spec, role="producer"
        )
    )

    anchors = payload["permitted_evidence_anchors"]
    assert anchors
    assert all(
        item["anchor_id"] == content_digest(item["anchor"])
        for item in anchors
    )
    assert {
        item["anchor"]["evidence_id"] for item in anchors
    } == set(entry.primary_snapshot_evidence_ids + entry.supporting_snapshot_evidence_ids)


@pytest.mark.unit
def test_verifier_context_is_fresh_and_binds_candidate(tmp_path: Path) -> None:
    run_dir = _published(tmp_path)
    context = load_protocol_28_run_context(run_dir)
    assert isinstance(context, Protocol28RunContext)
    entry, spec, _evidence, candidate = _candidate_fixture()
    target = next(
        item
        for item in context.inputs.exhaustive_plan.target_plans
        if entry.identity in {planned.identity for planned in item.entries}
    )

    producer = build_protocol_28_slice_context(
        context, target, entry, spec, role="producer"
    )
    verifier = build_protocol_28_slice_context(
        context,
        target,
        entry,
        spec,
        role="verifier",
        candidate=candidate,
    )

    assert producer != verifier
    assert candidate.identity.encode("ascii") in verifier
