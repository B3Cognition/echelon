# Controller State Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one reusable, fail-closed contract boundary for all
controller-owned workflow state before routing, persistence, completion, and
checkpointing.

**Architecture:** Five named JSON Schema Draft 2020-12 contracts live in one
strictly loaded workflow registry. `PhaseGraph` compiles and shares them,
controller results pass through bounded lossless normalization into an
immutable prepared-result boundary, and state advancement becomes
all-or-error with the existing iteration increment included before
checkpointing.

**Tech Stack:** Python 3.11, PyYAML, jsonschema 4.x, pytest, Echelon
`PhaseGraph`/`SquadController`/`SquadStateStore`.

## Global Constraints

- Keep provider-owned `allowed_state_updates` separate from controller-owned
  contract fields.
- Do not add a compatibility flag, shadow path, fallback parser, or legacy
  `controller_state_updates` support.
- Migrate all five contracts and seven current phases in one implementation.
- Do not coerce strings to booleans, numbers, or enums.
- Do not duplicate controller field schemas in phase YAML or operational
  Markdown.
- Validate controller state before transitions, product-input side effects,
  state advancement, successful timing telemetry, and checkpointing.
- Keep exact tuples, mappings, `PathLike`, and `Enum` as the only lossless
  normalization inputs described by the design.
- Preserve the unrelated untracked
  `docs/findings/2026-07-23-egr-service-workflow-robustness-review.md`.
- Do not implement currently descriptive transition actions other than the
  existing `increment_iteration` mutation.

---

## File Map

| File | Responsibility |
|---|---|
| `src/harness/controller_state_contracts.py` | Strict registry loading, schema compilation, bounded normalization, and controller validation |
| `src/harness/prepared_phase_result.py` | Immutable prepared-result receipt and provider/controller ownership merge |
| `extension/workflow/controller-state-contracts.yaml` | Single authoritative controller contract registry |
| `src/harness/phase_graph.py` | Resolve named controller contracts onto phase nodes |
| `src/harness/workflow_validator.py` | Fail startup for invalid references, ownership overlap, legacy declarations, and unsupported skips |
| `src/harness/squad.py` | Produce controller enrichment separately, prepare results before routing, and block deterministically |
| `src/harness/squad_state.py` | All-or-error state advance, contract receipt, and atomic iteration increment |
| `tests/kernel/test_controller_state_contracts.py` | Registry, normalization, and schema contract tests |
| `tests/kernel/test_prepared_phase_result.py` | Prepared-result ownership and immutability tests |
| `tests/kernel/test_phase_graph.py` | Shared contract resolution and migrated node tests |
| `tests/kernel/test_workflow_validator.py` | Workflow startup validation tests |
| `tests/kernel/test_squad_state.py` | Transactional state advancement tests |
| `tests/integration/test_squad_controller.py` | Main/manual/mixed-node fail-closed orchestration tests |
| `tests/unit/test_squad_phase_checkpoints.py` | No checkpoint on preparation/advance failure |
| `pyproject.toml`, `uv.lock` | Direct jsonschema dependency |

---

### Task 1: Strict Controller Contract Registry

**Files:**
- Create: `src/harness/controller_state_contracts.py`
- Create: `tests/kernel/test_controller_state_contracts.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces:
  - `ControllerContractRegistryError(ValueError)`
  - `ControllerStateContractViolation(ValueError)`
  - `CompiledControllerStateContract`
  - `load_controller_state_contracts(path: Path) -> Mapping[str, CompiledControllerStateContract]`
- Consumes: no earlier task interfaces.

- [ ] **Step 1: Add failing strict-loader and schema-profile tests**

```python
def _schema(
    fields: dict[str, object],
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "state_updates"],
        "properties": {
            "verdict": {"type": "string"},
            "state_updates": {
                "type": "object",
                "additionalProperties": False,
                "properties": fields,
            },
        },
    }
    schema.update(extra or {})
    return schema


def _write_registry(
    tmp_path: Path,
    contracts: dict[str, object],
) -> Path:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "contracts": contracts}),
        encoding="utf-8",
    )
    return path


def test_registry_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        "schema_version: 1\ncontracts:\n  sample: {}\n  sample: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(ControllerContractRegistryError, match="duplicate key 'sample'"):
        load_controller_state_contracts(path)


def test_registry_rejects_remote_ref(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        {"sample": _schema({"value": {"type": "string"}},
                           extra={"$ref": "https://example.test/schema.json"})},
    )
    with pytest.raises(ControllerContractRegistryError, match="remote.*\\$ref"):
        load_controller_state_contracts(path)


def test_registry_compiles_immutable_contract_and_stable_digest(tmp_path: Path) -> None:
    path = _write_registry(
        tmp_path,
        {"sample": _schema({"value": {"type": "string"}})},
    )
    first = load_controller_state_contracts(path)["sample"]
    second = load_controller_state_contracts(path)["sample"]
    assert first.state_update_keys == frozenset({"value"})
    assert first.sha256 == second.sha256
    with pytest.raises(TypeError):
        first.schema["type"] = "array"
```

- [ ] **Step 2: Run the new tests and confirm import failure**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_controller_state_contracts.py
```

Expected: collection fails because
`harness.controller_state_contracts` does not exist.

- [ ] **Step 3: Add jsonschema as a direct dependency**

Add to `dependencies` in `pyproject.toml`:

```toml
"jsonschema>=4.23,<5",
```

Regenerate the lock:

```bash
uv lock
```

- [ ] **Step 4: Implement strict loading and compilation**

Create `src/harness/controller_state_contracts.py` with:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class ControllerContractRegistryError(ValueError):
    pass


