"""Sealed document contract for one durable Phase A spec step."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from harness.spec_step import (
    SpecStepEffectReceipt,
    SpecStepError,
    append_spec_step_receipt,
    discard_unreferenced_spec_step,
    load_prepared_spec_step,
    prepare_spec_step,
)


STEP_ID = "a" * 32


def _receipt(
    occurrence_id: str,
    *,
    assignment_id: str = "phase3-consensus/agents/0/echelon.sage:WHY3",
    contract_sha256: str = "e" * 64,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "dispatch_id": hashlib.sha256(occurrence_id.encode()).hexdigest()[:32],
        "phase_id": "phase3-consensus",
        "assignment_id": assignment_id,
        "occurrence_id": occurrence_id,
        "state_revision": 7,
        "contract_sha256": contract_sha256,
        "prompt_sha256": "1" * 64,
        "prompt_metadata_sha256": "2" * 64,
        "outcome": "published",
        "outputs": [],
        "semantic_validator_id": None,
        "semantic_result_sha256": None,
        "provider_attempts_sha256": "3" * 64,
        "validated_result_sha256": "4" * 64,
    }


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _manifest(
    occurrence_id: str,
    *,
    status: str,
    receipt: dict[str, object] | None = None,
    assignment_id: str = "phase3-consensus/agents/0/echelon.sage:WHY3",
    contract_sha256: str = "e" * 64,
    reason: str = "",
    reused_step_id: str | None = None,
    reused_dispatch_id: str | None = None,
) -> dict[str, object]:
    return {
        "assignment_id": assignment_id,
        "occurrence_id": occurrence_id,
        "contract_sha256": contract_sha256,
        "status": status,
        "reason": reason,
        "receipt_sha256": _digest(receipt) if receipt is not None else None,
        "reused_step_id": reused_step_id,
        "reused_dispatch_id": reused_dispatch_id,
    }


def _provider_execution_provenance(
    manifest: list[dict[str, object]],
    receipts: list[dict[str, object]],
    *,
    cost_usd_delta: float = 1.25,
) -> dict[str, object]:
    return {
        "prepared_result_sha256": "d" * 64,
        "provider_execution": {
            "schema_version": 1,
            "manifest_sha256": _digest(manifest),
            "manifest": manifest,
            "receipts": receipts,
            "cost_usd_delta": cost_usd_delta,
        },
    }


def _prepare(squad_dir: Path, **overrides: object):
    values: dict[str, object] = {
        "step_id": STEP_ID,
        "origin": "routed",
        "expected_state_revision": 7,
        "expected_previous_dispatch_sha256": "b" * 64,
        "route": {
            "from_phase": "phase3-consensus",
            "to_phase": "phase2",
            "manual": False,
        },
        "effects": ("publication", "journal"),
        "publication": {
            "kind": "external",
            "marker": {
                "schema_version": 1,
                "transaction_id": STEP_ID,
                "manifest_sha256": "c" * 64,
            },
        },
        "final_state": {"phase_a_state_version": 1, "phase": "phase2"},
        "provenance": {"prepared_result_sha256": "d" * 64},
    }
    values.update(overrides)
    return prepare_spec_step(squad_dir, **values)


def test_prepare_spec_step_seals_one_exact_intent(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)

    assert prepared.marker.step_id == STEP_ID
    assert prepared.marker.cursor == "publication"
    assert prepared.intent.effects == ("publication", "journal")
    assert load_prepared_spec_step(tmp_path, prepared.marker.to_dict()).marker == prepared.marker


def test_prepared_spec_step_views_are_detached(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)

    route = prepared.intent.route
    route["to_phase"] = "tampered"
    final_state = prepared.intent.final_state
    final_state["phase"] = "tampered"
    publication = prepared.intent.publication
    assert publication is not None
    publication["marker"]["manifest_sha256"] = "0" * 64

    assert prepared.intent.route["to_phase"] == "phase2"
    assert prepared.intent.final_state["phase"] == "phase2"
    assert prepared.intent.publication["marker"]["manifest_sha256"] == "c" * 64


def test_spec_step_rejects_executed_occurrence_without_exact_receipt(
    tmp_path: Path,
) -> None:
    receipt = _receipt("why3/initial")
    provenance = _provider_execution_provenance(
        [_manifest("why3/initial", status="executed", receipt=receipt)],
        [],
    )

    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(tmp_path, provenance=provenance)


def test_spec_step_accepts_all_manifest_statuses_and_repeated_occurrences(
    tmp_path: Path,
) -> None:
    initial = _receipt("why3/initial")
    final = _receipt("why3/final-revalidation")
    rows = [
        _manifest(
            "pre-dispatch/0",
            status="skipped",
            reason="condition did not match",
        ),
        _manifest("why3/initial", status="executed", receipt=initial),
        _manifest(
            "specialist/2",
            status="reused",
            reason="sealed provider result reuse",
            reused_step_id="5" * 32,
            reused_dispatch_id="6" * 32,
        ),
        _manifest(
            "stage2/2",
            status="deferred",
            reason="prerequisite review failed",
        ),
        _manifest(
            "why3/final-revalidation",
            status="executed",
            receipt=final,
        ),
    ]
    provenance = _provider_execution_provenance(rows, [initial, final])

    prepared = _prepare(tmp_path, provenance=provenance)

    assert prepared.intent.provenance == provenance


@pytest.mark.parametrize(
    "mutate",
    [
        lambda execution: execution.update({"unknown": True}),
        lambda execution: execution["manifest"][0].update({"unknown": True}),
        lambda execution: execution["manifest"][0].update({"reason": "forged"}),
        lambda execution: execution["manifest"][0].update(
            {"receipt_sha256": "0" * 64}
        ),
        lambda execution: execution["receipts"][0].update(
            {"contract_sha256": "0" * 64}
        ),
        lambda execution: execution["receipts"][0].update(
            {"provider_output_receipts": []}
        ),
        lambda execution: execution["manifest"].append(
            dict(execution["manifest"][0])
        ),
    ],
    ids=(
        "unknown-execution-key",
        "unknown-manifest-key",
        "executed-reason",
        "receipt-digest-mismatch",
        "contract-mismatch",
        "forged-receipt-field",
        "duplicate-occurrence",
    ),
)
def test_spec_step_rejects_invalid_provider_execution_provenance(
    tmp_path: Path,
    mutate,
) -> None:
    receipt = _receipt("why3/initial")
    execution = _provider_execution_provenance(
        [_manifest("why3/initial", status="executed", receipt=receipt)],
        [receipt],
    )["provider_execution"]
    mutate(execution)
    execution["manifest_sha256"] = _digest(execution["manifest"])

    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(
            tmp_path,
            provenance={
                "prepared_result_sha256": "d" * 64,
                "provider_execution": execution,
            },
        )


def test_spec_step_rejects_noncanonical_provider_manifest_order(
    tmp_path: Path,
) -> None:
    initial = _receipt("why3/initial")
    assess = _receipt(
        "stage1/1",
        assignment_id="phase3-consensus/agents/1/echelon.gatekeeper:ASSESS2",
    )
    rows = [
        _manifest(
            "stage1/1",
            status="executed",
            receipt=assess,
            assignment_id=str(assess["assignment_id"]),
        ),
        _manifest("why3/initial", status="executed", receipt=initial),
    ]

    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(
            tmp_path,
            provenance=_provider_execution_provenance(
                rows,
                [assess, initial],
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("root", "project"),
        ("path", "../issues.md"),
        ("path", "issues\\forged.md"),
    ],
)
def test_spec_step_rejects_invalid_provider_output_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    receipt = _receipt("why3/initial")
    receipt["outputs"] = [
        {
            "root": "active_spec",
            "path": "issues.md",
            "kind": "file",
            "requirement": "required",
            "sha256": "5" * 64,
            "preimage_identity_sha256": None,
            "postimage_identity_sha256": "6" * 64,
            "evidence_kind": "created",
            "members": [],
        }
    ]
    receipt["outputs"][0][field] = value

    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(
            tmp_path,
            provenance=_provider_execution_provenance(
                [_manifest("why3/initial", status="executed", receipt=receipt)],
                [receipt],
            ),
        )


def test_spec_step_rejects_provider_receipt_for_another_phase(
    tmp_path: Path,
) -> None:
    receipt = _receipt("why3/initial")
    receipt["phase_id"] = "phase1-why2"

    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(
            tmp_path,
            route={"from_phase": "phase3-consensus", "to_phase": "phase4"},
            provenance=_provider_execution_provenance(
                [_manifest("why3/initial", status="executed", receipt=receipt)],
                [receipt],
            ),
        )


@pytest.mark.parametrize(
    "effects,publication",
    [
        (("journal", "journal"), None),
        (("journal", "publication"), {"schema_version": 1, "transaction_id": STEP_ID, "manifest_sha256": "c" * 64}),
        (("commit",), None),
        (("publication",), None),
        (("journal",), {"schema_version": 1, "transaction_id": STEP_ID, "manifest_sha256": "c" * 64}),
    ],
)
def test_prepare_rejects_noncanonical_effect_and_publication_combinations(
    tmp_path: Path,
    effects: tuple[str, ...],
    publication: object,
) -> None:
    with pytest.raises(SpecStepError, match="intent_invalid"):
        _prepare(tmp_path, effects=effects, publication=publication)


@pytest.mark.parametrize("attempts", [-1, 1_000_001, True])
def test_marker_rejects_unbounded_failure_attempts(tmp_path: Path, attempts: object) -> None:
    prepared = _prepare(tmp_path)
    marker = prepared.marker.to_dict()
    marker["failure"] = {
        "effect": "publication",
        "code": "effect_io",
        "attempts": attempts,
        "resume_status": "running",
    }

    with pytest.raises(SpecStepError, match="intent_invalid"):
        load_prepared_spec_step(tmp_path, marker)


def test_marker_cursor_must_name_the_next_intent_effect(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    marker = prepared.marker.to_dict()
    marker["cursor"] = "timing"

    with pytest.raises(SpecStepError, match="intent_mismatch"):
        load_prepared_spec_step(tmp_path, marker)


def test_append_accepts_only_cursor_effect_and_advances_marker(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    wrong = SpecStepEffectReceipt(STEP_ID, "journal", "e" * 64, {"written": True})
    with pytest.raises(SpecStepError, match="receipts_invalid"):
        append_spec_step_receipt(prepared, wrong)

    receipt = SpecStepEffectReceipt(
        STEP_ID,
        "publication",
        "e" * 64,
        {"published": True},
    )
    advanced = append_spec_step_receipt(prepared, receipt)

    assert advanced.marker.cursor == "journal"
    assert advanced.receipts == (receipt,)
    assert load_prepared_spec_step(tmp_path, advanced.marker).marker == advanced.marker


def test_old_marker_may_load_exactly_one_ahead_receipt(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    receipt = SpecStepEffectReceipt(
        STEP_ID,
        "publication",
        "e" * 64,
        {"published": True},
    )
    append_spec_step_receipt(prepared, receipt)

    recovered = load_prepared_spec_step(tmp_path, prepared.marker)

    assert recovered.marker == prepared.marker
    assert recovered.receipts == (receipt,)
    assert append_spec_step_receipt(recovered, receipt).marker.cursor == "journal"


def test_load_rejects_duplicate_key_json(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    intent_path = tmp_path / ".spec-step-outbox" / STEP_ID / "intent.json"
    intent_path.write_text('{"schema_version":1,"schema_version":1}\n', encoding="utf-8")
    marker = prepared.marker.to_dict()
    marker["intent_sha256"] = __import__("hashlib").sha256(intent_path.read_bytes()).hexdigest()

    with pytest.raises(SpecStepError, match="intent_invalid"):
        load_prepared_spec_step(tmp_path, marker)


def test_load_rejects_oversized_or_nonregular_documents(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    root = tmp_path / ".spec-step-outbox" / STEP_ID
    receipts_path = root / "receipts.json"
    receipts_path.write_bytes(b"x" * (1_048_576 + 1))
    with pytest.raises(SpecStepError, match="receipts_invalid"):
        load_prepared_spec_step(tmp_path, prepared.marker)

    receipts_path.unlink()
    receipts_path.mkdir()
    with pytest.raises(SpecStepError, match="receipts_invalid"):
        load_prepared_spec_step(tmp_path, prepared.marker)


def test_prepare_rejects_symlinked_outbox(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / ".spec-step-outbox").symlink_to(target, target_is_directory=True)

    with pytest.raises(SpecStepError, match="stage_corrupt"):
        _prepare(tmp_path)


def test_prepared_handle_rejects_replaced_transaction_root(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)
    root = tmp_path / ".spec-step-outbox" / STEP_ID
    replacement = tmp_path / "replacement"
    shutil.copytree(root, replacement)
    shutil.rmtree(root)
    os.rename(replacement, root)
    receipt = SpecStepEffectReceipt(
        STEP_ID,
        "publication",
        "e" * 64,
        {"published": True},
    )

    with pytest.raises(SpecStepError, match="stage_corrupt"):
        append_spec_step_receipt(prepared, receipt)


def test_discard_unreferenced_spec_step_is_idempotent(tmp_path: Path) -> None:
    prepared = _prepare(tmp_path)

    assert discard_unreferenced_spec_step(tmp_path, prepared.marker) is True
    assert discard_unreferenced_spec_step(tmp_path, prepared.marker) is False
    assert not (tmp_path / ".spec-step-outbox" / STEP_ID).exists()
