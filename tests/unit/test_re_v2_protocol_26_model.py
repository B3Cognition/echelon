from __future__ import annotations

from dataclasses import replace
import json

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_26.model import (
    CheckpointManifestV1,
    CheckpointSelectionBundleV1,
    LayerExecutionContractV1,
    Protocol26SchemaError,
    RunManifestV5,
)
from tests.re_v2_protocol_26_fixtures import (
    checkpoint_manifest_v1,
    checkpoint_selection_bundle_v1,
    layer_execution_contract_v1,
    manifest_v5,
)


@pytest.mark.unit
@pytest.mark.parametrize("target_layer", ["L1", "L2", "L3"])
def test_layer_execution_contract_round_trips_exact_layer_manifest(
    target_layer: str,
) -> None:
    contract = layer_execution_contract_v1(target_layer)

    decoded = LayerExecutionContractV1.from_json_dict(contract.to_json_dict())

    assert decoded == contract
    assert decoded.target_layer == target_layer
    assert decoded.identity == content_digest(contract.to_json_dict())


@pytest.mark.unit
def test_layer_execution_contract_rejects_wrong_target_layer() -> None:
    raw = layer_execution_contract_v1("L1").to_json_dict()
    raw["target_layer"] = "L2"

    with pytest.raises(Protocol26SchemaError, match="target_layer"):
        LayerExecutionContractV1.from_json_dict(raw)


@pytest.mark.unit
def test_checkpoint_manifest_round_trips_exact_receipt_authority() -> None:
    checkpoint = checkpoint_manifest_v1()

    decoded = CheckpointManifestV1.from_json_dict(checkpoint.to_json_dict())

    assert decoded == checkpoint
    assert decoded.identity == content_digest(checkpoint.to_json_dict())
    assert decoded.artifact_key_id == decoded.work_item.output_key.identity
    assert (
        decoded.adopted_artifact_authority.artifact_acceptance_receipt_id
        == decoded.artifact_acceptance_receipt.identity
    )


@pytest.mark.unit
def test_checkpoint_manifest_rejects_cross_bound_artifact_hash() -> None:
    checkpoint = checkpoint_manifest_v1()
    raw = checkpoint.to_json_dict()
    raw["artifact_hash"] = "sha256:" + "f" * 64

    with pytest.raises(Protocol26SchemaError, match="artifact_hash"):
        CheckpointManifestV1.from_json_dict(raw)


def test_checkpoint_manifest_round_trips_exact_l3_epoch_authority(tmp_path) -> None:
    from dataclasses import replace

    from harness.re_v2.protocol_24.model import AdoptedArtifactAuthorityV1
    from harness.re_v2.protocol_26.model import CheckpointRankV1
    from tests.integration.test_re_v2_protocol_25_recovery import (
        _context,
        _semantic_result_work_item,
    )
    from tests.re_v2_protocol_22_fixtures import digest
    from tests.unit.test_re_v2_protocol_25_runtime import _certified_resolution

    context = _context(tmp_path)
    _audit, epoch, _semantic_context, result = _certified_resolution()
    item = _semantic_result_work_item(context, result)
    candidate = replace(result.candidate_assessment, work_item_id=item.work_item_id)
    rank = CheckpointRankV1(1, "semantic-pass-v1", digest("semantic-rank"), (1,))
    ledger_hash = digest("semantic-ledger-record")
    authority = AdoptedArtifactAuthorityV1(
        1,
        item.output_key.identity,
        result.acceptance.artifact_hash,
        item.output_key.dependency_hashes,
        result.certification.identity,
        candidate.identity,
        result.acceptance.identity,
        "re-l3-origin",
        ledger_hash,
    )
    immutable = {
        item.work_item_id,
        result.acceptance.artifact_hash,
        result.certification.identity,
        candidate.identity,
        candidate.execution_capture_hash,
        candidate.normalized_authorial_payload_hash,
        result.acceptance.identity,
        epoch.identity,
        *item.output_key.dependency_hashes,
    }
    checkpoint = CheckpointManifestV1(
        1,
        "re-l3-origin",
        digest("l3-origin-manifest"),
        "2.5",
        4,
        digest("l3-acceptance-event"),
        digest("l3-event-prefix"),
        ledger_hash,
        digest("l3-ledger-prefix"),
        item,
        item.output_key.identity,
        result.acceptance.artifact_hash,
        result.certification,
        candidate,
        result.acceptance,
        authority,
        (),
        item.output_key.dependency_hashes,
        tuple(sorted(value for value in immutable if value is not None)),
        epoch.identity,
        tuple(sorted((result.certification.identity, epoch.identity))),
        rank,
        rank.policy_hash,
    )

    decoded = CheckpointManifestV1.from_json_dict(checkpoint.to_json_dict())

    assert decoded == checkpoint
    assert decoded.audit_epoch_id == epoch.identity
    assert epoch.identity in decoded.semantic_authority_ids


@pytest.mark.unit
def test_selection_bundle_round_trips_dependency_order_and_inventory() -> None:
    bundle = checkpoint_selection_bundle_v1()

    decoded = CheckpointSelectionBundleV1.from_json_dict(bundle.to_json_dict())

    assert decoded == bundle
    assert decoded.selected[0].checkpoint_manifest_id is not None
    assert decoded.copied_object_ids == tuple(sorted(decoded.copied_object_ids))


@pytest.mark.unit
def test_selection_bundle_rejects_duplicate_selected_work_item() -> None:
    bundle = checkpoint_selection_bundle_v1()
    raw = bundle.to_json_dict()
    raw["selected"] = [raw["selected"][0], raw["selected"][0]]

    with pytest.raises(Protocol26SchemaError, match="selected"):
        CheckpointSelectionBundleV1.from_json_dict(raw)


@pytest.mark.unit
@pytest.mark.parametrize("target_layer", ["L1", "L2", "L3"])
def test_manifest_v5_round_trips_and_pins_protocol_2_6(target_layer: str) -> None:
    manifest = manifest_v5(target_layer)
    payload = canonical_json_bytes(manifest.to_json_dict())

    assert RunManifestV5.from_json_dict(json.loads(payload)) == manifest
    assert manifest.run_manifest_id == content_digest(payload)


@pytest.mark.unit
def test_manifest_v5_rejects_duplicate_catalog_reference() -> None:
    manifest = manifest_v5()

    with pytest.raises(Protocol26SchemaError, match="distinct"):
        replace(
            manifest,
            checkpoint_selection=manifest.layer_execution_contract,
        )


@pytest.mark.unit
def test_manifest_v5_rejects_unknown_field() -> None:
    raw = manifest_v5().to_json_dict()
    raw["new_authority"] = "not-pinned"

    with pytest.raises(Protocol26SchemaError, match="unknown fields"):
        RunManifestV5.from_json_dict(raw)