class ControllerStateContractViolation(ValueError):
    def __init__(
        self,
        message: str,
        *,
        contract: str,
        json_path: str = "$",
        validator: str = "contract",
    ) -> None:
        super().__init__(message)
        self.contract = contract
        self.json_path = json_path
        self.validator = validator


@dataclass(frozen=True)
class CompiledControllerStateContract:
    name: str
    schema: Mapping[str, Any]
    state_update_keys: frozenset[str]
    validator: Draft202012Validator
    sha256: str


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ControllerContractRegistryError(f"duplicate key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _reject_external_refs(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key == "$ref" and (
                not isinstance(item, str) or not item.startswith("#/$defs/")
            ):
                raise ControllerContractRegistryError(
                    f"remote or non-local $ref is forbidden at {child}"
                )
            if key == "default":
                raise ControllerContractRegistryError(
                    f"schema defaults are forbidden at {child}"
                )
            _reject_external_refs(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_external_refs(item, f"{path}[{index}]")


def load_controller_state_contracts(
    path: Path,
) -> Mapping[str, CompiledControllerStateContract]:
    try:
        raw = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except ControllerContractRegistryError:
        raise
    except Exception as exc:
        raise ControllerContractRegistryError(
            f"cannot read controller contract registry: {exc}"
        ) from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ControllerContractRegistryError(
            "controller contract registry schema_version must be 1"
        )
    contracts = raw.get("contracts")
    if not isinstance(contracts, dict) or not contracts:
        raise ControllerContractRegistryError(
            "controller contract registry must contain contracts"
        )

    compiled = {}
    for name, schema in contracts.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(schema, dict):
            raise ControllerContractRegistryError("contract names and schemas must be mappings")
        _reject_external_refs(schema)
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ControllerContractRegistryError(
                f"invalid controller contract {name!r}: {exc.message}"
            ) from exc
        properties = schema.get("properties")
        state_schema = properties.get("state_updates") if isinstance(properties, dict) else None
        state_properties = (
            state_schema.get("properties") if isinstance(state_schema, dict) else None
        )
        if (
            schema.get("type") != "object"
            or schema.get("additionalProperties") is not False
            or not isinstance(state_schema, dict)
            or state_schema.get("type") != "object"
            or state_schema.get("additionalProperties") is not False
            or not isinstance(state_properties, dict)
            or not state_properties
        ):
            raise ControllerContractRegistryError(
                f"controller contract {name!r} does not satisfy the supported schema profile"
            )
        canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        compiled[name] = CompiledControllerStateContract(
            name=name,
            schema=_freeze(schema),
            state_update_keys=frozenset(str(key) for key in state_properties),
            validator=Draft202012Validator(schema),
            sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )
    return MappingProxyType(compiled)
```

- [ ] **Step 5: Run registry tests**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_controller_state_contracts.py
```

Expected: all registry-loading tests pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/harness/controller_state_contracts.py \
  tests/kernel/test_controller_state_contracts.py
git commit -m "feat: add controller contract registry"
```

---

### Task 2: Bounded Lossless Normalization and Contract Validation

**Files:**
- Modify: `src/harness/controller_state_contracts.py`
- Modify: `tests/kernel/test_controller_state_contracts.py`

**Interfaces:**
- Consumes: `CompiledControllerStateContract`,
  `ControllerStateContractViolation`.
- Produces:
  - `NormalizationOutcome`
  - `normalize_controller_updates(updates: Mapping[str, Any]) -> NormalizationOutcome`
  - `validate_controller_result(contract, verdict, updates) -> tuple[ControllerContractError, ...]`

- [ ] **Step 1: Add the normalization matrix and invariant-error tests**

```python
class DemoEnum(Enum):
    VALUE = "value"


def _load_sample_contract(tmp_path: Path) -> CompiledControllerStateContract:
    return load_controller_state_contracts(_write_registry(
        tmp_path,
        {"sample": _schema({
            "count": {"type": "integer", "minimum": 0},
            "pass": {"type": "boolean"},
        })},
    ))["sample"]


def test_lossless_normalization_is_idempotent(tmp_path: Path) -> None:
    source = {
        "path": PurePosixPath("reports/result.json"),
        "enum": DemoEnum.VALUE,
        "items": ["native", ("one", {"two": ("three",)})],
    }
    first = normalize_controller_updates(source)
    second = normalize_controller_updates(first.updates)
    assert first.updates == {
        "path": "reports/result.json",
        "enum": "value",
        "items": ["native", ["one", {"two": ["three"]}]],
    }
    assert second.updates == first.updates
    assert source["items"] == ["native", ("one", {"two": ("three",)})]


@pytest.mark.parametrize("value", [{1, 2}, b"bytes"])
def test_normalizer_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(ControllerStateContractViolation):
        normalize_controller_updates({"value": value})


def test_normalizer_preserves_json_native_scalar_types() -> None:
    outcome = normalize_controller_updates(
        {"text": "true", "other_text": "2", "flag": True, "count": 2}
    )
    assert outcome.updates == {
        "text": "true",
        "other_text": "2",
        "flag": True,
        "count": 2,
    }
    assert outcome.normalized_paths == ()


def test_contract_errors_are_sorted_and_value_redacted(tmp_path: Path) -> None:
    contract = _load_sample_contract(tmp_path)
    errors = validate_controller_result(
        contract,
        "DONE",
        {"count": -1, "pass": "secret-invalid-value"},
    )
    assert [error.json_path for error in errors] == sorted(
        error.json_path for error in errors
    )
    assert all("secret-invalid-value" not in str(error) for error in errors)
```

Add explicit tests for cycles, depth 33, 10,001 visited values, a 10,001-entry
collection, a bytes-returning `PathLike`, non-string mapping keys, and Boolean
values presented to integer schemas.

- [ ] **Step 2: Run the new tests and confirm missing-interface failures**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_controller_state_contracts.py
```

Expected: failures for missing `NormalizationOutcome`,
`normalize_controller_updates`, and `validate_controller_result`.

- [ ] **Step 3: Implement bounded recursive normalization**

Add:

```python
from collections.abc import Mapping as MappingABC
from enum import Enum
from os import PathLike, fspath

MAX_NORMALIZATION_DEPTH = 32
MAX_NORMALIZATION_NODES = 10_000
MAX_NORMALIZATION_COLLECTION = 10_000


@dataclass(frozen=True)
class NormalizationOutcome:
    updates: dict[str, Any]
    normalized_paths: tuple[str, ...] = ()


def normalize_controller_updates(
    updates: Mapping[str, Any],
) -> NormalizationOutcome:
    normalized_paths: list[str] = []
    active: set[int] = set()
    visited = 0

    def visit(value: Any, path: str, depth: int) -> Any:
        nonlocal visited
        visited += 1
        if depth > MAX_NORMALIZATION_DEPTH or visited > MAX_NORMALIZATION_NODES:
            raise ControllerStateContractViolation(
                "controller normalization limit exceeded",
                contract="normalization",
                json_path=path,
                validator="normalization_limit",
            )
        if value is None or isinstance(value, (str, bool, int, float)):
            return value
        if isinstance(value, PathLike):
            result = fspath(value)
            if not isinstance(result, str):
                raise ControllerStateContractViolation(
                    "PathLike must normalize to text",
                    contract="normalization",
                    json_path=path,
                    validator="pathlike",
                )
            normalized_paths.append(path)
            return result
        if isinstance(value, Enum):
            result = visit(value.value, path, depth + 1)
            if not isinstance(result, (str, bool, int, float)) and result is not None:
                raise ControllerStateContractViolation(
                    "Enum value must be a supported scalar",
                    contract="normalization",
                    json_path=path,
                    validator="enum",
                )
            normalized_paths.append(path)
            return result
        if isinstance(value, list):
            if len(value) > MAX_NORMALIZATION_COLLECTION:
                raise ControllerStateContractViolation(
                    "controller collection is too large",
                    contract="normalization",
                    json_path=path,
                    validator="maxItems",
                )
            identity = id(value)
            if identity in active:
                raise ControllerStateContractViolation(
                    "cyclic controller value",
                    contract="normalization",
                    json_path=path,
                    validator="cycle",
                )
            active.add(identity)
            try:
                return [
                    visit(item, f"{path}[{index}]", depth + 1)
                    for index, item in enumerate(value)
                ]
            finally:
                active.remove(identity)
        if isinstance(value, tuple):
            if len(value) > MAX_NORMALIZATION_COLLECTION:
                raise ControllerStateContractViolation(
                    "controller collection is too large",
                    contract="normalization",
                    json_path=path,
                    validator="maxItems",
                )
            identity = id(value)
            if identity in active:
                raise ControllerStateContractViolation(
                    "cyclic controller value",
                    contract="normalization",
                    json_path=path,
                    validator="cycle",
                )
            active.add(identity)
            try:
                result = [visit(item, f"{path}[{index}]", depth + 1)
                          for index, item in enumerate(value)]
            finally:
                active.remove(identity)
            normalized_paths.append(path)
            return result
        if isinstance(value, MappingABC):
            if len(value) > MAX_NORMALIZATION_COLLECTION:
                raise ControllerStateContractViolation(
                    "controller mapping is too large",
                    contract="normalization",
                    json_path=path,
                    validator="maxProperties",
                )
            if not all(isinstance(key, str) for key in value):
                raise ControllerStateContractViolation(
                    "controller mapping keys must be strings",
                    contract="normalization",
                    json_path=path,
                    validator="propertyNames",
                )
            identity = id(value)
            if identity in active:
                raise ControllerStateContractViolation(
                    "cyclic controller value",
                    contract="normalization",
                    json_path=path,
                    validator="cycle",
                )
            active.add(identity)
            try:
                result = {
                    key: visit(item, f"{path}.{key}", depth + 1)
                    for key, item in value.items()
                }
            finally:
                active.remove(identity)
            if type(value) is not dict:
                normalized_paths.append(path)
            return result
        raise ControllerStateContractViolation(
            f"unsupported controller value type {type(value).__name__}",
            contract="normalization",
            json_path=path,
            validator="type",
        )

    result = visit(dict(updates), "$.state_updates", 0)
    return NormalizationOutcome(
        updates=result,
        normalized_paths=tuple(sorted(set(normalized_paths))),
    )
```

- [ ] **Step 4: Implement deterministic JSON Schema error conversion**

```python
@dataclass(frozen=True)
class ControllerContractError:
    contract: str
    json_path: str
    validator: str
    message: str


def validate_controller_result(
    contract: CompiledControllerStateContract,
    verdict: str,
    updates: Mapping[str, Any],
) -> tuple[ControllerContractError, ...]:
    payload = {"verdict": verdict, "state_updates": dict(updates)}
    errors = []
    for error in contract.validator.iter_errors(payload):
        path = "$" + "".join(
            f"[{part}]" if isinstance(part, int) else f".{part}"
            for part in error.absolute_path
        )
        errors.append(ControllerContractError(
            contract=contract.name,
            json_path=path,
            validator=str(error.validator or "schema"),
            message=error.message.replace(repr(error.instance), "<redacted>"),
        ))
    return tuple(sorted(errors, key=lambda item: (
        item.json_path, item.validator, item.message
    )))
```

Do not rely only on string replacement for redaction: tests must ensure the
final persisted diagnostic is built from validator name, expected constraint,
and path without embedding `error.instance`.

- [ ] **Step 5: Run the complete contract test module**

```bash
.venv/bin/pytest -q tests/kernel/test_controller_state_contracts.py
```

Expected: all loader, normalization, bounds, redaction, and validation tests
pass.

- [ ] **Step 6: Commit**

```bash
git add src/harness/controller_state_contracts.py \
  tests/kernel/test_controller_state_contracts.py
git commit -m "feat: validate normalized controller state"
```

---

### Task 3: Registry Schemas and Workflow Ownership Migration

**Files:**
- Create: `extension/workflow/controller-state-contracts.yaml`
- Modify: `extension/workflow/definition.yaml`
- Modify: `src/harness/phase_graph.py`
- Modify: `src/harness/workflow_validator.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Consumes: `load_controller_state_contracts()` and
  `CompiledControllerStateContract`.
- Produces:
  - `PhaseNode.controller_state_contract`
  - `PhaseNode.controller_state_update_keys`
  - `PhaseGraph.controller_contract(name)`

- [ ] **Step 1: Write failing graph and workflow-validator tests**

Add assertions:

```python
def test_shared_controller_contracts_are_compiled_once() -> None:
    graph = PhaseGraph(DEFINITION, EXT_YML)
    first = graph.get("phase3-tasks-lexicon").controller_state_contract
    second = graph.get("phase3-consensus-tasks-lexicon").controller_state_contract
    assert first is second
    assert first.name == "tasks_lexicon"
    assert first.state_update_keys == {
        "tasks_lexicon_action",
        "tasks_lexicon_pass",
        "tasks_lexicon_attempts",
        "tasks_lexicon_findings",
        "tasks_lexicon_report",
        "blocked_reason",
    }


def test_workflow_validator_rejects_legacy_controller_state_updates(tmp_path: Path) -> None:
    definition = _write_definition(tmp_path, [{
        "id": "start",
        "type": "agent",
        "allowed_state_updates": [],
        "controller_state_updates": ["legacy"],
        "transitions": [{"to": "done", "condition": "always"}],
    }, {"id": "done", "type": "terminal"}])
    report = validate_workflow_definition(
        definition_path=definition,
        extension_yml_path=_write_extension_yml(tmp_path),
    )
    assert any("controller_state_updates is no longer supported" in i.message
               for i in report.issues)
```

Also add tests for unknown contract, missing explicit allowlist, overlap,
contract-bearing successful skip, nested controller reference, and controller
fields resolving transition conditions.

- [ ] **Step 2: Run focused graph/validator tests**

```bash
.venv/bin/pytest -q tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py
```

Expected: failures because the registry and new phase property do not exist.

- [ ] **Step 3: Create the five exact schemas**

Create `extension/workflow/controller-state-contracts.yaml` with:

- `spec_lexicon`: evaluation enum; success branches for pending/passed/failed;
  non-negative attempts/findings; Boolean warning waiver.
- `tasks_lexicon`: the action/pass/block invariants from the design.
- `understanding`: evidence object with completed/error branches and
  `quality_scores` entries requiring Boolean `pass`.
- `feasibility_structural`: pass/attempt/findings/report plus exhaustion enum
  `feasibility`.
- `intent_alignment_structural`: corresponding intent-alignment fields plus
  exhaustion enum `intent-alignment-check`.

Every schema must use:

```yaml
type: object
additionalProperties: false
required: [verdict, state_updates]
properties:
  verdict: {type: string}
  state_updates:
    type: object
    additionalProperties: false
    properties: {}
```

Use `allOf` `if`/`then` rules for the semantic invariants; do not add custom
schema keywords or defaults.

- [ ] **Step 4: Load and resolve contracts in PhaseGraph**

Change `PhaseNode`:

```python
controller_state_contract: CompiledControllerStateContract | None = None

@property
def controller_state_update_keys(self) -> frozenset[str]:
    contract = self.controller_state_contract
    return contract.state_update_keys if contract is not None else frozenset()
```

In `PhaseGraph.__init__`, resolve
`controller_state_contracts_file` relative to `definition_path.parent`, compile
once, and replace each phase contract name with the shared object. Raise a
clear `ControllerContractRegistryError` for unknown references.

- [ ] **Step 5: Migrate all seven workflow nodes atomically**

At the root:

```yaml
controller_state_contracts_file: controller-state-contracts.yaml
```

Replace every `controller_state_updates` block with exactly one of:

```yaml
controller_state_contract: spec_lexicon
controller_state_contract: tasks_lexicon
controller_state_contract: understanding
controller_state_contract: feasibility_structural
controller_state_contract: intent_alignment_structural
```

Keep each current `allowed_state_updates`, including explicit empty lists.

- [ ] **Step 6: Strengthen workflow startup validation**

Update `_phase_condition_fields()` to receive the resolved `PhaseNode` or
derived contract keys. Reject:

- legacy `controller_state_updates`;
- unknown contract;
- missing `allowed_state_updates`;
- overlap;
- contract on a nested agent;
- `skip_agent_proceed_to_next` on a contract-bearing phase.

Keep provider type/enum validation unchanged.

- [ ] **Step 7: Run graph and workflow tests**

```bash
.venv/bin/pytest -q tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/unit/test_tasks_wiring.py \
  tests/unit/test_structural_wiring.py
```

Expected: all pass with no legacy controller list.

- [ ] **Step 8: Commit**

```bash
git add extension/workflow/controller-state-contracts.yaml \
  extension/workflow/definition.yaml src/harness/phase_graph.py \
  src/harness/workflow_validator.py tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py tests/unit/test_tasks_wiring.py \
  tests/unit/test_structural_wiring.py
git commit -m "feat: declare reusable controller state contracts"
```

---

### Task 4: Immutable Prepared Phase Result Boundary

**Files:**
- Create: `src/harness/prepared_phase_result.py`
- Create: `tests/kernel/test_prepared_phase_result.py`

**Interfaces:**
- Consumes: compiled contracts, normalization, controller validation,
  `PhaseNode`, and `SquadAgentResult`.
- Produces:
  - `PreparedPhaseResult`
  - `prepare_phase_result(node, result, controller_updates, routing_override,
    controller_owns_result_updates=False)`

- [ ] **Step 1: Add failing ownership, normalization, and immutability tests**

```python
def _result(updates: dict[str, object]) -> SquadAgentResult:
    return SquadAgentResult(
        exit_code=0,
        echelon_result={"verdict": "DONE", "state_updates": updates},
        raw_output="",
        duration_ms=0,
        timed_out=False,
    )


def _node(contract: CompiledControllerStateContract) -> PhaseNode:
    return PhaseNode(
        id="controller-node",
        type="deterministic_lexicon",
        allowed_state_updates=[],
        controller_state_contract=contract,
    )


@pytest.fixture
def contract(tmp_path: Path) -> CompiledControllerStateContract:
    path = tmp_path / "contracts.yaml"
    path.write_text(
        """
schema_version: 1
contracts:
  sample:
    $schema: https://json-schema.org/draft/2020-12/schema
    type: object
    additionalProperties: false
    required: [verdict, state_updates]
    properties:
      verdict: {type: string}
      state_updates:
        type: object
        additionalProperties: false
        properties:
          tasks_lexicon_pass: {type: boolean}
          tasks_lexicon_report: {type: string}
""".lstrip(),
        encoding="utf-8",
    )
    return load_controller_state_contracts(path)["sample"]


def test_prepare_merges_disjoint_provider_and_controller_updates(contract) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["status"],
        controller_state_contract=contract,
    )
    result = _result({"status": "running"})
    prepared = prepare_phase_result(
        node,
        result,
        controller_updates={"tasks_lexicon_report": PurePath("report.json")},
        controller_owns_result_updates=False,
    )
    assert prepared.state_updates == {
        "status": "running",
        "tasks_lexicon_report": "report.json",
    }
    assert prepared.normalized_paths == (
        "$.state_updates.tasks_lexicon_report",
    )


