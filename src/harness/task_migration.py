"""Migrate legacy tasks.md task markers to canonical task rows."""

from __future__ import annotations

import re

from kernel.task_contract import TASK_ID_PATTERN, parse_task_rows


_LEGACY_TASK_ID_PATTERN = rf"(?:T-?\d{{3,4}}|{TASK_ID_PATTERN})"
_HEADING_RE = re.compile(
    rf"^(?P<level>#{{1,6}})\s+(?P<task_id>{_LEGACY_TASK_ID_PATTERN})\s*[:\-]?\s*(?P<title>.*)$"
)
_CHECKBOX_RE = re.compile(
    rf"^- \[(?P<status>[ xX])\]\s+(?P<task_id>{_LEGACY_TASK_ID_PATTERN})\b\s*[:\-]?\s*(?P<title>.*)$"
)


def migrate_tasks_markdown(markdown: str) -> str:
    """Return markdown with legacy task headings/checklists converted to canonical rows."""
    migrated: list[str] = []

    for line in markdown.splitlines(keepends=True):
        body = line.rstrip("\n")
        newline = "\n" if line.endswith("\n") else ""

        if parse_task_rows(body):
            migrated.append(line)
            continue

        checkbox = _CHECKBOX_RE.match(body)
        if checkbox is not None:
            migrated.extend(_canonical_block(checkbox.groupdict(), newline))
            continue

        heading = _HEADING_RE.match(body)
        if heading is not None:
            migrated.extend(_canonical_block(heading.groupdict() | {"status": " "}, newline))
            continue

        migrated.append(line)

    return "".join(migrated)


def _canonical_block(data: dict[str, str], newline: str) -> list[str]:
    status = data["status"]
    task_id = _normalize_task_id(data["task_id"])
    title = data["title"].strip()
    parallel = title.endswith("[P]")
    if parallel:
        title = title.removesuffix("[P]").rstrip()
    parallel_marker = " [P]" if parallel else ""
    row = (
        f"- [{status}] {task_id}{parallel_marker} "
        "complexity=standard phase=legacy req=UNMAPPED depends=none"
    )
    if not title:
        return [row + newline]
    return [row + "\n", "\n", f"  **Title:** {title}{newline}"]


def _normalize_task_id(task_id: str) -> str:
    if "-" in task_id:
        return task_id
    return f"T-{task_id[1:]}"
