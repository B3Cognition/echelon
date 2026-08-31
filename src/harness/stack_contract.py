"""Immutable selected-stack context for one Phase A run."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from echelon.stack_selection import StackSelection
from harness.stacks import resolve_stacks, resolved_to_dict
from harness.stacks.schema import StackDefinition


STACK_CONTRACT_SCHEMA_VERSION = 1
MAX_STACK_CONTEXT_FILE_BYTES = 128 * 1024


class StackContractError(ValueError):
    """Raised when selected stack guidance cannot be frozen safely."""


def build_stack_contract(
    selection: StackSelection,
    definitions: Mapping[str, StackDefinition],
) -> dict[str, object]:
    """Return a fully serializable snapshot of the selected stack semantics."""
    resolved = resolve_stacks(selection.effective, dict(definitions))
    context_files = [_freeze_context_file(Path(path)) for path in resolved.context_files]
    stacks = [
        _stack_semantics(definitions[stack_id])
        for stack_id in resolved.resolved_ids
    ]
    return {
        "schema_version": STACK_CONTRACT_SCHEMA_VERSION,
        "explicit_ids": list(selection.explicit),
        "effective_ids": list(selection.effective),
        "resolved_ids": list(resolved.resolved_ids),
        "implied_by": dict(resolved.implied_by),
        "stacks": stacks,
        "resolved": resolved_to_dict(resolved),
        "context_files": context_files,
    }


def render_stack_contract(contract: object) -> str:
    """Render a stored contract without consulting workspace stack files."""
    if not isinstance(contract, Mapping):
        return ""
    resolved_ids = contract.get("resolved_ids")
    if not isinstance(resolved_ids, list):
        return ""
    lines = ["## Selected Stack Contract", ""]
    if not resolved_ids:
        lines.extend(["No Echelon stack is selected for this run.", ""])
        return "\n".join(lines)
    lines.extend([
        "This controller-owned snapshot governs product shape, constitution, ",
        "requirements, architecture, implementation planning, and tests.",
        "Do not infer a conflicting stack or replace these constraints.",
        "",
        "### Resolved stacks",
        "",
    ])
    for stack in contract.get("stacks", []):
        if not isinstance(stack, Mapping):
            continue
        stack_id = stack.get("id")
        if not isinstance(stack_id, str):
            continue
        description = stack.get("description")
        version = stack.get("version")
        suffix = f" v{version}" if isinstance(version, str) and version else ""
        lines.append(f"- {stack_id}{suffix}: {description or 'No description provided.'}")
    context_files = contract.get("context_files")
    if isinstance(context_files, list) and context_files:
        lines.extend(["", "### Stack guidance", ""])
        for context in context_files:
            if not isinstance(context, Mapping):
                continue
            name = context.get("name")
            content = context.get("content")
            if isinstance(name, str) and isinstance(content, str):
                lines.extend([f"#### {name}", "", content, ""])
    return "\n".join(lines).rstrip() + "\n\n"


def _freeze_context_file(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise StackContractError(f"cannot read selected stack context file: {path}") from exc
    if len(raw) > MAX_STACK_CONTEXT_FILE_BYTES:
        raise StackContractError(
            f"selected stack context file exceeds {MAX_STACK_CONTEXT_FILE_BYTES} bytes: {path}"
        )
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StackContractError(f"selected stack context file is not UTF-8: {path}") from exc
    return {
        "name": path.name,
        "sha256": sha256(raw).hexdigest(),
        "content": content,
    }


def _stack_semantics(stack: StackDefinition) -> dict[str, Any]:
    return {
        "id": stack.id,
        "name": stack.name,
        "version": stack.version,
        "kind": stack.kind,
        "description": stack.description,
        "archetypes": list(stack.applies_to_archetypes),
        "provides": dict(stack.provides),
        "requires_commands": list(stack.requires_commands),
        "requires_registries": list(stack.requires_registries),
        "tools": sorted(stack.tools),
    }