def test_prepare_rejects_provider_controller_overlap(contract) -> None:
    node = PhaseNode(
        id="mixed",
        type="agent",
        allowed_state_updates=["tasks_lexicon_pass"],
        controller_state_contract=contract,
    )
    with pytest.raises(ControllerStateContractViolation, match="overlap"):
        prepare_phase_result(node, _result({}), controller_updates={})


def test_prepared_result_has_no_alias_to_executor_payload(contract) -> None:
    result = _result({})
    controller = {"tasks_lexicon_report": PurePath("report.json")}
    prepared = prepare_phase_result(_node(contract), result, controller)
    controller["tasks_lexicon_report"] = "changed"
    result.echelon_result["state_updates"]["other"] = "changed"
    assert prepared.state_updates["tasks_lexicon_report"] == "report.json"
```

- [ ] **Step 2: Run tests and confirm the module is missing**

```bash
.venv/bin/pytest -q tests/kernel/test_prepared_phase_result.py
```

Expected: collection failure for `harness.prepared_phase_result`.

- [ ] **Step 3: Implement the prepared result**

```python
@dataclass(frozen=True)
class PreparedPhaseResult:
    _result: SquadAgentResult = field(repr=False)
    provider_update_keys: frozenset[str]
    controller_update_keys: frozenset[str]
    controller_contract_name: str | None
    controller_contract_sha256: str | None
    normalized_paths: tuple[str, ...]
    routing_override: str | None = None

    @property
    def echelon_result(self) -> dict[str, Any]:
        payload = self._result.echelon_result
        return deepcopy(payload) if isinstance(payload, dict) else {}

    @property
    def verdict(self) -> str:
        return str(self._result.verdict or "")

    @property
    def state_updates(self) -> dict[str, Any]:
        return deepcopy(self._result.state_updates)

    def as_squad_agent_result(self) -> SquadAgentResult:
        return deepcopy(self._result)
