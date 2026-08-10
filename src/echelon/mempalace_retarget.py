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
import secrets
import stat
import sys
from typing import Iterable, Mapping

from echelon.mempalace_audit import (
    MAX_AUDIT_SCAN_ROWS,
    SpecMemoryAuditReport,
    SpecMemoryCleanupReport,
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
    config_path = root / ".echelon" / "config.yml"
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
    expected_receipt_identity: tuple[int, int, int] | None = None,
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
        if (
            expected_receipt_identity is not None
            and _cleanup_entry_identity(receipt_identity)
            != expected_receipt_identity
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup receipt identity changed"
            )
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


@dataclass(frozen=True)
class _BoundReportTransaction:
    old_contents: dict[str, str | None]
    new_contents: dict[str, str]
    old_manifest: str | None
    new_manifest: str
    records: dict[str, dict[str, object]]
    journal_identity: tuple[int, int, int]

    def __iter__(self):
        yield self.old_contents
        yield self.new_contents
        yield self.old_manifest
        yield self.new_manifest


def _identity_record(metadata: os.stat_result) -> list[int]:
    return [stat.S_IFMT(metadata.st_mode), metadata.st_dev, metadata.st_ino]


def _strict_identity_record(value: object) -> tuple[int, int, int]:
    if (
        type(value) is not list
        or len(value) != 3
        or any(type(part) is not int for part in value)
        or value[0] not in {stat.S_IFREG, stat.S_IFDIR}
        or value[1] < 0
        or value[2] <= 0
    ):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    return (value[0], value[1], value[2])


def _open_report_parent(spec_dir: Path) -> tuple[int, tuple[int, int, int]]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NOFOLLOW", 0):
        raise RetargetMemoryError(
            "replacement memory descriptor-bound publication is unsupported"
        )
    try:
        descriptor = os.open(spec_dir, flags)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory report parent is invalid"
        ) from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise RetargetMemoryError(
            "replacement memory report parent is invalid"
        )
    return descriptor, _cleanup_entry_identity(metadata)


def _require_report_parent_binding(
    spec_dir: Path,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
    *,
    boundary: str,
) -> None:
    del boundary
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        public_fd = os.open(spec_dir, flags)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory report parent identity changed"
        ) from exc
    try:
        if _cleanup_entry_identity(os.fstat(public_fd)) != parent_identity:
            raise RetargetMemoryError(
                "replacement memory report parent identity changed"
            )
        if _cleanup_entry_identity(os.fstat(parent_fd)) != parent_identity:
            raise RetargetMemoryError(
                "replacement memory report parent identity changed"
            )
    finally:
        os.close(public_fd)


def _entry_stat_at(parent_fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory report entry is unavailable"
        ) from exc


def _require_open_entry_binding(
    parent_fd: int,
    name: str,
    metadata: os.stat_result,
    *,
    label: str,
) -> None:
    current = _entry_stat_at(parent_fd, name)
    if (
        current is None
        or _cleanup_entry_identity(current) != _cleanup_entry_identity(metadata)
    ):
        raise RetargetMemoryError(f"replacement memory {label} identity changed")


def _directory_names_at(directory_fd: int) -> set[str]:
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        ) from exc
    if any(name in {"", ".", ".."} or "/" in name for name in names):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    return set(names)


def _read_text_entry_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
) -> tuple[str, os.stat_result]:
    descriptor, content = _read_regular_entry_at(parent_fd, name)
    try:
        metadata = os.fstat(descriptor)
        _require_open_entry_binding(
            parent_fd,
            name,
            metadata,
            label=label,
        )
        return content, metadata
    finally:
        os.close(descriptor)


def _read_optional_report_text_at(
    parent_fd: int,
    name: str,
) -> tuple[str | None, tuple[int, int, int] | None]:
    metadata = _entry_stat_at(parent_fd, name)
    if metadata is None:
        return None, None
    if not stat.S_ISREG(metadata.st_mode):
        raise RetargetMemoryError(
            "replacement memory report target is not a regular file"
        )
    content, opened = _read_text_entry_at(parent_fd, name, label="report target")
    return content, _cleanup_entry_identity(opened)


def _write_transaction_text_at(
    directory_fd: int,
    name: str,
    content: str,
    *,
    mode: int = 0o600,
) -> tuple[int, int, int]:
    encoded = content.encode("utf-8")
    if len(encoded) > _MAX_REPORT_BYTES:
        raise RetargetMemoryError("replacement memory report is oversized")
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(name, flags, mode, dir_fd=directory_fd)
    except OSError as exc:
        raise RetargetMemoryError(
            "replacement memory report staging entry is invalid"
        ) from exc
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError(errno.EIO, "short report transaction write")
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    _require_open_entry_binding(
        directory_fd,
        name,
        metadata,
        label="report staging entry",
    )
    return _cleanup_entry_identity(metadata)


def _atomic_rename_no_replace_between(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> None:
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
            source_fd,
            os.fsencode(source_name),
            destination_fd,
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
            source_fd,
            os.fsencode(source_name),
            destination_fd,
            os.fsencode(destination_name),
            0x00000001,
        )
    else:
        raise RetargetMemoryError(
            "replacement memory atomic publication is unsupported"
        )
    ctypes.set_errno(0)
    if function(*arguments) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), destination_name)
    os.fsync(source_fd)
    if destination_fd != source_fd:
        os.fsync(destination_fd)


