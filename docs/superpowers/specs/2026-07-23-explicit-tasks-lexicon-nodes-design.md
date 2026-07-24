# Explicit Tasks Lexicon Nodes Design

**Date:** 2026-07-23  
**Status:** Approved for implementation planning  
**Scope:** Replace the hidden tasks-Lexicon post-dispatch hook with two visible,
provider-free workflow nodes.

## Goal

Make tasks-Lexicon certification visible, deterministic, independently
checkpointed, and resumable without changing the tasks grammar, configured
thresholds, report schema, repair owner, consensus agents, or public
configuration.

## Non-Goals

This design does not:

- introduce a compatibility or shadow-execution mode;
- create a generic gate framework;
- split `phase3-consensus`;
- split ORCHESTRATOR or any other agent role;
- change tasks-Lexicon grammar or validation findings;
- change the tasks-Lexicon report schema;
- rename existing persisted tasks-Lexicon state fields;
- change Lexicon configuration keys or defaults;
- change the checkpoint subsystem;
- extract other structural or quality gates;
- implement general phase rerun semantics.

## Existing Behavior

Tasks certification currently runs as a hidden hook in
`SquadController._evaluate_transitions()` after:

1. `phase3-plan`, where ORCHESTRATOR creates or repairs `tasks.md`; and
2. `phase3-consensus`, where PLAN2 may revise `tasks.md`.

`SquadController._enforce_tasks_lexicon_gate_result()` validates:

- `tasks.md` against the TASKS grammar;
- the configured specification reference;
- the configured glossary;
- required planning artifacts:
  - `critical-path.md`;
  - `risk-matrix.md`;
  - `dependencies.md`;
- task-to-target ownership.

The hook writes `tasks-lexicon-report.json`, updates controller-owned state,
calculates repair attempts, and influences transition selection. Because this
work happens inside transition evaluation, it is not a separately visible,
resumable, or checkpointed workflow step.

## Design Principles

1. Follow the existing `phase1-lexicon` pattern.
2. Keep provider agents responsible for authoring and deterministic nodes
   responsible for certification.
3. Use the existing workflow executor, state advancement, checkpoint, telemetry,
   and manual-phase mechanisms.
4. Preserve one authoritative execution path.
5. Remove the hidden implementation in the same change that introduces the
   visible nodes.
6. Treat missing authored artifacts as repairable findings.
7. Treat missing controller context or failed evidence persistence as execution
   blockers, because another provider dispatch cannot repair them.

## Workflow Architecture

### Initial planning certification

```text
phase3-plan
    |
    v
phase3-tasks-lexicon
    |-- repair ----------------------> phase3-plan
    |-- block -----------------------> terminal-blocked
    `-- proceed / proceed-with-warning
                                      |
                                      v
                             phase3-understanding
```

### Post-PLAN2 certification

```text
phase3-consensus
    |
    v
phase3-consensus-tasks-lexicon
    |-- repair ----------------------> phase3-plan
    |-- block -----------------------> terminal-blocked
    `-- proceed / proceed-with-warning
                                      |
                                      v
                         existing consensus routing:
                           WHY3 failure -> phase1-what
                           ASSESS2 rejection -> phase3-how
                           pass/risk acceptance -> checkpoint-plan
                           iteration exhaustion -> existing warning path
```

The second certification remains necessary because PLAN2 may revise
`tasks.md`. The two nodes have distinct IDs so their return destinations,
history, telemetry, checkpoints, and recovery state do not depend on a dynamic
caller or return-target field.

## Node Definitions

Both nodes use the existing executor type:

```yaml
type: deterministic_lexicon
lexicon_artifact: tasks
allowed_state_updates: []
controller_state_updates:
  - tasks_lexicon_action
  - tasks_lexicon_pass
  - tasks_lexicon_attempts
  - tasks_lexicon_findings
  - tasks_lexicon_report
  - blocked_reason
```

The exact workflow definitions are conceptually:

```yaml
- id: phase3-tasks-lexicon
  label: "Deterministic Tasks Lexicon Gate"
  type: deterministic_lexicon
  lexicon_artifact: tasks
  allowed_state_updates: []
  controller_state_updates:
    - tasks_lexicon_action
    - tasks_lexicon_pass
    - tasks_lexicon_attempts
    - tasks_lexicon_findings
    - tasks_lexicon_report
    - blocked_reason
  state_update_types:
    tasks_lexicon_action: string
    tasks_lexicon_pass: boolean
    tasks_lexicon_attempts: integer
    tasks_lexicon_findings: integer
    tasks_lexicon_report: string
    blocked_reason: string
  state_update_enums:
    tasks_lexicon_action:
      - proceed
      - repair
      - proceed_with_warning
      - block
  transitions:
    - to: phase3-plan
      condition: "tasks_lexicon_action = repair"
      action: increment_iteration
    - to: terminal-blocked
      condition: "tasks_lexicon_action = block"
    - to: phase3-understanding
      condition: "tasks_lexicon_action in [proceed, proceed_with_warning]"
```

```yaml
- id: phase3-consensus-tasks-lexicon
  label: "Deterministic Post-Consensus Tasks Lexicon Gate"
  type: deterministic_lexicon
  lexicon_artifact: tasks
  allowed_state_updates: []
  controller_state_updates:
    - tasks_lexicon_action
    - tasks_lexicon_pass
    - tasks_lexicon_attempts
    - tasks_lexicon_findings
    - tasks_lexicon_report
    - blocked_reason
  state_update_types:
    tasks_lexicon_action: string
    tasks_lexicon_pass: boolean
    tasks_lexicon_attempts: integer
    tasks_lexicon_findings: integer
    tasks_lexicon_report: string
    blocked_reason: string
  state_update_enums:
    tasks_lexicon_action:
      - proceed
      - repair
      - proceed_with_warning
      - block
  transitions:
    - to: phase3-plan
      condition: "tasks_lexicon_action = repair"
      action: increment_iteration
    - to: terminal-blocked
      condition: "tasks_lexicon_action = block"
    - to: phase1-what
      condition: "quality_gates.fail AND iteration < max_iterations"
      action: increment_iteration
    - to: phase1-what
      condition: "why3-verdict = FAIL AND iteration < max_iterations"
      action: increment_iteration
    - to: checkpoint-plan
      condition: "why3-verdict = PASS AND assess2-verdict = PASS"
    - to: checkpoint-plan
      condition: "gate_decision = accept_with_risk OR phase_recommendation = advance_past_consensus_to_delivery"
    - to: phase3-how
      condition: "assess2-verdict = REJECTED AND iteration < max_iterations"
      action: increment_iteration
    - to: checkpoint-plan
      condition: "iteration >= max_iterations"
      action: force_convergence_warning
```

The implementation must ensure the consensus conditions are evaluated only
when `tasks_lexicon_action` is `proceed` or `proceed_with_warning`. This can be
expressed by prefixing those conditions with the action predicate or by using a
small deterministic transition grouping already supported by the workflow
model. It must not rely on transition fall-through after an unknown value.

`phase3-plan` changes to one successful forward transition:

```yaml
transitions:
  - to: phase3-tasks-lexicon
    condition: always
```

`phase3-consensus` changes to one successful forward transition:

```yaml
transitions:
  - to: phase3-consensus-tasks-lexicon
    condition: always
```

Provider failures and blocked consensus prerequisites are handled before
transition evaluation as they are today, so the post-consensus gate is reached
only after successful consensus execution.

## State Contract

The deterministic tasks nodes own:

```yaml
tasks_lexicon_action: proceed | repair | proceed_with_warning | block
tasks_lexicon_pass: true | false
tasks_lexicon_attempts: <integer>
tasks_lexicon_findings: <integer>
tasks_lexicon_report: <path>
```

`blocked_reason` is emitted only for `block`.

Existing persisted fields remain valid. `tasks_lexicon_action` is additive and
is recalculated whenever either new node executes. Runs already beyond a new
node do not require it.

Provider-owned contracts change as follows:

- Remove `tasks_lexicon_attempts` from `phase3-plan.allowed_state_updates`.
- Remove `tasks_lexicon_attempts` from PLAN2's per-agent
  `allowed_state_updates`.
- Remove all `tasks_lexicon_*` controller state declarations from
  `phase3-plan` and `phase3-consensus`.
- Keep provider ownership of authored planning artifacts unchanged.

Agents never report certification state or repair counters.

## Outcome Semantics

