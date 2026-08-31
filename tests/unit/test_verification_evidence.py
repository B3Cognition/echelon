"""Tests for immutable Ralph-owned host verification evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from harness.verification_evidence import (
    VerificationEvidenceRef,
    VerificationStage,
    validate_verification_receipt,
    write_verification_receipt,
)


def _write_fixture_receipt(
    root: Path,
    *,
    before: str = "b" * 64,
    after: str = "b" * 64,
    sequence: int = 1,
    started_at: str = "2026-08-31T00:00:00Z",
    stdout: bytes = b"passed\n",
) -> VerificationEvidenceRef:
    return write_verification_receipt(
        evidence_dir=root,
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before=before,
        fingerprint_after=after,
        verifier_source="configured",
        stages=[
            VerificationStage(
                name="verify",
                command=("python", "-c", "print('passed')"),
                exit_code=0,
                duration_ms=12,
                stdout=stdout,
                stderr=b"",
            )
        ],
        attempt_sequence=sequence,
        sensitive_environment={},
        started_at=started_at,
    )


@pytest.mark.unit
def test_writes_immutable_redacted_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://user:secret@localhost/db"
    )
    ref = write_verification_receipt(
        evidence_dir=tmp_path,
        spec_id="003-demo",
        strategy_id="default",
        build_id="build-1",
        candidate_commit="a" * 40,
        fingerprint_before="b" * 64,
        fingerprint_after="b" * 64,
        verifier_source="configured",
        stages=[
            VerificationStage(
                name="verify",
                command=(
                    "pnpm",
                    "verify",
                    "--url=postgres://user:secret@localhost/db",
                ),
                exit_code=0,
                duration_ms=12,
                stdout=(
                    b"connected postgres://user:secret@localhost/db\n"
                    b"token ghp_abcdefghijklmnopqrstuvwxyz0123456789AB\n"
                    b"4 passed"
                ),
                stderr=b"Authorization: Bearer abc.def.ghi",
            )
        ],
        attempt_sequence=1,
        sensitive_environment=os.environ,
    )

    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert "user:secret" not in serialized
    assert "abc.def.ghi" not in serialized
    assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB" not in serialized
    assert payload["status"] == "passed"
    assert payload["authority"] == "ralph-host-verifier"
    assert validate_verification_receipt(
        ref,
        candidate_commit="a" * 40,
        candidate_fingerprint="b" * 64,
    ).valid


@pytest.mark.unit
def test_candidate_mutation_produces_failed_receipt(tmp_path: Path) -> None:
    ref = _write_fixture_receipt(
        tmp_path, before="a" * 64, after="b" * 64
    )

    assert ref.passed is False
    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    assert payload["failure_id"] == "candidate_mutated_during_verification"
    assert not validate_verification_receipt(
        ref,
        candidate_commit="a" * 40,
        candidate_fingerprint="b" * 64,
    ).valid


@pytest.mark.unit
def test_timestamp_only_changes_keep_stable_evidence_digest(
    tmp_path: Path,
) -> None:
    first = _write_fixture_receipt(
        tmp_path,
        sequence=1,
        started_at="2026-08-31T00:00:00Z",
    )
    second = _write_fixture_receipt(
        tmp_path,
        sequence=2,
        started_at="2026-08-31T00:01:00Z",
    )

    assert first.receipt_sha256 != second.receipt_sha256
    assert first.evidence_sha256 == second.evidence_sha256


@pytest.mark.unit
def test_output_change_changes_stable_evidence_digest(tmp_path: Path) -> None:
    first = _write_fixture_receipt(tmp_path, sequence=1, stdout=b"passed\n")
    second = _write_fixture_receipt(
        tmp_path, sequence=2, stdout=b"different passed output\n"
    )

    assert first.evidence_sha256 != second.evidence_sha256


@pytest.mark.unit
def test_attempt_is_immutable_and_latest_selects_new_attempt(
    tmp_path: Path,
) -> None:
    first = _write_fixture_receipt(tmp_path, sequence=1)
    with pytest.raises(FileExistsError):
        _write_fixture_receipt(tmp_path, sequence=1)

    second = _write_fixture_receipt(tmp_path, sequence=2)
    latest = json.loads(
        (tmp_path / "latest.json").read_text(encoding="utf-8")
    )

    assert first.path.exists()
    assert second.path.exists()
    assert latest == {
        "path": second.path.name,
        "receipt_sha256": second.receipt_sha256,
    }


@pytest.mark.unit
def test_tampered_receipt_is_rejected(tmp_path: Path) -> None:
    ref = _write_fixture_receipt(tmp_path)
    payload = json.loads(ref.path.read_text(encoding="utf-8"))
    payload["status"] = "failed"
    ref.path.write_text(json.dumps(payload), encoding="utf-8")

    validation = validate_verification_receipt(
        ref,
        candidate_commit="a" * 40,
        candidate_fingerprint="b" * 64,
    )

    assert validation.valid is False
    assert "digest" in validation.reason


@pytest.mark.unit
def test_stale_candidate_is_rejected(tmp_path: Path) -> None:
    ref = _write_fixture_receipt(tmp_path)

    validation = validate_verification_receipt(
        ref,
        candidate_commit="c" * 40,
        candidate_fingerprint="b" * 64,
    )

    assert validation.valid is False
    assert "candidate" in validation.reason
