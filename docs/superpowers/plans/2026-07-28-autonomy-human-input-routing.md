# Autonomy Human-Input Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** Tasks 1-9 implemented and reviewed. Full-suite unrelated failures
are recorded in the Task 9 report.

**Goal:** Route every Phase A Squad request for human input through one typed controller boundary so Guided asks the human, Semi auto-applies only explicit low-risk recommendations, Banzai delegates project decisions to COMMANDER, and external prerequisites always remain human-owned.

**Architecture:** Compile a closed human-input policy registry from workflow declarations plus three controller safeguard declarations. Seal a schema-v2 `blocked_decision` and matching recovery instruction through the existing state CAS boundary before any automatic resolution. `SquadController` owns mode selection, COMMANDER validation, and all resolution handlers; the CLI only displays decisions or submits answers through that controller.

**Tech Stack:** Python 3.12, frozen dataclasses, PyYAML, pytest, existing `PhaseGraph`, `PreparedPhaseResult`, `PreparedRoutingDecision`, `SquadStateStore`, Phase A execution leases, and Echelon result contracts.

## Global Constraints

- Preserve `blocked_decision` and recovery-instruction schema v1 behavior for RE and legacy runs.
- New Squad decisions use schema v2 only; no generic state write may create or clear them.
- Provider output supplies question facts only. Classification, handler, producer identity, phase identity, and revision are controller-owned.
- `reason_code` is part of the exact policy key: `(source_kind, producer_id, reason_code)`.
- No wildcard policy, fallback classification, default gate approval, or Banzai-to-human fallback for project decisions.
- COMMANDER returns a decision only. It cannot write files, phase, status, counters, or recovery state.
- Use the existing `PhaseAExecutionLock` then `SpecRunExecutionLock`; add no lock, lease, or lock-order rank.
- Keep OCI/process containment, accounting, provider selection/protocol, workflow bundles, run lifecycle, publication/completion, Phase B, and RE lifecycle outside the diff.
- `src/echelon/cli_app.py` already contains unrelated worktree edits. Preserve them and make only the narrow command/help changes described here.
- Run each red-green command from the repository root:
  `/Users/michalbachorik/work/echelon_r/echelon`.

## Interface Map

### Human-input types

Create `src/harness/human_input.py` with these public values:

```python
HumanInputSourceKind = Literal[
    "provider_escalation",
    "human_gate",
    "controller_safeguard",
    "legacy_recovery",
]
HumanInputClassification = Literal[
    "operational",
    "material",
    "external_prerequisite",
]
HumanInputRisk = Literal["low", "medium", "high", "critical"]
SemiPolicy = Literal["require_human", "auto_if_recommended_low_risk"]


@dataclass(frozen=True)
class HumanInputOption:
    id: str
    label: str
    description: str
    recommended: bool
    risk_level: HumanInputRisk | None
    next_phase: str | None
    outcome: str | None


@dataclass(frozen=True)
class HumanInputPolicy:
    source_kind: HumanInputSourceKind
    producer_id: str
    reason_code: str
    classification: HumanInputClassification
    semi_policy: SemiPolicy
    resolution_handler: str
    allow_free_text: bool
    allowed_phase_ids: frozenset[str]
    allowed_target_phases: frozenset[str]
    context_state_keys: tuple[str, ...]
    context_paths: tuple[str, ...]
    options: tuple[HumanInputOption, ...]


@dataclass(frozen=True)
class PreparedHumanInput:
    schema_version: Literal[1]
    source_kind: HumanInputSourceKind
    producer_id: str
    phase_id: str
    reason_code: str
    classification: HumanInputClassification
    question: str
    options: tuple[HumanInputOption, ...]
    recommended_answer: str | None
    risk_level: HumanInputRisk | None
    resolution_handler: str
    source_state_revision: int


@dataclass(frozen=True)
class DecisionResolution:
    selected_option_id: str | None
    answer_text: str | None
    rationale: str
    confidence: Literal["high", "medium", "low"]


@dataclass(frozen=True)
class HumanInputResolution:
    selected_option_id: str | None
    answer_text: str | None
    resolved_by: Literal["user", "semi", "COMMANDER"]
```

`HumanInputPolicyRegistry.lookup(source_kind, producer_id, reason_code)` is an
exact lookup. `HumanInputPolicyRegistry.prepare(...)` creates the only valid
`PreparedHumanInput`. `select_initial_decision_status(mode, policy, request)`
returns only `pending` or `awaiting_human`.

### Compiled workflow policy

`PhaseNode.human_input_policies` is
`tuple[HumanInputPolicy, ...]`. `PhaseGraph.human_input_policy_registry()`
returns a registry containing all workflow policies and the closed safeguard
policies. Workflow `human_input` is always a list, including when it contains
one entry.

The initial closed context state-key allowlist is:

