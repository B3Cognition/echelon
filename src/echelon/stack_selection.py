"""Read, validate, and persist explicit Echelon stack selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import yaml

from harness.config import (
    CANONICAL_CONFIG_PATH,
    CANONICAL_LOCAL_CONFIG_PATH,
    get_full_resolved_config,
)
from harness.stacks import resolve_stacks
from harness.stacks.schema import StackDefinition


class StackSelectionError(Exception):
    """Raised when a persistent stack-selection change is unsafe or invalid."""


@dataclass(frozen=True)
class StackSelection:
    explicit: list[str]
    effective: list[str]
    resolved: list[str]
    local_override: bool


def change_stack_selection(
    project_root: Path,
    stack_ids: list[str],
    definitions: dict[str, StackDefinition],
    *,
    operation: str,
    dry_run: bool = False,
) -> StackSelection:
    """Validate and optionally persist one explicit stack-selection mutation."""
    config_path, raw = _read_canonical_config(project_root)
    existing = _selected_stack_ids(raw)
    if operation == "enable":
        selected = list(existing)
        for stack_id in stack_ids:
            if stack_id not in selected:
                selected.append(stack_id)
    elif operation == "disable":
        removed = set(stack_ids)
        selected = [stack_id for stack_id in existing if stack_id not in removed]
    elif operation == "select":
        selected = _unique_stack_ids(stack_ids)
    else:
        raise ValueError(f"unsupported stack selection operation: {operation}")
    resolve_stacks(selected, definitions, target_archetypes=_target_archetypes(raw))
    if not dry_run:
        _write_selected_stack_ids(config_path, raw, selected)
    return _selection_status(project_root, definitions, explicit=selected)


def get_stack_selection(
    project_root: Path,
    definitions: dict[str, StackDefinition],
) -> StackSelection:
    """Return explicit project selection and resolved effective selection."""
    _, raw = _read_canonical_config(project_root)
    return _selection_status(project_root, definitions, explicit=_selected_stack_ids(raw))


def _selection_status(
    project_root: Path,
    definitions: dict[str, StackDefinition],
    *,
    explicit: list[str],
) -> StackSelection:
    resolved_config = get_full_resolved_config(project_root)
    effective = _selected_stack_ids(resolved_config)
    resolved = resolve_stacks(
        effective,
        definitions,
        target_archetypes=_target_archetypes(resolved_config),
    )
    local_path = project_root / CANONICAL_LOCAL_CONFIG_PATH
    local = _read_yaml_mapping(local_path) if local_path.is_file() else {}
    local_stacks = local.get("stacks")
    local_override = isinstance(local_stacks, dict) and "selected" in local_stacks
    return StackSelection(
        explicit=explicit,
        effective=effective,
        resolved=resolved.resolved_ids,
        local_override=local_override,
    )


def _read_canonical_config(project_root: Path) -> tuple[Path, dict[str, Any]]:
    config_path = project_root / CANONICAL_CONFIG_PATH
    if not config_path.is_file():
        raise StackSelectionError(
            f"Project config not found: {config_path}. Run `echelon workspace init` first."
        )
    return config_path, _read_yaml_mapping(config_path)


def _read_yaml_mapping(config_path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise StackSelectionError(f"Cannot parse project config: {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise StackSelectionError(f"Project config must be a mapping: {config_path}")
    return raw


def _write_selected_stack_ids(
    config_path: Path,
    raw: dict[str, Any],
    selected: list[str],
) -> None:
    """Replace only ``stacks.selected`` so project-owned YAML stays intact."""
    lines = config_path.read_text(encoding="utf-8").splitlines(keepends=True)
    stack_index = _find_stacks_section(lines)
    rendered = _render_selected_stack_ids("  ", selected)
    if stack_index is None:
        suffix = "" if not lines or lines[-1].endswith("\n") else "\n"
        lines.extend([suffix, "stacks:\n", *rendered])
    elif _is_flow_stacks_line(lines[stack_index]):
        stacks = raw.get("stacks")
        if not isinstance(stacks, dict):
            raise StackSelectionError("stacks must be a mapping")
        updated = dict(stacks)
        updated["selected"] = selected
        lines[stack_index : stack_index + 1] = yaml.safe_dump(
            {"stacks": updated},
            sort_keys=False,
        ).splitlines(keepends=True)
    elif _is_null_stacks_line(lines[stack_index]):
        lines[stack_index : stack_index + 1] = ["stacks:\n", *rendered]
    else:
        section_end = _section_end(lines, stack_index)
        child_indent = _direct_child_indent(lines, stack_index + 1, section_end)
        selected_index = _find_selected_line(
            lines,
            stack_index + 1,
            section_end,
            child_indent,
        )
        if selected_index is None:
            lines[stack_index + 1 : stack_index + 1] = rendered
        else:
            indent = re.match(r"^(\s*)", lines[selected_index]).group(1)
            end = _selected_value_end(lines, selected_index + 1, section_end, len(indent))
            lines[selected_index:end] = _render_selected_stack_ids(indent, selected)
    config_path.write_text("".join(lines), encoding="utf-8")


def _find_stacks_section(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if re.match(r"^stacks:\s*(?:#.*)?$", line):
            return index
        if re.match(r"^stacks:\s*(?:null|~)\s*(?:#.*)?$", line):
            return index
        if _is_flow_stacks_line(line):
            return index
    return None


def _is_null_stacks_line(line: str) -> bool:
    return bool(re.match(r"^stacks:\s*(?:null|~)\s*(?:#.*)?$", line))


def _is_flow_stacks_line(line: str) -> bool:
    return bool(re.match(r"^stacks:\s*\{.*}\s*(?:#.*)?$", line))


def _section_end(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and not line.startswith((" ", "\t")):
            return index
    return len(lines)


def _direct_child_indent(lines: list[str], start: int, end: int) -> int | None:
    for index in range(start, end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            return len(line) - len(line.lstrip(" \t"))
    return None


def _find_selected_line(
    lines: list[str],
    start: int,
    end: int,
    direct_indent: int | None,
) -> int | None:
    if direct_indent is None:
        return None
    for index in range(start, end):
        line = lines[index]
        indent = len(line) - len(line.lstrip(" \t"))
        if indent == direct_indent and re.match(r"^\s*selected:\s*.*$", line):
            return index
    return None


def _selected_value_end(lines: list[str], start: int, end: int, indent: int) -> int:
    for index in range(start, end):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#"):
            current_indent = len(line) - len(line.lstrip(" \t"))
            if current_indent < indent or (
                current_indent == indent and not line.lstrip().startswith("-")
            ):
                return index
    return end


def _render_selected_stack_ids(indent: str, selected: list[str]) -> list[str]:
    if not selected:
        return [f"{indent}selected: []\n"]
    return [f"{indent}selected:\n", *(f"{indent}- {stack_id}\n" for stack_id in selected)]


def _selected_stack_ids(raw: dict[str, Any]) -> list[str]:
    stacks = raw.get("stacks", {})
    if stacks is None:
        stacks = {}
    if not isinstance(stacks, dict):
        raise StackSelectionError("stacks must be a mapping")
    selected = stacks.get("selected", [])
    if selected is None:
        selected = []
    if not isinstance(selected, list) or not all(
        isinstance(stack_id, str) and stack_id.strip() for stack_id in selected
    ):
        raise StackSelectionError("stacks.selected must be a list of non-empty stack IDs")
    return list(selected)


def _target_archetypes(raw: dict[str, Any]) -> set[str] | None:
    stacks = raw.get("stacks", {})
    if stacks is None:
        stacks = {}
    if not isinstance(stacks, dict):
        raise StackSelectionError("stacks must be a mapping")
    archetypes = stacks.get("target_archetypes", [])
    if archetypes is None:
        archetypes = []
    if not isinstance(archetypes, list) or not all(
        isinstance(archetype, str) and archetype.strip() for archetype in archetypes
    ):
        raise StackSelectionError(
            "stacks.target_archetypes must be a list of non-empty archetype IDs"
        )
    return set(archetypes) or None


def _unique_stack_ids(stack_ids: list[str]) -> list[str]:
    selected: list[str] = []
    for stack_id in stack_ids:
        if stack_id not in selected:
            selected.append(stack_id)
    return selected
