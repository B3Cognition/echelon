"""Single-dispatch orchestration for the pinned RE v2 execution kernel."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import inspect
import os
from pathlib import Path
import secrets
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
from .model import ExecutionObservation, RunManifest, WorkItem
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
    """Common immutable metadata for one pinned execution implementation."""

    @property
    def provider_name(self) -> str: ...

    @property
    def provider_contract_hash(self) -> str: ...

    @property
    def execution_mode(self) -> Literal["in_process", "provider_process"]: ...


class InProcessWorkExecutor(WorkExecutor, Protocol):
    """Execute deterministic work in the already-leased controller process."""

    def execute(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]: ...


class ProviderProcessHandle(Protocol):
    """Owned gate for one child that cannot work before durable admission.

    The provider child must remain blocked while the handle is unreleased.  If
    the controller dies, the provider-side gate must observe loss of ownership
    and exit without provider side effects.  ``abort_unleased`` synchronously
    stops and reaps that child; ``close`` releases all remaining handle-owned
    resources and is safe after either abort or release.
    """

    @property
    def process_identity(self) -> ProcessIdentity: ...

    def release_leased(self) -> None: ...

    def abort_unleased(self) -> None: ...

    def close(self) -> None: ...


class ProviderProcessWorkExecutor(WorkExecutor, Protocol):
    """Create a gated child, then release/collect it only after durable leasing.

    ``start`` may perform safe process creation only.  The child must not perform
    provider work before ``collect`` and must self-terminate when an unleased
    controller disappears.  ``collect`` is the first provider-side-effect gate.
    """

    def start(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        dispatch_id: str,
    ) -> ProviderProcessHandle: ...

    def collect(
        self,
        snapshot_root: Path,
        work_item: WorkItem,
        lease: DispatchLease,
    ) -> tuple[Path, ExecutionObservation]: ...


ProcessIdentityFactory = Callable[[WorkItem, str, int, str], ProcessIdentity]
ExecutorKey = tuple[str, str, str, str, str, str]


@dataclass(frozen=True, slots=True)
class ExecutorRegistration:
    """Immutable provider and work-protocol binding for one executor."""

    provider_name: str
    provider_contract_hash: str
    producer_id: str
    producer_protocol_version: str
    layer: str
    result_contract_id: str
    execution_mode: Literal["in_process", "provider_process"]
    executor: WorkExecutor

    def __post_init__(self) -> None:
        if not _valid_executor_key(self.key):
            raise ReV2ControllerError(
                "executor registration must contain exact provider and protocol pins"
            )
        if self.execution_mode not in {"in_process", "provider_process"}:
            raise ReV2ControllerError("executor registration has an invalid mode")
        declared_mode = _executor_execution_mode(self.executor)
        if declared_mode != self.execution_mode:
            raise ReV2ControllerError(
                "executor-declared mode does not match registration"
            )
        required_methods = (
            ("execute",)
            if self.execution_mode == "in_process"
            else ("start", "collect")
        )
        if any(
            not callable(getattr(self.executor, method, None))
            for method in required_methods
        ):
            contract = (
                "execute(snapshot, work, lease)"
                if self.execution_mode == "in_process"
                else "start(snapshot, work, dispatch_id) and collect(snapshot, work, lease)"
            )
            raise ReV2ControllerError(
                f"registered {self.execution_mode} executor must provide {contract}"
            )
        declared_binding = _executor_provider_binding(self.executor)
        if declared_binding != (
            self.provider_name,
            self.provider_contract_hash,
        ):
            raise ReV2ControllerError(
                "executor-declared provider metadata does not match registration"
            )

    @property
    def key(self) -> ExecutorKey:
        return (
            self.provider_name,
            self.provider_contract_hash,
            self.producer_id,
            self.producer_protocol_version,
            self.layer,
            self.result_contract_id,
        )


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
        provider_contract_hash: str,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.output_root = Path(output_root)
        self._provider_contract_hash = provider_contract_hash
        self._clock = clock or _canonical_utc_now

    @property
    def provider_name(self) -> str:
        return "deterministic-inventory"

    @property
    def provider_contract_hash(self) -> str:
        return self._provider_contract_hash

    @property
    def execution_mode(self) -> Literal["in_process"]:
        return "in_process"

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
    provider_contract: Mapping[str, object],
    clock: Callable[[], str] | None = None,
) -> Mapping[ExecutorKey, ExecutorRegistration]:
    """Return only the deterministic source/partition L0 producers."""
    provider_name = str(provider_contract.get("provider"))
    if provider_name != "deterministic-inventory":
        return MappingProxyType({})
    provider_contract_hash = content_digest(provider_contract)
    executor = DeterministicInventoryExecutor(
        output_root,
        provider_contract_hash=provider_contract_hash,
        clock=clock,
    )
    registrations = tuple(
        ExecutorRegistration(
            provider_name=provider_name,
            provider_contract_hash=provider_contract_hash,
            producer_id=producer,
            producer_protocol_version="re-v2-l0-v1",
            layer="L0",
            result_contract_id="deterministic-inventory-v1",
            execution_mode="in_process",
            executor=executor,
        )
        for producer in sorted(DeterministicInventoryExecutor._PRODUCERS)
    )
    return MappingProxyType(
        {registration.key: registration for registration in registrations}
    )


class ReV2Controller:
    """Recover, plan, and durably execute at most one WorkItem per call."""

    def __init__(
        self,
        context: ReV2RunContext,
        *,
        executor_registry: Mapping[ExecutorKey, ExecutorRegistration] | None = None,
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
        manifest = context.manifest
        provider_name, provider_contract_hash = _provider_binding(manifest)
        if executor is not None:
            declared_binding = _executor_provider_binding(executor)
            declared_mode = _executor_execution_mode(executor)
            if declared_binding != (provider_name, provider_contract_hash):
                raise ReV2ControllerError(
                    "convenience executor does not match manifest provider contract"
                )
            generated = tuple(
                ExecutorRegistration(
                    provider_name=declared_binding[0],
                    provider_contract_hash=declared_binding[1],
                    producer_id=template.producer_id,
                    producer_protocol_version=template.producer_protocol_version,
                    layer=template.layer,
                    result_contract_id=template.result_contract_id,
                    execution_mode=declared_mode,
                    executor=executor,
                )
                for template in context.graph.templates
            )
            executor_registry = {
                registration.key: registration for registration in generated
            }
        if executor_registry is None:
            executor_registry = production_executor_registry(
                context.paths.root / ".execution",
                provider_contract=manifest.to_json_dict()["provider_contract"],
                clock=self._clock,
            )
        registrations: dict[ExecutorKey, ExecutorRegistration] = {}
        for key, registration in executor_registry.items():
            if not _valid_executor_key(key):
                raise ReV2ControllerError(
                    "executor registry keys must be exact provider protocol tuples"
                )
            if type(registration) is not ExecutorRegistration:
                raise ReV2ControllerError(
                    "executor registry values must be frozen ExecutorRegistration objects"
                )
            if registration.key != key:
                raise ReV2ControllerError(
                    "executor registry key does not match registration metadata"
                )
            if _executor_provider_binding(registration.executor) != (
                registration.provider_name,
                registration.provider_contract_hash,
            ):
                raise ReV2ControllerError(
                    "executor-declared provider metadata does not match registration"
                )
            if _executor_execution_mode(registration.executor) != (
                registration.execution_mode
            ):
                raise ReV2ControllerError(
                    "executor-declared mode does not match registration"
                )
            if (
                registration.provider_name != provider_name
                or registration.provider_contract_hash != provider_contract_hash
            ):
                raise ReV2ControllerError(
                    "executor registration does not match manifest provider contract"
                )
            registrations[key] = registration
        self._executors = MappingProxyType(registrations)

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

            if not decision.ready:
                self._record_plan(decision, now)
                if _goals_satisfied(decision):
                    return self._complete(decision, now)
                reason_code, reason = _blocked_reason(decision)
                return self._pause(reason_code, reason, decision, now)

            item = decision.ready[0]
            _validate_item_certifier(self.context, item)
            provider_name, provider_contract_hash = _provider_binding(
                recovery.manifest
            )
            selected = self._executors.get(
                _executor_key(
                    item,
                    provider_name=provider_name,
                    provider_contract_hash=provider_contract_hash,
                )
            )
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
                _validate_selected_executor_binding(
                    selected,
                    provider_name=provider_name,
                    provider_contract_hash=provider_contract_hash,
                )
                self._record_plan(decision, now)
                return self._pause(
                    f"{exhausted}_exhausted",
                    f"The {exhausted} budget is exhausted for {item.work_item_id}.",
                    decision,
                    now,
                )
            _validate_selected_executor_binding(
                selected,
                provider_name=provider_name,
                provider_contract_hash=provider_contract_hash,
            )
            self._record_plan(decision, now)
            return self._dispatch(
                item,
                selected,
                decision,
                attempt_kind=attempt_kind,
                attempt_index=attempt_index,
                manifest_provider_name=provider_name,
                manifest_provider_contract_hash=provider_contract_hash,
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
        registration: ExecutorRegistration,
        decision: PlanDecision,
        *,
        attempt_kind: str,
        attempt_index: int,
        manifest_provider_name: str,
        manifest_provider_contract_hash: str,
        now: str,
    ) -> ReV2ControllerResult:
        _validate_selected_executor_binding(
            registration,
            provider_name=manifest_provider_name,
            provider_contract_hash=manifest_provider_contract_hash,
        )
        dispatch_id: str | None = None
        provider_handle: object | None = None
        provider_released = False
        try:
            if registration.execution_mode == "provider_process":
                dispatch_id = _new_dispatch_id(
                    item,
                    attempt_kind=attempt_kind,
                    attempt_index=attempt_index,
                )
                try:
                    provider_handle = _start_provider_process(
                        registration.executor,
                        self.context.snapshot.read_root,
                        item,
                        dispatch_id,
                    )
                except ReV2ControllerError:
                    raise
                except Exception as exc:
                    raise ReV2ControllerError(
                        f"cannot safely start provider process: {exc}"
                    ) from exc
                self._fault("provider_started")
                identity = _provider_process_identity(provider_handle)
                if identity.pid == os.getpid():
                    raise ReV2ControllerError(
                        "provider_process executor returned the controller PID"
                    )
                leased_at = _timestamp(
                    self._clock(), "post-start controller clock"
                )
                _validate_selected_executor_binding(
                    registration,
                    provider_name=manifest_provider_name,
                    provider_contract_hash=manifest_provider_contract_hash,
                )
            else:
                try:
                    identity = self._process_identity_factory(
                        item, attempt_kind, attempt_index, now
                    )
                except Exception as exc:
                    raise ReV2ControllerError(
                        f"cannot create in-process dispatch identity: {exc}"
                    ) from exc
                if not isinstance(identity, ProcessIdentity):
                    raise ReV2ControllerError(
                        "process_identity_factory must return ProcessIdentity"
                    )
                leased_at = now
            lease = self.context.candidate_store.begin(
                item,
                identity,
                dispatch_id=dispatch_id,
                leased_at=leased_at,
            )
            if provider_handle is not None:
                _release_provider_process(provider_handle)
                provider_released = True
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

            _validate_selected_executor_binding(
                registration,
                provider_name=manifest_provider_name,
                provider_contract_hash=manifest_provider_contract_hash,
            )
            outcome = _collect_execution(
                registration,
                self.context.snapshot.read_root,
                item,
                lease,
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
            if observation.provider_name != registration.provider_name:
                raise ReV2ControllerError(
                    "executor observation provider does not match the manifest"
                )
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
        finally:
            if provider_handle is not None:
                try:
                    if not provider_released:
                        _abort_unleased_provider_process(provider_handle)
                finally:
                    _close_provider_process(provider_handle)
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
    provider_limit = min(
        item.max_provider_attempts, budget.provider_attempt_limit
    )
    if budget.provider_attempts.get(item_id, 0) >= provider_limit:
        return "provider_attempts"
    if kind in {"initial_generation", "semantic_repair"}:
        generation_limit = min(
            item.max_generation_attempts,
            budget.generation_attempt_limit,
        )
        if budget.generation_attempts.get(item_id, 0) >= generation_limit:
            return "generation_attempts"
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


def _executor_key(
    item: object,
    *,
    provider_name: str,
    provider_contract_hash: str,
) -> ExecutorKey:
    output_key = getattr(item, "output_key", None)
    layer = getattr(output_key, "layer", None)
    if layer is None:
        layer = getattr(item, "layer", None)
    return (
        provider_name,
        provider_contract_hash,
        str(getattr(item, "producer_id")),
        str(getattr(item, "producer_protocol_version")),
        str(layer),
        str(getattr(item, "result_contract_id")),
    )


def _valid_executor_key(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 6
        and all(isinstance(item, str) and item for item in value)
        and value[1].startswith("sha256:")
        and len(value[1]) == 71
        and all(character in "0123456789abcdef" for character in value[1][7:])
    )


def _executor_provider_binding(executor: object) -> tuple[str, str]:
    for field in ("provider_name", "provider_contract_hash"):
        descriptor = inspect.getattr_static(type(executor), field, None)
        if (
            not isinstance(descriptor, property)
            or descriptor.fset is not None
            or descriptor.fdel is not None
        ):
            raise ReV2ControllerError(
                "executor provider metadata must use immutable read-only properties"
            )
    provider_name = getattr(executor, "provider_name", None)
    provider_contract_hash = getattr(executor, "provider_contract_hash", None)
    if not isinstance(provider_name, str) or not provider_name:
        raise ReV2ControllerError("executor provider_name is invalid")
    if not (
        isinstance(provider_contract_hash, str)
        and provider_contract_hash.startswith("sha256:")
        and len(provider_contract_hash) == 71
        and all(
            character in "0123456789abcdef"
            for character in provider_contract_hash[7:]
        )
    ):
        raise ReV2ControllerError("executor provider_contract_hash is invalid")
    return provider_name, provider_contract_hash


def _executor_execution_mode(
    executor: object,
) -> Literal["in_process", "provider_process"]:
    descriptor = inspect.getattr_static(type(executor), "execution_mode", None)
    if (
        not isinstance(descriptor, property)
        or descriptor.fset is not None
        or descriptor.fdel is not None
    ):
        raise ReV2ControllerError(
            "executor execution_mode must use an immutable read-only property"
        )
    mode = getattr(executor, "execution_mode", None)
    if mode not in {"in_process", "provider_process"}:
        raise ReV2ControllerError("executor execution_mode is invalid")
    return mode


def _validate_selected_executor_binding(
    registration: ExecutorRegistration,
    *,
    provider_name: str,
    provider_contract_hash: str,
) -> None:
    registration_binding = (
        registration.provider_name,
        registration.provider_contract_hash,
    )
    manifest_binding = (provider_name, provider_contract_hash)
    declared_binding = _executor_provider_binding(registration.executor)
    if (
        registration_binding != manifest_binding
        or declared_binding != registration_binding
        or _executor_execution_mode(registration.executor)
        != registration.execution_mode
    ):
        raise ReV2ControllerError(
            "selected executor provider binding does not match its immutable "
            "registration and manifest provider contract"
        )


def _start_provider_process(
    executor: object,
    snapshot_root: Path,
    work_item: WorkItem,
    dispatch_id: str,
) -> object:
    start = getattr(executor, "start", None)
    if not callable(start):
        raise ReV2ControllerError(
            "provider_process executor has no start method"
        )
    return start(snapshot_root, work_item, dispatch_id)


def _provider_process_identity(handle: object) -> ProcessIdentity:
    for method_name in ("release_leased", "abort_unleased", "close"):
        if not callable(getattr(handle, method_name, None)):
            raise ReV2ControllerError(
                "provider_process start must return an owned gated handle with "
                "release_leased(), abort_unleased(), and close()"
            )
    identity = getattr(handle, "process_identity", None)
    if not isinstance(identity, ProcessIdentity):
        raise ReV2ControllerError(
            "provider_process gated handle must expose the actual ProcessIdentity"
        )
    return identity


def _release_provider_process(handle: object) -> None:
    release = getattr(handle, "release_leased", None)
    if not callable(release):
        raise ReV2ControllerError(
            "provider_process gated handle has no release_leased method"
        )
    release()


def _abort_unleased_provider_process(handle: object) -> None:
    abort = getattr(handle, "abort_unleased", None)
    if callable(abort):
        abort()


def _close_provider_process(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        close()


def _collect_execution(
    registration: ExecutorRegistration,
    snapshot_root: Path,
    work_item: WorkItem,
    lease: DispatchLease,
) -> tuple[Path, ExecutionObservation]:
    method_name = (
        "execute"
        if registration.execution_mode == "in_process"
        else "collect"
    )
    method = getattr(registration.executor, method_name, None)
    if not callable(method):
        raise ReV2ControllerError(
            f"{registration.execution_mode} executor has no {method_name} method"
        )
    return method(snapshot_root, work_item, lease)


def _new_dispatch_id(
    work_item: WorkItem,
    *,
    attempt_kind: str,
    attempt_index: int,
) -> str:
    suffix = content_digest(
        {
            "attempt_index": attempt_index,
            "attempt_kind": attempt_kind,
            "nonce": secrets.token_hex(32),
            "work_item_id": work_item.work_item_id,
        }
    ).removeprefix("sha256:")
    return f"dispatch-{suffix}"


def _provider_binding(manifest: RunManifest) -> tuple[str, str]:
    provider_contract = manifest.to_json_dict()["provider_contract"]
    if not isinstance(provider_contract, dict):
        raise ReV2ControllerError("manifest provider contract is not canonical")
    return str(provider_contract["provider"]), content_digest(provider_contract)


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
    "ExecutorKey",
    "ExecutorRegistration",
    "InProcessWorkExecutor",
    "ProcessIdentityFactory",
    "ProviderProcessHandle",
    "ProviderProcessWorkExecutor",
    "ReV2Controller",
    "ReV2ControllerError",
    "ReV2ControllerResult",
    "WorkExecutor",
    "production_executor_registry",
)
