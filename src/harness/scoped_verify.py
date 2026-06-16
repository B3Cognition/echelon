"""Deterministic scoped fulfillment verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from kernel.fulfillment import latest_fulfillment_report, read_fulfillment_metadata
from kernel.task_contract import parse_task_rows


@dataclass(frozen=True)
class ScopedVerifyPlan:
    impacted_requirement_ids: tuple[str, ...]
    completed_task_ids: tuple[str, ...]
    changed_files: tuple[str, ...]
    base_full_report_path: Path | None
    base_full_verify_commit: str | None


def build_scoped_verify_plan(
    *,
    spec_dir: Path,
    completed_task_ids: Iterable[str],
    changed_files: Iterable[str],
) -> ScopedVerifyPlan:
    """Return deterministic requirement IDs that must be rejudged."""
    completed = tuple(dict.fromkeys(_clean_items(completed_task_ids)))
    changed = tuple(dict.fromkeys(_normalize_path(item) for item in _clean_items(changed_files)))
    tasks = parse_task_rows((spec_dir / "tasks.md").read_text(encoding="utf-8", errors="replace"))
    by_task = {task.task_id: task for task in tasks}

    impacted: set[str] = set()
    for task_id in completed:
        task = by_task.get(task_id)
        if task is None:
            continue
        impacted.update(_mapped_requirements(task.requirements))
        for dependency_id in task.dependencies:
            dependency = by_task.get(dependency_id)
            if dependency is not None:
                impacted.update(_mapped_requirements(dependency.requirements))

    report = latest_fulfillment_report(spec_dir)
    if report is not None:
        for row in _fulfillment_rows(report.read_text(encoding="utf-8", errors="replace")):
            if _evidence_changed(row.evidence, changed):
                impacted.add(row.item_id)

    metadata = read_fulfillment_metadata(report) if report is not None else {}
    base_commit = _base_full_verify_commit(metadata)
    return ScopedVerifyPlan(
        impacted_requirement_ids=tuple(sorted(impacted)),
        completed_task_ids=completed,
        changed_files=changed,
        base_full_report_path=report,
        base_full_verify_commit=base_commit if isinstance(base_commit, str) else None,
    )


def merge_scoped_fulfillment_report(
    *,
    base_report_path: Path,
    scoped_report_path: Path,
    output_report_path: Path,
    impacted_requirement_ids: Iterable[str],
    spec_id: str,
    commit: str,
    base_full_verify_commit: str | None,
) -> None:
    """Merge scoped judgments into a copy of the previous full report."""
    impacted = set(_clean_items(impacted_requirement_ids))
    base_text = base_report_path.read_text(encoding="utf-8", errors="replace")
    scoped_text = scoped_report_path.read_text(encoding="utf-8", errors="replace")
    scoped_rows = {
        row.item_id: row.line
        for row in _fulfillment_rows(scoped_text)
        if row.item_id in impacted
    }

    merged_lines: list[str] = []
    for line in _strip_frontmatter(base_text).splitlines():
        row = _fulfillment_row(line)
        if row is not None and row.item_id in scoped_rows:
            merged_lines.append(scoped_rows[row.item_id])
        else:
            merged_lines.append(line)

    metadata = {
        "spec_id": spec_id,
        "verified_commit": commit,
        "verify_scope": "scoped",
        "base_full_verify_commit": base_full_verify_commit or "",
        "scoped_requirement_ids": sorted(impacted),
    }
    output_report_path.write_text(
        _frontmatter(metadata) + "\n".join(merged_lines) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class _ReportRow:
    item_id: str
    evidence: str
    line: str


_REQ_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9_.:]+)+$")
_FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n?", re.DOTALL)


def _mapped_requirements(requirements: Iterable[str]) -> list[str]:
    return [
        requirement
        for requirement in requirements
        if requirement and requirement != "UNMAPPED"
    ]


def _clean_items(items: Iterable[str]) -> list[str]:
    return [str(item).strip() for item in items if str(item).strip()]


def _normalize_path(value: str) -> str:
    return value.strip().replace("\\", "/").lstrip("./")


def _normalize_evidence_path(value: str) -> str:
    normalized = _normalize_path(value).strip("`[]()")
    if ":" in normalized:
        path, suffix = normalized.rsplit(":", 1)
        if suffix.isdigit():
            normalized = path
    return normalized


def _evidence_changed(evidence: str, changed_files: tuple[str, ...]) -> bool:
    if not changed_files:
        return False
    evidence_paths = {
        _normalize_evidence_path(item)
        for item in re.split(r"[,; ]+", evidence)
        if item.strip()
    }
    for changed in changed_files:
        for evidence_path in evidence_paths:
            if changed == evidence_path or changed.endswith(f"/{evidence_path}"):
                return True
    return False


def _base_full_verify_commit(metadata: dict[str, object]) -> str | None:
    if metadata.get("verify_scope") == "scoped":
        base_commit = metadata.get("base_full_verify_commit")
        return base_commit if isinstance(base_commit, str) else None
    verified_commit = metadata.get("verified_commit")
    return verified_commit if isinstance(verified_commit, str) else None


def _fulfillment_rows(markdown: str) -> list[_ReportRow]:
    rows: list[_ReportRow] = []
    for line in _strip_frontmatter(markdown).splitlines():
        row = _fulfillment_row(line)
        if row is not None:
            rows.append(row)
    return rows


def _fulfillment_row(line: str) -> _ReportRow | None:
    stripped = line.strip()
    if not stripped.startswith("|") or "---" in stripped:
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if len(cells) < 3 or cells[0] == "ID" or not _REQ_ID_RE.match(cells[0]):
        return None
    return _ReportRow(item_id=cells[0], evidence=cells[2], line=line)


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1)


def _frontmatter(metadata: dict[str, object]) -> str:
    lines = ["---"]
    for key, value in metadata.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"- {item}")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"