def _atomic_exchange_at(
    left_fd: int,
    left_name: str,
    right_fd: int,
    right_name: str,
) -> None:
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
            left_fd,
            os.fsencode(left_name),
            right_fd,
            os.fsencode(right_name),
            0x00000002,
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
            left_fd,
            os.fsencode(left_name),
            right_fd,
            os.fsencode(right_name),
            0x00000002,
        )
    else:
        raise RetargetMemoryError(
            "replacement memory atomic exchange is unsupported"
        )
    ctypes.set_errno(0)
    if function(*arguments) != 0:
        error_number = ctypes.get_errno() or errno.EIO
        raise OSError(error_number, os.strerror(error_number), right_name)
    os.fsync(left_fd)
    if right_fd != left_fd:
        os.fsync(right_fd)


def _open_transaction_child(journal_fd: int, name: str) -> int:
    return _open_entry_at(journal_fd, name, directory=True)


def _transaction_entry_names() -> tuple[str, ...]:
    return (*_REPORT_NAMES, _REPORT_MANIFEST_NAME)


def _parse_legacy_bound_report_transaction(
    *,
    spec_id: str,
    journal_fd: int,
) -> _BoundReportTransaction:
    new_fd: int | None = None
    old_fd: int | None = None
    try:
        new_fd = _open_transaction_child(journal_fd, "new")
        old_fd = _open_transaction_child(journal_fd, "old")
        descriptor_text, _metadata = _read_text_entry_at(
            journal_fd,
            "transaction.json",
            label="report transaction descriptor",
        )
        try:
            descriptor = loads_strict_json(descriptor_text)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            ) from exc
        if (
            type(descriptor) is not dict
            or set(descriptor)
            != {
                "schema_version",
                "spec_id",
                "files",
                "old_manifest_present",
                "old_manifest_sha256",
                "new_manifest_sha256",
            }
            or descriptor["schema_version"] != 1
            or type(descriptor["schema_version"]) is not int
            or descriptor["spec_id"] != spec_id
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
        for raw in descriptor["files"]:
            if (
                type(raw) is not dict
                or set(raw)
                != {"path", "old_present", "old_sha256", "new_sha256"}
                or type(raw["path"]) is not str
                or raw["path"] not in _REPORT_NAMES
                or raw["path"] in records
                or type(raw["old_present"]) is not bool
                or type(raw["new_sha256"]) is not str
                or _SHA256.fullmatch(raw["new_sha256"]) is None
                or (
                    raw["old_present"]
                    and (
                        type(raw["old_sha256"]) is not str
                        or _SHA256.fullmatch(raw["old_sha256"]) is None
                    )
                )
                or (not raw["old_present"] and raw["old_sha256"] is not None)
            ):
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            records[raw["path"]] = raw
        if tuple(sorted(records)) != _REPORT_NAMES:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        expected_new = set(_REPORT_NAMES) | {_REPORT_MANIFEST_NAME}
        expected_old = {
            name for name, record in records.items() if record["old_present"]
        }
        if descriptor["old_manifest_present"]:
            expected_old.add(_REPORT_MANIFEST_NAME)
        if (
            _directory_names_at(new_fd) != expected_new
            or _directory_names_at(old_fd) != expected_old
        ):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        new_contents: dict[str, str] = {}
        old_contents: dict[str, str | None] = {}
        for name, record in records.items():
            new_content, _metadata = _read_text_entry_at(
                new_fd,
                name,
                label="report transaction new entry",
            )
            if _sha256_text(new_content) != record["new_sha256"]:
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            new_contents[name] = new_content
            if record["old_present"]:
                old_content, _metadata = _read_text_entry_at(
                    old_fd,
                    name,
                    label="report transaction old entry",
                )
                if _sha256_text(old_content) != record["old_sha256"]:
                    raise RetargetMemoryError(
                        "replacement memory report transaction is invalid"
                    )
                old_contents[name] = old_content
            else:
                old_contents[name] = None
        new_manifest, _metadata = _read_text_entry_at(
            new_fd,
            _REPORT_MANIFEST_NAME,
            label="report transaction new manifest",
        )
        if _sha256_text(new_manifest) != descriptor["new_manifest_sha256"]:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        expected_manifest, _digest = _report_manifest(
            spec_id=spec_id,
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
            old_manifest, _metadata = _read_text_entry_at(
                old_fd,
                _REPORT_MANIFEST_NAME,
                label="report transaction old manifest",
            )
            if _sha256_text(old_manifest) != descriptor["old_manifest_sha256"]:
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
        elif descriptor["old_manifest_sha256"] is not None:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        _require_open_entry_binding(
            journal_fd,
            "new",
            os.fstat(new_fd),
            label="report transaction new directory",
        )
        _require_open_entry_binding(
            journal_fd,
            "old",
            os.fstat(old_fd),
            label="report transaction old directory",
        )
        return _BoundReportTransaction(
            old_contents=old_contents,
            new_contents=new_contents,
            old_manifest=old_manifest,
            new_manifest=new_manifest,
            records={},
            journal_identity=_cleanup_entry_identity(os.fstat(journal_fd)),
        )
    finally:
        if old_fd is not None:
            os.close(old_fd)
        if new_fd is not None:
            os.close(new_fd)


def _parse_bound_report_transaction(
    *,
    spec_id: str,
    journal_fd: int,
) -> _BoundReportTransaction:
    journal_metadata = os.fstat(journal_fd)
    if not stat.S_ISDIR(journal_metadata.st_mode):
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    journal_names = _directory_names_at(journal_fd)
    if journal_names == {"new", "old", "transaction.json"}:
        return _parse_legacy_bound_report_transaction(
            spec_id=spec_id,
            journal_fd=journal_fd,
        )
    if journal_names != {
        "new",
        "old",
        "slots",
        "transaction.json",
    }:
        raise RetargetMemoryError(
            "replacement memory report transaction is invalid"
        )
    new_fd: int | None = None
    old_fd: int | None = None
    slots_fd: int | None = None
    try:
        new_fd = _open_transaction_child(journal_fd, "new")
        old_fd = _open_transaction_child(journal_fd, "old")
        slots_fd = _open_transaction_child(journal_fd, "slots")
        descriptor_text, _descriptor_metadata = _read_text_entry_at(
            journal_fd,
            "transaction.json",
            label="report transaction descriptor",
        )
        try:
            descriptor = loads_strict_json(descriptor_text)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            ) from exc
        if (
            type(descriptor) is not dict
            or set(descriptor)
            != {
                "schema_version",
                "spec_id",
                "journal_identity",
                "directory_identities",
                "entries",
            }
            or descriptor["schema_version"] != 2
            or type(descriptor["schema_version"]) is not int
            or descriptor["spec_id"] != spec_id
            or type(descriptor["spec_id"]) is not str
            or _strict_identity_record(descriptor["journal_identity"])
            != _cleanup_entry_identity(journal_metadata)
            or type(descriptor["directory_identities"]) is not dict
            or set(descriptor["directory_identities"])
            != {"new", "old", "slots"}
            or _strict_identity_record(descriptor["directory_identities"]["new"])
            != _cleanup_entry_identity(os.fstat(new_fd))
            or _strict_identity_record(descriptor["directory_identities"]["old"])
            != _cleanup_entry_identity(os.fstat(old_fd))
            or _strict_identity_record(
                descriptor["directory_identities"]["slots"]
            )
            != _cleanup_entry_identity(os.fstat(slots_fd))
            or type(descriptor["entries"]) is not list
            or len(descriptor["entries"]) != len(_transaction_entry_names())
        ):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        records: dict[str, dict[str, object]] = {}
        for raw in descriptor["entries"]:
            if (
                type(raw) is not dict
                or set(raw)
                != {
                    "path",
                    "old_present",
                    "old_sha256",
                    "old_identity",
                    "old_snapshot_identity",
                    "new_sha256",
                    "new_identity",
                    "slot_identity",
                }
                or type(raw["path"]) is not str
                or raw["path"] not in _transaction_entry_names()
                or raw["path"] in records
                or type(raw["old_present"]) is not bool
                or type(raw["new_sha256"]) is not str
                or _SHA256.fullmatch(raw["new_sha256"]) is None
            ):
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            if raw["old_present"]:
                if (
                    type(raw["old_sha256"]) is not str
                    or _SHA256.fullmatch(raw["old_sha256"]) is None
                    or _strict_identity_record(raw["old_identity"])[0]
                    != stat.S_IFREG
                    or _strict_identity_record(raw["old_snapshot_identity"])[0]
                    != stat.S_IFREG
                ):
                    raise RetargetMemoryError(
                        "replacement memory report transaction is invalid"
                    )
            elif (
                raw["old_sha256"] is not None
                or raw["old_identity"] is not None
                or raw["old_snapshot_identity"] is not None
            ):
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            if (
                _strict_identity_record(raw["new_identity"])[0] != stat.S_IFREG
                or _strict_identity_record(raw["slot_identity"])[0]
                != stat.S_IFREG
            ):
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            records[raw["path"]] = raw
        if tuple(sorted(records)) != tuple(sorted(_transaction_entry_names())):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        expected_new = set(_transaction_entry_names())
        expected_old = {
            name for name, record in records.items() if record["old_present"]
        }
        if _directory_names_at(new_fd) != expected_new:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        if _directory_names_at(old_fd) != expected_old:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        slot_names = _directory_names_at(slots_fd)
        if not slot_names.issubset(expected_new):
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        new_contents: dict[str, str] = {}
        old_contents: dict[str, str | None] = {}
        for name, record in records.items():
            new_content, new_metadata = _read_text_entry_at(
                new_fd,
                name,
                label="report transaction new entry",
            )
            if (
                _sha256_text(new_content) != record["new_sha256"]
                or _cleanup_entry_identity(new_metadata)
                != _strict_identity_record(record["new_identity"])
            ):
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
            new_contents[name] = new_content
            if record["old_present"]:
                old_content, old_metadata = _read_text_entry_at(
                    old_fd,
                    name,
                    label="report transaction old entry",
                )
                if (
                    _sha256_text(old_content) != record["old_sha256"]
                    or _cleanup_entry_identity(old_metadata)
                    != _strict_identity_record(record["old_snapshot_identity"])
                ):
                    raise RetargetMemoryError(
                        "replacement memory report transaction is invalid"
                    )
                old_contents[name] = old_content
            else:
                old_contents[name] = None
            if name in slot_names:
                slot_content, slot_metadata = _read_text_entry_at(
                    slots_fd,
                    name,
                    label="report transaction slot",
                )
                slot_identity = _cleanup_entry_identity(slot_metadata)
                permitted = {
                    (
                        record["new_sha256"],
                        _strict_identity_record(record["slot_identity"]),
                    )
                }
                if record["old_present"]:
                    permitted.add(
                        (
                            record["old_sha256"],
                            _strict_identity_record(record["old_identity"]),
                        )
                    )
                if (_sha256_text(slot_content), slot_identity) not in permitted:
                    raise RetargetMemoryError(
                        "replacement memory report transaction is invalid"
                    )
            elif record["old_present"]:
                raise RetargetMemoryError(
                    "replacement memory report transaction is invalid"
                )
        expected_manifest, _digest = _report_manifest(
            spec_id=spec_id,
            contents={name: new_contents[name] for name in _REPORT_NAMES},
        )
        if new_contents[_REPORT_MANIFEST_NAME] != expected_manifest:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        for child_name, child_fd in (
            ("new", new_fd),
            ("old", old_fd),
            ("slots", slots_fd),
        ):
            _require_open_entry_binding(
                journal_fd,
                child_name,
                os.fstat(child_fd),
                label=f"report transaction {child_name} directory",
            )
        return _BoundReportTransaction(
            old_contents={name: old_contents[name] for name in _REPORT_NAMES},
            new_contents={name: new_contents[name] for name in _REPORT_NAMES},
            old_manifest=old_contents[_REPORT_MANIFEST_NAME],
            new_manifest=new_contents[_REPORT_MANIFEST_NAME],
            records=records,
            journal_identity=_cleanup_entry_identity(journal_metadata),
        )
    finally:
        if slots_fd is not None:
            os.close(slots_fd)
        if old_fd is not None:
            os.close(old_fd)
        if new_fd is not None:
            os.close(new_fd)


def _load_report_transaction(
    spec_dir: Path,
    *,
    transaction_path: Path | None = None,
    parent_fd: int | None = None,
    transaction_fd: int | None = None,
    source_name: str | None = None,
) -> _BoundReportTransaction:
    owns_parent = parent_fd is None
    owns_transaction = transaction_fd is None
    try:
        if parent_fd is None:
            parent_fd, _parent_identity = _open_report_parent(spec_dir)
        if source_name is None:
            source_name = (
                transaction_path.name
                if transaction_path is not None
                else _REPORT_TRANSACTION_NAME
            )
        if source_name in {"", ".", ".."} or "/" in source_name:
            raise RetargetMemoryError(
                "replacement memory report transaction is invalid"
            )
        if transaction_fd is None:
            transaction_fd = _open_entry_at(
                parent_fd,
                source_name,
                directory=True,
            )
        metadata = os.fstat(transaction_fd)
        loaded = _parse_bound_report_transaction(
            spec_id=spec_dir.name,
            journal_fd=transaction_fd,
        )
        _require_open_entry_binding(
            parent_fd,
            source_name,
            metadata,
            label="report journal",
        )
        return loaded
    finally:
        if owns_transaction and transaction_fd is not None:
            os.close(transaction_fd)
        if owns_parent and parent_fd is not None:
            os.close(parent_fd)


def _stage_report_transaction_at(
    spec_dir: Path,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
    *,
    spec_id: str,
    contents: dict[str, str],
    manifest_content: str,
) -> None:
    _require_report_parent_binding(
        spec_dir,
        parent_fd,
        parent_identity,
        boundary="stage",
    )
    old_values: dict[str, tuple[str | None, tuple[int, int, int] | None]] = {}
    new_values = dict(contents)
    new_values[_REPORT_MANIFEST_NAME] = manifest_content
    for name in _transaction_entry_names():
        old_values[name] = _read_optional_report_text_at(parent_fd, name)
    staging_name = ""
    for _attempt in range(32):
        candidate = f".mempalace-refresh-staging-{secrets.token_hex(16)}"
        try:
            os.mkdir(candidate, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        staging_name = candidate
        break
    if not staging_name:
        raise RetargetMemoryError(
            "replacement memory report staging is unavailable"
        )
    staging_fd = _open_entry_at(parent_fd, staging_name, directory=True)
    try:
        staging_identity = _cleanup_entry_identity(os.fstat(staging_fd))
        for child in ("new", "old", "slots"):
            os.mkdir(child, mode=0o700, dir_fd=staging_fd)
        new_fd: int | None = None
        old_fd: int | None = None
        slots_fd: int | None = None
        try:
            new_fd = _open_transaction_child(staging_fd, "new")
            old_fd = _open_transaction_child(staging_fd, "old")
            slots_fd = _open_transaction_child(staging_fd, "slots")
            records: list[dict[str, object]] = []
            for name in _transaction_entry_names():
                new_identity = _write_transaction_text_at(
                    new_fd,
                    name,
                    new_values[name],
                )
                slot_identity = _write_transaction_text_at(
                    slots_fd,
                    name,
                    new_values[name],
                    mode=0o644,
                )
                old_content, old_identity = old_values[name]
                if old_content is not None:
                    snapshot_identity = _write_transaction_text_at(
                        old_fd,
                        name,
                        old_content,
                    )
                    if snapshot_identity == old_identity:
                        raise RetargetMemoryError(
                            "replacement memory report staging identity is invalid"
                        )
                records.append(
                    {
                        "path": name,
                        "old_present": old_content is not None,
                        "old_sha256": (
                            _sha256_text(old_content)
                            if old_content is not None
                            else None
                        ),
                        "old_identity": (
                            list(old_identity) if old_identity is not None else None
                        ),
                        "old_snapshot_identity": (
                            list(snapshot_identity)
                            if old_content is not None
                            else None
                        ),
                        "new_sha256": _sha256_text(new_values[name]),
                        "new_identity": list(new_identity),
                        "slot_identity": list(slot_identity),
                    }
                )
            descriptor = {
                "schema_version": 2,
                "spec_id": spec_id,
                "journal_identity": list(staging_identity),
                "directory_identities": {
                    "new": list(_cleanup_entry_identity(os.fstat(new_fd))),
                    "old": list(_cleanup_entry_identity(os.fstat(old_fd))),
                    "slots": list(_cleanup_entry_identity(os.fstat(slots_fd))),
                },
                "entries": records,
            }
            _write_transaction_text_at(
                staging_fd,
                "transaction.json",
                json.dumps(
                    descriptor,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n",
            )
            os.fsync(new_fd)
            os.fsync(old_fd)
            os.fsync(slots_fd)
        finally:
            if slots_fd is not None:
                os.close(slots_fd)
            if old_fd is not None:
                os.close(old_fd)
            if new_fd is not None:
                os.close(new_fd)
        os.fsync(staging_fd)
        _require_open_entry_binding(
            parent_fd,
            staging_name,
            os.fstat(staging_fd),
            label="report staging journal",
        )
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="stage",
        )
        _atomic_rename_no_replace_at(
            parent_fd,
            staging_name,
            _REPORT_TRANSACTION_NAME,
        )
        _require_open_entry_binding(
            parent_fd,
            _REPORT_TRANSACTION_NAME,
            os.fstat(staging_fd),
            label="report journal",
        )
    finally:
        os.close(staging_fd)


def _read_cleanup_receipt_at(
    parent_fd: int,
    name: str,
) -> tuple[dict[str, object], str, os.stat_result]:
    content, metadata = _read_text_entry_at(
        parent_fd,
        name,
        label="cleanup receipt",
    )
    return _parse_report_cleanup_receipt(content), content, metadata


def _live_report_set_matches_at(
    parent_fd: int,
    *,
    contents: Mapping[str, str | None],
    manifest: str | None,
) -> bool:
    if tuple(sorted(contents)) != _REPORT_NAMES:
        return False
    for name, expected in contents.items():
        actual, _identity = _read_optional_report_text_at(parent_fd, name)
        if actual != expected:
            return False
    actual_manifest, _identity = _read_optional_report_text_at(
        parent_fd,
        _REPORT_MANIFEST_NAME,
    )
    return actual_manifest == manifest


def _receipt_matches_bound_transaction(
    receipt: Mapping[str, object],
    transaction: _BoundReportTransaction,
) -> bool:
    return _cleanup_receipt_matches_transaction(
        receipt,
        old_contents=transaction.old_contents,
        new_contents=transaction.new_contents,
        old_manifest=transaction.old_manifest,
        new_manifest=transaction.new_manifest,
    )


def _validate_completed_report_archives_at(
    spec_dir: Path,
    parent_fd: int,
    *,
    active_receipt: Mapping[str, object] | None,
) -> int:
    names = _directory_names_at(parent_fd)
    completed_names = sorted(
        name
        for name in names
        if name.startswith(_REPORT_COMPLETED_RECEIPT_PREFIX)
    )
    if len(completed_names) > _MAX_COMPLETED_REPORT_TRANSACTIONS:
        raise RetargetMemoryError(
            "replacement memory completed transaction history is full"
        )
    completed: dict[str, tuple[dict[str, object], str, os.stat_result]] = {}
    for receipt_name in completed_names:
        receipt, content, metadata = _read_cleanup_receipt_at(
            parent_fd,
            receipt_name,
        )
        if receipt_name != _report_completed_receipt_name(content):
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipt is invalid"
            )
        cleanup_name = receipt["cleanup_name"]
        if type(cleanup_name) is not str or cleanup_name in completed:
            raise RetargetMemoryError(
                "replacement memory completed cleanup receipts conflict"
            )
        completed[cleanup_name] = (receipt, content, metadata)
    detached_names = {
        name for name in names if name.startswith(_REPORT_DETACHED_PREFIX)
    }
    active_name = (
        active_receipt["cleanup_name"]
        if active_receipt is not None
        else None
    )
    if type(active_name) is str and active_name in completed:
        raise RetargetMemoryError(
            "replacement memory cleanup evidence is duplicated"
        )
    expected = set(completed)
    if type(active_name) is str and active_name in detached_names:
        expected.add(active_name)
    if detached_names != expected:
        raise RetargetMemoryError(
            "replacement memory detached cleanup is unauthenticated"
        )
    for cleanup_name, (receipt, _content, receipt_metadata) in completed.items():
        journal_fd = _open_entry_at(parent_fd, cleanup_name, directory=True)
        try:
            journal_metadata = os.fstat(journal_fd)
            if (
                journal_metadata.st_dev != receipt["device"]
                or journal_metadata.st_ino != receipt["inode"]
            ):
                raise RetargetMemoryError(
                    "replacement memory completed journal identity changed"
                )
            transaction = _load_report_transaction(
                spec_dir,
                parent_fd=parent_fd,
                transaction_fd=journal_fd,
                source_name=cleanup_name,
            )
            descriptor_text, _metadata = _read_text_entry_at(
                journal_fd,
                "transaction.json",
                label="report transaction descriptor",
            )
            if _sha256_text(descriptor_text) != receipt["transaction_sha256"]:
                raise RetargetMemoryError(
                    "replacement memory completed journal identity changed"
                )
            if not _receipt_matches_bound_transaction(receipt, transaction):
                raise RetargetMemoryError(
                    "replacement memory completed cleanup receipt is inconsistent"
                )
            _require_open_entry_binding(
                parent_fd,
                cleanup_name,
                journal_metadata,
                label="completed journal",
            )
            _require_open_entry_binding(
                parent_fd,
                _report_completed_receipt_name(_content),
                receipt_metadata,
                label="completed cleanup receipt",
            )
        finally:
            os.close(journal_fd)
    return len(completed_names)


def _load_active_cleanup_receipt_at(
    parent_fd: int,
) -> tuple[dict[str, object], str, os.stat_result] | None:
    if _entry_stat_at(parent_fd, _REPORT_CLEANUP_RECEIPT_NAME) is None:
        return None
    return _read_cleanup_receipt_at(parent_fd, _REPORT_CLEANUP_RECEIPT_NAME)


def _active_journal_source_at(
    parent_fd: int,
    receipt: Mapping[str, object],
) -> str:
    cleanup_name = receipt["cleanup_name"]
    if type(cleanup_name) is not str:
        raise RetargetMemoryError(
            "replacement memory cleanup receipt is invalid"
        )
    active = _entry_stat_at(parent_fd, _REPORT_TRANSACTION_NAME) is not None
    detached = _entry_stat_at(parent_fd, cleanup_name) is not None
    if active == detached:
        raise RetargetMemoryError(
            "replacement memory cleanup journal is missing or duplicated"
        )
    return _REPORT_TRANSACTION_NAME if active else cleanup_name


def _retire_active_cleanup_at(
    spec_dir: Path,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
) -> int:
    active_record = _load_active_cleanup_receipt_at(parent_fd)
    active_receipt = active_record[0] if active_record is not None else None
    completed_count = _validate_completed_report_archives_at(
        spec_dir,
        parent_fd,
        active_receipt=active_receipt,
    )
    if active_record is None:
        return completed_count
    if completed_count >= _MAX_COMPLETED_REPORT_TRANSACTIONS:
        raise RetargetMemoryError(
            "replacement memory completed transaction history is full"
        )
    receipt, receipt_content, receipt_metadata = active_record
    source_name = _active_journal_source_at(parent_fd, receipt)
    journal_fd = _open_entry_at(parent_fd, source_name, directory=True)
    try:
        journal_metadata = os.fstat(journal_fd)
        if (
            journal_metadata.st_dev != receipt["device"]
            or journal_metadata.st_ino != receipt["inode"]
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction identity changed"
            )
        transaction = _load_report_transaction(
            spec_dir,
            parent_fd=parent_fd,
            transaction_fd=journal_fd,
            source_name=source_name,
        )
        descriptor_text, _metadata = _read_text_entry_at(
            journal_fd,
            "transaction.json",
            label="report transaction descriptor",
        )
        if (
            _sha256_text(descriptor_text) != receipt["transaction_sha256"]
            or not _receipt_matches_bound_transaction(receipt, transaction)
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup transaction state is inconsistent"
            )
        expected_contents = (
            transaction.new_contents
            if receipt["expected_live"] == "new"
            else transaction.old_contents
        )
        expected_manifest = (
            transaction.new_manifest
            if receipt["expected_live"] == "new"
            else transaction.old_manifest
        )
        if not _live_report_set_matches_at(
            parent_fd,
            contents=expected_contents,
            manifest=expected_manifest,
        ):
            raise RetargetMemoryError(
                "replacement memory cleanup live report set changed"
            )
        _require_open_entry_binding(
            parent_fd,
            source_name,
            journal_metadata,
            label="cleanup journal",
        )
        _require_open_entry_binding(
            parent_fd,
            _REPORT_CLEANUP_RECEIPT_NAME,
            receipt_metadata,
            label="cleanup receipt",
        )
        if _canonical_cleanup_receipt(receipt) != receipt_content:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt changed"
            )
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="archive",
        )
        _retire_report_cleanup_receipt(
            parent_fd,
            source_name=source_name,
            receipt=receipt,
            expected_receipt_identity=_cleanup_entry_identity(receipt_metadata),
        )
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="archive",
        )
    finally:
        os.close(journal_fd)
    return completed_count + 1


