"""Committed, deterministic deferrals for deliberately removed spec scope."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable, Sequence

from harness.canonical_requirements import extract_canonical_requirements
from kernel.task_contract import parse_task_rows, validate_tasks_markdown


LEDGER_FILENAME = "deferred-scope.json"
SCHEMA_VERSION = 1
_REQUIREMENT_PREFIXES = ("FR-", "NFR-", "AC-", "SC-")


class DeferredScopeError(ValueError):
    """Raised when a deferred-scope request or ledger is invalid."""


@dataclass(frozen=True)
class DeferredScopePlan:
    selected_ids: tuple[str, ...]
    derived_task_ids: tuple[str, ...]
    related_active_ids: tuple[str, ...]


@dataclass(frozen=True)
class DeferredScopeEntry:
    entry_id: str
    status: str
    selected_ids: tuple[str, ...]
    derived_task_ids: tuple[str, ...]
    reason: str
    deferred_at: str
    planned_at: str | None

    @classmethod
    def from_dict(cls, payload: object) -> "DeferredScopeEntry":
        if not isinstance(payload, dict):
            raise DeferredScopeError("deferred-scope entry must be an object")
        entry_id = _required_text(payload, "entry_id")
        status = _required_text(payload, "status")
        if status not in {"deferred", "planned"}:
            raise DeferredScopeError(f"unsupported deferred-scope entry status: {status}")
        return cls(
            entry_id=entry_id,
            status=status,
            selected_ids=_id_tuple(payload.get("selected_ids"), "selected_ids"),
            derived_task_ids=_id_tuple(payload.get("derived_task_ids"), "derived_task_ids"),
            reason=_required_text(payload, "reason"),
            deferred_at=_required_text(payload, "deferred_at"),
            planned_at=_optional_text(payload.get("planned_at")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "entry_id": self.entry_id,
            "status": self.status,
            "selected_ids": list(self.selected_ids),
            "derived_task_ids": list(self.derived_task_ids),
            "reason": self.reason,
            "deferred_at": self.deferred_at,
            "planned_at": self.planned_at,
        }


@dataclass(frozen=True)
class DeferredScopeLedger:
    entries: tuple[DeferredScopeEntry, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in self.entries],
        }


def ledger_path(spec_dir: Path) -> Path:
    return spec_dir / LEDGER_FILENAME


def read_ledger(spec_dir: Path) -> DeferredScopeLedger:
    path = ledger_path(spec_dir)
    if not path.exists():
        return DeferredScopeLedger(entries=())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeferredScopeError(f"invalid deferred-scope ledger: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise DeferredScopeError("unsupported deferred-scope ledger schema")
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise DeferredScopeError("deferred-scope ledger entries must be a list")
    entries = tuple(DeferredScopeEntry.from_dict(item) for item in raw_entries)
    if len({entry.entry_id for entry in entries}) != len(entries):
        raise DeferredScopeError("duplicate deferred-scope entry id")
    return DeferredScopeLedger(entries=entries)


def plan_defer(spec_dir: Path, ids: Sequence[str], *, reason: str) -> DeferredScopePlan:
    selected_ids = _normalize_ids(ids)
    if not str(reason).strip():
        raise DeferredScopeError("defer requires a non-empty reason")
    task_by_id, requirement_ids = _scope_ids(spec_dir)
    _validate_selected_ids(selected_ids, task_by_id, requirement_ids)
    ledger = read_ledger(spec_dir)
    active = {
        item_id
        for entry in ledger.entries
        if entry.status == "deferred"
        for item_id in entry.selected_ids
    }
    duplicate = sorted(active.intersection(selected_ids))
    if duplicate:
        raise DeferredScopeError(f"already deferred: {', '.join(duplicate)}")

    requirement_ids_selected = set(selected_ids).intersection(requirement_ids)
    derived = set(item_id for item_id in selected_ids if item_id in task_by_id)
    for task_id, task in task_by_id.items():
        if requirement_ids_selected.intersection(task.requirements):
            derived.add(task_id)
    related_active = {
        requirement_id
        for task_id in derived
        for requirement_id in task_by_id[task_id].requirements
        if requirement_id != "UNMAPPED" and requirement_id not in requirement_ids_selected
    }
    return DeferredScopePlan(
        selected_ids=selected_ids,
        derived_task_ids=tuple(sorted(derived)),
        related_active_ids=tuple(sorted(related_active)),
    )


def apply_defer(spec_dir: Path, ids: Sequence[str], *, reason: str) -> DeferredScopePlan:
    plan = plan_defer(spec_dir, ids, reason=reason)
    ledger = read_ledger(spec_dir)
    entry = DeferredScopeEntry(
        entry_id=f"defer-{len(ledger.entries) + 1:03d}",
        status="deferred",
        selected_ids=plan.selected_ids,
        derived_task_ids=plan.derived_task_ids,
        reason=str(reason).strip(),
        deferred_at=_timestamp(),
        planned_at=None,
    )
    _write_ledger(spec_dir, DeferredScopeLedger(entries=(*ledger.entries, entry)))
    return plan


def plan_restore(spec_dir: Path, ids: Sequence[str]) -> DeferredScopePlan:
    selected_ids = _normalize_ids(ids)
    ledger = read_ledger(spec_dir)
    matches = _active_entries_matching(ledger, selected_ids)
    if not matches:
        raise DeferredScopeError(f"no active deferral for: {', '.join(selected_ids)}")
    return DeferredScopePlan(
        selected_ids=selected_ids,
        derived_task_ids=tuple(sorted({task for entry in matches for task in entry.derived_task_ids})),
        related_active_ids=(),
    )


def apply_restore(spec_dir: Path, ids: Sequence[str]) -> DeferredScopePlan:
    plan = plan_restore(spec_dir, ids)
    ledger = read_ledger(spec_dir)
    selected_ids = set(plan.selected_ids)
    changed = False
    entries: list[DeferredScopeEntry] = []
    for entry in ledger.entries:
        if entry.status == "deferred" and selected_ids.intersection(
            set(entry.selected_ids) | set(entry.derived_task_ids)
        ):
            entries.append(replace(entry, status="planned", planned_at=_timestamp()))
            changed = True
        else:
            entries.append(entry)
    if not changed:
        raise DeferredScopeError(f"no active deferral for: {', '.join(plan.selected_ids)}")
    _write_ledger(spec_dir, DeferredScopeLedger(entries=tuple(entries)))
    return plan


def active_deferred_requirement_ids(spec_dir: Path) -> frozenset[str]:
    return frozenset(
        item_id
        for entry in read_ledger(spec_dir).entries
        if entry.status == "deferred"
        for item_id in entry.selected_ids
        if item_id.startswith(_REQUIREMENT_PREFIXES)
    )


def active_entries(spec_dir: Path) -> tuple[DeferredScopeEntry, ...]:
    return tuple(entry for entry in read_ledger(spec_dir).entries if entry.status == "deferred")


def _scope_ids(spec_dir: Path):
    tasks_markdown = (spec_dir / "tasks.md").read_text(encoding="utf-8", errors="replace")
    validation = validate_tasks_markdown(tasks_markdown)
    if not validation.valid:
        raise DeferredScopeError(f"invalid tasks.md: {'; '.join(validation.errors)}")
    task_by_id = {task.task_id: task for task in parse_task_rows(tasks_markdown)}
    requirement_ids = {row.id for row in extract_canonical_requirements(spec_dir)}
    return task_by_id, requirement_ids


def _validate_selected_ids(
    ids: Iterable[str], task_by_id: dict[str, object], requirement_ids: set[str]
) -> None:
    unknown = [item_id for item_id in ids if item_id not in task_by_id and item_id not in requirement_ids]
    if unknown:
        raise DeferredScopeError(f"unknown canonical id: {', '.join(unknown)}")
    unsupported = [
        item_id
        for item_id in ids
        if not item_id.startswith(("T-", *_REQUIREMENT_PREFIXES))
    ]
    if unsupported:
        raise DeferredScopeError(f"unsupported defer id: {', '.join(unsupported)}")


def _normalize_ids(ids: Sequence[str]) -> tuple[str, ...]:
    values = tuple(dict.fromkeys(str(item).strip() for item in ids if str(item).strip()))
    if not values:
        raise DeferredScopeError("at least one canonical id is required")
    return values


def _active_entries_matching(
    ledger: DeferredScopeLedger, ids: tuple[str, ...]
) -> tuple[DeferredScopeEntry, ...]:
    wanted = set(ids)
    return tuple(
        entry
        for entry in ledger.entries
        if entry.status == "deferred"
        and wanted.intersection(set(entry.selected_ids) | set(entry.derived_task_ids))
    )


def _write_ledger(spec_dir: Path, ledger: DeferredScopeLedger) -> None:
    path = ledger_path(spec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(ledger.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _required_text(payload: dict[str, object], key: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise DeferredScopeError(f"deferred-scope entry missing {key}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _id_tuple(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise DeferredScopeError(f"deferred-scope entry {key} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()
