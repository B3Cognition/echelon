# Echelon Stacks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement schema-backed Echelon Stacks so selected stacks resolve into deterministic capability/tool context for Phase A and Phase B.

**Architecture:** Add a focused `harness.stacks` subsystem that validates stack definitions, resolves selected and implied stacks, detects capability conflicts, and renders machine/agent context. Keep stack definitions as data under `extension/stacks/`; integrate selected stack IDs through existing full-config loading and inject rendered context into build strategy context without changing individual agent prose.

**Tech Stack:** Python dataclasses, PyYAML, pytest, existing Echelon config cascade, existing build prompt `strategy_context`.

## Global Constraints

- Stack selection is opt-in; no selected stacks means existing Echelon behavior is unchanged.
- Do not extend speckit presets; stacks are Echelon-native.
- Agents consume generated resolved context, not raw `stack.yml` files.
- Stark implies Playbook; Playbook does not imply Stark.
- MSA must not imply Postgres, Kafka, Flink, or any other infrastructure dependency.
- Project-local stacks may add new stack IDs but may not override bundled stack IDs in the first implementation.
- Keep implementation additive and deterministic.

---

## File Structure

- Create `src/harness/stacks/schema.py`: dataclasses and strict validation helpers for stack definitions, tools, resolved capabilities, and resolved stack output.
- Create `src/harness/stacks/errors.py`: user-facing stack exception types.
- Create `src/harness/stacks/loader.py`: bundled/project-local stack discovery and YAML loading.
- Create `src/harness/stacks/resolver.py`: selected stack resolution, implication recursion, archetype checks, capability merging, conflict detection, and requirement/tool aggregation.
- Create `src/harness/stacks/renderer.py`: stable `resolved.yml` dictionary generation and `resolved.md` rendering.
- Create `src/harness/stacks/__init__.py`: public API exports.
- Modify `src/harness/config.py`: parse top-level `stacks.selected` into config data accessible to callers.
- Modify `src/harness/build_prompt.py`: accept resolved stack context and append it as a dedicated prompt section.
- Modify `src/harness/coordinator.py`: resolve stacks and pass rendered context into `strategy_context`.
- Add `extension/stacks/statsperform-playbook/stack.yml` and `context.md`.
- Add `extension/stacks/statsperform-msa-service/stack.yml` and `context.md`.
- Add `extension/stacks/statsperform-stark-webapp/stack.yml` and `context.md`.
- Modify `extension/config-template.yml` and `extension/echelon-config.yml`: document `stacks.selected: []`.
- Create `tests/unit/test_stacks_schema.py`, `tests/unit/test_stacks_resolver.py`, and `tests/unit/test_stacks_integration.py`.
- Modify `tests/unit/test_config.py`: cover parsed stack selection defaults and explicit config.

---

### Task 1: Add Stack Config Parsing

**Files:**
- Modify: `src/harness/config.py`
- Modify: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `StacksConfig(selected: List[str])`
- Produces: `HarnessConfig.stacks: StacksConfig`
- Consumes: existing `get_full_resolved_config()` and `_parse_config()`

- [ ] **Step 1: Write failing config tests**

Add these imports in `tests/unit/test_config.py`:

```python
from harness.config import (
    DEFAULT_NETWORK_ALLOWLIST,
    HarnessConfig,
    StacksConfig,
    ValidationError,
    _parse_config,
    get_full_resolved_config,
    load_config,
)
```

Add tests under `TestParseConfigValid`:

```python
    def test_stacks_default_to_empty_selection(self) -> None:
        config = _parse_config(MINIMAL)

        assert isinstance(config.stacks, StacksConfig)
        assert config.stacks.selected == []

    def test_stacks_selection_can_be_configured(self) -> None:
        config = _parse_config({
            **MINIMAL,
            "stacks": {
                "selected": [
                    "statsperform-playbook",
                    "statsperform-msa-service",
                ],
            },
        })

        assert config.stacks.selected == [
            "statsperform-playbook",
            "statsperform-msa-service",
        ]
```

Add invalid tests under `TestParseConfigInvalid`:

```python
    def test_stacks_selected_must_be_list(self) -> None:
        with pytest.raises(ValidationError, match="stacks.selected"):
            _parse_config({**MINIMAL, "stacks": {"selected": "statsperform-playbook"}})

    def test_stacks_selected_rejects_empty_ids(self) -> None:
        with pytest.raises(ValidationError, match="stacks.selected"):
            _parse_config({**MINIMAL, "stacks": {"selected": ["statsperform-playbook", " "]}})
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_config.py -q
```

Expected: FAIL because `StacksConfig` and `HarnessConfig.stacks` do not exist.

- [ ] **Step 3: Implement config dataclass and parser**

In `src/harness/config.py`, add after `FulfillmentConfig`:

```python
@dataclass
class StacksConfig:
    """Selected Echelon stacks from committed project config."""
    selected: List[str] = field(default_factory=list)
```

Add to `HarnessConfig`:

```python
    stacks: StacksConfig = field(default_factory=StacksConfig)
```

Add parser before `_parse_fulfillment`:

```python
def _parse_stacks(data: Dict[str, Any]) -> StacksConfig:
    raw = data.get("stacks", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValidationError("stacks must be a mapping", field_path="stacks")

    selected_raw = raw.get("selected", [])
    if selected_raw is None:
        selected_raw = []
    if not isinstance(selected_raw, list):
        raise ValidationError(
            "stacks.selected must be a list of stack IDs",
            field_path="stacks.selected",
        )

    selected: List[str] = []
    for index, value in enumerate(selected_raw):
        stack_id = str(value).strip()
        if not stack_id:
            raise ValidationError(
                "stacks.selected entries must be non-empty strings",
                field_path=f"stacks.selected[{index}]",
            )
        selected.append(stack_id)

    return StacksConfig(selected=selected)
```

Pass into `HarnessConfig(...)`:

```python
        stacks=_parse_stacks(data),
```

- [ ] **Step 4: Run config tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/config.py tests/unit/test_config.py
git commit -m "feat: parse selected Echelon stacks"
```

---

### Task 2: Add Stack Schema Validation

**Files:**
- Create: `src/harness/stacks/__init__.py`
- Create: `src/harness/stacks/errors.py`
- Create: `src/harness/stacks/schema.py`
- Create: `tests/unit/test_stacks_schema.py`

**Interfaces:**
- Produces: `StackDefinition`
- Produces: `StackTool`
- Produces: `parse_stack_definition(raw: dict, source_path: Path) -> StackDefinition`
- Produces: `CORE_CAPABILITY_PREFIXES`

- [ ] **Step 1: Write failing schema tests**

Create `tests/unit/test_stacks_schema.py`:

```python
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


def test_parse_valid_stack_definition() -> None:
    stack = parse_stack_definition(VALID_STACK, Path("stack.yml"))

    assert stack.id == "example-web"
    assert stack.kind == "capability"
    assert stack.applies_to_archetypes == ["web_app"]
    assert stack.provides == {"ui.components": "example"}
    assert stack.tools["example_cli"].command == "npx"
    assert stack.tools["example_cli"].commands["list"].output == "json"


def test_rejects_unknown_core_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"unknown.capability": "value"}}

    with pytest.raises(StackValidationError, match="unknown capability namespace"):
        parse_stack_definition(raw, Path("stack.yml"))


def test_allows_extension_namespace() -> None:
    raw = {**VALID_STACK, "provides": {"x.example.capability": "value"}}

    stack = parse_stack_definition(raw, Path("stack.yml"))

    assert stack.provides == {"x.example.capability": "value"}


def test_rejects_invalid_kind() -> None:
    raw = {
        **VALID_STACK,
        "stack": {**VALID_STACK["stack"], "kind": "template"},
    }

    with pytest.raises(StackValidationError, match="kind"):
        parse_stack_definition(raw, Path("stack.yml"))


def test_rejects_missing_context_files() -> None:
    raw = {**VALID_STACK, "context": {"files": []}}

    with pytest.raises(StackValidationError, match="context.files"):
        parse_stack_definition(raw, Path("stack.yml"))
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_schema.py -q
```

Expected: FAIL because `harness.stacks` does not exist.

- [ ] **Step 3: Implement stack errors**

Create `src/harness/stacks/errors.py`:

```python
from __future__ import annotations

from pathlib import Path


class StackError(Exception):
    """Base class for Echelon stack errors."""


class StackValidationError(StackError):
    """Raised when a stack definition fails schema validation."""

    def __init__(self, message: str, *, path: Path | None = None, field_path: str | None = None) -> None:
        self.path = path
        self.field_path = field_path
        super().__init__(message)

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.field_path:
            parts.append(f"field: {self.field_path}")
        if self.path:
            parts.append(f"path: {self.path}")
        return " (".join([parts[0], ", ".join(parts[1:]) + ")"]) if len(parts) > 1 else parts[0]
```

- [ ] **Step 4: Implement stack schema**

Create `src/harness/stacks/schema.py`:

```python
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
    _require_mapping(raw, "root", source_path)
    schema_version = str(raw.get("schema_version", "")).strip()
    if schema_version != "1.0":
        raise StackValidationError(
            "unsupported stack schema_version",
            path=source_path,
            field_path="schema_version",
        )

    stack_raw = _mapping(raw.get("stack"), source_path, "stack")
    stack_id = _non_empty_str(stack_raw.get("id"), source_path, "stack.id")
    kind = _non_empty_str(stack_raw.get("kind"), source_path, "stack.kind")
    if kind not in VALID_STACK_KINDS:
        raise StackValidationError(
            f"invalid stack kind {kind!r}",
            path=source_path,
            field_path="stack.kind",
        )

    applies_to = _mapping(raw.get("applies_to"), source_path, "applies_to")
    archetypes = _string_list(applies_to.get("archetypes"), source_path, "applies_to.archetypes")
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
            raise StackValidationError("empty capability key", path=source_path, field_path="provides")
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
        name=_non_empty_str(stack_raw.get("name"), source_path, "stack.name"),
        version=_non_empty_str(stack_raw.get("version"), source_path, "stack.version"),
        kind=kind,
        owner=str(stack_raw.get("owner", "")).strip(),
        description=str(stack_raw.get("description", "")).strip(),
        source_path=source_path,
        applies_to_archetypes=archetypes,
        provides=provides,
        implies=_string_list(raw.get("implies", []), source_path, "implies"),
        requires_commands=_string_list(requires_map.get("commands", []), source_path, "requires.commands"),
        requires_registries=_string_list(requires_map.get("registries", []), source_path, "requires.registries"),
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
        phase_scope = _string_list(tool_raw.get("phase_scope", []), source_path, f"tools.{tool_id}.phase_scope")
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
            command=_non_empty_str(tool_raw.get("command"), source_path, f"tools.{tool_id}.command"),
            args=_string_list(tool_raw.get("args", []), source_path, f"tools.{tool_id}.args"),
            phase_scope=phase_scope,
            purpose=str(tool_raw.get("purpose", "")).strip(),
            commands=_parse_tool_commands(tool_raw.get("commands", {}), source_path, tool_id),
        )
    return tools