```

The factory must:

1. deep-copy and validate the base result;
2. derive provider and controller allowed sets;
3. reject overlap and unknown final keys;
4. normalize controller updates;
5. validate the synthetic controller payload;
6. deep-copy the canonical `SquadAgentResult` into the immutable wrapper.

When `controller_owns_result_updates` is true, require an explicitly empty
provider allowlist and move all raw result updates into the controller bundle
before merging enrichment. When it is false, reject any raw result key outside
the provider allowlist, including controller keys. This prevents a mixed
provider node from impersonating controller enrichment.

Raise the first deterministic `ControllerStateContractViolation` for
diagnostics.

- [ ] **Step 4: Run prepared-result tests**

```bash
.venv/bin/pytest -q tests/kernel/test_prepared_phase_result.py
```

Expected: all ownership, normalization, schema, and alias tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/prepared_phase_result.py \
  tests/kernel/test_prepared_phase_result.py
git commit -m "feat: add prepared phase result boundary"
```

---

### Task 5: Separate Controller Enrichment from Transition Evaluation

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_phase2_tracker_routing.py`
- Modify: `tests/unit/test_consensus_routing.py`

**Interfaces:**
- Consumes: `PreparedPhaseResult`, `prepare_phase_result()`.
- Produces:
  - `ControllerEnrichment`
  - `SquadController._controller_enrichment()`
  - read-only `_evaluate_transitions(node, prepared)`

- [ ] **Step 1: Add tests proving enrichment is separate and routing is read-only**

```python
def test_governance_enrichment_does_not_mutate_provider_result(tmp_path: Path) -> None:
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase2-decide")
    provider_result = self._result({"status": "running"})
    original = deepcopy(provider_result.echelon_result)
    enrichment = ctrl._controller_enrichment(node, store.load(), provider_result)
    assert provider_result.echelon_result == original
    assert "feasibility_structural_pass" in enrichment.updates


