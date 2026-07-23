# Explicit Governance Structural Nodes Design

**Date:** 2026-07-23  
**Status:** Approved for implementation planning  
**Scope:** Replace the hidden governance structural-validation hook with two
visible, provider-free workflow nodes.

## Goal

Make structural certification of `feasibility.md` and
`intent-alignment-check.md` visible, deterministic, independently checkpointed,
and resumable without changing structural validation rules, templates, report
schemas, repair owners, provider verdicts, or public governance configuration.

## Non-Goals

This design does not:

- split GATEKEEPER, TRACKER, or any other provider role;
- change feasibility or intent-alignment authoring prompts;
- change `lexicon.structural.structural_validate`;
- change structural templates, required sections, cross-reference rules, or
  verdict enums;
- change `governance.*` configuration names or defaults;
- rename existing persisted structural state fields;
- introduce a general-purpose gate framework;
- change COMMANDER judgment fallback behavior;
- split consensus or specialist orchestration;
- add estimate-consistency validation;
- change checkpoint infrastructure or general rerun semantics;
- add shadow or dual execution.

## Existing Behavior

Structural certification currently runs inside
`SquadController._evaluate_transitions()` through
`_enforce_governance_structural_gate_result()` after two provider phases:

1. `phase2-decide`, where GATEKEEPER authors `feasibility.md`; and
2. `phase2-tracker-alignment`, where TRACKER authors
   `intent-alignment-check.md`.

The controller:

- resolves `governance.artifacts.<artifact>`;
- treats a structural gate as active only when `governance.enabled` is true and
  the artifact tier is `structural`;
- validates the authored artifact against its configured template;
- loads configured cross-reference artifacts;
- invokes `lexicon.structural.structural_validate`;
- writes a JSON findings report;
- writes controller-owned pass, attempt, finding-count, and report state;
- re-dispatches the authoring phase while repair budget remains;
- warns or blocks when governance or workflow iteration budgets are exhausted.

Because certification occurs during transition evaluation, it has no separate
phase identity, checkpoint, telemetry span, resume point, or manual phase
surface.

## Design Principles

1. Follow the explicit spec-Lexicon and tasks-Lexicon node patterns.
2. Keep provider agents responsible for authoring and deterministic nodes
   responsible for certification.
3. Preserve one authoritative structural-validation path.
4. Reuse existing validation semantics rather than redesigning them.
5. Move both structural gates together so no mixed hidden/visible governance
   architecture remains.
6. Treat missing or structurally invalid authored artifacts as repairable.
7. Treat invalid controller context or failed evidence persistence as blockers.
8. Preserve provider verdicts across certification so downstream routing remains
   behaviorally equivalent.

## Workflow Architecture

### Feasibility certification

```text
phase2-decide
    |
    v
phase2-feasibility-structural
    |-- repair ----------------------> phase2-decide
    |-- block -----------------------> terminal-blocked
    |-- provider verdict KILL -------> done
    |-- provider verdict DEFER ------> phase1-what or escalate
    `-- provider verdict PASS -------> phase2-strategic-overview
```

### Intent-alignment certification

```text
phase2-tracker-alignment
    |
    v
phase2-intent-alignment-structural
    |-- repair ----------------------> phase2-tracker-alignment
    |-- block -----------------------> terminal-blocked
    |-- ALIGNED / DRIFT / DRIFTING --> phase3-specialists
    `-- STOP_AND_ASK / ESCALATE -----> phase2-tracker-alignment
```

The deterministic nodes run only after their provider phase returns a valid,
non-blocking executor result. Provider execution failures and typed human
escalations continue to stop before transition evaluation as they do today.

## Persisting Provider Routing Results

The existing hidden hook evaluates structural findings and provider verdicts in
one call. Once certification becomes a separate node, downstream transitions
must not depend on the deterministic node's generic executor verdict.

The authoring phases therefore persist their routing verdict under
controller-validated, phase-specific state:

```yaml
feasibility_verdict: PASS | KILL | DEFER
intent_alignment_verdict: ALIGNED | DRIFT | DRIFTING | STOP_AND_ASK | ESCALATE
```

The provider still returns its existing top-level verdict. During successful
advancement from the provider phase to its structural node, the controller
copies the validated verdict into the corresponding routing field. The
structural node reads that field after certification.

This is a narrow controller-owned projection, not a new provider state-update
permission. Agents must not emit either field themselves.

The fields are recalculated on every successful authoring dispatch. A repair
dispatch therefore replaces the prior routing verdict before certification
runs again.

## Node Definitions

Both nodes use a new explicit executor type:

```yaml
type: deterministic_structural
```

Using a distinct type keeps Lexicon and governance semantics separate while
allowing both structural artifacts to share one focused executor and service.

### Feasibility node

```yaml
- id: phase2-feasibility-structural
  label: "Deterministic Feasibility Structural Gate"
  type: deterministic_structural
  structural_artifact: feasibility
  allowed_state_updates: []
  controller_state_updates:
    - structural_action
    - feasibility_structural_pass
    - feasibility_structural_attempts
    - feasibility_structural_findings
    - feasibility_structural_report
    - governance_gate_exhausted
    - blocked_reason
  state_update_types:
    structural_action: string
    feasibility_structural_pass: boolean
    feasibility_structural_attempts: integer
    feasibility_structural_findings: integer
    feasibility_structural_report: string
    governance_gate_exhausted: string
    blocked_reason: string
  state_update_enums:
    structural_action: [proceed, repair, proceed_with_warning, block]
    governance_gate_exhausted: [feasibility]
  transitions:
    - to: phase2-decide
      condition: "structural_action = repair"
      action: increment_iteration
    - to: terminal-blocked
      condition: "structural_action = block"
    - to: phase2-strategic-overview
      condition: "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = PASS"
    - to: done
      condition: "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = KILL"
      action: write_kill_report
    - to: phase1-what
      condition: "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = DEFER AND defer_count < assess_defer_loop_limit"
      action: increment_defer_count
    - to: escalate
      condition: "structural_action in [proceed, proceed_with_warning] AND feasibility_verdict = DEFER AND defer_count >= assess_defer_loop_limit"
```

### Intent-alignment node

```yaml
- id: phase2-intent-alignment-structural
  label: "Deterministic Intent Alignment Structural Gate"
  type: deterministic_structural
  structural_artifact: intent-alignment-check
  allowed_state_updates: []
  controller_state_updates:
    - structural_action
    - intent_alignment_check_structural_pass
    - intent_alignment_check_structural_attempts
    - intent_alignment_check_structural_findings
    - intent_alignment_check_structural_report
    - governance_gate_exhausted
    - blocked_reason
  state_update_types:
    structural_action: string
    intent_alignment_check_structural_pass: boolean
    intent_alignment_check_structural_attempts: integer
    intent_alignment_check_structural_findings: integer
    intent_alignment_check_structural_report: string
    governance_gate_exhausted: string
    blocked_reason: string
  state_update_enums:
    structural_action: [proceed, repair, proceed_with_warning, block]
    governance_gate_exhausted: [intent-alignment-check]
  transitions:
    - to: phase2-tracker-alignment
      condition: "structural_action = repair"
      action: increment_iteration
    - to: terminal-blocked
      condition: "structural_action = block"
    - to: phase3-specialists
      condition: "structural_action in [proceed, proceed_with_warning] AND intent_alignment_verdict in [ALIGNED, DRIFT, DRIFTING]"
    - to: phase2-tracker-alignment
      condition: "structural_action in [proceed, proceed_with_warning] AND intent_alignment_verdict in [STOP_AND_ASK, ESCALATE]"
```

`phase2-decide` changes to one successful forward transition:

```yaml
transitions:
  - to: phase2-feasibility-structural
    condition: always
```

`phase2-tracker-alignment` changes to one successful forward transition:

```yaml
transitions:
  - to: phase2-intent-alignment-structural
    condition: always
```

The controller preserves existing early handling for a provider result that
sets typed blocked/escalation state. Such a result does not advance to the
structural node.

## Phase Graph Contract

Extend `PhaseNode` with:

```python
structural_artifact: str | None
```

Workflow validation requires:

- `type: deterministic_structural` has a non-empty `structural_artifact`;
- the artifact key exists under the bundled governance artifact contract;
- the node has no provider agent or provider-owned state updates;
- every controller-owned state key has a declared type;
- `structural_action` has the complete four-value enum;
- the node has explicit repair, block, and forward transitions;
- unknown executor types remain invalid.

The runtime registers `deterministic_structural` explicitly. An unknown node
type must not fall back to COMMANDER as part of this package.

## Structural Gate Service

Create:

```text
src/harness/governance_structural_gate.py
```

The service exposes:

```python
StructuralAction = Literal[
    "proceed",
    "repair",
    "proceed_with_warning",
    "block",
]

@dataclass(frozen=True)
class GovernanceStructuralGateResult:
    artifact_key: str
    action: StructuralAction
    passed: bool
    attempts: int
    findings: int
    report_path: Path | None
    exhausted_artifact: str | None
    blocked_reason: str | None
    detail: str

    def state_updates(self) -> dict[str, object]:
        ...

def run_governance_structural_gate(
    *,
    artifact_key: str,
    spec_dir: Path | None,
    extension_root: Path,
    governance_config: Mapping[str, object],
    previous_attempts: object,
    iteration: object,
    max_iterations: object,
) -> GovernanceStructuralGateResult:
    ...
```

The service owns:

- configuration lookup and validation;
- enabled/disabled behavior;
- artifact and cross-reference path resolution;
- template resolution;
- invocation of `structural_validate`;
- report construction;
- atomic report persistence;
- attempt calculation;
- exhaustion policy;
- controller state projection.

The service does not:

- invoke a provider;
- mutate squad state directly;
- choose the next phase;
- interpret GATEKEEPER or TRACKER verdicts;
- write checkpoints or telemetry;
- modify authored artifacts.

## Artifact Contract

The existing configuration remains authoritative:

```yaml
governance:
  enabled: true
  max_repair_attempts: 3
  on_exhausted: warn
  artifacts:
    feasibility:
      tier: structural
      template: feasibility-template.md
      verdict:
        section: "Kill / Defer / Pass Decision"
        enum: [PASS, KILL, DEFER]
    intent-alignment-check:
      tier: structural
      template: intent-alignment-check-template.md
      verdict:
        section: "Alignment Verdict"
        enum: [ALIGNED, DRIFT]
      cross_refs:
        - ids: "REQ|FR|NFR"
          against: spec.md
```

The service uses the existing output field names:

| Artifact | File | Report | State prefix |
|---|---|---|---|
| `feasibility` | `feasibility.md` | Existing configured/default structural report | `feasibility_structural_*` |
| `intent-alignment-check` | `intent-alignment-check.md` | Existing configured/default structural report | `intent_alignment_check_structural_*` |

Report schema remains version 1:

```json
{
  "schema_version": 1,
  "artifact": "feasibility",
  "path": "/absolute/spec/path/feasibility.md",
  "ok": false,
  "findings": [
    {
      "code": "missing-structural-artifact",
      "message": "required governance artifact is missing: feasibility.md",
      "artifact": "feasibility.md"
    }
  ]
}
```

Writes use the repository's atomic JSON helper. A report write failure blocks
without incrementing the repair counter because the next provider attempt would
not repair controller evidence persistence.

## Outcome Semantics

