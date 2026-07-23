# Controller State Contracts Design

**Date:** 2026-07-23  
**Status:** Approved design; awaiting written-spec review  
**Scope:** Add one fail-closed, reusable contract boundary for controller-owned
workflow state.

## Goal

Make controller-produced workflow state as deterministic and fail-closed as
provider-produced state without:

- giving providers permission to write controller-owned fields;
- duplicating field contracts in multiple workflow nodes or Markdown files;
- introducing a compatibility switch or parallel execution path;
- allowing malformed routing values to reach transition evaluation,
  persistence, phase completion, or checkpointing.

The result must be a single reusable mechanism for current Lexicon,
Understanding, and governance nodes and for future controller-producing nodes.

## Current Problem

The workflow currently separates provider and controller ownership:

- `allowed_state_updates` lists provider-owned fields;
- `controller_state_updates` lists fields added by deterministic executors or
  controller enrichment.

Provider fields can use `state_update_types` and `state_update_enums`.
Controller fields cannot use those declarations because the workflow validator
requires type and enum keys to be a subset of `allowed_state_updates`.

At the final state-store boundary, provider and controller key lists are
combined. That boundary validates result shape and allowed keys but does not
generically validate controller field types, enums, required fields, or
cross-field consistency. The normal producers construct correct values, but a
producer defect can still create malformed or contradictory routing state.

The current state-store failure behavior is also insufficiently transactional:
`advance()` can mark the state blocked and return to a caller that proceeds
toward successful checkpoint handling.

## Design Principles

1. One authoritative schema definition per controller contract.
2. Multiple phases may reference the same named contract.
3. Provider and controller ownership remain disjoint.
4. Use a standard schema implementation instead of inventing a new expression
   language.
5. Normalize only lossless structural representations.
6. Validate before any transition or successful phase side effect.
7. Make invalid prepared results impossible to pass accidentally to routing.
8. Fail closed at the current phase with structured diagnostics.
9. Preserve the existing state field names and valid workflow behavior.
10. Migrate all current controller-producing nodes atomically.

## Non-Goals

This change does not:

- change Lexicon, Understanding, or governance business rules;
- rename existing persisted controller fields;
- change provider-owned workflow contract syntax;
- add automatic correction of semantic values;
- coerce strings into booleans, numbers, or enum values;
- add a feature flag, compatibility mode, shadow path, or fallback parser;
- retroactively certify controller values written by an older Echelon version;
- redesign checkpoint storage or artifact checkpoint ownership;
- implement currently descriptive transition actions other than the existing
  `increment_iteration` state mutation;
- make nested provider agents controller-state producers.

## Authoritative Contract Registry

Controller contracts live in:

```text
extension/workflow/controller-state-contracts.yaml
```

The root of `workflow/definition.yaml` declares the registry once:

```yaml
controller_state_contracts_file: controller-state-contracts.yaml
```

The path is resolved relative to the directory containing
`workflow/definition.yaml`. A phase references one named contract:

```yaml
allowed_state_updates: []
controller_state_contract: tasks_lexicon
```

Runtime and phase Markdown may explain a contract's purpose and refer to its
name, but it must not duplicate field lists, types, enums, required fields, or
invariants. This historical design record describes required behavior but is
not an operational schema source.

### Registry format

The registry is YAML containing JSON Schema Draft 2020-12 schemas. Its
structural shape is:

```yaml
schema_version: 1
contracts:
  example_contract:
    $schema: "https://json-schema.org/draft/2020-12/schema"
    type: object
    additionalProperties: false
    required: [verdict, state_updates]
    properties:
      verdict:
        type: string
      state_updates:
        type: object
        additionalProperties: false
        properties:
          example_field:
            type: string
    allOf: []
```

The validator receives a synthetic object containing the real result verdict
and only the controller-owned portion of `state_updates`. This permits one
schema to define success and `BLOCKED` requirements without duplicating field
definitions. The example above shows structure only; exact fields and
invariants exist solely in the registry.

### Supported schema profile

Each named contract MUST:

- have a top-level object schema;
- set `additionalProperties: false` at the top level;
- declare `verdict` and `state_updates`;
- make `state_updates` an object;
- set `state_updates.additionalProperties: false`;
- declare controller-owned keys only under
  `properties.state_updates.properties`;
- use only local `#/$defs/...` references when `$ref` is needed.

Remote, file, and network references are forbidden. Defaults are forbidden:
the schema validates state but never invents it.

The registry loader rejects duplicate YAML mapping keys before schema parsing.
Every schema is checked with `Draft202012Validator.check_schema()` at workflow
startup. `jsonschema` becomes a direct project dependency rather than relying
on its current transitive presence.

## Named Contracts and Atomic Migration

The first release defines five contracts:

| Contract | Referencing phases |
|---|---|
| `spec_lexicon` | `phase1-lexicon` |
| `tasks_lexicon` | `phase3-tasks-lexicon`, `phase3-consensus-tasks-lexicon` |
| `understanding` | `phase1-understanding`, `phase3-understanding` |
| `feasibility_structural` | `phase2-decide` |
| `intent_alignment_structural` | `phase2-tracker-alignment` |

The contract schemas own the existing 23 unique controller fields. The two
Tasks Lexicon phases and two Understanding phases resolve the same compiled
contract object and digest within one `PhaseGraph`.

The migration removes `controller_state_updates` from all seven phases and
from `PhaseNode`. Workflow validation rejects the legacy key after migration.
There is no dual parser and no fallback to the removed list.

For any phase with `controller_state_contract`:

- `allowed_state_updates` MUST be explicitly present, even when empty;
- provider and controller fields MUST be disjoint;
- nested `agents[]` entries cannot declare or emit controller-owned fields;
- `on_greenfield.action: skip_agent_proceed_to_next` is invalid because it
  would bypass required controller production.

Controller-owned keys are derived from the named schema. No separate list is
maintained.

## Contract Compilation

`PhaseGraph` loads and compiles the registry once. A compiled contract contains:

- name;
- immutable schema;
- derived controller-owned key set;
- `Draft202012Validator`;
- canonical SHA-256 digest.

The digest is calculated from canonical JSON serialization of the parsed
schema with sorted keys and stable separators. It identifies the exact
contract used for a phase result.

Schema objects and derived key sets are immutable after graph construction.
One phase cannot broaden another phase's contract at runtime.

## Controller Update Provenance

Provider updates and controller updates remain separate until preparation:

```text
provider result state_updates ─┐
                               ├─ ownership check ─ normalize controller values
controller update bundle ──────┘                         │
                                                         v
                                               contract validation
                                                         │
                                                         v
                                               immutable prepared result
```

Controller enrichment functions MUST return a separate controller update
mapping. They must not mutate provider `state_updates` in place.

For provider-free deterministic nodes, all result state updates are treated as
the controller update bundle because `allowed_state_updates` is explicitly
empty.

For mixed agent/controller nodes:

1. the executor validates provider updates against `allowed_state_updates`;
2. governance enrichment returns a separate controller mapping;
3. preparation rejects overlap before merging.

The final key set MUST be a subset of:

```text
provider allowed keys UNION controller contract keys
```

This union check happens before routing. It catches an undeclared controller
field even if a producer accidentally adds it under a provider-shaped result.

All controller mutations currently embedded in transition evaluation move to
the preparation stage, including:

- structural governance pass/attempt/finding/report fields;
- governance exhaustion metadata;
- spec Lexicon warning-waiver metadata.

Transition evaluation becomes read-only with respect to result and persisted
state.

## Lossless Normalization

Normalization operates on a deep copy of controller values. Provider values
retain their existing contract behavior.

The only supported conversions are:

| Input | Normalized representation |
|---|---|
| `os.PathLike` returning text | string |
| `enum.Enum` with a supported scalar value | its scalar value |
| exact tuple | list |
| `collections.abc.Mapping` with string keys | plain dictionary |

Normalization is recursive with:

- cycle detection;
- maximum nesting depth of 32;
- maximum 10,000 visited container/scalar nodes;
- maximum 10,000 entries in any one collection;
- rejection of duplicate or non-string mapping keys;
- rejection of `PathLike` values returning bytes.

