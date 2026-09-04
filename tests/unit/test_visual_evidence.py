"""Tests for immutable, candidate-bound visual evidence receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.visual_evidence import (
    validate_visual_receipt,
    write_visual_receipt,
)


PASSING_PLAYWRIGHT = {
    "total": 1,
    "passed": 1,
    "failed": 0,
    "skipped": 0,
    "tests": [],
}


def _write_receipt(tmp_path: Path, *, fingerprint: str = "product-a", artifacts=True):
    screenshot = tmp_path / "source.png"
    screenshot.write_bytes(b"png-evidence")
    return write_visual_receipt(
        evidence_dir=tmp_path / "evidence",
        spec_id="003",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="abc123",
        candidate_fingerprint=fingerprint,
        screenshot_dir="test-results",
        playwright=PASSING_PLAYWRIGHT,
        artifact_paths=[screenshot] if artifacts else [],
        required_artifacts=True,
        attempt_sequence=1,
    )


def test_visual_receipt_retains_hashed_artifact_and_validates(tmp_path: Path) -> None:
    ref = _write_receipt(tmp_path)

    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    artifact = payload["artifacts"][0]
    retained = ref.path.parent / artifact["path"]

    assert retained.read_bytes() == b"png-evidence"
    assert artifact["sha256"]
    assert ref.artifact_count == 1
    assert ref.passed is True
    assert validate_visual_receipt(ref, candidate_fingerprint="product-a").valid


def test_visual_receipt_is_exclusive_per_attempt(tmp_path: Path) -> None:
    _write_receipt(tmp_path)

    with pytest.raises(FileExistsError):
        _write_receipt(tmp_path)


def test_visual_receipt_rejects_candidate_mismatch(tmp_path: Path) -> None:
    ref = _write_receipt(tmp_path)

    validation = validate_visual_receipt(ref, candidate_fingerprint="product-b")

    assert validation.valid is False
    assert "candidate" in validation.reason


def test_visual_receipt_rejects_tampered_artifact(tmp_path: Path) -> None:
    ref = _write_receipt(tmp_path)
    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    retained = ref.path.parent / payload["artifacts"][0]["path"]
    retained.write_bytes(b"tampered")

    validation = validate_visual_receipt(ref, candidate_fingerprint="product-a")

    assert validation.valid is False
    assert "artifact" in validation.reason


def test_required_visual_receipt_with_zero_artifacts_fails_closed(tmp_path: Path) -> None:
    ref = _write_receipt(tmp_path, artifacts=False)

    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    assert ref.passed is False
    assert payload["failure_id"] == "visual_artifacts_missing"
    assert not validate_visual_receipt(ref, candidate_fingerprint="product-a").valid