def _exchange_report_entry_at(
    parent_fd: int,
    slots_fd: int,
    *,
    name: str,
    old_present: bool,
    old_identity: tuple[int, int, int] | None,
    new_identity: tuple[int, int, int],
) -> None:
    live = _entry_stat_at(parent_fd, name)
    slot = _entry_stat_at(slots_fd, name)
    if slot is None or _cleanup_entry_identity(slot) != new_identity:
        raise RetargetMemoryError(
            "replacement memory report publication slot changed"
        )
    if old_present:
        if live is None or _cleanup_entry_identity(live) != old_identity:
            raise RetargetMemoryError(
                "replacement memory live report changed before publication"
            )
        _atomic_exchange_at(parent_fd, name, slots_fd, name)
        after_live = _entry_stat_at(parent_fd, name)
        after_slot = _entry_stat_at(slots_fd, name)
        if (
            after_live is None
            or after_slot is None
            or _cleanup_entry_identity(after_live) != new_identity
            or _cleanup_entry_identity(after_slot) != old_identity
        ):
            raise RetargetMemoryError(
                "replacement memory report publication is uncertain"
            )
    else:
        if live is not None:
            raise RetargetMemoryError(
                "replacement memory live report changed before publication"
            )
        _atomic_rename_no_replace_between(slots_fd, name, parent_fd, name)
        after_live = _entry_stat_at(parent_fd, name)
        if (
            after_live is None
            or _cleanup_entry_identity(after_live) != new_identity
            or _entry_stat_at(slots_fd, name) is not None
        ):
            raise RetargetMemoryError(
                "replacement memory report publication is uncertain"
            )