The following are not normalized:

- string booleans or numbers;
- booleans used as integers;
- enum case or whitespace;
- sets, frozensets, generators, or other unordered/lazy collections;
- dataclasses or arbitrary objects;
- `Decimal`, date/time, or byte values;
- absent fields or guessed defaults.

Normalization MUST be idempotent. The normalized copy is used for both
transition evaluation and persistence. The unnormalized object is never
re-read after successful preparation.

Telemetry records contract name and normalized JSON paths, not field values.

## Prepared Phase Result Boundary

Introduce an immutable `PreparedPhaseResult`, created only by a preparation
factory. It contains:

- canonical normalized result payload with no mutable aliases to the executor
  payload;
- provider-owned update keys;
- controller-owned update keys;
- controller contract name and digest, when present;
- normalized field paths;
- any validated controller routing directive.

The factory also attaches an internal, process-local attestation over the
canonical payload and its preparation provenance, including phase identity,
ownership sets, contract identity, normalized paths, and routing override.
State advancement verifies that attestation before persistence. Ordinary
attestation-protocol failures during preparation become one generic,
value-redacted `ControllerStateContractViolation` with no chained cause or
context; already typed contract violations and process-control exceptions
retain their existing semantics.

`_evaluate_transitions()` accepts `PreparedPhaseResult`, not raw
`SquadAgentResult`. State advancement also accepts the prepared form. This
forces production and test call sites through the same boundary.

Preparation order is:

1. Receive the executor result.
2. Apply the existing provider result contract.
3. Produce controller enrichment as a separate candidate mapping.
4. Apply controller policy calculations without persisting state.
5. Losslessly normalize controller values.
6. Reject provider/controller overlap and keys outside the ownership union.
7. Validate the synthetic controller result against its named schema.
8. Deep-copy and seal the canonical prepared result.
9. Handle a valid `BLOCKED` result, or evaluate transitions for a valid
   non-blocked result.
10. Apply product-input side effects only after result preparation succeeds.
11. Determine whether the selected transition applies the existing
    `increment_iteration` state mutation.
12. Atomically advance state with the normalized updates, optional iteration
    increment, completion history, and contract receipt.
13. Apply successful post-commit timing telemetry.
14. Create the successful phase checkpoint.

No success-side state mutation occurs before preparation succeeds. Evidence
files produced while evaluating an artifact may exist after a validation
failure, but they remain uncheckpointed and cannot affect routing.

## BLOCKED Semantics

A result with verdict `BLOCKED` still enters preparation:

- all present controller fields are normalized and schema-validated;
- the contract's `BLOCKED` branch determines required controller fields;
- no success-only fields are required;
- no transition is evaluated;
- the phase is not marked completed;
- no successful checkpoint is created.

For deterministic Lexicon and Understanding execution failures, the contract
requires a non-empty `blocked_reason`.

A valid business decision such as:

```yaml
verdict: DONE
state_updates:
  tasks_lexicon_action: block
  tasks_lexicon_pass: false
  tasks_lexicon_attempts: 3
  tasks_lexicon_findings: 8
  blocked_reason: lexicon_gate_exhausted
```

is not an executor failure. It is a successful, contract-valid deterministic
result whose explicit workflow transition may target `terminal-blocked`.

## Semantic Invariants

Each contract validates the routing relationships it owns, not merely scalar
types.

### `tasks_lexicon`

- `proceed` implies pass is true.
- `repair`, `proceed_with_warning`, and `block` imply pass is false.
- `block` requires `blocked_reason`.
- attempts and findings are non-negative.
- successful non-blocked execution requires action, pass, attempts, and
  findings.

### `spec_lexicon`

- evaluation is one of `pending`, `passed`, or `failed`.
- `pending` does not claim a pass or certified report.
- When the global gate or spec artifact subgate is disabled, the existing
  unexecuted branch persists only `pending` evaluation and attempt count,
  removes stale pass, findings, and report evidence, and routes onward using
  the derived effective `lexicon_gate.spec_enabled` value.
