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
VALID_DETECTION_SECTIONS = {"positive", "negative", "modernization"}
VALID_DETECTION_RULE_FIELDS = {"technologies", "dependencies", "files"}


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
class StackDetectionRuleSet:
    technologies: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "technologies": self.technologies,
            "dependencies": self.dependencies,
            "files": self.files,
        }


@dataclass(frozen=True)
class StackDetection:
    positive: StackDetectionRuleSet = field(default_factory=StackDetectionRuleSet)
    negative: StackDetectionRuleSet = field(default_factory=StackDetectionRuleSet)
    modernization: StackDetectionRuleSet = field(default_factory=StackDetectionRuleSet)

    def to_dict(self) -> dict[str, dict[str, list[str]]]:
        return {
            "positive": self.positive.to_dict(),
            "negative": self.negative.to_dict(),
            "modernization": self.modernization.to_dict(),
        }


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
    detection: StackDetection = field(default_factory=StackDetection)


def parse_stack_definition(raw: dict[str, Any], source_path: Path) -> StackDefinition:
    _mapping(raw, source_path, "root")
    schema_version = _required_literal_str(
        raw.get("schema_version", ""),
        source_path,
        "schema_version",
        expected="1.0",
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
        provides[capability] = _non_empty_str(
            value, source_path, f"provides.{capability}"
        )
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
        owner=_optional_str(stack_raw.get("owner"), source_path, "stack.owner"),
        description=_optional_str(
            stack_raw.get("description"), source_path, "stack.description"
        ),
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
        detection=_parse_detection(raw.get("detection", {}), source_path),
        tools=_parse_tools(raw.get("tools", {}), source_path),
        context_files=context_files,
    )


def _parse_detection(value: Any, source_path: Path) -> StackDetection:
    if value is None:
        return StackDetection()
    detection_raw = _mapping(value, source_path, "detection")
    for section in detection_raw:
        if section not in VALID_DETECTION_SECTIONS:
            raise StackValidationError(
                f"unknown detection section: {section}",
                path=source_path,
                field_path=f"detection.{section}",
            )

    return StackDetection(
        positive=_parse_detection_rule_set(
            detection_raw.get("positive", {}), source_path, "detection.positive"
        ),
        negative=_parse_detection_rule_set(
            detection_raw.get("negative", {}), source_path, "detection.negative"
        ),
        modernization=_parse_detection_rule_set(
            detection_raw.get("modernization", {}),
            source_path,
            "detection.modernization",
        ),
    )


def _parse_detection_rule_set(
    value: Any,
    source_path: Path,
    field_path: str,
) -> StackDetectionRuleSet:
    if value is None:
        return StackDetectionRuleSet()
    rules_raw = _mapping(value, source_path, field_path)
    for rule_field in rules_raw:
        if rule_field not in VALID_DETECTION_RULE_FIELDS:
            raise StackValidationError(
                f"unknown detection rule field: {rule_field}",
                path=source_path,
                field_path=f"{field_path}.{rule_field}",
            )
    return StackDetectionRuleSet(
        technologies=_string_list(
            rules_raw.get("technologies", []), source_path, f"{field_path}.technologies"
        ),
        dependencies=_string_list(
            rules_raw.get("dependencies", []), source_path, f"{field_path}.dependencies"
        ),
        files=_string_list(rules_raw.get("files", []), source_path, f"{field_path}.files"),
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
            type=_optional_str(
                tool_raw.get("type"), source_path, f"tools.{tool_id}.type", default="cli"
            ),
            command=_non_empty_str(
                tool_raw.get("command"), source_path, f"tools.{tool_id}.command"
            ),
            args=_string_list(tool_raw.get("args", []), source_path, f"tools.{tool_id}.args"),
            phase_scope=phase_scope,
            purpose=_optional_str(tool_raw.get("purpose"), source_path, f"tools.{tool_id}.purpose"),
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
            output=_optional_str(
                command_raw.get("output"),
                source_path,
                f"tools.{tool_id}.commands.{command_id}.output",
                default="text",
            ),
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
    if not isinstance(value, str):
        raise StackValidationError(
            f"{field_path} must be a string",
            path=source_path,
            field_path=field_path,
        )
    result = value.strip()
    if not result:
        raise StackValidationError(
            f"{field_path} must be a non-empty string",
            path=source_path,
            field_path=field_path,
        )
    return result


def _optional_str(
    value: Any,
    source_path: Path,
    field_path: str,
    default: str = "",
) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise StackValidationError(
            f"{field_path} must be a string",
            path=source_path,
            field_path=field_path,
        )
    return value.strip()


def _required_literal_str(
    value: Any,
    source_path: Path,
    field_path: str,
    *,
    expected: str,
) -> str:
    if not isinstance(value, str):
        raise StackValidationError(
            f"{field_path} must be a string",
            path=source_path,
            field_path=field_path,
        )
    result = value.strip()
    if result != expected:
        raise StackValidationError(
            "unsupported stack schema_version",
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
    for item in value:
        if not isinstance(item, str):
            raise StackValidationError(
                f"{field_path} entries must be strings",
                path=source_path,
                field_path=field_path,
            )
    result = [item.strip() for item in value]
    if any(not item for item in result):
        raise StackValidationError(
            f"{field_path} entries must be non-empty strings",
            path=source_path,
            field_path=field_path,
        )
    return result