def test_transition_evaluation_does_not_mutate_prepared_result_or_state(tmp_path: Path) -> None:
    ctrl, store = _controller(tmp_path)
    prepared = _prepared_tasks_result(ctrl, action="proceed")
    before_state = store.load()
    before_payload = prepared.echelon_result
    assert ctrl._evaluate_transitions(
        ctrl._graph.get("phase3-tasks-lexicon"), prepared
    ) == "phase3-understanding"
    assert store.load() == before_state
    assert prepared.echelon_result == before_payload
```

Add hard-exhaustion tests proving the enrichment returns
`routing_override="terminal-blocked"` and metadata without saving state.

- [ ] **Step 2: Run focused tests and confirm they fail**

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_phase2_tracker_routing.py \
  tests/unit/test_consensus_routing.py
```

Expected: new tests fail because enrichment mutates the raw result and
transition evaluation still accepts it.

- [ ] **Step 3: Add a separate enrichment value**

```python
@dataclass(frozen=True)
class ControllerEnrichment:
    updates: Mapping[str, object] = field(default_factory=dict)
    routing_override: str | None = None
    controller_owns_result_updates: bool = False
```

Convert governance structural validation to return updates. Convert Lexicon
warning/exhaustion and governance exhaustion helpers to return additional
updates and optional routing override. They may write evidence reports but
must not save state or mutate `SquadAgentResult`.