- `passed` requires pass true, zero findings, and a report.
- `failed` requires pass false, at least one finding, and a report.
- attempts and findings are non-negative.
- warning waiver is Boolean when present.

### `understanding`

- evidence status is `completed` or `error`.
- completed evidence requires a digest, path, Boolean pass value, and
  quality-score output.
- error evidence requires a non-empty error and controller blocked reason.
- iteration is non-negative.
- quality score entries retain the existing mandatory Boolean `pass` shape.

### Structural governance contracts

- pass and attempts are always present after successful enrichment.
- pass is Boolean and attempts/findings are non-negative integers.
- a report is required when findings were produced.
- exhaustion metadata, when present, is restricted to that contract's
  artifact identifier.

The schemas must not encode configuration defaults. Enrichment resolves
configuration first and then emits a complete candidate result for validation.

## Transactional State Advancement

`SquadStateStore.advance()` becomes an all-or-error operation.

It MUST:

1. load current state;
2. build the complete next state in memory;
3. validate the prepared result receipt and ownership metadata;
4. apply the normalized updates to the in-memory copy;
5. apply `increment_iteration` when selected and not already supplied by the
   validated result;
6. add completion history and contract receipt;
7. perform the existing atomic file replacement;
8. return an `AdvanceReceipt`.

The controller accepts that receipt only after loading the newly persisted
state and proving that `last_dispatch` is new and matches the requested phase
advance, completion identity, prepared contract provenance, and receipt.

It MUST NOT catch a validation error, mutate state to blocked, and return
normally.

On failure it raises a typed exception before changing:

- phase;
- completed phases;
- last successful dispatch;
- timing transition state;
- controller values;
- checkpoint metadata.

The controller catches the exception and writes a separate blocked-state
diagnostic. That diagnostic is not a successful phase advance.

## Failure Diagnostics

A controller contract failure leaves the run at the current phase with:

```json
{
  "status": "blocked",
  "blocked_reason": "controller_state_contract_validation_failed",
  "controller_contract_error": {
    "phase_id": "phase3-tasks-lexicon",
    "contract": "tasks_lexicon",
    "contract_sha256": "...",
    "json_path": "$.state_updates.tasks_lexicon_pass",
    "validator": "type",
    "message": "expected boolean"
  }
}
```

Diagnostics never include the rejected value. Errors are sorted by JSON path
and validator name so repeated failures are deterministic.

The same data is emitted to telemetry. A successful rerun clears
`controller_contract_error`.

The run does not:

- select or evaluate a transition;
- increment workflow iteration through transition action;
- mark the phase completed;
- write a successful phase receipt;
- apply successful timing transition state;
- create a successful phase checkpoint.

The current phase remains retryable. Existing dispatch limits still prevent an
unbounded retry loop.

## Successful Receipt and Checkpoint Ordering

Every successfully advanced phase with a controller contract records:

```json
{
  "controller_contract": "tasks_lexicon",
  "controller_contract_sha256": "...",
  "controller_normalized": false
}
```

This metadata is stored in `last_dispatch` and captured by the existing phase
checkpoint. It is an audit receipt for the newly produced result, not a
retroactive migration mechanism for older runs.

Required order:

```text
prepare and validate
        ↓
evaluate transition
        ↓
resolve existing increment-iteration mutation
        ↓
atomic state advance, optional increment, and receipt
        ↓
post-commit timing telemetry
        ↓
phase checkpoint
```

Every newly persisted dispatch and `AdvanceReceipt` carries an exact Boolean
`conditional_skip` identity. `false` identifies an executed phase and `true`
identifies the explicit condition-false skip path. This identity is verified
independently from `manual_phase_run`: a manual invocation can execute normally
or perform a conditional skip, so neither marker substitutes for the other.

If state advance fails, checkpointing is not attempted. If checkpointing
fails, existing checkpoint failure handling remains responsible for blocking
the run; this design does not redefine checkpoint rollback semantics.

## Workflow Validation

Startup validation rejects:

