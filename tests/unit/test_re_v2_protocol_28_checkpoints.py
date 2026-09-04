from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_28.checkpoints import (
    CheckpointManifestV2,
    L4CheckpointExpectationV1,
    Protocol28CheckpointError,
)
from harness.re_v2.protocol_28.checkpoint_cache import (
    CheckpointCacheIndexV2,
    CheckpointCachePathsV2,
    copy_selected_checkpoint_objects,
    load_checkpoint_cache_v2,
    publish_checkpoint_cache_v2,
    select_checkpoints_v2,
)
from harness.re_v2.protocol_28.execution import certify_and_accept
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from tests.re_v2_protocol_28_fixtures import digest
from tests.unit.test_re_v2_protocol_28_ledger import _captures, _pass_verification


def _checkpoint(
    tmp_path: Path,
    *,
    origin: str = "re-origin",
    noncanonical_provider_json: bool = False,
):  # type: ignore[no-untyped-def]
    tmp_path.mkdir(parents=True, exist_ok=True)
    entry, spec, evidence, candidate, store, ledger, producer, verifier = _captures(
        tmp_path,
        noncanonical_provider_json=noncanonical_provider_json,
    )
    policy = build_initial_exhaustive_policy()
    artifact_policy_catalog_id = store.put_blob(b"artifact-policy-catalog")
    verification = _pass_verification(entry, spec, candidate)
    accepted = certify_and_accept(
        store,
        ledger,
        spec,
        entry,
        evidence,
        policy,
        candidate,
        verification,
        producer,
        verifier,
    )
    view = ledger.replay()
    certification = view.certifications[accepted.certification_receipt_hash]
    acceptance = view.acceptances[accepted.output_artifact_key_id]
    typed = (
        spec,
        entry,
        policy,
        candidate,
        verification,
        certification,
        acceptance,
        accepted,
    )
    for value in typed:
        store.put_blob(canonical_json_bytes(value.to_json_dict()))
    required = tuple(
        sorted(
            {value.identity for value in typed}
            | {
                producer.envelope.identity,
                producer.capture.identity,
                producer.capture.raw_result_hash,
                verifier.envelope.identity,
                verifier.capture.identity,
                verifier.capture.raw_result_hash,
                artifact_policy_catalog_id,
            }
        )
    )
    objects = {object_id: store.read_blob(object_id) for object_id in required}
    manifest = CheckpointManifestV2(
        2,
        origin,
        digest(f"{origin}:manifest"),
        digest(f"{origin}:event-prefix"),
        digest(f"{origin}:ledger-prefix"),
        spec,
        entry,
        policy.identity,
        artifact_policy_catalog_id,
        accepted,
        candidate,
        verification,
        certification,
        acceptance,
        required,
        {key: len(value) for key, value in objects.items()},
        (1,),
    )
    expectation = L4CheckpointExpectationV1(
        1,
        spec,
        entry,
        policy.identity,
        artifact_policy_catalog_id,
    )
    return manifest, expectation, objects, store


@pytest.mark.unit
def test_checkpoint_v2_round_trips_exact_slice_local_authority(tmp_path: Path) -> None:
    manifest, expectation, _objects, _store = _checkpoint(tmp_path)

    decoded = CheckpointManifestV2.from_json_dict(manifest.to_json_dict())

    assert decoded == manifest
    assert decoded.compatibility_id == expectation.compatibility_id
    assert (
        decoded.accepted_slice.output_artifact_key_id
        == expectation.output_artifact_key_id
    )


@pytest.mark.unit
def test_checkpoint_authenticates_noncanonical_raw_provider_json(
    tmp_path: Path,
) -> None:
    manifest, expectation, objects, _store = _checkpoint(
        tmp_path,
        noncanonical_provider_json=True,
    )

    selected = select_checkpoints_v2(
        (expectation,),
        (manifest,),
        {manifest.identity: objects},
    )

    assert len(selected.selected) == 1
    assert selected.rejected == ()