| Condition | Action | Pass | Attempts | Routing |
|---|---|---:|---:|---|
| Governance globally disabled | `proceed` | `true` | `0` | Provider-verdict route |
| Artifact absent from config | `proceed` | `true` | `0` | Provider-verdict route |
| Artifact tier is not structural | `proceed` | `true` | `0` | Provider-verdict route |
| Validation passes | `proceed` | `true` | `0` | Provider-verdict route |
| Validation fails with budget remaining | `repair` | `false` | Previous + 1 | Authoring phase |
| Validation fails, exhausted, warn policy | `proceed_with_warning` | `false` | Final value | Provider-verdict route |
| Validation fails, exhausted, block policy | `block` | `false` | Final value | `terminal-blocked` |
| `spec_dir` missing or invalid | `block` | `false` | Preserved | `terminal-blocked` |
| Governance configuration malformed | `block` | `false` | Preserved | `terminal-blocked` |
| Report cannot be written atomically | `block` | `false` | Preserved | `terminal-blocked` |

Exhaustion occurs when either:

- `governance.max_repair_attempts` is reached; or
- the run's `iteration` reaches `max_iterations`.

When exhausted, `governance_gate_exhausted` records the artifact key for both
warn and block policies, preserving current operator evidence.

## Executor Integration

Add `DeterministicStructuralExecutor` to `squad_executors.py`.

It:

1. loads state;
2. resolves the run-local spec directory;
3. resolves governance configuration through the existing config cascade;
4. invokes `run_governance_structural_gate`;
5. converts service output into a controller-owned `SquadAgentResult`;
6. performs no provider dispatch.

The executor returns a stable generic verdict:

- `PASS` for `proceed`;
- `WARN` for `proceed_with_warning`;
- `REPAIR` for `repair`;
- `BLOCKED` for `block`.

Routing uses `structural_action`, not these generic verdicts.

## State Ownership

Provider phases stop declaring structural certification state:

- remove `feasibility_structural_*` and `governance_gate_exhausted` controller
  ownership from `phase2-decide`;
- remove `intent_alignment_check_structural_*` and
  `governance_gate_exhausted` controller ownership from
  `phase2-tracker-alignment`.

The two deterministic nodes exclusively own those fields.

The controller exclusively owns:

- `feasibility_verdict`;
- `intent_alignment_verdict`.

Provider prompts continue to prohibit reporting structural certification
fields. They do not need to mention the projected routing fields.

## Repair Context

The existing next-dispatch repair context remains:

- a failed feasibility gate injects the feasibility report into the next
  GATEKEEPER dispatch;
- a failed intent-alignment gate injects the alignment report into the next
  TRACKER dispatch;
- agents repair authored files only;
- agents do not run the structural validator or report certification state.

The prompt renderer reads the same persisted pass/report fields, so only wording
that names the visible gate node needs updating.

## Recovery and Compatibility

### Runs at provider phases

They execute the provider, persist its routing verdict, and advance through the
new deterministic node.

### Runs already at downstream phases

They continue without forced rewind. The new nodes do not retroactively
invalidate completed runs.

### Runs blocked on the old provider phase

They resume the provider phase under existing recovery rules. After successful
repair they proceed through the new node.

### Runs whose provider phase completed but whose old hidden gate did not

Existing state may have `last_dispatch.post_dispatch_complete: false` or may
remain on the provider phase. Existing dispatch recovery remains authoritative.
The migration must not infer provider success solely from a structural report.

### Runs manually placed on a new node

`echelon phase run` and normal resume execute the provider-free node without an
LLM call. Missing authoring context produces a typed block or repair outcome
according to the service contract.

No persisted-state migration is required. Existing structural state fields are
reused; the routing-verdict fields are additive.

## Checkpoint and Telemetry

Both structural nodes use ordinary successful-phase checkpoint behavior.

- A passing or warning certification is checkpointed before advancing.
- A repair outcome is checkpointed with its report before returning to the
  authoring phase.
- A blocking outcome persists state and report evidence before stopping.
- Telemetry records the node as `deterministic_structural`, with no provider
  token usage.

Checkpoint coverage tests must prove that the structural report exists in the
checkpoint commit for repair and passing paths.

## Failure Handling

