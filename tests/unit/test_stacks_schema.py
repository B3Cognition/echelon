from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks.errors import StackValidationError
from harness.stacks.schema import parse_stack_definition


VALID_STACK = {
    "schema_version": "1.0",
    "stack": {
        "id": "example-web",
        "name": "Example Web",
        "version": "1.0.0",
        "kind": "capability",
        "owner": "example",
        "description": "Example stack",
    },
    "applies_to": {"archetypes": ["web_app"]},
    "provides": {"ui.components": "example"},
    "requires": {"commands": ["npx"], "registries": ["example-registry"]},
    "tools": {
        "example_cli": {
            "type": "cli",
            "command": "npx",
            "args": ["-y", "example"],
            "phase_scope": ["spec", "delivery"],
            "purpose": "lookup",
            "commands": {
                "list": {
                    "args": ["list", "--json"],
                    "output": "json",
                    "gate": False,
                }
            },
        }
    },
    "context": {"files": ["context.md"]},
    "implies": [],
    "conflicts": [],
}


@pytest.mark.unit
def test_parse_valid_stack_definition() -> None:
    stack = parse_stack_definition(VALID_STACK, Path("stack.yml"))

    assert stack.id == "example-web"
    assert stack.kind == "capability"
    assert stack.applies_to_archetypes == ["web_app"]
    assert stack.provides == {"ui.components": "example"}
    assert stack.tools["example_cli"].command == "npx"
    assert stack.tools["example_cli"].commands["list"].output == "json"


@pytest.mark.unit
def test_rejects_unknown_core_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"unknown.capability": "value"}}

    with pytest.raises(StackValidationError, match="unknown capability namespace"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_allows_extension_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"x.example.capability": "value"}}

    stack = parse_stack_definition(raw, Path("stack.yml"))

    assert stack.provides == {"x.example.capability": "value"}


@pytest.mark.unit
def test_rejects_invalid_kind() -> None:
    raw = {
        **VALID_STACK,
        "stack": {**VALID_STACK["stack"], "kind": "template"},
    }

    with pytest.raises(StackValidationError, match="kind"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_missing_context_files() -> None:
    raw = {**VALID_STACK, "context": {"files": []}}

    with pytest.raises(StackValidationError, match="context.files"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_invalid_phase_scope() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "phase_scope": ["spec", "qa"],
            }
        },
    }

    with pytest.raises(StackValidationError, match="phase_scope"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_unsupported_schema_version() -> None:
    raw = {**VALID_STACK, "schema_version": "2.0"}

    with pytest.raises(StackValidationError, match="unsupported stack schema_version"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_schema_version() -> None:
    raw = {**VALID_STACK, "schema_version": 1.0}

    with pytest.raises(StackValidationError, match="schema_version must be a string"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_stack_id() -> None:
    raw = {**VALID_STACK, "stack": {**VALID_STACK["stack"], "id": 123}}

    with pytest.raises(StackValidationError, match="stack.id"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_archetype_entry() -> None:
    raw = {**VALID_STACK, "applies_to": {"archetypes": [False]}}

    with pytest.raises(StackValidationError, match="applies_to.archetypes"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_requires_command_entry() -> None:
    raw = {**VALID_STACK, "requires": {"commands": [7]}}

    with pytest.raises(StackValidationError, match="requires.commands"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_empty_applies_to_archetypes() -> None:
    raw = {**VALID_STACK, "applies_to": {"archetypes": []}}

    with pytest.raises(StackValidationError, match="at least one archetype"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_empty_provides() -> None:
    raw = {**VALID_STACK, "provides": {}}

    with pytest.raises(StackValidationError, match="at least one capability"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_capability_value() -> None:
    raw = {**VALID_STACK, "provides": {"ui.components": 123}}

    with pytest.raises(StackValidationError, match="provides.ui.components"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_owner() -> None:
    raw = {**VALID_STACK, "stack": {**VALID_STACK["stack"], "owner": 123}}

    with pytest.raises(StackValidationError, match="stack.owner"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_description() -> None:
    raw = {
        **VALID_STACK,
        "stack": {**VALID_STACK["stack"], "description": {"text": "value"}},
    }

    with pytest.raises(StackValidationError, match="stack.description"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_tool_type() -> None:
    raw = {**VALID_STACK, "tools": {"example_cli": {"type": 1, "command": "npx"}}}

    with pytest.raises(StackValidationError, match="tools.example_cli.type"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_tool_purpose() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "purpose": [],
            }
        },
    }

    with pytest.raises(StackValidationError, match="tools.example_cli.purpose"):
        parse_stack_definition(raw, Path("stack.yml"))


@pytest.mark.unit
def test_rejects_non_string_command_output() -> None:
    raw = {
        **VALID_STACK,
        "tools": {
            "example_cli": {
                "type": "cli",
                "command": "npx",
                "commands": {"list": {"output": 5}},
            }
        },
    }

    with pytest.raises(StackValidationError, match="tools.example_cli.commands.list.output"):
        parse_stack_definition(raw, Path("stack.yml"))