def _parse_tool_commands(value: Any, source_path: Path, tool_id: str) -> dict[str, StackToolCommand]:
    if value is None:
        return {}
    commands_raw = _mapping(value, source_path, f"tools.{tool_id}.commands")
    commands: dict[str, StackToolCommand] = {}
    for command_id_raw, command_raw_value in commands_raw.items():
        command_id = str(command_id_raw).strip()
        command_raw = _mapping(command_raw_value, source_path, f"tools.{tool_id}.commands.{command_id}")
        commands[command_id] = StackToolCommand(
            args=_string_list(command_raw.get("args", []), source_path, f"tools.{tool_id}.commands.{command_id}.args"),
            output=str(command_raw.get("output", "text")).strip(),
            gate=bool(command_raw.get("gate", False)),
        )
    return commands


def _known_capability(capability: str) -> bool:
    return capability.startswith("x.") or capability.startswith(CORE_CAPABILITY_PREFIXES)


def _require_mapping(value: Any, field_path: str, source_path: Path) -> None:
    if not isinstance(value, dict):
        raise StackValidationError(
            f"{field_path} must be a mapping",
            path=source_path,
            field_path=field_path,
        )


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
```

Create `src/harness/stacks/__init__.py`:

```python
"""Echelon stack loading, validation, resolution, and rendering."""
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_schema.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/stacks tests/unit/test_stacks_schema.py
git commit -m "feat: add Echelon stack schema validation"
```

---

### Task 3: Add Stack Loader and Resolver

**Files:**
- Create: `src/harness/stacks/loader.py`
- Create: `src/harness/stacks/resolver.py`
- Create: `src/harness/stacks/renderer.py`
- Modify: `src/harness/stacks/errors.py`
- Modify: `src/harness/stacks/__init__.py`
- Create: `tests/unit/test_stacks_resolver.py`

**Interfaces:**
- Produces: `load_stack_definitions(extension_root: Path, project_root: Path) -> dict[str, StackDefinition]`
- Produces: `resolve_stacks(selected_ids: list[str], definitions: dict[str, StackDefinition], target_archetypes: set[str] | None = None) -> ResolvedStacks`
- Produces: `render_resolved_markdown(resolved: ResolvedStacks) -> str`
- Produces: `resolved_to_dict(resolved: ResolvedStacks) -> dict`

- [ ] **Step 1: Write failing resolver tests**

Create `tests/unit/test_stacks_resolver.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from harness.stacks.errors import StackConflictError, StackResolutionError
from harness.stacks.resolver import resolve_stacks
from harness.stacks.renderer import render_resolved_markdown, resolved_to_dict
from harness.stacks.schema import StackDefinition


def _stack(
    stack_id: str,
    *,
    provides: dict[str, str],
    archetypes: list[str] | None = None,
    implies: list[str] | None = None,
    context_files: list[str] | None = None,
) -> StackDefinition:
    return StackDefinition(
        id=stack_id,
        name=stack_id,
        version="1.0.0",
        kind="capability",
        owner="test",
        description="",
        source_path=Path(f"{stack_id}/stack.yml"),
        applies_to_archetypes=archetypes or ["web_app"],
        provides=provides,
        implies=implies or [],
        requires_commands=[],
        requires_registries=[],
        tools={},
        context_files=context_files or ["context.md"],
    )


def test_resolve_no_selected_stacks_is_empty() -> None:
    resolved = resolve_stacks([], {})

    assert resolved.selected_ids == []
    assert resolved.capabilities == {}


def test_resolve_implied_stack() -> None:
    definitions = {
        "stark": _stack("stark", provides={"web_app.framework": "nextjs"}, implies=["playbook"]),
        "playbook": _stack("playbook", provides={"ui.components": "playbook"}),
    }

    resolved = resolve_stacks(["stark"], definitions, target_archetypes={"web_app"})

    assert resolved.selected_ids == ["stark"]
    assert resolved.resolved_ids == ["stark", "playbook"]
    assert resolved.implied_by == {"playbook": "stark"}
    assert resolved.capabilities["ui.components"].value == "playbook"


def test_unknown_stack_fails() -> None:
    with pytest.raises(StackResolutionError, match="Unknown Echelon stack"):
        resolve_stacks(["missing"], {})


def test_implication_cycle_fails() -> None:
    definitions = {
        "a": _stack("a", provides={"ui.components": "a"}, implies=["b"]),
        "b": _stack("b", provides={"ui.tokens": "b"}, implies=["a"]),
    }

    with pytest.raises(StackResolutionError, match="cycle"):
        resolve_stacks(["a"], definitions)


def test_capability_conflict_fails() -> None:
    definitions = {
        "playbook": _stack("playbook", provides={"ui.components": "playbook"}),
        "mui": _stack("mui", provides={"ui.components": "mui"}),
    }

    with pytest.raises(StackConflictError, match="ui.components"):
        resolve_stacks(["playbook", "mui"], definitions)