| Condition | Action | Pass | Attempts | Routing |
|---|---|---:|---:|---|
| Global Lexicon gate disabled | `proceed` | `true` | `0` | Forward |
| Tasks sub-gate disabled | `proceed` | `true` | `0` | Forward |
| Validation passes | `proceed` | `true` | `0` | Forward |
| Validation fails with budget remaining | `repair` | `false` | Previous + 1 | `phase3-plan` |
| Validation fails, exhausted, warn policy | `proceed_with_warning` | `false` | Final value | Forward |
| Validation fails, exhausted, block policy | `block` | `false` | Final value | `terminal-blocked` |
| `spec_dir` missing or invalid | `block` | `false` | Preserved | `terminal-blocked` |
| Report cannot be written atomically | `block` | `false` | Preserved | `terminal-blocked` |

The service evaluates both:

- `lexicon_gate.max_repair_attempts`; and
- the run's `iteration` / `max_iterations` cap.

A failure is exhausted when either applicable cap is reached. Configuration
semantics remain the same as the current hidden gate.

## Tasks Lexicon Service

Create:

```text
src/harness/tasks_lexicon_gate.py
```

The module contains:

```python
@dataclass(frozen=True)
class TasksLexiconGateResult:
    action: Literal[
        "proceed",
        "repair",
        "proceed_with_warning",
        "block",
    ]
    passed: bool
    attempts: int
    findings: int
    report_path: Path | None
    blocked_reason: str | None
    detail: str

    def state_updates(self) -> dict[str, object]:
        ...


def run_tasks_lexicon_gate(
    *,
    project_root: Path,
    spec_dir_ref: str,
    config: Mapping[str, object],
    previous_attempts: object,
    workflow_iteration: object,
    max_workflow_iterations: object,
) -> TasksLexiconGateResult:
    ...
```

The service:

1. Reads the resolved `lexicon_gate` and tasks artifact configuration.
2. Returns a passing bypass when the global or tasks gate is disabled.
3. Resolves `spec_dir`.
4. Validates required planning outputs.
5. Validates TASKS grammar against the configured spec reference and glossary.
6. Validates target ownership.
7. Builds the existing schema-version-1 report.
8. Writes the report atomically.
9. Calculates pass, attempt, exhaustion, and action.
10. Returns a complete immutable result.

The service does not:

- read or write squad state;
- choose a workflow phase;
- invoke a provider;
- write journal entries;
- create checkpoints;
- mutate authored artifacts.

### Report compatibility

The existing report shape remains:

```json
{
  "schema_version": 1,
  "ok": true,
  "tasks": "tasks.md",
  "spec_ref": "requirements.lexicon.md",
  "findings": []
}
```

Existing finding codes remain unchanged, including:

- `missing-plan-output`;
- `missing-spec-ref`;
- TASKS validator finding codes;
- `tasks-validator-error`;
- `undeclared-target`;
- `unused-declared-target`;
- `task-without-target`;
- `cross-target-task`;
- `target-file-mismatch`;
- `task-target-validator-error`.

### Atomic report writing

The implementation follows `spec_lexicon_gate.py`'s existing atomic JSON write
pattern: write and `fsync` a temporary file in the destination directory, then
replace the report path.

The smallest safe reuse is to make that helper a public Lexicon-report helper
used by both spec and tasks services, or to place it in a narrowly named shared
module. Do not introduce a general persistence abstraction.

## Executor Integration

Extend `DeterministicLexiconExecutor.execute()`:

```python
artifact = str(node.lexicon_artifact or "")
if artifact == "spec":
    gate = run_spec_lexicon_gate(...)
elif artifact == "tasks":
    gate = run_tasks_lexicon_gate(...)
else:
    return blocked_unsupported_artifact_result(...)
```

Both branches:

- load resolved configuration through `get_full_resolved_config()`;
- receive state only as input values;
- return `SquadAgentResult` with controller-owned updates;
- print a concise provider-free phase result;
- never invoke `SquadCliProvider`.

The tasks branch returns `verdict: DONE` for all graph-routable actions,
including `repair`, `proceed_with_warning`, and `block`. A `block` action uses a
normal transition to `terminal-blocked`, allowing state advancement and
checkpoint creation. Executor-level `BLOCKED` remains reserved for a malformed
node contract such as an unsupported `lexicon_artifact`.

## Checkpointing

No new checkpoint implementation is required.

`SquadController` already executes:

```text
execute node
→ evaluate transition
→ state_store.advance(...)
→ _checkpoint_successful_phase(phase, next_phase)
```

The checkpoint function has no phase allowlist. Therefore, the new nodes
automatically use the established Phase A checkpoint mechanism.

Expected checkpoints:

| Completed node | Example `next_phase` | Checkpoint contents |
|---|---|---|
| `phase3-plan` | `phase3-tasks-lexicon` | Authored planning artifacts before certification |
| `phase3-tasks-lexicon` | `phase3-understanding` | Passing report and certified state |
| `phase3-tasks-lexicon` | `phase3-plan` | Failed report before repair |
| `phase3-consensus` | `phase3-consensus-tasks-lexicon` | PLAN2 output before post-consensus certification |
| `phase3-consensus-tasks-lexicon` | `checkpoint-plan` | Passing post-PLAN2 report |
| `phase3-consensus-tasks-lexicon` | `phase3-plan` | Failed post-PLAN2 report before repair |
| Either tasks gate | `terminal-blocked` | Final failed report and exhausted state |

Repeated executions retain the existing ledger behavior: the latest checkpoint
for a phase ID replaces the prior checkpoint with that ID.

If the node cannot produce a valid state transition because controller context
is absent or evidence cannot be persisted, it blocks before advancement and no
checkpoint is created. An incomplete node is not checkpointed.

Checkpoint creation failure continues to use the existing fail-closed
`phase_checkpoint_failed: <phase>: <detail>` behavior.

## Iteration and Recovery

Add both tasks nodes to the same iterative-phase policy used by
`phase1-lexicon`. This allows the configured workflow iteration budget rather
than the generic non-iterative phase-dispatch cap.

Recovery behavior:

- An interrupted run at either tasks node resumes the exact provider-free node.
- A pre-change run at `phase3-plan` follows its new forward edge to the first
  gate after the provider completes.
- A pre-change run at `phase3-consensus` follows its new forward edge after the
  consensus executor completes.
- A run already at `phase3-understanding`, `checkpoint-plan`, or later remains
  valid and needs no migration.
- Existing `tasks_lexicon_*` fields are treated as prior evidence only; the
  visible node always recertifies the current files.
- Manual `echelon phase run <new-node-id>` uses the existing manual phase
  execution path and invokes no provider.

## Direct Removal

Delete the old hidden path in the same implementation:

- `SquadController._enforce_tasks_lexicon_gate_result()`;
- `SquadController._validate_tasks_gate_artifacts()`;
- `SquadController._mark_tasks_lexicon_uncertified()`;
- the tasks-only glossary helper if no longer used;
- the call to `_enforce_tasks_lexicon_gate_result()` from
  `_evaluate_transitions()`;
- `phase3-plan` and `phase3-consensus` entries in the implicit
  `_lexicon_gate_must_block_on_exhaustion()` table;
- old tasks-gate self-loop transitions on provider nodes;
- provider permission to write `tasks_lexicon_attempts`;
- prompt language saying certification occurs as a hidden post-dispatch hook.

Keep spec-Lexicon behavior unchanged.

## Error Handling

### Repairable authored failures

These produce a report and `tasks_lexicon_action: repair` while budget remains:

- missing or malformed tasks;
- missing planning artifacts;
- missing configured specification reference;
- grammar findings;
- target-ownership findings;
- content-triggered validator exceptions represented by existing error finding
  codes.

The next ORCHESTRATOR prompt receives the existing controller repair context
from `tasks_lexicon_report`.

### Execution blockers

These produce `tasks_lexicon_action: block` with a precise `blocked_reason`:

- missing or invalid `spec_dir`;
- report directory cannot be created;
- report cannot be written, flushed, or atomically replaced;
- invalid gate configuration that prevents resolving safe artifact paths.

The node must not retry an authoring agent for a controller/runtime failure.

### Hard exhaustion

For `on_exhausted: block`, the final failed report is persisted, state advances,
a checkpoint is created, and the graph transitions to `terminal-blocked`.

### Warning exhaustion

For `on_exhausted: warn`, the final failed report and attempt count are
preserved and `tasks_lexicon_action` becomes `proceed_with_warning`. Downstream
consensus routing continues exactly as before.

## Testing Strategy

### Service unit tests

Create focused tests for:

- global Lexicon disabled;
- tasks sub-gate disabled;
- valid tasks;
- invalid TASKS grammar;
- missing `tasks.md`;
- each missing required planning artifact;
- missing configured specification reference;
- invalid task target ownership;
- custom tasks, spec-reference, glossary, and report paths;
- tasks-validator exception;
- target-validator exception;
- failed-attempt increment;
- successful reset to zero;
- repair-cap exhaustion under `warn`;
- repair-cap exhaustion under `block`;
- workflow-iteration exhaustion;
- missing `spec_dir`;
- atomic report-write failure;
- report-schema and finding-code compatibility.