Deterministic Lexicon and Understanding enrichment sets
`controller_owns_result_updates=True`. Mixed governance enrichment leaves it
false.

- [ ] **Step 4: Make transition evaluation consume only prepared results**

Change:

```python
def _evaluate_transitions(
    self,
    node: PhaseNode,
    prepared: PreparedPhaseResult,
) -> str:
    if prepared.routing_override:
        return prepared.routing_override
    result = prepared.as_squad_agent_result()
    state = self._state_store.load()
    eval_state = {
        **self._lexicon_gate_config(),
        **self._governance_config(),
        **state,
        **prepared.state_updates,
    }
    # existing condition order, with no result/state mutation
```

Move all result mutation before `prepare_phase_result()`. Keep existing
condition order and routing behavior.

- [ ] **Step 5: Update direct routing tests to prepare results**

Every test calling `_evaluate_transitions(node, raw_result)` must call the
controller preparation helper first. Do not expose a bypass flag for tests.

- [ ] **Step 6: Run routing and governance tests**

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_phase2_tracker_routing.py \
  tests/unit/test_consensus_routing.py \
  tests/unit/test_understanding_gate.py
```

Expected: all pass; transition evaluation is read-only.

- [ ] **Step 7: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py \
  tests/unit/test_phase2_tracker_routing.py \
  tests/unit/test_consensus_routing.py tests/unit/test_understanding_gate.py
git commit -m "refactor: prepare controller state before routing"
```

---

### Task 6: Fail-Closed Execution Paths and Diagnostics

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Consumes: enrichment and prepared-result factory.
- Produces:
  - `_prepare_phase_result_or_block() -> PreparedPhaseResult | None`
  - stable `controller_contract_error` state.

- [ ] **Step 1: Add a malformed-output call-order test**

```python
def test_malformed_controller_output_blocks_before_all_success_steps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctrl, store = _controller(tmp_path)
    node = ctrl._graph.get("phase3-tasks-lexicon")
    raw = self._result({
        "tasks_lexicon_action": "proceed",
        "tasks_lexicon_pass": "not-boolean",
        "tasks_lexicon_attempts": 0,
        "tasks_lexicon_findings": 0,
    })
    calls = []
    monkeypatch.setattr(ctrl, "_evaluate_transitions",
                        lambda *_: calls.append("transition"))
    monkeypatch.setattr(ctrl, "_apply_product_input_updates",
                        lambda *_: calls.append("product"))
    monkeypatch.setattr(ctrl, "_checkpoint_successful_phase",
                        lambda *_: calls.append("checkpoint"))
    prepared = ctrl._prepare_phase_result_or_block(node, raw)
    assert prepared is None
    assert calls == []
    state = store.load()
    assert state["phase"] == node.id
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "controller_state_contract_validation_failed"
    assert state["controller_contract_error"]["contract"] == "tasks_lexicon"
    assert "not-boolean" not in json.dumps(state["controller_contract_error"])
```

Add equivalent tests for manual execution, resumed execution, valid `BLOCKED`
Understanding evidence, and mixed governance.

- [ ] **Step 2: Run the new fail-closed tests**

Expected: failures because orchestration handles blocked/product-input work
before controller preparation.

- [ ] **Step 3: Implement one preparation/error handler**

