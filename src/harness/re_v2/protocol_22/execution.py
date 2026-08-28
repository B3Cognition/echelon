"""Durable protocol-2.2 execution inputs, captures, and commit authority."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import fcntl
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
from types import MappingProxyType
from typing import Callable, Iterator, Literal, Mapping, TypeAlias

from harness.re_v2.candidates import ProcessIdentity, ReV2CandidateError
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.run_store import ReV2Paths

from .authorities import (
    InstalledAuthorityRegistry,
    Protocol22AuthorityError,
    validate_installed_authorities,
)
from .cli_provider import calculate_shared_cli_dispatch_reservation
from .executors import (
    IN_PROCESS_CALCULATOR_ID,
    ExecutorContractCatalogV1,
    ExecutorContractEntryV1,
)
from .model import (
    DeterministicInvocationV1,
    ExecutionCaptureCommitV1,
    ExecutionCaptureV1,
    ExecutionInputV1,
    PersistedCandidateV2,
    ProviderRequestEnvelopeV1,
    WorkItemV2,
)
from .provider import (
    DispatchReservationV1,
    Protocol22ProviderError,
    RawExecutionResultV1,
    RequestTokenizerV1,
    calculate_bounded_dispatch_reservation,
    render_provider_request_envelope,
    validate_provider_content_authority,
)
from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    integer_or_none,
    literal,
    load_canonical_object,
    nonnegative_int,
    one_of,
    positive_int,
    safe_id,
    utc_timestamp,
)


FaultHook = Callable[[str], None]
ProcessProbe = Callable[[int], str | None]
_STDOUT_RETAINED_LIMIT = 128 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_HAS_DIRFD = all(
    operation in os.supports_dir_fd
    for operation in (os.open, os.mkdir, os.stat, os.unlink)
)


class Protocol22ExecutionError(RuntimeError):
    """Raised when execution authority is unsafe, incomplete, or conflicting."""


@dataclass(frozen=True, slots=True)
class CandidateInventoryEntryV1:
    relative_path: str
    object_kind: Literal["regular", "symlink", "special"]
    mode: int
    byte_count: int
    content_hash: str | None

    FIELDS = (
        "relative_path",
        "object_kind",
        "mode",
        "byte_count",
        "content_hash",
    )

    def __post_init__(self) -> None:
        _candidate_relative_path(self.relative_path)
        one_of(
            self.object_kind,
            {"regular", "symlink", "special"},
            "CandidateInventoryEntryV1.object_kind",
        )
        if (
            not isinstance(self.mode, int)
            or isinstance(self.mode, bool)
            or not 0 <= self.mode <= 0o7777
        ):
            raise Protocol22ExecutionError(
                "candidate inventory mode must be an integer in [0, 4095]"
            )
        try:
            nonnegative_int(
                self.byte_count,
                "CandidateInventoryEntryV1.byte_count",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if self.object_kind == "regular":
            try:
                digest_value(
                    self.content_hash,
                    "CandidateInventoryEntryV1.content_hash",
                )
            except Protocol22SchemaError as exc:
                raise Protocol22ExecutionError(str(exc)) from exc
        elif self.content_hash is not None or self.byte_count != 0:
            raise Protocol22ExecutionError(
                "symlink/special candidate entries require null hash and zero bytes"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "CandidateInventoryEntryV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
            return cls(**{field: raw[field] for field in cls.FIELDS})
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class CandidateInventoryV1:
    schema_version: int
    dispatch_id: str
    work_item_id: str
    entries: tuple[CandidateInventoryEntryV1, ...]

    FIELDS = ("schema_version", "dispatch_id", "work_item_id", "entries")

    def __post_init__(self) -> None:
        try:
            literal(self.schema_version, 1, "CandidateInventoryV1.schema_version")
            safe_id(self.dispatch_id, "CandidateInventoryV1.dispatch_id")
            digest_value(self.work_item_id, "CandidateInventoryV1.work_item_id")
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(item, CandidateInventoryEntryV1) for item in self.entries
        ):
            raise Protocol22ExecutionError(
                "CandidateInventoryV1.entries must contain closed entries"
            )
        entries = tuple(self.entries)
        paths = tuple(item.relative_path for item in entries)
        if paths != tuple(sorted(set(paths), key=lambda item: item.encode("utf-8"))):
            raise Protocol22ExecutionError(
                "candidate inventory paths must be byte-sorted and unique"
            )
        object.__setattr__(self, "entries", entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dispatch_id": self.dispatch_id,
            "work_item_id": self.work_item_id,
            "entries": [item.to_json_dict() for item in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "CandidateInventoryV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        entries = raw["entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol22ExecutionError(
                "CandidateInventoryV1.entries must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            dispatch_id=raw["dispatch_id"],
            work_item_id=raw["work_item_id"],
            entries=tuple(
                CandidateInventoryEntryV1.from_json_dict(item) for item in entries
            ),
        )


@dataclass(frozen=True, slots=True)
class InProcessDispatchReservationV1:
    billable_tokens: Literal[0]
    active_ms: int

    def __post_init__(self) -> None:
        try:
            literal(
                self.billable_tokens,
                0,
                "InProcessDispatchReservationV1.billable_tokens",
            )
            positive_int(
                self.active_ms,
                "InProcessDispatchReservationV1.active_ms",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc


ExecutionReservationV1: TypeAlias = (
    DispatchReservationV1 | InProcessDispatchReservationV1
)


@dataclass(frozen=True, slots=True)
class ProviderExecutionDependenciesV1:
    executor: ExecutorContractEntryV1
    registry: InstalledAuthorityRegistry
    agent_bytes: bytes
    context_bytes: bytes
    response_schema_bytes: bytes
    tokenizer: RequestTokenizerV1 | None
    retry_diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.executor, ExecutorContractEntryV1):
            raise Protocol22ExecutionError("provider dependencies require an executor")
        if not isinstance(self.registry, InstalledAuthorityRegistry):
            raise Protocol22ExecutionError(
                "provider dependencies require installed authority"
            )
        for field_name in (
            "agent_bytes",
            "context_bytes",
            "response_schema_bytes",
        ):
            if not isinstance(getattr(self, field_name), bytes):
                raise Protocol22ExecutionError(
                    f"provider dependency {field_name} must be bytes"
                )
        if not isinstance(self.retry_diagnostics, (list, tuple)):
            raise Protocol22ExecutionError(
                "provider retry diagnostics must be an array"
            )
        diagnostics = tuple(self.retry_diagnostics)
        if diagnostics and diagnostics != tuple(sorted(set(diagnostics))):
            raise Protocol22ExecutionError(
                "provider retry diagnostics must be sorted and unique"
            )
        object.__setattr__(self, "retry_diagnostics", diagnostics)
        if self.executor.execution_mode == "api" and self.tokenizer is None:
            raise Protocol22ExecutionError(
                "API provider dependencies require a request tokenizer"
            )
        if self.executor.execution_mode == "cli" and self.tokenizer is not None:
            raise Protocol22ExecutionError(
                "CLI provider dependencies delegate tokenization to the shared provider"
            )


@dataclass(frozen=True, slots=True)
class DeterministicExecutionDependenciesV1:
    executor: ExecutorContractEntryV1
    registry: InstalledAuthorityRegistry
    invocation: DeterministicInvocationV1
    workspace_partition_hash: str | None
    referenced_objects: Mapping[str, bytes] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.executor, ExecutorContractEntryV1):
            raise Protocol22ExecutionError(
                "deterministic dependencies require an executor"
            )
        if not isinstance(self.registry, InstalledAuthorityRegistry):
            raise Protocol22ExecutionError(
                "deterministic dependencies require installed authority"
            )
        if not isinstance(self.invocation, DeterministicInvocationV1):
            raise Protocol22ExecutionError(
                "deterministic dependencies require a closed invocation"
            )
        if self.workspace_partition_hash is not None:
            try:
                digest_value(
                    self.workspace_partition_hash,
                    "deterministic workspace_partition_hash",
                )
            except Protocol22SchemaError as exc:
                raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.referenced_objects, Mapping):
            raise Protocol22ExecutionError("referenced objects must be a mapping")
        copied: dict[str, bytes] = {}
        for object_hash, payload in self.referenced_objects.items():
            try:
                digest_value(object_hash, "referenced object hash")
            except Protocol22SchemaError as exc:
                raise Protocol22ExecutionError(str(exc)) from exc
            if not isinstance(payload, bytes) or content_digest(payload) != object_hash:
                raise Protocol22ExecutionError(
                    "referenced object bytes do not match their content address"
                )
            copied[object_hash] = payload
        object.__setattr__(
            self,
            "referenced_objects",
            MappingProxyType(dict(sorted(copied.items()))),
        )


PreparationDependenciesV1: TypeAlias = (
    ProviderExecutionDependenciesV1 | DeterministicExecutionDependenciesV1
)


@dataclass(frozen=True, slots=True)
class PreparedExecutionV1:
    dispatch_id: str
    execution_input: ExecutionInputV1
    execution_input_hash: str
    provider_envelope: ProviderRequestEnvelopeV1 | None
    provider_envelope_hash: str | None
    reservation: ExecutionReservationV1

    def __post_init__(self) -> None:
        try:
            safe_id(self.dispatch_id, "PreparedExecutionV1.dispatch_id")
            digest_value(
                self.execution_input_hash,
                "PreparedExecutionV1.execution_input_hash",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.execution_input, ExecutionInputV1):
            raise Protocol22ExecutionError("prepared execution input is invalid")
        if (
            self.dispatch_id != self.execution_input.dispatch_id
            or self.execution_input_hash != self.execution_input.identity
        ):
            raise Protocol22ExecutionError(
                "prepared execution identity does not match execution input"
            )
        provider_branch = (
            self.execution_input.agent_contract_hash is not None
            and self.execution_input.context_bundle_hash is not None
            and self.execution_input.deterministic_invocation is None
        )
        if provider_branch:
            if not isinstance(self.reservation, DispatchReservationV1):
                raise Protocol22ExecutionError(
                    "prepared provider reservation authority is invalid"
                )
            if self.provider_envelope is None:
                if (
                    self.provider_envelope_hash is not None
                    or self.execution_input.provider_request_envelope_hash is not None
                ):
                    raise Protocol22ExecutionError(
                        "prepared CLI execution cannot contain an API envelope"
                    )
            elif (
                not isinstance(self.provider_envelope, ProviderRequestEnvelopeV1)
                or self.provider_envelope_hash != self.provider_envelope.identity
                or self.execution_input.provider_request_envelope_hash
                != self.provider_envelope_hash
            ):
                raise Protocol22ExecutionError(
                    "prepared API envelope authority is invalid"
                )
        elif (
            self.provider_envelope_hash is not None
            or self.execution_input.provider_request_envelope_hash is not None
            or not isinstance(self.reservation, InProcessDispatchReservationV1)
        ):
            raise Protocol22ExecutionError(
                "prepared deterministic execution authority is invalid"
            )


@dataclass(frozen=True, slots=True)
class DeterministicRawResultV1:
    artifact_bytes: bytes | None
    stdout: bytes
    stderr: bytes
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    timed_out: bool

    def __post_init__(self) -> None:
        if self.artifact_bytes is not None and not isinstance(
            self.artifact_bytes, bytes
        ):
            raise Protocol22ExecutionError(
                "deterministic artifact must be bytes or null"
            )
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise Protocol22ExecutionError(
                "deterministic execution output must be bytes"
            )
        try:
            utc_timestamp(self.started_at, "DeterministicRawResultV1.started_at")
            utc_timestamp(self.ended_at, "DeterministicRawResultV1.ended_at")
            nonnegative_int(
                self.duration_ms,
                "DeterministicRawResultV1.duration_ms",
            )
            integer_or_none(
                self.exit_code,
                "DeterministicRawResultV1.exit_code",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.timed_out, bool):
            raise Protocol22ExecutionError(
                "DeterministicRawResultV1.timed_out must be boolean"
            )
        if self.artifact_bytes is not None and (self.exit_code != 0 or self.timed_out):
            raise Protocol22ExecutionError(
                "deterministic artifact requires successful local execution"
            )
        _validate_timeline(self.started_at, self.ended_at)


@dataclass(frozen=True, slots=True)
class CapturedExecutionV1:
    capture: ExecutionCaptureV1
    capture_hash: str
    commit: ExecutionCaptureCommitV1

    def __post_init__(self) -> None:
        if not isinstance(self.capture, ExecutionCaptureV1):
            raise Protocol22ExecutionError("captured execution value is invalid")
        try:
            digest_value(self.capture_hash, "CapturedExecutionV1.capture_hash")
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.commit, ExecutionCaptureCommitV1):
            raise Protocol22ExecutionError("captured execution commit is invalid")
        if self.capture_hash != self.capture.identity:
            raise Protocol22ExecutionError(
                "capture identity hash does not match capture bytes"
            )


@dataclass(frozen=True, slots=True)
class ValidatedCaptureClosureV1:
    commit: ExecutionCaptureCommitV1
    capture: ExecutionCaptureV1
    execution_input: ExecutionInputV1
    provider_envelope: ProviderRequestEnvelopeV1 | None
    candidate_inventory: CandidateInventoryV1 | None
    stdout_bytes: bytes
    provider_usage_bytes: bytes | None
    deterministic_artifact_bytes: bytes | None


@dataclass(frozen=True, slots=True)
class Missing:
    dispatch_id: str
    staging_path: Path
    committed_path: Path
    incomplete_staging: bool = False


@dataclass(frozen=True, slots=True)
class StagingReady:
    dispatch_id: str
    path: Path
    commit: ExecutionCaptureCommitV1
    closure: ValidatedCaptureClosureV1


@dataclass(frozen=True, slots=True)
class Committed:
    dispatch_id: str
    path: Path
    commit: ExecutionCaptureCommitV1
    closure: ValidatedCaptureClosureV1
    staging_path: Path | None


@dataclass(frozen=True, slots=True)
class Conflict:
    dispatch_id: str
    staging_path: Path
    committed_path: Path
    reason: str


CaptureCommitState: TypeAlias = Missing | StagingReady | Committed | Conflict


@dataclass(frozen=True, slots=True)
class StartedExecutionLeaseV1:
    schema_version: int
    dispatch_id: str
    work_item_id: str
    execution_input_hash: str
    executor_contract_hash: str
    process_identity: ProcessIdentity

    FIELDS = (
        "schema_version",
        "dispatch_id",
        "work_item_id",
        "execution_input_hash",
        "executor_contract_hash",
        "process_identity",
    )

    def __post_init__(self) -> None:
        try:
            literal(self.schema_version, 1, "StartedExecutionLeaseV1.schema_version")
            safe_id(self.dispatch_id, "StartedExecutionLeaseV1.dispatch_id")
            digest_value(self.work_item_id, "StartedExecutionLeaseV1.work_item_id")
            digest_value(
                self.execution_input_hash,
                "StartedExecutionLeaseV1.execution_input_hash",
            )
            digest_value(
                self.executor_contract_hash,
                "StartedExecutionLeaseV1.executor_contract_hash",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutionError(str(exc)) from exc
        if not isinstance(self.process_identity, ProcessIdentity):
            raise Protocol22ExecutionError("started lease process identity is invalid")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dispatch_id": self.dispatch_id,
            "work_item_id": self.work_item_id,
            "execution_input_hash": self.execution_input_hash,
            "executor_contract_hash": self.executor_contract_hash,
            "process_identity": self.process_identity.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "StartedExecutionLeaseV1":
        try:
            raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
            process = ProcessIdentity.from_json_dict(raw["process_identity"])
            return cls(
                schema_version=raw["schema_version"],
                dispatch_id=raw["dispatch_id"],
                work_item_id=raw["work_item_id"],
                execution_input_hash=raw["execution_input_hash"],
                executor_contract_hash=raw["executor_contract_hash"],
                process_identity=process,
            )
        except (Protocol22SchemaError, ReV2CandidateError, ValueError) as exc:
            raise Protocol22ExecutionError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DispatchPreviewV1:
    """Pure dispatch identity and reservation preview for read-only status."""

    dispatch_id: str
    reservation: DispatchReservationV1 | InProcessDispatchReservationV1


def preview_dispatch_reservation(
    work_item: WorkItemV2,
    attempt_kind: str,
    dependencies: PreparationDependenciesV1,
) -> DispatchPreviewV1:
    """Calculate the exact next reservation without publishing any objects."""
    _validate_item_executor(work_item, dependencies.executor)
    _validate_installed(dependencies.executor, dependencies.registry)
    dispatch_id = _dispatch_id(work_item, attempt_kind)
    executor = dependencies.executor
    if isinstance(dependencies, ProviderExecutionDependenciesV1):
        if (attempt_kind == "initial_generation") != (
            not dependencies.retry_diagnostics
        ):
            raise Protocol22ExecutionError(
                "provider retry diagnostics must exist exactly for retry attempts"
            )
        if executor.execution_mode == "cli":
            return DispatchPreviewV1(
                dispatch_id,
                calculate_shared_cli_dispatch_reservation(
                    dependencies.agent_bytes,
                    dependencies.context_bytes,
                    dependencies.response_schema_bytes,
                    executor,
                    dependencies.retry_diagnostics,
                ),
            )
        if executor.execution_mode != "api":
            raise Protocol22ExecutionError(
                "provider preview requires API or CLI execution mode"
            )
        schema_hash = content_digest(dependencies.response_schema_bytes)
        envelope = render_provider_request_envelope(
            work_item,
            dispatch_id,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            executor,
            schema_hash,
            dependencies.retry_diagnostics,
        )
        reservation = calculate_bounded_dispatch_reservation(
            envelope,
            dependencies.response_schema_bytes,
            executor,
            dependencies.tokenizer,
        )
        return DispatchPreviewV1(dispatch_id, reservation)
    if isinstance(dependencies, DeterministicExecutionDependenciesV1):
        if attempt_kind != "initial_generation":
            raise Protocol22ExecutionError(
                "deterministic preview cannot use a retry attempt"
            )
        if (
            executor.execution_mode != "in_process"
            or executor.reservation_calculator.calculator_id != IN_PROCESS_CALCULATOR_ID
        ):
            raise Protocol22ExecutionError(
                "deterministic preview requires bounded in-process execution"
            )
        _validate_invocation(
            work_item,
            dependencies.invocation,
            dependencies.workspace_partition_hash,
        )
        return DispatchPreviewV1(
            dispatch_id,
            InProcessDispatchReservationV1(
                billable_tokens=0,
                active_ms=executor.limits.max_active_ms_per_dispatch,
            ),
        )
    raise Protocol22ExecutionError(
        "dispatch preview dependencies select no closed execution branch"
    )


def dispatch_id_for(work_item: WorkItemV2, attempt_kind: str) -> str:
    """Return the deterministic dispatch identity without publishing state."""
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22ExecutionError("dispatch identity requires WorkItemV2")
    if attempt_kind not in {
        "initial_generation",
        "result_contract_retry",
        "artifact_contract_retry",
    }:
        raise Protocol22ExecutionError("dispatch identity has unsupported attempt kind")
    return _dispatch_id(work_item, attempt_kind)


class Protocol22ExecutionStore:
    """Content-address execution bytes and publish one no-clobber capture commit."""

    def __init__(
        self,
        paths: ReV2Paths,
        object_store: ObjectStore,
        *,
        process_probe: ProcessProbe | None = None,
    ) -> None:
        if not isinstance(paths, ReV2Paths):
            raise Protocol22ExecutionError("execution store requires ReV2Paths")
        if not isinstance(object_store, ObjectStore):
            raise Protocol22ExecutionError("execution store requires ObjectStore")
        if ReV2Paths.for_run(paths.root.parent) != paths:
            raise Protocol22ExecutionError("execution paths are not canonical")
        if object_store.root.absolute() != paths.objects.absolute():
            raise Protocol22ExecutionError(
                "execution object store does not match run-local object path"
            )
        self.paths = paths
        self.object_store = object_store
        self.capture_root = paths.root / "captures"
        self.staging_root = self.capture_root / ".staging"
        self.committed_root = self.capture_root / "committed"
        self.leases_root = self.capture_root / "leases"
        self._process_probe = process_probe or _default_process_probe
        self._ensure_layout()

    def prepare_execution(
        self,
        work_item: WorkItemV2,
        attempt_kind: str,
        dependencies: PreparationDependenciesV1,
        fault_hook: FaultHook | None = None,
    ) -> PreparedExecutionV1:
        """Persist exact request authority; preparation alone never starts work."""
        _validate_item_executor(work_item, dependencies.executor)
        _validate_installed(dependencies.executor, dependencies.registry)
        dispatch_id = _dispatch_id(work_item, attempt_kind)
        try:
            if isinstance(dependencies, ProviderExecutionDependenciesV1):
                prepared = self._prepare_provider(
                    work_item,
                    attempt_kind,
                    dispatch_id,
                    dependencies,
                    fault_hook,
                )
            elif isinstance(dependencies, DeterministicExecutionDependenciesV1):
                prepared = self._prepare_deterministic(
                    work_item,
                    attempt_kind,
                    dispatch_id,
                    dependencies,
                    fault_hook,
                )
            else:
                raise Protocol22ExecutionError(
                    "execution dependencies select no closed execution branch"
                )
            return prepared
        except Protocol22ExecutionError:
            raise
        except (
            Protocol22SchemaError,
            Protocol22ProviderError,
            ReV2LedgerError,
        ) as exc:
            raise Protocol22ExecutionError(str(exc)) from exc

    def _prepare_provider(
        self,
        work_item: WorkItemV2,
        attempt_kind: str,
        dispatch_id: str,
        dependencies: ProviderExecutionDependenciesV1,
        fault_hook: FaultHook | None,
    ) -> PreparedExecutionV1:
        executor = dependencies.executor
        if (attempt_kind == "initial_generation") != (
            not dependencies.retry_diagnostics
        ):
            raise Protocol22ExecutionError(
                "provider retry diagnostics must exist exactly for retry attempts"
            )
        if executor.execution_mode not in {"api", "cli"}:
            raise Protocol22ExecutionError(
                "provider preparation requires API or CLI execution mode"
            )
        if executor.execution_mode == "cli":
            validate_provider_content_authority(
                work_item,
                dependencies.agent_bytes,
                dependencies.context_bytes,
                executor,
                content_digest(dependencies.response_schema_bytes),
            )
        agent_hash = self.object_store.put_blob(dependencies.agent_bytes)
        context_hash = self.object_store.put_blob(dependencies.context_bytes)
        schema_hash = self.object_store.put_blob(dependencies.response_schema_bytes)
        envelope = None
        envelope_hash = None
        if executor.execution_mode == "api":
            envelope = render_provider_request_envelope(
                work_item,
                dispatch_id,
                dependencies.agent_bytes,
                dependencies.context_bytes,
                executor,
                schema_hash,
                dependencies.retry_diagnostics,
            )
            envelope_hash = self.object_store.put_blob(
                canonical_json_bytes(envelope.to_json_dict())
            )
            _fault(fault_hook, "provider_envelope_fsynced")
            if dependencies.tokenizer is None:
                raise Protocol22ExecutionError("API request tokenizer is missing")
            reservation = calculate_bounded_dispatch_reservation(
                envelope,
                dependencies.response_schema_bytes,
                executor,
                dependencies.tokenizer,
            )
        else:
            reservation = calculate_shared_cli_dispatch_reservation(
                dependencies.agent_bytes,
                dependencies.context_bytes,
                dependencies.response_schema_bytes,
                executor,
                dependencies.retry_diagnostics,
            )
        execution_input = ExecutionInputV1(
            schema_version=1,
            dispatch_id=dispatch_id,
            work_item_id=work_item.work_item_id,
            attempt_kind=attempt_kind,  # type: ignore[arg-type]
            executor_contract_hash=executor.executor_contract_hash,
            agent_contract_hash=agent_hash,
            context_bundle_hash=context_hash,
            provider_request_envelope_hash=envelope_hash,
            deterministic_invocation=None,
        )
        input_hash = self.object_store.put_blob(
            canonical_json_bytes(execution_input.to_json_dict())
        )
        _fault(fault_hook, "execution_input_fsynced")
        return PreparedExecutionV1(
            dispatch_id=dispatch_id,
            execution_input=execution_input,
            execution_input_hash=input_hash,
            provider_envelope=envelope,
            provider_envelope_hash=envelope_hash,
            reservation=reservation,
        )

    def _prepare_deterministic(
        self,
        work_item: WorkItemV2,
        attempt_kind: str,
        dispatch_id: str,
        dependencies: DeterministicExecutionDependenciesV1,
        fault_hook: FaultHook | None,
    ) -> PreparedExecutionV1:
        executor = dependencies.executor
        if (
            executor.execution_mode != "in_process"
            or executor.reservation_calculator.calculator_id != IN_PROCESS_CALCULATOR_ID
        ):
            raise Protocol22ExecutionError(
                "deterministic preparation requires bounded in-process execution"
            )
        invocation = dependencies.invocation
        _validate_invocation(
            work_item,
            invocation,
            dependencies.workspace_partition_hash,
        )
        for object_hash, payload in dependencies.referenced_objects.items():
            if self.object_store.put_blob(payload) != object_hash:
                raise Protocol22ExecutionError(
                    "referenced object publication changed identity"
                )
        for value in invocation.inputs:
            self.object_store.read_blob(value.object_hash)
        invocation_hash = self.object_store.put_blob(
            canonical_json_bytes(invocation.to_json_dict())
        )
        if invocation_hash != invocation.identity:
            raise Protocol22ExecutionError(
                "deterministic invocation publication changed identity"
            )
        _fault(fault_hook, "deterministic_invocation_fsynced")
        reservation = InProcessDispatchReservationV1(
            billable_tokens=0,
            active_ms=executor.limits.max_active_ms_per_dispatch,
        )
        execution_input = ExecutionInputV1(
            schema_version=1,
            dispatch_id=dispatch_id,
            work_item_id=work_item.work_item_id,
            attempt_kind=attempt_kind,  # type: ignore[arg-type]
            executor_contract_hash=executor.executor_contract_hash,
            agent_contract_hash=None,
            context_bundle_hash=None,
            provider_request_envelope_hash=None,
            deterministic_invocation=invocation,
        )
        input_hash = self.object_store.put_blob(
            canonical_json_bytes(execution_input.to_json_dict())
        )
        _fault(fault_hook, "execution_input_fsynced")
        return PreparedExecutionV1(
            dispatch_id=dispatch_id,
            execution_input=execution_input,
            execution_input_hash=input_hash,
            provider_envelope=None,
            provider_envelope_hash=None,
            reservation=reservation,
        )

    def validate_prepared_execution(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2,
        dependencies: PreparationDependenciesV1,
    ) -> PreparedExecutionV1:
        """Reload and independently validate immutable preparation authority."""
        if not isinstance(prepared, PreparedExecutionV1):
            raise Protocol22ExecutionError("prepared execution is invalid")
        _validate_item_executor(work_item, dependencies.executor)
        _validate_installed(dependencies.executor, dependencies.registry)
        try:
            input_bytes = self.object_store.read_blob(prepared.execution_input_hash)
            execution_input = load_canonical_object(
                input_bytes,
                ExecutionInputV1.from_json_dict,
            )
            if execution_input != prepared.execution_input:
                raise Protocol22ExecutionError(
                    "stored execution input differs from prepared authority"
                )
            if (
                execution_input.work_item_id != work_item.work_item_id
                or execution_input.executor_contract_hash
                != dependencies.executor.executor_contract_hash
            ):
                raise Protocol22ExecutionError(
                    "stored execution input IDs do not match work authority"
                )
            if isinstance(dependencies, ProviderExecutionDependenciesV1):
                return self._validate_prepared_provider(
                    prepared,
                    work_item,
                    dependencies,
                )
            if isinstance(dependencies, DeterministicExecutionDependenciesV1):
                return self._validate_prepared_deterministic(
                    prepared,
                    work_item,
                    dependencies,
                )
        except Protocol22ExecutionError:
            raise
        except (
            Protocol22SchemaError,
            Protocol22ProviderError,
            ReV2LedgerError,
        ) as exc:
            raise Protocol22ExecutionError(
                f"prepared execution closure is invalid: {exc}"
            ) from exc
        raise Protocol22ExecutionError(
            "prepared execution dependency branch is invalid"
        )

    def _validate_prepared_provider(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2,
        dependencies: ProviderExecutionDependenciesV1,
    ) -> PreparedExecutionV1:
        if dependencies.executor.execution_mode == "cli":
            if prepared.provider_envelope is not None or (
                prepared.provider_envelope_hash is not None
            ):
                raise Protocol22ExecutionError(
                    "prepared CLI execution contains an API envelope"
                )
            validate_provider_content_authority(
                work_item,
                dependencies.agent_bytes,
                dependencies.context_bytes,
                dependencies.executor,
                content_digest(dependencies.response_schema_bytes),
            )
            expected = calculate_shared_cli_dispatch_reservation(
                self.object_store.read_blob(
                    prepared.execution_input.agent_contract_hash or ""
                ),
                self.object_store.read_blob(
                    prepared.execution_input.context_bundle_hash or ""
                ),
                dependencies.response_schema_bytes,
                dependencies.executor,
                dependencies.retry_diagnostics,
            )
            if expected != prepared.reservation:
                raise Protocol22ExecutionError(
                    "prepared CLI reservation authority mismatch"
                )
            return prepared
        envelope_hash = prepared.provider_envelope_hash
        if envelope_hash is None:
            raise Protocol22ExecutionError("prepared provider envelope is missing")
        envelope = load_canonical_object(
            self.object_store.read_blob(envelope_hash),
            ProviderRequestEnvelopeV1.from_json_dict,
        )
        expected = render_provider_request_envelope(
            work_item,
            prepared.dispatch_id,
            self.object_store.read_blob(
                prepared.execution_input.agent_contract_hash or ""
            ),
            self.object_store.read_blob(
                prepared.execution_input.context_bundle_hash or ""
            ),
            dependencies.executor,
            content_digest(dependencies.response_schema_bytes),
            dependencies.retry_diagnostics,
        )
        schema_hash = content_digest(dependencies.response_schema_bytes)
        try:
            stored_schema = self.object_store.read_blob(schema_hash)
        except ReV2LedgerError as exc:
            raise Protocol22ExecutionError(
                f"stored response schema authority is missing: {exc}"
            ) from exc
        if stored_schema != dependencies.response_schema_bytes:
            raise Protocol22ExecutionError("stored response schema bytes mismatch")
        if schema_hash != expected.response_format.schema_hash:
            raise Protocol22ExecutionError("stored response schema authority mismatch")
        if dependencies.tokenizer is None:
            raise Protocol22ExecutionError("API request tokenizer is missing")
        reservation = calculate_bounded_dispatch_reservation(
            envelope,
            dependencies.response_schema_bytes,
            dependencies.executor,
            dependencies.tokenizer,
        )
        if (
            envelope != expected
            or envelope != prepared.provider_envelope
            or reservation != prepared.reservation
        ):
            raise Protocol22ExecutionError(
                "prepared provider request/reservation authority mismatch"
            )
        return prepared

    def _validate_prepared_deterministic(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2,
        dependencies: DeterministicExecutionDependenciesV1,
    ) -> PreparedExecutionV1:
        invocation = prepared.execution_input.deterministic_invocation
        if invocation is None or invocation != dependencies.invocation:
            raise Protocol22ExecutionError(
                "prepared deterministic invocation authority mismatch"
            )
        _validate_invocation(
            work_item,
            invocation,
            dependencies.workspace_partition_hash,
        )
        if self.object_store.read_blob(invocation.identity) != canonical_json_bytes(
            invocation.to_json_dict()
        ):
            raise Protocol22ExecutionError(
                "stored deterministic invocation bytes mismatch"
            )
        for value in invocation.inputs:
            self.object_store.read_blob(value.object_hash)
        expected = InProcessDispatchReservationV1(
            billable_tokens=0,
            active_ms=dependencies.executor.limits.max_active_ms_per_dispatch,
        )
        if prepared.reservation != expected:
            raise Protocol22ExecutionError(
                "prepared in-process reservation authority mismatch"
            )
        return prepared

    def record_started_lease(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2,
        dependencies: PreparationDependenciesV1,
        process_identity: ProcessIdentity,
        fault_hook: FaultHook | None = None,
    ) -> StartedExecutionLeaseV1:
        """Revalidate preparation, then publish one stable live-owner lease."""
        self.validate_prepared_execution(prepared, work_item, dependencies)
        if not isinstance(process_identity, ProcessIdentity):
            raise Protocol22ExecutionError("started lease requires ProcessIdentity")
        try:
            observed = self._process_probe(process_identity.pid)
        except Exception as exc:
            raise Protocol22ExecutionError(
                "started lease process probe failed"
            ) from exc
        if observed != process_identity.process_start_identity:
            raise Protocol22ExecutionError(
                "started lease process identity is not currently live"
            )
        lease = StartedExecutionLeaseV1(
            schema_version=1,
            dispatch_id=prepared.dispatch_id,
            work_item_id=work_item.work_item_id,
            execution_input_hash=prepared.execution_input_hash,
            executor_contract_hash=dependencies.executor.executor_contract_hash,
            process_identity=process_identity,
        )
        payload = canonical_json_bytes(lease.to_json_dict())
        with self._locked():
            directory_fd = _open_directory_path_nofollow(self.leases_root)
            try:
                name = f"{prepared.dispatch_id}.json"
                _write_identical_or_new(directory_fd, name, payload, "started lease")
                _fsync(directory_fd)
            finally:
                os.close(directory_fd)
        _fault(fault_hook, "started_lease_fsynced")
        return lease

    def load_started_lease(self, dispatch_id: str) -> StartedExecutionLeaseV1 | None:
        _safe_dispatch_id(dispatch_id)
        directory_fd = _open_directory_path_nofollow(self.leases_root)
        try:
            name = f"{dispatch_id}.json"
            try:
                payload, _metadata = _read_closed_file_at(
                    directory_fd,
                    name,
                    "started lease",
                )
            except FileNotFoundError:
                return None
        finally:
            os.close(directory_fd)
        return _load_object(
            payload,
            StartedExecutionLeaseV1.from_json_dict,
            "started lease",
        )

    def capture_provider_result(
        self,
        prepared: PreparedExecutionV1,
        candidate_root: Path,
        result: RawExecutionResultV1,
        fault_hook: FaultHook | None = None,
    ) -> CapturedExecutionV1:
        """Persist provider candidate/output blobs before one capture object."""
        if not isinstance(prepared, PreparedExecutionV1) or (
            prepared.execution_input.agent_contract_hash is None
            or prepared.execution_input.context_bundle_hash is None
            or prepared.execution_input.deterministic_invocation is not None
        ):
            raise Protocol22ExecutionError(
                "provider capture requires prepared provider execution"
            )
        if not isinstance(result, RawExecutionResultV1):
            raise Protocol22ExecutionError("provider result is invalid")
        self._validate_prepared_objects(prepared)
        _validate_timeline(result.timing.started_at, result.timing.ended_at)
        try:
            entries = _capture_candidate_entries(
                Path(candidate_root),
                self.object_store,
                fault_hook,
            )
            inventory = CandidateInventoryV1(
                schema_version=1,
                dispatch_id=prepared.dispatch_id,
                work_item_id=prepared.execution_input.work_item_id,
                entries=entries,
            )
            inventory_hash = self.object_store.put_blob(
                canonical_json_bytes(inventory.to_json_dict())
            )
            _fault(fault_hook, "candidate_inventory_fsynced")
            stdout = _capture_stdout(result.stdout, self.object_store)
            _fault(fault_hook, "stdout_blob_fsynced")
            usage_hash = _persist_usage(result.provider_usage, self.object_store)
            if usage_hash is not None:
                _fault(fault_hook, "usage_blob_fsynced")
            capture = ExecutionCaptureV1(
                schema_version=1,
                dispatch_id=prepared.dispatch_id,
                work_item_id=prepared.execution_input.work_item_id,
                execution_input_hash=prepared.execution_input_hash,
                executor_contract_hash=(
                    prepared.execution_input.executor_contract_hash
                ),
                execution_mode=(
                    "api" if prepared.provider_envelope is not None else "cli"
                ),
                result_kind="provider_candidate",
                candidate_inventory_hash=inventory_hash,
                deterministic_artifact_hash=None,
                stdout_digest=stdout.digest,
                stdout_blob_hash=stdout.blob_hash,
                stdout_byte_count=stdout.byte_count,
                stdout_retained_byte_count=stdout.retained_count,
                stdout_capture=stdout.capture_kind,
                stderr_digest=(
                    None if not result.stderr else content_digest(result.stderr)
                ),
                provider_usage_blob_hash=usage_hash,
                started_at=result.timing.started_at,
                ended_at=result.timing.ended_at,
                duration_ms=result.timing.duration_ms,
                exit_code=(
                    0
                    if result.outcome == "candidate_ready"
                    else None
                    if result.outcome == "timed_out"
                    else 1
                ),
                timed_out=result.outcome == "timed_out",
                output_truncated=stdout.capture_kind == "terminal_tail",
                provider_name=(
                    prepared.provider_envelope.provider_id
                    if prepared.provider_envelope is not None
                    else result.provider_name or "unavailable"
                ),
                resolved_model_revision=(
                    prepared.provider_envelope.model_revision
                    if prepared.provider_envelope is not None
                    else result.resolved_model_revision
                ),
            )
            return self._persist_capture(capture, fault_hook)
        except Protocol22ExecutionError:
            raise
        except (Protocol22SchemaError, ReV2LedgerError, OSError) as exc:
            raise Protocol22ExecutionError(
                f"cannot durably capture provider result: {exc}"
            ) from exc

    def capture_deterministic_result(
        self,
        prepared: PreparedExecutionV1,
        result: DeterministicRawResultV1,
        fault_hook: FaultHook | None = None,
    ) -> CapturedExecutionV1:
        """Persist deterministic artifact/failure bytes before one capture object."""
        if not isinstance(prepared, PreparedExecutionV1) or (
            prepared.provider_envelope is not None
            or prepared.execution_input.deterministic_invocation is None
        ):
            raise Protocol22ExecutionError(
                "deterministic capture requires prepared in-process execution"
            )
        if not isinstance(result, DeterministicRawResultV1):
            raise Protocol22ExecutionError("deterministic result is invalid")
        self._validate_prepared_objects(prepared)
        try:
            artifact_hash = None
            if result.artifact_bytes is not None:
                artifact_hash = self.object_store.put_blob(result.artifact_bytes)
                _fault(fault_hook, "deterministic_artifact_fsynced")
            stdout = _capture_stdout(result.stdout, self.object_store)
            _fault(fault_hook, "stdout_blob_fsynced")
            capture = ExecutionCaptureV1(
                schema_version=1,
                dispatch_id=prepared.dispatch_id,
                work_item_id=prepared.execution_input.work_item_id,
                execution_input_hash=prepared.execution_input_hash,
                executor_contract_hash=(
                    prepared.execution_input.executor_contract_hash
                ),
                execution_mode="in_process",
                result_kind=(
                    "deterministic_artifact" if artifact_hash is not None else "none"
                ),
                candidate_inventory_hash=None,
                deterministic_artifact_hash=artifact_hash,
                stdout_digest=stdout.digest,
                stdout_blob_hash=stdout.blob_hash,
                stdout_byte_count=stdout.byte_count,
                stdout_retained_byte_count=stdout.retained_count,
                stdout_capture=stdout.capture_kind,
                stderr_digest=(
                    None if not result.stderr else content_digest(result.stderr)
                ),
                provider_usage_blob_hash=None,
                started_at=result.started_at,
                ended_at=result.ended_at,
                duration_ms=result.duration_ms,
                exit_code=result.exit_code,
                timed_out=result.timed_out,
                output_truncated=stdout.capture_kind == "terminal_tail",
                provider_name="in-process",
                resolved_model_revision=None,
            )
            return self._persist_capture(capture, fault_hook)
        except Protocol22ExecutionError:
            raise
        except (Protocol22SchemaError, ReV2LedgerError) as exc:
            raise Protocol22ExecutionError(
                f"cannot durably capture deterministic result: {exc}"
            ) from exc

    def _persist_capture(
        self,
        capture: ExecutionCaptureV1,
        fault_hook: FaultHook | None,
    ) -> CapturedExecutionV1:
        capture_hash = self.object_store.put_blob(
            canonical_json_bytes(capture.to_json_dict())
        )
        _fault(fault_hook, "execution_capture_fsynced")
        commit = ExecutionCaptureCommitV1(
            schema_version=1,
            dispatch_id=capture.dispatch_id,
            work_item_id=capture.work_item_id,
            execution_input_hash=capture.execution_input_hash,
            execution_capture_hash=capture_hash,
        )
        return CapturedExecutionV1(capture, capture_hash, commit)

    def _validate_prepared_objects(self, prepared: PreparedExecutionV1) -> None:
        try:
            execution_input = load_canonical_object(
                self.object_store.read_blob(prepared.execution_input_hash),
                ExecutionInputV1.from_json_dict,
            )
            if execution_input != prepared.execution_input:
                raise Protocol22ExecutionError(
                    "prepared execution input object does not match"
                )
            provider_branch = (
                execution_input.agent_contract_hash is not None
                and execution_input.context_bundle_hash is not None
                and execution_input.deterministic_invocation is None
            )
            if prepared.provider_envelope_hash is not None:
                envelope = load_canonical_object(
                    self.object_store.read_blob(prepared.provider_envelope_hash),
                    ProviderRequestEnvelopeV1.from_json_dict,
                )
                if envelope != prepared.provider_envelope:
                    raise Protocol22ExecutionError(
                        "prepared execution envelope object does not match"
                    )
            elif not provider_branch:
                invocation = execution_input.deterministic_invocation
                if invocation is None or self.object_store.read_blob(
                    invocation.identity
                ) != canonical_json_bytes(invocation.to_json_dict()):
                    raise Protocol22ExecutionError(
                        "prepared execution invocation object does not match"
                    )
        except Protocol22ExecutionError:
            raise
        except (Protocol22SchemaError, ReV2LedgerError) as exc:
            raise Protocol22ExecutionError(
                f"prepared execution object closure is invalid: {exc}"
            ) from exc

    def validate_capture_closure(
        self,
        commit: ExecutionCaptureCommitV1,
    ) -> ValidatedCaptureClosureV1:
        """Read-only verification of every byte named by a capture commit."""
        if not isinstance(commit, ExecutionCaptureCommitV1):
            raise Protocol22ExecutionError("capture commit is invalid")
        try:
            capture = load_canonical_object(
                self.object_store.read_blob(commit.execution_capture_hash),
                ExecutionCaptureV1.from_json_dict,
            )
            execution_input = load_canonical_object(
                self.object_store.read_blob(commit.execution_input_hash),
                ExecutionInputV1.from_json_dict,
            )
        except (Protocol22SchemaError, ReV2LedgerError) as exc:
            raise Protocol22ExecutionError(
                f"capture/execution object closure is invalid: {exc}"
            ) from exc
        expected_commit = ExecutionCaptureCommitV1(
            schema_version=1,
            dispatch_id=capture.dispatch_id,
            work_item_id=capture.work_item_id,
            execution_input_hash=capture.execution_input_hash,
            execution_capture_hash=capture.identity,
        )
        if commit != expected_commit or (
            execution_input.identity != commit.execution_input_hash
            or execution_input.dispatch_id != capture.dispatch_id
            or execution_input.work_item_id != capture.work_item_id
            or execution_input.executor_contract_hash != capture.executor_contract_hash
        ):
            raise Protocol22ExecutionError(
                "capture commit identity does not match execution input/capture"
            )
        _validate_timeline(capture.started_at, capture.ended_at)
        stdout = _read_named_blob(
            self.object_store,
            capture.stdout_blob_hash,
            "stdout",
        )
        if len(stdout) != capture.stdout_retained_byte_count:
            raise Protocol22ExecutionError("stdout retained byte count mismatch")
        if capture.stdout_capture == "complete" and (
            content_digest(stdout) != capture.stdout_digest
            or len(stdout) != capture.stdout_byte_count
        ):
            raise Protocol22ExecutionError("complete stdout digest mismatch")
        if capture.stdout_capture == "terminal_tail" and (
            len(stdout) >= capture.stdout_byte_count
            or len(stdout) > _STDOUT_RETAINED_LIMIT
        ):
            raise Protocol22ExecutionError("terminal-tail stdout closure mismatch")

        provider_envelope = None
        candidate_inventory = None
        usage_bytes = None
        deterministic_bytes = None
        if capture.execution_mode in {"api", "cli"}:
            envelope_hash = execution_input.provider_request_envelope_hash
            if capture.execution_mode == "api" and envelope_hash is None:
                raise Protocol22ExecutionError(
                    "provider capture has no request envelope"
                )
            if capture.execution_mode == "cli" and envelope_hash is not None:
                raise Protocol22ExecutionError(
                    "CLI provider capture cannot name an API request envelope"
                )
            agent_bytes = _read_named_blob(
                self.object_store,
                execution_input.agent_contract_hash or "",
                "provider agent contract",
            )
            context_bytes = _read_named_blob(
                self.object_store,
                execution_input.context_bundle_hash or "",
                "provider context bundle",
            )
            try:
                if envelope_hash is not None:
                    provider_envelope = load_canonical_object(
                        self.object_store.read_blob(envelope_hash),
                        ProviderRequestEnvelopeV1.from_json_dict,
                    )
                inventory_hash = capture.candidate_inventory_hash
                if inventory_hash is None:
                    raise Protocol22ExecutionError(
                        "provider capture has no candidate inventory"
                    )
                candidate_inventory = load_canonical_object(
                    self.object_store.read_blob(inventory_hash),
                    CandidateInventoryV1.from_json_dict,
                )
            except (Protocol22SchemaError, ReV2LedgerError) as exc:
                raise Protocol22ExecutionError(
                    f"provider envelope/candidate inventory closure is invalid: {exc}"
                ) from exc
            if (
                candidate_inventory.dispatch_id != capture.dispatch_id
                or candidate_inventory.work_item_id != capture.work_item_id
                or candidate_inventory.identity != capture.candidate_inventory_hash
            ):
                raise Protocol22ExecutionError(
                    "provider capture closure identity/revision mismatch"
                )
            if provider_envelope is not None and (
                provider_envelope.dispatch_id != capture.dispatch_id
                or provider_envelope.work_item_id != capture.work_item_id
                or provider_envelope.executor_contract_hash
                != capture.executor_contract_hash
                or provider_envelope.model_revision != capture.resolved_model_revision
                or provider_envelope.provider_id != capture.provider_name
                or provider_envelope.messages[0].content_utf8.encode("utf-8")
                != agent_bytes
                or provider_envelope.messages[1].content_utf8.encode("utf-8")
                != context_bytes
            ):
                raise Protocol22ExecutionError(
                    "provider capture closure identity/revision mismatch"
                )
            for entry in candidate_inventory.entries:
                if entry.object_kind != "regular":
                    continue
                payload = _read_named_blob(
                    self.object_store,
                    entry.content_hash or "",
                    f"candidate {entry.relative_path}",
                )
                if len(payload) != entry.byte_count:
                    raise Protocol22ExecutionError(
                        f"candidate {entry.relative_path} byte count mismatch"
                    )
            if capture.provider_usage_blob_hash is not None:
                usage_bytes = _read_named_blob(
                    self.object_store,
                    capture.provider_usage_blob_hash,
                    "provider usage",
                )
                try:
                    load_canonical_object(usage_bytes, lambda value: value)
                except Protocol22SchemaError as exc:
                    raise Protocol22ExecutionError(
                        f"provider usage closure is invalid: {exc}"
                    ) from exc
        else:
            if capture.provider_name != "in-process":
                raise Protocol22ExecutionError(
                    "deterministic capture provider name is invalid"
                )
            invocation = execution_input.deterministic_invocation
            if invocation is None:
                raise Protocol22ExecutionError(
                    "in-process capture has no deterministic invocation"
                )
            invocation_bytes = _read_named_blob(
                self.object_store,
                invocation.identity,
                "deterministic invocation",
            )
            if invocation_bytes != canonical_json_bytes(invocation.to_json_dict()):
                raise Protocol22ExecutionError(
                    "deterministic invocation object mismatch"
                )
            for value in invocation.inputs:
                _read_named_blob(
                    self.object_store,
                    value.object_hash,
                    f"deterministic input {value.role}",
                )
            if capture.deterministic_artifact_hash is not None:
                deterministic_bytes = _read_named_blob(
                    self.object_store,
                    capture.deterministic_artifact_hash,
                    "deterministic artifact",
                )
        return ValidatedCaptureClosureV1(
            commit=commit,
            capture=capture,
            execution_input=execution_input,
            provider_envelope=provider_envelope,
            candidate_inventory=candidate_inventory,
            stdout_bytes=stdout,
            provider_usage_bytes=usage_bytes,
            deterministic_artifact_bytes=deterministic_bytes,
        )

    def commit_capture(
        self,
        captured: CapturedExecutionV1,
        fault_hook: FaultHook | None = None,
    ) -> Committed:
        """Stage and hard-link one exact capture commit without replacement."""
        if not isinstance(captured, CapturedExecutionV1):
            raise Protocol22ExecutionError("capture commit requires captured execution")
        _validate_captured_identity(captured)
        self.validate_capture_closure(captured.commit)
        payload = canonical_json_bytes(captured.commit.to_json_dict())
        with self._locked():
            current = self.capture_state(captured.capture.dispatch_id)
            if isinstance(current, Committed):
                if current.commit != captured.commit:
                    raise Protocol22ExecutionError(
                        "conflicting existing capture commit"
                    )
                return current
            if isinstance(current, Conflict):
                raise Protocol22ExecutionError(
                    f"conflicting capture commit: {current.reason}"
                )
            staging_fd = _open_directory_path_nofollow(self.staging_root)
            committed_fd = _open_directory_path_nofollow(self.committed_root)
            dispatch_fd: int | None = None
            try:
                dispatch_fd = _ensure_directory_at(
                    staging_fd,
                    captured.capture.dispatch_id,
                    0o700,
                    "capture staging directory",
                )
                entries = set(os.listdir(dispatch_fd))
                if entries - {"ready.json"}:
                    raise Protocol22ExecutionError(
                        "conflicting capture staging entries"
                    )
                _write_identical_or_new(
                    dispatch_fd,
                    "ready.json",
                    payload,
                    "capture staging ready",
                )
                _fsync(dispatch_fd)
                _fsync(staging_fd)
                _fault(fault_hook, "capture_staging_ready_fsynced")
                target = f"{captured.capture.dispatch_id}.json"
                try:
                    os.link(
                        "ready.json",
                        target,
                        src_dir_fd=dispatch_fd,
                        dst_dir_fd=committed_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    existing, existing_metadata = _read_closed_file_at(
                        committed_fd,
                        target,
                        "committed capture",
                    )
                    ready_metadata = os.stat(
                        "ready.json",
                        dir_fd=dispatch_fd,
                        follow_symlinks=False,
                    )
                    if existing != payload or not _same_inode(
                        ready_metadata,
                        existing_metadata,
                    ):
                        raise Protocol22ExecutionError(
                            "conflicting existing capture commit"
                        )
                _fsync(committed_fd)
                _fault(fault_hook, "capture_committed_fsynced")
            except Protocol22ExecutionError:
                raise
            except OSError as exc:
                raise Protocol22ExecutionError(
                    f"cannot no-clobber commit capture: {exc}"
                ) from exc
            finally:
                if dispatch_fd is not None:
                    os.close(dispatch_fd)
                os.close(committed_fd)
                os.close(staging_fd)
        state = self.capture_state(captured.capture.dispatch_id)
        if not isinstance(state, Committed) or state.commit != captured.commit:
            raise Protocol22ExecutionError(
                "capture commit did not publish complete authority"
            )
        return state

    def capture_state(self, dispatch_id: str) -> CaptureCommitState:
        """Inspect ready/committed authority without modifying any run bytes."""
        _safe_dispatch_id(dispatch_id)
        staging_path = self.staging_root / dispatch_id
        committed_path = self.committed_root / f"{dispatch_id}.json"
        try:
            staged = _inspect_staging(self.staging_root, dispatch_id)
            committed = _inspect_commit(self.committed_root, dispatch_id)
            if staged.error or committed.error:
                return Conflict(
                    dispatch_id,
                    staging_path,
                    committed_path,
                    staged.error or committed.error or "capture state conflict",
                )
            if staged.value is not None and committed.value is not None:
                if staged.payload != committed.payload or not _same_inode(
                    staged.metadata,
                    committed.metadata,
                ):
                    return Conflict(
                        dispatch_id,
                        staging_path,
                        committed_path,
                        "staging and committed capture bytes/identity differ",
                    )
            chosen = committed.value or staged.value
            if chosen is None:
                return Missing(
                    dispatch_id,
                    staging_path,
                    committed_path,
                    incomplete_staging=staged.incomplete,
                )
            closure = self.validate_capture_closure(chosen)
            if committed.value is not None:
                return Committed(
                    dispatch_id=dispatch_id,
                    path=committed_path,
                    commit=committed.value,
                    closure=closure,
                    staging_path=(staging_path if staged.value is not None else None),
                )
            return StagingReady(
                dispatch_id=dispatch_id,
                path=staging_path / "ready.json",
                commit=chosen,
                closure=closure,
            )
        except Protocol22ExecutionError as exc:
            return Conflict(
                dispatch_id,
                staging_path,
                committed_path,
                str(exc),
            )
        except OSError as exc:
            return Conflict(
                dispatch_id,
                staging_path,
                committed_path,
                f"cannot inspect capture state: {exc}",
            )

    def persist_candidate(
        self,
        committed: Committed,
        fault_hook: FaultHook | None = None,
    ) -> PersistedCandidateV2:
        """Persist candidate provenance only after a valid provider capture commit."""
        if not isinstance(committed, Committed):
            raise Protocol22ExecutionError(
                "candidate persistence requires committed capture authority"
            )
        current = self.capture_state(committed.dispatch_id)
        if not isinstance(current, Committed) or current.commit != committed.commit:
            raise Protocol22ExecutionError(
                "candidate capture commit is no longer authoritative"
            )
        capture = current.closure.capture
        if capture.execution_mode not in {"api", "cli"} or (
            capture.candidate_inventory_hash is None
        ):
            raise Protocol22ExecutionError(
                "deterministic capture cannot create PersistedCandidateV2"
            )
        candidate = PersistedCandidateV2(
            schema_version=2,
            dispatch_id=capture.dispatch_id,
            work_item_id=capture.work_item_id,
            execution_capture_hash=capture.identity,
            candidate_inventory_hash=capture.candidate_inventory_hash,
        )
        try:
            candidate_hash = self.object_store.put_blob(
                canonical_json_bytes(candidate.to_json_dict())
            )
        except ReV2LedgerError as exc:
            raise Protocol22ExecutionError(
                f"cannot persist candidate record: {exc}"
            ) from exc
        if candidate_hash != candidate.candidate_id:
            raise Protocol22ExecutionError(
                "candidate record publication changed candidate identity"
            )
        _fault(fault_hook, "candidate_record_fsynced")
        return candidate

    def _ensure_layout(self) -> None:
        if not _HAS_DIRFD or not _NOFOLLOW:
            raise Protocol22ExecutionError(
                "protocol-2.2 execution requires directory-relative no-follow I/O"
            )
        root_fd = _open_directory_path_nofollow(self.paths.root)
        capture_fd: int | None = None
        try:
            capture_fd = _ensure_directory_at(
                root_fd,
                "captures",
                0o700,
                "capture root",
            )
            for name in (".staging", "committed", "leases"):
                child = _ensure_directory_at(
                    capture_fd,
                    name,
                    0o700,
                    f"capture {name} directory",
                )
                os.close(child)
            _fsync(capture_fd)
            _fsync(root_fd)
        except Protocol22ExecutionError:
            raise
        except OSError as exc:
            raise Protocol22ExecutionError(
                f"cannot establish safe capture layout: {exc}"
            ) from exc
        finally:
            if capture_fd is not None:
                os.close(capture_fd)
            os.close(root_fd)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        capture_fd = _open_directory_path_nofollow(self.capture_root)
        flags = os.O_RDWR | os.O_CREAT | _CLOEXEC | _NOFOLLOW
        try:
            lock_fd = os.open(".lock", flags, 0o600, dir_fd=capture_fd)
        except OSError as exc:
            os.close(capture_fd)
            raise Protocol22ExecutionError(
                f"cannot safely open execution-store lock: {exc}"
            ) from exc
        try:
            metadata = os.fstat(lock_fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise Protocol22ExecutionError(
                    "execution-store lock is not a regular file"
                )
            os.fchmod(lock_fd, 0o600)
            _retry_eintr(fcntl.flock, lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            _retry_eintr(fcntl.flock, lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            os.close(capture_fd)


@dataclass(frozen=True, slots=True)
class _CapturedStdout:
    digest: str
    blob_hash: str
    byte_count: int
    retained_count: int
    capture_kind: Literal["complete", "terminal_tail"]


@dataclass(frozen=True, slots=True)
class _InspectedCommit:
    value: ExecutionCaptureCommitV1 | None = None
    payload: bytes | None = None
    metadata: os.stat_result | None = None
    incomplete: bool = False
    error: str | None = None


def _dispatch_id(work_item: WorkItemV2, attempt_kind: str) -> str:
    payload = canonical_json_bytes(
        {
            "attempt_kind": attempt_kind,
            "work_item_id": work_item.work_item_id,
        }
    )
    return "dispatch-" + hashlib.sha256(payload).hexdigest()


def _validate_item_executor(
    work_item: object,
    executor: ExecutorContractEntryV1,
) -> None:
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22ExecutionError("execution requires WorkItemV2")
    if not isinstance(executor, ExecutorContractEntryV1):
        raise Protocol22ExecutionError("execution requires executor authority")
    expected = {
        "executor_contract_hash": executor.executor_contract_hash,
        "producer_family": executor.producer_family,
        "producer_protocol_version": executor.producer_protocol_version,
        "result_contract_id": executor.result_contract_id,
        "verifier_id": executor.verifier.verifier_id,
        "verifier_version": executor.verifier.verifier_version,
        "verifier_implementation_digest": executor.verifier.implementation_digest,
    }
    for field_name, value in expected.items():
        if getattr(work_item, field_name) != value:
            raise Protocol22ExecutionError(
                f"work item {field_name} does not match executor authority"
            )


def _validate_installed(
    executor: ExecutorContractEntryV1,
    registry: InstalledAuthorityRegistry,
) -> None:
    try:
        catalog = ExecutorContractCatalogV1(1, (executor,))
        mismatches = validate_installed_authorities(catalog, registry)
    except (Protocol22AuthorityError, Protocol22SchemaError) as exc:
        raise Protocol22ExecutionError(
            f"installed authority validation failed: {exc}"
        ) from exc
    if mismatches:
        detail = ", ".join(
            f"{item.authority_kind}:{item.authority_id}" for item in mismatches
        )
        raise Protocol22ExecutionError(f"installed authority mismatch: {detail}")


def _validate_invocation(
    work_item: WorkItemV2,
    invocation: DeterministicInvocationV1,
    workspace_partition_hash: str | None,
) -> None:
    if (
        invocation.producer_family != work_item.producer_family
        or invocation.output_key != work_item.output_key
        or invocation.artifact_policy_hash != work_item.output_key.layer_policy_hash
    ):
        raise Protocol22ExecutionError(
            "deterministic invocation does not match work item authority"
        )
    roles = frozenset(value.role for value in invocation.inputs)
    kind = work_item.output_key.artifact_kind
    static_roles = {
        "source-inventory": frozenset({"workspace_partition"}),
        "domain-inventory": frozenset({"workspace_partition"}),
        "source-partition": frozenset({"workspace_partition"}),
        "source-evidence-pack": frozenset({"source_inventory", "source_partition"}),
        "domain-evidence-pack": frozenset({"domain_inventory"}),
        "domain-context-bundle": frozenset(
            {"domain_inventory", "domain_evidence_pack"}
        ),
    }
    expected = static_roles.get(kind)
    if expected is not None:
        roles_valid = roles == expected
    elif kind == "source-overview-context-bundle":
        base = {"source_inventory", "source_partition", "source_evidence_pack"}
        roles_valid = base.issubset(roles) and all(
            role in base or _domain_role(role) for role in roles
        )
    elif kind == "source-baseline-root":
        roles_valid = "source_overview" in roles and all(
            role == "source_overview" or _domain_role(role) for role in roles
        )
    else:
        roles_valid = False
    hashes = tuple(sorted(value.object_hash for value in invocation.inputs))
    if kind in {"source-inventory", "domain-inventory", "source-partition"}:
        closure_valid = workspace_partition_hash is not None and hashes == (
            workspace_partition_hash,
        )
    else:
        closure_valid = (
            workspace_partition_hash is None
            and hashes == work_item.required_artifact_hashes
        )
    if not roles_valid:
        raise Protocol22ExecutionError(
            "deterministic invocation roles do not equal producer contract"
        )
    if not closure_valid:
        if kind in {"source-inventory", "domain-inventory", "source-partition"}:
            raise Protocol22ExecutionError(
                "deterministic invocation does not name the pinned workspace partition"
            )
        raise Protocol22ExecutionError(
            "deterministic invocation roles/hashes do not equal producer contract"
        )


def _domain_role(role: str) -> bool:
    if not role.startswith("domain:"):
        return False
    try:
        digest_value(role.removeprefix("domain:"), "domain invocation role")
    except Protocol22SchemaError:
        return False
    return True


def _capture_candidate_entries(
    root: Path,
    object_store: ObjectStore,
    fault_hook: FaultHook | None,
) -> tuple[CandidateInventoryEntryV1, ...]:
    root_fd = _open_directory_path_nofollow(root)
    entries: list[CandidateInventoryEntryV1] = []
    before = _stat_identity(os.fstat(root_fd))
    try:
        names = sorted(os.listdir(root_fd), key=lambda item: item.encode("utf-8"))
        for name in names:
            _candidate_relative_path(name)
            initial = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            mode = stat.S_IMODE(initial.st_mode)
            if stat.S_ISREG(initial.st_mode):
                payload, final = _read_regular_candidate(root_fd, name)
                if _stat_identity(initial) != _stat_identity(final):
                    raise Protocol22ExecutionError(
                        f"candidate entry changed while capturing: {name}"
                    )
                object_hash = object_store.put_blob(payload)
                entries.append(
                    CandidateInventoryEntryV1(
                        relative_path=name,
                        object_kind="regular",
                        mode=mode,
                        byte_count=len(payload),
                        content_hash=object_hash,
                    )
                )
            else:
                kind = "symlink" if stat.S_ISLNK(initial.st_mode) else "special"
                final = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if _stat_identity(initial) != _stat_identity(final):
                    raise Protocol22ExecutionError(
                        f"candidate entry changed while capturing: {name}"
                    )
                entries.append(CandidateInventoryEntryV1(name, kind, mode, 0, None))
        if names != sorted(
            os.listdir(root_fd),
            key=lambda item: item.encode("utf-8"),
        ) or before != _stat_identity(os.fstat(root_fd)):
            raise Protocol22ExecutionError(
                "candidate directory changed while capturing"
            )
    finally:
        os.close(root_fd)
    if any(item.object_kind == "regular" for item in entries):
        _fault(fault_hook, "candidate_blob_fsynced")
    return tuple(entries)


def _read_regular_candidate(
    parent_fd: int,
    name: str,
) -> tuple[bytes, os.stat_result]:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NONBLOCK | _CLOEXEC | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise Protocol22ExecutionError(
            f"cannot safely open candidate entry {name}: {exc}"
        ) from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Protocol22ExecutionError(
                f"candidate entry changed from regular: {name}"
            )
        payload = _read_all(fd)
        after = os.fstat(fd)
        if (
            _stat_identity(before) != _stat_identity(after)
            or len(payload) != before.st_size
        ):
            raise Protocol22ExecutionError(
                f"candidate entry changed while reading: {name}"
            )
        return payload, after
    finally:
        os.close(fd)


def _capture_stdout(stdout: bytes, object_store: ObjectStore) -> _CapturedStdout:
    if not isinstance(stdout, bytes):
        raise Protocol22ExecutionError("captured stdout must be bytes")
    retained = stdout[-_STDOUT_RETAINED_LIMIT:]
    blob_hash = object_store.put_blob(retained)
    return _CapturedStdout(
        digest=content_digest(stdout),
        blob_hash=blob_hash,
        byte_count=len(stdout),
        retained_count=len(retained),
        capture_kind=(
            "complete" if len(stdout) <= _STDOUT_RETAINED_LIMIT else "terminal_tail"
        ),
    )


def _validate_timeline(started_at: str, ended_at: str) -> None:
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    if ended < started:
        raise Protocol22ExecutionError(
            "execution capture timeline ends before it starts"
        )


def _persist_usage(payload: bytes | None, object_store: ObjectStore) -> str | None:
    if payload is None:
        return None
    if not isinstance(payload, bytes):
        raise Protocol22ExecutionError("provider usage must be bytes or null")
    try:
        load_canonical_object(payload, lambda value: value)
    except Protocol22SchemaError as exc:
        raise Protocol22ExecutionError(
            f"provider usage bytes are not canonical: {exc}"
        ) from exc
    return object_store.put_blob(payload)


def _validate_captured_identity(captured: CapturedExecutionV1) -> None:
    capture = captured.capture
    expected = ExecutionCaptureCommitV1(
        schema_version=1,
        dispatch_id=capture.dispatch_id,
        work_item_id=capture.work_item_id,
        execution_input_hash=capture.execution_input_hash,
        execution_capture_hash=capture.identity,
    )
    if captured.capture_hash != capture.identity or captured.commit != expected:
        raise Protocol22ExecutionError(
            "capture commit identity does not match captured execution"
        )


def _inspect_staging(root: Path, dispatch_id: str) -> _InspectedCommit:
    root_fd = _open_directory_path_nofollow(root)
    dispatch_fd: int | None = None
    try:
        try:
            dispatch_fd = os.open(
                dispatch_id,
                os.O_RDONLY | _DIRECTORY | _CLOEXEC | _NOFOLLOW,
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return _InspectedCommit()
        except OSError as exc:
            return _InspectedCommit(error=f"unsafe staging directory: {exc}")
        entries = set(os.listdir(dispatch_fd))
        if not entries:
            return _InspectedCommit(incomplete=True)
        if entries != {"ready.json"}:
            return _InspectedCommit(error="capture staging has unexpected entries")
        try:
            payload, metadata = _read_closed_file_at(
                dispatch_fd,
                "ready.json",
                "capture staging ready",
            )
            value = _load_object(
                payload,
                ExecutionCaptureCommitV1.from_json_dict,
                "capture staging ready",
            )
        except Protocol22ExecutionError as exc:
            return _InspectedCommit(error=str(exc))
        if value.dispatch_id != dispatch_id:
            return _InspectedCommit(error="staging ready dispatch ID mismatch")
        return _InspectedCommit(value, payload, metadata)
    finally:
        if dispatch_fd is not None:
            os.close(dispatch_fd)
        os.close(root_fd)


def _inspect_commit(root: Path, dispatch_id: str) -> _InspectedCommit:
    root_fd = _open_directory_path_nofollow(root)
    try:
        try:
            payload, metadata = _read_closed_file_at(
                root_fd,
                f"{dispatch_id}.json",
                "committed capture",
            )
        except FileNotFoundError:
            return _InspectedCommit()
        except Protocol22ExecutionError as exc:
            return _InspectedCommit(error=str(exc))
        value = _load_object(
            payload,
            ExecutionCaptureCommitV1.from_json_dict,
            "committed capture",
        )
        if value.dispatch_id != dispatch_id:
            return _InspectedCommit(error="committed capture dispatch ID mismatch")
        return _InspectedCommit(value, payload, metadata)
    finally:
        os.close(root_fd)


def _load_object(payload: bytes, decoder, label: str):  # type: ignore[no-untyped-def]
    try:
        return load_canonical_object(payload, decoder)
    except (Protocol22SchemaError, Protocol22ExecutionError, ValueError) as exc:
        raise Protocol22ExecutionError(f"invalid {label}: {exc}") from exc


def _read_named_blob(
    object_store: ObjectStore,
    object_hash: str,
    label: str,
) -> bytes:
    try:
        return object_store.read_blob(object_hash)
    except (ReV2LedgerError, Protocol22SchemaError) as exc:
        raise Protocol22ExecutionError(
            f"missing or corrupt {label} blob: {exc}"
        ) from exc


def _candidate_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise Protocol22ExecutionError(
            "candidate relative_path must be a nonempty UTF-8 string"
        )
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol22ExecutionError(
            "candidate relative_path contains invalid Unicode"
        ) from exc
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise Protocol22ExecutionError(
            "candidate relative_path must be normalized and relative"
        )
    return value


def _safe_dispatch_id(value: object) -> str:
    try:
        result = safe_id(value, "capture dispatch_id")
    except Protocol22SchemaError as exc:
        raise Protocol22ExecutionError(str(exc)) from exc
    if result.startswith("."):
        raise Protocol22ExecutionError("capture dispatch_id cannot be private")
    return result


def _ensure_directory_at(
    parent_fd: int,
    name: str,
    mode: int,
    label: str,
) -> int:
    try:
        os.mkdir(name, mode, dir_fd=parent_fd)
        _fsync(parent_fd)
    except FileExistsError:
        pass
    try:
        fd = os.open(
            name,
            os.O_RDONLY | _DIRECTORY | _CLOEXEC | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as exc:
        raise Protocol22ExecutionError(f"unsafe {label}: {exc}") from exc
    metadata = os.fstat(fd)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(fd)
        raise Protocol22ExecutionError(f"{label} is not a directory")
    return fd


def _open_directory_path_nofollow(path: Path) -> int:
    if not _HAS_DIRFD or not _NOFOLLOW:
        raise Protocol22ExecutionError(
            "directory-relative no-follow operations are unavailable"
        )
    absolute = path.absolute()
    if not absolute.is_absolute() or any(
        part in {".", ".."} for part in absolute.parts
    ):
        raise Protocol22ExecutionError(f"unsafe directory path: {path}")
    current = os.open("/", os.O_RDONLY | _DIRECTORY | _CLOEXEC)
    try:
        for part in absolute.parts[1:]:
            next_fd = os.open(
                part,
                os.O_RDONLY | _DIRECTORY | _CLOEXEC | _NOFOLLOW,
                dir_fd=current,
            )
            os.close(current)
            current = next_fd
        if not stat.S_ISDIR(os.fstat(current).st_mode):
            raise Protocol22ExecutionError(f"path is not a directory: {path}")
        return current
    except Exception:
        os.close(current)
        raise


def _write_identical_or_new(
    parent_fd: int,
    name: str,
    payload: bytes,
    label: str,
) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _CLOEXEC | _NOFOLLOW
    try:
        fd = os.open(name, flags, 0o400, dir_fd=parent_fd)
    except FileExistsError:
        existing, _metadata = _read_closed_file_at(parent_fd, name, label)
        if existing != payload:
            raise Protocol22ExecutionError(f"conflicting existing {label}")
        return
    except OSError as exc:
        raise Protocol22ExecutionError(f"cannot create {label}: {exc}") from exc
    try:
        os.fchmod(fd, 0o400)
        _write_all(fd, payload)
        _fsync(fd)
    except OSError as exc:
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass
        raise Protocol22ExecutionError(f"cannot write {label}: {exc}") from exc
    finally:
        os.close(fd)


def _read_closed_file_at(
    parent_fd: int,
    name: str,
    label: str,
) -> tuple[bytes, os.stat_result]:
    try:
        fd = os.open(
            name,
            os.O_RDONLY | os.O_NONBLOCK | _CLOEXEC | _NOFOLLOW,
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise Protocol22ExecutionError(f"unsafe {label}: {exc}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise Protocol22ExecutionError(f"{label} is not a regular file")
        if stat.S_IMODE(before.st_mode) != 0o400:
            raise Protocol22ExecutionError(f"{label} mode is not 0400")
        payload = _read_all(fd)
        after = os.fstat(fd)
        if (
            _stat_identity(before) != _stat_identity(after)
            or len(payload) != before.st_size
        ):
            raise Protocol22ExecutionError(f"{label} changed while reading")
        return payload, after
    finally:
        os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = _retry_eintr(os.write, fd, view)
        if written <= 0:
            raise OSError("short durable execution write")
        view = view[written:]


def _read_all(fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = _retry_eintr(os.read, fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
    )


def _same_inode(
    first: os.stat_result | None,
    second: os.stat_result | None,
) -> bool:
    return (
        first is not None
        and second is not None
        and first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
    )


def _fsync(fd: int) -> None:
    _retry_eintr(os.fsync, fd)


def _fault(fault_hook: FaultHook | None, boundary: str) -> None:
    if fault_hook is not None:
        fault_hook(boundary)


def _default_process_probe(pid: int) -> str | None:
    if sys.platform.startswith("linux"):
        try:
            data = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
            fields = data[data.rfind(")") + 2 :].split()
            return f"linux:{fields[19]}" if len(fields) > 19 else None
        except (OSError, ValueError, IndexError):
            return None
    if sys.platform == "darwin":
        try:
            completed = subprocess.run(
                ["ps", "-o", "lstart=", "-p", str(pid)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            return None
        started = completed.stdout.strip()
        if completed.returncode != 0 or not started:
            return None
        return "macos:" + hashlib.sha256(started.encode("utf-8")).hexdigest()
    raise Protocol22ExecutionError(
        "stable process probing is unsupported on this platform"
    )


def _retry_eintr(operation, *args, **kwargs):  # type: ignore[no-untyped-def]
    while True:
        try:
            return operation(*args, **kwargs)
        except InterruptedError:
            continue


__all__ = (
    "CandidateInventoryEntryV1",
    "CandidateInventoryV1",
    "CaptureCommitState",
    "CapturedExecutionV1",
    "Committed",
    "Conflict",
    "DeterministicExecutionDependenciesV1",
    "dispatch_id_for",
    "DeterministicRawResultV1",
    "DispatchPreviewV1",
    "InProcessDispatchReservationV1",
    "Missing",
    "PreparedExecutionV1",
    "Protocol22ExecutionError",
    "Protocol22ExecutionStore",
    "ProviderExecutionDependenciesV1",
    "StagingReady",
    "StartedExecutionLeaseV1",
    "ValidatedCaptureClosureV1",
    "preview_dispatch_reservation",
)