@pytest.mark.unit
def test_checkpoint_v2_rejects_cross_bound_verifier_or_missing_object(
    tmp_path: Path,
) -> None:
    manifest, _expectation, _objects, _store = _checkpoint(tmp_path)

    with pytest.raises(Protocol28CheckpointError, match="verifier"):
        replace(
            manifest,
            verification=replace(
                manifest.verification,
                verifier_policy_id=digest("changed-verifier"),
            ),
        )
    with pytest.raises(Protocol28CheckpointError, match="inventory"):
        replace(
            manifest,
            immutable_object_hashes=manifest.immutable_object_hashes[1:],
            immutable_object_byte_counts={
                key: value
                for key, value in manifest.immutable_object_byte_counts.items()
                if key in manifest.immutable_object_hashes[1:]
            },
        )


@pytest.mark.unit
def test_selection_ignores_unrelated_global_identity_but_rejects_local_change(
    tmp_path: Path,
) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)
    sibling = replace(
        manifest,
        origin_run_id="re-other",
        origin_manifest_hash=digest("unrelated-global-manifest"),
        origin_event_prefix_hash=digest("unrelated-global-event"),
        origin_ledger_prefix_hash=digest("unrelated-global-ledger"),
    )

    selected = select_checkpoints_v2(
        (expectation,), (sibling,), {sibling.identity: objects}
    )
    changed = replace(
        expectation,
        exhaustive_policy_id=digest("changed-policy"),
    )
    rejected = select_checkpoints_v2(
        (changed,), (sibling,), {sibling.identity: objects}
    )

    assert selected.selected[0].checkpoint_manifest_id == sibling.identity
    assert rejected.selected == ()
    assert rejected.rejected[0].reason == "checkpoint_incompatible"


@pytest.mark.unit
def test_selection_expansion_adopts_old_slice_and_leaves_new_slice_missing(
    tmp_path: Path,
) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)
    new_expectation = replace(
        expectation,
        slice_spec=replace(
            expectation.slice_spec,
            output_artifact_key_id=digest("new-output-key"),
        ),
    )

    bundle = select_checkpoints_v2(
        tuple(
            sorted(
                (expectation, new_expectation),
                key=lambda item: item.output_artifact_key_id,
            )
        ),
        (manifest,),
        {manifest.identity: objects},
    )

    assert len(bundle.selected) == 1
    assert bundle.missing_output_artifact_key_ids == (
        new_expectation.output_artifact_key_id,
    )


@pytest.mark.unit
def test_selected_checkpoint_is_copied_child_local_before_origin_deletion(
    tmp_path: Path,
) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path / "origin")
    bundle = select_checkpoints_v2(
        (expectation,), (manifest,), {manifest.identity: objects}
    )
    child = tmp_path / "child-objects"
    child.parent.mkdir(parents=True, exist_ok=True)

    copied = copy_selected_checkpoint_objects(
        bundle,
        {manifest.identity: manifest},
        {manifest.identity: objects},
        child,
    )

    assert copied == manifest.immutable_object_hashes
    for object_id in copied:
        suffix = object_id.removeprefix("sha256:")
        assert (child / "sha256" / suffix[:2] / suffix[2:]).is_file()


@pytest.mark.unit
def test_checkpoint_v2_paths_are_physically_separate(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = CheckpointCachePathsV2.for_workspace(workspace)

    assert paths.index.name == "index-v2.json"
    assert paths.manifests.name == "manifests-v2"
    assert paths.quarantine.name == "quarantine-v2.json"


@pytest.mark.unit
def test_selection_quarantines_missing_or_changed_object(tmp_path: Path) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)
    missing = dict(objects)
    missing.pop(next(iter(missing)))

    result = select_checkpoints_v2(
        (expectation,), (manifest,), {manifest.identity: missing}
    )

    assert result.selected == ()
    assert result.quarantined[0].reason == "checkpoint_object_inventory_mismatch"
    assert result.missing_output_artifact_key_ids == (
        expectation.output_artifact_key_id,
    )


