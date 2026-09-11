from __future__ import annotations

import pytest

from harness.convergence import ConvergenceLease, ProgressSnapshot
from harness.verify_result import FailureCategory, FailureEntry, VerifyResult


def _failure(
    category: FailureCategory,
    failure_id: str,
    *,
    details: dict[str, object] | None = None,
) -> VerifyResult:
    return VerifyResult(
        passed=False,
        failures=[
            FailureEntry(
                category=category,
                id=failure_id,
                error="deliberately noisy provider output",
                details=details or {},
            )
        ],
    )


def _snapshot(
    verify_result: VerifyResult,
    *,
    completed: int = 1,
    fingerprint: str = "candidate-a",
    checkpoint: str | None = "commit-a",
) -> ProgressSnapshot:
    return ProgressSnapshot.from_verify_result(
        verify_result,
        completed_tasks=completed,
        total_tasks=4,
        product_fingerprint=fingerprint,
        checkpoint_commit=checkpoint,
    )


@pytest.mark.unit
def test_first_authoritative_observation_establishes_baseline() -> None:
    snapshot = _snapshot(_failure(FailureCategory.TEST, "verify-command"))

    observation = ConvergenceLease.from_state(None).observe(
        snapshot,
        hard_ceiling=12,
    )

    assert observation.outcome == "baseline"
    assert observation.should_stop is False
    assert observation.lease.meaningful_attempts == 1
    assert observation.lease.stalled_attempts == 0
    assert observation.lease.best_snapshot == snapshot


@pytest.mark.unit
def test_task_completion_resets_stall_patience() -> None:
    verify = _failure(FailureCategory.TEST, "verify-command")
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(verify), hard_ceiling=12
    ).lease
    lease = lease.observe(
        _snapshot(verify, fingerprint="candidate-b"), hard_ceiling=12
    ).lease

    observation = lease.observe(
        _snapshot(verify, completed=2, fingerprint="candidate-c", checkpoint="commit-c"),
        hard_ceiling=12,
    )

    assert observation.outcome == "improved"
    assert observation.reason_code == "task_progress"
    assert observation.lease.stalled_attempts == 0
    assert observation.lease.best_checkpoint_commit == "commit-c"


@pytest.mark.unit
def test_reducing_fulfillment_debt_is_progress() -> None:
    previous = _snapshot(
        _failure(
            FailureCategory.OTHER,
            "fulfillment-gaps",
            details={
                "gaps": [
                    {"requirement_id": "AC-001", "status": "MISSING"},
                    {"requirement_id": "AC-002", "status": "PARTIAL"},
                ]
            },
        )
    )
    current = _snapshot(
        _failure(
            FailureCategory.OTHER,
            "fulfillment-gaps",
            details={
                "gaps": [
                    {"requirement_id": "AC-001", "status": "PARTIAL"},
                ]
            },
        ),
        fingerprint="candidate-b",
    )
    lease = ConvergenceLease.from_state(None).observe(previous, hard_ceiling=12).lease

    observation = lease.observe(current, hard_ceiling=12)

    assert observation.outcome == "improved"
    assert observation.reason_code == "fulfillment_debt_reduced"
    assert current.fulfillment_debt == 1


@pytest.mark.unit
def test_reaching_later_verification_gate_is_progress_even_when_it_exposes_debt() -> None:
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(_failure(FailureCategory.TEST, "verify-command")),
        hard_ceiling=12,
    ).lease
    fulfillment = _snapshot(
        _failure(
            FailureCategory.OTHER,
            "fulfillment-gaps",
            details={
                "gaps": [
                    {"requirement_id": "AC-001", "status": "UNVERIFIED"},
                    {"requirement_id": "AC-002", "status": "PARTIAL"},
                ]
            },
        ),
        fingerprint="candidate-b",
    )

    observation = lease.observe(fulfillment, hard_ceiling=12)

    assert observation.outcome == "improved"
    assert observation.reason_code == "verification_gate_advanced"


