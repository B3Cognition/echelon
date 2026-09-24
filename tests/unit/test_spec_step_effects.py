from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import harness.spec_step_effects as effects_module
from harness.spec_step import prepare_spec_step
from harness.spec_step_effects import PhaseASpecStepEffects
from harness.spec_step_kernel import SpecStepEffectError
from harness.squad_publication import SquadPublicationTransaction


STEP_ID = "a" * 32
NON_PUBLICATION_EFFECTS = (
    "journal",
    "timing",
    "quality",
    "checkpoint",
    "context",
    "mining",
    "retarget",
)
PRIMITIVE_NAMES = {
    "checkpoint": "create_or_recover_step_checkpoint",
    "context": "install_or_verify_step_context",
}


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    squad_dir = project_root / ".echelon" / "squads" / "active"
    squad_dir.mkdir(parents=True)
    return project_root, squad_dir


def _prepared(
    squad_dir: Path,
    effect: str,
    *,
    publication: dict[str, object] | None = None,
):
    return prepare_spec_step(
        squad_dir,
        step_id=STEP_ID,
        origin="routed",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="b" * 64,
        route={"kind": "routed", "from_phase": "phase1", "to_phase": "phase2"},
        effects=(effect,),
        publication=publication,
        final_state={"phase_a_state_version": 1, "phase": "phase2"},
        provenance={"effects": {effect: {"sealed": True}}},
    )


def _adapter(project_root: Path, squad_dir: Path) -> PhaseASpecStepEffects:
    return PhaseASpecStepEffects(
        project_root=project_root,
        squad_dir=squad_dir,
        phase_graph=object(),
        telemetry_store=object(),
        context_drawer_loader=lambda *_args: [],
    )


@pytest.mark.parametrize("effect", NON_PUBLICATION_EFFECTS)
def test_effect_adapter_returns_one_bound_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effect: str,
) -> None:
    project_root, squad_dir = _roots(tmp_path)
    prepared = _prepared(squad_dir, effect)
    calls: list[tuple[object, object]] = []

    def primitive(*, prepared, state, **_kwargs):
        calls.append((prepared, state))
        return {"effect": effect, "saved": True}

    monkeypatch.setattr(
        effects_module,
        PRIMITIVE_NAMES.get(effect, f"apply_or_verify_step_{effect}"),
        primitive,
    )
    state = {"state_revision": 7}

    receipt = _adapter(project_root, squad_dir).apply(prepared, state)

    assert calls == [(prepared, state)]
    assert receipt.step_id == STEP_ID
    assert receipt.effect == effect
    assert receipt.payload == {"effect": effect, "saved": True}


def _publication_step(tmp_path: Path):
    project_root, squad_dir = _roots(tmp_path)
    transaction = SquadPublicationTransaction.begin(project_root, squad_dir, STEP_ID)
    staged = transaction.build_path("staged/result.txt")
    staged.parent.mkdir(parents=True)
    staged.write_text("published\n", encoding="utf-8")
    transaction.add_write(
        Path("specs/result.txt"),
        staged,
        owned_paths={Path("specs/result.txt")},
    )
    publication = transaction.seal()
    prepared = _prepared(squad_dir, "publication", publication=publication.marker.to_dict())
    return project_root, squad_dir, prepared, publication


def test_publication_adapter_publishes_and_binds_exact_postimage(tmp_path: Path) -> None:
    project_root, squad_dir, prepared, publication = _publication_step(tmp_path)

    receipt = _adapter(project_root, squad_dir).apply(prepared, {"state_revision": 7})

    assert (project_root / "specs/result.txt").read_text(encoding="utf-8") == "published\n"
    assert receipt.step_id == STEP_ID
    assert receipt.effect == "publication"
    assert receipt.payload["marker"] == publication.marker.to_dict()
    encoded = json.dumps(
        receipt.payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert receipt.postimage_sha256 == hashlib.sha256(encoded).hexdigest()


def test_publication_adapter_adopts_publish_before_receipt(tmp_path: Path) -> None:
    project_root, squad_dir, prepared, publication = _publication_step(tmp_path)
    publication.publish()

    receipt = _adapter(project_root, squad_dir).apply(prepared, {"state_revision": 7})

    assert receipt.effect == "publication"
    assert (project_root / "specs/result.txt").read_text(encoding="utf-8") == "published\n"


def test_publication_adapter_reports_target_drift_without_overwrite(tmp_path: Path) -> None:
    project_root, squad_dir, prepared, _publication = _publication_step(tmp_path)
    target = project_root / "specs/result.txt"
    target.parent.mkdir(parents=True)
    target.write_text("unexpected\n", encoding="utf-8")

    with pytest.raises(SpecStepEffectError, match="target_drift"):
        _adapter(project_root, squad_dir).apply(prepared, {"state_revision": 7})

    assert target.read_text(encoding="utf-8") == "unexpected\n"


def test_publication_adapter_rejects_marker_stage_mismatch(tmp_path: Path) -> None:
    project_root, squad_dir, prepared, _publication = _publication_step(tmp_path)
    marker = prepared.intent.publication
    assert marker is not None
    marker["manifest_sha256"] = "f" * 64
    mismatched = prepare_spec_step(
        squad_dir,
        step_id="c" * 32,
        origin="routed",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="b" * 64,
        route={"kind": "routed"},
        effects=("publication",),
        publication={
            "schema_version": 1,
            "transaction_id": "c" * 32,
            "manifest_sha256": marker["manifest_sha256"],
        },
        final_state={"phase_a_state_version": 1},
        provenance={},
    )

    with pytest.raises(SpecStepEffectError, match="manifest_mismatch|stage_missing"):
        _adapter(project_root, squad_dir).apply(mismatched, {"state_revision": 7})


def test_effect_adapter_rejects_commit(tmp_path: Path) -> None:
    project_root, squad_dir = _roots(tmp_path)
    prepared = _prepared(squad_dir, "journal")
    marker = prepared.marker.__class__(
        prepared.marker.schema_version,
        prepared.marker.step_id,
        prepared.marker.intent_sha256,
        prepared.marker.receipts_sha256,
        "commit",
        prepared.marker.origin,
        prepared.marker.publication_binding_sha256,
        prepared.marker.failure,
    )
    forged = prepared.__class__(
        marker,
        prepared.intent,
        prepared._squad_dir,
        prepared._transaction_root,
        prepared._transaction_identity,
        prepared._receipts_json,
    )

    with pytest.raises(SpecStepEffectError, match="effect_invalid"):
        _adapter(project_root, squad_dir).apply(forged, {"state_revision": 7})
