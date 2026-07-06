from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness.stacks.errors import StackValidationError


CORE_CAPABILITY_PREFIXES = (
    "ui.",
    "web_app.",
    "service.",
    "test.",
    "lint.",
    "typecheck.",
    "delivery.",
    "observability.",
    "audit.",
    "docs.",
    "data.",
    "messaging.",
    "stream.",
    "schema.",
)

VALID_STACK_KINDS = {"archetype", "capability", "policy", "resource"}
VALID_PHASE_SCOPE = {"spec", "delivery"}


@dataclass(frozen=True)
class StackToolCommand:
    args: list[str] = field(default_factory=list)
    output: str = "text"
    gate: bool = False


@dataclass(frozen=True)
class StackTool:
    id: str
    type: str
    command: str
    args: list[str] = field(default_factory=list)
    phase_scope: list[str] = field(default_factory=list)
    purpose: str = ""
    commands: dict[str, StackToolCommand] = field(default_factory=dict)


@dataclass(frozen=True)
class StackDefinition:
    id: str
    name: str
    version: str
    kind: str
    owner: str
    description: str
    source_path: Path
    applies_to_archetypes: list[str]
    provides: dict[str, str]
    implies: list[str]
    requires_commands: list[str]
    requires_registries: list[str]
    tools: dict[str, StackTool]
    context_files: list[str]


def parse_stack_definition(raw: dict[str, Any], source_path: Path) -> StackDefinition:
    _mapping(raw, source_path, "root")
    schema_version = str(raw.get("schema_version", "")).strip()
    if schema_version != "1.0":
        raise StackValidationError(
            "unsupported stack schema_version",
            path=source_path,
            field_path="schema_version",
        )

    stack_raw = _mapping(raw.get("stack"), source_path, "stack")
    stack_id = _non_empty_str(stack_raw.get("id"), source_path, "stack.id")
    name = _non_empty_str(stack_raw.get("name"), source_path, "stack.name")
    version = _non_empty_str(stack_raw.get("version"), source_path, "stack.version")
    kind = _non_empty_str(stack_raw.get("kind"), source_path, "stack.kind")
    if kind not in VALID_STACK_KINDS:
        raise StackValidationError(
            f"invalid stack kind {kind!r}",
            path=source_path,
            field_path="stack.kind",
        )

    applies_to = _mapping(raw.get("applies_to"), source_path, "applies_to")
    archetypes = _string_list(
        applies_to.get("archetypes"), source_path, "applies_to.archetypes"
    )
    if not archetypes:
        raise StackValidationError(
            "applies_to.archetypes must contain at least one archetype",
            path=source_path,
            field_path="applies_to.archetypes",
        )

    provides_raw = _mapping(raw.get("provides"), source_path, "provides")
    provides: dict[str, str] = {}
    for key, value in provides_raw.items():
        capability = str(key).strip()
        if not capability:
            raise StackValidationError(
                "empty capability key",
                path=source_path,
                field_path="provides",
            )
        if not _known_capability(capability):
            raise StackValidationError(
                f"unknown capability namespace: {capability}",
                path=source_path,
                field_path=f"provides.{capability}",
            )
        provides[capability] = str(value).strip()
    if not provides:
        raise StackValidationError(
            "provides must contain at least one capability",
            path=source_path,
            field_path="provides",
        )

    context = _mapping(raw.get("context"), source_path, "context")
    context_files = _string_list(context.get("files"), source_path, "context.files")
    if not context_files:
        raise StackValidationError(
            "context.files must contain at least one file",
            path=source_path,
            field_path="context.files",
        )

    requires = raw.get("requires", {})
    if requires is None:
        requires = {}
    requires_map = _mapping(requires, source_path, "requires")

    return StackDefinition(
        id=stack_id,
        name=name,
        version=version,
        kind=kind,
        owner=str(stack_raw.get("owner", "")).strip(),
        description=str(stack_raw.get("description", "")).strip(),
        source_path=source_path,
        applies_to_archetypes=archetypes,
        provides=provides,
        implies=_string_list(raw.get("implies", []), source_path, "implies"),
        requires_commands=_string_list(
            requires_map.get("commands"), source_path, "requires.commands"
        ),
        requires_registries=_string_list(
            requires_map.get("registries"), source_path, "requires.registries"
        ),
        tools=_parse_tools(raw.get("tools", {}), source_path),
        context_files=context_files,
    )


def _parse_tools(value: Any, source_path: Path) -> dict[str, StackTool]:
    if value is None:
        return {}
    tools_raw = _mapping(value, source_path, "tools")
    tools: dict[str, StackTool] = {}
    for tool_id_raw, tool_raw_value in tools_raw.items():
        tool_id = str(tool_id_raw).strip()
        tool_raw = _mapping(tool_raw_value, source_path, f"tools.{tool_id}")
        phase_scope = _string_list(
            tool_raw.get("phase_scope", []),
            source_path,
            f"tools.{tool_id}.phase_scope",
        )
        invalid_scope = [scope for scope in phase_scope if scope not in VALID_PHASE_SCOPE]
        if invalid_scope:
            raise StackValidationError(
                f"invalid phase_scope values: {invalid_scope}",
                path=source_path,
                field_path=f"tools.{tool_id}.phase_scope",
            )
        tools[tool_id] = StackTool(
            id=tool_id,
            type=str(tool_raw.get("type", "cli")).strip(),
            command=_non_empty_str(
                tool_raw.get("command"), source_path, f"tools.{tool_id}.command"
            ),
            args=_string_list(tool_raw.get("args", []), source_path, f"tools.{tool_id}.args"),
            phase_scope=phase_scope,
            purpose=str(tool_raw.get("purpose", "")).strip(),
            commands=_parse_tool_commands(
                tool_raw.get("commands", {}), source_path, tool_id
            ),
        )
    return tools


def _parse_tool_commands(
    value: Any,
    source_path: Path,
    tool_id: str,
) -> dict[str, StackToolCommand]:
    if value is None:
        return {}
    commands_raw = _mapping(value, source_path, f"tools.{tool_id}.commands")
    commands: dict[str, StackToolCommand] = {}
    for command_id_raw, command_raw_value in commands_raw.items():
        command_id = str(command_id_raw).strip()
        command_raw = _mapping(
            command_raw_value, source_path, f"tools.{tool_id}.commands.{command_id}"
        )
        commands[command_id] = StackToolCommand(
            args=_string_list(
                command_raw.get("args", []),
                source_path,
                f"tools.{tool_id}.commands.{command_id}.args",
            ),
            output=str(command_raw.get("output", "text")).strip(),
            gate=bool(command_raw.get("gate", False)),
        )
    return commands


def _known_capability(capability: str) -> bool:
    return capability.startswith("x.") or capability.startswith(CORE_CAPABILITY_PREFIXES)


def _mapping(value: Any, source_path: Path, field_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StackValidationError(
            f"{field_path} must be a mapping",
            path=source_path,
            field_path=field_path,
        )
    return value


def _non_empty_str(value: Any, source_path: Path, field_path: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise StackValidationError(
            f"{field_path} must be a non-empty string",
            path=source_path,
            field_path=field_path,
        )
    return result


def _string_list(value: Any, source_path: Path, field_path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StackValidationError(
            f"{field_path} must be a list",
            path=source_path,
            field_path=field_path,
        )
    result = [str(item).strip() for item in value]
    if any(not item for item in result):
        raise StackValidationError(
            f"{field_path} entries must be non-empty strings",
            path=source_path,
            field_path=field_path,
        )
    return result