def _restore_old_entry_at(
    parent_fd: int,
    slots_fd: int,
    *,
    name: str,
    record: Mapping[str, object],
) -> None:
    old_present = bool(record["old_present"])
    old_identity = (
        _strict_identity_record(record["old_identity"])
        if old_present
        else None
    )
    new_identity = _strict_identity_record(record["slot_identity"])
    live = _entry_stat_at(parent_fd, name)
    slot = _entry_stat_at(slots_fd, name)
    live_identity = _cleanup_entry_identity(live) if live is not None else None
    slot_identity = _cleanup_entry_identity(slot) if slot is not None else None
    if old_present:
        if live_identity == old_identity and slot_identity == new_identity:
            return
        if live_identity == new_identity and slot_identity == old_identity:
            _atomic_exchange_at(parent_fd, name, slots_fd, name)
        else:
            raise RetargetMemoryError(
                "replacement memory report rollback state is inconsistent"
            )
    else:
        if live is None and slot_identity == new_identity:
            return
        if live_identity == new_identity and slot is None:
            _atomic_rename_no_replace_between(parent_fd, name, slots_fd, name)
        else:
            raise RetargetMemoryError(
                "replacement memory report rollback state is inconsistent"
            )
    final_live = _entry_stat_at(parent_fd, name)
    final_slot = _entry_stat_at(slots_fd, name)
    if old_present:
        if (
            final_live is None
            or final_slot is None
            or _cleanup_entry_identity(final_live) != old_identity
            or _cleanup_entry_identity(final_slot) != new_identity
        ):
            raise RetargetMemoryError(
                "replacement memory report rollback is uncertain"
            )
    elif final_live is not None or final_slot is None or (
        _cleanup_entry_identity(final_slot) != new_identity
    ):
        raise RetargetMemoryError(
            "replacement memory report rollback is uncertain"
        )


