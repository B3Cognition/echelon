"""Tests for verification evidence transport on VerifyResult."""

from __future__ import annotations

import pytest

from harness.verify_result import VerifyResult


@pytest.mark.unit
def test_from_dict_preserves_verification_evidence_mapping() -> None:
    evidence = {
        "path": "/tmp/evidence/attempt.json",
        "receipt_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "candidate_commit": "c" * 40,
        "candidate_fingerprint": "d" * 64,
        "passed": True,
    }

    result = VerifyResult.from_dict(
        {"passed": True, "failures": [], "verification_evidence": evidence}
    )

    assert result.verification_evidence == evidence


@pytest.mark.unit
def test_from_dict_ignores_non_mapping_verification_evidence() -> None:
    result = VerifyResult.from_dict(
        {"passed": True, "failures": [], "verification_evidence": "bad"}
    )

    assert result.verification_evidence == {}