| Failure | Behavior |
|---|---|
| Missing authored artifact | Report finding and repair |
| Missing configured cross-reference | Report finding and repair |
| Structural validator exception | Report finding and repair while budget remains |
| Invalid `spec_dir` | Block with typed reason |
| Invalid governance configuration | Block with typed reason |
| Evidence write failure | Block without provider redispatch |
| Missing projected provider verdict after pass | Block as a state-contract failure |
| Unknown structural artifact key | Block before validation |
| Repair budget exhausted under `warn` | Continue with explicit debt |
| Repair budget exhausted under `block` | Stop at `terminal-blocked` |

The controller must not dispatch COMMANDER to resolve any of these failures.

## Test Strategy

### Service tests

Add focused tests for:

- disabled governance;
- missing/non-structural artifact configuration;
- valid feasibility artifact;
- invalid feasibility artifact;
- valid intent-alignment artifact with cross-references;
- missing cross-reference;
- validator exception;
- existing attempt normalization;
- governance repair exhaustion;
- workflow iteration exhaustion;
- warn and block policies;
- invalid spec directory;
- invalid configuration;
- atomic report failure;
- exact state-update projection.

### Graph and contract tests

Verify:

- both provider phases have one forward edge to their structural node;
- both structural nodes are provider-free;
- provider phases no longer own structural certification state;
- every structural state field is controller-owned and typed;
- projected provider verdict fields are controller-only;
- all forward routes are gated by
  `structural_action in [proceed, proceed_with_warning]`;
- the workflow validator rejects malformed structural nodes;
- unknown executor types fail validation rather than invoking COMMANDER.

### Controller integration tests

Cover:

- feasibility pass;
- feasibility repair and redispatch;
- feasibility KILL after certification;
- feasibility DEFER routing and defer exhaustion;
- intent alignment pass;
- intent alignment repair and redispatch;
- STOP_AND_ASK/ESCALATE behavior after certification;
- disabled-gate bypass;
- warning exhaustion;
- blocking exhaustion;
- provider verdict projection replacement after repair;
- missing projected verdict blocking;
- resume directly at each deterministic node;
- no provider call during deterministic-node execution;
- structural report in phase checkpoint commits.

### Regression tests

Retain or adapt all existing governance structural tests. Add source assertions
that:

- `_enforce_governance_structural_gate_result` is absent from
  `SquadController`;
- `_validate_governance_structural_artifact` is absent from
  `SquadController`;
- `_governance_gate_must_stop_on_exhaustion` is absent from
  `SquadController`;
- `_evaluate_transitions()` does not invoke structural validation;
- no provider prompt permits structural certification writes.

## Rollout and Rollback

This is a single authoritative-path migration, matching the Tasks Lexicon
package.

Rollout:

1. extract the service with characterization tests;
2. add the deterministic executor;
3. add graph nodes and provider-verdict projection;
4. add recovery, checkpoint, and manual-phase tests;
5. remove the hidden controller hook;
6. update phase/prompt documentation;
7. run focused and full verification;
8. reinstall the development extension for live validation;
9. run one representative Phase A flow with governance enabled.

Rollback is one coherent revert restoring:

- provider-phase transitions;
- hidden structural hook;
- prior controller-owned state declarations.

No configuration or persisted-state rollback is required because existing field
names and report schemas remain compatible.

## Acceptance Criteria

- `feasibility.md` and `intent-alignment-check.md` are certified only by visible
  provider-free nodes.
- The hidden structural hook and its phase table are removed.
- Structural rules, templates, report schemas, repair budgets, and exhaustion
  policies are behaviorally unchanged.
- GATEKEEPER and TRACKER remain the sole authored-artifact repair owners.
- Provider verdict routing remains equivalent after successful certification.
- Both nodes are independently visible, checkpointed, resumable, and manually
  executable.
- Deterministic-node execution makes no provider call.
- Invalid controller context and evidence-write failures block without paying
  for another provider dispatch.
- Existing runs require no state migration.
- Focused graph, service, controller, checkpoint, prompt-contract, and full
  repository test suites pass.
