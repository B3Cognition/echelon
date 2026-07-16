"""Deterministic task-to-source ownership for workspace delivery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from kernel.task_contract import parse_task_rows


_TASK_ROW_RE = re.compile(r"^- \[[ xX]\] (?P<task_id>T-[A-Za-z0-9-]+)\b")
_SOURCE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<target>sources/[A-Za-z0-9._-]+)(?=/|`|\s|$)"
)


@dataclass(frozen=True)
class TaskTargetAnalysis:
    target_tasks: dict[str, tuple[str, ...]]
    unowned_tasks: tuple[str, ...]
    cross_target_tasks: dict[str, tuple[str, ...]]
    all_task_ids: tuple[str, ...]
    task_titles: dict[str, str]
    path_target_mismatches: dict[str, tuple[str, tuple[str, ...]]]


@dataclass(frozen=True)
class TaskTargetValidation:
    valid: bool
    target_tasks: dict[str, tuple[str, ...]]
    missing_targets: tuple[str, ...]
    unreferenced_targets: tuple[str, ...]
    unowned_tasks: tuple[str, ...]
    cross_target_tasks: dict[str, tuple[str, ...]]
    task_titles: dict[str, str]
    path_target_mismatches: dict[str, tuple[str, tuple[str, ...]]]


def analyze_task_targets(markdown: str) -> TaskTargetAnalysis:
    """Map canonical task blocks to workspace ``sources/<id>`` paths."""
    blocks = _task_blocks(markdown)
    target_tasks: dict[str, list[str]] = {}
    unowned: list[str] = []
    cross_target: dict[str, tuple[str, ...]] = {}
    task_titles: dict[str, str] = {}
    path_target_mismatches: dict[str, tuple[str, tuple[str, ...]]] = {}

    for task_id, block in blocks:
        task_titles[task_id] = _task_title(block)
        files_section = _task_files_section(block)
        file_targets = tuple(
            sorted(
                {
                    match.group("target")
                    for match in _SOURCE_PATH_RE.finditer(files_section)
                }
            )
        )
        rows = parse_task_rows(block)
        explicit_target = _normalize_target(rows[0].target) if rows and rows[0].target else ""
        if explicit_target:
            mismatched = tuple(target for target in file_targets if target != explicit_target)
            if mismatched:
                path_target_mismatches[task_id] = (explicit_target, mismatched)
            if len(file_targets) > 1:
                cross_target[task_id] = file_targets
            else:
                target_tasks.setdefault(explicit_target, []).append(task_id)
        elif not file_targets:
            unowned.append(task_id)
        else:
            # Legacy task paths are diagnostic evidence only. They must not
            # become implementation ownership implicitly.
            unowned.append(task_id)
            if len(file_targets) > 1:
                cross_target[task_id] = file_targets

    return TaskTargetAnalysis(
        target_tasks={target: tuple(task_ids) for target, task_ids in sorted(target_tasks.items())},
        unowned_tasks=tuple(unowned),
        cross_target_tasks=cross_target,
        all_task_ids=tuple(task_id for task_id, _block in blocks),
        task_titles=task_titles,
        path_target_mismatches=path_target_mismatches,
    )


def validate_task_targets(
    markdown: str,
    *,
    declared_targets: Iterable[str],
    allow_legacy_single_target: bool = True,
) -> TaskTargetValidation:
    """Reconcile task-owned source roots with targets declared for the spec."""
    declared = tuple(sorted({_normalize_target(target) for target in declared_targets if str(target).strip()}))
    analysis = analyze_task_targets(markdown)
    referenced = set(analysis.target_tasks)
    declared_set = set(declared)
    multi_source = len(referenced | declared_set) > 1

    target_tasks = dict(analysis.target_tasks)
    unowned = analysis.unowned_tasks
    if (
        allow_legacy_single_target
        and not multi_source
        and len(declared) == 1
        and not analysis.cross_target_tasks
    ):
        only_target = declared[0]
        assigned = list(target_tasks.get(only_target, ()))
        assigned.extend(task_id for task_id in unowned if task_id not in assigned)
        target_tasks = {only_target: tuple(assigned)}
        unowned = ()

    missing = tuple(sorted(referenced - declared_set))
    unreferenced = tuple(sorted(declared_set - referenced)) if referenced else ()
    valid = (
        not missing
        and not unreferenced
        and not unowned
        and not analysis.cross_target_tasks
        and not analysis.path_target_mismatches
    )
    if (
        allow_legacy_single_target
        and not referenced
        and len(declared) == 1
        and not analysis.cross_target_tasks
    ):
        valid = not analysis.path_target_mismatches

    return TaskTargetValidation(
        valid=valid,
        target_tasks=target_tasks,
        missing_targets=missing,
        unreferenced_targets=unreferenced,
        unowned_tasks=unowned,
        cross_target_tasks=analysis.cross_target_tasks,
        task_titles=analysis.task_titles,
        path_target_mismatches=analysis.path_target_mismatches,
    )


def _task_blocks(markdown: str) -> list[tuple[str, str]]:
    lines = markdown.splitlines()
    starts: list[tuple[int, str]] = []
    in_fence = False
    for index, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _TASK_ROW_RE.match(line)
        if match is not None:
            starts.append((index, match.group("task_id")))

    blocks: list[tuple[str, str]] = []
    for position, (start, task_id) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        blocks.append((task_id, "\n".join(lines[start:end])))
    return blocks


def _normalize_target(target: object) -> str:
    value = str(target).strip().replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value.rstrip("/") or "."


def _task_files_section(block: str) -> str:
    lines = block.splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if line.strip() == "**Files:**":
            start = index + 1
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("**") and stripped.endswith(":**"):
            end = index
            break
    return "\n".join(lines[start:end])


def _task_title(block: str) -> str:
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("**Title:**"):
            return stripped.split("**Title:**", 1)[1].strip()
    return ""
