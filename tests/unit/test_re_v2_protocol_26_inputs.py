from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.model import CatalogReferenceV1
from harness.re_v2.protocol_26.inputs import (
    Protocol26InputSet,
    Protocol26InputStoreError,
    create_protocol_26_run_store,
    load_protocol_26_inputs,
)
from harness.re_v2.protocol_26.model import LayerExecutionContractV1, RunManifestV5
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_26_fixtures import (
    checkpoint_manifest_v1,
    checkpoint_selection_bundle_v1,
)
from tests.unit.test_re_v2_protocol_22_inputs import _input_fixture


class InjectedFault(RuntimeError):
    pass


def _protocol26_input_fixture(target_layer: str = "L1") -> Protocol26InputSet:
    if target_layer == "L1":
        layer_inputs, inner = _input_fixture()
        inner = replace(inner, run_id="re-checkpoint-inputs-l1")
    elif target_layer == "L2":
        from tests.unit.test_re_v2_protocol_24_inputs import _fixture

        layer_inputs, inner = _fixture()
        inner = replace(inner, run_id="re-checkpoint-inputs-l2")
    else:
        from tests.unit.test_re_v2_protocol_25_inputs import _fixture

        layer_inputs, inner = _fixture()
        inner = replace(inner, run_id="re-checkpoint-inputs-l3")
    contract = LayerExecutionContractV1.from_layer_manifest(inner)
    checkpoint = checkpoint_manifest_v1()
    authority_objects = {
        checkpoint.origin_manifest_hash: b"re-origin:manifest",
        checkpoint.origin_event_prefix_hash: b"re-origin:accepted-artifact:event-prefix",
        checkpoint.origin_ledger_prefix_hash: b"re-origin:accepted-artifact:ledger-prefix",
        checkpoint.artifact_hash: b"accepted-artifact",
        checkpoint.work_item.work_item_id: canonical_json_bytes(
            checkpoint.work_item.to_json_dict()
        ),
        checkpoint.certification_receipt.identity: canonical_json_bytes(
            checkpoint.certification_receipt.to_json_dict()
        ),
        checkpoint.artifact_acceptance_receipt.identity: canonical_json_bytes(
            checkpoint.artifact_acceptance_receipt.to_json_dict()
        ),
    }
    assert {content_digest(payload) for payload in authority_objects.values()} == set(
        authority_objects
    )
    copied_bytes = sum(len(payload) for payload in authority_objects.values())
    base_selection = checkpoint_selection_bundle_v1()
    selection = replace(
        base_selection,
        source_snapshot_id=inner.source_snapshot_id,
        partition_manifest_id=inner.partition_manifest_id,
        target_layer=target_layer,
        target_selection_id=(
            inner.selection.identity
            if hasattr(inner, "selection")
            else base_selection.target_selection_id
        ),
        selected=(
            replace(
                base_selection.selected[0],
                copied_byte_count=copied_bytes,
            ),
        ),
        copied_byte_count=copied_bytes,
    )
    manifest = RunManifestV5(
        schema_version=5,
        engine="re-v2",
        engine_protocol_version="2.6",
        run_id=inner.run_id,
        created_at=inner.created_at,
        source_snapshot_id=inner.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=inner.partition_manifest_id,
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
    return Protocol26InputSet(
        manifest=manifest,
        layer_execution_contract=contract,
        layer_inputs=layer_inputs,
        checkpoint_selection=selection,
        authority_objects=authority_objects,
    )


@pytest.mark.unit
@pytest.mark.parametrize("target_layer", ("L1", "L2", "L3"))
def test_schema5_store_contains_every_selected_object_before_manifest(
    tmp_path: Path,
    target_layer: str,
) -> None:
    inputs = _protocol26_input_fixture(target_layer)
    seen: list[str] = []

    paths = create_protocol_26_run_store(
        tmp_path / "runs" / inputs.manifest.run_id,
        inputs.manifest,
        inputs,
        fault_hook=seen.append,
    )
    loaded = load_protocol_26_inputs(paths, inputs.manifest)
    objects = ObjectStore(paths.objects)

    assert loaded.checkpoint_selection == inputs.checkpoint_selection
    assert all(
        objects.verify(object_hash)
        for object_hash in loaded.checkpoint_selection.copied_object_ids
    )
    assert seen[-1] == "manifest_published"
    assert seen.index("before_manifest_publish") < seen.index("manifest_published")


@pytest.mark.unit
@pytest.mark.parametrize(
    "seam",
    (
        "catalogs_written",
        "authority_object_written",
        "selection_written",
        "before_manifest_publish",
    ),
)
def test_schema5_creation_is_retryable_at_every_prepublication_seam(
    tmp_path: Path,
    seam: str,
) -> None:
    inputs = _protocol26_input_fixture()
    run_dir = tmp_path / "runs" / inputs.manifest.run_id

    def fail_at(point: str) -> None:
        if point == seam:
            raise InjectedFault(point)

    with pytest.raises(InjectedFault, match=seam):
        create_protocol_26_run_store(
            run_dir,
            inputs.manifest,
            inputs,
            fault_hook=fail_at,
        )
    assert not ReV2Paths.for_run(run_dir).manifest.exists()

    paths = create_protocol_26_run_store(run_dir, inputs.manifest, inputs)

    assert load_protocol_26_inputs(paths, inputs.manifest).checkpoint_selection == (
        inputs.checkpoint_selection
    )


@pytest.mark.unit
def test_schema5_store_is_no_clobber(tmp_path: Path) -> None:
    inputs = _protocol26_input_fixture()
    run_dir = tmp_path / "runs" / inputs.manifest.run_id
    create_protocol_26_run_store(run_dir, inputs.manifest, inputs)

    with pytest.raises(Protocol26InputStoreError, match="already exists"):
        create_protocol_26_run_store(run_dir, inputs.manifest, inputs)


@pytest.mark.unit
def test_protocol26_input_set_rejects_missing_selected_object() -> None:
    inputs = _protocol26_input_fixture()
    missing = next(iter(inputs.authority_objects))

    with pytest.raises(Protocol26InputStoreError, match="selected object"):
        replace(
            inputs,
            authority_objects={
                key: payload
                for key, payload in inputs.authority_objects.items()
                if key != missing
            },
        )


@pytest.mark.unit
def test_loaded_child_does_not_require_origin_or_cache(tmp_path: Path) -> None:
    inputs = _protocol26_input_fixture()
    workspace = tmp_path / "workspace"
    origin = workspace / "runs" / "re-origin"
    cache = workspace / ".echelon" / "re-v2" / "checkpoints"
    origin.mkdir(parents=True)
    cache.mkdir(parents=True)
    run_dir = workspace / "runs" / inputs.manifest.run_id
    paths = create_protocol_26_run_store(run_dir, inputs.manifest, inputs)

    shutil.rmtree(origin)
    shutil.rmtree(cache)

    loaded = load_protocol_26_inputs(paths, inputs.manifest)
    assert loaded.checkpoint_selection == inputs.checkpoint_selection
