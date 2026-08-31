from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_28.authority import ParentAuthorityBundleV3
from harness.re_v2.protocol_28.closure import (
    complete_l4_closure_successor,
    create_or_reuse_l4_closure_successor,
)
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.inputs import Protocol28ClosureInputs
from tests.unit.test_re_v2_protocol_28_inputs import _closure_fixture


def _complete_closure_fixture(run_id: str = "re-l4-closure-live"):
    manifest, inputs = _closure_fixture(run_id)
    finding_ids = manifest.closure_request.unresolved_finding_ids
    parent = ParentAuthorityBundleV3(
        3,
        manifest.source_snapshot_id,
        manifest.partition_manifest_id,
        manifest.selection.identity,
        content_digest(b"workspace-partition"),
        content_digest(b"artifact-policy"),
        (content_digest(b"lower-root"),),
        manifest.lineage.l3_run_id,
        manifest.lineage.l3_manifest_hash,
        manifest.lineage.l3_terminal_event_hash,
        manifest.closure_request.frozen_epoch_id,
        content_digest(b"projection-catalog"),
        inputs.closure_parent_bundle.assigned_target_projection_ids,
        (content_digest(b"epoch-membership"),),
        finding_ids,
        (),
    )
    run_root = replace(
        inputs.l4_run_root,
        parent_authority_bundle_id=parent.identity,
    )
    closure_parent = replace(
        inputs.closure_parent_bundle,
        l4_run_root_id=run_root.identity,
        immutable_object_ids=tuple(
            sorted(
                {*inputs.closure_parent_bundle.immutable_object_ids, parent.identity}
            )
        ),
    )
    request = replace(
        manifest.closure_request,
        l4_run_root_id=run_root.identity,
    )
    manifest = replace(
        manifest,
        closure_parent_bundle_id=closure_parent.identity,
        closure_request=request,
        l4_run_root_id=run_root.identity,
    )
    authority_objects = {
        **dict(inputs.authority_objects),
        parent.identity: canonical_json_bytes(parent.to_json_dict()),
    }
    return Protocol28ClosureInputs(
        manifest,
        closure_parent,
        run_root,
        inputs.target_roots,
        inputs.accepted_slices,
        inputs.verification_receipts,
        inputs.closure_policy_bytes,
        authority_objects,
    )


@pytest.mark.unit
def test_closure_successor_completes_and_replays_without_provider_seam(
    tmp_path: Path,
) -> None:
    inputs = _complete_closure_fixture()

    first = create_or_reuse_l4_closure_successor(tmp_path, inputs)
    before = (first / "v2" / "events.jsonl").read_bytes()
    second = create_or_reuse_l4_closure_successor(tmp_path, inputs)
    after = (first / "v2" / "events.jsonl").read_bytes()

    assert second == first
    assert after == before
    state = replay_protocol_28(load_protocol_28_run_context(first).events.replay())
    assert state.lifecycle_state == "complete"
    assert state.closure_root_id is not None
    assert (first / "re" / "l4" / "materialization.json").is_file()
    assert (first / "re" / "l4" / "roots" / "closure.json").is_file()
    assert not any(
        "dispatch" in event.type
        for event in load_protocol_28_run_context(first).events.replay()
    )


@pytest.mark.unit
def test_closure_completion_blocks_when_parent_authority_is_missing(
    tmp_path: Path,
) -> None:
    inputs = _complete_closure_fixture("re-l4-closure-missing-parent")
    with pytest.raises(Exception, match="missing"):
        replace(
            inputs,
            authority_objects={
                key: value
                for key, value in inputs.authority_objects.items()
                if key != inputs.l4_run_root.parent_authority_bundle_id
            },
        )


@pytest.mark.unit
def test_explicit_closure_continue_is_idempotent(tmp_path: Path) -> None:
    inputs = _complete_closure_fixture("re-l4-closure-continue")
    run_dir = create_or_reuse_l4_closure_successor(tmp_path, inputs)
    first = complete_l4_closure_successor(run_dir)
    second = complete_l4_closure_successor(run_dir)

    assert second == first