def test_same_capability_same_value_composes() -> None:
    definitions = {
        "a": _stack("a", provides={"audit.design_system": "playbook-cli"}),
        "b": _stack("b", provides={"audit.design_system": "playbook-cli"}),
    }

    resolved = resolve_stacks(["a", "b"], definitions)

    assert resolved.capabilities["audit.design_system"].sources == ["a", "b"]


def test_archetype_mismatch_fails() -> None:
    definitions = {
        "msa": _stack("msa", provides={"service.framework": "fastapi"}, archetypes=["service"]),
    }

    with pytest.raises(StackResolutionError, match="applies to"):
        resolve_stacks(["msa"], definitions, target_archetypes={"web_app"})


def test_renderer_outputs_capabilities_and_tools() -> None:
    definitions = {
        "playbook": _stack("playbook", provides={"ui.components": "playbook"}),
    }

    resolved = resolve_stacks(["playbook"], definitions, target_archetypes={"web_app"})
    data = resolved_to_dict(resolved)
    markdown = render_resolved_markdown(resolved)

    assert data["capabilities"]["ui.components"]["value"] == "playbook"
    assert "| ui.components | playbook | playbook |" in markdown
```

- [ ] **Step 2: Run resolver tests and verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_resolver.py -q
```

Expected: FAIL because resolver modules do not exist.

- [ ] **Step 3: Add resolution errors**

Append to `src/harness/stacks/errors.py`:

```python
class StackResolutionError(StackError):
    """Raised when selected stacks cannot be resolved."""


class StackConflictError(StackResolutionError):
    """Raised when selected stacks provide conflicting capabilities."""
```

- [ ] **Step 4: Implement resolver dataclasses and algorithm**

Create `src/harness/stacks/resolver.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from harness.stacks.errors import StackConflictError, StackResolutionError
from harness.stacks.schema import StackDefinition, StackTool


@dataclass(frozen=True)
class ResolvedCapability:
    value: str
    sources: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedStacks:
    selected_ids: list[str]
    resolved_ids: list[str]
    implied_by: dict[str, str]
    capabilities: dict[str, ResolvedCapability]
    tools: dict[str, StackTool]
    required_commands: list[str]
    required_registries: list[str]
    context_files: list[str]


def resolve_stacks(
    selected_ids: list[str],
    definitions: dict[str, StackDefinition],
    target_archetypes: set[str] | None = None,
) -> ResolvedStacks:
    if not selected_ids:
        return ResolvedStacks(
            selected_ids=[],
            resolved_ids=[],
            implied_by={},
            capabilities={},
            tools={},
            required_commands=[],
            required_registries=[],
            context_files=[],
        )

    for stack_id in selected_ids:
        if stack_id not in definitions:
            raise StackResolutionError(
                f"Unknown Echelon stack: {stack_id}. "
                f"Available stacks: {', '.join(sorted(definitions)) or 'none'}"
            )

    resolved_ids: list[str] = []
    implied_by: dict[str, str] = {}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stack_id: str, parent: str | None = None) -> None:
        if stack_id in visiting:
            raise StackResolutionError(f"Stack implication cycle detected at {stack_id}")
        if stack_id in visited:
            return
        if stack_id not in definitions:
            raise StackResolutionError(f"Unknown Echelon stack: {stack_id}")
        visiting.add(stack_id)
        if parent is not None and stack_id not in selected_ids:
            implied_by.setdefault(stack_id, parent)
        stack = definitions[stack_id]
        for implied in stack.implies:
            visit(implied, stack_id)
        visiting.remove(stack_id)
        visited.add(stack_id)
        resolved_ids.append(stack_id)

    for stack_id in selected_ids:
        visit(stack_id)

    if target_archetypes:
        for stack_id in resolved_ids:
            stack = definitions[stack_id]
            if not set(stack.applies_to_archetypes).intersection(target_archetypes):
                raise StackResolutionError(
                    f"Stack {stack_id} applies to "
                    f"{'/'.join(stack.applies_to_archetypes)}, but target archetypes are "
                    f"{'/'.join(sorted(target_archetypes))}."
                )

    capabilities: dict[str, ResolvedCapability] = {}
    tools: dict[str, StackTool] = {}
    required_commands: list[str] = []
    required_registries: list[str] = []
    context_files: list[str] = []

    for stack_id in resolved_ids:
        stack = definitions[stack_id]
        for capability, value in stack.provides.items():
            existing = capabilities.get(capability)
            if existing is not None and existing.value != value:
                raise StackConflictError(
                    "Stack capability conflict:\n"
                    f"  {capability} = {existing.value} from {', '.join(existing.sources)}\n"
                    f"  {capability} = {value} from {stack_id}"
                )
            if existing is None:
                capabilities[capability] = ResolvedCapability(value=value, sources=[stack_id])
            else:
                capabilities[capability] = ResolvedCapability(
                    value=existing.value,
                    sources=[*existing.sources, stack_id],
                )

        for tool_id, tool in stack.tools.items():
            tools.setdefault(tool_id, tool)
        required_commands.extend(command for command in stack.requires_commands if command not in required_commands)
        required_registries.extend(registry for registry in stack.requires_registries if registry not in required_registries)
        context_files.extend(
            f"{stack.source_path.parent / file_path}"
            for file_path in stack.context_files
        )

    return ResolvedStacks(
        selected_ids=selected_ids,
        resolved_ids=resolved_ids,
        implied_by=implied_by,
        capabilities=capabilities,
        tools=tools,
        required_commands=required_commands,
        required_registries=required_registries,
        context_files=context_files,
    )
```