- missing registry file;
- unsupported registry version;
- duplicate YAML keys;
- invalid JSON Schema;
- duplicate contract names;
- unknown phase contract references;
- legacy `controller_state_updates`;
- missing explicit provider allowlist on a controller-contract phase;
- provider/controller field overlap;
- controller schemas that allow additional state properties;
- remote or non-local schema references;
- unsupported skip semantics on a controller-contract phase;
- nested agent controller ownership;
- transition fields that cannot be resolved from declared provider fields,
  controller fields, outputs, config namespaces, or established state.

These checks run before a controller or provider is dispatched.

## Execution Path Coverage

The preparation boundary is mandatory for:

- normal squad execution;
- manual phase execution;
- resumed phase execution;
- provider-free deterministic executors;
- mixed provider/controller governance nodes;
- valid `BLOCKED` results;
- controller policy routing on exhaustion.

Node skipping never fabricates required controller state. Workflow validation
forbids the existing successful-skip action on contract-bearing nodes.

## Testing Strategy

### Registry and graph tests

- Strict loader rejects duplicate keys.
- Registry version and path are validated.
- Every schema passes Draft 2020-12 self-validation.
- Unknown, missing, or remote references fail.
- All seven migrated nodes resolve the correct contract.
- Shared nodes resolve the same compiled object and digest.
- Controller keys are derived solely from schema properties.
- Legacy `controller_state_updates` is rejected.

### Normalization tests

- Every supported conversion is covered.
- Normalization is idempotent.
- Original result objects remain unchanged.
- Cycles, depth overflow, node-count overflow, and oversized collections fail.
- Strings are not coerced to booleans, integers, or enum values.
- Sets, bytes paths, dataclasses, and non-string mapping keys fail.

### Contract mutation matrix

For every controller field:

- valid boundary value passes;
- wrong type fails;
- missing required value fails;
- unknown field fails;
- invalid enum fails;
- negative count fails where applicable.

Each discriminator outcome receives explicit cross-field invariant tests.
Examples include action/pass disagreement, spec evaluation/pass disagreement,
missing block reason, and completed Understanding evidence without scores.

### Pipeline tests

Injected malformed controller output proves that:

- controller policy cannot persist state;
- `_evaluate_transitions()` is not called;
- product-input updates are not applied;
- state phase and completion history remain unchanged;
- successful timing transition is not applied;
- checkpointing is not called;
- a deterministic structured error is persisted.

Equivalent tests cover normal, manual, resumed, deterministic, mixed
governance, and `BLOCKED` paths.

### State-store tests

- Advance either commits the full new state or changes none of the
  success-state fields.
- An invalid receipt raises instead of returning normally.
- The controller's subsequent blocked diagnostic is distinct from a successful
  advance.
- A failed advance cannot be followed by a successful checkpoint.

### Regression tests

Existing workflow, Lexicon, Understanding, governance, routing, recovery,
manual-phase, state-store, telemetry, and checkpoint suites must retain their
valid-path behavior.

The complete repository test suite must pass before release.

## Rollout

The change lands atomically:

1. add the registry and direct `jsonschema` dependency;
2. add strict registry loading and compilation;
3. add lossless normalization and prepared-result validation;
4. make state advance transactional;
5. migrate all five contracts and seven phases;
6. move controller mutation out of transition evaluation;
7. remove `controller_state_updates` and its parser;
8. update tests and documentation;
9. run the complete test suite;
10. release as one version.

There is no compatibility switch, shadow path, fallback list, or mixed schema
mode. Installed extensions must update the workflow definition, registry, and
harness together as one release.

## Acceptance Criteria

The design is complete when:

1. Every current controller-producing phase references one named contract.
2. Shared phase types reuse the same contract definition.
3. No controller field list or field schema is duplicated in a workflow node
   or runtime/phase Markdown.
4. Provider/controller ownership overlap is impossible at startup and runtime.
5. Only explicitly lossless normalization occurs.
6. Scalar and cross-field routing invariants are validated before routing.
7. Raw results cannot reach transition evaluation or state advancement.
8. Invalid controller state cannot advance, complete, or checkpoint a phase.
9. State advancement is all-or-error.
10. Failure diagnostics are stable, structured, and value-redacted.
11. Valid existing workflow behavior remains unchanged.
12. No compatibility or fallback path remains after migration.