```python
def _prepare_phase_result_or_block(
    self,
    node: PhaseNode,
    result: SquadAgentResult,
) -> PreparedPhaseResult | None:
    state = self._state_store.load()
    try:
        enrichment = self._controller_enrichment(node, state, result)
        prepared = prepare_phase_result(
            node,
            result,
            controller_updates=enrichment.updates,
            routing_override=enrichment.routing_override,
            controller_owns_result_updates=(
                enrichment.controller_owns_result_updates
            ),
        )
    except ControllerStateContractViolation as exc:
        blocked = self._state_store.load()
        blocked["phase"] = node.id
        blocked["status"] = "blocked"
        blocked["blocked_reason"] = (
            "controller_state_contract_validation_failed"
        )
        blocked["controller_contract_error"] = {
            "phase_id": node.id,
            "contract": exc.contract,
            "contract_sha256": (
                node.controller_state_contract.sha256
                if node.controller_state_contract is not None else None
            ),
            "json_path": exc.json_path,
            "validator": exc.validator,
            "message": str(exc),
        }
        self._state_store.save(blocked)
        return None
    return prepared
```

Build messages without raw rejected values. Clear
`controller_contract_error` only after a later successful preparation and
advance.

- [ ] **Step 4: Put preparation first in every execution path**

Normal and manual execution order becomes:

```python
prepared = self._prepare_phase_result_or_block(node, result)
if prepared is None:
    return SquadResult.from_state(self._state_store.load())
blocked_reason = self._blocked_executor_reason(
    prepared.as_squad_agent_result()
)
if blocked_reason:
    self._block_after_executor_failure(
        phase,
        blocked_reason,
        prepared.as_squad_agent_result(),
    )
    return SquadResult.from_state(self._state_store.load())
product_input_error = self._apply_product_input_updates(
    prepared.as_squad_agent_result(), phase
)
if product_input_error:
    if self._schedule_product_input_mapping_repair(
        phase,
        product_input_error,
        prepared.as_squad_agent_result(),
    ):
        continue
    self._block_after_executor_failure(
        phase,
        product_input_error,
        prepared.as_squad_agent_result(),
    )
    return SquadResult.from_state(self._state_store.load())
next_phase = self._evaluate_transitions(node, prepared)
```

Skip paths remain allowed only for nodes without controller contracts and must
wrap their empty result with the same prepared factory.

- [ ] **Step 5: Run orchestration and checkpoint tests**

```bash
.venv/bin/pytest -q tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

Expected: all malformed-result call-order tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
git commit -m "feat: block malformed controller state before routing"
```

---

### Task 7: Transactional State Advance and Atomic Iteration Increment

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/kernel/test_squad_state.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: `PreparedPhaseResult`.
- Produces:
  - `StateAdvanceError(RuntimeError)`
  - `AdvanceReceipt`
  - `advance(from_phase: str, to_phase: str, prepared: PreparedPhaseResult, *,
    increment_iteration: bool = False, manual_phase_run: bool = False) ->
    AdvanceReceipt`

- [ ] **Step 1: Add all-or-error state tests**

```python
def test_invalid_advance_raises_without_success_state_mutation(tmp_path: Path) -> None:
    store = _initialized_store(tmp_path)
    before = store.load()
    invalid = _invalid_prepared_result()
    with pytest.raises(StateAdvanceError):
        store.advance("init", "phase1-discover", invalid)
    after = store.load()
    assert after["phase"] == before["phase"]
    assert after["completed_phases"] == before["completed_phases"]
    assert after["last_dispatch"] == before["last_dispatch"]


def test_advance_applies_iteration_and_contract_receipt_atomically(tmp_path: Path) -> None:
    store = _initialized_store(tmp_path)
    receipt = store.advance(
        "phase3-tasks-lexicon",
        "phase3-plan",
        _prepared_tasks_result(),
        increment_iteration=True,
    )
    state = store.load()
    assert state["iteration"] == 1
    assert state["last_dispatch"]["controller_contract"] == "tasks_lexicon"
    assert state["last_dispatch"]["controller_contract_sha256"]
    assert receipt.to_phase == "phase3-plan"
```

- [ ] **Step 2: Run state tests and confirm existing silent-return behavior fails**

```bash
.venv/bin/pytest -q tests/kernel/test_squad_state.py
```

Expected: the new invalid-advance test fails because `advance()` currently
blocks and returns `None`.

- [ ] **Step 3: Implement typed receipts and all-or-error advance**

