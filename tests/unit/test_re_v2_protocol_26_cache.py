from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_26.cache import rebuild_checkpoint_cache
from harness.re_v2.protocol_26.model import CheckpointManifestV1
from tests.re_v2_protocol_26_fixtures import CheckpointWorkspace


@pytest.fixture
def checkpoint_workspace(tmp_path: Path) -> CheckpointWorkspace:
    return CheckpointWorkspace.create(tmp_path / "workspace")


def test_cache_rebuild_is_deterministic_and_disposable(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.origin_with_one_accepted_domain("active")

    first = rebuild_checkpoint_cache(checkpoint_workspace.root)
    shutil.rmtree(first.paths.root)
    second = rebuild_checkpoint_cache(checkpoint_workspace.root)

    assert second.index.identity == first.index.identity
    assert second.index.manifest_ids == first.index.manifest_ids


def test_malformed_cache_is_rebuilt_not_authorized(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.origin_with_one_accepted_domain("active")
    checkpoint_workspace.write_cache_index(b'{"selected":true}')

    generation = rebuild_checkpoint_cache(checkpoint_workspace.root)

    assert generation.index.manifest_ids == generation.reconstructed_manifest_ids
    assert generation.index.manifest_ids


def test_published_manifest_projection_is_canonical_and_revalidated(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.origin_with_one_accepted_domain("active")

    generation = rebuild_checkpoint_cache(checkpoint_workspace.root)

    manifest_id = generation.index.manifest_ids[0]
    projection = generation.paths.manifests / f"{manifest_id}.json"
    payload = projection.read_bytes()
    decoded = CheckpointManifestV1.from_json_dict(json.loads(payload))
    assert decoded.identity == manifest_id == content_digest(payload)
    assert generation.manifests[manifest_id] == decoded


def test_concurrent_rebuilds_publish_one_complete_generation(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    checkpoint_workspace.origin_with_one_accepted_domain("active")

    with ThreadPoolExecutor(max_workers=4) as executor:
        generations = tuple(
            executor.map(
                lambda _item: rebuild_checkpoint_cache(checkpoint_workspace.root),
                range(8),
            )
        )

    assert len({item.index.identity for item in generations}) == 1
    final = rebuild_checkpoint_cache(checkpoint_workspace.root)
    assert final.index.manifest_ids == final.reconstructed_manifest_ids
    assert all(
        (final.paths.manifests / f"{manifest_id}.json").is_file()
        for manifest_id in final.index.manifest_ids
    )


def test_symlinked_origin_is_quarantined_not_followed(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    linked = checkpoint_workspace.root / "runs" / "re-linked"
    linked.symlink_to(origin.run_dir, target_is_directory=True)

    generation = rebuild_checkpoint_cache(checkpoint_workspace.root)

    assert generation.index.manifest_ids
    assert any(
        item.origin_run_id == "re-linked"
        and item.reason == "checkpoint_manifest_invalid"
        for item in generation.quarantine
    )


def test_corrupt_origin_is_quarantined_and_cannot_be_authorized(
    checkpoint_workspace: CheckpointWorkspace,
) -> None:
    origin = checkpoint_workspace.origin_with_one_accepted_domain("active")
    first = rebuild_checkpoint_cache(checkpoint_workspace.root)
    artifact_hash = next(iter(first.manifests.values())).artifact_hash
    suffix = artifact_hash.removeprefix("sha256:")
    object_path = origin.run_dir / "v2" / "objects" / "sha256" / suffix[:2] / suffix[2:]
    object_path.chmod(0o600)
    object_path.write_bytes(b"corrupt")

    generation = rebuild_checkpoint_cache(checkpoint_workspace.root)

    assert generation.index.manifest_ids == ()
    assert generation.reconstructed_manifest_ids == ()
    assert generation.quarantine[0].reason == "checkpoint_object_hash_mismatch"
