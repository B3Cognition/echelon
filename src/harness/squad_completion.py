"""Durable, exact authority for controller post-dispatch completion effects."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from echelon.context_builder import (
    CONTEXT_OUTPUT_NAMES as _CONTEXT_OUTPUT_NAMES,
)
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
_MAX_CONTEXT_FILE_BYTES = 16_777_216
_MAX_MINING_DRAWER_IDS = 256
_MAX_MINING_DRAWER_ID_LENGTH = 1_024
_MAX_PHASE_LENGTH = 1_024
_COMPLETION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")
_SHA256_PATTERN = re.compile(r"\A[0-9a-f]{64}\Z")
_GIT_OBJECT_ID_PATTERN = re.compile(
    r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z"
)
_EFFECT_ORDER = ("journal", "timing", "checkpoint", "context", "mining", "retarget")
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
_CONTEXT_STAGE_NAME = "context"
_CONTEXT_FILES_NAME = "files"
_MINING_OUTCOMES = frozenset(
    {
        "written",
        "already_present",
        "unavailable",
        "failed",
        "not_applicable",
    }
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
    _project_root: Path = field(repr=False)
    _squad_dir: Path = field(repr=False)
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


@dataclass(frozen=True)
class CompletionMiningOutcome:
    """One bounded deterministic mining result suitable for a receipt."""

    completion_id: str
    outcome: str
    spec_sha256: str | None
    drawer_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "completion_id": self.completion_id,
            "outcome": self.outcome,
            "spec_sha256": self.spec_sha256,
            "drawer_ids": list(self.drawer_ids),
        }


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
    if origin == "terminal" and effect_plan not in (
        [],
        ["mining"],
        ["mining", "retarget"],
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
    project, squad = _validate_roots(project_root, squad_dir)
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
        _project_root=project,
        _squad_dir=squad,
        _transaction_root=transaction_root,
        _transaction_identity=transaction_identity,
        _receipts_json=_canonical_json(receipts, newline=False),
    )


def discard_unreferenced_controller_completion(
    project_root: Path,
    squad_dir: Path,
    completion_id: str,
) -> bool:
    """Discard one exact, valid stage after its caller proves no authority."""
    completion_id = _validate_completion_id(completion_id)
    project, squad = _validate_roots(project_root, squad_dir)
    outbox = squad / _OUTBOX_DIRECTORY
    try:
        outbox = _require_real_directory(
            outbox,
            missing_code="stage_missing",
        )
        transaction_root = _require_real_directory(
            outbox / completion_id,
            missing_code="stage_missing",
        )
    except CompletionError as exc:
        if exc.code == "stage_missing":
            return False
        raise
    metadata = os.lstat(transaction_root)
    identity = _directory_identity(metadata)
    intent_content = _read_regular(
        transaction_root / _INTENT_NAME,
        maximum=_MAX_INTENT_BYTES,
        code="intent_invalid",
    )
    receipts_content = _read_regular(
        transaction_root / _RECEIPTS_NAME,
        maximum=_MAX_RECEIPTS_BYTES,
        code="receipts_invalid",
    )
    intent = _validate_intent(
        _detach_loaded_json(
            _decode_canonical(
                intent_content,
                code="intent_invalid",
            ),
            root_path="$.controller_completion",
            code="intent_invalid",
        )
    )
    receipts = _validate_receipts(
        _detach_loaded_json(
            _decode_canonical(
                receipts_content,
                code="receipts_invalid",
            ),
            root_path="$.controller_completion_receipts",
            code="receipts_invalid",
        ),
        intent=intent,
    )
    if (
        intent["completion_id"] != completion_id
        or receipts["completion_id"] != completion_id
    ):
        _raise("intent_mismatch")
    publication = intent["publication"]
    if publication["kind"] == "external":
        from harness.squad_publication import (
            PublicationError,
            load_prepared_publication,
        )

        try:
            prepared_publication = load_prepared_publication(
                project,
                squad,
                publication["marker"],
            )
            prepared_publication.discard()
        except PublicationError as error:
            if error.code != "stage_missing":
                _raise(
                    "stage_io"
                    if error.code == "publish_io"
                    else "stage_corrupt"
                )
    _discard_exact_transaction(
        outbox,
        completion_id,
        identity,
        missing_ok=True,
    )
    return True


@contextmanager
def reasoning_journal_lock(squad_dir: Path) -> Iterator[None]:
    """Hold the repository-wide rank-6 journal lock for one transaction."""
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


def _atomic_exchange_files(
    directory_fd: int,
    first_name: str,
    second_name: str,
) -> None:
    """Atomically exchange two names within one pinned directory."""
    import ctypes
    import ctypes.util
    import sys

    library_name = ctypes.util.find_library("c")
    if library_name is None:
        _raise("stage_io")
    libc = ctypes.CDLL(library_name, use_errno=True)
    first = os.fsencode(first_name)
    second = os.fsencode(second_name)
    if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
        function = libc.renameatx_np
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(
            directory_fd,
            first,
            directory_fd,
            second,
            0x00000002,  # RENAME_SWAP
        )
    elif hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        result = function(
            directory_fd,
            first,
            directory_fd,
            second,
            0x00000002,  # RENAME_EXCHANGE
        )
    else:
        _raise("stage_io")
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
        )


def _durably_replace_file(
    path: Path,
    content: bytes,
    *,
    expected_preimage: Mapping[str, object] | None = None,
    postimage: Mapping[str, object] | None = None,
    mismatch_code: str = "stage_corrupt",
) -> None:
    """Replace a file durably, optionally with a pinned final preimage CAS."""
    if expected_preimage is None and postimage is None:
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
        return
    if (
        expected_preimage is None
        or postimage is None
        or mismatch_code not in _ERROR_CODES
        or path.name in {"", ".", ".."}
        or path.parent / path.name != path
    ):
        _raise("stage_corrupt")
    expected = dict(expected_preimage)
    expected_postimage = dict(postimage)
    actual_postimage = {
        "kind": "file",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }
    if expected_postimage != actual_postimage:
        _raise("stage_corrupt")

    parent = _require_real_directory(
        path.parent,
        missing_code="stage_missing",
    )
    try:
        parent_before = os.lstat(parent)
    except OSError:
        _raise("stage_io")
    parent_fd = _open_directory_fd(
        parent,
        missing_code="stage_missing",
    )
    temporary_name = f".{path.name}-{secrets.token_hex(12)}.tmp"
    temporary_fd: int | None = None
    preserve_temporary = False

    def entry_token_at(name: str) -> tuple[object, ...]:
        """Return a bounded identity/version token without reading contents."""
        try:
            metadata = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return ("missing",)
        except OSError:
            _raise("stage_io")
        return (
            "entry",
            stat.S_IFMT(metadata.st_mode),
            metadata.st_mode,
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_nlink,
            metadata.st_size,
            metadata.st_mtime_ns,
            getattr(metadata, "st_flags", None),
            getattr(metadata, "st_gen", None),
        )

    def descriptor_at(name: str) -> dict[str, object]:
        try:
            metadata = os.stat(
                name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return {"kind": "missing"}
        except OSError:
            _raise("stage_io")
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
            metadata.st_mode
        ):
            _raise(mismatch_code)
        allowed_sizes = {
            value.get("size_bytes")
            for value in (expected, expected_postimage)
            if value.get("kind") == "file"
        }
        if metadata.st_size not in allowed_sizes:
            _raise(mismatch_code)
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
        except OSError:
            _raise(mismatch_code)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size)
            ):
                _raise(mismatch_code)
            remaining = opened.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(
                    descriptor,
                    min(1_048_576, remaining),
                )
                if not chunk:
                    _raise(mismatch_code)
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ):
                _raise(mismatch_code)
            try:
                current_entry = os.stat(
                    name,
                    dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except OSError:
                _raise(mismatch_code)
            if (
                current_entry.st_dev,
                current_entry.st_ino,
                current_entry.st_size,
            ) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
            ):
                _raise(mismatch_code)
            observed = b"".join(chunks)
            return {
                "kind": "file",
                "sha256": hashlib.sha256(observed).hexdigest(),
                "size_bytes": len(observed),
            }
        except CompletionError:
            raise
        except OSError:
            _raise("stage_io")
        finally:
            os.close(descriptor)

    try:
        opened_parent = os.fstat(parent_fd)
        if _directory_identity(opened_parent) != _directory_identity(
            parent_before
        ):
            _raise("stage_corrupt")
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=parent_fd,
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
        postimage_token = entry_token_at(temporary_name)

        current = descriptor_at(path.name)
        if current != expected_postimage:
            if current != expected:
                _raise(mismatch_code)
            if expected.get("kind") == "missing":
                try:
                    os.link(
                        temporary_name,
                        path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    if descriptor_at(path.name) != expected_postimage:
                        _raise(mismatch_code)
            else:
                captured_expected_token = entry_token_at(path.name)
                if (
                    descriptor_at(path.name) != expected
                    or entry_token_at(path.name)
                    != captured_expected_token
                ):
                    _raise(mismatch_code)
                try:
                    _atomic_exchange_files(
                        parent_fd,
                        temporary_name,
                        path.name,
                    )
                except FileNotFoundError:
                    _raise(mismatch_code)
                captured_token = entry_token_at(temporary_name)
                try:
                    captured_descriptor = descriptor_at(
                        temporary_name
                    )
                except CompletionError:
                    captured_descriptor = None
                if (
                    captured_token != captured_expected_token
                    or captured_descriptor
                    not in (expected, expected_postimage)
                ):
                    candidate_token = captured_token
                    target_expected_token = postimage_token
                    for _ in range(8):
                        if (
                            entry_token_at(path.name)
                            != target_expected_token
                        ):
                            _raise(mismatch_code)
                        try:
                            _atomic_exchange_files(
                                parent_fd,
                                temporary_name,
                                path.name,
                            )
                        except OSError:
                            _raise("stage_io")
                        os.fsync(parent_fd)
                        displaced_token = entry_token_at(
                            temporary_name
                        )
                        if displaced_token == target_expected_token:
                            if (
                                entry_token_at(path.name)
                                != candidate_token
                            ):
                                _raise(mismatch_code)
                            _raise(mismatch_code)
                        target_expected_token = candidate_token
                        candidate_token = displaced_token
                    preserve_temporary = True
                    _raise(mismatch_code)
                try:
                    installed = descriptor_at(path.name)
                except CompletionError:
                    installed = None
                if installed != expected_postimage:
                    _raise(mismatch_code)
            os.fsync(parent_fd)
        try:
            parent_after = os.lstat(parent)
        except OSError:
            _raise("stage_io")
        if _directory_identity(parent_after) != _directory_identity(
            opened_parent
        ):
            _raise("stage_corrupt")
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
        if not preserve_temporary:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except OSError:
                pass
        os.close(parent_fd)


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
                    "agent": "echelon-commander",
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


def _completion_timing_effect_id(
    completion_id: str,
    kind: str,
    phase: str,
) -> str:
    return f"{completion_id}:timing:{kind}:{phase}"


def _completion_timing_events(
    store: object,
    *,
    require_durable: bool = False,
) -> tuple[object, ...]:
    try:
        if require_durable:
            events, diagnostics = store.read_durable_phase_timings()
        else:
            events, diagnostics = store.read_phase_timings()
    except (AttributeError, OSError, RuntimeError, ValueError):
        _raise("receipts_invalid")
    if diagnostics:
        _raise("receipts_invalid")
    return tuple(events)


def _completion_timing_event_sha256(event: object) -> str:
    try:
        record = event.to_json_dict()
    except AttributeError:
        _raise("receipts_invalid")
    return hashlib.sha256(
        _canonical_json(record, newline=False)
    ).hexdigest()


def _completion_timing_receipt(
    completion_id: str,
    events: list[object],
) -> dict[str, object]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": completion_id,
        "events": [
            {
                "effect_id": event.effect_id,
                "event_sha256": _completion_timing_event_sha256(event),
            }
            for event in events
        ],
    }


def _validate_completion_timing_receipt(
    receipt: object,
    *,
    completion_id: str,
    store: object,
    allowed_sequences: tuple[tuple[str, ...], ...],
    effect_semantics: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    record = _validate_exact_dict(
        receipt,
        frozenset({"schema_version", "completion_id", "events"}),
        code="receipts_mismatch",
    )
    event_receipts = record["events"]
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != _SCHEMA_VERSION
        or type(record["completion_id"]) is not str
        or record["completion_id"] != completion_id
        or type(event_receipts) is not list
    ):
        _raise("receipts_mismatch")
    effect_ids: list[str] = []
    expected_digests: dict[str, str] = {}
    for event_receipt in event_receipts:
        item = _validate_exact_dict(
            event_receipt,
            frozenset({"effect_id", "event_sha256"}),
            code="receipts_mismatch",
        )
        effect_id = item["effect_id"]
        digest = item["event_sha256"]
        if (
            type(effect_id) is not str
            or type(digest) is not str
            or _SHA256_PATTERN.fullmatch(digest) is None
            or effect_id in expected_digests
        ):
            _raise("receipts_mismatch")
        effect_ids.append(effect_id)
        expected_digests[effect_id] = digest
    if tuple(effect_ids) not in allowed_sequences:
        _raise("receipts_mismatch")
    events = _completion_timing_events(
        store,
        require_durable=True,
    )
    completion_events = [
        event
        for event in events
        if getattr(event, "completion_id", None) == completion_id
    ]
    if len(completion_events) != len(effect_ids):
        _raise("receipts_mismatch")
    by_effect: dict[str, object] = {}
    for event in completion_events:
        effect_id = getattr(event, "effect_id", None)
        if (
            type(effect_id) is not str
            or effect_id in by_effect
            or effect_id not in expected_digests
        ):
            _raise("receipts_mismatch")
        by_effect[effect_id] = event
    for effect_id in effect_ids:
        event = by_effect.get(effect_id)
        semantics = effect_semantics.get(effect_id)
        trace_id = getattr(store, "trace_id", None)
        try:
            from echelon.telemetry.model import PhaseTimingEvent

            PhaseTimingEvent.from_json_dict(event.to_json_dict())
        except (AttributeError, ValueError):
            _raise("receipts_mismatch")
        if (
            event is None
            or semantics is None
            or getattr(event, "completion_id", None) != completion_id
            or getattr(event, "phase", None) != semantics["phase"]
            or getattr(event, "event", None) != semantics["event"]
            or getattr(event, "budget_seconds", None)
            != semantics["budget_seconds"]
            or (
                type(trace_id) is str
                and getattr(event, "trace_id", None) != trace_id
            )
            or (
                semantics["event"] == "started"
                and (
                    getattr(event, "elapsed_seconds", None) is not None
                    or getattr(event, "over_budget", None) is not None
                )
            )
            or (
                semantics["event"] == "finished"
                and (
                    type(getattr(event, "elapsed_seconds", None))
                    is not float
                    or type(getattr(event, "over_budget", None))
                    is not bool
                )
            )
            or _completion_timing_event_sha256(event)
            != expected_digests[effect_id]
        ):
            _raise("receipts_mismatch")
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": completion_id,
        "events": [
            {
                "effect_id": effect_id,
                "event_sha256": expected_digests[effect_id],
            }
            for effect_id in effect_ids
        ],
    }


def apply_or_verify_completion_timing(
    intent: CompletionIntent,
    store: object,
    *,
    close_phase: str | None = None,
    close_budget_seconds: float | None = None,
    open_phase: str | None = None,
    open_budget_seconds: float | None = None,
    expected_receipt: object | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Append or adopt one completion-tagged timing transition."""
    if (
        type(intent) is not CompletionIntent
        or "timing" not in intent.effect_plan
        or intent.route.get("kind") != "routed"
        or (fault_hook is not None and not callable(fault_hook))
    ):
        _raise("intent_invalid")
    close = (
        _validate_bounded_string(
            close_phase,
            maximum=_MAX_PHASE_LENGTH,
        )
        if close_phase is not None
        else None
    )
    opened = (
        _validate_bounded_string(
            open_phase,
            maximum=_MAX_PHASE_LENGTH,
        )
        if open_phase is not None
        else None
    )
    if close is None and opened is None:
        _raise("intent_invalid")

    def budget(value: object, *, required: bool) -> float | None:
        if value is None and not required:
            return None
        if (
            type(value) not in (int, float)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            _raise("intent_invalid")
        return float(value)

    close_budget = budget(
        close_budget_seconds,
        required=close is not None,
    )
    open_budget = budget(
        open_budget_seconds,
        required=opened is not None,
    )
    completion_id = intent.completion_id
    close_id = (
        _completion_timing_effect_id(
            completion_id,
            "close",
            close,
        )
        if close is not None
        else None
    )
    open_id = (
        _completion_timing_effect_id(
            completion_id,
            "open",
            opened,
        )
        if opened is not None
        else None
    )
    base_ids = tuple(
        effect_id
        for effect_id in (close_id, open_id)
        if effect_id is not None
    )
    allowed_sequences = (base_ids,)
    effect_semantics: dict[str, dict[str, object]] = {}
    if close_id is not None:
        effect_semantics[close_id] = {
            "phase": close,
            "event": "finished",
            "budget_seconds": close_budget,
        }
    if open_id is not None:
        effect_semantics[open_id] = {
            "phase": opened,
            "event": "started",
            "budget_seconds": open_budget,
        }
    if expected_receipt is not None:
        return _validate_completion_timing_receipt(
            expected_receipt,
            completion_id=completion_id,
            store=store,
            allowed_sequences=allowed_sequences,
            effect_semantics=effect_semantics,
        )

    from echelon.telemetry.phase_timing import (
        record_phase_finish,
        record_phase_start,
    )

    allowed_ids = {
        effect_id
        for effect_id in (close_id, open_id)
        if effect_id is not None
    }
    if any(
        getattr(event, "effect_id", None) not in allowed_ids
        for event in _completion_timing_events(store)
        if getattr(event, "completion_id", None) == completion_id
    ):
        _raise("receipts_mismatch")

    def call_timing(function: Callable[..., object], **kwargs: object) -> object:
        try:
            return function(store, **kwargs)
        except (AttributeError, OSError, ValueError):
            _raise("receipts_mismatch")

    if close is not None and close_id is not None:
        call_timing(
            record_phase_finish,
            phase=close,
            completion_id=completion_id,
            effect_id=close_id,
            expected_budget_seconds=close_budget,
        )
        if fault_hook is not None:
            fault_hook("after_close")

    if opened is not None and open_id is not None:
        assert open_budget is not None
        call_timing(
            record_phase_start,
            phase=opened,
            budget_seconds=open_budget,
            completion_id=completion_id,
            effect_id=open_id,
        )
        if fault_hook is not None:
            fault_hook("after_open")

    events = _completion_timing_events(store)
    by_effect = {
        getattr(event, "effect_id", None): event
        for event in events
        if getattr(event, "completion_id", None) == completion_id
    }
    ordered_ids = base_ids
    try:
        receipt_events = [by_effect[effect_id] for effect_id in ordered_ids]
    except KeyError:
        _raise("receipts_mismatch")
    receipt = _completion_timing_receipt(
        completion_id,
        receipt_events,
    )
    return _validate_completion_timing_receipt(
        receipt,
        completion_id=completion_id,
        store=store,
        allowed_sequences=allowed_sequences,
        effect_semantics=effect_semantics,
    )


def create_or_recover_completion_checkpoint(
    intent: CompletionIntent,
    *,
    project_root: Path,
    spec_dir: Path | None,
    run_id: str,
    spec_id: str,
    additional_spec_dirs: tuple[Path, ...] = (),
    additional_owned_paths: tuple[Path, ...] = (),
    expected_receipt: object | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Apply a checkpoint using only identity sealed by the intent."""

    if (
        type(intent) is not CompletionIntent
        or "checkpoint" not in intent.effect_plan
    ):
        _raise("intent_invalid")
    route = intent.route
    if route.get("kind") != "routed":
        _raise("intent_invalid")
    from harness.phase_checkpoints import (
        PhaseCheckpointError,
        create_or_recover_completion_checkpoint as apply_checkpoint,
    )

    try:
        return apply_checkpoint(
            project_root=project_root,
            spec_dir=spec_dir,
            phase=route["from_phase"],
            next_phase=route["to_phase"],
            run_id=run_id,
            spec_id=spec_id,
            completion_id=intent.completion_id,
            checkpoint_prestate=intent.checkpoint_prestate,
            additional_spec_dirs=additional_spec_dirs,
            additional_owned_paths=additional_owned_paths,
            expected_receipt=expected_receipt,
            fault_hook=fault_hook,
        )
    except PhaseCheckpointError:
        _raise("receipts_mismatch")


def _verify_prepared_completion_identity(
    prepared: PreparedControllerCompletion,
) -> None:
    if type(prepared) is not PreparedControllerCompletion:
        _raise("intent_invalid")
    root = prepared._transaction_root
    if (
        root.name != prepared.marker.completion_id
        or root.parent.name != _OUTBOX_DIRECTORY
        or root.parent.parent != prepared._squad_dir
    ):
        _raise("stage_corrupt")
    try:
        metadata = os.lstat(root)
    except FileNotFoundError:
        _raise("stage_missing")
    except OSError:
        _raise("stage_io")
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or _directory_identity(metadata)
        != prepared._transaction_identity
    ):
        _raise("stage_corrupt")


def _require_prepared_project_root(
    prepared: PreparedControllerCompletion,
    project_root: Path,
) -> Path:
    if not isinstance(project_root, Path):
        _raise("intent_invalid")
    project = _require_real_directory(
        project_root,
        missing_code="stage_missing",
    )
    if project != prepared._project_root:
        _raise("intent_invalid")
    return project


def _current_completion_effect_receipt(
    prepared: PreparedControllerCompletion,
    effect: str,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Read a marker-bound prefix or its one exact current receipt."""
    _verify_prepared_completion_identity(prepared)
    plan = prepared.intent.effect_plan
    if (
        effect not in plan
        or prepared.marker.step != effect
        or plan.index(effect) >= len(plan)
    ):
        _raise("intent_invalid")
    content = _read_regular(
        prepared._transaction_root / _RECEIPTS_NAME,
        maximum=_MAX_RECEIPTS_BYTES,
        code="receipts_invalid",
    )
    try:
        receipts = _validate_receipts(
            _detach_loaded_json(
                _decode_canonical(
                    content,
                    code="receipts_invalid",
                ),
                root_path="$.controller_completion_receipts",
                code="receipts_invalid",
            ),
            intent=prepared.intent.to_dict(),
        )
    except CompletionError:
        raise
    except Exception:
        _raise("receipts_invalid")
    index = plan.index(effect)
    effects = receipts["effects"]
    if len(effects) not in {index, index + 1}:
        _raise("receipts_mismatch")
    prior_effects = {
        name: effects[name]
        for name in plan[:index]
    }
    prior = {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": prepared.intent.completion_id,
        "effects": prior_effects,
    }
    if hashlib.sha256(_canonical_json(prior)).hexdigest() != (
        prepared.marker.receipts_sha256
    ):
        _raise("receipts_mismatch")
    receipt = effects.get(effect)
    if len(effects) == index and receipt is not None:
        _raise("receipts_mismatch")
    if len(effects) == index + 1 and type(receipt) is not dict:
        _raise("receipts_mismatch")
    return receipts, receipt


def _persist_current_completion_receipt(
    prepared: PreparedControllerCompletion,
    effect: str,
    receipt: dict[str, object],
) -> dict[str, object]:
    receipts, existing = _current_completion_effect_receipt(
        prepared,
        effect,
    )
    if existing is not None:
        if _canonical_json(existing, newline=False) != _canonical_json(
            receipt,
            newline=False,
        ):
            _raise("receipts_mismatch")
        return existing
    effects = dict(receipts["effects"])
    effects[effect] = _clone_json(receipt)
    updated = {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": prepared.intent.completion_id,
        "effects": effects,
    }
    content = _canonical_json(updated)
    if len(content) > _MAX_RECEIPTS_BYTES:
        _raise("receipts_invalid")
    prior_content = _canonical_json(receipts)
    _durably_replace_file(
        prepared._transaction_root / _RECEIPTS_NAME,
        content,
        expected_preimage={
            "kind": "file",
            "sha256": hashlib.sha256(prior_content).hexdigest(),
            "size_bytes": len(prior_content),
        },
        postimage={
            "kind": "file",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        },
        mismatch_code="receipts_mismatch",
    )
    observed = _read_regular(
        prepared._transaction_root / _RECEIPTS_NAME,
        maximum=_MAX_RECEIPTS_BYTES,
        code="receipts_invalid",
    )
    if observed != content:
        _raise("stage_io")
    _, persisted = _current_completion_effect_receipt(
        prepared,
        effect,
    )
    if persisted is None:
        _raise("receipts_mismatch")
    return persisted


def persist_completion_effect_receipt(
    prepared: PreparedControllerCompletion,
    effect: str,
    receipt: dict[str, object],
) -> dict[str, object]:
    """Persist the exact receipt for the marker's current effect."""
    return _persist_current_completion_receipt(
        prepared,
        effect,
        receipt,
    )


def _context_stage_paths(
    prepared: PreparedControllerCompletion,
) -> tuple[Path, Path]:
    stage = prepared._transaction_root / _CONTEXT_STAGE_NAME
    return stage, stage / _CONTEXT_FILES_NAME


def _remove_unreceipted_context_stage(
    prepared: PreparedControllerCompletion,
) -> None:
    stage, _ = _context_stage_paths(prepared)
    try:
        metadata = os.lstat(stage)
    except FileNotFoundError:
        return
    except OSError:
        _raise("stage_io")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
        metadata.st_mode
    ):
        _raise("stage_corrupt")
    stage_fd = _open_directory_fd(
        stage,
        missing_code="stage_missing",
    )
    try:
        opened = os.fstat(stage_fd)
        identity = _directory_identity(opened)
        if identity != _directory_identity(metadata):
            _raise("stage_corrupt")
        _remove_directory_contents_fd(stage_fd)
        current = os.lstat(stage)
        if _directory_identity(current) != identity:
            _raise("stage_corrupt")
        os.rmdir(stage)
        _fsync_directory(prepared._transaction_root)
    except CompletionError:
        raise
    except (FileNotFoundError, OSError):
        _raise("stage_io")
    finally:
        os.close(stage_fd)


def _create_context_stage(
    prepared: PreparedControllerCompletion,
) -> Path:
    stage, files = _context_stage_paths(prepared)
    try:
        os.mkdir(stage, 0o700)
        os.mkdir(files, 0o700)
        _fsync_directory(files)
        _fsync_directory(stage)
        _fsync_directory(prepared._transaction_root)
    except FileExistsError:
        _raise("stage_corrupt")
    except OSError:
        _raise("stage_io")
    return files


def _read_context_stage(
    prepared: PreparedControllerCompletion,
) -> dict[str, bytes]:
    stage, files = _context_stage_paths(prepared)
    _require_real_directory(stage, missing_code="stage_missing")
    _require_real_directory(files, missing_code="stage_missing")
    try:
        if sorted(os.listdir(stage)) != [_CONTEXT_FILES_NAME]:
            _raise("stage_corrupt")
        names = tuple(os.listdir(files))
    except CompletionError:
        raise
    except OSError:
        _raise("stage_io")
    if any(name not in names for name in _CONTEXT_OUTPUT_NAMES):
        _raise("stage_missing")
    if len(names) != len(_CONTEXT_OUTPUT_NAMES):
        _raise("stage_corrupt")
    result: dict[str, bytes] = {}
    for name in _CONTEXT_OUTPUT_NAMES:
        result[name] = _read_regular(
            files / name,
            maximum=_MAX_CONTEXT_FILE_BYTES,
            code="stage_corrupt",
        )
    return result


def _sync_context_stage(
    prepared: PreparedControllerCompletion,
) -> dict[str, bytes]:
    content = _read_context_stage(prepared)
    _, files = _context_stage_paths(prepared)
    for name in _CONTEXT_OUTPUT_NAMES:
        try:
            descriptor = os.open(
                files / name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            _raise("stage_io")
    _fsync_directory(files)
    _fsync_directory(files.parent)
    _fsync_directory(prepared._transaction_root)
    return content


def _context_file_descriptor(path: Path) -> dict[str, object]:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return {"kind": "missing"}
    except OSError:
        _raise("stage_io")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(
        metadata.st_mode
    ):
        _raise("receipts_mismatch")
    content = _read_regular(
        path,
        maximum=_MAX_CONTEXT_FILE_BYTES,
        code="receipts_mismatch",
    )
    return {
        "kind": "file",
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _capture_context_preimages(
    prepared: PreparedControllerCompletion,
) -> dict[str, dict[str, object]]:
    target = prepared._squad_dir / "context"
    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        return {
            name: {"kind": "missing"}
            for name in _CONTEXT_OUTPUT_NAMES
        }
    except OSError:
        _raise("stage_io")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
        metadata.st_mode
    ):
        _raise("receipts_mismatch")
    _require_real_directory(target, missing_code="stage_missing")
    return {
        name: _context_file_descriptor(target / name)
        for name in _CONTEXT_OUTPUT_NAMES
    }


def _validate_context_preimage(value: object) -> dict[str, object]:
    if type(value) is not dict:
        _raise("receipts_mismatch")
    kind = dict.get(value, "kind")
    if kind == "missing":
        _validate_exact_dict(
            value,
            frozenset({"kind"}),
            code="receipts_mismatch",
        )
        return {"kind": "missing"}
    _validate_exact_dict(
        value,
        frozenset({"kind", "sha256", "size_bytes"}),
        code="receipts_mismatch",
    )
    size = value["size_bytes"]
    if (
        kind != "file"
        or type(size) is not int
        or size < 0
        or size > _MAX_CONTEXT_FILE_BYTES
    ):
        _raise("receipts_mismatch")
    digest = value["sha256"]
    if type(digest) is not str or _SHA256_PATTERN.fullmatch(digest) is None:
        _raise("receipts_mismatch")
    return {
        "kind": "file",
        "sha256": digest,
        "size_bytes": size,
    }


def _validate_completion_context_receipt(
    receipt: object,
    *,
    prepared: PreparedControllerCompletion,
    staged: Mapping[str, bytes],
) -> dict[str, object]:
    record = _validate_exact_dict(
        receipt,
        frozenset(
            {
                "schema_version",
                "completion_id",
                "source_state_revision",
                "prepared_at",
                "files",
            }
        ),
        code="receipts_mismatch",
    )
    revision = record["source_state_revision"]
    prepared_at = record["prepared_at"]
    files = record["files"]
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != _SCHEMA_VERSION
        or record["completion_id"] != prepared.intent.completion_id
        or type(revision) is not int
        or revision < 0
        or revision > (1 << 63) - 1
        or not _valid_journal_timestamp(prepared_at)
        or type(files) is not list
        or len(files) != len(_CONTEXT_OUTPUT_NAMES)
    ):
        _raise("receipts_mismatch")
    validated_files: list[dict[str, object]] = []
    for expected_name, value in zip(
        _CONTEXT_OUTPUT_NAMES,
        files,
        strict=True,
    ):
        item = _validate_exact_dict(
            value,
            frozenset({"name", "preimage", "sha256", "size_bytes"}),
            code="receipts_mismatch",
        )
        name = item["name"]
        digest = item["sha256"]
        size = item["size_bytes"]
        if (
            type(name) is not str
            or name != expected_name
            or type(digest) is not str
            or _SHA256_PATTERN.fullmatch(digest) is None
            or type(size) is not int
            or size < 0
            or size > _MAX_CONTEXT_FILE_BYTES
        ):
            _raise("receipts_mismatch")
        if (
            name not in staged
            or len(staged[name]) != size
            or hashlib.sha256(staged[name]).hexdigest() != digest
        ):
            _raise("stage_corrupt")
        validated_files.append(
            {
                "name": name,
                "preimage": _validate_context_preimage(
                    item["preimage"]
                ),
                "sha256": digest,
                "size_bytes": size,
            }
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "completion_id": prepared.intent.completion_id,
        "source_state_revision": revision,
        "prepared_at": prepared_at,
        "files": validated_files,
    }


def prepare_or_load_completion_context(
    prepared: PreparedControllerCompletion,
    *,
    project_root: Path,
    source_state_revision: int,
    prepared_at: str | None = None,
    user_request: str = "",
    drawers: object = (),
    generator: Callable[..., object] | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Freeze the fixed context output set and persist its one-ahead receipt."""
    _verify_prepared_completion_identity(prepared)
    _require_prepared_project_root(prepared, project_root)
    if (
        "context" not in prepared.intent.effect_plan
        or prepared.marker.step != "context"
        or (fault_hook is not None and not callable(fault_hook))
    ):
        _raise("intent_invalid")
    _, existing = _current_completion_effect_receipt(
        prepared,
        "context",
    )
    if existing is not None:
        staged = _read_context_stage(prepared)
        return _validate_completion_context_receipt(
            existing,
            prepared=prepared,
            staged=staged,
        )
    if (
        type(source_state_revision) is not int
        or source_state_revision < 0
        or source_state_revision > (1 << 63) - 1
        or type(user_request) is not str
    ):
        _raise("intent_invalid")
    timestamp = _journal_timestamp() if prepared_at is None else prepared_at
    if not _valid_journal_timestamp(timestamp):
        _raise("intent_invalid")
    if generator is None:
        from echelon.context_builder import build_run_context

        generator = build_run_context
    if not callable(generator):
        _raise("intent_invalid")

    preimages = _capture_context_preimages(prepared)
    _remove_unreceipted_context_stage(prepared)
    output_dir = _create_context_stage(prepared)
    try:
        generator(
            prepared._project_root,
            prepared._squad_dir,
            user_request=user_request,
            drawers=drawers,
            output_dir=output_dir,
        )
        staged = _sync_context_stage(prepared)
        if _capture_context_preimages(prepared) != preimages:
            _raise("receipts_mismatch")
        receipt = {
            "schema_version": _SCHEMA_VERSION,
            "completion_id": prepared.intent.completion_id,
            "source_state_revision": source_state_revision,
            "prepared_at": timestamp,
            "files": [
                {
                    "name": name,
                    "preimage": preimages[name],
                    "sha256": hashlib.sha256(
                        staged[name]
                    ).hexdigest(),
                    "size_bytes": len(staged[name]),
                }
                for name in _CONTEXT_OUTPUT_NAMES
            ],
        }
        validated = _validate_completion_context_receipt(
            receipt,
            prepared=prepared,
            staged=staged,
        )
        if fault_hook is not None:
            fault_hook("after_generation")
        return _persist_current_completion_receipt(
            prepared,
            "context",
            validated,
        )
    except BaseException:
        current = None
        try:
            _, current = _current_completion_effect_receipt(
                prepared,
                "context",
            )
        except CompletionError:
            pass
        if current is None:
            try:
                _remove_unreceipted_context_stage(prepared)
            except CompletionError:
                pass
        raise


def install_or_verify_completion_context(
    prepared: PreparedControllerCompletion,
    *,
    expected_receipt: object | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Install or exactly verify the immutable fixed context output set."""
    _verify_prepared_completion_identity(prepared)
    if (
        "context" not in prepared.intent.effect_plan
        or prepared.marker.step != "context"
        or (fault_hook is not None and not callable(fault_hook))
    ):
        _raise("intent_invalid")
    _, persisted = _current_completion_effect_receipt(
        prepared,
        "context",
    )
    if persisted is None:
        _raise("receipts_invalid")
    staged = _read_context_stage(prepared)
    receipt = _validate_completion_context_receipt(
        persisted,
        prepared=prepared,
        staged=staged,
    )
    if (
        expected_receipt is not None
        and _canonical_json(expected_receipt, newline=False)
        != _canonical_json(receipt, newline=False)
    ):
        _raise("receipts_mismatch")

    target = prepared._squad_dir / "context"
    expected_by_name = {
        item["name"]: item
        for item in receipt["files"]
    }
    current_by_name = _capture_context_preimages(prepared)
    states: dict[str, str] = {}
    for name in _CONTEXT_OUTPUT_NAMES:
        current = current_by_name[name]
        item = expected_by_name[name]
        postimage = {
            "kind": "file",
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        if current == postimage:
            states[name] = "postimage"
        elif current == item["preimage"]:
            states[name] = "preimage"
        else:
            _raise("receipts_mismatch")

    try:
        metadata = os.lstat(target)
    except FileNotFoundError:
        try:
            os.mkdir(target, 0o755)
            _fsync_directory(target)
            _fsync_directory(prepared._squad_dir)
        except FileExistsError:
            _raise("receipts_mismatch")
        except OSError:
            _raise("stage_io")
    except OSError:
        _raise("stage_io")
    else:
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(
            metadata.st_mode
        ):
            _raise("receipts_mismatch")
        _require_real_directory(target, missing_code="stage_missing")

    for name in _CONTEXT_OUTPUT_NAMES:
        if states[name] == "postimage":
            continue
        item = expected_by_name[name]
        path = target / name
        current = _context_file_descriptor(path)
        postimage = {
            "kind": "file",
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        if current == postimage:
            continue
        if current != item["preimage"]:
            _raise("receipts_mismatch")
        _durably_replace_file(
            path,
            staged[name],
            expected_preimage=item["preimage"],
            postimage=postimage,
            mismatch_code="receipts_mismatch",
        )
        if _context_file_descriptor(path) != postimage:
            _raise("stage_io")
        if fault_hook is not None:
            fault_hook(f"after_install:{name}")

    for name in _CONTEXT_OUTPUT_NAMES:
        item = expected_by_name[name]
        if _context_file_descriptor(target / name) != {
            "kind": "file",
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }:
            _raise("receipts_mismatch")
    return receipt


def _validate_mining_drawer_ids(
    value: object,
) -> tuple[str, ...]:
    if (
        type(value) is not list
        or len(value) > _MAX_MINING_DRAWER_IDS
    ):
        _raise("receipts_mismatch")
    result: list[str] = []
    total_length = 0
    for drawer_id in value:
        if (
            type(drawer_id) is not str
            or not drawer_id.startswith("drawer_")
            or len(drawer_id) > _MAX_MINING_DRAWER_ID_LENGTH
            or re.fullmatch(r".+_[0-9a-f]{64}", drawer_id) is None
            or any(
                character in drawer_id
                for character in ("/", "\\", "\x00", "\n", "\r")
            )
        ):
            _raise("receipts_mismatch")
        total_length += len(drawer_id)
        result.append(drawer_id)
    if (
        result != sorted(set(result))
        or total_length > 262_144
    ):
        _raise("receipts_mismatch")
    return tuple(result)


def _validate_completion_mining_receipt(
    receipt: object,
    *,
    prepared: PreparedControllerCompletion,
) -> CompletionMiningOutcome:
    record = _validate_exact_dict(
        receipt,
        frozenset(
            {
                "schema_version",
                "completion_id",
                "outcome",
                "spec_sha256",
                "drawer_ids",
            }
        ),
        code="receipts_mismatch",
    )
    outcome = record["outcome"]
    spec_sha256 = record["spec_sha256"]
    drawer_ids = _validate_mining_drawer_ids(record["drawer_ids"])
    if (
        type(record["schema_version"]) is not int
        or record["schema_version"] != _SCHEMA_VERSION
        or record["completion_id"] != prepared.intent.completion_id
        or type(outcome) is not str
        or outcome not in _MINING_OUTCOMES
    ):
        _raise("receipts_mismatch")
    if outcome == "not_applicable":
        if spec_sha256 is not None or drawer_ids:
            _raise("receipts_mismatch")
    else:
        if (
            type(spec_sha256) is not str
            or _SHA256_PATTERN.fullmatch(spec_sha256) is None
        ):
            _raise("receipts_mismatch")
        if outcome == "unavailable" and drawer_ids:
            _raise("receipts_mismatch")
        if outcome == "written" and not drawer_ids:
            _raise("receipts_mismatch")
    return CompletionMiningOutcome(
        completion_id=prepared.intent.completion_id,
        outcome=outcome,
        spec_sha256=spec_sha256,
        drawer_ids=drawer_ids,
    )


def _completion_mining_spec_snapshot(
    prepared: PreparedControllerCompletion,
    *,
    project_root: Path,
    spec_file: Path,
) -> tuple[bytes, str, str]:
    _require_prepared_project_root(prepared, project_root)
    if not isinstance(spec_file, Path):
        _raise("intent_invalid")
    try:
        relative = spec_file.relative_to(prepared._project_root)
    except ValueError:
        _raise("intent_invalid")
    if (
        len(relative.parts) != 3
        or relative.parts[0] != "specs"
        or relative.parts[1] in {"", ".", ".."}
        or relative.parts[2] != "spec.md"
    ):
        _raise("intent_invalid")
    _require_real_directory(
        spec_file.parent,
        missing_code="stage_missing",
    )
    content = _read_regular(
        spec_file,
        maximum=_MAX_CONTEXT_FILE_BYTES,
        code="receipts_mismatch",
    )
    return (
        content,
        hashlib.sha256(content).hexdigest(),
        relative.as_posix(),
    )


def _completion_mining_metadata(
    metadata: object,
    *,
    source: str,
    spec_sha256: str,
) -> dict[str, object]:
    if metadata is None:
        result: dict[str, object] = {}
    elif type(metadata) is dict:
        try:
            result = _normalize_json(
                _bounded_detach_untrusted(
                    metadata,
                    root_path="$.completion_mining_metadata",
                )
            )
        except Exception:
            _raise("intent_invalid")
    else:
        _raise("intent_invalid")
    required = {
        "scope": "canonical",
        "canonical": True,
        "artifact_path": source,
        "artifact_hash": f"sha256:{spec_sha256}",
    }
    for key, expected in required.items():
        if key in result and result[key] != expected:
            _raise("receipts_mismatch")
        result[key] = expected
    return result


def _completion_local_mining_plan(
    *,
    project_root: Path,
    content: bytes,
    source: str,
    metadata: dict[str, object],
) -> tuple[str, ...]:
    """Compute deterministic IDs from local config/spec without a backend."""
    try:
        from codegen.memory.context import (
            _read_wing_from_echelon_config,
        )
        from echelon.spec_memory_miner import (
            plan_canonical_requirement_drawer_ids,
        )

        wing = _read_wing_from_echelon_config(project_root)
        planned = plan_canonical_requirement_drawer_ids(
            content,
            source=source,
            artifact_metadata=metadata,
            wing=wing,
        )
    except (Exception, SystemExit) as exc:
        raise ValueError("local deterministic mining plan failed") from exc
    if type(planned) is not list:
        raise ValueError("local deterministic mining plan is invalid")
    return _validate_mining_drawer_ids(sorted(planned))


def _default_completion_miner_factory(
    project_root: Path,
    run_id: str,
) -> object:
    from echelon.mempalace_requirements import create_requirement_memory_adapter

    return create_requirement_memory_adapter(project_root, run_id)


def _completion_mining_factory(
    factory: Callable[[], object] | None,
    *,
    project_root: Path,
    run_id: str,
) -> object:
    if factory is None:
        return _default_completion_miner_factory(
            project_root,
            run_id,
        )
    if not callable(factory):
        _raise("intent_invalid")
    return factory()


def _verify_completion_mining_postimage(
    miner: object,
    *,
    content: bytes,
    source: str,
    metadata: dict[str, object],
    drawer_ids: tuple[str, ...],
) -> bool:
    verify = getattr(miner, "verify_canonical_bytes", None)
    if not callable(verify):
        return False
    try:
        return verify(
            content,
            source=source,
            artifact_metadata=metadata,
            drawer_ids=list(drawer_ids),
        ) is True
    except (Exception, SystemExit):
        return False


def _persist_completion_mining_outcome(
    prepared: PreparedControllerCompletion,
    outcome: CompletionMiningOutcome,
) -> CompletionMiningOutcome:
    persisted = _persist_current_completion_receipt(
        prepared,
        "mining",
        outcome.to_dict(),
    )
    return _validate_completion_mining_receipt(
        persisted,
        prepared=prepared,
    )


def apply_or_verify_completion_mining(
    prepared: PreparedControllerCompletion,
    *,
    project_root: Path,
    spec_file: Path | None,
    run_id: str,
    artifact_metadata: object = None,
    miner_factory: Callable[[], object] | None = None,
    expected_receipt: object | None = None,
    fault_hook: Callable[[str], None] | None = None,
) -> CompletionMiningOutcome:
    """Mine, receipt, or verify one bounded deterministic canonical outcome."""
    _verify_prepared_completion_identity(prepared)
    _require_prepared_project_root(prepared, project_root)
    if (
        "mining" not in prepared.intent.effect_plan
        or prepared.marker.step != "mining"
        or not prepared.intent.mine_phase_a
        or (fault_hook is not None and not callable(fault_hook))
    ):
        _raise("intent_invalid")
    _, current_receipt = _current_completion_effect_receipt(
        prepared,
        "mining",
    )
    persisted_outcome = (
        _validate_completion_mining_receipt(
            current_receipt,
            prepared=prepared,
        )
        if current_receipt is not None
        else None
    )
    if expected_receipt is not None:
        expected = _validate_completion_mining_receipt(
            expected_receipt,
            prepared=prepared,
        )
        if persisted_outcome is None or expected != persisted_outcome:
            _raise("receipts_mismatch")

    if spec_file is None:
        if persisted_outcome is not None:
            if persisted_outcome.outcome != "not_applicable":
                _raise("receipts_mismatch")
            return persisted_outcome
        return _persist_completion_mining_outcome(
            prepared,
            CompletionMiningOutcome(
                completion_id=prepared.intent.completion_id,
                outcome="not_applicable",
                spec_sha256=None,
                drawer_ids=(),
            ),
        )

    content, spec_sha256, source = _completion_mining_spec_snapshot(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
    )
    metadata = _completion_mining_metadata(
        artifact_metadata,
        source=source,
        spec_sha256=spec_sha256,
    )
    if persisted_outcome is not None:
        if (
            persisted_outcome.outcome == "not_applicable"
            or persisted_outcome.spec_sha256 != spec_sha256
        ):
            _raise("receipts_mismatch")
        if persisted_outcome.outcome == "unavailable":
            return persisted_outcome
        if (
            persisted_outcome.outcome == "failed"
            and not persisted_outcome.drawer_ids
        ):
            return persisted_outcome
    try:
        planned_ids = _completion_local_mining_plan(
            project_root=prepared._project_root,
            content=content,
            source=source,
            metadata=metadata,
        )
    except (CompletionError, ValueError):
        if persisted_outcome is not None:
            _raise("receipts_mismatch")
        return _persist_completion_mining_outcome(
            prepared,
            CompletionMiningOutcome(
                completion_id=prepared.intent.completion_id,
                outcome="failed",
                spec_sha256=spec_sha256,
                drawer_ids=(),
            ),
        )
    if persisted_outcome is not None:
        if any(
            drawer_id not in planned_ids
            for drawer_id in persisted_outcome.drawer_ids
        ):
            _raise("receipts_mismatch")
        if persisted_outcome.outcome == "failed":
            return persisted_outcome
        if type(run_id) is not str or not run_id or len(run_id) > 1_024:
            _raise("intent_invalid")
        try:
            miner = _completion_mining_factory(
                miner_factory,
                project_root=prepared._project_root,
                run_id=run_id,
            )
        except (Exception, SystemExit):
            _raise("receipts_mismatch")
        plan = getattr(miner, "plan_canonical_bytes", None)
        try:
            planned = plan(
                content,
                source=source,
                artifact_metadata=metadata,
            )
        except (Exception, SystemExit, TypeError):
            _raise("receipts_mismatch")
        producer_planned_ids = _validate_mining_drawer_ids(
            sorted(planned) if type(planned) is list else planned
        )
        if producer_planned_ids != planned_ids:
            _raise("receipts_mismatch")
        if (
            persisted_outcome.outcome
            in {"written", "already_present"}
            and persisted_outcome.drawer_ids != planned_ids
        ):
            _raise("receipts_mismatch")
        if not _verify_completion_mining_postimage(
            miner,
            content=content,
            source=source,
            metadata=metadata,
            drawer_ids=persisted_outcome.drawer_ids,
        ):
            _raise("receipts_mismatch")
        return persisted_outcome

    if type(run_id) is not str or not run_id or len(run_id) > 1_024:
        _raise("intent_invalid")
    try:
        miner = _completion_mining_factory(
            miner_factory,
            project_root=prepared._project_root,
            run_id=run_id,
        )
    except (Exception, SystemExit):
        return _persist_completion_mining_outcome(
            prepared,
            CompletionMiningOutcome(
                completion_id=prepared.intent.completion_id,
                outcome="unavailable",
                spec_sha256=spec_sha256,
                drawer_ids=(),
            ),
        )

    plan = getattr(miner, "plan_canonical_bytes", None)
    mine = getattr(miner, "mine_canonical_bytes", None)
    if not callable(plan) or not callable(mine):
        result_outcome = CompletionMiningOutcome(
            completion_id=prepared.intent.completion_id,
            outcome="failed",
            spec_sha256=spec_sha256,
            drawer_ids=(),
        )
        return _persist_completion_mining_outcome(
            prepared,
            result_outcome,
        )
    try:
        planned_raw = plan(
            content,
            source=source,
            artifact_metadata=metadata,
        )
        if type(planned_raw) is not list:
            raise ValueError("invalid deterministic mining plan")
        producer_planned_ids = _validate_mining_drawer_ids(
            sorted(planned_raw)
        )
        if producer_planned_ids != planned_ids:
            _raise("receipts_mismatch")
    except CompletionError:
        raise
    except (Exception, SystemExit):
        return _persist_completion_mining_outcome(
            prepared,
            CompletionMiningOutcome(
                completion_id=prepared.intent.completion_id,
                outcome="failed",
                spec_sha256=spec_sha256,
                drawer_ids=(),
            ),
        )
    try:
        result = mine(
            content,
            source=source,
            artifact_metadata=metadata,
        )
    except (Exception, SystemExit):
        result = None

    observed, observed_digest, _ = _completion_mining_spec_snapshot(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
    )
    if observed != content or observed_digest != spec_sha256:
        _raise("receipts_mismatch")
    if result is None:
        return _persist_completion_mining_outcome(
            prepared,
            CompletionMiningOutcome(
                completion_id=prepared.intent.completion_id,
                outcome="failed",
                spec_sha256=spec_sha256,
                drawer_ids=(),
            ),
        )

    counters: dict[str, int] = {}
    for name in (
        "total",
        "written",
        "already_present",
        "unavailable",
        "failed",
    ):
        value = getattr(result, name, None)
        if type(value) is not int or value < 0:
            _raise("receipts_mismatch")
        counters[name] = value
    expected_ids_value = getattr(result, "expected_drawer_ids", None)
    drawer_ids_value = getattr(result, "drawer_ids", None)
    if (
        type(expected_ids_value) is not list
        or type(drawer_ids_value) is not list
    ):
        _raise("receipts_mismatch")
    result_expected_ids = _validate_mining_drawer_ids(
        sorted(expected_ids_value)
    )
    drawer_ids = _validate_mining_drawer_ids(
        sorted(drawer_ids_value)
    )
    if (
        result_expected_ids != planned_ids
        or counters["total"] != len(planned_ids)
        or sum(
            counters[name]
            for name in (
                "written",
                "already_present",
                "unavailable",
                "failed",
            )
        )
        != counters["total"]
        or len(drawer_ids)
        != counters["written"] + counters["already_present"]
        or any(
            drawer_id not in planned_ids
            for drawer_id in drawer_ids
        )
    ):
        _raise("receipts_mismatch")
    if drawer_ids and not _verify_completion_mining_postimage(
        miner,
        content=content,
        source=source,
        metadata=metadata,
        drawer_ids=drawer_ids,
    ):
        _raise("receipts_mismatch")
    observed, observed_digest, _ = _completion_mining_spec_snapshot(
        prepared,
        project_root=project_root,
        spec_file=spec_file,
    )
    if observed != content or observed_digest != spec_sha256:
        _raise("receipts_mismatch")

    if counters["failed"]:
        outcome_name = "failed"
    elif counters["unavailable"]:
        outcome_name = (
            "unavailable" if not drawer_ids else "failed"
        )
    elif counters["written"]:
        outcome_name = "written"
    else:
        outcome_name = "already_present"
    outcome_ids = (
        ()
        if outcome_name == "unavailable"
        else drawer_ids
    )
    outcome = CompletionMiningOutcome(
        completion_id=prepared.intent.completion_id,
        outcome=outcome_name,
        spec_sha256=spec_sha256,
        drawer_ids=outcome_ids,
    )
    if fault_hook is not None:
        fault_hook("after_mining")
    return _persist_completion_mining_outcome(
        prepared,
        outcome,
    )
