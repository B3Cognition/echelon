"""Tests for immutable opt-in local verification attestations."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.local_runner_candidate import EffectiveLocalCandidate
from harness.local_runner_evidence import (
    LocalRunnabilityAttestationInput,
    select_local_verification_status,
    write_local_runnability_attestation,
)


def _candidate(fingerprint: str = "a" * 64) -> EffectiveLocalCandidate:
    return EffectiveLocalCandidate(
        build_id="build-local-demo",
        sandbox_candidate_commit="b" * 40,
        effective_candidate_commit="c" * 40,
        product_fingerprint=fingerprint,
        contract_hash="d" * 64,
        stack_hash="e" * 64,
        observer_plan_hash="f" * 64,
        sandbox_receipt_sha256="1" * 64,
        mirror_path=Path("/tmp/mirror.git"),
        stack_snapshot={"schema_version": 1, "resolved": {}},
    )


def _write(
    root: Path,
    *,
    sequence: int,
    status: str,
    candidate: EffectiveLocalCandidate,
):
    return write_local_runnability_attestation(
        root,
        LocalRunnabilityAttestationInput(
            status=status,
            candidate=candidate,
            sandbox_receipt_sha256="1" * 64,
            runner_profile_digest="2" * 64,
            cleanup_complete=status == "passed",
            redacted_logs="DATABASE_URL=[REDACTED]",
            attempt_sequence=sequence,
            local_run_id=f"local-{sequence}",
        ),
    )


@pytest.mark.unit
def test_latest_valid_pass_survives_later_preflight_failure(tmp_path: Path) -> None:
    candidate = _candidate()
    passed = _write(tmp_path, sequence=1, status="passed", candidate=candidate)
    failed = _write(tmp_path, sequence=2, status="host_preflight_failed", candidate=candidate)

    status = select_local_verification_status(tmp_path, candidate)

    assert status.valid_pass_path == passed.path
    assert status.latest_attempt_path == failed.path
    assert status.display_status == "passed"


@pytest.mark.unit
def test_changed_effective_candidate_makes_prior_attestation_stale(tmp_path: Path) -> None:
    _write(tmp_path, sequence=1, status="passed", candidate=_candidate("a" * 64))

    status = select_local_verification_status(tmp_path, _candidate("b" * 64))

    assert status.display_status == "stale"