- [ ] **Step 5: Implement renderer**

Create `src/harness/stacks/renderer.py`:

```python
from __future__ import annotations

from harness.stacks.resolver import ResolvedStacks


def resolved_to_dict(resolved: ResolvedStacks) -> dict:
    return {
        "selected": resolved.selected_ids,
        "resolved": resolved.resolved_ids,
        "implied_by": resolved.implied_by,
        "capabilities": {
            key: {"value": capability.value, "sources": capability.sources}
            for key, capability in sorted(resolved.capabilities.items())
        },
        "tools": {
            tool_id: {
                "type": tool.type,
                "command": tool.command,
                "args": tool.args,
                "phase_scope": tool.phase_scope,
                "purpose": tool.purpose,
                "commands": {
                    command_id: {
                        "args": command.args,
                        "output": command.output,
                        "gate": command.gate,
                    }
                    for command_id, command in sorted(tool.commands.items())
                },
            }
            for tool_id, tool in sorted(resolved.tools.items())
        },
        "requirements": {
            "commands": resolved.required_commands,
            "registries": resolved.required_registries,
        },
        "context_files": resolved.context_files,
    }


def render_resolved_markdown(resolved: ResolvedStacks) -> str:
    lines = ["# Resolved Echelon Stacks", ""]

    if not resolved.resolved_ids:
        lines.extend([
            "No Echelon stacks selected. Use normal Echelon inference.",
            "",
        ])
        return "\n".join(lines)

    lines.extend(["## Selected Stacks", ""])
    for stack_id in resolved.resolved_ids:
        suffix = ""
        if stack_id in resolved.implied_by:
            suffix = f" (implied by {resolved.implied_by[stack_id]})"
        lines.append(f"- {stack_id}{suffix}")

    lines.extend(["", "## Capabilities", "", "| Capability | Value | Source |", "|---|---|---|"])
    for key, capability in sorted(resolved.capabilities.items()):
        lines.append(f"| {key} | {capability.value} | {', '.join(capability.sources)} |")

    if resolved.tools:
        lines.extend(["", "## Available Stack Tools", ""])
        for tool_id, tool in sorted(resolved.tools.items()):
            command = " ".join([tool.command, *tool.args]).strip()
            lines.extend([
                f"### {tool_id}",
                "",
                f"- Command: `{command}`",
                f"- Phase scope: {', '.join(tool.phase_scope) if tool.phase_scope else 'unspecified'}",
            ])
            if tool.purpose:
                lines.append(f"- Purpose: {tool.purpose}")
            gate_commands = [
                command_id
                for command_id, command_def in tool.commands.items()
                if command_def.gate
            ]
            if gate_commands:
                lines.append(f"- Gate commands: {', '.join(sorted(gate_commands))}")
            lines.append("")

    if resolved.required_commands or resolved.required_registries:
        lines.extend(["## Requirements", ""])
        for command in resolved.required_commands:
            lines.append(f"- Command: `{command}`")
        for registry in resolved.required_registries:
            lines.append(f"- Registry: `{registry}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 6: Implement loader**

Create `src/harness/stacks/loader.py`:

```python
from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

from harness.stacks.errors import StackResolutionError, StackValidationError
from harness.stacks.schema import StackDefinition, parse_stack_definition


def load_stack_definitions(
    *,
    extension_root: Path,
    project_root: Path | None = None,
) -> dict[str, StackDefinition]:
    definitions: dict[str, StackDefinition] = {}
    _load_from_dir(extension_root / "stacks", definitions, allow_override=False)
    if project_root is not None:
        _load_from_dir(project_root / ".echelon" / "stacks", definitions, allow_override=False)
    return definitions


def _load_from_dir(
    root: Path,
    definitions: dict[str, StackDefinition],
    *,
    allow_override: bool,
) -> None:
    if not root.exists():
        return
    for path in sorted(root.glob("*/stack.yml")):
        stack = _load_one(path)
        if stack.id in definitions and not allow_override:
            raise StackResolutionError(f"Duplicate Echelon stack ID: {stack.id}")
        definitions[stack.id] = stack


def _load_one(path: Path) -> StackDefinition:
    if yaml is None:
        raise StackValidationError("PyYAML is required for stack loading", path=path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise StackValidationError(f"Could not read stack definition: {exc}", path=path) from exc
    return parse_stack_definition(raw, path)
```

- [ ] **Step 7: Export public API**

Update `src/harness/stacks/__init__.py`:

```python
"""Echelon stack loading, validation, resolution, and rendering."""

from harness.stacks.loader import load_stack_definitions
from harness.stacks.renderer import render_resolved_markdown, resolved_to_dict
from harness.stacks.resolver import ResolvedStacks, resolve_stacks

__all__ = [
    "ResolvedStacks",
    "load_stack_definitions",
    "render_resolved_markdown",
    "resolve_stacks",
    "resolved_to_dict",
]
```

