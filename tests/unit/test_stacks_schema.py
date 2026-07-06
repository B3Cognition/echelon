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