def _archive_bound_transaction_at(
    spec_dir: Path,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
    *,
    transaction_fd: int,
    expected_live: str,
) -> None:
    transaction = _load_report_transaction(
        spec_dir,
        parent_fd=parent_fd,
        transaction_fd=transaction_fd,
        source_name=_REPORT_TRANSACTION_NAME,
    )
    if expected_live == "new":
        expected_contents: Mapping[str, str | None] = transaction.new_contents
        expected_manifest = transaction.new_manifest
    elif expected_live == "old":
        expected_contents = transaction.old_contents
        expected_manifest = transaction.old_manifest
    else:
        raise RetargetMemoryError("replacement memory cleanup state is invalid")
    if not _live_report_set_matches_at(
        parent_fd,
        contents=expected_contents,
        manifest=expected_manifest,
    ):
        raise RetargetMemoryError(
            "replacement memory cleanup live report set is inconsistent"
        )
    journal_metadata = os.fstat(transaction_fd)
    descriptor_text, _metadata = _read_text_entry_at(
        transaction_fd,
        "transaction.json",
        label="report transaction descriptor",
    )
    transaction_digest = _sha256_text(descriptor_text)
    cleanup_name = _report_cleanup_name(
        transaction_sha256=transaction_digest,
        expected_live=expected_live,
        device=journal_metadata.st_dev,
        inode=journal_metadata.st_ino,
    )
    receipt = {
        "schema_version": 1,
        "cleanup_name": cleanup_name,
        "transaction_sha256": transaction_digest,
        "expected_live": expected_live,
        "device": journal_metadata.st_dev,
        "inode": journal_metadata.st_ino,
        "files": _cleanup_live_records(expected_contents),
        "manifest_present": expected_manifest is not None,
        "manifest_sha256": (
            _sha256_text(expected_manifest)
            if expected_manifest is not None
            else None
        ),
    }
    receipt_content = _canonical_cleanup_receipt(receipt)
    existing = _entry_stat_at(parent_fd, _REPORT_CLEANUP_RECEIPT_NAME)
    if existing is None:
        receipt_identity = _write_transaction_text_at(
            parent_fd,
            _REPORT_CLEANUP_RECEIPT_NAME,
            receipt_content,
        )
    else:
        _loaded, persisted, receipt_metadata = _read_cleanup_receipt_at(
            parent_fd,
            _REPORT_CLEANUP_RECEIPT_NAME,
        )
        if persisted != receipt_content:
            raise RetargetMemoryError(
                "replacement memory cleanup receipt changed"
            )
        receipt_identity = _cleanup_entry_identity(receipt_metadata)
    _require_open_entry_binding(
        parent_fd,
        _REPORT_TRANSACTION_NAME,
        journal_metadata,
        label="report journal",
    )
    _require_report_parent_binding(
        spec_dir,
        parent_fd,
        parent_identity,
        boundary="archive",
    )
    _retire_report_cleanup_receipt(
        parent_fd,
        source_name=_REPORT_TRANSACTION_NAME,
        receipt=receipt,
        expected_receipt_identity=receipt_identity,
    )
    _require_report_parent_binding(
        spec_dir,
        parent_fd,
        parent_identity,
        boundary="archive",
    )


