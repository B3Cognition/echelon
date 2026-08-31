"""Durable, content-free L3-to-L4 orchestration intent authority."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Callable, ClassVar, Literal, Mapping, Protocol

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.events import (
    EventProtocol,
    EventRecord,
    EventReplayState,
    EventStore,
    ReV2EventError,
    _canonical_payload,
    _thaw_json,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    positive_or_none,
    safe_id,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3TargetV1,
    build_l3_target_projections,
)


class DeepenOrchestrationError(RuntimeError):
    """Raised when durable L4 orchestration authority is invalid."""


@dataclass(frozen=True, slots=True)
class ResolvedL4ParentV1:
    """Manifest-first result of traversing input lineage toward exact L3 authority."""

    input_run_dir: Path
    analysis_run_dir: Path
    selected_l3: ValidatedL3ParentV1 | None
    authority_objects: Mapping[str, bytes]
    prerequisite_required: bool

    def __post_init__(self) -> None:
        copied: dict[str, bytes] = {}
        for object_id, payload in self.authority_objects.items():
            if not isinstance(payload, bytes) or content_digest(payload) != object_id:
                raise DeepenOrchestrationError(
                    f"resolved parent authority hash mismatch: {object_id}"
                )
            copied[object_id] = payload
        object.__setattr__(
            self,
            "authority_objects",
            MappingProxyType(dict(sorted(copied.items()))),
        )
        if self.prerequisite_required == (self.selected_l3 is not None):
            raise DeepenOrchestrationError(
                "resolved L4 parent prerequisite state is inconsistent"
            )


class _L4InputsFactory(Protocol):
    def __call__(
        self,
        parent: ResolvedL4ParentV1,
        intent: "DeepenOrchestrationIntentV1",
    ) -> object: ...


class _ClosureInputsFactory(Protocol):
    def __call__(
        self,
        parent: ResolvedL4ParentV1,
        l4_run_dir: Path,
    ) -> object: ...


class _CheckpointAdoptionFactory(Protocol):
    def __call__(self, inputs: object) -> object: ...


@dataclass(frozen=True, slots=True)
class Protocol28OrchestrationOptions:
    """Runtime dependencies for advancing one durable semantic intent."""

    from_run: str | Path
    selection: SelectionScopeV1
    request: "DeepenOrchestrationRequestV1"
    l4_inputs_factory: _L4InputsFactory
    l3_prerequisite_factory: (
        Callable[[Path, str | Path, SelectionScopeV1], Path] | None
    ) = None
    closure_inputs_factory: _ClosureInputsFactory | None = None
    checkpoint_adoption_factory: _CheckpointAdoptionFactory | None = None
    token_limit: int | None = None
    active_ms_limit: int | None = None
    clock: Callable[[], str] | None = None


@dataclass(frozen=True, slots=True)
class Protocol28OrchestrationResult:
    request_id: str
    state: OrchestrationStateV1
    l3_run_id: str | None
    l4_run_id: str | None
    closure_run_id: str | None
    blocked_stage: str | None
    blocked_reason_code: str | None


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise DeepenOrchestrationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DeepenOrchestrationRequestV1:
    """Semantic L4 request identity; resource authorization is deliberately absent."""

    schema_version: int
    input_run_id: str
    input_manifest_hash: str
    input_terminal_event_hash: str
    source_snapshot_id: str
    partition_manifest_id: str
    selection: SelectionScopeV1
    exhaustive_policy_catalog_id: str
    executor_catalog_id: str
    l3_prerequisite_request_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "input_run_id",
        "input_manifest_hash",
        "input_terminal_event_hash",
        "source_snapshot_id",
        "partition_manifest_id",
        "selection",
        "exhaustive_policy_catalog_id",
        "executor_catalog_id",
        "l3_prerequisite_request_id",
    )

    def __post_init__(self) -> None:
        _schema(
            literal,
            self.schema_version,
            1,
            "DeepenOrchestrationRequestV1.schema_version",
        )
        _schema(safe_id, self.input_run_id, "DeepenOrchestrationRequestV1.input_run_id")
        for field in (
            "input_manifest_hash",
            "input_terminal_event_hash",
            "source_snapshot_id",
            "partition_manifest_id",
            "exhaustive_policy_catalog_id",
            "executor_catalog_id",
            "l3_prerequisite_request_id",
        ):
            _schema(
                digest_value,
                getattr(self, field),
                f"DeepenOrchestrationRequestV1.{field}",
            )
        if not isinstance(self.selection, SelectionScopeV1):
            raise DeepenOrchestrationError(
                "DeepenOrchestrationRequestV1.selection is invalid"
            )

    @property
    def request_id(self) -> str:
        return content_digest(canonical_json_bytes(self.to_json_dict()))

    @property
    def identity(self) -> str:
        return self.request_id

    def to_json_dict(self) -> dict[str, object]:
        return {
            **{
                field: getattr(self, field)
                for field in self.FIELDS
                if field != "selection"
            },
            "selection": self.selection.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "DeepenOrchestrationRequestV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(
            **{field: raw[field] for field in cls.FIELDS if field != "selection"},
            selection=SelectionScopeV1.from_json_dict(raw["selection"]),
        )


OrchestrationStateV1 = Literal[
    "awaiting_l3", "awaiting_l4", "awaiting_closure", "complete"
]


@dataclass(frozen=True, slots=True)
class DeepenOrchestrationProjectionV1:
    schema_version: int
    request_id: str
    state: OrchestrationStateV1
    token_limit: int | None
    active_ms_limit: int | None
    l3_run_id: str | None
    l3_manifest_hash: str | None
    l3_terminal_event_hash: str | None
    l4_run_id: str | None
    l4_manifest_hash: str | None
    l4_terminal_event_hash: str | None
    closure_run_id: str | None
    closure_manifest_hash: str | None
    closure_terminal_event_hash: str | None
    blocked_stage: str | None
    blocked_reason_code: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "active_ms_limit": self.active_ms_limit,
            "blocked_reason_code": self.blocked_reason_code,
            "blocked_stage": self.blocked_stage,
            "closure_manifest_hash": self.closure_manifest_hash,
            "closure_run_id": self.closure_run_id,
            "closure_terminal_event_hash": self.closure_terminal_event_hash,
            "l3_manifest_hash": self.l3_manifest_hash,
            "l3_run_id": self.l3_run_id,
            "l3_terminal_event_hash": self.l3_terminal_event_hash,
            "l4_manifest_hash": self.l4_manifest_hash,
            "l4_run_id": self.l4_run_id,
            "l4_terminal_event_hash": self.l4_terminal_event_hash,
            "request_id": self.request_id,
            "schema_version": self.schema_version,
            "state": self.state,
            "token_limit": self.token_limit,
        }


def _digest(value: object, field: str) -> None:
    try:
        digest_value(value, field)
    except Protocol22SchemaError as exc:
        raise ReV2EventError(str(exc)) from exc


def _safe(value: object, field: str) -> None:
    try:
        safe_id(value, field)
    except Protocol22SchemaError as exc:
        raise ReV2EventError(str(exc)) from exc


def _positive(value: object, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ReV2EventError(f"{field} must be a positive integer")


def _nullable_positive(value: object, field: str) -> None:
    try:
        positive_or_none(value, field)
    except Protocol22SchemaError as exc:
        raise ReV2EventError(str(exc)) from exc


def _dimension(value: object, field: str) -> None:
    if value not in {"tokens", "active_ms"}:
        raise ReV2EventError(f"{field} must be tokens or active_ms")


def _boolean(value: object, field: str) -> None:
    if not isinstance(value, bool):
        raise ReV2EventError(f"{field} must be boolean")


_PAYLOADS = {
    "orchestration_created": {"request_id": _digest, "request_object_id": _digest},
    "resource_authorized": {
        "authorized_by": _safe,
        "dimension": _dimension,
        "new_value": _positive,
        "old_value": _nullable_positive,
    },
    "l3_child_bound": {"manifest_hash": _digest, "run_id": _safe},
    "l3_satisfied": {
        "manifest_hash": _digest,
        "run_id": _safe,
        "terminal_event_hash": _digest,
    },
    "l4_child_bound": {"manifest_hash": _digest, "run_id": _safe},
    "l4_completed": {
        "closure_required": _boolean,
        "manifest_hash": _digest,
        "run_id": _safe,
        "terminal_event_hash": _digest,
    },
    "closure_child_bound": {"manifest_hash": _digest, "run_id": _safe},
    "closure_completed": {
        "manifest_hash": _digest,
        "run_id": _safe,
        "terminal_event_hash": _digest,
    },
    "orchestration_blocked": {"reason_code": _safe, "stage": _safe},
}


class _OrchestrationReplayState(EventReplayState):
    def __init__(self) -> None:
        self.request_id: str | None = None
        self.state: OrchestrationStateV1 | None = None
        self.token_limit: int | None = None
        self.active_ms_limit: int | None = None
        self.l3: tuple[str, str, str | None] | None = None
        self.l4: tuple[str, str, str | None] | None = None
        self.closure: tuple[str, str, str | None] | None = None
        self.blocked: tuple[str, str] | None = None

    def consume(self, event: EventRecord) -> None:
        kind = event.type
        payload = event.payload
        if kind == "orchestration_created":
            if self.request_id is not None:
                raise ReV2EventError("orchestration may be created only once")
            self.request_id = str(payload["request_id"])
            self.state = "awaiting_l3"
            return
        if self.request_id is None or self.state is None:
            raise ReV2EventError(f"{kind} requires orchestration_created")
        if self.state == "complete":
            raise ReV2EventError(f"{kind} cannot follow completed orchestration")
        if kind == "resource_authorized":
            dimension = str(payload["dimension"])
            current = (
                self.token_limit if dimension == "tokens" else self.active_ms_limit
            )
            if payload["old_value"] != current or int(payload["new_value"]) <= (
                current or 0
            ):
                raise ReV2EventError("resource authorization must be an exact increase")
            if dimension == "tokens":
                self.token_limit = int(payload["new_value"])
            else:
                self.active_ms_limit = int(payload["new_value"])
            return
        if kind == "orchestration_blocked":
            self.blocked = (str(payload["stage"]), str(payload["reason_code"]))
            return
        if kind == "l3_child_bound":
            self._bind("l3", payload, "awaiting_l3")
            return
        if kind == "l3_satisfied":
            self._satisfy("l3", payload, "awaiting_l3")
            self.state = "awaiting_l4"
            self.blocked = None
            return
        if kind == "l4_child_bound":
            self._bind("l4", payload, "awaiting_l4")
            return
        if kind == "l4_completed":
            self._satisfy("l4", payload, "awaiting_l4")
            self.state = (
                "awaiting_closure" if payload["closure_required"] else "complete"
            )
            self.blocked = None
            return
        if kind == "closure_child_bound":
            self._bind("closure", payload, "awaiting_closure")
            return
        if kind == "closure_completed":
            self._satisfy("closure", payload, "awaiting_closure")
            self.state = "complete"
            self.blocked = None
            return
        raise ReV2EventError(f"unknown orchestration event type: {kind}")

    def _bind(self, name: str, payload: Mapping[str, object], state: str) -> None:
        if self.state != state:
            raise ReV2EventError(f"{name} child cannot bind while {self.state}")
        if getattr(self, name) is not None:
            raise ReV2EventError(f"orchestration already binds a {name} child")
        setattr(
            self, name, (str(payload["run_id"]), str(payload["manifest_hash"]), None)
        )

    def _satisfy(self, name: str, payload: Mapping[str, object], state: str) -> None:
        if self.state != state:
            raise ReV2EventError(f"{name} child cannot complete while {self.state}")
        bound = getattr(self, name)
        if bound is None:
            raise ReV2EventError(f"{name} completion requires a bound child")
        if (payload["run_id"], payload["manifest_hash"]) != bound[:2]:
            raise ReV2EventError(f"{name} completion does not match bound child")
        setattr(self, name, (bound[0], bound[1], str(payload["terminal_event_hash"])))


class _OrchestrationEventProtocol(EventProtocol):
    def canonical_payload(
        self, event_type: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        if event_type not in _PAYLOADS:
            raise ReV2EventError(f"unknown orchestration event: {event_type}")
        canonical = _canonical_payload(_thaw_json(payload))
        expected = _PAYLOADS[event_type]
        unknown = set(canonical) - set(expected)
        missing = set(expected) - set(canonical)
        if unknown:
            raise ReV2EventError(
                f"{event_type} has unknown fields: {', '.join(sorted(unknown))}"
            )
        if missing:
            raise ReV2EventError(
                f"{event_type} is missing fields: {', '.join(sorted(missing))}"
            )
        for field, validator in expected.items():
            validator(canonical[field], f"{event_type}.{field}")
        return MappingProxyType(dict(canonical))

    def new_state(self) -> EventReplayState:
        return _OrchestrationReplayState()


ORCHESTRATION_EVENTS: EventProtocol = _OrchestrationEventProtocol()


@dataclass(frozen=True, slots=True)
class OrchestrationPaths:
    root: Path
    request: Path
    events: Path
    projection: Path

    @classmethod
    def for_request(cls, workspace_root: Path, request_id: str) -> "OrchestrationPaths":
        root = (
            Path(workspace_root).resolve()
            / "runs"
            / ".re-v2-orchestrations"
            / request_id
        )
        return cls(
            root, root / "request.json", root / "events.jsonl", root / "projection.json"
        )


@dataclass(frozen=True, slots=True)
class DeepenOrchestrationIntentV1:
    paths: OrchestrationPaths
    request: DeepenOrchestrationRequestV1
    events: EventStore


def _projection(state: _OrchestrationReplayState) -> DeepenOrchestrationProjectionV1:
    if state.request_id is None or state.state is None:
        raise DeepenOrchestrationError("orchestration has no creation authority")
    l3 = state.l3 or (None, None, None)
    l4 = state.l4 or (None, None, None)
    closure = state.closure or (None, None, None)
    blocked = state.blocked or (None, None)
    return DeepenOrchestrationProjectionV1(
        1,
        state.request_id,
        state.state,
        state.token_limit,
        state.active_ms_limit,
        l3[0],
        l3[1],
        l3[2],
        l4[0],
        l4[1],
        l4[2],
        closure[0],
        closure[1],
        closure[2],
        blocked[0],
        blocked[1],
    )


def _replay_projection(
    events: tuple[EventRecord, ...],
) -> DeepenOrchestrationProjectionV1:
    state = _OrchestrationReplayState()
    for event in events:
        state.consume(event)
    return _projection(state)


class DeepenOrchestrationController:
    def __init__(
        self,
        intent: DeepenOrchestrationIntentV1,
        *,
        clock: Callable[[], str],
        fault: Callable[[str], None] | None = None,
    ) -> None:
        self.intent = intent
        self.clock = clock
        self.fault = fault

    def rebuild_projection(self) -> DeepenOrchestrationProjectionV1:
        value = _replay_projection(self.intent.events.replay())
        _atomic_replace(
            self.intent.paths.projection, canonical_json_bytes(value.to_json_dict())
        )
        return value

    def _append_once(
        self, event_type: str, payload: Mapping[str, object]
    ) -> EventRecord:
        canonical = self.intent.events.protocol.canonical_payload(event_type, payload)
        matching = tuple(
            event for event in self.intent.events.replay() if event.type == event_type
        )
        for event in matching:
            if event.payload == canonical:
                self.rebuild_projection()
                return event
        if (
            event_type
            in {
                "l3_child_bound",
                "l3_satisfied",
                "l4_child_bound",
                "l4_completed",
                "closure_child_bound",
                "closure_completed",
            }
            and matching
        ):
            raise DeepenOrchestrationError(
                f"orchestration already binds or completes {event_type}"
            )
        try:
            event = self.intent.events.append(
                event_type, payload, occurred_at=self.clock()
            )
        except ReV2EventError as exc:
            raise DeepenOrchestrationError(str(exc)) from exc
        if self.fault is not None:
            self.fault("after_event_before_projection")
        self.rebuild_projection()
        return event

    def authorize(
        self,
        dimension: Literal["tokens", "active_ms"],
        new_value: int,
        *,
        authorized_by: str,
    ) -> EventRecord:
        current = self.rebuild_projection()
        old = current.token_limit if dimension == "tokens" else current.active_ms_limit
        if (
            not isinstance(new_value, int)
            or isinstance(new_value, bool)
            or new_value <= (old or 0)
        ):
            raise DeepenOrchestrationError("resource authorization must be an increase")
        return self._append_once(
            "resource_authorized",
            {
                "authorized_by": authorized_by,
                "dimension": dimension,
                "new_value": new_value,
                "old_value": old,
            },
        )

    def bind_l3_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once(
            "l3_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash}
        )

    def satisfy_l3(
        self, run_id: str, terminal_event_hash: str, *, manifest_hash: str | None = None
    ) -> EventRecord:
        current = self.rebuild_projection()
        if current.l3_run_id != run_id or (
            manifest_hash is not None and current.l3_manifest_hash != manifest_hash
        ):
            raise DeepenOrchestrationError("L3 completion does not match bound child")
        assert current.l3_manifest_hash is not None
        return self._append_once(
            "l3_satisfied",
            {
                "run_id": run_id,
                "manifest_hash": current.l3_manifest_hash,
                "terminal_event_hash": terminal_event_hash,
            },
        )

    def bind_l4_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once(
            "l4_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash}
        )

    def complete_l4(
        self, run_id: str, terminal_event_hash: str, *, closure_required: bool
    ) -> EventRecord:
        current = self.rebuild_projection()
        if current.l4_run_id != run_id or current.l4_manifest_hash is None:
            raise DeepenOrchestrationError("L4 completion does not match bound child")
        return self._append_once(
            "l4_completed",
            {
                "run_id": run_id,
                "manifest_hash": current.l4_manifest_hash,
                "terminal_event_hash": terminal_event_hash,
                "closure_required": closure_required,
            },
        )

    def bind_closure_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once(
            "closure_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash}
        )

    def complete_closure(self, run_id: str, terminal_event_hash: str) -> EventRecord:
        current = self.rebuild_projection()
        if current.closure_run_id != run_id or current.closure_manifest_hash is None:
            raise DeepenOrchestrationError(
                "closure completion does not match bound child"
            )
        return self._append_once(
            "closure_completed",
            {
                "run_id": run_id,
                "manifest_hash": current.closure_manifest_hash,
                "terminal_event_hash": terminal_event_hash,
            },
        )

    def block(self, stage: str, reason_code: str) -> EventRecord:
        return self._append_once(
            "orchestration_blocked",
            {"stage": stage, "reason_code": reason_code},
        )


def _atomic_replace(path: Path, payload: bytes) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise DeepenOrchestrationError(f"unsafe orchestration path: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _write_new(path: Path, payload: bytes) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    fd = os.open(path, flags, 0o400)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def load_orchestration(path: Path) -> DeepenOrchestrationIntentV1:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise DeepenOrchestrationError("orchestration directory is unsafe or missing")
    paths = OrchestrationPaths(
        root, root / "request.json", root / "events.jsonl", root / "projection.json"
    )
    if paths.request.is_symlink() or not paths.request.is_file():
        raise DeepenOrchestrationError("orchestration request is unsafe or missing")
    try:
        raw = json.loads(paths.request.read_bytes())
        request = DeepenOrchestrationRequestV1.from_json_dict(raw)
    except (OSError, json.JSONDecodeError, DeepenOrchestrationError) as exc:
        raise DeepenOrchestrationError(f"invalid orchestration request: {exc}") from exc
    if root.name != request.request_id:
        raise DeepenOrchestrationError(
            "orchestration directory does not match request identity"
        )
    events = EventStore(paths.events, protocol=ORCHESTRATION_EVENTS)
    history = events.replay()
    projection = _replay_projection(history)
    if projection.request_id != request.request_id:
        raise DeepenOrchestrationError("orchestration events do not match request")
    return DeepenOrchestrationIntentV1(paths, request, events)


def create_or_load_orchestration(
    workspace_root: Path,
    request: DeepenOrchestrationRequestV1,
    *,
    clock: Callable[[], str],
    token_limit: int | None = None,
    active_ms_limit: int | None = None,
) -> DeepenOrchestrationIntentV1:
    if not isinstance(request, DeepenOrchestrationRequestV1):
        raise DeepenOrchestrationError("orchestration request is invalid")
    paths = OrchestrationPaths.for_request(workspace_root, request.request_id)
    namespace = paths.root.parent
    runs = namespace.parent
    runs.mkdir(parents=True, exist_ok=True)
    if runs.is_symlink() or namespace.is_symlink():
        raise DeepenOrchestrationError("orchestration namespace is unsafe")
    namespace.mkdir(mode=0o700, exist_ok=True)
    created = False
    try:
        paths.root.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    if created:
        _write_new(paths.request, canonical_json_bytes(request.to_json_dict()))
        events = EventStore(paths.events, protocol=ORCHESTRATION_EVENTS)
        events.append(
            "orchestration_created",
            {"request_id": request.request_id, "request_object_id": request.identity},
            occurred_at=clock(),
        )
    intent = load_orchestration(paths.root)
    controller = DeepenOrchestrationController(intent, clock=clock)
    projection = controller.rebuild_projection()
    for dimension, value, old in (
        ("tokens", token_limit, projection.token_limit),
        ("active_ms", active_ms_limit, projection.active_ms_limit),
    ):
        if value is not None and (old is None or value > old):
            controller.authorize(dimension, value, authorized_by="initial-request")  # type: ignore[arg-type]
    return load_orchestration(paths.root)


def find_exact_orchestration(workspace_root: Path, request_id: str) -> Path | None:
    _schema(digest_value, request_id, "orchestration request ID")
    path = OrchestrationPaths.for_request(workspace_root, request_id).root
    if not path.exists():
        return None
    return load_orchestration(path).paths.root


def find_open_orchestrations_for_child(
    workspace_root: Path,
    child_run_id: str,
    *,
    require_unique: bool = False,
) -> tuple[Path, ...]:
    _schema(safe_id, child_run_id, "child run ID")
    namespace = Path(workspace_root).resolve() / "runs" / ".re-v2-orchestrations"
    if not namespace.exists():
        return ()
    if namespace.is_symlink() or not namespace.is_dir():
        raise DeepenOrchestrationError("orchestration namespace is unsafe")
    matches: list[Path] = []
    for path in sorted(namespace.iterdir(), key=lambda item: item.name):
        if path.is_symlink() or not path.is_dir():
            continue
        intent = load_orchestration(path)
        projection = _replay_projection(intent.events.replay())
        if projection.state != "complete" and child_run_id in {
            projection.l3_run_id,
            projection.l4_run_id,
            projection.closure_run_id,
        }:
            matches.append(path)
    if require_unique and len(matches) > 1:
        raise DeepenOrchestrationError("multiple open orchestrations name this child")
    return tuple(matches)


def evaluate_l3_eligibility(
    parent: ValidatedL3ParentV1,
    selection: SelectionScopeV1,
) -> ValidatedL3ParentV1:
    """Authenticate exact selected target closure and the closed L4 blocker set."""
    if not isinstance(parent, ValidatedL3ParentV1) or not isinstance(
        selection, SelectionScopeV1
    ):
        raise DeepenOrchestrationError("L3 eligibility inputs are invalid")
    # Projection construction is the canonical strict selection coverage check.
    catalog = build_l3_target_projections(parent, selection)
    selected_ids = {item.identity for item in catalog.projections}
    selected = tuple(
        item
        for item in parent.targets
        if any(
            projection.identity in selected_ids
            and projection.source_id == item.source_id
            and projection.target_kind == item.target_kind
            and projection.target_id == item.target_id
            for projection in catalog.projections
        )
    )
    unresolved = {
        finding_id for item in selected for finding_id in item.unresolved_finding_ids
    }
    if unresolved:
        if parent.terminal_state != "blocked" or parent.blocker_classes != (
            "requires_deeper_evidence",
        ):
            raise DeepenOrchestrationError(
                "selected L3 findings are not exclusively requires_deeper_evidence"
            )
        if any(
            item.closure_state != "deeper-evidence-blocked"
            for item in selected
            if item.unresolved_finding_ids
        ):
            raise DeepenOrchestrationError(
                "selected unresolved L3 target is not frozen for deeper evidence"
            )
    elif parent.terminal_state != "complete":
        raise DeepenOrchestrationError("selected L3 authority is not terminal-complete")
    return parent


def resolve_l4_parent(
    workspace_root: Path,
    from_run: str | Path,
    selection: SelectionScopeV1,
) -> ResolvedL4ParentV1:
    """Traverse supported synthesis/checkpoint lineage to exact L3 analysis authority."""
    root = Path(workspace_root).resolve()
    requested = Path(from_run)
    input_run = (
        requested.resolve()
        if requested.is_absolute()
        else (root / "runs" / requested).resolve()
    )
    runs = (root / "runs").resolve()
    if input_run.parent != runs or input_run.is_symlink() or not input_run.is_dir():
        raise DeepenOrchestrationError("L4 input run is unsafe or missing")
    return _resolve_l4_parent_run(root, input_run, input_run, selection, set())


def _resolve_l4_parent_run(
    workspace_root: Path,
    input_run: Path,
    run_dir: Path,
    selection: SelectionScopeV1,
    visited: set[str],
) -> ResolvedL4ParentV1:
    from harness.re_v2.protocol_25.model import RunManifestV4
    from harness.re_v2.protocol_26.model import RunManifestV5
    from harness.re_v2.protocol_27.model import RunManifestV6
    from harness.re_v2.run_store import load_run_manifest

    manifest = load_run_manifest(run_dir)
    if manifest.run_id in visited:
        raise DeepenOrchestrationError("L4 input lineage contains a cycle")
    visited.add(manifest.run_id)
    if isinstance(manifest, RunManifestV6):
        selected_sources = (
            {item.source_id for item in manifest.accepted_sources}
            if selection.all_sources
            else set(selection.source_ids)
        )
        outcomes = {item.source_id: item for item in manifest.accepted_sources}
        unknown = selected_sources - set(outcomes)
        if unknown:
            raise DeepenOrchestrationError(
                "selected synthesis source is unavailable: " + ",".join(sorted(unknown))
            )
        partial = tuple(
            sorted(
                source_id
                for source_id in selected_sources
                if outcomes[source_id].outcome == "partial"
            )
        )
        if partial:
            raise DeepenOrchestrationError(
                "selected synthesis source requires the next explicit L3 audit epoch: "
                + ",".join(partial)
            )
        parent_dir = workspace_root / "runs" / manifest.parent_run_id
        if not parent_dir.is_dir() or parent_dir.is_symlink():
            raise DeepenOrchestrationError("synthesis analysis parent is unavailable")
        return _resolve_l4_parent_run(
            workspace_root, input_run, parent_dir, selection, visited
        )
    if isinstance(manifest, RunManifestV4) or (
        isinstance(manifest, RunManifestV5) and manifest.target_layer == "L3"
    ):
        from echelon.cli import _re_v2_context

        context = _re_v2_context(workspace_root, run_dir)
        parent, objects = _validated_l3_parent_from_context(context, selection)
        evaluate_l3_eligibility(parent, selection)
        return ResolvedL4ParentV1(input_run, run_dir, parent, objects, False)
    if isinstance(manifest, RunManifestV5) and manifest.target_layer not in {
        "L1",
        "L2",
    }:
        raise DeepenOrchestrationError("unsupported protocol-2.6 analysis layer")
    # A compatible L0/L1/L2 run has no L3 authority yet.  The orchestration
    # layer binds one automatic protocol-2.5 prerequisite before L4 staging.
    return ResolvedL4ParentV1(input_run, run_dir, None, {}, True)


def _validated_l3_parent_from_context(
    context: object,
    selection: SelectionScopeV1,
) -> tuple[ValidatedL3ParentV1, Mapping[str, bytes]]:
    from harness.re_v2.protocol_22.schema import load_canonical_object
    from harness.re_v2.protocol_25.artifacts import (
        AuditCandidateV1,
        SemanticResolutionOverlayV1,
    )
    from harness.re_v2.protocol_25.recovery import (
        Protocol25RunContext,
        recover_protocol_25_run,
    )
    from harness.re_v2.run_store import load_run_manifest

    if not isinstance(context, Protocol25RunContext):
        raise DeepenOrchestrationError("resolved L3 run has no protocol-2.5 context")
    recovered = recover_protocol_25_run(context)
    state = recovered.controller_state
    if state.terminal_state not in {"complete", "blocked_plateau"}:
        reason = state.terminal_state or "unfinished"
        raise DeepenOrchestrationError(f"L3 authority is terminal-ineligible: {reason}")
    if state.audit_epoch_id is None or len(recovered.ledger.audit_epochs) != 1:
        raise DeepenOrchestrationError("L3 authority has no unique frozen audit epoch")
    if state.deferred_observation_ids:
        raise DeepenOrchestrationError(
            "L3 authority requires the next explicit audit epoch"
        )
    events = recovered.events
    if not events or events[-1].type not in {"run_completed", "run_failed"}:
        raise DeepenOrchestrationError("L3 authority has no terminal event")

    active_manifest = load_run_manifest(context.paths.root.parent)
    manifest_bytes = canonical_json_bytes(active_manifest.to_json_dict())
    manifest_hash = content_digest(manifest_bytes)
    terminal = events[-1]
    terminal_bytes = canonical_json_bytes(terminal.identity_dict())
    terminal_hash = terminal.event_hash
    if content_digest(terminal_bytes) != terminal_hash:
        raise DeepenOrchestrationError("L3 terminal event identity is invalid")

    epoch = next(iter(recovered.ledger.audit_epochs.values()))
    target_states = {item.audit_target_id: item for item in state.targets}
    entries = {
        item.audit_target_id: item for item in epoch.target_candidate_authorities
    }
    overlays_by_target: dict[str, list[str]] = {}
    for acceptance in recovered.ledger.accepted_artifacts.values():
        if acceptance.artifact_key.artifact_kind != "semantic-resolution-overlay":
            continue
        overlay = load_canonical_object(
            context.object_store.read_blob(acceptance.artifact_hash),
            SemanticResolutionOverlayV1.from_json_dict,
        )
        overlays_by_target.setdefault(overlay.audit_target_id, []).append(
            overlay.identity
        )

    objects: dict[str, bytes] = dict(context.semantic_inputs.immutable_objects)
    objects[manifest_hash] = manifest_bytes
    objects[terminal_hash] = terminal_bytes
    objects[epoch.identity] = canonical_json_bytes(epoch.to_json_dict())
    blockers: set[str] = set()
    targets: list[ValidatedL3TargetV1] = []
    selected_source_ids = (
        {item.source_id for item in state.targets}
        if selection.all_sources
        else set(selection.source_ids)
    )
    for target_id, entry in sorted(entries.items()):
        candidate_bytes = context.object_store.read_blob(entry.candidate_hash)
        candidate = load_canonical_object(
            candidate_bytes, AuditCandidateV1.from_json_dict
        )
        scope = candidate.audit_target.scope
        target_key = scope.domain_key or scope.source_id
        if scope.source_id not in selected_source_ids:
            continue
        if (
            candidate.audit_target.target_kind == "domain"
            and selection.domain_keys
            and target_key not in set(selection.domain_keys)
        ):
            continue
        controller_target = target_states.get(target_id)
        if controller_target is None or controller_target.audit_state != "accepted":
            raise DeepenOrchestrationError("selected L3 audit target is unfinished")
        unresolved = controller_target.unresolved_finding_ids
        finding_by_id = {item.finding_key_id: item for item in candidate.findings}
        classes = {finding_by_id[item].finding_key.finding_class for item in unresolved}
        blockers.update(classes)
        for finding in candidate.findings:
            key_bytes = canonical_json_bytes(finding.finding_key.to_json_dict())
            if content_digest(key_bytes) != finding.finding_key_id:
                raise DeepenOrchestrationError("L3 finding key identity is invalid")
            objects[finding.finding_key_id] = key_bytes
        objects[candidate.identity] = candidate_bytes
        entry_bytes = canonical_json_bytes(entry.to_json_dict())
        objects[entry.identity] = entry_bytes
        receipts = tuple(
            sorted(
                item.identity
                for item in recovered.ledger.latest_finding_closures.values()
                if item.audit_target_id == target_id
            )
        )
        for receipt_id in receipts:
            objects[receipt_id] = context.object_store.read_blob(receipt_id)
        overlay_ids = tuple(sorted(overlays_by_target.get(target_id, ())))
        for overlay_id in overlay_ids:
            objects[overlay_id] = context.object_store.read_blob(overlay_id)
        for lower_id in candidate.audit_target.lower_dependency_hashes:
            objects[lower_id] = context.object_store.read_blob(lower_id)
        targets.append(
            ValidatedL3TargetV1(
                1,
                candidate.audit_target.target_kind,
                scope.source_id,
                target_key,
                scope.content_id,
                candidate.identity,
                entry.finding_key_ids,
                unresolved,
                overlay_ids,
                receipts,
                "deeper-evidence-blocked" if unresolved else "complete",
                candidate.audit_target.lower_dependency_hashes,
                epoch.audit_policy_hash,
                epoch.executor_authority_hash,
                epoch.identity,
                entry.identity,
            )
        )
    if not targets:
        raise DeepenOrchestrationError("selected L3 authority contains no targets")
    if blockers - {"requires_deeper_evidence"}:
        raise DeepenOrchestrationError(
            "selected L3 blocker set is ineligible for L4: "
            + ",".join(sorted(blockers))
        )
    semantic_manifest = context.semantic_graph.manifest
    workspace_bytes = canonical_json_bytes(
        context.semantic_inputs.workspace_partition.to_json_dict()
    )
    artifact_policy_bytes = canonical_json_bytes(
        context.semantic_inputs.artifact_policy.to_json_dict()
    )
    objects[content_digest(workspace_bytes)] = workspace_bytes
    objects[content_digest(artifact_policy_bytes)] = artifact_policy_bytes
    lower_ids = tuple(
        sorted({item for target in targets for item in target.relevant_l2_root_ids})
    )
    parent = ValidatedL3ParentV1(
        1,
        active_manifest.run_id,
        manifest_hash,
        terminal_hash,
        active_manifest.source_snapshot_id,
        active_manifest.partition_manifest_id,
        selection.identity,
        epoch.identity,
        "blocked" if blockers else "complete",
        tuple(sorted(blockers)),
        context.semantic_inputs.workspace_partition.identity,
        context.semantic_inputs.artifact_policy.identity,
        lower_ids,
        tuple(sorted(targets, key=lambda item: item.sort_key)),
    )
    # Preserve the semantic manifest authority too when protocol 2.6 is the
    # outer run envelope; it remains useful lineage evidence but is not the
    # direct parent identity.
    semantic_bytes = canonical_json_bytes(semantic_manifest.to_json_dict())
    objects[content_digest(semantic_bytes)] = semantic_bytes
    return parent, objects


def execute_deepen_orchestration(
    workspace_root: Path,
    options: Protocol28OrchestrationOptions,
    provider_factory: Callable[[], object],
) -> Protocol28OrchestrationResult:
    """Advance one exact L3 -> L4 -> closure chain as far as authority permits."""
    from datetime import datetime, timezone

    from harness.re_v2.protocol_28.closure import (
        create_or_reuse_l4_closure_successor,
    )
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.inputs import (
        Protocol28ClosureInputs,
        Protocol28CreationInputs,
    )
    from harness.re_v2.protocol_28.lifecycle import (
        Protocol28CheckpointAdoptionV1,
        create_or_reuse_protocol_28_child,
        run_protocol_28_exhaustive,
    )
    from harness.re_v2.run_store import load_run_manifest

    if not isinstance(options, Protocol28OrchestrationOptions):
        raise DeepenOrchestrationError("protocol-2.8 orchestration options are invalid")
    if options.request.selection != options.selection:
        raise DeepenOrchestrationError(
            "orchestration request selection differs from execution selection"
        )
    clock = options.clock or (
        lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    root = Path(workspace_root).resolve()
    intent = create_or_load_orchestration(
        root,
        options.request,
        clock=clock,
        token_limit=options.token_limit,
        active_ms_limit=options.active_ms_limit,
    )
    controller = DeepenOrchestrationController(intent, clock=clock)
    projection = controller.rebuild_projection()
    resolved = resolve_l4_parent(root, options.from_run, options.selection)

    if resolved.prerequisite_required:
        if options.l3_prerequisite_factory is None:
            controller.block("l3", "l3_prerequisite_required")
            return _orchestration_result(controller.rebuild_projection())
        if projection.l3_run_id is None:
            l3_dir = options.l3_prerequisite_factory(
                root, resolved.analysis_run_dir, options.selection
            )
            l3_manifest = load_run_manifest(l3_dir)
            controller.bind_l3_child(
                l3_manifest.run_id,
                content_digest(canonical_json_bytes(l3_manifest.to_json_dict())),
            )
        else:
            l3_dir = root / "runs" / projection.l3_run_id
        try:
            resolved = resolve_l4_parent(root, l3_dir, options.selection)
        except DeepenOrchestrationError:
            controller.block("l3", "l3_prerequisite_not_terminal")
            return _orchestration_result(controller.rebuild_projection())

    if resolved.selected_l3 is None:
        controller.block("l3", "l3_prerequisite_unavailable")
        return _orchestration_result(controller.rebuild_projection())
    l3 = resolved.selected_l3
    projection = controller.rebuild_projection()
    if projection.l3_run_id is None:
        controller.bind_l3_child(l3.run_id, l3.manifest_hash)
    controller.satisfy_l3(
        l3.run_id,
        l3.terminal_event_hash,
        manifest_hash=l3.manifest_hash,
    )

    projection = controller.rebuild_projection()
    if projection.state == "awaiting_l4":
        created = options.l4_inputs_factory(resolved, intent)
        if not isinstance(created, Protocol28CreationInputs):
            raise DeepenOrchestrationError(
                "L4 input factory did not return Protocol28CreationInputs"
            )
        manifest = created.manifest
        if (
            manifest.selection != options.selection
            or manifest.lineage.direct_parent_run_id != l3.run_id
            or manifest.lineage.direct_parent_manifest_hash != l3.manifest_hash
            or manifest.lineage.direct_parent_terminal_event_hash
            != l3.terminal_event_hash
        ):
            raise DeepenOrchestrationError(
                "prepared L4 child does not bind the resolved L3 authority"
            )
        checkpoint_adoption = None
        if options.checkpoint_adoption_factory is not None:
            checkpoint_adoption = options.checkpoint_adoption_factory(created)
            if checkpoint_adoption is not None and not isinstance(
                checkpoint_adoption, Protocol28CheckpointAdoptionV1
            ):
                raise DeepenOrchestrationError(
                    "checkpoint adoption factory returned invalid authority"
                )
        l4_dir = create_or_reuse_protocol_28_child(
            root,
            created,
            checkpoint_adoption=checkpoint_adoption,
        )
        l4_manifest = load_run_manifest(l4_dir)
        if projection.l4_run_id is None:
            controller.bind_l4_child(
                l4_manifest.run_id,
                content_digest(canonical_json_bytes(l4_manifest.to_json_dict())),
            )
    else:
        if projection.l4_run_id is None:
            raise DeepenOrchestrationError("orchestration lost its L4 child binding")
        l4_dir = root / "runs" / projection.l4_run_id

    l4_result = run_protocol_28_exhaustive(l4_dir, provider_factory)  # type: ignore[arg-type]
    if l4_result.run_root_id is None:
        controller.block("l4", l4_result.reason_code or l4_result.state)
        return _orchestration_result(controller.rebuild_projection())
    l4_context = load_protocol_28_run_context(l4_dir)
    l4_events = l4_context.events.replay()
    if not l4_events:
        raise DeepenOrchestrationError("L4 child has no completion boundary event")
    closure_required = bool(l3.blocker_classes)
    controller.complete_l4(
        l4_result.run_id,
        l4_events[-1].event_hash,
        closure_required=closure_required,
    )
    if not closure_required:
        return _orchestration_result(controller.rebuild_projection())

    if options.closure_inputs_factory is None:
        controller.block("closure", "closure_inputs_required")
        return _orchestration_result(controller.rebuild_projection())
    projection = controller.rebuild_projection()
    if projection.closure_run_id is None:
        closure_inputs = options.closure_inputs_factory(resolved, l4_dir)
        if not isinstance(closure_inputs, Protocol28ClosureInputs):
            raise DeepenOrchestrationError(
                "closure input factory did not return Protocol28ClosureInputs"
            )
        closure_dir = create_or_reuse_l4_closure_successor(root, closure_inputs)
        closure_manifest = load_run_manifest(closure_dir)
        controller.bind_closure_child(
            closure_manifest.run_id,
            content_digest(canonical_json_bytes(closure_manifest.to_json_dict())),
        )
    else:
        closure_dir = root / "runs" / projection.closure_run_id
        # Exact replay is provider-free and repairs a missing deterministic suffix.
        from harness.re_v2.protocol_28.closure import complete_l4_closure_successor

        complete_l4_closure_successor(closure_dir)
    closure_context = load_protocol_28_run_context(closure_dir)
    closure_events = closure_context.events.replay()
    if not closure_events:
        raise DeepenOrchestrationError("closure child has no terminal event")
    controller.complete_closure(closure_dir.name, closure_events[-1].event_hash)
    return _orchestration_result(controller.rebuild_projection())


def _orchestration_result(
    projection: DeepenOrchestrationProjectionV1,
) -> Protocol28OrchestrationResult:
    return Protocol28OrchestrationResult(
        projection.request_id,
        projection.state,
        projection.l3_run_id,
        projection.l4_run_id,
        projection.closure_run_id,
        projection.blocked_stage,
        projection.blocked_reason_code,
    )


__all__ = (
    "DeepenOrchestrationController",
    "DeepenOrchestrationError",
    "DeepenOrchestrationIntentV1",
    "DeepenOrchestrationProjectionV1",
    "DeepenOrchestrationRequestV1",
    "ORCHESTRATION_EVENTS",
    "OrchestrationPaths",
    "Protocol28OrchestrationOptions",
    "Protocol28OrchestrationResult",
    "ResolvedL4ParentV1",
    "create_or_load_orchestration",
    "find_exact_orchestration",
    "find_open_orchestrations_for_child",
    "evaluate_l3_eligibility",
    "execute_deepen_orchestration",
    "resolve_l4_parent",
    "load_orchestration",
)
