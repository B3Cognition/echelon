"""Deterministic task requirement metadata mapping."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kernel.task_contract import parse_task_rows, validate_tasks_markdown


_REQ_ID_RE = re.compile(
    r"^(?:FR|US|AC|EDGE|NFR|SC|REQ|OQ|INV|TC)-?[A-Za-z0-9_.-]+$|^INFRA$"
)
_REQ_ID_FIND_RE = re.compile(
    r"\b(?:FR|US|AC|EDGE|NFR|SC|REQ|OQ|INV|TC)-?[A-Za-z0-9_.-]+\b|\bINFRA\b"
)
_TASK_ROW_RE = re.compile(
    r"^(?P<prefix>- \[[ xX]\]\s+(?P<task_id>T-(?:\d{3,4}|S\d{2}[A-Za-z]?))"
    r"(?:\s+\[P\])?\s+complexity=(?:trivial|standard|complex)\s+"
    r"phase=[A-Za-z0-9_.-]+\s+)req=(?P<requirements>[A-Za-z0-9_,.-]+)"
    r"(?P<suffix>\s+depends=(?:none|[A-Za-z0-9_,.-]+))$"
)


@dataclass(frozen=True)
class RequirementMappingResult:
    safe_count: int
    applied_count: int
    skipped_count: int


@dataclass(frozen=True)
class _Mapping:
    task_id: str
    requirements: tuple[str, ...]
    evidence: str
    reason: str


def write_task_requirement_mapping_candidates(
    *,
    tasks_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    """Write conservative req= metadata candidates from explicit task text IDs."""
    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    validation = validate_tasks_markdown(markdown)
    if not validation.valid:
        raise ValueError(f"invalid tasks.md: {'; '.join(validation.errors)}")

    task_blocks = _task_blocks(markdown)
    mappings: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []

    for task in parse_task_rows(markdown):
        if task.requirements != ["UNMAPPED"]:
            continue
        requirement_ids = _explicit_requirement_ids(task_blocks.get(task.task_id, ""))
        if requirement_ids:
            joined = ", ".join(requirement_ids)
            mappings.append(
                {
                    "task_id": task.task_id,
                    "requirements": requirement_ids,
                    "evidence": f"tasks.md#{task.task_id} explicit requirement IDs: {joined}",
                    "reason": "task text explicitly names mapped requirement IDs",
                }
            )
        else:
            ambiguous.append(
                {
                    "task_id": task.task_id,
                    "requirements": [],
                    "evidence": f"tasks.md#{task.task_id}",
                    "reason": "task has req=UNMAPPED and no explicit requirement IDs in task text",
                }
            )

    payload = {
        "task_requirement_mappings": mappings,
        "ambiguous_task_requirement_mappings": ambiguous,
    }
    _write_json(out_path, payload)
    return payload


def apply_task_requirement_mapping(
    *,
    tasks_path: Path,
    candidate_path: Path,
    out_plan_json: Path,
    out_plan_md: Path,
    dry_run: bool,
    out_applied_json: Path | None = None,
    out_applied_md: Path | None = None,
) -> RequirementMappingResult:
    """Validate candidate task requirement metadata and optionally apply it."""
    candidate = _load_candidate(candidate_path)
    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    validation = validate_tasks_markdown(markdown)
    if not validation.valid:
        raise ValueError(f"invalid tasks.md: {'; '.join(validation.errors)}")

    known_task_ids = {task.task_id for task in parse_task_rows(markdown)}
    mappings = _candidate_mappings(candidate.get("task_requirement_mappings", []))
    safe: list[_Mapping] = []
    skipped: list[dict[str, str]] = []

    for mapping in mappings:
        skip_reason = _skip_reason(mapping, known_task_ids)
        if skip_reason:
            skipped.append(_skip_payload(mapping, skip_reason))
        else:
            safe.append(mapping)

    plan_payload = _report_payload(safe, skipped, dry_run=dry_run)
    _write_json(out_plan_json, plan_payload)
    _write_text(out_plan_md, _render_markdown("Task Requirement Mapping Plan", plan_payload))

    applied: list[_Mapping] = []
    if not dry_run:
        updated = markdown
        for mapping in safe:
            updated = _update_task_requirements(updated, mapping)
            applied.append(mapping)

        applied_validation = validate_tasks_markdown(updated)
        if not applied_validation.valid:
            raise ValueError(
                f"invalid mapped tasks.md: {'; '.join(applied_validation.errors)}"
            )

        tasks_path.write_text(updated, encoding="utf-8")
        applied_payload = _report_payload(applied, skipped, dry_run=False, applied=True)
        if out_applied_json is None or out_applied_md is None:
            raise ValueError("apply mode requires applied output paths")
        _write_json(out_applied_json, applied_payload)
        _write_text(
            out_applied_md,
            _render_markdown("Task Requirement Mapping Applied", applied_payload),
        )

    return RequirementMappingResult(
        safe_count=len(safe),
        applied_count=len(applied),
        skipped_count=len(skipped),
    )


def _task_blocks(markdown: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current_task_id: str | None = None
    in_fence = False
    for line in markdown.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _TASK_ROW_RE.match(line.rstrip())
        if match:
            current_task_id = match.group("task_id")
            blocks[current_task_id] = [line]
            continue
        if current_task_id is not None:
            blocks[current_task_id].append(line)
    return {task_id: "\n".join(lines) for task_id, lines in blocks.items()}


def _explicit_requirement_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for match in _REQ_ID_FIND_RE.finditer(text):
        requirement_id = match.group(0)
        if requirement_id == "UNMAPPED" or requirement_id in seen:
            continue
        seen.add(requirement_id)
        ids.append(requirement_id)
    return ids


def _load_candidate(candidate_path: Path) -> dict[str, Any]:
    data = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("task requirement mapping candidate file must be a JSON object")
    return data


def _candidate_mappings(value: object) -> list[_Mapping]:
    mappings: list[_Mapping] = []
    for item in _list(value):
        raw_requirements = item.get("requirements", [])
        if isinstance(raw_requirements, str):
            requirements = tuple(_split_csv(raw_requirements))
        elif isinstance(raw_requirements, list):
            requirements = tuple(str(req).strip() for req in raw_requirements if str(req).strip())
        else:
            requirements = ()
        mappings.append(
            _Mapping(
                task_id=str(item.get("task_id", "")).strip(),
                requirements=requirements,
                evidence=str(item.get("evidence", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return mappings


def _skip_reason(mapping: _Mapping, known_task_ids: set[str]) -> str | None:
    if not mapping.task_id:
        return "missing task id"
    if mapping.task_id not in known_task_ids:
        return "unknown task id"
    if not mapping.requirements:
        return "missing requirements"
    for requirement in mapping.requirements:
        if not _REQ_ID_RE.match(requirement):
            return f"invalid requirement id: {requirement}"
    if not mapping.evidence:
        return "missing evidence"
    if not mapping.reason:
        return "missing reason"
    return None


def _update_task_requirements(markdown: str, mapping: _Mapping) -> str:
    replacement = ",".join(mapping.requirements)
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        match = _TASK_ROW_RE.match(line)
        if match is None or match.group("task_id") != mapping.task_id:
            continue
        lines[index] = f"{match.group('prefix')}req={replacement}{match.group('suffix')}"
        return "\n".join(lines) + ("\n" if markdown.endswith("\n") else "")
    raise ValueError(f"task id not found while applying mapping: {mapping.task_id}")


def _report_payload(
    safe: list[_Mapping],
    skipped: list[dict[str, str]],
    *,
    dry_run: bool,
    applied: bool = False,
) -> dict[str, Any]:
    return {
        "mode": "dry_run" if dry_run else "apply",
        "applied": applied,
        "safe_task_requirement_mappings": [_mapping_payload(mapping) for mapping in safe],
        "skipped_task_requirement_mappings": skipped,
    }


def _mapping_payload(mapping: _Mapping) -> dict[str, str]:
    return {
        "task_id": mapping.task_id,
        "requirements": ",".join(mapping.requirements),
        "evidence": mapping.evidence,
        "reason": mapping.reason,
    }


def _skip_payload(mapping: _Mapping, reason: str) -> dict[str, str]:
    payload = _mapping_payload(mapping)
    payload["skip_reason"] = reason
    return payload


def _render_markdown(title: str, payload: dict[str, Any]) -> str:
    lines = [
        f"# {title}",
        "",
        f"Mode: {payload['mode']}",
        "",
        "## Safe Task Requirement Mappings",
        *_bullet_rows(payload["safe_task_requirement_mappings"]),
        "",
        "## Skipped Task Requirement Mappings",
        *_bullet_rows(payload["skipped_task_requirement_mappings"], include_skip=True),
        "",
    ]
    return "\n".join(lines)


def _bullet_rows(rows: object, *, include_skip: bool = False) -> list[str]:
    items = _list(rows)
    if not items:
        return ["- None"]
    rendered: list[str] = []
    for item in items:
        parts = [
            f"- {item.get('task_id', '(unknown)')}",
            f"requirements: {item.get('requirements', '')}",
            f"evidence: {item.get('evidence', '')}",
        ]
        if include_skip:
            parts.append(f"skip: {item.get('skip_reason', '')}")
        reason = item.get("reason", "")
        if reason:
            parts.append(f"reason: {reason}")
        rendered.append("; ".join(parts))
    return rendered


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]