### Graph-contract tests

Tests prove:

- both nodes exist;
- both use `deterministic_lexicon`;
- both declare `lexicon_artifact: tasks`;
- both prohibit agent state updates;
- both exclusively declare the tasks certification fields;
- `phase3-plan` routes directly to the first gate;
- `phase3-consensus` routes directly to the second gate;
- repair, block, pass, warning, WHY3, ASSESS2, accepted-risk, and iteration-cap
  transitions preserve ordering;
- all new condition fields resolve deterministically;
- provider nodes cannot write `tasks_lexicon_*`.

### Executor tests

Tests prove:

- neither tasks node invokes a provider;
- the executor selects the correct service for `spec` and `tasks`;
- unsupported artifacts block clearly;
- controller-owned state is returned with the expected types;
- console output identifies the tasks gate;
- manual single-phase execution works.

### Controller integration tests

Cover:

```text
PLAN -> gate pass -> Understanding
PLAN -> gate repair -> PLAN
PLAN -> gate warn -> Understanding
PLAN -> gate block -> terminal-blocked

CONSENSUS -> gate pass -> checkpoint-plan
CONSENSUS -> gate repair -> PLAN
CONSENSUS -> gate pass + WHY3 fail -> WHAT
CONSENSUS -> gate pass + ASSESS2 reject -> HOW
CONSENSUS -> gate warn -> existing consensus decision
CONSENSUS -> gate block -> terminal-blocked
```

Every case asserts that COMMANDER judgment is not invoked.

### Checkpoint tests

Tests explicitly prove:

- `phase3-plan` checkpoint points to `phase3-tasks-lexicon`;
- first-gate pass checkpoint points to `phase3-understanding`;
- first-gate repair checkpoint points to `phase3-plan`;
- `phase3-consensus` checkpoint points to
  `phase3-consensus-tasks-lexicon`;
- second-gate pass checkpoint points to the chosen consensus destination;
- second-gate repair checkpoint points to `phase3-plan`;
- hard exhaustion checkpoint points to `terminal-blocked`;
- the report is included in the checkpoint commit;
- checkpoint failure blocks through existing behavior.

### Recovery tests

Tests prove:

- exact-node resume for both new nodes;
- pre-change state at `phase3-plan`;
- pre-change state at `phase3-consensus`;
- no migration for runs already beyond a new boundary;
- stale provider-reported certification cannot bypass recertification.

### Regression verification

Run:

```text
focused tasks-Lexicon service tests
phase graph and workflow validator tests
executor and squad-controller tests
checkpoint and recovery tests
existing spec-Lexicon tests
full pytest suite
legacy shell contract suite
scripts/bash/dry-run.sh
```

A real-Git fixture must confirm checkpoint commits and ledger entries. A
provider-backed representative Phase A run is recommended before release but is
not a dependency of deterministic test execution.

## Rollout

Ship as one atomic implementation:

1. Add characterization tests for the current tasks validation behavior.
2. Add the tasks service.
3. Extend the existing deterministic Lexicon executor.
4. Add both workflow nodes.
5. Move routing and state ownership.
6. Add checkpoint and recovery coverage.
7. Remove the hidden hook and provider-owned repair counter.
8. Update phase documentation.
9. Run focused, full, shell, dry-run, and real-Git verification.

There is no runtime switch and no parallel legacy path. Git revert of the
atomic implementation is the rollback mechanism.

## Acceptance Criteria

- Tasks certification appears as two visible workflow nodes.
- Neither node invokes an AI provider.
- Tasks are certified after initial planning and after PLAN2.
- Existing validation rules, finding codes, configuration, and report schema
  remain compatible.
- Provider agents cannot write tasks certification fields or repair counters.
- Routing is based on the typed controller-owned action.
- Repair, warning, block, and consensus precedence match existing behavior.
- Both new nodes use normal state advancement, telemetry, history, manual phase
  execution, and checkpoints.
- Checkpoint commits include the certification report.
- Interrupted runs resume at the exact tasks gate.
- No compatibility switch, duplicate execution path, or generic gate framework
  is introduced.
- The old hidden tasks-gate code is removed.
- Existing spec-Lexicon behavior remains unchanged.
- Focused tests, the full Python suite, legacy shell contracts, and dry-run pass.
