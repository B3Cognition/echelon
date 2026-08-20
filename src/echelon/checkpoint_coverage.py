"""Run-scoped Phase A checkpoint coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from harness.phase_checkpoints import CheckpointLedger, PhaseCheckpoint


class CheckpointCoverageError(RuntimeError):
    """Raised when checkpoint coverage authorities disagree."""


@dataclass(frozen=True)
class CheckpointCoverageRow:
    completion_id: str
    phase: str
    status: str
    rewind: str


def _phase_policy(graph: object, phase: str) -> tuple[str, str]:
    try:
        node = graph.get(phase)  # type: ignore[attr-defined]
    except (AttributeError, KeyError) as exc:
        raise CheckpointCoverageError(f"unknown checkpoint phase: {phase}") from exc
    checkpoint = getattr(node, "checkpoint", None)
    rewind = getattr(node, "rewind", None)
    if checkpoint not in {"required", "none"} or rewind not in {
        "supported",
        "none",
    }:
        raise CheckpointCoverageError(f"invalid checkpoint policy for phase: {phase}")
    return checkpoint, rewind


def _completion_index(
    ledger: CheckpointLedger,
) -> dict[str, PhaseCheckpoint]:
    indexed: dict[str, PhaseCheckpoint] = {}
    for checkpoint in ledger.checkpoints:
        completion_id = checkpoint.completion_id
        if not completion_id:
            continue
        if completion_id in indexed:
            raise CheckpointCoverageError(
                f"duplicate checkpoint completion ID: {completion_id}"
            )
        indexed[completion_id] = checkpoint
    return indexed


def _validate_matching_checkpoint(
    checkpoint: PhaseCheckpoint,
    *,
    phase: str,
    state: Mapping[str, object],
    ledger: CheckpointLedger,
) -> None:
    run_id = state.get("run_id")
    spec_id = state.get("spec_id")
    if (
        checkpoint.phase != phase
        or checkpoint.spec_id != ledger.spec_id
        or (isinstance(run_id, str) and run_id and checkpoint.run_id != run_id)
        or (isinstance(spec_id, str) and spec_id and checkpoint.spec_id != spec_id)
    ):
        raise CheckpointCoverageError("checkpoint completion identity drift")


def _versioned_coverage(
    graph: object,
    state: Mapping[str, object],
    ledger: CheckpointLedger,
) -> tuple[CheckpointCoverageRow, ...]:
    outcomes = state.get("phase_completion_outcomes")
    if type(outcomes) is not list:
        raise CheckpointCoverageError("phase completion outcomes must be a list")
    checkpoints = _completion_index(ledger)
    seen: set[str] = set()
    rows: list[CheckpointCoverageRow] = []
    for outcome in outcomes:
        if type(outcome) is not dict:
            raise CheckpointCoverageError("invalid phase completion outcome")
        completion_id = outcome.get("completion_id")
        phase = outcome.get("phase")
        result = outcome.get("outcome")
        if (
            type(completion_id) is not str
            or not completion_id
            or type(phase) is not str
            or not phase
            or result not in {"executed", "skipped"}
        ):
            raise CheckpointCoverageError("invalid phase completion outcome")
        if completion_id in seen:
            raise CheckpointCoverageError(
                f"duplicate phase completion ID: {completion_id}"
            )
        seen.add(completion_id)
        checkpoint_policy, rewind_policy = _phase_policy(graph, phase)
        sealed_policy = outcome.get("checkpoint")
        if sealed_policy is not None and sealed_policy != checkpoint_policy:
            raise CheckpointCoverageError("checkpoint policy identity drift")

        matching = checkpoints.get(completion_id)
        if matching is not None:
            _validate_matching_checkpoint(
                matching,
                phase=phase,
                state=state,
                ledger=ledger,
            )
        if outcome.get("legacy") is True:
            status = "legacy-migrated"
        elif result == "skipped":
            status = "skipped"
        elif checkpoint_policy == "none":
            status = "not-checkpointed"
        elif matching is None:
            status = "missing"
        else:
            status = "recorded"
        rows.append(
            CheckpointCoverageRow(
                completion_id=completion_id,
                phase=phase,
                status=status,
                rewind=matching.rewind if matching is not None else rewind_policy,
            )
        )
    return tuple(rows)


def _legacy_coverage(
    graph: object,
    state: Mapping[str, object],
    ledger: CheckpointLedger,
) -> tuple[CheckpointCoverageRow, ...]:
    completed = state.get("completed_phases", [])
    if type(completed) is not list:
        raise CheckpointCoverageError("completed phases must be a list")
    rows: list[CheckpointCoverageRow] = []
    seen: set[str] = set()
    for phase in completed:
        if type(phase) is not str or not phase:
            raise CheckpointCoverageError("invalid completed phase")
        if phase in seen:
            continue
        seen.add(phase)
        _, rewind_policy = _phase_policy(graph, phase)
        matching = [row for row in ledger.checkpoints if row.phase == phase]
        rows.append(
            CheckpointCoverageRow(
                completion_id="",
                phase=phase,
                status="recorded" if matching else "legacy-untracked",
                rewind=matching[-1].rewind if matching else rewind_policy,
            )
        )
    return tuple(rows)


def compute_spec_checkpoint_coverage(
    graph: object,
    state: Mapping[str, object],
    ledger: CheckpointLedger,
) -> tuple[CheckpointCoverageRow, ...]:
    """Compute checkpoint coverage from run state and its exact spec ledger."""

    if state.get("checkpoint_policy_version") == 2:
        return _versioned_coverage(graph, state, ledger)
    return _legacy_coverage(graph, state, ledger)