- [ ] **Step 8: Run resolver tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/harness/stacks tests/unit/test_stacks_resolver.py
git commit -m "feat: resolve Echelon stack capabilities"
```

---

### Task 4: Add Bundled Stats Perform Stack Definitions

**Files:**
- Create: `extension/stacks/statsperform-playbook/stack.yml`
- Create: `extension/stacks/statsperform-playbook/context.md`
- Create: `extension/stacks/statsperform-msa-service/stack.yml`
- Create: `extension/stacks/statsperform-msa-service/context.md`
- Create: `extension/stacks/statsperform-stark-webapp/stack.yml`
- Create: `extension/stacks/statsperform-stark-webapp/context.md`
- Create: `tests/unit/test_stacks_integration.py`

**Interfaces:**
- Consumes: `load_stack_definitions()`
- Produces: bundled stack definitions that validate and resolve

- [ ] **Step 1: Write failing bundled stack test**

Create `tests/unit/test_stacks_integration.py`:

```python
from __future__ import annotations

from pathlib import Path

from harness.stacks import load_stack_definitions, resolve_stacks
from harness.stacks.renderer import render_resolved_markdown


ROOT = Path(__file__).resolve().parents[2]
EXTENSION_ROOT = ROOT / "extension"


def test_loads_bundled_statsperform_stacks() -> None:
    definitions = load_stack_definitions(extension_root=EXTENSION_ROOT)

    assert sorted(definitions) == [
        "statsperform-msa-service",
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]


def test_stark_implies_playbook_without_conflict() -> None:
    definitions = load_stack_definitions(extension_root=EXTENSION_ROOT)

    resolved = resolve_stacks(
        ["statsperform-stark-webapp"],
        definitions,
        target_archetypes={"web_app"},
    )

    assert resolved.resolved_ids == [
        "statsperform-playbook",
        "statsperform-stark-webapp",
    ]
    assert resolved.capabilities["ui.components"].value == "playbook"
    assert resolved.capabilities["web_app.framework"].value == "nextjs"


def test_msa_and_stark_compose_for_multi_target_context() -> None:
    definitions = load_stack_definitions(extension_root=EXTENSION_ROOT)

    resolved = resolve_stacks(
        ["statsperform-msa-service", "statsperform-stark-webapp"],
        definitions,
        target_archetypes={"service", "web_app"},
    )

    assert resolved.capabilities["service.framework"].value == "fastapi"
    assert resolved.capabilities["web_app.framework"].value == "nextjs"


def test_rendered_context_mentions_stack_tools() -> None:
    definitions = load_stack_definitions(extension_root=EXTENSION_ROOT)
    resolved = resolve_stacks(["statsperform-playbook"], definitions, target_archetypes={"web_app"})

    markdown = render_resolved_markdown(resolved)

    assert "playbook_cli" in markdown
    assert "npx -y @statsperform/playbook-cli" in markdown
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_integration.py -q
```

Expected: FAIL because bundled stacks do not exist.

- [ ] **Step 3: Add Playbook stack files**

Create `extension/stacks/statsperform-playbook/stack.yml`:

```yaml
schema_version: "1.0"
stack:
  id: statsperform-playbook
  name: Stats Perform Playbook
  version: "1.0.0"
  kind: capability
  owner: statsperform
  description: Playbook UI, component, token, form, and compliance stack for web apps.
applies_to:
  archetypes:
    - web_app
provides:
  ui.components: playbook
  ui.tokens: playbook
  ui.forms: playbook-form-builder
  ui.icons: playbook-icons
  ui.scaffolding: playbook-guided
  test.ui_accessibility: axe
  test.visual: playwright
  audit.design_system: playbook-cli
  docs.ui_lookup: playbook-cli
implies: []
requires:
  commands:
    - npx
  registries:
    - statsperform-nexus
tools:
  playbook_cli:
    type: cli
    command: npx
    args:
      - "-y"
      - "@statsperform/playbook-cli"
    phase_scope:
      - spec
      - delivery
    purpose: Component discovery, token lookup, icon lookup, form-builder docs, patterns, and compliance scans.
    commands:
      components_list:
        args: ["components", "list", "--json"]
        output: json
        gate: false
      components_show:
        args: ["components", "show"]
        output: markdown
        gate: false
      styles_show:
        args: ["styles", "show"]
        output: markdown
        gate: false
      icons_list:
        args: ["icons", "list"]
        output: text
        gate: false
      compliance_scan:
        args: ["compliance", "scan"]
        output: text
        gate: true
context:
  files:
    - context.md
conflicts: []
```

Create `extension/stacks/statsperform-playbook/context.md`:

```markdown
# Stats Perform Playbook Stack

Use Playbook as the default UI, component, design-token, icon, form, and design-system compliance stack for web-app targets.

Mandatory guidance:

- Use `npx -y @statsperform/playbook-cli` for component discovery, props, examples, tokens, icons, patterns, form-builder docs, and compliance checks.
- Run `components list` before selecting a Playbook component.
- Run `components show button --outline` before reading full component docs; replace `button` with the concrete component name discovered from `components list`.
- Use Playbook components when they exist for the UI pattern.
- Use Playbook Form Builder for forms unless requirements explicitly rule it out.
- Use Playbook tokens for custom styling.
- Run Playbook compliance checks before UI sign-off when source exists.

Boundaries:

- This stack does not imply Stark.
- This stack does not choose the frontend framework or frontend test runner.
- This stack adds accessibility and compliance obligations around UI composition.
```

- [ ] **Step 4: Add MSA stack files**

Create `extension/stacks/statsperform-msa-service/stack.yml`:

```yaml
schema_version: "1.0"
stack:
  id: statsperform-msa-service
  name: Stats Perform MSA Service
  version: "1.0.0"
  kind: archetype
  owner: statsperform
  description: CAIC MSA service archetype using the MSA service template and MSA core.
