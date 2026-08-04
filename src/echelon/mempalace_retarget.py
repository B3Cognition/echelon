"""Fail-closed MemPalace ownership boundaries for destructive spec retargets."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Iterable, Mapping

from echelon.atomic_install import atomic_rename_no_replace
from echelon.mempalace_audit import (
    MAX_AUDIT_SCAN_ROWS,
    SpecMemoryAuditReport,
    SpecMemoryCleanupReport,
    _write_text_durable_atomic,
    audit_spec_memory,
    cleanup_stale_spec_memory,
    render_audit_markdown,
    scan_wing_rows_complete,
)
from echelon.mempalace_requirements import (
    SpecMemoryMineReport,
    create_requirement_memory_adapter,
    mine_spec_requirements,
)
from echelon.strict_json import loads_strict_json


_CANONICAL_SPEC_ID = re.compile(
    r"^(?:[0-9]{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PATH_LENGTH = 4_096
_MAX_DRAWER_ID_LENGTH = 1_024
_DELETE_BATCH_SIZE = 128
_REPORT_NAMES = (
    "mempalace-audit.json",
    "mempalace-audit.md",
    "mempalace-mine.json",
)
_REPORT_MANIFEST_NAME = "mempalace-refresh-manifest.json"
_REPORT_TRANSACTION_NAME = ".mempalace-refresh-transaction"
_REPORT_CLEANUP_RECEIPT_NAME = ".mempalace-refresh-cleanup.json"
_REPORT_DETACHED_PREFIX = ".mempalace-refresh-detached-"
_REPORT_COMPLETED_RECEIPT_PREFIX = ".mempalace-refresh-completed-"
_MAX_COMPLETED_REPORT_TRANSACTIONS = 128
_MAX_REPORT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class RetargetMemoryReceipt:
    status: str
    spec_id: str
    deleted_count: int
    deleted_ids: tuple[str, ...]
    drawer_set_digest: str
    mine_status: str | None = None
    audit_status: str | None = None
    adapter: str | None = None
    wing: str | None = None
    palace_path: str | None = None
    scanned_count: int = 0
    delete_acknowledged_count: int | None = None
    remaining_owned_ids: tuple[str, ...] = ()
    unrelated_missing_ids: tuple[str, ...] = ()
    unrelated_changed_ids: tuple[str, ...] = ()
    unexpected_added_ids: tuple[str, ...] = ()
    report_set_digest: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "not_applicable"}:
            raise ValueError("invalid retarget memory receipt status")
        _require_spec_id(self.spec_id)
        _require_receipt_ids(self.deleted_ids, field="deleted_ids")
        _require_receipt_ids(
            self.remaining_owned_ids,
            field="remaining_owned_ids",
        )
        _require_receipt_ids(
            self.unrelated_missing_ids,
            field="unrelated_missing_ids",
        )
        _require_receipt_ids(
            self.unrelated_changed_ids,
            field="unrelated_changed_ids",
        )
        _require_receipt_ids(
            self.unexpected_added_ids,
            field="unexpected_added_ids",
        )
        if type(self.deleted_count) is not int or self.deleted_count != len(
            self.deleted_ids
        ):
            raise ValueError("invalid retarget memory deleted count")
        if type(self.scanned_count) is not int or not (
            0 <= self.scanned_count <= MAX_AUDIT_SCAN_ROWS
        ):
            raise ValueError("invalid retarget memory scanned count")
        if (
            self.delete_acknowledged_count is not None
            and (
                type(self.delete_acknowledged_count) is not int
                or self.delete_acknowledged_count < 0
            )
        ):
            raise ValueError("invalid retarget memory delete acknowledgement")
        if _SHA256.fullmatch(self.drawer_set_digest) is None:
            raise ValueError("invalid retarget memory drawer digest")
        if (
            self.report_set_digest is not None
            and _SHA256.fullmatch(self.report_set_digest) is None
        ):
            raise ValueError("invalid retarget memory report set digest")
        for value, field in (
            (self.mine_status, "mine_status"),
            (self.audit_status, "audit_status"),
            (self.adapter, "adapter"),
            (self.wing, "wing"),
            (self.palace_path, "palace_path"),
            (self.failure_code, "failure_code"),
        ):
            if value is not None:
                _require_receipt_text(value, field=field)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "spec_id": self.spec_id,
            "deleted_count": self.deleted_count,
            "deleted_ids": list(self.deleted_ids),
            "drawer_set_digest": self.drawer_set_digest,
            "mine_status": self.mine_status,
            "audit_status": self.audit_status,
            "adapter": self.adapter,
            "wing": self.wing,
            "palace_path": self.palace_path,
            "scanned_count": self.scanned_count,
            "delete_acknowledged_count": self.delete_acknowledged_count,
            "remaining_owned_ids": list(self.remaining_owned_ids),
            "unrelated_missing_ids": list(self.unrelated_missing_ids),
            "unrelated_changed_ids": list(self.unrelated_changed_ids),
            "unexpected_added_ids": list(self.unexpected_added_ids),
            "report_set_digest": self.report_set_digest,
            "failure_code": self.failure_code,
        }


class RetargetMemoryError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        receipt: RetargetMemoryReceipt | None = None,
    ) -> None:
        super().__init__(message)
        self.receipt = receipt


def _require_spec_id(spec_id: object) -> str:
    if type(spec_id) is not str or _CANONICAL_SPEC_ID.fullmatch(spec_id) is None:
        raise ValueError("invalid canonical spec ID")
    return spec_id


def _require_receipt_text(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_PATH_LENGTH
        or value != value.strip()
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"invalid retarget memory {field}")
    return value


def _require_receipt_ids(values: object, *, field: str) -> tuple[str, ...]:
    if (
        type(values) is not tuple
        or len(values) > MAX_AUDIT_SCAN_ROWS
        or any(
            type(value) is not str
            or not value
            or len(value) > _MAX_DRAWER_ID_LENGTH
            for value in values
        )
        or values != tuple(sorted(set(values)))
    ):
        raise ValueError(f"invalid retarget memory {field}")
    return values


def _digest_ids(drawer_ids: tuple[str, ...]) -> str:
    _require_receipt_ids(drawer_ids, field="drawer_ids")
    payload = json.dumps(
        list(drawer_ids),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _configured_mempalace_wing(project_root: Path) -> str | None:
    root = project_root.resolve()
    canonical = root / ".echelon" / "config.yml"
    legacy = (
        root
        / ".specify"
        / "extensions"
        / "echelon"
        / "echelon-config.yml"
    )
    config_path = canonical if os.path.lexists(canonical) else legacy
    if not os.path.lexists(config_path):
        return None
    if config_path.is_symlink() or not config_path.is_file():
        raise RetargetMemoryError("configured MemPalace config is unavailable")
    try:
        import yaml

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config = {} if loaded is None else loaded
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "configured MemPalace config is unavailable"
        ) from exc
    if type(config) is not dict:
        raise RetargetMemoryError("configured MemPalace config is invalid")
    if "mempalace" not in config:
        return None
    mempalace = config["mempalace"]
    if type(mempalace) is not dict:
        raise RetargetMemoryError("configured MemPalace storage is incomplete")
    wing = mempalace.get("wing")
    if type(wing) is not str or not wing.strip():
        raise RetargetMemoryError("configured MemPalace storage is incomplete")
    checked_wing = wing.strip()
    try:
        _require_receipt_text(checked_wing, field="wing")
    except ValueError as exc:
        raise RetargetMemoryError(
            "configured MemPalace storage identity is invalid"
        ) from exc
    return checked_wing


def _normalized_ownership_path(value: object) -> tuple[str, str | None]:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_PATH_LENGTH
        or "\\" in value
        or value.startswith("/")
        or ":" in value
        or "%" in value
        or any(ord(character) < 32 for character in value)
    ):
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    path = PurePosixPath(value)
    if (
        path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    if path.parts[0] != "specs":
        return value, None
    if len(path.parts) < 3 or _CANONICAL_SPEC_ID.fullmatch(path.parts[1]) is None:
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    return value, path.parts[1]


def _owned_by_spec(metadata: Mapping[str, object], spec_id: str) -> bool:
    _require_spec_id(spec_id)
    if not isinstance(metadata, Mapping):
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    declared: str | None = None
    if "spec_id" in metadata:
        value = metadata["spec_id"]
        if type(value) is not str or _CANONICAL_SPEC_ID.fullmatch(value) is None:
            raise RetargetMemoryError("invalid MemPalace ownership metadata")
        declared = value
    paths: list[tuple[str, str | None]] = []
    for field in ("artifact_path", "source_file"):
        if field in metadata:
            paths.append(_normalized_ownership_path(metadata[field]))
    if len(paths) == 2 and paths[0][0] != paths[1][0]:
        raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
    path_spec = paths[0][1] if paths else None
    if declared is not None and paths and path_spec is None:
        raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
    if declared is not None and path_spec is not None and declared != path_spec:
        raise RetargetMemoryError("ambiguous MemPalace ownership metadata")

    canonical = metadata.get("canonical") if "canonical" in metadata else None
    scope = metadata.get("scope") if "scope" in metadata else None
    artifact_kind = (
        metadata.get("artifact_kind")
        if "artifact_kind" in metadata
        else None
    )
    if "canonical" in metadata and type(canonical) is not bool:
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    if "scope" in metadata and (type(scope) is not str or not scope):
        raise RetargetMemoryError("invalid MemPalace ownership metadata")
    if "artifact_kind" in metadata and (
        type(artifact_kind) is not str or not artifact_kind
    ):
        raise RetargetMemoryError("invalid MemPalace ownership metadata")

    exact_evidence = (
        declared is not None
        and canonical is True
        and scope == "spec-evidence"
        and artifact_kind == "spec-evidence"
    )
    if path_spec is not None:
        if canonical is False:
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        if scope is None and artifact_kind is not None:
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        if scope == "canonical" and artifact_kind is not None:
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        if scope == "canonical-support" and artifact_kind != "supporting-context":
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        if artifact_kind == "supporting-context" and scope != "canonical-support":
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        if scope == "spec-evidence" or artifact_kind == "spec-evidence":
            if not exact_evidence:
                raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        elif scope not in {None, "canonical", "canonical-support"}:
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        return path_spec == spec_id

    if declared is not None:
        if not exact_evidence:
            raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
        return declared == spec_id
    if scope in {"canonical", "canonical-support", "spec-evidence"} or (
        artifact_kind in {"supporting-context", "spec-evidence"}
    ):
        raise RetargetMemoryError("ambiguous MemPalace ownership metadata")
    return False


def _adapter_identity(
    adapter: object,
    *,
    configured_wing: str,
) -> tuple[str, str, str]:
    wing = getattr(adapter, "wing", None)
    palace_path = getattr(adapter, "palace_path", None)
    if type(wing) is not str or wing != configured_wing:
        raise RetargetMemoryError(
            "configured MemPalace adapter wing identity is inconsistent"
        )
    if not isinstance(palace_path, (str, Path)):
        raise RetargetMemoryError(
            "configured MemPalace adapter storage identity is incomplete"
        )
    adapter_name = f"{type(adapter).__module__}.{type(adapter).__qualname__}"
    palace_identity = str(palace_path)
    try:
        _require_receipt_text(adapter_name, field="adapter")
        _require_receipt_text(wing, field="wing")
        _require_receipt_text(palace_identity, field="palace_path")
    except ValueError as exc:
        raise RetargetMemoryError(
            "configured MemPalace adapter identity is invalid"
        ) from exc
    return adapter_name, wing, palace_identity


def _collection_from_requirement_adapter(adapter: object) -> object:
    opener = getattr(adapter, "open_collection_read_only", None)
    if not callable(opener):
        raise RetargetMemoryError("configured MemPalace adapter is unavailable")
    try:
        return opener()
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "configured MemPalace collection is unavailable"
        ) from exc


def _delete_acknowledgement(result: object) -> int | None:
    if result is None:
        return None
    value: object
    if type(result) is int:
        value = result
    elif isinstance(result, Mapping):
        if "deleted" not in result:
            return None
        value = result["deleted"]
    elif hasattr(result, "deleted"):
        value = getattr(result, "deleted")
    else:
        raise RetargetMemoryError("MemPalace delete acknowledgement is invalid")
    if type(value) is not int or value < 0:
        raise RetargetMemoryError("MemPalace delete acknowledgement is invalid")
    return value


def _type_exact_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        left_dict = left
        right_dict = right
        if len(left_dict) != len(right_dict):
            return False
        unmatched = list(right_dict.items())
        for left_key, left_value in left_dict.items():
            for index, (right_key, right_value) in enumerate(unmatched):
                if _type_exact_equal(left_key, right_key):
                    if not _type_exact_equal(left_value, right_value):
                        return False
                    unmatched.pop(index)
                    break
            else:
                return False
        return not unmatched
    if type(left) in {list, tuple}:
        return len(left) == len(right) and all(
            _type_exact_equal(left_value, right_value)
            for left_value, right_value in zip(left, right)
        )
    return bool(left == right)


def _classify_owned_rows(
    rows: Mapping[str, tuple[str, dict[str, object]]],
    spec_id: str,
) -> tuple[str, ...]:
    owned: list[str] = []
    for drawer_id, (_document, metadata) in rows.items():
        if (
            type(drawer_id) is not str
            or not drawer_id
            or len(drawer_id) > _MAX_DRAWER_ID_LENGTH
        ):
            raise RetargetMemoryError("invalid MemPalace drawer identity")
        if _owned_by_spec(metadata, spec_id):
            owned.append(drawer_id)
    result = tuple(sorted(owned))
    _require_receipt_ids(result, field="owned_ids")
    return result


def exclude_retarget_spec_drawers(
    drawers: Iterable[object],
    spec_id: str,
) -> list[object]:
    """Return a new result list without exact selected-spec memory drawers."""
    try:
        checked_spec_id = _require_spec_id(spec_id)
    except ValueError as exc:
        raise RetargetMemoryError("invalid retarget spec identity") from exc
    filtered: list[object] = []
    for drawer in drawers:
        metadata = getattr(drawer, "metadata", None)
        if not isinstance(metadata, Mapping):
            raise RetargetMemoryError("invalid MemPalace ownership metadata")
        if not _owned_by_spec(metadata, checked_spec_id):
            filtered.append(drawer)
    return filtered


def _receipt(
    *,
    status: str,
    spec_id: str,
    deleted_ids: tuple[str, ...],
    drawer_ids: tuple[str, ...],
    adapter: str | None = None,
    wing: str | None = None,
    palace_path: str | None = None,
    scanned_count: int = 0,
    acknowledged: int | None = None,
    remaining: tuple[str, ...] = (),
    unrelated_missing: tuple[str, ...] = (),
    unrelated_changed: tuple[str, ...] = (),
    unexpected_added: tuple[str, ...] = (),
    report_set_digest: str | None = None,
    failure_code: str | None = None,
    mine_status: str | None = None,
    audit_status: str | None = None,
) -> RetargetMemoryReceipt:
    return RetargetMemoryReceipt(
        status=status,
        spec_id=spec_id,
        deleted_count=len(deleted_ids),
        deleted_ids=deleted_ids,
        drawer_set_digest=_digest_ids(drawer_ids),
        mine_status=mine_status,
        audit_status=audit_status,
        adapter=adapter,
        wing=wing,
        palace_path=palace_path,
        scanned_count=scanned_count,
        delete_acknowledged_count=acknowledged,
        remaining_owned_ids=remaining,
        unrelated_missing_ids=unrelated_missing,
        unrelated_changed_ids=unrelated_changed,
        unexpected_added_ids=unexpected_added,
        report_set_digest=report_set_digest,
        failure_code=failure_code,
    )


def purge_retarget_spec_memory(
    project_root: Path,
    spec_id: str,
) -> RetargetMemoryReceipt:
    """Delete only rows whose complete metadata proves exact spec ownership."""
    try:
        checked_spec_id = _require_spec_id(spec_id)
    except ValueError as exc:
        raise RetargetMemoryError("invalid retarget spec identity") from exc
    configured_wing = _configured_mempalace_wing(project_root)
    if configured_wing is None:
        return _receipt(
            status="not_applicable",
            spec_id=checked_spec_id,
            deleted_ids=(),
            drawer_ids=(),
        )
    try:
        adapter = create_requirement_memory_adapter(
            project_root,
            run_id="retarget-purge",
        )
        adapter_name, wing, palace_path = _adapter_identity(
            adapter,
            configured_wing=configured_wing,
        )
        collection = _collection_from_requirement_adapter(adapter)
        rows = scan_wing_rows_complete(collection, wing=wing)
        owned = _classify_owned_rows(rows, checked_spec_id)
    except RetargetMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "configured MemPalace complete scan is unavailable"
        ) from exc
    if not owned:
        return _receipt(
            status="pass",
            spec_id=checked_spec_id,
            deleted_ids=(),
            drawer_ids=(),
            adapter=adapter_name,
            wing=wing,
            palace_path=palace_path,
            scanned_count=len(rows),
        )

    acknowledgement_total = 0
    all_batches_acknowledged = True
    completed_batches = 0
    total_batches = (len(owned) + _DELETE_BATCH_SIZE - 1) // _DELETE_BATCH_SIZE
    delete_failure: Exception | SystemExit | None = None
    for start in range(0, len(owned), _DELETE_BATCH_SIZE):
        batch = owned[start : start + _DELETE_BATCH_SIZE]
        try:
            raw_acknowledgement = collection.delete(ids=list(batch))  # type: ignore[attr-defined]
            acknowledgement = _delete_acknowledgement(raw_acknowledgement)
            if acknowledgement is None:
                all_batches_acknowledged = False
            else:
                acknowledgement_total += acknowledgement
                if acknowledgement != len(batch):
                    raise RetargetMemoryError(
                        "MemPalace reported partial deletion"
                    )
            completed_batches += 1
        except (Exception, SystemExit) as exc:
            delete_failure = exc
            break

    try:
        remaining_rows = scan_wing_rows_complete(collection, wing=wing)
        postscan_owned = _classify_owned_rows(
            remaining_rows,
            checked_spec_id,
        )
    except (Exception, SystemExit) as exc:
        receipt = _receipt(
            status="fail",
            spec_id=checked_spec_id,
            deleted_ids=(),
            drawer_ids=owned,
            adapter=adapter_name,
            wing=wing,
            palace_path=palace_path,
            scanned_count=len(rows),
            acknowledged=(
                acknowledgement_total
                if all_batches_acknowledged
                and completed_batches == total_batches
                and delete_failure is None
                else None
            ),
            failure_code="retarget_memory_rescan_failed",
        )
        raise RetargetMemoryError(
            "MemPalace complete rescan failed after deletion",
            receipt=receipt,
        ) from exc

    remaining_ids = set(remaining_rows)
    remaining_owned = tuple(
        sorted(set(postscan_owned).union(set(owned).intersection(remaining_ids)))
    )
    actual_deleted = tuple(sorted(set(owned).difference(remaining_ids)))
    unrelated_before = {
        drawer_id: row
        for drawer_id, row in rows.items()
        if drawer_id not in set(owned)
    }
    unrelated_missing = tuple(
        sorted(set(unrelated_before).difference(remaining_ids))
    )
    unrelated_changed = tuple(
        sorted(
            drawer_id
            for drawer_id, before_row in unrelated_before.items()
            if drawer_id in remaining_rows
            and not _type_exact_equal(before_row, remaining_rows[drawer_id])
        )
    )
    unexpected_added = tuple(
        sorted(remaining_ids.difference(set(rows)))
    )
    receipt = _receipt(
        status=(
            "fail"
            if delete_failure is not None
            or remaining_owned
            or unrelated_missing
            or unrelated_changed
            or unexpected_added
            else "pass"
        ),
        spec_id=checked_spec_id,
        deleted_ids=actual_deleted,
        drawer_ids=owned,
        adapter=adapter_name,
        wing=wing,
        palace_path=palace_path,
        scanned_count=len(rows),
        acknowledged=(
            acknowledgement_total
            if all_batches_acknowledged
            and completed_batches == total_batches
            and delete_failure is None
            else None
        ),
        remaining=remaining_owned,
        unrelated_missing=unrelated_missing,
        unrelated_changed=unrelated_changed,
        unexpected_added=unexpected_added,
        failure_code=(
            "retarget_memory_delete_partial"
            if delete_failure is not None or remaining_owned
            else (
                "retarget_memory_unrelated_missing"
                if unrelated_missing
                else (
                    "retarget_memory_unrelated_changed"
                    if unrelated_changed
                    else (
                        "retarget_memory_unexpected_added"
                        if unexpected_added
                        else None
                    )
                )
            )
        ),
    )
    if delete_failure is not None or remaining_owned:
        raise RetargetMemoryError(
            "MemPalace partial deletion left selected spec memory",
            receipt=receipt,
        ) from delete_failure
    if unrelated_missing:
        raise RetargetMemoryError(
            "MemPalace deletion affected unrelated drawer IDs",
            receipt=receipt,
        )
    if unrelated_changed or unexpected_added:
        raise RetargetMemoryError(
            "MemPalace unrelated postimage changed during deletion",
            receipt=receipt,
        )
    return receipt


def _require_refresh_report_identity(
    report: object,
    *,
    label: str,
    spec_id: str,
    spec_dir: Path,
    wing: str,
    palace_path: str,
) -> None:
    if (
        getattr(report, "spec_id", None) != spec_id
        or getattr(report, "spec_dir", None) != str(spec_dir)
        or getattr(report, "wing", None) != wing
        or getattr(report, "palace_path", None) != palace_path
    ):
        raise RetargetMemoryError(
            f"replacement memory {label} receipt is inconsistent"
        )


def _strict_report_ids(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise RetargetMemoryError(
            f"replacement memory {label} receipt is inconsistent"
        )
    result = tuple(value)
    try:
        return _require_receipt_ids(result, field=label)
    except ValueError as exc:
        raise RetargetMemoryError(
            f"replacement memory {label} receipt is inconsistent"
        ) from exc


def _strict_report_strings(value: object, *, label: str) -> tuple[str, ...]:
    if (
        type(value) is not list
        or len(value) > MAX_AUDIT_SCAN_ROWS
        or any(
            type(item) is not str
            or not item
            or len(item) > _MAX_PATH_LENGTH
            or any(ord(character) < 32 for character in item)
            for item in value
        )
        or value != sorted(set(value))
    ):
        raise RetargetMemoryError(
            f"replacement memory {label} receipt is inconsistent"
        )
    return tuple(value)


def _validate_refresh_audit(
    audit: object,
    *,
    expected_count: int,
) -> str:
    if (
        type(audit) is not SpecMemoryAuditReport
        or type(getattr(audit, "schema_version", None)) is not int
        or getattr(audit, "schema_version", None) != 1
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    status = getattr(audit, "status", None)
    if type(status) is not str or status not in {"pass", "warn"}:
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    observed_expected = getattr(audit, "expected_count", None)
    observed_present = getattr(audit, "present_current_count", None)
    if (
        type(observed_expected) is not int
        or type(observed_present) is not int
        or observed_expected != expected_count
        or observed_present != expected_count
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    anomaly_fields = (
        "missing",
        "stale",
        "wrong_wing",
        "wrong_room",
        "duplicate",
        "non_canonical",
        "lifecycle_excluded",
    )
    if any(
        _strict_report_ids(getattr(audit, field, None), label="audit")
        for field in anomaly_fields
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    if _strict_report_strings(
        getattr(audit, "recommendations", None),
        label="audit recommendations",
    ) or _strict_report_strings(
        getattr(audit, "errors", None),
        label="audit errors",
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    probe = getattr(audit, "retrieval_probe", None)
    if type(probe) is not dict or set(probe) != {"status", "checked"}:
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    probe_status = probe["status"]
    checked = probe["checked"]
    if (
        type(probe_status) is not str
        or probe_status not in {"pass", "warn"}
        or type(checked) is not int
        or not (0 <= checked <= MAX_AUDIT_SCAN_ROWS)
        or (probe_status == "warn" and checked != 0)
        or (probe_status == "pass" and checked != expected_count)
        or status != ("warn" if probe_status == "warn" else "pass")
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
        )
    return status


def _sha256_text(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os,
        "O_NOFOLLOW",
        0,
    )
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_optional_report_text(path: Path) -> str | None:
    if not os.path.lexists(path):
        return None
    if path.is_symlink() or not path.is_file():
        raise RetargetMemoryError(
            "replacement memory report target is not a regular file"
        )
    size = path.stat().st_size
    if size > _MAX_REPORT_BYTES:
        raise RetargetMemoryError("replacement memory report target is oversized")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RetargetMemoryError(
            "replacement memory report target is unreadable"
        ) from exc


def _report_manifest(
    *,
    spec_id: str,
    contents: Mapping[str, str],
) -> tuple[str, str]:
    if type(contents) is not dict or tuple(sorted(contents)) != _REPORT_NAMES:
        raise RetargetMemoryError("replacement memory report set is inconsistent")
    files = [
        {
            "path": name,
            "sha256": _sha256_text(contents[name]),
            "size": len(contents[name].encode("utf-8")),
        }
        for name in _REPORT_NAMES
    ]
    digest_payload = json.dumps(
        files,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    report_set_digest = f"sha256:{hashlib.sha256(digest_payload).hexdigest()}"
    manifest = {
        "schema_version": 1,
        "spec_id": spec_id,
        "files": files,
        "report_set_digest": report_set_digest,
    }
    return (
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        report_set_digest,
    )


def _preflight_report_set(spec_dir: Path) -> None:
    if spec_dir.is_symlink() or not spec_dir.is_dir():
        raise RetargetMemoryError(
            "replacement memory report parent is not a real directory"
        )
    for name in (*_REPORT_NAMES, _REPORT_MANIFEST_NAME):
        _read_optional_report_text(spec_dir / name)
    transaction = spec_dir / _REPORT_TRANSACTION_NAME
    if os.path.lexists(transaction) and (
        transaction.is_symlink() or not transaction.is_dir()
    ):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )


def _write_transaction_text(path: Path, content: str) -> None:
    if len(content.encode("utf-8")) > _MAX_REPORT_BYTES:
        raise RetargetMemoryError("replacement memory report is oversized")
    _write_text_durable_atomic(path, content)


def _stage_report_transaction(
    spec_dir: Path,
    *,
    spec_id: str,
    contents: dict[str, str],
    manifest_content: str,
) -> Path:
    old_contents = {
        name: _read_optional_report_text(spec_dir / name)
        for name in _REPORT_NAMES
    }
    old_manifest = _read_optional_report_text(
        spec_dir / _REPORT_MANIFEST_NAME
    )
    staging = Path(
        tempfile.mkdtemp(
            prefix=".mempalace-refresh-staging-",
            dir=spec_dir,
        )
    )
    transaction = spec_dir / _REPORT_TRANSACTION_NAME
    try:
        new_dir = staging / "new"
        old_dir = staging / "old"
        new_dir.mkdir(mode=0o700)
        old_dir.mkdir(mode=0o700)
        for name in _REPORT_NAMES:
            _write_transaction_text(new_dir / name, contents[name])
            old_content = old_contents[name]
            if old_content is not None:
                _write_transaction_text(old_dir / name, old_content)
        _write_transaction_text(
            new_dir / _REPORT_MANIFEST_NAME,
            manifest_content,
        )
        if old_manifest is not None:
            _write_transaction_text(
                old_dir / _REPORT_MANIFEST_NAME,
                old_manifest,
            )
        records = [
            {
                "path": name,
                "old_present": old_contents[name] is not None,
                "old_sha256": (
                    _sha256_text(old_contents[name])
                    if old_contents[name] is not None
                    else None
                ),
                "new_sha256": _sha256_text(contents[name]),
            }
            for name in _REPORT_NAMES
        ]
        descriptor = {
            "schema_version": 1,
            "spec_id": spec_id,
            "files": records,
            "old_manifest_present": old_manifest is not None,
            "old_manifest_sha256": (
                _sha256_text(old_manifest)
                if old_manifest is not None
                else None
            ),
            "new_manifest_sha256": _sha256_text(manifest_content),
        }
        _write_transaction_text(
            staging / "transaction.json",
            json.dumps(
                descriptor,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
        )
        _fsync_directory(new_dir)
        _fsync_directory(old_dir)
        _fsync_directory(staging)
        atomic_rename_no_replace(staging, transaction)
        return transaction
    finally:
        if os.path.lexists(staging):
            shutil.rmtree(staging)


def _require_transaction_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    return _read_optional_report_text(path) or ""


def _load_report_transaction(
    spec_dir: Path,
    *,
    transaction_path: Path | None = None,
) -> tuple[dict[str, str | None], dict[str, str], str | None, str]:
    transaction = (
        spec_dir / _REPORT_TRANSACTION_NAME
        if transaction_path is None
        else transaction_path
    )
    if transaction.is_symlink() or not transaction.is_dir():
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    if {entry.name for entry in transaction.iterdir()} != {
        "new",
        "old",
        "transaction.json",
    }:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    new_dir = transaction / "new"
    old_dir = transaction / "old"
    if (
        new_dir.is_symlink()
        or not new_dir.is_dir()
        or old_dir.is_symlink()
        or not old_dir.is_dir()
    ):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    try:
        descriptor = loads_strict_json(
            _require_transaction_file(transaction / "transaction.json")
        )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        ) from exc
    expected_keys = {
        "schema_version",
        "spec_id",
        "files",
        "old_manifest_present",
        "old_manifest_sha256",
        "new_manifest_sha256",
    }
    if (
        type(descriptor) is not dict
        or set(descriptor) != expected_keys
        or type(descriptor["schema_version"]) is not int
        or descriptor["schema_version"] != 1
        or descriptor["spec_id"] != spec_dir.name
        or type(descriptor["spec_id"]) is not str
        or type(descriptor["files"]) is not list
        or len(descriptor["files"]) != len(_REPORT_NAMES)
        or type(descriptor["old_manifest_present"]) is not bool
        or type(descriptor["new_manifest_sha256"]) is not str
        or _SHA256.fullmatch(descriptor["new_manifest_sha256"]) is None
    ):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    records: dict[str, dict[str, object]] = {}
    for raw_record in descriptor["files"]:
        if (
            type(raw_record) is not dict
            or set(raw_record)
            != {"path", "old_present", "old_sha256", "new_sha256"}
            or type(raw_record["path"]) is not str
            or raw_record["path"] not in _REPORT_NAMES
            or raw_record["path"] in records
            or type(raw_record["old_present"]) is not bool
            or type(raw_record["new_sha256"]) is not str
            or _SHA256.fullmatch(raw_record["new_sha256"]) is None
            or (
                raw_record["old_present"]
                and (
                    type(raw_record["old_sha256"]) is not str
                    or _SHA256.fullmatch(raw_record["old_sha256"]) is None
                )
            )
            or (
                not raw_record["old_present"]
                and raw_record["old_sha256"] is not None
            )
        ):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        records[raw_record["path"]] = raw_record
    if tuple(sorted(records)) != _REPORT_NAMES:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    new_contents: dict[str, str] = {}
    old_contents: dict[str, str | None] = {}
    expected_new_entries = set(_REPORT_NAMES) | {_REPORT_MANIFEST_NAME}
    expected_old_entries = {
        name
        for name, record in records.items()
        if record["old_present"]
    }
    if descriptor["old_manifest_present"]:
        expected_old_entries.add(_REPORT_MANIFEST_NAME)
    if {entry.name for entry in new_dir.iterdir()} != expected_new_entries or {
        entry.name for entry in old_dir.iterdir()
    } != expected_old_entries:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    for name, record in records.items():
        new_content = _require_transaction_file(new_dir / name)
        if _sha256_text(new_content) != record["new_sha256"]:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        new_contents[name] = new_content
        if record["old_present"]:
            old_content = _require_transaction_file(old_dir / name)
            if _sha256_text(old_content) != record["old_sha256"]:
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            old_contents[name] = old_content
        else:
            old_contents[name] = None
    new_manifest = _require_transaction_file(
        new_dir / _REPORT_MANIFEST_NAME
    )
    if _sha256_text(new_manifest) != descriptor["new_manifest_sha256"]:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    expected_manifest, _digest = _report_manifest(
        spec_id=spec_dir.name,
        contents=new_contents,
    )
    if new_manifest != expected_manifest:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    old_manifest: str | None = None
    if descriptor["old_manifest_present"]:
        if (
            type(descriptor["old_manifest_sha256"]) is not str
            or _SHA256.fullmatch(descriptor["old_manifest_sha256"]) is None
        ):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        old_manifest = _require_transaction_file(
            old_dir / _REPORT_MANIFEST_NAME
        )
        if _sha256_text(old_manifest) != descriptor["old_manifest_sha256"]:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
    elif descriptor["old_manifest_sha256"] is not None:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    return old_contents, new_contents, old_manifest, new_manifest


def _unlink_report_file(path: Path) -> None:
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise RetargetMemoryError(
                "replacement memory report target is not a regular file"
            )
        os.unlink(path)
        _fsync_directory(path.parent)


def _detached_cleanup_paths(spec_dir: Path) -> list[Path]:
    return sorted(
        (
            entry
            for entry in spec_dir.iterdir()
            if entry.name.startswith(_REPORT_DETACHED_PREFIX)
        ),
        key=lambda entry: entry.name,
    )


def _report_set_matches(
    spec_dir: Path,
    *,
    contents: Mapping[str, str | None],
    manifest: str | None,
) -> bool:
    return (
        tuple(sorted(contents)) == _REPORT_NAMES
        and all(
            _read_optional_report_text(spec_dir / name) == content
            for name, content in contents.items()
        )
        and _read_optional_report_text(
            spec_dir / _REPORT_MANIFEST_NAME
        )
        == manifest
    )


def _cleanup_live_records(
    contents: Mapping[str, str | None],
) -> list[dict[str, object]]:
    return [
        {
            "path": name,
            "present": contents[name] is not None,
            "sha256": (
                _sha256_text(contents[name])
                if contents[name] is not None
                else None
            ),
        }
        for name in _REPORT_NAMES
    ]


def _report_cleanup_name(
    *,
    transaction_sha256: str,
    expected_live: str,
    device: int | None = None,
    inode: int | None = None,
) -> str:
    identity = "" if device is None or inode is None else f":{device}:{inode}"
    cleanup_key = hashlib.sha256(
        f"{transaction_sha256}:{expected_live}{identity}".encode("ascii")
    ).hexdigest()
    return f"{_REPORT_DETACHED_PREFIX}{cleanup_key}"


def _report_completed_receipt_name(content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return f"{_REPORT_COMPLETED_RECEIPT_PREFIX}{digest}.json"


def _parse_report_cleanup_receipt(content: str) -> dict[str, object]:
    try:
        loaded = loads_strict_json(content)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        ) from exc
    expected_keys = {
        "schema_version",
        "cleanup_name",
        "transaction_sha256",
        "expected_live",
        "device",
        "inode",
        "files",
        "manifest_present",
        "manifest_sha256",
    }
    if (
        type(loaded) is not dict
        or set(loaded) != expected_keys
        or type(loaded["schema_version"]) is not int
        or loaded["schema_version"] != 1
        or type(loaded["cleanup_name"]) is not str
        or re.fullmatch(
            re.escape(_REPORT_DETACHED_PREFIX) + r"[0-9a-f]{64}",
            loaded["cleanup_name"],
        )
        is None
        or type(loaded["transaction_sha256"]) is not str
        or _SHA256.fullmatch(loaded["transaction_sha256"]) is None
        or type(loaded["expected_live"]) is not str
        or loaded["expected_live"] not in {"old", "new"}
        or type(loaded["device"]) is not int
        or loaded["device"] < 0
        or type(loaded["inode"]) is not int
        or loaded["inode"] <= 0
        or type(loaded["files"]) is not list
        or len(loaded["files"]) != len(_REPORT_NAMES)
        or type(loaded["manifest_present"]) is not bool
    ):
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    legacy_name = _report_cleanup_name(
        transaction_sha256=loaded["transaction_sha256"],
        expected_live=loaded["expected_live"],
    )
    identity_name = _report_cleanup_name(
        transaction_sha256=loaded["transaction_sha256"],
        expected_live=loaded["expected_live"],
        device=loaded["device"],
        inode=loaded["inode"],
    )
    if loaded["cleanup_name"] not in {legacy_name, identity_name}:
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    records: dict[str, dict[str, object]] = {}
    for raw_record in loaded["files"]:
        if (
            type(raw_record) is not dict
            or set(raw_record) != {"path", "present", "sha256"}
            or type(raw_record["path"]) is not str
            or raw_record["path"] not in _REPORT_NAMES
            or raw_record["path"] in records
            or type(raw_record["present"]) is not bool
            or (
                raw_record["present"]
                and (
                    type(raw_record["sha256"]) is not str
                    or _SHA256.fullmatch(raw_record["sha256"]) is None
                )
            )
            or (
                not raw_record["present"]
                and raw_record["sha256"] is not None
            )
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup receipt is invalid"
            )
        records[raw_record["path"]] = raw_record
    if tuple(sorted(records)) != _REPORT_NAMES:
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    if (
        loaded["manifest_present"]
        and (
            type(loaded["manifest_sha256"]) is not str
            or _SHA256.fullmatch(loaded["manifest_sha256"]) is None
        )
    ) or (
        not loaded["manifest_present"]
        and loaded["manifest_sha256"] is not None
    ):
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    return loaded


def _load_report_cleanup_receipt(spec_dir: Path) -> dict[str, object] | None:
    receipt_path = spec_dir / _REPORT_CLEANUP_RECEIPT_NAME
    if not os.path.lexists(receipt_path):
        return None
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    return _parse_report_cleanup_receipt(
        _read_optional_report_text(receipt_path) or ""
    )


def _cleanup_receipt_live_matches(
    spec_dir: Path,
    receipt: Mapping[str, object],
) -> bool:
    for record in receipt["files"]:  # type: ignore[index]
        name = record["path"]
        content = _read_optional_report_text(spec_dir / name)
        if record["present"]:
            if content is None or _sha256_text(content) != record["sha256"]:
                return False
        elif content is not None:
            return False
    manifest = _read_optional_report_text(
        spec_dir / _REPORT_MANIFEST_NAME
    )
    if receipt["manifest_present"]:
        return (
            manifest is not None
            and _sha256_text(manifest) == receipt["manifest_sha256"]
        )
    return manifest is None


def _cleanup_entry_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (stat.S_IFMT(metadata.st_mode), metadata.st_dev, metadata.st_ino)


def _canonical_cleanup_receipt(receipt: Mapping[str, object]) -> str:
    return (
        json.dumps(
            dict(receipt),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _completed_receipt_paths(spec_dir: Path) -> list[Path]:
    return sorted(
        (
            entry
            for entry in spec_dir.iterdir()
            if entry.name.startswith(_REPORT_COMPLETED_RECEIPT_PREFIX)
        ),
        key=lambda entry: entry.name,
    )


def _cleanup_receipt_matches_transaction(
    receipt: Mapping[str, object],
    *,
    old_contents: Mapping[str, str | None],
    new_contents: Mapping[str, str],
    old_manifest: str | None,
    new_manifest: str,
) -> bool:
    expected_contents: Mapping[str, str | None]
    if receipt["expected_live"] == "new":
        expected_contents = new_contents
        expected_manifest = new_manifest
    else:
        expected_contents = old_contents
        expected_manifest = old_manifest
    return (
        _type_exact_equal(
            receipt["files"],
            _cleanup_live_records(expected_contents),
        )
        and receipt["manifest_present"] is (expected_manifest is not None)
        and receipt["manifest_sha256"]
        == (
            _sha256_text(expected_manifest)
            if expected_manifest is not None
            else None
        )
    )


def _validate_completed_report_archives(
    spec_dir: Path,
    *,
    active_receipt: Mapping[str, object] | None,
) -> None:
    completed_paths = _completed_receipt_paths(spec_dir)
    if len(completed_paths) > _MAX_COMPLETED_REPORT_TRANSACTIONS:
        raise RetargetMemoryError(
            "replacement memory completed transaction history is full"
        )
    completed: dict[str, dict[str, object]] = {}
    for receipt_path in completed_paths:
        content = _read_optional_report_text(receipt_path)
        if (
            content is None
            or receipt_path.name != _report_completed_receipt_name(content)
        ):
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipt is invalid"
            )
        receipt = _parse_report_cleanup_receipt(content)
        cleanup_name = receipt["cleanup_name"]
        if type(cleanup_name) is not str or cleanup_name in completed:
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipts conflict"
            )
        completed[cleanup_name] = receipt

    detached = {path.name: path for path in _detached_cleanup_paths(spec_dir)}
    active_name = (
        active_receipt["cleanup_name"]
        if active_receipt is not None
        else None
    )
    if type(active_name) is str and active_name in completed:
        raise RetargetMemoryError(
            "replacement memory cleanup evidence is duplicated"
        )
    expected_detached = set(completed)
    if type(active_name) is str and active_name in detached:
        expected_detached.add(active_name)
    if set(detached) != expected_detached:
        raise RetargetMemoryError(
            "replacement memory detached cleanup is unauthenticated"
        )

    for cleanup_name, receipt in completed.items():
        transaction = detached[cleanup_name]
        if transaction.is_symlink() or not transaction.is_dir():
            raise RetargetMemoryError(
                "replacement memory completed journal is invalid"
            )
        identity = transaction.stat(follow_symlinks=False)
        if (
            identity.st_dev != receipt["device"]
            or identity.st_ino != receipt["inode"]
            or _sha256_text(
                _require_transaction_file(transaction / "transaction.json")
            )
            != receipt["transaction_sha256"]
        ):
            raise RetargetMemoryError(
                "replacement memory completed journal identity changed"
            )
        old_contents, new_contents, old_manifest, new_manifest = (
            _load_report_transaction(
                spec_dir,
                transaction_path=transaction,
            )
        )
        if not _cleanup_receipt_matches_transaction(
            receipt,
            old_contents=old_contents,
            new_contents=new_contents,
            old_manifest=old_manifest,
            new_manifest=new_manifest,
        ):
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipt is inconsistent"
            )


def _atomic_rename_no_replace_at(
    parent_fd: int,
    source_name: str,
    destination_name: str,
) -> None:
    if (
        source_name in {"", ".", ".."}
        or destination_name in {"", ".", ".."}
        or "/" in source_name
        or "/" in destination_name
    ):
        raise RetargetMemoryError(
            "replacement memory archive name is invalid"
        )
    libc = ctypes.CDLL(None, use_errno=True)
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
        arguments = (
            parent_fd,
            os.fsencode(source_name),
            parent_fd,
            os.fsencode(destination_name),
            0x00000004,
        )
    elif sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        function = libc.renameat2
        function.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        function.restype = ctypes.c_int
        arguments = (
            parent_fd,
            os.fsencode(source_name),
            parent_fd,
            os.fsencode(destination_name),
            0x00000001,
        )
    else:
        raise RetargetMemoryError(
            "replacement memory atomic archive is unsupported"
        )
    ctypes.set_errno(0)
    if function(*arguments) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), destination_name)
    os.fsync(parent_fd)


def _open_entry_at(parent_fd: int, name: str, *, directory: bool) -> int:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not no_follow or (directory and not directory_flag):
        raise RetargetMemoryError(
            "replacement memory descriptor-bound archive is unsupported"
        )
    flags = os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0)
    if directory:
        flags |= directory_flag | getattr(os, "O_NONBLOCK", 0)
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory cleanup evidence is unavailable"
        ) from exc


def _read_regular_entry_at(parent_fd: int, name: str) -> tuple[int, str]:
    descriptor = _open_entry_at(parent_fd, name, directory=False)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_REPORT_BYTES:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt is invalid"
            )
        chunks: list[bytes] = []
        remaining = _MAX_REPORT_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        if remaining == 0:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt is oversized"
            )
        try:
            content = b"".join(chunks).decode("utf-8")
        except UnicodeError as exc:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt is invalid"
            ) from exc
        return descriptor, content
    except BaseException:
        os.close(descriptor)
        raise


def _retire_report_cleanup_receipt(
    parent_fd: int,
    *,
    source_name: str,
    receipt: Mapping[str, object],
) -> None:
    cleanup_name = receipt["cleanup_name"]
    if type(cleanup_name) is not str:
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    journal_fd = _open_entry_at(parent_fd, source_name, directory=True)
    receipt_fd: int | None = None
    try:
        journal_identity = os.fstat(journal_fd)
        if (
            journal_identity.st_dev != receipt["device"]
            or journal_identity.st_ino != receipt["inode"]
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction identity changed"
            )
        if source_name != cleanup_name:
            _atomic_rename_no_replace_at(parent_fd, source_name, cleanup_name)
        archived_identity = os.stat(
            cleanup_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if _cleanup_entry_identity(archived_identity) != _cleanup_entry_identity(
            journal_identity
        ):
            raise RetargetMemoryError(
                "replacement memory completed journal identity changed"
            )

        receipt_content = _canonical_cleanup_receipt(receipt)
        receipt_fd, persisted_content = _read_regular_entry_at(
            parent_fd,
            _REPORT_CLEANUP_RECEIPT_NAME,
        )
        if persisted_content != receipt_content:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt changed"
            )
        receipt_identity = os.fstat(receipt_fd)
        archived_receipt_name = _report_completed_receipt_name(receipt_content)
        _atomic_rename_no_replace_at(
            parent_fd,
            _REPORT_CLEANUP_RECEIPT_NAME,
            archived_receipt_name,
        )
        archived_receipt_identity = os.stat(
            archived_receipt_name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if _cleanup_entry_identity(
            archived_receipt_identity
        ) != _cleanup_entry_identity(receipt_identity):
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipt identity changed"
            )
    finally:
        if receipt_fd is not None:
            os.close(receipt_fd)
        os.close(journal_fd)


def _finish_detached_report_cleanup(
    spec_dir: Path,
    *,
    receipt: Mapping[str, object],
) -> None:
    cleanup_name = receipt["cleanup_name"]
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    no_follow_flag = getattr(os, "O_NOFOLLOW", 0)
    if not directory_flag or not no_follow_flag:
        raise RetargetMemoryError(
            "replacement memory descriptor-bound cleanup is unsupported"
        )
    parent_flags = (
        os.O_RDONLY
        | directory_flag
        | no_follow_flag
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        parent_fd = os.open(spec_dir, parent_flags)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory cleanup parent is invalid"
        ) from exc
    try:
        transaction_present = True
        cleanup_present = True
        try:
            os.stat(
                _REPORT_TRANSACTION_NAME,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            transaction_present = False
        try:
            os.stat(
                cleanup_name,  # type: ignore[arg-type]
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            cleanup_present = False
        if transaction_present == cleanup_present:
            raise RetargetMemoryError(
                "replacement memory cleanup journal is missing or duplicated"
            )
        _retire_report_cleanup_receipt(
            parent_fd,
            source_name=(
                _REPORT_TRANSACTION_NAME if transaction_present else cleanup_name
            ),  # type: ignore[arg-type]
            receipt=receipt,
        )
    finally:
        os.close(parent_fd)


def _retire_detached_report_cleanup(spec_dir: Path) -> None:
    receipt = _load_report_cleanup_receipt(spec_dir)
    _validate_completed_report_archives(
        spec_dir,
        active_receipt=receipt,
    )
    if receipt is None:
        return
    if not _cleanup_receipt_live_matches(spec_dir, receipt):
        raise RetargetMemoryError(
            "replacement memory cleanup live report set changed"
        )
    transaction = spec_dir / _REPORT_TRANSACTION_NAME
    cleanup_path = spec_dir / receipt["cleanup_name"]  # type: ignore[operator]
    if os.path.lexists(transaction) and os.path.lexists(cleanup_path):
        raise RetargetMemoryError(
            "replacement memory cleanup has multiple active artifacts"
        )
    if os.path.lexists(transaction):
        if transaction.is_symlink() or not transaction.is_dir():
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        identity = transaction.stat(follow_symlinks=False)
        if (
            identity.st_dev != receipt["device"]
            or identity.st_ino != receipt["inode"]
            or _sha256_text(
                _require_transaction_file(transaction / "transaction.json")
            )
            != receipt["transaction_sha256"]
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction identity changed"
            )
        old_contents, new_contents, old_manifest, new_manifest = (
            _load_report_transaction(spec_dir)
        )
        expected_contents = (
            new_contents if receipt["expected_live"] == "new" else old_contents
        )
        expected_manifest = (
            new_manifest if receipt["expected_live"] == "new" else old_manifest
        )
        if not _report_set_matches(
            spec_dir,
            contents=expected_contents,
            manifest=expected_manifest,
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction state is inconsistent"
            )
    elif os.path.lexists(cleanup_path):
        if cleanup_path.is_symlink() or not cleanup_path.is_dir():
            raise RetargetMemoryError(
                "replacement memory detached cleanup path is invalid"
            )
        identity = cleanup_path.stat(follow_symlinks=False)
        if (
            identity.st_dev != receipt["device"]
            or identity.st_ino != receipt["inode"]
            or _sha256_text(
                _require_transaction_file(cleanup_path / "transaction.json")
            )
            != receipt["transaction_sha256"]
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction identity changed"
            )
        old_contents, new_contents, old_manifest, new_manifest = (
            _load_report_transaction(
                spec_dir,
                transaction_path=cleanup_path,
            )
        )
        if not _cleanup_receipt_matches_transaction(
            receipt,
            old_contents=old_contents,
            new_contents=new_contents,
            old_manifest=old_manifest,
            new_manifest=new_manifest,
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction state is inconsistent"
            )
    _finish_detached_report_cleanup(spec_dir, receipt=receipt)


def _remove_report_transaction(
    spec_dir: Path,
    *,
    expected_live: str,
) -> None:
    _retire_detached_report_cleanup(spec_dir)
    transaction = spec_dir / _REPORT_TRANSACTION_NAME
    old_contents, new_contents, old_manifest, new_manifest = (
        _load_report_transaction(spec_dir)
    )
    if expected_live == "new":
        expected_contents: Mapping[str, str | None] = new_contents
        expected_manifest = new_manifest
    elif expected_live == "old":
        expected_contents = old_contents
        expected_manifest = old_manifest
    else:
        raise RetargetMemoryError(
            "replacement memory cleanup state is invalid"
        )
    if not _report_set_matches(
        spec_dir,
        contents=expected_contents,
        manifest=expected_manifest,
    ):
        raise RetargetMemoryError(
            "replacement memory cleanup live report set is inconsistent"
        )
    transaction_identity = transaction.stat(follow_symlinks=False)
    transaction_digest = _sha256_text(
        _require_transaction_file(transaction / "transaction.json")
    )
    cleanup_name = _report_cleanup_name(
        transaction_sha256=transaction_digest,
        expected_live=expected_live,
        device=transaction_identity.st_dev,
        inode=transaction_identity.st_ino,
    )
    manifest_present = expected_manifest is not None
    receipt = {
        "schema_version": 1,
        "cleanup_name": cleanup_name,
        "transaction_sha256": transaction_digest,
        "expected_live": expected_live,
        "device": transaction_identity.st_dev,
        "inode": transaction_identity.st_ino,
        "files": _cleanup_live_records(expected_contents),
        "manifest_present": manifest_present,
        "manifest_sha256": (
            _sha256_text(expected_manifest) if expected_manifest is not None else None
        ),
    }
    _write_text_durable_atomic(
        spec_dir / _REPORT_CLEANUP_RECEIPT_NAME,
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )
    _finish_detached_report_cleanup(spec_dir, receipt=receipt)


def _recover_report_transaction(spec_dir: Path) -> None:
    _retire_detached_report_cleanup(spec_dir)
    transaction = spec_dir / _REPORT_TRANSACTION_NAME
    if not os.path.lexists(transaction):
        return
    old_contents, new_contents, old_manifest, new_manifest = (
        _load_report_transaction(spec_dir)
    )
    live_manifest = _read_optional_report_text(
        spec_dir / _REPORT_MANIFEST_NAME
    )
    if live_manifest == new_manifest:
        if all(
            _read_optional_report_text(spec_dir / name) == content
            for name, content in new_contents.items()
        ):
            _remove_report_transaction(spec_dir, expected_live="new")
            return
        raise RetargetMemoryError(
            "committed replacement memory report set is inconsistent"
        )
    if live_manifest not in {None, old_manifest}:
        raise RetargetMemoryError(
            "replacement memory report transaction postimage is inconsistent"
        )
    for name in _REPORT_NAMES:
        live = _read_optional_report_text(spec_dir / name)
        if live not in {old_contents[name], new_contents[name]}:
            raise RetargetMemoryError(
                "replacement memory report transaction postimage is inconsistent"
            )
    _unlink_report_file(spec_dir / _REPORT_MANIFEST_NAME)
    for name in _REPORT_NAMES:
        target = spec_dir / name
        old_content = old_contents[name]
        if old_content is None:
            _unlink_report_file(target)
        else:
            _write_text_durable_atomic(target, old_content)
    if old_manifest is not None:
        _write_text_durable_atomic(
            spec_dir / _REPORT_MANIFEST_NAME,
            old_manifest,
        )
    _remove_report_transaction(spec_dir, expected_live="old")


def _publish_report_set(
    spec_dir: Path,
    *,
    spec_id: str,
    contents: dict[str, str],
) -> str:
    _recover_report_transaction(spec_dir)
    _preflight_report_set(spec_dir)
    manifest_content, report_set_digest = _report_manifest(
        spec_id=spec_id,
        contents=contents,
    )
    if (
        _read_optional_report_text(spec_dir / _REPORT_MANIFEST_NAME)
        == manifest_content
        and all(
            _read_optional_report_text(spec_dir / name) == content
            for name, content in contents.items()
        )
    ):
        return report_set_digest
    _stage_report_transaction(
        spec_dir,
        spec_id=spec_id,
        contents=contents,
        manifest_content=manifest_content,
    )
    try:
        _unlink_report_file(spec_dir / _REPORT_MANIFEST_NAME)
        for name in _REPORT_NAMES:
            _write_text_durable_atomic(spec_dir / name, contents[name])
        _write_text_durable_atomic(
            spec_dir / _REPORT_MANIFEST_NAME,
            manifest_content,
        )
        if any(
            _read_optional_report_text(spec_dir / name) != contents[name]
            for name in _REPORT_NAMES
        ) or _read_optional_report_text(
            spec_dir / _REPORT_MANIFEST_NAME
        ) != manifest_content:
            raise RetargetMemoryError(
                "replacement memory report set postimage is inconsistent"
            )
    except (Exception, SystemExit):
        _recover_report_transaction(spec_dir)
        raise
    _remove_report_transaction(spec_dir, expected_live="new")
    return report_set_digest


def refresh_retarget_spec_memory(
    project_root: Path,
    spec_dir: Path,
) -> RetargetMemoryReceipt:
    """Mine, clean, audit, and durably report replacement spec memory."""
    root = project_root.resolve()
    resolved_spec_dir = spec_dir.resolve()
    try:
        relative = resolved_spec_dir.relative_to(root)
    except ValueError as exc:
        raise RetargetMemoryError(
            "replacement memory spec directory is outside the project"
        ) from exc
    if len(relative.parts) != 2 or relative.parts[0] != "specs":
        raise RetargetMemoryError(
            "replacement memory requires a canonical spec directory"
        )
    try:
        spec_id = _require_spec_id(relative.parts[1])
    except ValueError as exc:
        raise RetargetMemoryError("invalid retarget spec identity") from exc
    configured_wing = _configured_mempalace_wing(root)
    if configured_wing is None:
        return RetargetMemoryReceipt(
            status="not_applicable",
            spec_id=spec_id,
            deleted_count=0,
            deleted_ids=(),
            drawer_set_digest=_digest_ids(()),
            mine_status="not_applicable",
            audit_status="not_applicable",
        )
    try:
        identity_adapter = create_requirement_memory_adapter(
            root,
            run_id="retarget-finalize-identity",
        )
        adapter_name, wing, palace_path = _adapter_identity(
            identity_adapter,
            configured_wing=configured_wing,
        )
    except RetargetMemoryError:
        raise
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "configured replacement memory adapter is unavailable"
        ) from exc

    try:
        mine = mine_spec_requirements(
            root,
            resolved_spec_dir,
            run_id="retarget-finalize",
        )
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "replacement memory mine is unavailable"
        ) from exc
    mine_status = getattr(mine, "status", None)
    if mine_status != "complete":
        raise RetargetMemoryError(
            f"replacement memory mine is {mine_status or 'invalid'}",
            receipt=_receipt(
                status="fail",
                spec_id=spec_id,
                deleted_ids=(),
                drawer_ids=(),
                adapter=adapter_name,
                wing=wing,
                palace_path=palace_path,
                failure_code="retarget_memory_mine_incomplete",
                mine_status=(
                    mine_status if type(mine_status) is str and mine_status else "invalid"
                ),
            ),
        )
    _require_refresh_report_identity(
        mine,
        label="mine",
        spec_id=spec_id,
        spec_dir=resolved_spec_dir,
        wing=wing,
        palace_path=palace_path,
    )
    if (
        type(mine) is not SpecMemoryMineReport
        or getattr(mine, "schema_version", None) != 1
        or type(getattr(mine, "schema_version", None)) is not int
        or type(getattr(mine, "errors", None)) is not list
        or getattr(mine, "errors") != []
    ):
        raise RetargetMemoryError(
            "replacement memory mine receipt is inconsistent"
        )
    expected_ids = _strict_report_ids(
        getattr(mine, "expected_drawer_ids", None),
        label="mine expected drawers",
    )
    drawer_ids = _strict_report_ids(
        getattr(mine, "drawer_ids", None),
        label="mine drawers",
    )
    mine_counts = tuple(
        getattr(mine, field, None)
        for field in (
            "expected_count",
            "written_count",
            "adopted_count",
            "skipped_count",
            "failed_count",
            "drifted_count",
            "unavailable_count",
        )
    )
    if (
        any(type(value) is not int or value < 0 for value in mine_counts)
        or mine_counts[0] != len(expected_ids)
        or drawer_ids != expected_ids
        or mine_counts[1] + mine_counts[2] != mine_counts[0]
        or any(mine_counts[index] != 0 for index in range(3, 7))
    ):
        raise RetargetMemoryError(
            "replacement memory mine receipt is inconsistent"
        )

    try:
        cleanup = cleanup_stale_spec_memory(root, resolved_spec_dir)
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "replacement memory cleanup is unavailable"
        ) from exc
    _require_refresh_report_identity(
        cleanup,
        label="cleanup",
        spec_id=spec_id,
        spec_dir=resolved_spec_dir,
        wing=wing,
        palace_path=palace_path,
    )
    deleted_ids = _strict_report_ids(
        getattr(cleanup, "deleted_ids", None),
        label="cleanup deleted drawers",
    )
    cleanup_count = getattr(cleanup, "deleted_count", None)
    if (
        type(cleanup) is not SpecMemoryCleanupReport
        or getattr(cleanup, "schema_version", None) != 1
        or type(getattr(cleanup, "schema_version", None)) is not int
        or type(cleanup_count) is not int
        or cleanup_count != len(deleted_ids)
        or set(deleted_ids).intersection(drawer_ids)
    ):
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is inconsistent"
        )

    try:
        audit = audit_spec_memory(
            root,
            resolved_spec_dir,
            probe_retrieval=True,
        )
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "replacement memory audit is unavailable",
            receipt=_receipt(
                status="fail",
                spec_id=spec_id,
                deleted_ids=deleted_ids,
                drawer_ids=drawer_ids,
                adapter=adapter_name,
                wing=wing,
                palace_path=palace_path,
                failure_code="retarget_memory_audit_unavailable",
                mine_status="complete",
                audit_status="unavailable",
            ),
        ) from exc
    audit_status = getattr(audit, "status", None)
    if audit_status not in {"pass", "warn"}:
        checked_audit_status = (
            audit_status
            if type(audit_status) is str and audit_status
            else "invalid"
        )
        raise RetargetMemoryError(
            f"replacement memory audit is {checked_audit_status}",
            receipt=_receipt(
                status="fail",
                spec_id=spec_id,
                deleted_ids=deleted_ids,
                drawer_ids=drawer_ids,
                adapter=adapter_name,
                wing=wing,
                palace_path=palace_path,
                failure_code="retarget_memory_audit_unacceptable",
                mine_status="complete",
                audit_status=checked_audit_status,
            ),
        )
    _require_refresh_report_identity(
        audit,
        label="audit",
        spec_id=spec_id,
        spec_dir=resolved_spec_dir,
        wing=wing,
        palace_path=palace_path,
    )
    audit_status = _validate_refresh_audit(
        audit,
        expected_count=len(expected_ids),
    )

    mine_serializer = getattr(mine, "to_dict", None)
    if not callable(mine_serializer):
        raise RetargetMemoryError(
            "replacement memory mine receipt is inconsistent"
        )
    mine_payload = mine_serializer()
    if type(mine_payload) is not dict:
        raise RetargetMemoryError(
            "replacement memory mine receipt is inconsistent"
        )
    try:
        report_set_digest = _publish_report_set(
            resolved_spec_dir,
            spec_id=spec_id,
            contents={
                "mempalace-mine.json": json.dumps(
                mine_payload,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
                + "\n",
                "mempalace-audit.json": json.dumps(
                    audit.to_dict(),
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
                "mempalace-audit.md": render_audit_markdown(audit),
            },
        )
    except (Exception, SystemExit) as exc:
        detail = f": {exc}" if isinstance(exc, RetargetMemoryError) else ""
        raise RetargetMemoryError(
            f"replacement memory report write failed{detail}",
            receipt=_receipt(
                status="fail",
                spec_id=spec_id,
                deleted_ids=deleted_ids,
                drawer_ids=drawer_ids,
                adapter=adapter_name,
                wing=wing,
                palace_path=palace_path,
                failure_code="retarget_memory_report_write_failed",
                mine_status="complete",
                audit_status=audit_status,
            ),
        ) from exc
    return _receipt(
        status="pass",
        spec_id=spec_id,
        deleted_ids=deleted_ids,
        drawer_ids=drawer_ids,
        adapter=adapter_name,
        wing=wing,
        palace_path=palace_path,
        mine_status="complete",
        audit_status=audit_status,
        report_set_digest=report_set_digest,
    )
