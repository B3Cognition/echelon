"""Fail-closed MemPalace ownership boundaries for destructive spec retargets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Mapping

from echelon.mempalace_audit import (
    MAX_AUDIT_SCAN_ROWS,
    SpecMemoryAuditReport,
    SpecMemoryCleanupReport,
    _write_text_durable_atomic,
    audit_spec_memory,
    cleanup_stale_spec_memory,
    scan_wing_rows_complete,
    write_audit_reports,
)
from echelon.mempalace_requirements import (
    SpecMemoryMineReport,
    create_requirement_memory_adapter,
    mine_spec_requirements,
)


_CANONICAL_SPEC_ID = re.compile(
    r"^(?:[0-9]{3,})-[a-z0-9]+(?:-[a-z0-9]+)*$"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_PATH_LENGTH = 4_096
_MAX_DRAWER_ID_LENGTH = 1_024
_DELETE_BATCH_SIZE = 128


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
        for value, field in (
            (self.mine_status, "mine_status"),
            (self.audit_status, "audit_status"),
            (self.adapter, "adapter"),
            (self.wing, "wing"),
            (self.palace_path, "palace_path"),
            (self.failure_code, "failure_code"),
        ):
            if value is not None and (
                type(value) is not str or not value or len(value) > _MAX_PATH_LENGTH
            ):
                raise ValueError(f"invalid retarget memory {field}")

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
    return wing.strip()


def _normalized_ownership_path(value: object) -> tuple[str, str | None]:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_PATH_LENGTH
        or "\\" in value
        or value.startswith("/")
        or ":" in value
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
    return declared == spec_id or path_spec == spec_id


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
    if not isinstance(palace_path, (str, Path)) or not str(palace_path):
        raise RetargetMemoryError(
            "configured MemPalace adapter storage identity is incomplete"
        )
    adapter_name = f"{type(adapter).__module__}.{type(adapter).__qualname__}"
    if len(adapter_name) > _MAX_PATH_LENGTH:
        raise RetargetMemoryError("configured MemPalace adapter identity is invalid")
    return adapter_name, wing, str(palace_path)


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
    if isinstance(result, Mapping):
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
    acknowledgement_available = False
    delete_failure: Exception | SystemExit | None = None
    for start in range(0, len(owned), _DELETE_BATCH_SIZE):
        batch = owned[start : start + _DELETE_BATCH_SIZE]
        try:
            raw_acknowledgement = collection.delete(ids=list(batch))  # type: ignore[attr-defined]
            acknowledgement = _delete_acknowledgement(raw_acknowledgement)
            if acknowledgement is not None:
                acknowledgement_available = True
                acknowledgement_total += acknowledgement
                if acknowledgement != len(batch):
                    raise RetargetMemoryError(
                        "MemPalace reported partial deletion"
                    )
        except (Exception, SystemExit) as exc:
            delete_failure = exc
            break

    try:
        remaining_rows = scan_wing_rows_complete(collection, wing=wing)
        remaining_owned = _classify_owned_rows(
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
                acknowledgement_total if acknowledgement_available else None
            ),
            failure_code="retarget_memory_rescan_failed",
        )
        raise RetargetMemoryError(
            "MemPalace complete rescan failed after deletion",
            receipt=receipt,
        ) from exc

    remaining_ids = set(remaining_rows)
    actual_deleted = tuple(sorted(set(owned).difference(remaining_ids)))
    unrelated_before = set(rows).difference(owned)
    unrelated_missing = tuple(sorted(unrelated_before.difference(remaining_ids)))
    receipt = _receipt(
        status=(
            "fail"
            if delete_failure is not None
            or remaining_owned
            or unrelated_missing
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
            acknowledgement_total if acknowledgement_available else None
        ),
        remaining=remaining_owned,
        unrelated_missing=unrelated_missing,
        failure_code=(
            "retarget_memory_delete_partial"
            if delete_failure is not None or remaining_owned
            else (
                "retarget_memory_unrelated_missing"
                if unrelated_missing
                else None
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
    audit_expected_count = getattr(audit, "expected_count", None)
    audit_present_count = getattr(audit, "present_current_count", None)
    if (
        type(audit) is not SpecMemoryAuditReport
        or getattr(audit, "schema_version", None) != 1
        or type(getattr(audit, "schema_version", None)) is not int
        or type(getattr(audit, "errors", None)) is not list
        or getattr(audit, "errors") != []
        or type(audit_expected_count) is not int
        or type(audit_present_count) is not int
        or audit_expected_count != len(expected_ids)
        or audit_present_count != len(expected_ids)
    ):
        raise RetargetMemoryError(
            "replacement memory audit receipt is inconsistent"
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
        _write_text_durable_atomic(
            resolved_spec_dir / "mempalace-mine.json",
            json.dumps(
                mine_payload,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n",
        )
        write_audit_reports(audit, resolved_spec_dir)
    except (Exception, SystemExit) as exc:
        raise RetargetMemoryError(
            "replacement memory report write failed",
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
    )
