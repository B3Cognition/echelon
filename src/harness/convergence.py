"""Deterministic, persisted delivery convergence accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping

from harness.verify_result import FailureCategory, VerifyResult


DEFAULT_MAX_OUTER = 12
DEFAULT_MIN_MEANINGFUL_ATTEMPTS = 3
DEFAULT_STALL_PATIENCE = 2

_STATUS_DEBT = {
    "MISSING": 4,
    "DEVIATED": 4,
    "UNVERIFIED": 2,
    "PARTIAL": 1,
}

_CATEGORY_GATE = {
    FailureCategory.LINT: 0,
    FailureCategory.TYPECHECK: 1,
    FailureCategory.BUILD: 2,
    FailureCategory.TEST: 3,
    FailureCategory.PLAYWRIGHT_TEST: 4,
    FailureCategory.SECURITY: 0,
    FailureCategory.OTHER: 4,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_int(value: object, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _failure_keys(result: VerifyResult) -> tuple[str, ...]:
    keys: set[str] = set()
    for failure in result.failures:
        if failure.id == "fulfillment-gaps":
            continue
        test_cases = failure.details.get("test_cases")
        if isinstance(test_cases, list):
            for case in test_cases:
                if isinstance(case, Mapping):
                    case_id = case.get("id") or case.get("test_id") or case.get("name")
                else:
                    case_id = case
                if isinstance(case_id, str) and case_id.strip():
                    keys.add(f"{failure.category.value}:{failure.id}:{case_id.strip()}")
        if not test_cases:
            keys.add(f"{failure.category.value}:{failure.id}")
    return tuple(sorted(keys))


def _fulfillment_statuses(result: VerifyResult) -> tuple[tuple[str, str], ...]:
    statuses: dict[str, str] = {}
    for failure in result.failures:
        gaps = failure.details.get("gaps")
        if not isinstance(gaps, list):
            continue
        for gap in gaps:
            if not isinstance(gap, Mapping):
                continue
            requirement_id = gap.get("requirement_id")
            status = gap.get("status")
            if not isinstance(requirement_id, str) or not isinstance(status, str):
                continue
            normalized = status.upper().strip()
            if normalized in _STATUS_DEBT:
                statuses[requirement_id.strip()] = normalized
    return tuple(sorted(statuses.items()))


def _gate_rank(result: VerifyResult) -> int:
    if result.passed:
        return 6
    if any(failure.id == "fulfillment-gaps" for failure in result.failures):
        return 5
    if not result.failures:
        return 0
    return min(_CATEGORY_GATE.get(failure.category, 0) for failure in result.failures)


@dataclass(frozen=True)
class ProgressSnapshot:
    """One authoritative, JSON-safe view of product delivery progress."""

    completed_tasks: int
    total_tasks: int
    fulfillment_statuses: tuple[tuple[str, str], ...]
    failure_keys: tuple[str, ...]
    gate_rank: int
    product_fingerprint: str
    checkpoint_commit: str | None = None

    @classmethod
    def from_verify_result(
        cls,
        result: VerifyResult,
        *,
        completed_tasks: int,
        total_tasks: int,
        product_fingerprint: str | None,
        checkpoint_commit: str | None = None,
    ) -> "ProgressSnapshot":
        return cls(
            completed_tasks=_clean_int(completed_tasks),
            total_tasks=_clean_int(total_tasks),
            fulfillment_statuses=_fulfillment_statuses(result),
            failure_keys=_failure_keys(result),
            gate_rank=_gate_rank(result),
            product_fingerprint=str(product_fingerprint or ""),
            checkpoint_commit=(
                str(checkpoint_commit) if checkpoint_commit else None
            ),
        )

    @property
    def fulfillment_debt(self) -> int:
        return sum(_STATUS_DEBT.get(status, 0) for _, status in self.fulfillment_statuses)

    def to_state(self) -> dict[str, Any]:
        return {
            "completed_tasks": self.completed_tasks,
            "total_tasks": self.total_tasks,
            "fulfillment_statuses": [list(item) for item in self.fulfillment_statuses],
            "fulfillment_debt": self.fulfillment_debt,
            "failure_keys": list(self.failure_keys),
            "gate_rank": self.gate_rank,
            "product_fingerprint": self.product_fingerprint,
            "checkpoint_commit": self.checkpoint_commit,
        }

    @classmethod
    def from_state(cls, value: object) -> "ProgressSnapshot | None":
        if not isinstance(value, Mapping):
            return None
        raw_statuses = value.get("fulfillment_statuses")
        statuses: list[tuple[str, str]] = []
        if isinstance(raw_statuses, list):
            for item in raw_statuses:
                if (
                    isinstance(item, (list, tuple))
                    and len(item) == 2
                    and all(isinstance(part, str) for part in item)
                ):
                    statuses.append((item[0], item[1]))
        raw_keys = value.get("failure_keys")
        keys = (
            tuple(sorted(str(item) for item in raw_keys if isinstance(item, str)))
            if isinstance(raw_keys, list)
            else ()
        )
        checkpoint = value.get("checkpoint_commit")
        return cls(
            completed_tasks=_clean_int(value.get("completed_tasks")),
            total_tasks=_clean_int(value.get("total_tasks")),
            fulfillment_statuses=tuple(sorted(statuses)),
            failure_keys=keys,
            gate_rank=_clean_int(value.get("gate_rank")),
            product_fingerprint=str(value.get("product_fingerprint") or ""),
            checkpoint_commit=str(checkpoint) if checkpoint else None,
        )


@dataclass(frozen=True)
class LeaseObservation:
    outcome: str
    reason_code: str
    reason: str
    should_stop: bool
    stop_reason: str | None
    lease: "ConvergenceLease"


@dataclass(frozen=True)
class ConvergenceLease:
    """Persisted high-water mark and stop-loss counters for delivery."""

    schema_version: int = 1
    meaningful_attempts: int = 0
    stalled_attempts: int = 0
    infrastructure_attempts: int = 0
    last_outcome: str = "not_observed"
    last_reason_code: str = ""
    last_reason: str = ""
    last_infrastructure_reason: str = ""
    last_snapshot: ProgressSnapshot | None = None
    best_snapshot: ProgressSnapshot | None = None
    best_checkpoint_commit: str | None = None
    updated_at: str = ""

    @classmethod
    def from_state(cls, value: object) -> "ConvergenceLease":
        if not isinstance(value, Mapping):
            return cls()
        return cls(
            schema_version=1,
            meaningful_attempts=_clean_int(value.get("meaningful_attempts")),
            stalled_attempts=_clean_int(value.get("stalled_attempts")),
            infrastructure_attempts=_clean_int(value.get("infrastructure_attempts")),
            last_outcome=str(value.get("last_outcome") or "not_observed"),
            last_reason_code=str(value.get("last_reason_code") or ""),
            last_reason=str(value.get("last_reason") or ""),
            last_infrastructure_reason=str(
                value.get("last_infrastructure_reason") or ""
            ),
            last_snapshot=ProgressSnapshot.from_state(value.get("last_snapshot")),
            best_snapshot=ProgressSnapshot.from_state(value.get("best_snapshot")),
            best_checkpoint_commit=(
                str(value.get("best_checkpoint_commit"))
                if value.get("best_checkpoint_commit")
                else None
            ),
            updated_at=str(value.get("updated_at") or ""),
        )

    def to_state(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "meaningful_attempts": self.meaningful_attempts,
            "stalled_attempts": self.stalled_attempts,
            "infrastructure_attempts": self.infrastructure_attempts,
            "last_outcome": self.last_outcome,
            "last_reason_code": self.last_reason_code,
            "last_reason": self.last_reason,
            "last_infrastructure_reason": self.last_infrastructure_reason,
            "last_snapshot": self.last_snapshot.to_state() if self.last_snapshot else None,
            "best_snapshot": self.best_snapshot.to_state() if self.best_snapshot else None,
            "best_checkpoint_commit": self.best_checkpoint_commit,
            "updated_at": self.updated_at,
        }

    def with_infrastructure_attempt(self, reason: str) -> "ConvergenceLease":
        return replace(
            self,
            infrastructure_attempts=self.infrastructure_attempts + 1,
            last_infrastructure_reason=str(reason),
            updated_at=_now(),
        )

    def observe(
        self,
        snapshot: ProgressSnapshot,
        *,
        hard_ceiling: int,
        min_attempts: int = DEFAULT_MIN_MEANINGFUL_ATTEMPTS,
        stall_patience: int = DEFAULT_STALL_PATIENCE,
    ) -> LeaseObservation:
        attempts = self.meaningful_attempts + 1
        best = self.best_snapshot
        if best is None:
            outcome = "baseline"
            reason_code = "baseline_established"
            reason = "established the first authoritative delivery baseline"
            stalled = 0
            best = snapshot
            best_checkpoint = snapshot.checkpoint_commit
        else:
            comparison, reason_code, reason = _compare_snapshots(snapshot, best)
            if comparison > 0:
                outcome = "improved"
                stalled = 0
                best = snapshot
                best_checkpoint = snapshot.checkpoint_commit or self.best_checkpoint_commit
            elif comparison < 0:
                outcome = "regressed"
                stalled = self.stalled_attempts + 1
                best_checkpoint = self.best_checkpoint_commit
            else:
                outcome = "stalled"
                stalled = self.stalled_attempts + 1
                best_checkpoint = self.best_checkpoint_commit

        updated = replace(
            self,
            meaningful_attempts=attempts,
            stalled_attempts=stalled,
            last_outcome=outcome,
            last_reason_code=reason_code,
            last_reason=reason,
            last_snapshot=snapshot,
            best_snapshot=best,
            best_checkpoint_commit=best_checkpoint,
            updated_at=_now(),
        )
        if attempts >= min_attempts and stalled >= stall_patience:
            stop_reason = "stall_patience"
        elif attempts >= hard_ceiling:
            stop_reason = "hard_ceiling"
        else:
            stop_reason = None
        return LeaseObservation(
            outcome=outcome,
            reason_code=reason_code,
            reason=reason,
            should_stop=stop_reason is not None,
            stop_reason=stop_reason,
            lease=updated,
        )


def _compare_snapshots(
    current: ProgressSnapshot,
    best: ProgressSnapshot,
) -> tuple[int, str, str]:
    if current.completed_tasks != best.completed_tasks:
        if current.completed_tasks > best.completed_tasks:
            return (
                1,
                "task_progress",
                f"completed tasks increased from {best.completed_tasks} to {current.completed_tasks}",
            )
        return (
            -1,
            "task_progress_regressed",
            f"completed tasks decreased from {best.completed_tasks} to {current.completed_tasks}",
        )

    if current.gate_rank != best.gate_rank:
        if current.gate_rank > best.gate_rank:
            return (
                1,
                "verification_gate_advanced",
                f"verification advanced from gate {best.gate_rank} to {current.gate_rank}",
            )
        return (
            -1,
            "verification_gate_regressed",
            f"verification regressed from gate {best.gate_rank} to {current.gate_rank}",
        )

    if current.fulfillment_debt != best.fulfillment_debt:
        if current.fulfillment_debt < best.fulfillment_debt:
            return (
                1,
                "fulfillment_debt_reduced",
                "fulfillment debt decreased from "
                f"{best.fulfillment_debt} to {current.fulfillment_debt}",
            )
        return (
            -1,
            "fulfillment_debt_increased",
            "fulfillment debt increased from "
            f"{best.fulfillment_debt} to {current.fulfillment_debt}",
        )

    if len(current.failure_keys) != len(best.failure_keys):
        if len(current.failure_keys) < len(best.failure_keys):
            return (
                1,
                "blocking_failures_reduced",
                "stable blocking failures decreased from "
                f"{len(best.failure_keys)} to {len(current.failure_keys)}",
            )
        return (
            -1,
            "blocking_failures_increased",
            "stable blocking failures increased from "
            f"{len(best.failure_keys)} to {len(current.failure_keys)}",
        )

    return 0, "evidence_unchanged", "authoritative progress evidence did not improve"