applies_to:
  archetypes:
    - service
    - api_service
provides:
  service.template: caic-msa-service-template
  service.core: caic-msa-core
  service.framework: fastapi
  service.runtime: uv-python
  service.config: pydantic-settings
  delivery.service: msa-template-default
  test.backend: pytest
  lint.python: ruff
  typecheck.python: mypy
  observability.service: msa-default
implies: []
requires:
  commands:
    - uv
  registries:
    - statsperform-nexus
tools:
  uv:
    type: cli
    command: uv
    phase_scope:
      - spec
      - delivery
    purpose: MSA Python environment, dependency, test, lint, and typecheck command runner.
    commands:
      test:
        args: ["run", "pytest"]
        output: text
        gate: true
      lint:
        args: ["run", "ruff", "check", "."]
        output: text
        gate: true
      typecheck:
        args: ["run", "mypy", "src"]
        output: text
        gate: true
context:
  files:
    - context.md
conflicts: []
```

Create `extension/stacks/statsperform-msa-service/context.md`:

```markdown
# Stats Perform MSA Service Stack

Use the CAIC MSA service template and MSA core conventions for service and API-service targets.

Mandatory guidance:

- Use the MSA service template for new service structure.
- Use MSA core conventions for FastAPI service layout, configuration, health checks, observability, Docker, CI, and release behavior.
- Use `uv` for Python environment and dependency operations.
- Use pytest for backend tests, ruff for linting, and mypy for type checking.

Boundaries:

- This stack does not imply Postgres, Kafka, Flink, or other infrastructure dependencies.
- Select persistence, messaging, and stream-processing stacks separately when requirements call for them.
- This stack does not apply Stark web-app delivery behavior.
```

- [ ] **Step 5: Add Stark stack files**

Create `extension/stacks/statsperform-stark-webapp/stack.yml`:

```yaml
schema_version: "1.0"
stack:
  id: statsperform-stark-webapp
  name: Stats Perform Stark Web App
  version: "1.0.0"
  kind: archetype
  owner: statsperform
  description: Opta Stark Nx/Next.js web-app archetype.
applies_to:
  archetypes:
    - web_app
provides:
  web_app.template: opta-stark
  web_app.framework: nextjs
  web_app.workspace: nx
  web_app.runtime: node
  delivery.web_app: stark-default
  observability.web_app: stark-default
  test.frontend: jest-rtl
implies:
  - statsperform-playbook
requires:
  commands:
    - npm
    - npx
  registries:
    - statsperform-nexus
tools:
  nx:
    type: cli
    command: npx
    args:
      - nx
    phase_scope:
      - spec
      - delivery
    purpose: Nx project graph, dev, build, lint, and test tasks for Stark web apps.
    commands:
      build_web:
        args: ["build", "web"]
        output: text
        gate: true
      test_web:
        args: ["test", "web"]
        output: text
        gate: true
      lint_web:
        args: ["lint", "web"]
        output: text
        gate: true
context:
  files:
    - context.md
conflicts: []
```

Create `extension/stacks/statsperform-stark-webapp/context.md`:

```markdown
# Stats Perform Stark Web App Stack

Use the Opta Stark Nx/Next.js archetype for web-app targets.

Mandatory guidance:

- Use Nx and Next.js App Router conventions from the Stark template.
- Keep `/livez` and `/readyz` health checks for web-app delivery.
- Use Stark Docker and standalone output conventions.
- Use Jest and Testing Library for Stark frontend tests unless the target repository already standardizes otherwise.
- Follow Stark observability and structured logging conventions when relevant.

Implied stacks:

- `statsperform-playbook` is implied because Stark uses `@statsperform/react-playbook`.

Boundaries:

- This stack applies only to web-app targets.
- This stack does not imply MSA.
- This stack is not a backend service deployment model.
```

- [ ] **Step 6: Run bundled stack integration tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stacks_integration.py tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add extension/stacks tests/unit/test_stacks_integration.py
git commit -m "feat: add bundled Stats Perform stacks"
```

---

### Task 5: Generate Resolved Stack Context and Inject Into Build Prompts

**Files:**
- Modify: `src/harness/build_prompt.py`
- Modify: `src/harness/coordinator.py`
- Create: `tests/unit/test_stack_context_prompt.py`

**Interfaces:**
- Produces: `BuildPromptBuilder.build_prompt(..., stack_context: str = "")`
- Consumes: `HarnessConfig.stacks.selected`
- Consumes: `load_stack_definitions()`, `resolve_stacks()`, and `render_resolved_markdown()`

- [ ] **Step 1: Write failing prompt tests**

Create `tests/unit/test_stack_context_prompt.py`:

```python
from __future__ import annotations

from harness.build_prompt import BuildPromptBuilder


def test_build_prompt_includes_stack_context_when_present() -> None:
    prompt = BuildPromptBuilder().build_prompt(
        worktree_path="/tmp/work",
        spec_content="# Spec",
        tasks_content="# Tasks",
        build_skill="speckit-echelon-build",
        stack_context="# Resolved Echelon Stacks\n\n- statsperform-playbook\n",
    )

    assert "## Resolved Stack Context" in prompt
    assert "statsperform-playbook" in prompt


def test_build_prompt_omits_empty_stack_context() -> None:
    prompt = BuildPromptBuilder().build_prompt(
        worktree_path="/tmp/work",
        spec_content="# Spec",
        tasks_content="# Tasks",
        build_skill="speckit-echelon-build",
    )

    assert "## Resolved Stack Context" not in prompt
```