def _remove_report_transaction(
    spec_dir: Path,
    *,
    expected_live: str,
    parent_fd: int | None = None,
    parent_identity: tuple[int, int, int] | None = None,
    transaction_fd: int | None = None,
    transaction: _BoundReportTransaction | None = None,
) -> None:
    del transaction
    owns_parent = parent_fd is None
    owns_transaction = transaction_fd is None
    try:
        if parent_fd is None:
            parent_fd, parent_identity = _open_report_parent(spec_dir)
        if parent_identity is None:
            parent_identity = _cleanup_entry_identity(os.fstat(parent_fd))
        if transaction_fd is None:
            transaction_fd = _open_entry_at(
                parent_fd,
                _REPORT_TRANSACTION_NAME,
                directory=True,
            )
        _archive_bound_transaction_at(
            spec_dir,
            parent_fd,
            parent_identity,
            transaction_fd=transaction_fd,
            expected_live=expected_live,
        )
    finally:
        if owns_transaction and transaction_fd is not None:
            os.close(transaction_fd)
        if owns_parent and parent_fd is not None:
            os.close(parent_fd)


def _recover_report_transaction_at(
    spec_dir: Path,
    parent_fd: int,
    parent_identity: tuple[int, int, int],
) -> int:
    completed_count = _retire_active_cleanup_at(
        spec_dir,
        parent_fd,
        parent_identity,
    )
    if _entry_stat_at(parent_fd, _REPORT_TRANSACTION_NAME) is None:
        return completed_count
    if completed_count >= _MAX_COMPLETED_REPORT_TRANSACTIONS:
        raise RetargetMemoryError(
            "replacement memory completed transaction history is full"
        )
    transaction_fd = _open_entry_at(
        parent_fd,
        _REPORT_TRANSACTION_NAME,
        directory=True,
    )
    try:
        transaction = _load_report_transaction(
            spec_dir,
            parent_fd=parent_fd,
            transaction_fd=transaction_fd,
            source_name=_REPORT_TRANSACTION_NAME,
        )
        if _live_report_set_matches_at(
            parent_fd,
            contents=transaction.new_contents,
            manifest=transaction.new_manifest,
        ):
            _remove_report_transaction(
                spec_dir,
                expected_live="new",
                parent_fd=parent_fd,
                parent_identity=parent_identity,
                transaction_fd=transaction_fd,
                transaction=transaction,
            )
            return completed_count + 1
        if not transaction.records:
            raise RetargetMemoryError(
                "replacement memory legacy active journal requires manual recovery"
            )
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="rollback",
        )
        slots_fd = _open_transaction_child(transaction_fd, "slots")
        try:
            for name in (
                _REPORT_MANIFEST_NAME,
                *_REPORT_NAMES,
            ):
                _restore_old_entry_at(
                    parent_fd,
                    slots_fd,
                    name=name,
                    record=transaction.records[name],
                )
        finally:
            os.close(slots_fd)
        _require_open_entry_binding(
            parent_fd,
            _REPORT_TRANSACTION_NAME,
            os.fstat(transaction_fd),
            label="report journal",
        )
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="rollback",
        )
        _remove_report_transaction(
            spec_dir,
            expected_live="old",
            parent_fd=parent_fd,
            parent_identity=parent_identity,
            transaction_fd=transaction_fd,
            transaction=transaction,
        )
        return completed_count + 1
    finally:
        os.close(transaction_fd)


