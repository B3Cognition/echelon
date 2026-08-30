from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.re_v2.ledger import ObjectStore
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.ledger import Protocol22Ledger
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_26.adoption import (
    FrozenAcceptancePackageV1,
    Protocol26AdoptionError,
    import_frozen_checkpoint_closure,
    import_typed_acceptance,
)
from harness.re_v2.protocol_26.inputs import (
    ValidatedProtocol26Inputs,
    create_protocol_26_run_store,
    load_protocol_26_inputs,
)
from tests.re_v2_protocol_26_fixtures import checkpoint_for_item
from tests.unit.test_re_v2_protocol_26_inputs import _protocol26_input_fixture


@dataclass(frozen=True, slots=True)
class _CheckpointStore:
    inputs: ValidatedProtocol26Inputs
    objects: ObjectStore
    ledger: Protocol22Ledger


def _checkpoint_store(tmp_path: Path) -> _CheckpointStore:
    supplied = _protocol26_input_fixture()
    run_dir = tmp_path / "runs" / supplied.manifest.run_id
    paths = create_protocol_26_run_store(run_dir, supplied.manifest, supplied)
    validated = load_protocol_26_inputs(paths, supplied.manifest)
    objects = ObjectStore(paths.objects)
    return _CheckpointStore(
        validated,
        objects,
        Protocol22Ledger(paths.ledger, objects),
    )


@pytest.mark.unit
def test_checkpoint_import_uses_only_child_copied_objects(tmp_path: Path) -> None:
    store = _checkpoint_store(tmp_path)

    report = import_frozen_checkpoint_closure(
        store.inputs,
        store.objects,
        store.ledger,
    )

    expected = tuple(
        entry.adopted_artifact_authority.artifact_key_id
        for entry in store.inputs.checkpoint_selection.selected
        if entry.source_kind == "workspace_checkpoint"
    )
    assert report.artifact_key_ids == expected
    assert tuple(sorted(store.ledger.replay().accepted_artifacts)) == tuple(
        sorted(expected)
    )


@pytest.mark.unit
def test_checkpoint_import_is_idempotent(tmp_path: Path) -> None:
    store = _checkpoint_store(tmp_path)

    first = import_frozen_checkpoint_closure(
        store.inputs,
        store.objects,
        store.ledger,
    )
    bytes_after_first = store.ledger.path.read_bytes()
    second = import_frozen_checkpoint_closure(
        store.inputs,
        store.objects,
        store.ledger,
    )

    assert second == first
    assert store.ledger.path.read_bytes() == bytes_after_first


@pytest.mark.unit
def test_frozen_checkpoint_conflict_blocks_without_fallback(tmp_path: Path) -> None:
    store = _checkpoint_store(tmp_path)
    selection = store.inputs.checkpoint_selection.selected[0]
    work_payload = store.inputs.authority_objects[selection.expected_work_item_id]
    work_item = load_canonical_object(work_payload, WorkItemV2.from_json_dict)
    conflict = checkpoint_for_item(
        work_item,
        artifact_seed="conflicting-checkpoint-artifact",
        origin_run_id="re-conflict",
    )
    store.objects.put_blob(b"conflicting-checkpoint-artifact")
    store.ledger.record_certification(
        conflict.certification_receipt,
        conflict.work_item,
    )
    store.ledger.record_artifact_acceptance(conflict.artifact_acceptance_receipt)

    with pytest.raises(Protocol26AdoptionError, match="conflict"):
        import_frozen_checkpoint_closure(
            store.inputs,
            store.objects,
            store.ledger,
        )


@pytest.mark.unit
def test_typed_import_supports_existing_protocol25_semantic_receipts(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from harness.re_v2.protocol_25.ledger import Protocol25Ledger
    from tests.integration.test_re_v2_protocol_25_recovery import (
        _context,
        _semantic_result_work_item,
    )
    from tests.unit.test_re_v2_protocol_25_runtime import (
        _candidate,
        _certified_resolution,
        _resolution_payload,
    )

    context = _context(tmp_path / "origin-runs")
    _audit, epoch, _semantic_context, result = _certified_resolution()
    work_item = _semantic_result_work_item(context, result)
    candidate = replace(
        result.candidate_assessment,
        work_item_id=work_item.work_item_id,
    )
    source_candidate = _candidate(
        "resolution.json",
        _resolution_payload(epoch),
    )
    capture = (
        f"capture:resolution.json:{content_digest(source_candidate.candidate_bytes)}"
    ).encode()
    required = {
        result.acceptance.artifact_hash: result.artifact_bytes,
        candidate.execution_capture_hash: capture,
        candidate.normalized_authorial_payload_hash: (
            result.normalized_authorial_payload_bytes
        ),
    }
    root = tmp_path / "semantic-child" / "v2"
    root.mkdir(parents=True)
    objects = ObjectStore(root / "objects")
    ledger = Protocol25Ledger(root / "ledger.jsonl", objects)
    package = FrozenAcceptancePackageV1(
        work_item,
        result.certification,
        candidate,
        result.acceptance,
        required,
    )

    imported = import_typed_acceptance(package, objects, ledger)
    replayed = ledger.replay()

    assert imported.artifact_key_id == result.acceptance.artifact_key.identity
    assert replayed.semantic_certifications[result.certification.identity] == (
        result.certification
    )
    assert replayed.accepted_artifacts[imported.artifact_key_id] == result.acceptance