```python
{
    "user_message",
    "phase",
    "quality_scores",
    "iteration",
    "max_iterations",
    "why_fail_count",
    "why2_metric_stagnation_count",
    "phase_dispatch_limit_phase",
    "phase_dispatch_limit",
    "issue_resolution_ledger",
}
```

Context paths may start only with `{staging_dir}`, `{spec_dir}`,
`{context_dir}`, or `{squad_dir}` and must remain inside the resolved root.
Runtime context rendering is deterministic and capped at 32,768 UTF-8 bytes.

### Durable state

Add these `SquadStateStore` methods:

```python
def set_human_input_decision(
    self,
    request: PreparedHumanInput,
    *,
    initial_status: Literal["pending", "awaiting_human"],
) -> dict[str, Any]: ...

def claim_human_input_decision(
    self,
    decision_id: str,
    *,
    expected_state_revision: int,
) -> dict[str, Any]: ...

def recover_interrupted_human_input_decision(self) -> dict[str, Any]: ...

def record_human_input_resolution_failure(
    self,
    decision_id: str,
    *,
    expected_state_revision: int,
    failure_code: str,
) -> dict[str, Any]: ...

def apply_human_input_state_resolution(
    self,
    decision_id: str,
    *,
    expected_state_revision: int,
    resolution: HumanInputResolution,
    state_updates: Mapping[str, Any],
    state_removals: Iterable[str],
) -> dict[str, Any]: ...
```

Extend the existing provider transaction:

```python
def advance(
    self,
    from_phase: str,
    to_phase: str,
    decision: PreparedRoutingDecision,
    *,
    human_input: PreparedHumanInput | None = None,
    human_input_initial_status: Literal["pending", "awaiting_human"] | None = None,
) -> AdvanceReceipt: ...
```

Both `advance(...)` and `set_human_input_decision(...)` call one private
`_seal_human_input_decision_unlocked(...)`. The store derives
`autonomy_mode` from durable state, generates the decision id, checks the
source revision, and writes the v2 decision/instruction pair in one save.

### Controller boundary

Add these controller methods:

```python
def handle_human_input(
    self,
    request: PreparedHumanInput,
    *,
    provider_advance: _ProviderHumanInputAdvance | None = None,
) -> bool: ...

def resume_pending_human_input(self) -> bool: ...

def apply_human_input_resolution(
    self,
    decision_id: str,
    *,
    expected_state_revision: int,
    resolution: HumanInputResolution,
) -> bool: ...

def resume_with_human_input(self, answer: str) -> SquadResult: ...
```

`handle_human_input(...)` returns `True` only when the request was resolved and
the run may redispatch. It returns `False` for `awaiting_human`, failed
resolution, and gate rejection. `_ProviderHumanInputAdvance` contains
`from_phase`, `to_phase`, and the already attested `PreparedRoutingDecision`.
It is required for provider requests and for
`consecutive_why_fails`/`why2_metric_stagnation` requests discovered while
routing that provider result. It is forbidden for gates, legacy adaptation,
and the pre-dispatch `phase_dispatch_limit` safeguard.

`resume_with_human_input(...)` obtains the existing execution leases through
`_run_with_execution_lease`, validates the awaiting decision, calls
`apply_human_input_resolution(...)`, then resumes `_run_locked(...)`.

---

### Task 1: Compile the Closed Policy Registry