```python
class StateAdvanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdvanceReceipt:
    from_phase: str
    to_phase: str
    completed_at: str
    controller_contract: str | None
    controller_contract_sha256: str | None


def advance(
    self,
    from_phase: str,
    to_phase: str,
    prepared: PreparedPhaseResult,
    *,
    increment_iteration: bool = False,
    manual_phase_run: bool = False,
) -> AdvanceReceipt:
    state = self.load()
    try:
        result = validate_echelon_result(
            prepared.echelon_result,
            allowed_state_update_keys=(
                prepared.provider_update_keys | prepared.controller_update_keys
            ),
        )
    except EchelonResultValidationError as exc:
        raise StateAdvanceError(str(exc)) from exc
    next_state = deepcopy(state)
    completed_at = datetime.now(timezone.utc).isoformat()
    next_state["phase"] = to_phase
    next_state["last_dispatch"] = {
        "phase_id": from_phase,
        "verdict": prepared.verdict,
        "completed_at": completed_at,
        "controller_contract": prepared.controller_contract_name,
        "controller_contract_sha256": prepared.controller_contract_sha256,
        "controller_normalized": bool(prepared.normalized_paths),
    }
    if manual_phase_run:
        next_state["last_dispatch"]["manual_phase_run"] = True
        manual_runs = next_state.get("manual_phase_runs")
        manual_runs = list(manual_runs) if isinstance(manual_runs, list) else []
        manual_runs.append({
            "phase_id": from_phase,
            "next_phase": to_phase,
            "verdict": prepared.verdict,
            "completed_at": completed_at,
        })
        next_state["manual_phase_runs"] = manual_runs
    completed = next_state.get("completed_phases")
    completed = list(completed) if isinstance(completed, list) else []
    if from_phase not in completed:
        completed.append(from_phase)
    next_state["completed_phases"] = completed
    identity_is_bootstrapped = bool(next_state.get("feature_branch"))
    for key, value in result["state_updates"].items():
        if identity_is_bootstrapped and key in PHASE_A_IDENTITY_KEYS:
            if next_state.get(key) != value:
                logger.warning(
                    "Ignoring attempt to change controller-owned Phase A identity %s",
                    key,
                )
            continue
        if key == "status":
            self._transition_status(next_state, value)
        else:
            next_state[key] = value
    if increment_iteration and "iteration" not in result["state_updates"]:
        next_state["iteration"] = int(next_state.get("iteration") or 0) + 1
    next_state.pop("controller_contract_error", None)
    self.save(next_state)
    return AdvanceReceipt(
        from_phase=from_phase,
        to_phase=to_phase,
        completed_at=completed_at,
        controller_contract=prepared.controller_contract_name,
        controller_contract_sha256=prepared.controller_contract_sha256,
    )
```

`self.save()` is the only state write on success.

- [ ] **Step 4: Select increment before advance and checkpoint**

Add:

```python
def _transition_increments_iteration(
    node: PhaseNode,
    next_phase: str,
) -> bool:
    return any(
        transition.get("to") == next_phase
        and transition.get("action") == "increment_iteration"
        for transition in node.transitions
    )
```

Pass this Boolean into `advance()`. Remove the post-checkpoint iteration block.
Move `_apply_declared_phase_timing_transition()` after successful advance and
before checkpointing; it is telemetry and remains best-effort.

- [ ] **Step 5: Catch advance errors without checkpointing**

On `StateAdvanceError`, write a blocked diagnostic at the current phase and
return. Do not call timing transition or checkpoint methods.

- [ ] **Step 6: Run state, orchestration, and checkpoint tests**

```bash
.venv/bin/pytest -q tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

Expected: all pass, including checkpoint snapshots containing the incremented
iteration and contract receipt.

- [ ] **Step 7: Commit**

```bash
git add src/harness/squad_state.py src/harness/squad.py \
  tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
git commit -m "refactor: make phase state advance transactional"
```

---

### Task 8: Regression, Documentation Alignment, and Release Verification

**Files:**
- Modify only if assertions require alignment:
  - `tests/kernel/test_squad_executors_journal.py`
  - `tests/unit/test_tasks_wiring.py`
  - `tests/unit/test_structural_wiring.py`
  - `tests/unit/test_understanding_gate.py`
  - `docs/superpowers/specs/2026-07-23-controller-state-contracts-design.md`
- Modify for release:
  - `pyproject.toml`
  - `extension/extension.yml`
  - `src/echelon/cli.py`
  - `README.md`
  - `uv.lock`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified Echelon `3.7.14` release metadata and final test evidence.

- [ ] **Step 1: Run all directly affected tests**

```bash
.venv/bin/pytest -q \
  tests/kernel/test_controller_state_contracts.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_echelon_result_schema.py \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_squad_state.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/unit/test_tasks_wiring.py \
  tests/unit/test_structural_wiring.py \
  tests/unit/test_understanding_gate.py \
  tests/unit/test_phase2_tracker_routing.py \
  tests/unit/test_consensus_routing.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/integration/test_squad_controller.py
```

Expected: all pass.

- [ ] **Step 2: Run static contract and workflow checks**

```bash
.venv/bin/python -m harness.workflow_validator \
  extension/workflow/definition.yaml extension/extension.yml
git diff --check
```

If the validator has no module CLI, invoke
`validate_workflow_definition()` in a short read-only Python command and assert
`report.ok`.

Expected: workflow valid and no whitespace errors.

- [ ] **Step 3: Run the complete repository suite**

```bash
.venv/bin/pytest -q
```

Expected: all tests pass with no unexpected skips or collection errors.

- [ ] **Step 4: Verify no legacy declarations or duplicated operational schemas**

```bash
rg -n "controller_state_updates" extension src tests
rg -n "tasks_lexicon_action.*enum|tasks_lexicon_pass.*boolean" \
  extension/workflow --glob '*.md' --glob '*.yaml'
```

Expected:

- no runtime occurrence of `controller_state_updates` except the explicit
  validator rejection test;
- exact controller field schemas occur only in
  `controller-state-contracts.yaml`.

- [ ] **Step 5: Bump release metadata to 3.7.14**

Update every canonical version location from `3.7.13` to `3.7.14`, then run:

```bash
uv lock
rg -n "3\\.7\\.13|3\\.7\\.14" pyproject.toml extension/extension.yml \
  src/echelon/cli.py README.md uv.lock
```

Expected: canonical release metadata reports `3.7.14`; old-version occurrences
are only historical text if any.

- [ ] **Step 6: Commit release metadata**

```bash
git add pyproject.toml extension/extension.yml src/echelon/cli.py README.md uv.lock
git commit -m "chore: release v3.7.14"
```

- [ ] **Step 7: Final clean verification**

```bash
git status --short
git log -10 --oneline
```

Expected: only the pre-existing unrelated untracked findings document remains;
all implementation and release commits are present.

Do not push until the user explicitly requests publication.
