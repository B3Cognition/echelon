"""Sealed document contract for one durable Phase A spec step."""

from __future__ import annotations

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


def _prepare(squad_dir: Path, **overrides: object):
    values: dict[str, object] = {
        "step_id": STEP_ID,
        "origin": "routed",
        "expected_state_revision": 7,
        "expected_previous_dispatch_sha256": "b" * 64,
        "route": {"from_phase": "phase1", "to_phase": "phase2", "manual": False},
        "effects": ("publication", "journal"),
        "publication": {
            "schema_version": 1,
            "transaction_id": STEP_ID,
            "manifest_sha256": "c" * 64,
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
    publication["manifest_sha256"] = "0" * 64

    assert prepared.intent.route["to_phase"] == "phase2"
    assert prepared.intent.final_state["phase"] == "phase2"
    assert prepared.intent.publication["manifest_sha256"] == "c" * 64


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
