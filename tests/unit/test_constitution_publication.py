from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.constitution_publication import (
    ConstitutionPublicationError,
    apply_or_verify_constitution_publication,
    prepare_constitution_publication,
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _inputs(tmp_path: Path):
    project = tmp_path / "project"
    draft = project / ".echelon" / "squads" / "active" / "constitution.draft.md"
    target = project / ".echelon" / "constitution.md"
    draft.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    draft.write_text("# Constitution\n\nShip working software.\n", encoding="utf-8")
    provider_receipt = {
        "schema_version": 2,
        "dispatch_id": "a" * 32,
        "phase_id": "phase1-constitution",
        "assignment_id": "phase1-constitution",
        "occurrence_id": "ordinary",
    }
    request = prepare_constitution_publication(draft, target, provider_receipt)
    prepared = SimpleNamespace(
        intent=SimpleNamespace(
            provenance={
                "provider_execution": {"receipts": [provider_receipt]}
            }
        )
    )
    return draft, target, request, prepared


def test_prepare_does_not_publish_before_authority(tmp_path: Path) -> None:
    draft, target, request, prepared = _inputs(tmp_path)

    assert not target.exists()
    receipt = apply_or_verify_constitution_publication(prepared, request)

    assert target.read_bytes() == draft.read_bytes()
    assert receipt["target_sha256"] == request["draft_sha256"]


def test_recovery_adopts_exact_published_postimage(tmp_path: Path) -> None:
    _draft, target, request, prepared = _inputs(tmp_path)
    first = apply_or_verify_constitution_publication(prepared, request)

    second = apply_or_verify_constitution_publication(prepared, request)

    assert second == first
    assert target.read_text(encoding="utf-8").startswith("# Constitution")


def test_changed_draft_after_sealing_is_rejected(tmp_path: Path) -> None:
    draft, target, request, prepared = _inputs(tmp_path)
    draft.write_text("changed\n", encoding="utf-8")

    with pytest.raises(ConstitutionPublicationError, match="draft_drift"):
        apply_or_verify_constitution_publication(prepared, request)

    assert not target.exists()


def test_provider_receipt_binding_is_required(tmp_path: Path) -> None:
    _draft, _target, request, prepared = _inputs(tmp_path)
    prepared.intent.provenance["provider_execution"]["receipts"] = [
        {"different": True}
    ]

    with pytest.raises(ConstitutionPublicationError, match="receipt_mismatch"):
        apply_or_verify_constitution_publication(prepared, request)


def test_symlinked_draft_is_rejected(tmp_path: Path) -> None:
    draft, target, _request, prepared = _inputs(tmp_path)
    source = draft.with_name("source.md")
    source.write_text("# Constitution\n", encoding="utf-8")
    draft.unlink()
    draft.symlink_to(source)
    request = {
        "schema_version": 1,
        "draft_path": str(draft),
        "target_path": str(target),
        "draft_identity_sha256": "b" * 64,
        "draft_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "provider_receipt_sha256": _digest(
            prepared.intent.provenance["provider_execution"]["receipts"][0]
        ),
    }

    with pytest.raises(ConstitutionPublicationError, match="draft_invalid"):
        apply_or_verify_constitution_publication(prepared, request)


def test_symlinked_target_parent_is_rejected(tmp_path: Path) -> None:
    draft, target, request, prepared = _inputs(tmp_path)
    real_parent = target.parent.with_name("real-echelon")
    target.parent.rename(real_parent)
    target.parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ConstitutionPublicationError, match="target_invalid"):
        apply_or_verify_constitution_publication(prepared, request)