**Files:**
- Create: `src/harness/human_input.py`
- Modify: `src/harness/phase_graph.py`
- Modify: `src/harness/workflow_validator.py`
- Create: `tests/unit/test_human_input.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Produces: immutable option/policy/request types, exact triple-key registry,
  workflow policy compilation, context declaration validation.
- Consumes: workflow phase ids and transition targets only; no controller or
  state-store dependency.

- [ ] **Step 1: Write failing type and registry tests**

Cover a valid free-text provider policy, a valid gate policy, the two
`phase1-investigate` reason variants, duplicate exact keys, unknown lookups,
provider attempts to set policy-owned fields, duplicate option ids, multiple
recommendations, malformed risk, overlong question, and stale/negative source
revision.

Use literal assertions such as:

```python
policy = registry.lookup(
    "provider_escalation",
    "phase1-investigate",
    "investigation_access_required",
)
assert policy.classification == "external_prerequisite"
```

- [ ] **Step 2: Run the new unit test and verify import/behavior failures**

Run:
`python -m pytest tests/unit/test_human_input.py -q`

Expected: failure because `harness.human_input` and its types do not exist.

- [ ] **Step 3: Implement immutable validation and exact lookup**

Normalize strings once, reject bool-as-int revisions, enforce the 4,000
character question bound, and require option `next_phase`/`outcome` to match
the selected exact policy. Do not accept a missing lookup.

- [ ] **Step 4: Write failing graph and workflow validation tests**

Test that:

- `human_input` must be a list of mappings;
- each reason code is unique per producer;
- classifications, semi policies, handlers, keys, paths, targets, and options
  are closed;
- each gate option maps one-to-one to a declared transition outcome;
- `outcome` is accepted only on `human_gate` transitions, is unique within the
  gate, and matches `human_input_outcome = <value>` in that edge's condition;
- once a workflow contains any `human_input` declaration, every provider phase
  that allows `escalation_question` has at least one provider policy; this
  migration-aware gate keeps the unchanged production workflow valid until
  Task 7 adds the complete declaration set;
- the real workflow compiles.

- [ ] **Step 5: Compile policies into `PhaseNode` and add safeguard entries**

Declare exact safeguard policy records in `human_input.py` for
`phase_dispatch_limit`, `consecutive_why_fails`, and
`why2_metric_stagnation`. Enumerate allowed non-terminal source phases from
their current controller call sites; do not use `"*"` or all graph phases.

- [ ] **Step 6: Run focused policy and workflow tests**

Run:
`python -m pytest tests/unit/test_human_input.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py -q`

Expected: all pass.

- [ ] **Step 7: Commit the policy compiler**

Run:
`git add src/harness/human_input.py src/harness/phase_graph.py src/harness/workflow_validator.py tests/unit/test_human_input.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py && git commit -m "feat: compile human input policies"`

### Task 2: Validate Question Ingress and COMMANDER Decisions

**Files:**
- Modify: `src/harness/echelon_result_schema.py`
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `tests/kernel/test_echelon_result_schema.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`
- Create: `tests/unit/test_human_input_resolution_contract.py`

**Interfaces:**
- Produces: canonical question-bearing result validation and
  `validate_decision_resolution_result(...) -> DecisionResolution`.
- Consumes: immutable options from Task 1 and existing `SquadAgentResult`
  detachment/attestation.

- [ ] **Step 1: Write failing provider-ingress tests**

Require:

- a non-empty `escalation_question` only with `STOP_AND_ASK`;
- exact `blocked_reason` string to serve as `reason_code`;
- optional `escalation_recommended_answer` and
  `escalation_risk_level`;
- `ESCALATE` plus a question to fail closed;
- recommendation/risk values to survive prepared-result detachment without
  becoming controller-owned policy fields.

- [ ] **Step 2: Write failing strict decision-result tests**

Test the exact envelope:

```yaml
echelon_result:
  verdict: DECISION_RESOLVED
  state_updates: {}
  journal_entries: []
  decision:
    selected_option_id: approve
    answer_text: null
    rationale: The declared plan is internally consistent.
    confidence: high