- [ ] **Step 2: Run prompt tests and verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stack_context_prompt.py -q
```

Expected: FAIL because `stack_context` is not an accepted argument.

- [ ] **Step 3: Add build prompt stack context**

Modify `src/harness/build_prompt.py`.

Add parameter to `build_prompt()`:

```python
        stack_context: str = "",
```

Insert after `## Tasks`:

```python
        if stack_context.strip():
            parts.append(f"## Resolved Stack Context\n{stack_context.strip()}")
```

- [ ] **Step 4: Add coordinator stack context resolution**

Modify `src/harness/coordinator.py` imports:

```python
from harness.stacks import load_stack_definitions, render_resolved_markdown, resolve_stacks
from harness.stacks.errors import StackError
```

Add helper near other private helpers:

```python
def _resolved_stack_context(base_dir: str, selected: list[str]) -> str:
    if not selected:
        return ""
    base = Path(base_dir)
    extension_root = base / ".specify" / "extensions" / "echelon"
    if not extension_root.exists():
        extension_root = Path(__file__).resolve().parents[2] / "extension"
    definitions = load_stack_definitions(
        extension_root=extension_root,
        project_root=base,
    )
    resolved = resolve_stacks(selected, definitions)
    return render_resolved_markdown(resolved)
```

In the strategy loop before `arguments = ...`, add:

```python
            stack_context = ""
            try:
                stack_context = _resolved_stack_context(
                    self._base_dir,
                    self._config.stacks.selected,
                )
            except StackError as exc:
                raise RuntimeError(str(exc)) from exc
```

After appending `spec.context` to `arguments`, append stack context:

```python
            if stack_context:
                arguments += f"\n\n{stack_context}"
```

When calling `controller.run_loop`, pass combined context:

```python
                strategy_context="\n\n".join(
                    part for part in [spec.context, stack_context] if part
                ),
```

This preserves existing strategy context and adds resolved stack context without changing agent files.

- [ ] **Step 5: Run prompt tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stack_context_prompt.py -q
```

Expected: PASS.

- [ ] **Step 6: Run stack and coordinator-adjacent tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_stack_context_prompt.py tests/unit/test_stacks_integration.py tests/unit/test_config.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/harness/build_prompt.py src/harness/coordinator.py tests/unit/test_stack_context_prompt.py
git commit -m "feat: inject resolved stack context into build prompts"
```

---

### Task 6: Document Stack Config Defaults

**Files:**
- Modify: `extension/config-template.yml`
- Modify: `extension/echelon-config.yml`
- Modify: `docs/superpowers/specs/2026-07-05-echelon-stacks-design.md`

**Interfaces:**
- Produces: documented config shape
- Consumes: implementation behavior from previous tasks

- [ ] **Step 1: Add config template section**

In both `extension/config-template.yml` and `extension/echelon-config.yml`, add near the existing `tools:` or before `banzai:`:

```yaml
# =============================================================================
# ECHELON STACKS
# =============================================================================

stacks:
  # Opt-in stack IDs. Empty means Echelon uses normal inference.
  #
  # Examples:
  #   - statsperform-playbook
  #   - statsperform-msa-service
  #   - statsperform-stark-webapp
  selected: []
```

- [ ] **Step 2: Update design spec implementation notes**

In `docs/superpowers/specs/2026-07-05-echelon-stacks-design.md`, add under "Migration Plan":

```markdown
The first implementation resolves stack context for Phase B build prompts. Phase A
phase-spec context-pack injection can follow once the externalized workflow has a
deterministic context-pack materialization hook for `.echelon/context/stacks/`.
```

- [ ] **Step 3: Run config template smoke checks**

Run:

```bash
python - <<'PY'
from pathlib import Path
import yaml
for path in [Path("extension/config-template.yml"), Path("extension/echelon-config.yml")]:
    yaml.safe_load(path.read_text())
    print(path, "ok")
PY
```

Expected:

```text
extension/config-template.yml ok
extension/echelon-config.yml ok
```

- [ ] **Step 4: Commit**

```bash
git add extension/config-template.yml extension/echelon-config.yml docs/superpowers/specs/2026-07-05-echelon-stacks-design.md
git commit -m "docs: document Echelon stack selection config"
```

---

### Task 7: Full Verification

**Files:**
- No code changes expected.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: verified branch state.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_config.py tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py tests/unit/test_stacks_integration.py tests/unit/test_stack_context_prompt.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader unit tests if time permits**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit -q
```

Expected: PASS or report pre-existing failures with exact failing test names.

- [ ] **Step 3: Inspect branch diff**

Run:

```bash
git status --short
git log --oneline --max-count=8
```

Expected: clean worktree and visible task commits on `feature/echelon-stacks`.

- [ ] **Step 4: Final handoff**

Report the final branch state in prose with the exact targeted test command result, the exact broader unit test result if it was run, and these key file groups:

- `src/harness/stacks/`
- `extension/stacks/`
- `src/harness/config.py`
- `src/harness/build_prompt.py`
- `src/harness/coordinator.py`
