"""Single-dispatch orchestration for the pinned RE v2 execution kernel."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import stat
import tempfile
from types import MappingProxyType
from typing import Callable, Iterator, Literal, Mapping, Protocol

from .budget import BudgetDecision, ReV2BudgetError, evaluate_budget
from .candidates import (
    DispatchLease,
    ProcessIdentity,
    ReV2CandidateError,
)
from .canonical import canonical_json_bytes, content_digest
from .events import EventRecord, ReV2EventError
from .ledger import ReV2LedgerError
from .model import ExecutionObservation, WorkItem
from .planner import PlanDecision, ReV2PlanError, plan_next
from .projection import ReV2ProjectionError, rebuild_projection
from .recovery import (
    ProcessInspector,
    ReV2RecoveryError,
    ReV2RecoveryResult,
    ReV2RunContext,
    next_dispatch_attempt,
    recover_run,
)


class ReV2ControllerError(RuntimeError):
    """Raised when orchestration cannot safely produce a controller result."""


class WorkExecutor(Protocol):
    """Produce observable candidate bytes without granting them authority."""

    def execute(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]: ...


ProcessIdentityFactory = Callable[[WorkItem, str, int, str], ProcessIdentity]


@dataclass(frozen=True, slots=True)
class ReV2ControllerResult:
    """One durable controller outcome suitable for status/banner rendering."""

    status: Literal["active", "paused", "complete", "finalized_partial", "failed"]
    reason_code: str | None
    reason: str | None
    work_item_id: str | None
    projection: Mapping[str, object]
    plan: PlanDecision | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "projection", MappingProxyType(dict(self.projection))
        )


class DeterministicInventoryExecutor:
    """The complete production EGR-164 registry: deterministic L0 only."""

    _PRODUCERS = {
        "deterministic-source-inventory",
        "deterministic-partition-inventory",
    }

    def __init__(
        self,
        output_root: Path,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.output_root = Path(output_root)
        self._clock = clock or _canonical_utc_now

    def execute(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]:
        if (
            work_item.producer_id not in self._PRODUCERS
            or work_item.output_key.layer != "L0"
        ):
            raise ReV2ControllerError(
                "deterministic inventory executor accepts registered L0 work only"
            )
        if lease.work_item != work_item:
            raise ReV2ControllerError("executor lease does not match WorkItem")
        _ensure_output_root(self.output_root)
        started_at = _timestamp(self._clock(), "inventory executor clock")
        entries = _snapshot_inventory(Path(snapshot_root))
        document = {
            "artifact_kind": work_item.output_key.artifact_kind,
            "dependency_hashes": list(work_item.required_artifact_hashes),
            "partition_manifest_id": work_item.output_key.partition_manifest_id,
            "producer_protocol_version": work_item.producer_protocol_version,
            "schema_version": 1,
            "source_snapshot_id": work_item.output_key.source_snapshot_id,
            "snapshot_entries": entries,
            "work_item_id": work_item.work_item_id,
        }
        output = Path(
            tempfile.mkdtemp(prefix="dispatch-", dir=self.output_root)
        )
        (output / "inventory.json").write_bytes(canonical_json_bytes(document))
        ended_at = _timestamp(self._clock(), "inventory executor clock")
        duration_ms = _elapsed_ms(started_at, ended_at)
        return output, ExecutionObservation(
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            exit_code=0,
            timed_out=False,
            output_truncated=False,
            result_contract_valid=True,
            token_usage=0,
            provider_name="deterministic-inventory",
            model_name="none",
            stderr_digest=None,
        )


def production_executor_registry(
    output_root: Path,
    *,
    clock: Callable[[], str] | None = None,
) -> Mapping[str, WorkExecutor]:
    """Return only the deterministic source/partition L0 producers."""
    executor = DeterministicInventoryExecutor(output_root, clock=clock)
    return MappingProxyType(
        {
            producer: executor
            for producer in sorted(DeterministicInventoryExecutor._PRODUCERS)
        }
    )


class ReV2Controller:
    """Recover, plan, and durably execute at most one WorkItem per call."""

    def __init__(
        self,
        context: ReV2RunContext,
        *,
        executor_registry: Mapping[str, WorkExecutor] | None = None,
        executor: WorkExecutor | None = None,
        process_inspector: ProcessInspector | object | None = None,
        process_identity_factory: ProcessIdentityFactory | None = None,
        clock: Callable[[], str] | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(context, ReV2RunContext):
            raise ReV2ControllerError("controller requires a ReV2RunContext")
        if executor is not None and executor_registry is not None:
            raise ReV2ControllerError(
                "executor and executor_registry are mutually exclusive"
            )
        self.context = context
        self._clock = clock or _canonical_utc_now
        self._process_inspector = process_inspector or ProcessInspector()
        self._process_identity_factory = (
            process_identity_factory or _default_process_identity
        )
        self._fault_hook = fault_hook
        if executor is not None:
            producers = {template.producer_id for template in context.graph.templates}
            executor_registry = {producer: executor for producer in producers}
        if executor_registry is None:
            executor_registry = production_executor_registry(
                context.paths.root / ".execution", clock=self._clock
            )
        self._executors = MappingProxyType(dict(executor_registry))
        if any(
            not isinstance(producer, str) or not producer
            for producer in self._executors
        ):
            raise ReV2ControllerError("executor registry keys must be producer IDs")

    def run_once(self) -> ReV2ControllerResult:
        """Recover first, then plan and dispatch no more than one item."""
        with self._controller_lock():
            recovery = self._recover()
            terminal = _terminal_result(recovery)
            if terminal is not None:
                return terminal
            paused = _paused_result(recovery)
            if paused is not None:
                return paused

            now = _timestamp(self._clock(), "controller clock")
            try:
                budget = evaluate_budget(
                    recovery.manifest.initial_budget_policy,
                    recovery.events,
                    now=now,
                )
                decision = plan_next(
                    self.context.graph,
                    recovery.ledger,
                    budget,
                    requested_goals=recovery.manifest.requested_goals,
                )
            except (ReV2BudgetError, ReV2PlanError) as exc:
                raise ReV2ControllerError(f"planning failed: {exc}") from exc
            self._record_plan(decision, now)

            if not decision.ready:
                if _goals_satisfied(decision):
                    return self._complete(decision, now)
                reason_code, reason = _blocked_reason(decision)
                return self._pause(reason_code, reason, decision, now)

            item = decision.ready[0]
            _validate_item_certifier(self.context, item)
            try:
                attempt_kind, attempt_index = next_dispatch_attempt(
                    self.context.event_store.replay(), item
                )
            except (ReV2EventError, ReV2RecoveryError) as exc:
                raise ReV2ControllerError(
                    f"cannot select dispatch attempt: {exc}"
                ) from exc
            exhausted = _attempt_exhaustion(item, attempt_kind, budget)
            if exhausted is not None:
                return self._pause(
                    f"{exhausted}_exhausted",
                    f"The {exhausted} budget is exhausted for {item.work_item_id}.",
                    decision,
                    now,
                )
            selected = self._executors.get(item.producer_id)
            if selected is None:
                return self._pause(
                    "producer_not_registered",
                    (
                        "No pinned RE v2 executor is registered for producer "
                        f"{item.producer_id}."
                    ),
                    decision,
                    now,
                )
            return self._dispatch(
                item,
                selected,
                decision,
                attempt_kind=attempt_kind,
                attempt_index=attempt_index,
                now=now,
            )

    def run_until_stopped(self, *, max_steps: int = 10_000) -> ReV2ControllerResult:
        """Run serially until a durable pause or terminal result is reached."""
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps <= 0
        ):
            raise ReV2ControllerError("max_steps must be a positive integer")
        for _step in range(max_steps):
            result = self.run_once()
            if result.status != "active":
                return result
        raise ReV2ControllerError(
            "controller step limit reached without a paused or terminal outcome"
        )

    def _recover(self) -> ReV2RecoveryResult:
        try:
            return recover_run(
                self.context,
                process_inspector=self._process_inspector,
                clock=self._clock,
                fault_hook=self._fault_hook,
            )
        except ReV2RecoveryError:
            raise
        except Exception as exc:
            raise ReV2ControllerError(f"recovery failed: {exc}") from exc

    def _record_plan(self, decision: PlanDecision, occurred_at: str) -> None:
        work_item_ids = sorted({item.work_item_id for item in decision.ready})
        history = self.context.event_store.replay()
        prior = next(
            (event for event in reversed(history) if event.type == "work_planned"),
            None,
        )
        if prior is not None and tuple(prior.payload["work_item_ids"]) == tuple(
            work_item_ids
        ):
            return
        self.context.event_store.append(
            "work_planned",
            {"work_item_ids": work_item_ids},
            occurred_at=occurred_at,
        )
        self._fault("work_planned")

    def _dispatch(
        self,
        item: WorkItem,
        executor: WorkExecutor,
        decision: PlanDecision,
        *,
        attempt_kind: str,
        attempt_index: int,
        now: str,
    ) -> ReV2ControllerResult:
        try:
            identity = self._process_identity_factory(
                item, attempt_kind, attempt_index, now
            )
        except Exception as exc:
            raise ReV2ControllerError(
                f"cannot create dispatch process identity: {exc}"
            ) from exc
        if not isinstance(identity, ProcessIdentity):
            raise ReV2ControllerError(
                "process_identity_factory must return ProcessIdentity"
            )
        try:
            lease = self.context.candidate_store.begin(
                item,
                identity,
                leased_at=now,
            )
            self._fault("lease_written")
            self.context.event_store.append(
                "dispatch_leased",
                {
                    "dispatch_id": lease.dispatch_id,
                    "work_item_id": item.work_item_id,
                },
                occurred_at=lease.leased_at,
            )
            self._fault("dispatch_leased")
            self.context.event_store.append(
                "dispatch_started",
                {
                    "attempt_index": attempt_index,
                    "attempt_kind": attempt_kind,
                    "dispatch_id": lease.dispatch_id,
                    "work_item_id": item.work_item_id,
                },
                occurred_at=lease.leased_at,
            )
            self._fault("dispatch_started")

            outcome = executor.execute(
                self.context.snapshot.read_root, item, lease
            )
            if (
                not isinstance(outcome, tuple)
                or len(outcome) != 2
                or not isinstance(outcome[0], Path)
                or not isinstance(outcome[1], ExecutionObservation)
            ):
                raise ReV2ControllerError(
                    "executor must return (Path, ExecutionObservation)"
                )
            output_root, observation = outcome
            self._fault("provider_terminated")
            candidate = self.context.candidate_store.persist(
                lease, output_root, observation
            )
            self._fault("candidate_renamed")
            self.context.event_store.append(
                "dispatch_observed",
                {
                    "dispatch_id": lease.dispatch_id,
                    "observation": observation.to_json_dict(),
                    "work_item_id": item.work_item_id,
                },
                occurred_at=observation.ended_at,
            )
            self._fault("dispatch_observed")
            self.context.event_store.append(
                "candidate_persisted",
                {
                    "candidate_id": candidate.candidate_id,
                    "dispatch_id": candidate.dispatch_id,
                    "work_item_id": candidate.work_item_id,
                },
                occurred_at=candidate.persisted_at,
            )
            self._fault("candidate_persisted")
            recovered = self._recover()
        except ReV2ControllerError:
            raise
        except (
            ReV2CandidateError,
            ReV2EventError,
            ReV2LedgerError,
            ReV2ProjectionError,
        ) as exc:
            raise ReV2ControllerError(f"dispatch persistence failed: {exc}") from exc
        return ReV2ControllerResult(
            status="active",
            reason_code="work_item_processed",
            reason="One ready WorkItem was durably processed.",
            work_item_id=item.work_item_id,
            projection=recovered.projection,
            plan=decision,
        )

    def _pause(
        self,
        reason_code: str,
        reason: str,
        decision: PlanDecision,
        occurred_at: str,
    ) -> ReV2ControllerResult:
        try:
            self.context.event_store.append(
                "run_paused",
                {"reason": reason, "reason_code": reason_code},
                occurred_at=occurred_at,
            )
            ledger = self.context.ledger.replay()
            projection = rebuild_projection(self.context.paths, ledger)
        except (ReV2EventError, ReV2LedgerError, ReV2ProjectionError) as exc:
            raise ReV2ControllerError(f"cannot persist continuable pause: {exc}") from exc
        self._fault("run_paused")
        return ReV2ControllerResult(
            status="paused",
            reason_code=reason_code,
            reason=reason,
            work_item_id=None,
            projection=projection,
            plan=decision,
        )

    def _complete(
        self, decision: PlanDecision, occurred_at: str
    ) -> ReV2ControllerResult:
        reason = "Every requested goal has an exact accepted certification."
        try:
            self.context.event_store.append(
                "run_completed", {"reason": reason}, occurred_at=occurred_at
            )
            ledger = self.context.ledger.replay()
            projection = rebuild_projection(self.context.paths, ledger)
        except (ReV2EventError, ReV2LedgerError, ReV2ProjectionError) as exc:
            raise ReV2ControllerError(f"cannot persist run completion: {exc}") from exc
        self._fault("run_completed")
        return ReV2ControllerResult(
            status="complete",
            reason_code="requested_goals_satisfied",
            reason=reason,
            work_item_id=None,
            projection=projection,
            plan=decision,
        )

    def _fault(self, boundary: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(boundary)

    @contextmanager
    def _controller_lock(self) -> Iterator[None]:
        path = self.context.paths.root / "controller.lock"
        if path.is_symlink():
            raise ReV2ControllerError(f"controller lock is a symlink: {path}")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ReV2ControllerError(f"cannot open controller lock: {exc}") from exc
        try:
            _flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                _flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _goals_satisfied(decision: PlanDecision) -> bool:
    active = tuple(
        explanation
        for explanation in decision.explanations.values()
        if explanation.reason_code != "goal_not_requested"
    )
    return all(explanation.action == "reuse" for explanation in active)


def _blocked_reason(decision: PlanDecision) -> tuple[str, str]:
    active = tuple(
        explanation
        for explanation in decision.explanations.values()
        if explanation.reason_code != "goal_not_requested"
        and explanation.action != "reuse"
    )
    if not active:
        return (
            "requested_goals_not_satisfied",
            "Requested goals are not backed by exact accepted certifications.",
        )
    priority = {
        "blocked_budget": 0,
        "reject_incompatible": 1,
        "blocked_dependency": 2,
        "generate": 3,
    }
    selected = min(
        active,
        key=lambda item: (
            priority.get(item.action, 9),
            item.reason_code,
            item.work_item_id,
        ),
    )
    return selected.reason_code, selected.reason


def _attempt_exhaustion(
    item: WorkItem, kind: str, budget: BudgetDecision
) -> str | None:
    item_id = item.work_item_id
    if kind == "semantic_repair":
        limit = min(item.max_semantic_rounds, budget.semantic_round_limit)
        if budget.semantic_rounds.get(item_id, 0) >= limit:
            return "semantic_rounds"
    elif kind == "result_contract_retry":
        limit = min(
            item.max_result_contract_retries,
            budget.result_contract_retry_limit,
        )
        if budget.result_contract_retries.get(item_id, 0) >= limit:
            return "result_contract_retries"
    return None


def _validate_item_certifier(context: ReV2RunContext, item: WorkItem) -> None:
    verifier_id = getattr(context.certifier, "verifier_id", None)
    verifier_version = getattr(context.certifier, "verifier_version", None)
    if verifier_id != item.verifier_id or verifier_version != item.verifier_version:
        raise ReV2ControllerError(
            "pinned certifier does not match the ready WorkItem verifier"
        )


def _terminal_result(
    recovery: ReV2RecoveryResult,
) -> ReV2ControllerResult | None:
    if not recovery.events:
        return None
    event = recovery.events[-1]
    statuses = {
        "run_completed": ("complete", "requested_goals_satisfied"),
        "run_finalized_partial": ("finalized_partial", "run_finalized_partial"),
        "run_failed": ("failed", "run_failed"),
    }
    selected = statuses.get(event.type)
    if selected is None:
        return None
    status, reason_code = selected
    return ReV2ControllerResult(
        status=status,  # type: ignore[arg-type]
        reason_code=reason_code,
        reason=str(event.payload["reason"]),
        work_item_id=None,
        projection=recovery.projection,
        plan=None,
    )


def _paused_result(
    recovery: ReV2RecoveryResult,
) -> ReV2ControllerResult | None:
    paused: EventRecord | None = None
    for event in recovery.events:
        if event.type == "run_paused":
            paused = event
        elif event.type == "run_resumed":
            paused = None
    if paused is None:
        return None
    return ReV2ControllerResult(
        status="paused",
        reason_code=str(paused.payload["reason_code"]),
        reason=str(paused.payload["reason"]),
        work_item_id=None,
        projection=recovery.projection,
        plan=None,
    )


def _default_process_identity(
    item: WorkItem, attempt_kind: str, attempt_index: int, now: str
) -> ProcessIdentity:
    pid = os.getpid()
    identity = ProcessInspector()._probe(pid)
    if identity is None:
        raise ReV2ControllerError("current controller process is not inspectable")
    return ProcessIdentity(
        pid=pid,
        process_start_identity=identity,
        command_hash=content_digest(
            {
                "attempt_index": attempt_index,
                "attempt_kind": attempt_kind,
                "producer_id": item.producer_id,
                "producer_protocol_version": item.producer_protocol_version,
                "work_item_id": item.work_item_id,
            }
        ),
        provider_identity=content_digest(
            {
                "producer_id": item.producer_id,
                "producer_protocol_version": item.producer_protocol_version,
            }
        ),
        started_at=now,
    )


def _snapshot_inventory(root: Path) -> list[dict[str, object]]:
    if root.is_symlink() or not root.is_dir():
        raise ReV2ControllerError("snapshot root is not a safe directory")
    entries: list[dict[str, object]] = []
    for directory, names, files in os.walk(root, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in names:
            path = base / name
            if path.is_symlink():
                raise ReV2ControllerError("snapshot inventory rejects symlinks")
        for name in files:
            path = base / name
            if base == root and name == ".git":
                continue
            if path.is_symlink():
                raise ReV2ControllerError("snapshot inventory rejects symlinks")
            info = path.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ReV2ControllerError("snapshot inventory rejects special files")
            payload = path.read_bytes()
            entries.append(
                {
                    "digest": content_digest(payload),
                    "mode": stat.S_IMODE(info.st_mode),
                    "path": path.relative_to(root).as_posix(),
                    "size": len(payload),
                }
            )
    return sorted(entries, key=lambda item: str(item["path"]))


def _ensure_output_root(path: Path) -> None:
    if path.is_symlink():
        raise ReV2ControllerError(f"execution output root is a symlink: {path}")
    if path.exists():
        if not path.is_dir():
            raise ReV2ControllerError(
                f"execution output root is not a directory: {path}"
            )
        return
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise ReV2ControllerError(
            f"execution output parent is not a safe directory: {parent}"
        )
    path.mkdir(mode=0o700)


def _timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReV2ControllerError(f"{field} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ReV2ControllerError(f"{field} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ReV2ControllerError(f"{field} must be an RFC3339 timestamp")
    return value


def _elapsed_ms(started_at: str, ended_at: str) -> int:
    start = datetime.fromisoformat(
        started_at[:-1] + "+00:00" if started_at.endswith("Z") else started_at
    )
    end = datetime.fromisoformat(
        ended_at[:-1] + "+00:00" if ended_at.endswith("Z") else ended_at
    )
    if end < start:
        raise ReV2ControllerError("executor clock moved backwards")
    delta = end - start
    return (
        delta.days * 86_400_000
        + delta.seconds * 1_000
        + delta.microseconds // 1_000
    )


def _canonical_utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _flock(fd: int, operation: int) -> None:
    while True:
        try:
            fcntl.flock(fd, operation)
            return
        except InterruptedError:
            continue


__all__ = (
    "DeterministicInventoryExecutor",
    "ProcessIdentityFactory",
    "ReV2Controller",
    "ReV2ControllerError",
    "ReV2ControllerResult",
    "WorkExecutor",
    "production_executor_registry",
)