```

Reject extra fields, non-empty state updates, journal entries, unknown option
ids, both answer fields, neither answer field, invalid confidence, `BLOCKED`,
and rationale over the chosen 2,000-character bound.

- [ ] **Step 3: Run focused tests and verify contract failures**

Run:
`python -m pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_prepared_phase_result.py tests/unit/test_human_input_resolution_contract.py -q -k 'human_input or question or decision_resolution'`

- [ ] **Step 4: Implement canonical ingress and decision validation**

Add `DECISION_RESOLVED` to the global verdict vocabulary but accept it only
through the strict decision contract for this path. Keep general phase result
contracts from using it accidentally.

- [ ] **Step 5: Run the complete affected kernel tests**

Run:
`python -m pytest tests/kernel/test_echelon_result_schema.py tests/kernel/test_prepared_phase_result.py tests/unit/test_human_input_resolution_contract.py -q`

Expected: all pass.

- [ ] **Step 6: Commit ingress contracts**

Run:
`git add src/harness/echelon_result_schema.py src/harness/prepared_phase_result.py tests/kernel/test_echelon_result_schema.py tests/kernel/test_prepared_phase_result.py tests/unit/test_human_input_resolution_contract.py && git commit -m "feat: validate human input result contracts"`

### Task 3: Add Versioned Durable Decision and Recovery Schemas

**Files:**
- Modify: `src/harness/blocked_decision.py`
- Modify: `src/harness/recovery_instruction.py`
- Modify: `tests/unit/test_blocked_decision.py`
- Modify: `tests/unit/test_recovery.py`
- Modify: `tests/unit/test_re_lifecycle.py`

**Interfaces:**
- Produces: `validate_blocked_decision_v2(...)`,
  `build_blocked_decision_v2(...)`, `RecoveryKind.RESOLVE_DECISION`, and
  schema-v2 recovery validation with required `decision_id`.
- Preserves: every existing schema-v1 factory and RE assertion unchanged.

- [ ] **Step 1: Write failing exact-shape v2 tests**

Assert all required fields from the design, including explicit nulls. Reject
unknown fields, unknown status, malformed ids, mismatched option/answer shape,
negative attempts, invalid timestamps, and missing source revision.

- [ ] **Step 2: Write failing decision/instruction pairing tests**

Cover:

| Decision | Instruction |
|---|---|
| `pending`, `resolving` | v2 `resolve_decision`, human false |
| `awaiting_human` | v2 `await_human_answer`, human true |
| `failed` | v2 `manual_diagnosis`, empty phase, human false |
| `resolved` | no instruction |

Also prove schema-v1 rejects `decision_id` and schema-v2 requires it.

- [ ] **Step 3: Run focused tests and verify schema failures**

Run:
`python -m pytest tests/unit/test_blocked_decision.py tests/unit/test_recovery.py tests/unit/test_re_lifecycle.py -q`

- [ ] **Step 4: Implement v2 alongside v1**

Dispatch validation by exact integer `schema_version`. Update
`ensure_blocked_decision(...)` to leave every schema-v2 mapping untouched,
regardless of state display fields.

- [ ] **Step 5: Run the schema and RE lifecycle tests**

Run:
`python -m pytest tests/unit/test_blocked_decision.py tests/unit/test_recovery.py tests/unit/test_re_lifecycle.py -q`

Expected: all pass, including unchanged RE schema-v1 tests.

- [ ] **Step 6: Commit durable schemas**

Run:
`git add src/harness/blocked_decision.py src/harness/recovery_instruction.py tests/unit/test_blocked_decision.py tests/unit/test_recovery.py tests/unit/test_re_lifecycle.py && git commit -m "feat: add durable squad decision schema"`

### Task 4: Seal and Transition Decisions Through State CAS

**Files:**
- Modify: `src/harness/squad_state.py`
- Modify: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces: the state methods in the Interface Map and provider-advance
  decision sealing.
- Consumes: validated `PreparedHumanInput`, v2 decision builders, and v2
  recovery builders.

- [ ] **Step 1: Write failing non-provider seal tests**

Assert one state revision increment writes:

```python
{
    "status": "blocked",
    "blocked_decision": {"schema_version": 2, ...},
    "recovery_instruction": {"schema_version": 2, ...},
    "blocked_reason": request.reason_code,
    "escalation_question": request.question,
    "escalation_options": [...],
}
```

Prove stale source revision, an existing unresolved v2 decision, and an
invalid initial status write nothing.

- [ ] **Step 2: Write failing provider-advance atomicity tests**

Start from a provider snapshot and call `advance(...)` with a matching request.
Assert provider phase effects, dispatch receipt, v2 decision, and instruction
share one committed revision. Inject save failure and prove the durable state
is either the preimage or the complete postimage, never a schema-v1 decision.
Repeat the atomic assertion with a `controller_safeguard` request representing
`consecutive_why_fails`, since that safeguard is discovered inside the same
provider routing transaction.

- [ ] **Step 3: Write failing claim, recovery, failure, and resolve tests**

Cover:

- `pending -> resolving` and `attempts + 1`;
- a first provider/validation failure returns `resolving -> pending` so the
  second call can be claimed normally;
- a second provider/validation failure transitions to `failed`;
- interrupted `resolving -> pending` when attempts are below two;
- interrupted second attempt -> `failed` with
  `resolution_attempts_exhausted`;
- wrong decision id and stale revision are side-effect free;
- failed decisions clear legacy `escalation_question`;
- resolved decisions retain audit data and remove the instruction.

- [ ] **Step 4: Write failing generic-save protection tests**

An unrelated generic save may preserve an unresolved v2 pair exactly. It must
reject removal or mutation of the decision, instruction, phase, status,
blocked reason, question, or options. Resolved/failed decisions may be
replaced only by the dedicated seal path.

- [ ] **Step 5: Run focused state tests and verify failures**

Run:
`python -m pytest tests/kernel/test_squad_state.py -q -k 'human_input or decision_v2 or generic_save'`

- [ ] **Step 6: Implement the single unlocked seal primitive and CAS methods**

Call `_seal_human_input_decision_unlocked(...)` only while the state lock is
already held. In `advance(...)`, seal after applying attested provider and
controller effects but before `_save_unlocked(...)`; skip the existing
unconditional recovery-instruction removal when a request is being sealed.

- [ ] **Step 7: Run the complete state kernel**

Run:
`python -m pytest tests/kernel/test_squad_state.py -q`

Expected: all pass.

- [ ] **Step 8: Commit state authority**

Run:
`git add src/harness/squad_state.py tests/kernel/test_squad_state.py && git commit -m "feat: seal human decisions through state CAS"`

### Task 5: Implement the Controller Autonomy Boundary

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `extension/agents/control/commander.md`
- Create: `tests/integration/test_human_input_routing.py`
- Modify: `tests/unit/test_commander_escalation_options_contract.py`

**Interfaces:**
- Produces: `handle_human_input(...)`,
  `resume_pending_human_input()`, strict COMMANDER dispatch, deterministic
  Semi selection, and bounded context rendering.
- Consumes: registry, state CAS methods, existing provider dispatch telemetry,
  and existing execution leases.

- [ ] **Step 1: Write the failing autonomy matrix tests**

Parametrize:

| Mode | Operational | Material | External | Expected |
|---|---|---|---|---|
| guided | any | any | any | awaiting human |
| semi | low recommended | n/a | n/a | deterministic resolution |
| semi | no/unsafe recommendation | any | any | awaiting human |
| banzai | COMMANDER | COMMANDER | human | matching route |

Assert the sealed decision's `autonomy_mode` comes from state, not the current
CLI argument.

- [ ] **Step 2: Write failing Semi selection tests**

Cover option-level risk overriding request risk, missing risk, multiple
recommendations rejected during preparation, free-text recommendation,
`require_human`, and material classification always awaiting human.

- [ ] **Step 3: Write failing COMMANDER retry and context tests**

Assert:

- only registered state keys and files appear;
- paths cannot escape their declared roots;
- the complete prompt is at most 32,768 UTF-8 bytes;
- one invalid/provider-failed result retries once;
- a second failure persists `manual_diagnosis`;
- no question or direct-write instruction appears in COMMANDER output
  authority.

- [ ] **Step 4: Run the focused routing tests and verify failures**

Run:
`python -m pytest tests/integration/test_human_input_routing.py tests/unit/test_commander_escalation_options_contract.py -q -k 'mode or semi or commander or context'`

- [ ] **Step 5: Implement mode selection and strict COMMANDER dispatch**

Use `claim_human_input_decision(...)` immediately before each model call.
Validate the response before invoking any handler. After an invalid result,
call `record_human_input_resolution_failure(...)`; retry only when it returns a
`pending` decision. On process restart, `resume_pending_human_input()` first calls
`recover_interrupted_human_input_decision()`.

- [ ] **Step 6: Wire provider questions before the existing advance**

After `PreparedPhaseResult` validation and routing-decision construction, detect
the canonical question fields, prepare the request from the exact node/reason
policy and captured routing snapshot, and call `handle_human_input(...)` with
`_ProviderHumanInputAdvance`. The handler must pass that same attested routing
decision to `SquadStateStore.advance(...)`; do not reconstruct or replay the
provider result.

- [ ] **Step 7: Replace the two duplicated Banzai branches**

At controller entry and after provider decision sealing, call
`resume_pending_human_input()` only. Remove direct mode checks and calls to
`_judgment_dispatch_escalation(...)`. Retire that method after its handler
logic is moved in Task 6.

- [ ] **Step 8: Update the COMMANDER prompt contract**

Document `DECISION_RESOLVED`, exact choice/free-text rules, no recursive human
request, and no direct state/file mutation. Remove the old Banzai instruction
to write `user-clarifications.md` or return cleanup state updates.

- [ ] **Step 9: Run focused controller routing tests**

Run:
`python -m pytest tests/integration/test_human_input_routing.py tests/unit/test_commander_escalation_options_contract.py -q`

Expected: all pass.

- [ ] **Step 10: Commit the controller boundary**

Run:
`git add src/harness/squad.py extension/agents/control/commander.md tests/integration/test_human_input_routing.py tests/unit/test_commander_escalation_options_contract.py && git commit -m "feat: centralize autonomy decision routing"`

### Task 6: Move Resolution Handlers Behind One Apply Method

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_human_input_routing.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `apply_human_input_resolution(...)` plus the five closed handlers.
- Reuses: current issue-resolution ledger validation, dispatch-count reset,
  WHY counters, and routing targets. It does not duplicate those algorithms.

- [ ] **Step 1: Write failing clarification-handler tests**

Verify an answer appends:

```markdown
## Decision dec-...

