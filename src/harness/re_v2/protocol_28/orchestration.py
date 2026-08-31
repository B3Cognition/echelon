"""Durable, content-free L3-to-L4 orchestration intent authority."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
from typing import Callable, ClassVar, Literal, Mapping

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


class DeepenOrchestrationError(RuntimeError):
    """Raised when durable L4 orchestration authority is invalid."""


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
        _schema(literal, self.schema_version, 1, "DeepenOrchestrationRequestV1.schema_version")
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
            _schema(digest_value, getattr(self, field), f"DeepenOrchestrationRequestV1.{field}")
        if not isinstance(self.selection, SelectionScopeV1):
            raise DeepenOrchestrationError("DeepenOrchestrationRequestV1.selection is invalid")

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
            current = self.token_limit if dimension == "tokens" else self.active_ms_limit
            if payload["old_value"] != current or int(payload["new_value"]) <= (current or 0):
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
            self.state = "awaiting_closure" if payload["closure_required"] else "complete"
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
        setattr(self, name, (str(payload["run_id"]), str(payload["manifest_hash"]), None))

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
            raise ReV2EventError(f"{event_type} has unknown fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ReV2EventError(f"{event_type} is missing fields: {', '.join(sorted(missing))}")
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
        root = Path(workspace_root).resolve() / "runs" / ".re-v2-orchestrations" / request_id
        return cls(root, root / "request.json", root / "events.jsonl", root / "projection.json")


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
        l3[0], l3[1], l3[2],
        l4[0], l4[1], l4[2],
        closure[0], closure[1], closure[2],
        blocked[0], blocked[1],
    )


def _replay_projection(events: tuple[EventRecord, ...]) -> DeepenOrchestrationProjectionV1:
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
        _atomic_replace(self.intent.paths.projection, canonical_json_bytes(value.to_json_dict()))
        return value

    def _append_once(self, event_type: str, payload: Mapping[str, object]) -> EventRecord:
        canonical = self.intent.events.protocol.canonical_payload(event_type, payload)
        matching = tuple(event for event in self.intent.events.replay() if event.type == event_type)
        for event in matching:
            if event.payload == canonical:
                self.rebuild_projection()
                return event
        if event_type in {"l3_child_bound", "l3_satisfied", "l4_child_bound", "l4_completed", "closure_child_bound", "closure_completed"} and matching:
            raise DeepenOrchestrationError(f"orchestration already binds or completes {event_type}")
        try:
            event = self.intent.events.append(event_type, payload, occurred_at=self.clock())
        except ReV2EventError as exc:
            raise DeepenOrchestrationError(str(exc)) from exc
        if self.fault is not None:
            self.fault("after_event_before_projection")
        self.rebuild_projection()
        return event

    def authorize(self, dimension: Literal["tokens", "active_ms"], new_value: int, *, authorized_by: str) -> EventRecord:
        current = self.rebuild_projection()
        old = current.token_limit if dimension == "tokens" else current.active_ms_limit
        if not isinstance(new_value, int) or isinstance(new_value, bool) or new_value <= (old or 0):
            raise DeepenOrchestrationError("resource authorization must be an increase")
        return self._append_once("resource_authorized", {"authorized_by": authorized_by, "dimension": dimension, "new_value": new_value, "old_value": old})

    def bind_l3_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once("l3_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash})

    def satisfy_l3(self, run_id: str, terminal_event_hash: str, *, manifest_hash: str | None = None) -> EventRecord:
        current = self.rebuild_projection()
        if current.l3_run_id != run_id or (manifest_hash is not None and current.l3_manifest_hash != manifest_hash):
            raise DeepenOrchestrationError("L3 completion does not match bound child")
        assert current.l3_manifest_hash is not None
        return self._append_once("l3_satisfied", {"run_id": run_id, "manifest_hash": current.l3_manifest_hash, "terminal_event_hash": terminal_event_hash})

    def bind_l4_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once("l4_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash})

    def complete_l4(self, run_id: str, terminal_event_hash: str, *, closure_required: bool) -> EventRecord:
        current = self.rebuild_projection()
        if current.l4_run_id != run_id or current.l4_manifest_hash is None:
            raise DeepenOrchestrationError("L4 completion does not match bound child")
        return self._append_once("l4_completed", {"run_id": run_id, "manifest_hash": current.l4_manifest_hash, "terminal_event_hash": terminal_event_hash, "closure_required": closure_required})

    def bind_closure_child(self, run_id: str, manifest_hash: str) -> EventRecord:
        return self._append_once("closure_child_bound", {"run_id": run_id, "manifest_hash": manifest_hash})

    def complete_closure(self, run_id: str, terminal_event_hash: str) -> EventRecord:
        current = self.rebuild_projection()
        if current.closure_run_id != run_id or current.closure_manifest_hash is None:
            raise DeepenOrchestrationError("closure completion does not match bound child")
        return self._append_once("closure_completed", {"run_id": run_id, "manifest_hash": current.closure_manifest_hash, "terminal_event_hash": terminal_event_hash})


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
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
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
    paths = OrchestrationPaths(root, root / "request.json", root / "events.jsonl", root / "projection.json")
    if paths.request.is_symlink() or not paths.request.is_file():
        raise DeepenOrchestrationError("orchestration request is unsafe or missing")
    try:
        raw = json.loads(paths.request.read_bytes())
        request = DeepenOrchestrationRequestV1.from_json_dict(raw)
    except (OSError, json.JSONDecodeError, DeepenOrchestrationError) as exc:
        raise DeepenOrchestrationError(f"invalid orchestration request: {exc}") from exc
    if root.name != request.request_id:
        raise DeepenOrchestrationError("orchestration directory does not match request identity")
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
        events.append("orchestration_created", {"request_id": request.request_id, "request_object_id": request.identity}, occurred_at=clock())
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


__all__ = (
    "DeepenOrchestrationController",
    "DeepenOrchestrationError",
    "DeepenOrchestrationIntentV1",
    "DeepenOrchestrationProjectionV1",
    "DeepenOrchestrationRequestV1",
    "ORCHESTRATION_EVENTS",
    "OrchestrationPaths",
    "create_or_load_orchestration",
    "find_exact_orchestration",
    "find_open_orchestrations_for_child",
    "load_orchestration",
)