@pytest.mark.unit
def test_selection_quarantines_incomplete_execution_authority(tmp_path: Path) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)
    capture_payload = objects[manifest.accepted_slice.producer_execution_capture_hash]
    capture = json.loads(capture_payload)
    envelope_id = capture["execution_envelope_id"]
    reduced_objects = {
        key: value for key, value in objects.items() if key != envelope_id
    }
    reduced = replace(
        manifest,
        immutable_object_hashes=tuple(sorted(reduced_objects)),
        immutable_object_byte_counts={
            key: len(value) for key, value in reduced_objects.items()
        },
    )

    result = select_checkpoints_v2(
        (expectation,), (reduced,), {reduced.identity: reduced_objects}
    )

    assert result.selected == ()
    assert result.quarantined[0].reason == "checkpoint_execution_authority_incomplete"


@pytest.mark.unit
def test_changed_target_evidence_projection_invalidates_checkpoint(
    tmp_path: Path,
) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)
    changed_entry = replace(
        expectation.plan_entry,
        target_evidence_projection_id=digest("changed-target-evidence"),
    )
    changed_expectation = replace(
        expectation,
        plan_entry=changed_entry,
        slice_spec=replace(
            expectation.slice_spec,
            plan_entry_id=changed_entry.identity,
        ),
    )

    result = select_checkpoints_v2(
        (changed_expectation,), (manifest,), {manifest.identity: objects}
    )

    assert result.selected == ()
    assert result.rejected[0].reason == "checkpoint_incompatible"


@pytest.mark.unit
def test_direct_parent_authority_prevents_checkpoint_downgrade(tmp_path: Path) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path)

    result = select_checkpoints_v2(
        (expectation,),
        (manifest,),
        {manifest.identity: objects},
        direct_parent_output_artifact_key_ids=(expectation.output_artifact_key_id,),
    )

    assert result.selected == ()
    assert result.missing_output_artifact_key_ids == ()
    assert result.rejected[0].reason == "direct_parent_precedence"


@pytest.mark.unit
def test_v2_cache_publishes_manifest_last_without_touching_v1(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest, _expectation, _objects, _store = _checkpoint(tmp_path / "origin")
    cache_root = workspace / ".echelon" / "re-v2" / "checkpoints"
    cache_root.mkdir(parents=True)
    v1_index = cache_root / "index-v1.json"
    v1_index.write_bytes(b"v1-frozen\n")

    published = publish_checkpoint_cache_v2(workspace, (manifest,), ())
    loaded_index, loaded_manifests, quarantine = load_checkpoint_cache_v2(workspace)

    assert published == CheckpointCacheIndexV2.from_json_dict(published.to_json_dict())
    assert loaded_index == published
    assert loaded_manifests == {manifest.identity: manifest}
    assert quarantine == ()
    assert v1_index.read_bytes() == b"v1-frozen\n"


@pytest.mark.unit
def test_child_copy_survives_origin_and_cache_deletion(tmp_path: Path) -> None:
    manifest, expectation, objects, _store = _checkpoint(tmp_path / "origin")
    bundle = select_checkpoints_v2(
        (expectation,), (manifest,), {manifest.identity: objects}
    )
    child = tmp_path / "child" / "objects"
    child.parent.mkdir(parents=True)
    copied = copy_selected_checkpoint_objects(
        bundle,
        {manifest.identity: manifest},
        {manifest.identity: objects},
        child,
    )

    for payload in objects.values():
        assert payload
    for path in (tmp_path / "origin").rglob("*"):
        if path.is_file():
            path.unlink()

    child_store = ObjectStore(child)
    assert all(child_store.read_blob(object_id) for object_id in copied)