@pytest.mark.unit
def test_stable_failure_reduction_is_progress_at_same_gate() -> None:
    previous = VerifyResult(
        passed=False,
        failures=[
            FailureEntry(FailureCategory.TEST, "unit-a", "noise"),
            FailureEntry(FailureCategory.TEST, "unit-b", "different noise"),
        ],
    )
    current = _failure(FailureCategory.TEST, "unit-a")
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(previous), hard_ceiling=12
    ).lease

    observation = lease.observe(
        _snapshot(current, fingerprint="candidate-b"), hard_ceiling=12
    )

    assert observation.outcome == "improved"
    assert observation.reason_code == "blocking_failures_reduced"


@pytest.mark.unit
def test_fingerprint_only_change_consumes_stall_patience() -> None:
    verify = _failure(FailureCategory.TEST, "verify-command")
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(verify), hard_ceiling=12
    ).lease

    observation = lease.observe(
        _snapshot(verify, fingerprint="candidate-b", checkpoint="commit-b"),
        hard_ceiling=12,
    )

    assert observation.outcome == "stalled"
    assert observation.reason_code == "evidence_unchanged"
    assert observation.lease.stalled_attempts == 1
    assert observation.lease.best_checkpoint_commit == "commit-a"


@pytest.mark.unit
def test_regression_consumes_patience_without_replacing_high_water_mark() -> None:
    best = _snapshot(_failure(FailureCategory.TEST, "unit-a"), completed=2)
    lease = ConvergenceLease.from_state(None).observe(best, hard_ceiling=12).lease
    regressed = _snapshot(
        VerifyResult(
            passed=False,
            failures=[
                FailureEntry(FailureCategory.TEST, "unit-a", "noise"),
                FailureEntry(FailureCategory.TEST, "unit-b", "noise"),
            ],
        ),
        completed=1,
        fingerprint="candidate-b",
        checkpoint="commit-b",
    )

    observation = lease.observe(regressed, hard_ceiling=12)

    assert observation.outcome == "regressed"
    assert observation.lease.stalled_attempts == 1
    assert observation.lease.best_snapshot == best
    assert observation.lease.best_checkpoint_commit == "commit-a"


@pytest.mark.unit
def test_two_non_improving_observations_stop_after_minimum_attempts() -> None:
    verify = _failure(FailureCategory.TEST, "verify-command")
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(verify), hard_ceiling=12
    ).lease
    lease = lease.observe(
        _snapshot(verify, fingerprint="candidate-b"), hard_ceiling=12
    ).lease

    observation = lease.observe(
        _snapshot(verify, fingerprint="candidate-c"), hard_ceiling=12
    )

    assert observation.should_stop is True
    assert observation.stop_reason == "stall_patience"
    assert observation.lease.meaningful_attempts == 3
    assert observation.lease.stalled_attempts == 2


@pytest.mark.unit
def test_hard_ceiling_stops_even_when_latest_observation_improves() -> None:
    verify = _failure(FailureCategory.TEST, "verify-command")
    lease = ConvergenceLease.from_state(None).observe(
        _snapshot(verify), hard_ceiling=2
    ).lease

    observation = lease.observe(
        _snapshot(verify, completed=2, fingerprint="candidate-b"),
        hard_ceiling=2,
    )

    assert observation.outcome == "improved"
    assert observation.should_stop is True
    assert observation.stop_reason == "hard_ceiling"


@pytest.mark.unit
def test_state_round_trip_preserves_high_water_and_infrastructure_count() -> None:
    snapshot = _snapshot(_failure(FailureCategory.TEST, "verify-command"))
    lease = ConvergenceLease.from_state(None).with_infrastructure_attempt(
        "provider_session_limit"
    )
    lease = lease.observe(snapshot, hard_ceiling=12).lease

    restored = ConvergenceLease.from_state(lease.to_state())

    assert restored == lease
    assert restored.infrastructure_attempts == 1
    assert restored.last_infrastructure_reason == "provider_session_limit"