**Question:** ...

**Answer:** ...
```

to `staging/user-clarifications.md` through atomic replacement. Applying the
same decision after a simulated state-save interruption must not append a
second section.

- [ ] **Step 2: Write failing gate and safeguard-handler tests**

Cover:

- gate approve -> declared forward target;
- gate reject -> `terminal-blocked` and `gate_rejected`;
- dispatch-cap selection must match an existing evidence-backed issue option
  and reuse the current ledger update;
- repeated WHY failure resets `why_fail_count`;
- WHY2 stagnation resets both WHY and stagnation counters;
- invalid option, target, outcome, handler, resolver, id, or revision writes
  nothing.

- [ ] **Step 3: Run focused handler tests and verify failures**

Run:
`python -m pytest tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py -q -k 'human_input_handler or clarification_idempotent or banzai_escalation or consecutive_fail or phase_dispatch_limit'`

- [ ] **Step 4: Implement the closed handler dispatch**

Use an exact dictionary from handler id to private controller method. Handler
methods return only controller-owned `state_updates`, `state_removals`, and
the already validated route; they do not save state themselves.

Write the clarification file before the state CAS, keyed by decision id. Then
call `apply_human_input_state_resolution(...)` once so decision resolution,
display cleanup, instruction removal, status, phase, and counters share one
state replacement.

- [ ] **Step 5: Wire all three safeguard producers**

At the pre-dispatch cap, prepare a `controller_safeguard` request from the
captured revision and call `handle_human_input(...)` without a provider
advance.

At repeated-WHY-failure and WHY2-stagnation routing, return the prepared
safeguard request beside the controller updates, then call
`handle_human_input(...)` with the same `_ProviderHumanInputAdvance` that
commits those counters and provider effects. Remove direct question rendering
and raw decision-state writes while preserving the evidence consumed by the
handlers.

- [ ] **Step 6: Remove the retired escalation cleanup path**

Delete `_judgment_dispatch_escalation(...)` after migrating its dispatch-cap
and WHY reset behavior. Keep unrelated `_judgment_dispatch(...)` routing
judgments intact.

- [ ] **Step 7: Run focused and existing escalation regressions**

Run:
`python -m pytest tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py -q -k 'human_input or escalation or phase_dispatch_limit or consecutive_why or why2_metric_stagnation'`

Expected: all pass after updating obsolete direct-cleanup assertions to the v2
decision contract.

- [ ] **Step 8: Commit shared resolution handlers**

Run:
`git add src/harness/squad.py tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py && git commit -m "feat: apply human decisions through shared handlers"`

### Task 7: Migrate Workflow Producers and Human Gates

**Files:**
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/workflow/phases/phase1-tracker.md`
- Modify: `extension/workflow/phases/phase1-why1.md`
- Modify: `extension/workflow/phases/phase1-why2.md`
- Modify: `extension/workflow/phases/phase1-investigate.md`
- Modify: `extension/workflow/phases/phase2-tracker-alignment.md`
- Modify: `extension/agents/control/tracker.md`
- Modify: `extension/agents/exploration/sage.md`
- Modify: `extension/agents/specialists/investigator.md`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`
- Modify: `tests/integration/test_human_input_routing.py`
- Create: `tests/unit/test_human_input_static_contract.py`

**Interfaces:**
- Produces: exact initial registry declarations and one gate interception path.
- Removes: `HumanGateExecutor`, `_executors["human_gate"]`, all Phase A
  executor `input()`, gate autonomy stanzas, and question-bearing `ESCALATE`.

- [ ] **Step 1: Write failing real-workflow registry assertions**

Assert all eleven initial reason entries, including both
`phase1-investigate` variants. Assert:

- `checkpoint-assess` is material and Semi-human;
- `checkpoint-plan` is operational with one low-risk recommended approve;
- approve/reject options map to exact outcome edges;
- all question-capable provider allowlists include risk/recommendation fields
  only where declared.

- [ ] **Step 2: Write failing gate mode integration tests**

For both gates in Guided, Semi, and Banzai, assert the mode matrix. For Banzai,
provide COMMANDER approve and reject results separately. Prove
`checkpoint-plan` remains Semi-auto and `checkpoint-assess` remains
Semi-human.

- [ ] **Step 3: Write failing static guard tests**

Read source and workflow text and assert:

- no `HumanGateExecutor`;
- no `"human_gate"` executor registration;
- no `input(` in `src/harness/squad.py` or `src/harness/squad_executors.py`;
- no gate `autonomy:` stanza;
- no provider transition accepts `ESCALATE` when it can carry a question;
- no old COMMANDER direct clarification/state-cleanup instruction.

- [ ] **Step 4: Run workflow/gate/static tests and verify failures**

Run:
`python -m pytest tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py tests/integration/test_human_input_routing.py tests/unit/test_human_input_static_contract.py -q`

- [ ] **Step 5: Add exact workflow policy lists**

Use these reason codes and handlers:

| Producer | Reason | Classification | Handler |
|---|---|---|---|
| `phase1-tracker` | `human_clarification_required` | material | `clarification_resume` |
| `phase1-why1` | `human_clarification_required` | material | `clarification_resume` |
| `phase1-why2` | `human_clarification_required` | material | `clarification_resume` |
| `phase1-investigate` | `human_clarification_required` | material | `clarification_resume` |
| `phase1-investigate` | `investigation_access_required` | external prerequisite | `clarification_resume` |
| `phase2-tracker-alignment` | `human_clarification_required` | material | `clarification_resume` |
| `checkpoint-assess` | `checkpoint_assess_decision_required` | material | `gate_outcome` |
| `checkpoint-plan` | `checkpoint_plan_decision_required` | operational | `gate_outcome` |

Declare gate edges as `outcome: approved` or `outcome: rejected` with matching
`human_input_outcome = approved|rejected` conditions. The handler uses the
compiled edge target directly and does not persist `human_input_outcome`.

- [ ] **Step 6: Intercept gates before executor lookup**

Build the request from the node's sole gate policy and current state snapshot.
Do not construct a provider result for a gate. Remove `HumanGateExecutor` and
its registration.

- [ ] **Step 7: Update phase and shared agent prompts**

Require exact reason codes, `STOP_AND_ASK`, and risk/recommendation shape.
For investigation, use `investigation_access_required` only when authority or
credentials unavailable to Echelon are required; use
`human_clarification_required` for an inconclusive project decision.

- [ ] **Step 8: Run workflow, gate, and static tests**

Run:
`python -m pytest tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py tests/integration/test_human_input_routing.py tests/unit/test_human_input_static_contract.py -q`

Expected: all pass.

- [ ] **Step 9: Commit producer and gate migration**

Run:
`git add extension/workflow/definition.yaml extension/workflow/phases/phase1-tracker.md extension/workflow/phases/phase1-why1.md extension/workflow/phases/phase1-why2.md extension/workflow/phases/phase1-investigate.md extension/workflow/phases/phase2-tracker-alignment.md extension/agents/control/tracker.md extension/agents/exploration/sage.md extension/agents/specialists/investigator.md src/harness/squad.py src/harness/squad_executors.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py tests/integration/test_human_input_routing.py tests/unit/test_human_input_static_contract.py && git commit -m "feat: route workflow questions through controller"`

### Task 8: Route Status, Continue, and Resume Through the Decision

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `extension/commands/echelon.resume.md`
- Modify: `tests/unit/test_cli_status.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_resume_escalation_options.py`
- Modify: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Produces: read-only status rendering, continue-driven automatic resolution,
  and controller-owned human submission.
- Removes: direct CLI writes to `user-clarifications.md`, decision state,
  escalation cleanup fields, phase, and recovery instruction.

- [ ] **Step 1: Write failing status tests**

For a v2 active decision, show mode, classification, question, exact options,
recommendation, risk, and:

- `echelon spec continue` for `pending`/recoverable `resolving`;
- `echelon spec resume "<your answer>"` for `awaiting_human`;
- manual diagnosis for `failed`.

- [ ] **Step 2: Write failing continue tests**

Assert Banzai and eligible Semi call the controller with the persisted
decision and persisted autonomy mode. Guided, ineligible Semi, and external
prerequisites remain blocked without state cleanup. A `--mode` override cannot
claim or reclassify the decision.

- [ ] **Step 3: Rewrite resume regression fixtures around schema v2**

Assert exact option id/label parsing and free text call
`SquadController.resume_with_human_input(answer)`. Reject:

- non-`awaiting_human`;
- missing/mismatched v2 instruction;
- Banzai project decisions;
- malformed options;
- stale decision id.

Allow a Banzai external prerequisite because its decision is
`awaiting_human`.

- [ ] **Step 4: Write failing bypass-guard tests**

An unresolved v2 decision must reject `--next-phase` and
`echelon phase run`. The guard belongs in controller entry/manual phase entry
as well as CLI rendering, so direct Python invocation cannot bypass it.

- [ ] **Step 5: Run focused CLI tests and verify failures**

Run:
`python -m pytest tests/unit/test_cli_status.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/integration/test_human_input_routing.py -q -k 'decision or human_input or resume or bypass'`

- [ ] **Step 6: Implement read-only CLI routing**

Teach `_recovery_action_from_instruction(...)` about schema-v2
`resolve_decision`. Make `_cmd_resume(...)` construct the existing graph,
provider, store, and controller, then call only
`resume_with_human_input(answer)`.

Preserve the existing Typer wrappers in `cli_app.py`; update only descriptions
or argument help that still says generic escalation rather than active
decision.

- [ ] **Step 7: Update resume command documentation**

Describe awaiting-human decisions, exact option matching, Banzai external
prerequisites, and the shared controller apply path. Remove direct file/state
instructions.

- [ ] **Step 8: Run complete CLI decision tests**

Run:
`python -m pytest tests/unit/test_cli_status.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/integration/test_human_input_routing.py -q`

Expected: all pass.

- [ ] **Step 9: Commit CLI migration**

Before staging, inspect and preserve unrelated `cli_app.py` edits:
`git diff -- src/echelon/cli_app.py`

Then run:
`git add src/echelon/cli.py src/echelon/cli_app.py extension/commands/echelon.resume.md tests/unit/test_cli_status.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py tests/integration/test_human_input_routing.py && git commit -m "feat: route decision recovery through controller"`

### Task 9: Legacy Adaptation and End-to-End Verification

**Files:**
- Modify: `src/harness/human_input.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_human_input_routing.py`
- Modify: `tests/unit/test_human_input_static_contract.py`
- Modify: `docs/superpowers/specs/2026-07-27-autonomy-decision-resolution-design.md`
- Modify: `docs/superpowers/plans/2026-07-28-autonomy-human-input-routing.md`

**Interfaces:**
- Produces: one safe legacy Squad adapter and final proof of the approved
  boundary.
- Preserves: unknown v1 Squad and all RE decisions on their existing recovery
  paths.

- [x] **Step 1: Write failing safe-adaptation tests**

Adapt only when phase, normalized reason, options, and resume behavior identify
one exact current provider or safeguard policy. Assert `source_kind` becomes
`legacy_recovery` while the matched policy remains exact.

Reject unknown reasons, malformed options, terminal phases without a handler,
ambiguous `phase1-investigate` reasons, and already resolved schema-v1
decisions. Prove RE v1 states remain unchanged.

- [x] **Step 2: Write restart and interruption integration tests**

Cover:

- provider request resolved inline;
- process restart after provider v2 seal;
- crash after `pending -> resolving`;
- crash after clarification file replacement but before state resolution;
- second invalid COMMANDER attempt -> failed/manual diagnosis;
- status, continue, and resume observing the same decision id.

- [x] **Step 3: Run legacy and restart tests and verify failures**

Run:
`python -m pytest tests/integration/test_human_input_routing.py tests/unit/test_re_lifecycle.py -q -k 'legacy or restart or interrupted or external_prerequisite'`

- [x] **Step 4: Implement the exact legacy adapter**

Do not add a registry wildcard for `legacy_recovery`. Resolve one current
policy first, derive one exact
`(legacy_recovery, producer_id, reason_code)` alias with identical authority,
then prepare the tagged request through that alias. Unknown legacy state falls
through to the existing manual recovery classifier.

The implemented adapter accepts only an active schema-v1 Squad decision whose
question, display phase, normalized reason, answer shape, and optional
schema-v1 recovery instruction agree. A terminal safeguard display phase also
requires the exact non-terminal source in `phase_dispatch_limit_phase` or
`last_dispatch.phase_id`; the instruction, when present, must bind that same
source and resume kind. It rejects RE, resolved, malformed, ambiguous, and
unregistered states. A fresh process re-derives the same exact alias from the
sealed producer, reason, and source phase, preserving the durable decision id.

- [x] **Step 5: Run the complete focused suite**

Run:
`python -m pytest tests/unit/test_human_input.py tests/unit/test_human_input_resolution_contract.py tests/unit/test_blocked_decision.py tests/unit/test_recovery.py tests/unit/test_re_lifecycle.py tests/unit/test_human_input_static_contract.py tests/kernel/test_echelon_result_schema.py tests/kernel/test_prepared_phase_result.py tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py tests/kernel/test_squad_state.py tests/integration/test_human_input_routing.py tests/unit/test_cli_status.py tests/unit/test_cli_continue.py tests/unit/test_cli_resume_escalation_options.py -q`

- [x] **Step 6: Run existing controller and CLI regressions**

Run:
`python -m pytest tests/integration/test_squad_controller.py tests/unit/test_commander_escalation_options_contract.py tests/unit/test_cli_resume_spec_context.py tests/unit/test_readme_recovery_contracts.py -q`

- [x] **Step 7: Run the full Python suite**

Run:
`python -m pytest -q`

Expected: all pass. If unrelated pre-existing failures exist, record the exact
test ids and prove the focused suite remains green before proceeding.

- [x] **Step 8: Run static boundary checks**

Run:
`python -m pytest tests/unit/test_human_input_static_contract.py -q`

Run:
`git diff --name-only "$(git merge-base HEAD main)"..HEAD`

Confirm the implementation contains none of the excluded provider adapter,
Docker/OCI, usage ledger, workflow bundle, spec lifecycle, publication,
completion, Phase B, or RE controller modules.

- [x] **Step 9: Review type and placeholder consistency**

Run:
`rg -n 'TBD|TODO|FIXME|placeholder' src/harness/human_input.py src/harness/blocked_decision.py src/harness/recovery_instruction.py docs/superpowers/plans/2026-07-28-autonomy-human-input-routing.md`

Then verify every status, reason code, handler id, source kind, classification,
risk, resolver, and recovery kind has one spelling across source, workflow,
prompts, tests, design, and plan.

- [x] **Step 10: Commit compatibility and verification updates**

Run:
`git add src/harness/human_input.py src/harness/squad.py tests/integration/test_human_input_routing.py tests/unit/test_human_input_static_contract.py docs/superpowers/specs/2026-07-27-autonomy-decision-resolution-design.md docs/superpowers/plans/2026-07-28-autonomy-human-input-routing.md && git commit -m "test: verify autonomy human input routing"`

## Execution Handoff

1. **Subagent-Driven Development (recommended):** Use one fresh worker per
   task, with a spec-compliance review followed by a code-quality review before
   moving to the next task.
2. **Inline Execution:** Execute in this session while preserving the same task
   order, red-green checkpoints, and per-task commits.