def _publish_report_set(
    spec_dir: Path,
    *,
    spec_id: str,
    contents: dict[str, str],
) -> str:
    parent_fd, parent_identity = _open_report_parent(spec_dir)
    try:
        completed_count = _recover_report_transaction_at(
            spec_dir,
            parent_fd,
            parent_identity,
        )
        staging_names = {
            name
            for name in _directory_names_at(parent_fd)
            if name.startswith(".mempalace-refresh-staging-")
        }
        if staging_names:
            raise RetargetMemoryError(
                "replacement memory unauthenticated staging evidence is present"
            )
        manifest_content, report_set_digest = _report_manifest(
            spec_id=spec_id,
            contents=contents,
        )
        if _live_report_set_matches_at(
            parent_fd,
            contents=contents,
            manifest=manifest_content,
        ):
            _require_report_parent_binding(
                spec_dir,
                parent_fd,
                parent_identity,
                boundary="complete",
            )
            return report_set_digest
        if completed_count >= _MAX_COMPLETED_REPORT_TRANSACTIONS:
            raise RetargetMemoryError(
                "replacement memory completed transaction history is full"
            )
        _stage_report_transaction_at(
            spec_dir,
            parent_fd,
            parent_identity,
            spec_id=spec_id,
            contents=contents,
            manifest_content=manifest_content,
        )
        transaction_fd = _open_entry_at(
            parent_fd,
            _REPORT_TRANSACTION_NAME,
            directory=True,
        )
        try:
            transaction = _load_report_transaction(
                spec_dir,
                parent_fd=parent_fd,
                transaction_fd=transaction_fd,
                source_name=_REPORT_TRANSACTION_NAME,
            )
            _require_report_parent_binding(
                spec_dir,
                parent_fd,
                parent_identity,
                boundary="publish",
            )
            slots_fd = _open_transaction_child(transaction_fd, "slots")
            try:
                for name in (*_REPORT_NAMES, _REPORT_MANIFEST_NAME):
                    record = transaction.records[name]
                    _exchange_report_entry_at(
                        parent_fd,
                        slots_fd,
                        name=name,
                        old_present=bool(record["old_present"]),
                        old_identity=(
                            _strict_identity_record(record["old_identity"])
                            if record["old_present"]
                            else None
                        ),
                        new_identity=_strict_identity_record(
                            record["slot_identity"]
                        ),
                    )
            except (Exception, SystemExit):
                _recover_report_transaction_at(
                    spec_dir,
                    parent_fd,
                    parent_identity,
                )
                raise
            finally:
                os.close(slots_fd)
            if not _live_report_set_matches_at(
                parent_fd,
                contents=contents,
                manifest=manifest_content,
            ):
                raise RetargetMemoryError(
                    "replacement memory report set postimage is inconsistent"
                )
            _remove_report_transaction(
                spec_dir,
                expected_live="new",
                parent_fd=parent_fd,
                parent_identity=parent_identity,
                transaction_fd=transaction_fd,
                transaction=transaction,
            )
        finally:
            os.close(transaction_fd)
        _require_report_parent_binding(
            spec_dir,
            parent_fd,
            parent_identity,
            boundary="complete",
        )
        return report_set_digest
    finally:
        os.close(parent_fd)


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
