"""Durable, exact authority for controller post-dispatch completion effects."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from harness.prepared_phase_result import (
    _bounded_detach_untrusted,
    _canonical_payload_sha256,
)
from harness.reasoning_journal_store import (
    JournalStoreError,
    REASONING_JOURNAL_LOCK_RANK,
    durably_replace_file as _store_durably_replace_file,
    read_reasoning_journal as _store_read_reasoning_journal,
    reasoning_journal_lock as _store_reasoning_journal_lock,
)
from harness.state_transaction_namespace import (
    validate_pending_controller_completion,
    validate_pending_external_publication,
)


_SCHEMA_VERSION = 1
_OUTBOX_DIRECTORY = ".completion-outbox"
_INTENT_NAME = "intent.json"
_RECEIPTS_NAME = "receipts.json"
_MAX_INTENT_BYTES = 4_194_304
_MAX_RECEIPTS_BYTES = 1_048_576
_MAX_CONTEXT_REASON_LENGTH = 4_096
_MAX_PHASE_LENGTH = 1_024
_COMPLETION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_GIT_OBJECT_ID_PATTERN = re.compile(
    r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z"
)
_EFFECT_ORDER = ("journal", "timing", "checkpoint", "context", "mining")
_ERROR_CODES = frozenset(
    {
        "intent_invalid",
        "intent_mismatch",
        "receipts_invalid",
        "receipts_mismatch",
        "stage_corrupt",
        "stage_missing",
        "stage_io",
    }
)
_COMPLETION_STAMP_KEYS = frozenset(
    {"completion_id", "entry_index", "content_sha256"}
)


class CompletionError(Exception):
    """Bounded completion failure that never includes producer or path text."""

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in _ERROR_CODES:
            code = "stage_io"
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class CompletionMarker:
    """Exact state-store identity for one sealed completion intent."""

    schema_version: int
    completion_id: str
    intent_sha256: str
    publication_binding_sha256: str
    receipts_sha256: str
    origin: str
    step: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "completion_id": self.completion_id,
            "intent_sha256": self.intent_sha256,
            "publication_binding_sha256": (
                self.publication_binding_sha256
            ),
            "receipts_sha256": self.receipts_sha256,
            "origin": self.origin,
            "step": self.step,
        }


@dataclass(frozen=True)
class CompletionIntent:
    """An immutable view of one validated canonical completion intent."""

    completion_id: str
    origin: str
    effect_plan: tuple[str, ...]
    context_reason: str
    mine_phase_a: bool
    judgment_payload_sha256: tuple[str, ...]
    _publication_json: bytes = field(repr=False)
    _route_json: bytes = field(repr=False)
    _checkpoint_prestate_json: bytes = field(repr=False)
    _judgments_json: bytes = field(repr=False)

    @property
    def publication(self) -> dict[str, object]:
        return _decode_snapshot(self._publication_json)

    @property
    def route(self) -> dict[str, object]:
        return _decode_snapshot(self._route_json)

    @property
    def checkpoint_prestate(self) -> dict[str, object]:
        return _decode_snapshot(self._checkpoint_prestate_json)

    @property
    def judgments(self) -> tuple[dict[str, object], ...]:
        return tuple(_decode_snapshot(self._judgments_json))

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "completion_id": self.completion_id,
            "origin": self.origin,
            "publication": self.publication,
            "route": self.route,
            "effect_plan": list(self.effect_plan),
            "checkpoint_prestate": self.checkpoint_prestate,
            "context_reason": self.context_reason,
            "mine_phase_a": self.mine_phase_a,
            "judgment_payload_sha256": list(
                self.judgment_payload_sha256
            ),
            "judgments": list(self.judgments),
        }


@dataclass(frozen=True)
class PreparedControllerCompletion:
    """A loaded completion stage bound to its exact marker and intent."""

    marker: CompletionMarker
    intent: CompletionIntent
    _transaction_root: Path = field(repr=False)
    _transaction_identity: tuple[int, int, int] = field(repr=False)
    _receipts_json: bytes = field(repr=False)

    @property
    def receipts(self) -> dict[str, object]:
        return _decode_snapshot(self._receipts_json)

    def discard(self) -> None:
        """Discard only this exact unreferenced stage; repeated calls are safe."""
        root = self._transaction_root
        if (
            root.name != self.marker.completion_id
            or root.parent.name != _OUTBOX_DIRECTORY
        ):
            raise CompletionError("stage_corrupt")
        _discard_exact_transaction(
            root.parent,
            self.marker.completion_id,
            self._transaction_identity,
            missing_ok=True,
        )


@dataclass(frozen=True)
class JournalPlan:
    """Immutable controller-owned content for one completion journal batch."""

    completion_id: str
    phase: str
    journal: Path
    content_sha256: tuple[str, ...]
    _rows_json: bytes = field(repr=False)

    @property
    def rows(self) -> tuple[dict[str, object], ...]:
        value = _decode_snapshot(self._rows_json)
        if type(value) is not list:
            raise AssertionError("invalid internal journal plan snapshot")
        return tuple(value)


def _raise(code: str) -> None:
    raise CompletionError(code)


def _clone_json(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if type(value) is list:
        return [_clone_json(item) for item in value]
    if type(value) is tuple:
        return tuple(_clone_json(item) for item in value)
    if type(value) is dict:
        return {
            key: _clone_json(item)
            for key, item in dict.items(value)
        }
    _raise("intent_invalid")


def _decode_snapshot(content: bytes) -> Any:
    """Decode private canonical bytes so no mutable authority is exposed."""
    try:
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise AssertionError("invalid internal completion snapshot")


def _normalize_json(value: Any) -> Any:
    if value is None or type(value) in (bool, int, float, str):
        return value
    if type(value) in (list, tuple):
        return [_normalize_json(item) for item in value]
    if type(value) is dict:
        return {
            key: _normalize_json(item)
            for key, item in dict.items(value)
        }
    _raise("intent_invalid")


def _canonical_json(value: object, *, newline: bool = True) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if newline:
            encoded += "\n"
        return encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _raise("intent_invalid")


def _validate_exact_dict(
    value: object,
    keys: frozenset[str],
    *,
    code: str = "intent_invalid",
) -> dict[str, object]:
    if type(value) is not dict or frozenset(dict.keys(value)) != keys:
        _raise(code)
    return value


def _validate_completion_id(value: object) -> str:
    if (
        type(value) is not str
        or _COMPLETION_ID_PATTERN.fullmatch(value) is None
    ):
        _raise("intent_invalid")
    return value


def _validate_sha256(value: object) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        _raise("intent_invalid")
    return value


def _validate_bounded_string(
    value: object,
    *,
    maximum: int,
) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
    ):
        _raise("intent_invalid")
    return value


def _validate_publication(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _raise("intent_invalid")
    kind = dict.get(value, "kind")
    if kind == "none":
        _validate_exact_dict(value, frozenset({"kind"}))
        return {"kind": "none"}
    if kind == "external":
        _validate_exact_dict(value, frozenset({"kind", "marker"}))
        try:
            marker = validate_pending_external_publication(
                dict.__getitem__(value, "marker")
            )
        except ValueError:
            _raise("intent_invalid")
        return {"kind": "external", "marker": marker}
    _raise("intent_invalid")


def _validate_route(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _raise("intent_invalid")
    kind = dict.get(value, "kind")
    if kind == "routed":
        _validate_exact_dict(
            value,
            frozenset(
                {
                    "kind",
                    "from_phase",
                    "to_phase",
                    "manual_phase_run",
                    "record_completion",
                }
            ),
        )
        manual = dict.__getitem__(value, "manual_phase_run")
        record = dict.__getitem__(value, "record_completion")
        if type(manual) is not bool or type(record) is not bool:
            _raise("intent_invalid")
        return {
            "kind": "routed",
            "from_phase": _validate_bounded_string(
                dict.__getitem__(value, "from_phase"),
                maximum=_MAX_PHASE_LENGTH,
            ),
            "to_phase": _validate_bounded_string(
                dict.__getitem__(value, "to_phase"),
                maximum=_MAX_PHASE_LENGTH,
            ),
            "manual_phase_run": manual,
            "record_completion": record,
        }
    if kind == "terminal":
        _validate_exact_dict(
            value,
            frozenset({"kind", "terminal_phase"}),
        )
        return {
            "kind": "terminal",
            "terminal_phase": _validate_bounded_string(
                dict.__getitem__(value, "terminal_phase"),
                maximum=_MAX_PHASE_LENGTH,
            ),
        }
    _raise("intent_invalid")


def _validate_effect_plan(value: object) -> list[str]:
    if type(value) not in (list, tuple):
        _raise("intent_invalid")
    effects: list[str] = []
    previous_index = -1
    for effect in value:
        if type(effect) is not str or effect not in _EFFECT_ORDER:
            _raise("intent_invalid")
        index = _EFFECT_ORDER.index(effect)
        if index <= previous_index:
            _raise("intent_invalid")
        effects.append(effect)
        previous_index = index
    return effects


def _validate_checkpoint_prestate(
    value: object,
    *,
    checkpoint_planned: bool,
) -> dict[str, object]:
    if type(value) is not dict:
        _raise("intent_invalid")
    kind = dict.get(value, "kind")
    if not checkpoint_planned:
        _validate_exact_dict(value, frozenset({"kind"}))
        if kind != "none":
            _raise("intent_invalid")
        return {"kind": "none"}
    _validate_exact_dict(value, frozenset({"kind", "head"}))
    head = dict.__getitem__(value, "head")
    if (
        kind != "git_head"
        or type(head) is not str
        or _GIT_OBJECT_ID_PATTERN.fullmatch(head) is None
    ):
        _raise("intent_invalid")
    return {"kind": "git_head", "head": head}


def _validate_judgments(
    judgments_value: object,
    digests_value: object,
) -> tuple[list[dict[str, object]], list[str]]:
    if (
        type(judgments_value) not in (list, tuple)
        or type(digests_value) not in (list, tuple)
        or len(judgments_value) != len(digests_value)
    ):
        _raise("intent_invalid")
    judgments: list[dict[str, object]] = []
    digests: list[str] = []
    for judgment, digest_value in zip(
        judgments_value,
        digests_value,
        strict=True,
    ):
        record = _validate_exact_dict(
            judgment,
            frozenset(
                {"echelon_result", "quarantined_state_updates"}
            ),
        )
        echelon_result = dict.__getitem__(record, "echelon_result")
        quarantined = dict.__getitem__(
            record,
            "quarantined_state_updates",
        )
        if type(echelon_result) is not dict or type(quarantined) is not dict:
            _raise("intent_invalid")
        digest = _validate_sha256(digest_value)
        if _canonical_payload_sha256(echelon_result) != digest:
            _raise("intent_invalid")
        judgments.append(
            {
                "echelon_result": _clone_json(echelon_result),
                "quarantined_state_updates": _clone_json(quarantined),
            }
        )
        digests.append(digest)
    return judgments, digests


def _validate_intent(value: object) -> dict[str, object]:
    record = _validate_exact_dict(
        value,
        frozenset(
            {
                "schema_version",
                "completion_id",
                "origin",
                "publication",
                "route",
                "effect_plan",
                "checkpoint_prestate",
                "context_reason",
                "mine_phase_a",
                "judgment_payload_sha256",
                "judgments",
            }
        ),
    )
    schema_version = dict.__getitem__(record, "schema_version")
    if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
        _raise("intent_invalid")
    completion_id = _validate_completion_id(
        dict.__getitem__(record, "completion_id")
    )
    origin = dict.__getitem__(record, "origin")
    if type(origin) is not str or origin not in {"routed", "terminal"}:
        _raise("intent_invalid")
    publication = _validate_publication(
        dict.__getitem__(record, "publication")
    )
    route = _validate_route(dict.__getitem__(record, "route"))
    if origin != route["kind"]:
        _raise("intent_invalid")
    effect_plan = _validate_effect_plan(
        dict.__getitem__(record, "effect_plan")
    )
    if (
        origin == "routed"
        and route["record_completion"] is False
        and effect_plan != ["journal", "checkpoint"]
    ):
        _raise("intent_invalid")
    if origin == "terminal" and any(
        effect != "mining" for effect in effect_plan
    ):
        _raise("intent_invalid")
    checkpoint_prestate = _validate_checkpoint_prestate(
        dict.__getitem__(record, "checkpoint_prestate"),
        checkpoint_planned="checkpoint" in effect_plan,
    )
    context_reason = _validate_bounded_string(
        dict.__getitem__(record, "context_reason"),
        maximum=_MAX_CONTEXT_REASON_LENGTH,
    )
    mine_phase_a = dict.__getitem__(record, "mine_phase_a")
    if (
        type(mine_phase_a) is not bool
        or mine_phase_a != ("mining" in effect_plan)
    ):
        _raise("intent_invalid")
    judgments, judgment_digests = _validate_judgments(
        dict.__getitem__(record, "judgments"),
        dict.__getitem__(record, "judgment_payload_sha256"),
    )
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": completion_id,
        "origin": origin,
        "publication": publication,
        "route": route,
        "effect_plan": effect_plan,
        "checkpoint_prestate": checkpoint_prestate,
        "context_reason": context_reason,
        "mine_phase_a": mine_phase_a,
        "judgment_payload_sha256": judgment_digests,
        "judgments": judgments,
    }


def _validate_receipts(
    value: object,
    *,
    intent: dict[str, object],
) -> dict[str, object]:
    record = _validate_exact_dict(
        value,
        frozenset({"schema_version", "completion_id", "effects"}),
        code="receipts_invalid",
    )
    if (
        type(dict.__getitem__(record, "schema_version")) is not int
        or dict.__getitem__(record, "schema_version") != _SCHEMA_VERSION
        or dict.__getitem__(record, "completion_id")
        != intent["completion_id"]
        or type(dict.__getitem__(record, "effects")) is not dict
    ):
        _raise("receipts_invalid")
    effects = dict.__getitem__(record, "effects")
    plan = list(intent["effect_plan"])
    if any(
        type(key) is not str or key not in plan
        for key in dict.keys(effects)
    ):
        _raise("receipts_invalid")
    effect_indexes = sorted(plan.index(key) for key in dict.keys(effects))
    if effect_indexes != list(range(len(effect_indexes))):
        _raise("receipts_invalid")
    if any(type(receipt) is not dict for receipt in dict.values(effects)):
        _raise("receipts_invalid")
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": intent["completion_id"],
        "effects": _clone_json(effects),
    }


def _intent_view(value: dict[str, object]) -> CompletionIntent:
    return CompletionIntent(
        completion_id=str(value["completion_id"]),
        origin=str(value["origin"]),
        effect_plan=tuple(value["effect_plan"]),
        context_reason=str(value["context_reason"]),
        mine_phase_a=bool(value["mine_phase_a"]),
        judgment_payload_sha256=tuple(
            value["judgment_payload_sha256"]
        ),
        _publication_json=_canonical_json(
            value["publication"],
            newline=False,
        ),
        _route_json=_canonical_json(value["route"], newline=False),
        _checkpoint_prestate_json=_canonical_json(
            value["checkpoint_prestate"],
            newline=False,
        ),
        _judgments_json=_canonical_json(
            value["judgments"],
            newline=False,
        ),
    )


def _marker_from(value: object) -> CompletionMarker:
    try:
        marker = validate_pending_controller_completion(
            value.to_dict()
            if type(value) is CompletionMarker
            else value
        )
    except ValueError:
        _raise("intent_invalid")
    return CompletionMarker(
        schema_version=int(marker["schema_version"]),
        completion_id=str(marker["completion_id"]),
        intent_sha256=str(marker["intent_sha256"]),
        publication_binding_sha256=str(
            marker["publication_binding_sha256"]
        ),
        receipts_sha256=str(marker["receipts_sha256"]),
        origin=str(marker["origin"]),
        step=str(marker["step"]),
    )


def _require_real_directory(path: Path, *, missing_code: str) -> Path:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        _raise(missing_code)
    except OSError:
        _raise("stage_io")
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
        metadata.st_mode
    ):
        _raise("stage_corrupt")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        _raise("stage_corrupt")
    if resolved != path.absolute():
        _raise("stage_corrupt")
    return resolved


def _directory_identity(
    metadata: os.stat_result,
) -> tuple[int, int, int]:
    return (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _open_directory_fd(
    path: str | Path,
    *,
    dir_fd: int | None = None,
    missing_code: str,
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, dir_fd=dir_fd)
    except FileNotFoundError:
        _raise(missing_code)
    except (OSError, TypeError, NotImplementedError):
        _raise("stage_corrupt")
    try:
        metadata = os.fstat(fd)
    except OSError:
        os.close(fd)
        _raise("stage_corrupt")
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
        metadata.st_mode
    ):
        os.close(fd)
        _raise("stage_corrupt")
    return fd


def _remove_directory_contents_fd(directory_fd: int) -> None:
    """Remove descendants only through a retained exact directory FD."""
    try:
        names = os.listdir(directory_fd)
    except (OSError, TypeError, NotImplementedError):
        _raise("stage_io")
    for name in names:
        try:
            metadata = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            _raise("stage_corrupt")
        except (OSError, TypeError, NotImplementedError):
            _raise("stage_io")
        if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(
            metadata.st_mode
        ):
            child_fd = _open_directory_fd(
                name,
                dir_fd=directory_fd,
                missing_code="stage_corrupt",
            )
            try:
                opened = os.fstat(child_fd)
                if _directory_identity(opened) != _directory_identity(
                    metadata
                ):
                    _raise("stage_corrupt")
                _remove_directory_contents_fd(child_fd)
                current = os.stat(
                    name,
                    dir_fd=directory_fd,
                    follow_symlinks=False,
                )
                if _directory_identity(current) != _directory_identity(
                    opened
                ):
                    _raise("stage_corrupt")
                os.rmdir(name, dir_fd=directory_fd)
            except CompletionError:
                raise
            except FileNotFoundError:
                _raise("stage_corrupt")
            except (OSError, TypeError, NotImplementedError):
                _raise("stage_io")
            finally:
                os.close(child_fd)
        else:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except FileNotFoundError:
                _raise("stage_corrupt")
            except (OSError, TypeError, NotImplementedError):
                _raise("stage_io")
    try:
        os.fsync(directory_fd)
    except OSError:
        _raise("stage_io")


def _discard_exact_transaction(
    outbox: Path,
    completion_id: str,
    expected_identity: tuple[int, int, int],
    *,
    missing_ok: bool,
) -> None:
    try:
        outbox_fd = _open_directory_fd(
            outbox,
            missing_code="stage_missing",
        )
    except CompletionError as error:
        if missing_ok and error.code == "stage_missing":
            return
        raise
    transaction_fd: int | None = None
    try:
        try:
            transaction_fd = _open_directory_fd(
                completion_id,
                dir_fd=outbox_fd,
                missing_code="stage_missing",
            )
        except CompletionError as error:
            if missing_ok and error.code == "stage_missing":
                return
            raise
        try:
            entry = os.stat(
                completion_id,
                dir_fd=outbox_fd,
                follow_symlinks=False,
            )
            opened = os.fstat(transaction_fd)
        except FileNotFoundError:
            if missing_ok:
                return
            _raise("stage_missing")
        except (OSError, TypeError, NotImplementedError):
            _raise("stage_corrupt")
        if (
            stat.S_ISLNK(entry.st_mode)
            or not stat.S_ISDIR(entry.st_mode)
            or _directory_identity(entry) != expected_identity
            or _directory_identity(opened) != expected_identity
        ):
            _raise("stage_corrupt")
        _remove_directory_contents_fd(transaction_fd)
        try:
            current = os.stat(
                completion_id,
                dir_fd=outbox_fd,
                follow_symlinks=False,
            )
            if _directory_identity(current) != expected_identity:
                _raise("stage_corrupt")
            os.rmdir(completion_id, dir_fd=outbox_fd)
            os.fsync(outbox_fd)
        except CompletionError:
            raise
        except FileNotFoundError:
            _raise("stage_corrupt")
        except (OSError, TypeError, NotImplementedError):
            _raise("stage_io")
    finally:
        if transaction_fd is not None:
            os.close(transaction_fd)
        os.close(outbox_fd)


def _validate_roots(
    project_root: Path,
    squad_dir: Path,
) -> tuple[Path, Path]:
    if not isinstance(project_root, Path) or not isinstance(
        squad_dir,
        Path,
    ):
        _raise("stage_corrupt")
    project = _require_real_directory(
        project_root,
        missing_code="stage_missing",
    )
    squad = _require_real_directory(
        squad_dir,
        missing_code="stage_missing",
    )
    try:
        squad.relative_to(project)
    except ValueError:
        _raise("stage_corrupt")
    return project, squad


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        _raise("stage_io")
    try:
        os.fsync(fd)
    except OSError:
        _raise("stage_io")
    finally:
        os.close(fd)


def _ensure_outbox(squad_dir: Path) -> Path:
    outbox = squad_dir / _OUTBOX_DIRECTORY
    try:
        os.mkdir(outbox, 0o700)
    except FileExistsError:
        pass
    except OSError:
        _raise("stage_io")
    else:
        _fsync_directory(outbox)
        _fsync_directory(squad_dir)
    return _require_real_directory(outbox, missing_code="stage_missing")


def _create_transaction_root(
    squad_dir: Path,
    completion_id: str,
) -> tuple[Path, tuple[int, int, int]]:
    outbox = _ensure_outbox(squad_dir)
    transaction_root = outbox / completion_id
    try:
        os.mkdir(transaction_root, 0o700)
    except FileExistsError:
        _raise("stage_corrupt")
    except OSError:
        _raise("stage_io")
    try:
        metadata = os.lstat(transaction_root)
    except OSError:
        _raise("stage_corrupt")
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(
        metadata.st_mode
    ):
        _raise("stage_corrupt")
    transaction_identity = _directory_identity(metadata)
    try:
        _fsync_directory(transaction_root)
        _fsync_directory(outbox)
    except BaseException:
        try:
            _discard_exact_transaction(
                outbox,
                completion_id,
                transaction_identity,
                missing_ok=True,
            )
        except CompletionError:
            pass
        raise
    return transaction_root, transaction_identity


def _atomic_write(
    directory: Path,
    name: str,
    content: bytes,
    *,
    expected_identity: tuple[int, int, int],
) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory_fd = os.open(directory, flags)
    except OSError:
        _raise("stage_io")
    temporary_name = f".{name}-{secrets.token_hex(12)}.tmp"
    temporary_fd: int | None = None
    try:
        try:
            opened_directory = os.fstat(directory_fd)
        except OSError:
            _raise("stage_corrupt")
        if _directory_identity(opened_directory) != expected_identity:
            _raise("stage_corrupt")
        try:
            os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError:
            _raise("stage_io")
        else:
            _raise("stage_corrupt")
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        view = memoryview(content)
        while view:
            written = os.write(temporary_fd, view)
            if written <= 0:
                _raise("stage_io")
            view = view[written:]
        os.fsync(temporary_fd)
        os.close(temporary_fd)
        temporary_fd = None
        os.replace(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except CompletionError:
        raise
    except OSError:
        _raise("stage_io")
    finally:
        if temporary_fd is not None:
            try:
                os.close(temporary_fd)
            except OSError:
                pass
        try:
            os.unlink(temporary_name, dir_fd=directory_fd)
        except OSError:
            pass
        os.close(directory_fd)


def _read_regular(path: Path, *, maximum: int, code: str) -> bytes:
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_io")
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size > maximum
    ):
        _raise(code)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise(code)
    try:
        opened = os.fstat(fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino)
            != (before.st_dev, before.st_ino)
        ):
            _raise(code)
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(fd, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(fd)
        if (
            len(content) > maximum
            or (after.st_dev, after.st_ino, after.st_size)
            != (opened.st_dev, opened.st_ino, opened.st_size)
        ):
            _raise(code)
        return content
    except CompletionError:
        raise
    except OSError:
        _raise(code)
    finally:
        os.close(fd)


def _decode_canonical(
    content: bytes,
    *,
    code: str,
) -> object:
    try:
        value = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        _raise(code)
    try:
        canonical = _canonical_json(value)
    except (CompletionError, RecursionError):
        _raise(code)
    if canonical != content:
        _raise(code)
    return value


def _detach_loaded_json(
    value: object,
    *,
    root_path: str,
    code: str,
) -> object:
    try:
        return _normalize_json(
            _bounded_detach_untrusted(
                value,
                root_path=root_path,
            )
        )
    except Exception:
        _raise(code)


def prepare_controller_completion(
    project_root: Path,
    squad_dir: Path,
    *,
    completion_id: str,
    origin: str,
    publication: object,
    route: object,
    effect_plan: object,
    checkpoint_prestate: object,
    context_reason: object,
    mine_phase_a: object,
    judgment_payload_sha256: object,
    judgments: object,
) -> PreparedControllerCompletion:
    """Detach, validate, durably seal, and reread one completion intent."""
    completion_id = _validate_completion_id(completion_id)
    try:
        detached = _bounded_detach_untrusted(
            {
                "schema_version": _SCHEMA_VERSION,
                "completion_id": completion_id,
                "origin": origin,
                "publication": publication,
                "route": route,
                "effect_plan": effect_plan,
                "checkpoint_prestate": checkpoint_prestate,
                "context_reason": context_reason,
                "mine_phase_a": mine_phase_a,
                "judgment_payload_sha256": judgment_payload_sha256,
                "judgments": judgments,
            },
            root_path="$.controller_completion",
        )
        intent = _validate_intent(_normalize_json(detached))
    except CompletionError:
        raise
    except Exception:
        _raise("intent_invalid")
    intent_bytes = _canonical_json(intent)
    if len(intent_bytes) > _MAX_INTENT_BYTES:
        _raise("intent_invalid")
    receipts = {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": completion_id,
        "effects": {},
    }
    receipts_bytes = _canonical_json(receipts)
    if len(receipts_bytes) > _MAX_RECEIPTS_BYTES:
        _raise("receipts_invalid")
    project, squad = _validate_roots(project_root, squad_dir)
    transaction_root, transaction_identity = (
        _create_transaction_root(squad, completion_id)
    )
    try:
        _atomic_write(
            transaction_root,
            _INTENT_NAME,
            intent_bytes,
            expected_identity=transaction_identity,
        )
        _atomic_write(
            transaction_root,
            _RECEIPTS_NAME,
            receipts_bytes,
            expected_identity=transaction_identity,
        )
        publication_bytes = _canonical_json(intent["publication"])
        effect_plan_value = list(intent["effect_plan"])
        step = (
            "awaiting_publication"
            if intent["publication"]["kind"] == "external"
            else (
                effect_plan_value[0]
                if effect_plan_value
                else "complete"
            )
        )
        marker = CompletionMarker(
            schema_version=_SCHEMA_VERSION,
            completion_id=completion_id,
            intent_sha256=hashlib.sha256(intent_bytes).hexdigest(),
            publication_binding_sha256=hashlib.sha256(
                publication_bytes
            ).hexdigest(),
            receipts_sha256=hashlib.sha256(receipts_bytes).hexdigest(),
            origin=str(intent["origin"]),
            step=step,
        )
        loaded = load_prepared_controller_completion(
            project,
            squad,
            marker,
        )
        if loaded._transaction_identity != transaction_identity:
            _raise("stage_corrupt")
        return loaded
    except BaseException:
        try:
            _discard_exact_transaction(
                transaction_root.parent,
                completion_id,
                transaction_identity,
                missing_ok=True,
            )
        except CompletionError:
            pass
        raise


def load_prepared_controller_completion(
    project_root: Path,
    squad_dir: Path,
    marker: object,
) -> PreparedControllerCompletion:
    """Load one exact state-authorized completion stage without regeneration."""
    expected_marker = _marker_from(marker)
    _, squad = _validate_roots(project_root, squad_dir)
    outbox = _require_real_directory(
        squad / _OUTBOX_DIRECTORY,
        missing_code="stage_missing",
    )
    transaction_root = _require_real_directory(
        outbox / expected_marker.completion_id,
        missing_code="stage_missing",
    )
    try:
        transaction_before = os.lstat(transaction_root)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_corrupt")
    transaction_identity = _directory_identity(transaction_before)
    intent_bytes = _read_regular(
        transaction_root / _INTENT_NAME,
        maximum=_MAX_INTENT_BYTES,
        code="intent_invalid",
    )
    receipts_bytes = _read_regular(
        transaction_root / _RECEIPTS_NAME,
        maximum=_MAX_RECEIPTS_BYTES,
        code="receipts_invalid",
    )
    if (
        hashlib.sha256(intent_bytes).hexdigest()
        != expected_marker.intent_sha256
    ):
        _raise("intent_mismatch")
    receipts_digest = hashlib.sha256(receipts_bytes).hexdigest()
    if (
        receipts_digest != expected_marker.receipts_sha256
        and expected_marker.step not in _EFFECT_ORDER
    ):
        _raise("receipts_mismatch")
    try:
        intent = _validate_intent(
            _detach_loaded_json(
                _decode_canonical(
                    intent_bytes,
                    code="intent_invalid",
                ),
                root_path="$.controller_completion",
                code="intent_invalid",
            )
        )
    except CompletionError:
        raise
    except Exception:
        _raise("intent_invalid")
    try:
        receipts = _validate_receipts(
            _detach_loaded_json(
                _decode_canonical(
                    receipts_bytes,
                    code="receipts_invalid",
                ),
                root_path="$.controller_completion_receipts",
                code="receipts_invalid",
            ),
            intent=intent,
        )
    except CompletionError as error:
        if error.code != "receipts_invalid":
            _raise("receipts_invalid")
        raise
    except Exception:
        _raise("receipts_invalid")
    publication_binding = hashlib.sha256(
        _canonical_json(intent["publication"])
    ).hexdigest()
    if (
        intent["completion_id"] != expected_marker.completion_id
        or intent["origin"] != expected_marker.origin
        or publication_binding
        != expected_marker.publication_binding_sha256
    ):
        _raise("intent_mismatch")
    plan = list(intent["effect_plan"])
    receipt_count = len(receipts["effects"])
    if expected_marker.step == "awaiting_publication":
        if intent["publication"]["kind"] != "external":
            _raise("intent_mismatch")
        if (
            receipt_count
            or receipts_digest != expected_marker.receipts_sha256
        ):
            _raise("receipts_mismatch")
    elif expected_marker.step == "complete":
        if (
            receipt_count != len(plan)
            or receipts_digest != expected_marker.receipts_sha256
        ):
            _raise("receipts_mismatch")
    elif expected_marker.step in plan:
        step_index = plan.index(expected_marker.step)
        if receipt_count not in {step_index, step_index + 1}:
            _raise("receipts_mismatch")
        if receipt_count == step_index:
            if receipts_digest != expected_marker.receipts_sha256:
                _raise("receipts_mismatch")
        else:
            prior_effects = _clone_json(receipts["effects"])
            prior_effects.pop(expected_marker.step)
            prior_receipts = {
                "schema_version": _SCHEMA_VERSION,
                "completion_id": expected_marker.completion_id,
                "effects": prior_effects,
            }
            if hashlib.sha256(
                _canonical_json(prior_receipts)
            ).hexdigest() != expected_marker.receipts_sha256:
                _raise("receipts_mismatch")
    else:
        _raise("intent_mismatch")
    try:
        transaction_after = os.lstat(transaction_root)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_corrupt")
    if (
        not stat.S_ISDIR(transaction_after.st_mode)
        or stat.S_ISLNK(transaction_after.st_mode)
        or _directory_identity(transaction_after)
        != transaction_identity
    ):
        _raise("stage_corrupt")
    return PreparedControllerCompletion(
        marker=expected_marker,
        intent=_intent_view(intent),
        _transaction_root=transaction_root,
        _transaction_identity=transaction_identity,
        _receipts_json=_canonical_json(receipts, newline=False),
    )


@contextmanager
def reasoning_journal_lock(squad_dir: Path) -> Iterator[None]:
    """Hold the repository-wide rank-5 journal lock for one transaction."""
    if not isinstance(squad_dir, Path):
        _raise("stage_corrupt")
    directory = _require_real_directory(
        squad_dir,
        missing_code="stage_missing",
    )
    try:
        with _store_reasoning_journal_lock(directory):
            yield
    except JournalStoreError as error:
        _raise(
            "stage_io"
            if error.code == "journal_io"
            else "stage_corrupt"
        )


def _read_reasoning_journal(
    journal: Path,
    *,
    code: str,
) -> tuple[bytes, list[dict[str, object]]]:
    """Read and validate a complete JSONL journal without changing its bytes."""
    try:
        return _store_read_reasoning_journal(journal)
    except JournalStoreError:
        _raise(code)


def _durably_replace_file(path: Path, content: bytes) -> None:
    """Replace one regular file from a sibling fsynced temporary file."""
    try:
        _store_durably_replace_file(
            path,
            content,
            directory_sync=_fsync_directory,
        )
    except JournalStoreError as error:
        _raise(
            "stage_io"
            if error.code == "journal_io"
            else "stage_corrupt"
        )


def _journal_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_journal_timestamp(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def prepare_completion_journal_plan(
    intent: CompletionIntent,
    journal: Path,
) -> JournalPlan:
    """Reconstruct immutable journal content only from a sealed intent."""
    if type(intent) is not CompletionIntent or "journal" not in intent.effect_plan:
        _raise("intent_invalid")
    if not isinstance(journal, Path):
        _raise("intent_invalid")
    route = intent.route
    if route.get("kind") != "routed":
        _raise("intent_invalid")
    phase = route.get("from_phase")
    if type(phase) is not str:
        _raise("intent_invalid")
    parent = _require_real_directory(
        journal.parent,
        missing_code="stage_missing",
    )
    if parent != journal.parent.absolute():
        _raise("stage_corrupt")

    raw_entries: list[object] = []
    for judgment in intent.judgments:
        result = judgment.get("echelon_result")
        quarantined = judgment.get("quarantined_state_updates")
        if type(result) is not dict or type(quarantined) is not dict:
            _raise("intent_invalid")
        if quarantined:
            raw_entries.append(
                {
                    "type": "state_contract_warning",
                    "agent": "speckit-echelon-commander",
                    "data": {
                        "dropped_keys": sorted(quarantined),
                        "action": "quarantined",
                        "reason": (
                            "undeclared reporting fields were excluded "
                            "from the state mutation control plane"
                        ),
                    },
                }
            )
        entries = result.get("journal_entries", [])
        if type(entries) is not list:
            _raise("intent_invalid")
        raw_entries.extend(entries)

    try:
        from harness.journal_entry_validator import (
            prepare_completion_journal_contents,
        )

        rows = prepare_completion_journal_contents(
            raw_entries,
            phase_id=phase,
        )
    except CompletionError:
        raise
    except Exception:
        _raise("intent_invalid")
    digests = tuple(
        hashlib.sha256(
            _canonical_json(row, newline=False)
        ).hexdigest()
        for row in rows
    )
    return JournalPlan(
        completion_id=intent.completion_id,
        phase=phase,
        journal=journal,
        content_sha256=digests,
        _rows_json=_canonical_json(rows, newline=False),
    )


def _completion_journal_receipt(
    plan: JournalPlan,
    *,
    entry_ids: list[int],
    timestamp: str | None,
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": plan.completion_id,
        "phase": plan.phase,
        "entry_ids": entry_ids,
        "timestamp": timestamp,
        "content_sha256": list(plan.content_sha256),
    }


def apply_or_verify_completion_journal(
    plan: JournalPlan,
) -> dict[str, object]:
    """Atomically append or exactly adopt one completion-owned row batch."""
    if type(plan) is not JournalPlan:
        _raise("intent_invalid")
    expected_rows = plan.rows
    if len(expected_rows) != len(plan.content_sha256):
        _raise("intent_invalid")

    with reasoning_journal_lock(plan.journal.parent):
        original, existing_rows = _read_reasoning_journal(
            plan.journal,
            code="receipts_invalid",
        )
        candidates: list[dict[str, object]] = []
        candidate_positions: list[int] = []
        for position, row in enumerate(existing_rows):
            stamp = row.get("controller_completion")
            if (
                type(stamp) is dict
                and stamp.get("completion_id") == plan.completion_id
            ):
                candidates.append(row)
                candidate_positions.append(position)

        if candidates:
            if len(candidates) != len(expected_rows):
                _raise("receipts_mismatch")
            if candidate_positions != list(
                range(
                    candidate_positions[0],
                    candidate_positions[0] + len(candidates),
                )
            ):
                _raise("receipts_mismatch")
            by_index: dict[int, dict[str, object]] = {}
            physical_indexes: list[int] = []
            for row in candidates:
                stamp = row.get("controller_completion")
                if (
                    type(stamp) is not dict
                    or frozenset(stamp) != _COMPLETION_STAMP_KEYS
                ):
                    _raise("receipts_mismatch")
                index = stamp.get("entry_index")
                if (
                    type(index) is not int
                    or index < 0
                    or index >= len(expected_rows)
                    or index in by_index
                ):
                    _raise("receipts_mismatch")
                if (
                    stamp.get("content_sha256")
                    != plan.content_sha256[index]
                ):
                    _raise("receipts_mismatch")
                by_index[index] = row
                physical_indexes.append(index)
            if sorted(by_index) != list(range(len(expected_rows))):
                _raise("receipts_mismatch")
            if physical_indexes != list(range(len(expected_rows))):
                _raise("receipts_mismatch")

            entry_ids: list[int] = []
            timestamps: list[str] = []
            for index, expected in enumerate(expected_rows):
                row = by_index[index]
                entry_id = row.get("id")
                timestamp = row.get("timestamp")
                if type(entry_id) is not int or entry_id < 0:
                    _raise("receipts_mismatch")
                if not _valid_journal_timestamp(timestamp):
                    _raise("receipts_mismatch")
                content = dict(row)
                content.pop("id", None)
                content.pop("timestamp", None)
                content.pop("controller_completion", None)
                digest = hashlib.sha256(
                    _canonical_json(content, newline=False)
                ).hexdigest()
                if (
                    content != expected
                    or digest != plan.content_sha256[index]
                    or row.get("phase") != plan.phase
                ):
                    _raise("receipts_mismatch")
                entry_ids.append(entry_id)
                timestamps.append(str(timestamp))
            if (
                len(set(entry_ids)) != len(entry_ids)
                or (
                    entry_ids
                    and entry_ids
                    != list(
                        range(entry_ids[0], entry_ids[0] + len(entry_ids))
                    )
                )
                or len(set(timestamps)) != 1
            ):
                _raise("receipts_mismatch")
            for entry_id in entry_ids:
                if sum(
                    row.get("id") == entry_id
                    and type(row.get("id")) is int
                    for row in existing_rows
                ) != 1:
                    _raise("receipts_mismatch")
            return _completion_journal_receipt(
                plan,
                entry_ids=entry_ids,
                timestamp=timestamps[0] if timestamps else None,
            )

        if not expected_rows:
            return _completion_journal_receipt(
                plan,
                entry_ids=[],
                timestamp=None,
            )

        numeric_ids = [
            row["id"]
            for row in existing_rows
            if type(row.get("id")) is int
        ]
        next_id = max([0, *numeric_ids]) + 1
        timestamp = _journal_timestamp()
        appended: list[bytes] = []
        entry_ids = []
        for index, (content, digest) in enumerate(
            zip(expected_rows, plan.content_sha256, strict=True)
        ):
            row = dict(content)
            row["id"] = next_id + index
            row["timestamp"] = timestamp
            row["controller_completion"] = {
                "completion_id": plan.completion_id,
                "entry_index": index,
                "content_sha256": digest,
            }
            entry_ids.append(next_id + index)
            appended.append(_canonical_json(row))
        separator = b"\n" if original and not original.endswith(b"\n") else b""
        _durably_replace_file(
            plan.journal,
            original + separator + b"".join(appended),
        )
        return _completion_journal_receipt(
            plan,
            entry_ids=entry_ids,
            timestamp=timestamp,
        )
