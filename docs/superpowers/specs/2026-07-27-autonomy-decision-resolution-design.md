# Autonomy Human-Input Routing Design

**Status:** Implemented. The executable plan and verification record are
`docs/superpowers/plans/2026-07-28-autonomy-human-input-routing.md`.

## Goal

Echelon must have one standard way to represent "the workflow needs a human
decision" and one controller boundary that handles it according to autonomy
mode:

- `guided`: ask the human;
- `semi`: automatically apply only an explicit low-risk recommendation,
  otherwise ask the human;
- `banzai`: send every project decision to COMMANDER and apply its best valid
  answer;
- all modes: ask the human for genuine external prerequisites that Echelon
  cannot decide or perform.

The change makes the current Banzai behavior consistent and recoverable. It does
not redesign provider execution, accounting, workflow bootstrapping, completion,
or run lifecycle.

## Scope

This design covers Phase A Squad human-input sources:

1. Provider results containing a validated `escalation_question`.
2. `human_gate` workflow nodes.
3. Controller safeguards that currently create escalation questions.
4. Existing persisted human-facing recovery instructions when they contain
   enough legacy state to construct a request safely.

This design does not cover:

- OCI or process containment;
- token or cost accounting;
- provider selection or provider protocol changes;
- workflow bundles or installed-extension drift;
- spec run creation, switching, or branch recovery;
- publication or controller-completion protocol changes;
- Phase B build/review workflows;
- RE lifecycle decisions, which continue using `blocked_decision` schema v1.

Those concerns may have their own designs. They are not prerequisites for
autonomy routing.

## Current Problem

The necessary pieces already exist, but the policy is split across several
paths:

- `SquadController.run()` detects an existing escalation and dispatches
  COMMANDER only in Banzai.
- The same run loop repeats nearly identical logic immediately after a phase
  result is committed.
- `HumanGateExecutor` bypasses that logic: it calls `input()` in guided and
  automatically approves in both Semi and Banzai.
- `spec resume` edits clarification files and state directly.
- `blocked_decision` records a human-facing question, but it does not identify
  the producer or drive one shared autonomy policy.
- Semi treats provider escalations as human-only even when they carry an
  explicit low-risk recommendation.

Consequently, "human input required" is not one controller event. Banzai is
effective for some provider escalations but not for human gates, and new
producers can accidentally bypass it.

## Core Types

### PreparedHumanInput

Every current or future producer must construct a controller-owned
`PreparedHumanInput` before a question can be rendered, persisted as human
recovery, or sent to COMMANDER.

```python
@dataclass(frozen=True)
class PreparedHumanInput:
    schema_version: Literal[1]
    source_kind: Literal[
        "provider_escalation",
        "human_gate",
        "controller_safeguard",
        "legacy_recovery",
    ]
    producer_id: str
    phase_id: str
    reason_code: str
    classification: Literal[
        "operational",
        "material",
        "external_prerequisite",
    ]
    question: str
    options: tuple[HumanInputOption, ...]
    recommended_answer: str | None
    risk_level: Literal["low", "medium", "high", "critical"] | None
    resolution_handler: str
    source_state_revision: int
```

```python
@dataclass(frozen=True)
class HumanInputOption:
    id: str
    label: str
    description: str
    recommended: bool
    risk_level: Literal["low", "medium", "high", "critical"] | None
    next_phase: str | None
    outcome: str | None
```

Constraints:

- `producer_id` is the compiled workflow entry id or closed safeguard id; it is
  never provider text.
- `phase_id` must be a current workflow phase.
- `reason_code` and `resolution_handler` must be registered for the exact
  `(source_kind, producer_id, reason_code)` key, and the policy must permit
  `phase_id`.
- `question` is non-empty and at most 4,000 characters.
- Option ids are unique, non-empty, and controller-normalized.
- Any `next_phase` must be permitted by the registered policy and must name an
  exact current graph target.
- At most one option may be recommended.
- A free-text recommendation is allowed only when there are no options.
- Provider output may supply question text, option facts, recommendation, and
  risk. It cannot supply `source_kind`, `phase_id`, classification,
  `producer_id`, `resolution_handler`, or source state revision.
- Invalid input becomes ordinary `manual_diagnosis`; it is never shown to the
  human and never sent to COMMANDER.

`PreparedHumanInput` is ephemeral. The durable record remains
`blocked_decision`.

### Policy Registry

A closed `HumanInputPolicyRegistry` presents one lookup interface over two
controller-owned sources:

- Workflow producers compile from exact entries in the `human_input` list in
  `extension/workflow/definition.yaml`.
- Controller safeguards compile from an exact Python registry because they do
  not have workflow dispatch nodes.

Each entry maps an exact `(source_kind, producer_id, reason_code)` identity to:

- classification;
- allowed option targets and outcomes;
- resolution handler;
- whether free text is allowed;
- whether a recommendation may be used by Semi.

There is no wildcard fallback. Adding `escalation_question` to a result contract
without registering the producer is a validation error.

Workflow producer ids are their exact phase or nested dispatch ids. The initial
controller safeguard ids are exactly `phase_dispatch_limit`,
`consecutive_why_fails`, and `why2_metric_stagnation`; their policies enumerate
the non-terminal phases where each safeguard can be raised. They do not use a
phase wildcard.

The workflow shape is a list so a producer such as `phase1-investigate` can
declare multiple reason codes with different classifications without accepting
provider-supplied policy authority:

```yaml
human_input:
  - reason_code: human_clarification_required
    classification: material
    semi_policy: require_human | auto_if_recommended_low_risk
    resolution_handler: clarification_resume
    allow_free_text: true
    allowed_target_phases: [phase1-tracker]
    context_state_keys: [user_message, phase]
    context_paths: ["{staging_dir}/user-intent.md"]
```

For a `human_gate`, the list contains one entry that additionally declares
exact options:

```yaml
human_input:
  - reason_code: checkpoint_plan_decision_required
    classification: operational
    semi_policy: auto_if_recommended_low_risk
    resolution_handler: gate_outcome
    allow_free_text: false
    allowed_target_phases: [phase4-document, terminal-blocked]
    context_state_keys: [user_message, phase, quality_scores]
    context_paths: ["{spec_dir}/plan.md", "{spec_dir}/tasks.md"]
    options:
      - id: approve
        label: Approve
        description: Continue to finalization.
        recommended: true
        risk_level: low
        next_phase: phase4-document
        outcome: approved
      - id: reject
        label: Reject
        description: Stop for plan revision.
        recommended: false
        risk_level: low
        next_phase: terminal-blocked
        outcome: rejected
```

The workflow validator requires every `context_state_key` to come from a closed
read-only allowlist, resolves every context path through the existing controller
path mapping, and caps the complete COMMANDER context at 32 KiB. Providers
cannot add context keys or paths.

The initial registry is:

| Producer | Reason | Classification | Handler |
|---|---|---|---|
| `phase1-tracker` provider | `human_clarification_required` | material | `clarification_resume` |
| `phase1-why1` provider | `human_clarification_required` | material | `clarification_resume` |
| `phase1-why2` provider | `human_clarification_required` | material | `clarification_resume` |
| `phase1-investigate` inconclusive | `human_clarification_required` | material | `clarification_resume` |
| `phase1-investigate` access required | `investigation_access_required` | external_prerequisite | `clarification_resume` |
| `phase2-tracker-alignment` provider | `human_clarification_required` | material | `clarification_resume` |
| `checkpoint-assess` gate | `checkpoint_assess_decision_required` | material | `gate_outcome` |
| `checkpoint-plan` gate | `checkpoint_plan_decision_required` | operational | `gate_outcome` |
| dispatch cap safeguard | `phase_dispatch_limit` | material | `phase_dispatch_limit` |
| repeated WHY failure safeguard | `consecutive_why_fails` | material | `reset_why_fail_count` |
| WHY2 stagnation safeguard | `why2_metric_stagnation` | material | `reset_why2_stagnation` |

Provider prompts and workflow contracts are updated to use these exact reason
codes, permit `escalation_risk_level` where recommendations are allowed, and
use `STOP_AND_ASK` for every question-bearing result. Question-bearing
`ESCALATE` is removed. A producer-specific diagnostic may be retained
separately, but it is not policy authority.

## One Interception Boundary

`SquadController.handle_human_input(request)` is the only autonomy policy
boundary. It:

1. Validates the request against the policy registry and current graph.
2. Persists the matching durable decision and recovery instruction.
3. Chooses Guided, Semi, Banzai, or external-prerequisite handling.
4. Applies a valid resolution through one controller method, or returns the run
   blocked.

For provider-originated requests, and for the repeated-WHY/stagnation
safeguards discovered while evaluating that provider result, the caller also
supplies the already prepared phase advance. `handle_human_input` seals through
that existing advance transaction. Gates, the pre-dispatch phase-cap
safeguard, and legacy adaptation use the dedicated state-store seal method. A
provider request without its matching prepared advance, a routed WHY safeguard
without that advance, or any dedicated producer with an advance is a
controller contract error.

Every producer reaches this method:

- Provider escalation: after exact result validation and before the existing
  phase advance, when a non-empty `escalation_question` is present.
- Human gate: in `SquadController`, before executor lookup. The controller
  builds the request directly from the compiled node policy and does not
  dispatch a `HumanGateExecutor`.
- Controller safeguard: when the controller constructs the safeguard question.
  Repeated-WHY and stagnation requests travel with the current attested phase
  advance; the pre-dispatch phase cap uses the dedicated seal.
- Existing blocked run: at controller entry through
  `resume_pending_human_input()`.

`HumanGateExecutor` and its `_executors["human_gate"]` registration are removed.
The controller is the sole gate interception path.

For a provider escalation, the controller constructs `PreparedHumanInput`
before state mutation and passes it as a controller-owned argument to the
existing phase advance. The store persists the provider phase effects and the
schema-v2 decision/instruction pair in that same state replacement. It does not
first call the current automatic schema-v1 `ensure_blocked_decision` path. A
crash can therefore expose either the pre-advance state or the complete v2
block, never a new raw Squad escalation with only a v1 decision.

The two current Banzai escalation branches in `SquadController.run()` are
replaced by calls to `resume_pending_human_input()`. They do not contain their
own mode checks or COMMANDER invocation.

The interception guarantee is about decision routing: the question cannot
reach a human-facing surface before interception. This design does not change
the current phase-result publication transaction or require provider effects to
be rolled back when a later question is found.

## Autonomy Policy

| Mode | Operational | Material | External prerequisite |
|---|---|---|---|
| Guided | human | human | human |
| Semi | auto only with one explicit low-risk recommendation; otherwise human | human | human |
| Banzai | COMMANDER | COMMANDER | human |

The initial durable status is selected during the same seal transaction:

- Banzai operational/material requests and eligible Semi requests seal as
  `pending` with `resolve_decision`.
- Guided requests, ineligible Semi requests, and every external prerequisite
  seal as `awaiting_human` with `await_human_answer`.

Automatic resolution begins only after that transaction commits. A crash after
sealing is therefore recoverable through the matching instruction without
reclassifying the request.

Semi resolution is deterministic and does not call COMMANDER:

- The compiled policy must be `auto_if_recommended_low_risk`; a
  `require_human` policy always blocks for the human.
- For options, exactly one option must be marked recommended and its effective
  risk must be `low`; effective risk is the option risk when present and the
  request risk otherwise.
- For free text, `recommended_answer` must be non-empty and request risk must be
  `low`.
- Missing risk is not low risk.
- A medium, high, or critical recommendation requires the human.
- `checkpoint-plan` declares its approve option recommended and low risk, so
  existing Semi auto-proceed behavior remains.
- `checkpoint-assess` is material, so Semi continues to require the human.

Banzai never automatically approves a gate. It gives COMMANDER the exact
approve and reject options and accepts either valid choice.

Both current human gates gain explicit outcome edges in the workflow:
`approved` targets their current next phase and `rejected` targets
`terminal-blocked`. Gate options must correspond one-to-one with those declared
edges; the controller does not invent a reject route outside the graph.
Each gate transition declares an exact `outcome` key and a matching
`human_input_outcome = <value>` condition. `outcome` is valid only on
`human_gate` transitions, must be unique within the gate, and is declarative:
the controller selects the matched target directly without persisting
`human_input_outcome` as ordinary run state.
Their current per-mode `autonomy` stanzas are removed; the compiled
`human_input` policy plus the persisted `autonomy_mode` captured at request
sealing is the only gate mode authority.

The only intentional Banzai-to-human path is
`classification: external_prerequisite`. Examples are missing credentials,
legal acceptance, unavailable external access, or an action that only the
operator can perform. Uncertainty, product preference, architecture choice, or
risk is not an external prerequisite.

## COMMANDER Resolution Contract

Banzai calls the existing COMMANDER provider through a new strict
`DecisionResolutionContract`. COMMANDER receives:

- the prepared request;
- the exact allowed options;
- only the policy's compiled `context_state_keys` and `context_paths`, rendered
  and bounded by the controller;
- the instruction to choose the best valid answer without asking another
  question.

COMMANDER returns exactly one existing result envelope:

```yaml
echelon_result:
  verdict: DECISION_RESOLVED
  state_updates: {}
  journal_entries: []
  decision:
    selected_option_id: "<exact option id>" | null
    answer_text: "<answer>" | null
    rationale: "<bounded explanation>"
    confidence: high | medium | low
```

Rules:

- Choice requests require one exact `selected_option_id` and null
  `answer_text`.
- Free-text requests require non-empty `answer_text` and null
  `selected_option_id`.
- COMMANDER cannot set phase, status, counters, cleanup fields, or recovery
  fields.
- COMMANDER cannot return `BLOCKED`, request a human, invent an option, or
  choose an undeclared phase.
- Output is validated before any state or file mutation.
- Provider failure or invalid output records the failed attempt and returns the
  decision from `resolving` to `pending` when `attempts < 2`, then retries
  once. A second failure marks the decision failed and persists
  `manual_diagnosis`; it does not silently approve or ask the human in Banzai.

The controller, not COMMANDER, writes clarification files and state.

## Durable Decision and Recovery

New Squad decisions use `blocked_decision` schema v2:

```yaml
blocked_decision:
  schema_version: 2
  id: "dec-<random>"
  status: pending | resolving | awaiting_human | resolved | failed
  source_kind: provider_escalation | human_gate | controller_safeguard | legacy_recovery
  producer_id: phase1-why1
  source_phase: phase1-why1
  reason_code: human_clarification_required
  classification: material
  question: "..."
  options: []
  recommended_answer: null
  risk_level: null
  resolution_handler: clarification_resume
  autonomy_mode: banzai
  source_state_revision: 42
  selected_option_id: null
  answer_text: null
  resolved_by: null
  attempts: 0
  failure_code: null
  created_at: "<UTC>"
  resolved_at: null
```

All fields shown are required; nullable fields use explicit null.

The existing recovery-instruction mechanism gains:

- `RecoveryKind.RESOLVE_DECISION = "resolve_decision"`;
- schema v2 with one additional required `decision_id`.

The decision and instruction must agree:

| Decision status | Recovery kind | `requires_human_input` |
|---|---|---|
| `pending` or `resolving` | `resolve_decision` | false |
| `awaiting_human` | `await_human_answer` | true |
| `failed` | `manual_diagnosis` | false |
| `resolved` | no instruction | false |

For schema v2, `phase` equals `source_phase` for `resolve_decision` and
`await_human_answer`; it is empty for `manual_diagnosis`. The instruction's
`decision_id` must equal the active decision id. Schema-v1 validation remains
unchanged. Failing a decision keeps its sanitized question inside
`blocked_decision` for diagnosis but clears the legacy
`escalation_question`, so recovery classification cannot fall through to a
human prompt.

One private `_seal_human_input_decision_unlocked(...)` primitive validates and
writes the decision pair without acquiring a lock. It is called in exactly two
ways:

- the existing `advance(...)` state transaction calls it when the controller
  supplies a provider-originated request or a repeated-WHY/stagnation safeguard
  discovered during routing;
- `set_human_input_decision(...)` acquires the state lock once and calls it for
  human gates, the pre-dispatch phase-cap safeguard, and safe legacy
  adaptation.

The primitive atomically writes:

- `status: blocked`;
- the schema-v2 `blocked_decision`;
- the matching schema-v2 `recovery_instruction`;
- legacy display fields `blocked_reason`, `escalation_question`, and normalized
  `escalation_options`.

It compares `PreparedHumanInput.source_state_revision` with the state revision
loaded by that transaction. The durable field records that source revision;
the state replacement then advances the ordinary current revision. A stale
request has no effect.

The existing Phase A execution lock remains the single-run execution guard.
`spec run`, `spec continue`, and `spec resume` acquire it before sealing,
claiming, or applying a schema-v2 decision. No new process lease or lock
hierarchy is introduced. Before a COMMANDER call, the controller changes
`pending` to `resolving` and increments `attempts`.
The decision's `autonomy_mode` is copied from state when sealed and cannot be
changed by a CLI mode override. Under the execution lock, controller startup
treats a persisted `resolving` decision as an interrupted call: it returns it
to `pending` when `attempts < 2`, or fails it with
`resolution_attempts_exhausted` otherwise. Duplicate model calls are possible
after a process crash, as they are today, but only one result can pass the
current state-revision and decision-id checks. Provider-call accounting is
outside this design.

Resolved decisions remain in state for status/audit display. A later request
may replace only a resolved or failed decision. Pending, resolving, and
awaiting-human decisions cannot be overwritten.

## Applying a Resolution

Every Semi, Banzai, or human answer calls
`SquadController.apply_human_input_resolution(...)`. `spec resume` must not edit
state or clarification files directly.

The method validates:

- decision id and current decision status;
- the caller's expected current state revision, captured after claim or human
  submission;
- selected option or answer shape;
- graph target and registered handler;
- resolver permitted by autonomy mode.

It then invokes the registered controller handler:

- `clarification_resume`: atomically append one decision-id-labelled section to
  `staging/user-clarifications.md`; resume at the selected option's permitted
  `next_phase`, or at the source phase when the answer has no route.
- `gate_outcome`: apply the selected approve/reject outcome. Approve selects the
  declared target. Reject selects `terminal-blocked` with
  `blocked_reason: gate_rejected`.
- `phase_dispatch_limit`: require one existing evidence-backed issue option,
  apply the current issue-resolution ledger update, and reopen only the capped
  phase's dispatch count.
- `reset_why_fail_count`: reset the existing counter and redispatch the source
  phase.
- `reset_why2_stagnation`: reset the existing WHY and stagnation counters and
  redispatch the source phase.

In the same state transaction it marks the decision resolved, records selected
answer and resolver, removes the matching recovery instruction, clears
escalation display fields, and applies the handler's status/phase updates.

Clarification file writing uses an atomic replacement and is idempotent by
decision id. Recovery after a file write but before state replacement detects
the existing labelled section and does not append it twice.

## CLI Behavior

- `echelon spec status` displays the active decision, mode, question, options,
  recommendation, risk, and exact recovery command.
- `echelon spec continue` resolves `pending` or interrupted `resolving`
  decisions for Banzai and eligible Semi requests. It never clears the decision
  before resolution succeeds.
- `echelon spec resume "<answer>"` is accepted only for
  `awaiting_human` with a matching `await_human_answer` instruction. It parses
  an exact option id/label or free text and calls the shared controller
  resolution method.
- `spec resume` on a Banzai project decision is rejected because COMMANDER owns
  it. Banzai external prerequisites remain resumable by the human.
- Manual phase execution and `--next-phase` reject while an unresolved
  schema-v2 decision exists.
- Existing active-run selection behavior is unchanged.

## Legacy Compatibility

- `blocked_decision` schema v1 remains valid for RE and old Squad runs.
- The new Squad controller writes schema v2 only.
- An active legacy Squad state with `status: blocked` and a non-empty
  `escalation_question` can be adapted once to `source_kind: legacy_recovery`
  only when its phase, normalized reason, options, and resume behavior map to
  one exact current provider or safeguard registry entry. The adapter derives
  one exact `(legacy_recovery, producer_id, reason_code)` policy alias by
  copying that matched entry's authority; it does not install a wildcard or
  broaden any target, handler, classification, or recommendation rule.
- Adaptation requires an active schema-v1 `pending` decision whose question,
  reason, display phase, answer shape, and optional schema-v1 recovery
  instruction agree. A non-terminal display phase is the source phase. A
  terminal safeguard display phase is accepted only when
  `phase_dispatch_limit_phase` or `last_dispatch.phase_id` identifies one
  exact non-terminal source phase for the matching current safeguard. A
  persisted instruction must identify that source phase and the exact current
  `await_human_answer` or `resolve_issue` behavior.
- Free-text provider and safeguard recovery accepts no legacy options.
  Dispatch-cap recovery accepts only the complete canonical, evidence-backed
  issue-option shape already required by its current handler.
- A restarted controller re-resolves the current policy from the sealed
  producer, reason, and source phase before deriving the same exact alias; the
  alias is never installed in the compiled registry.
- Unknown legacy reasons, terminal phases without a registered handler, or
  malformed options remain on the current manual recovery path.
- Existing resolved schema-v1 decisions are not rewritten.
- States identified as `run_kind: re` are never adapted.
- Persisted v1 `AWAIT_HUMAN_ANSWER` and `RESOLVE_ISSUE` instructions retain
  their current CLI behavior unless the same state is safely adapted to a v2
  decision.
- The current `ensure_blocked_decision(...)` helper never replaces a schema-v2
  record. It remains available for RE and legacy writes, but the new provider
  advance supplies its v2 decision explicitly and bypasses v1 synthesis.

## Implementation Surface

Create:

- `src/harness/human_input.py`: request/option types, policy registry, and
  validation.

Modify:

- `src/harness/blocked_decision.py`: add Squad schema-v2 validation while
  retaining schema-v1 helpers for RE and legacy runs.
- `src/harness/recovery_instruction.py`: add `resolve_decision` and schema-v2
  decision binding while preserving schema v1.
- `src/harness/echelon_result_schema.py` and
  `src/harness/prepared_phase_result.py`: require `STOP_AND_ASK` for
  question-bearing results, validate recommendation/risk ingress, and expose
  the validated fields to controller preparation.
- `src/harness/squad.py`: add the single interception, pending-resolution, and
  application methods; replace both duplicated escalation branches.
- `src/harness/squad_executors.py`: remove `HumanGateExecutor`; no executor may
  call `input()` or implement autonomy policy.
- `src/harness/squad_state.py`: add dedicated CAS methods for sealing, claiming,
  resolving, and failing a decision plus the shared unlocked seal primitive and
  provider-advance argument. Generic `save` must not mutate an unresolved
  schema-v2 decision.
- `src/harness/phase_graph.py`, `src/harness/workflow_validator.py`, and
  `extension/workflow/definition.yaml`: compile and statically validate exact
  `human_input` policies, context allowlists, gate options/outcome edges, and
  provider reason codes.
- `extension/workflow/phases/phase1-tracker.md`,
  `extension/workflow/phases/phase1-why1.md`,
  `extension/workflow/phases/phase1-why2.md`,
  `extension/workflow/phases/phase1-investigate.md`,
  `extension/workflow/phases/phase2-tracker-alignment.md`, and their shared
  TRACKER, SAGE, and INVESTIGATOR agent prompts: emit the exact registered
  reason/risk fields and canonical `STOP_AND_ASK` results.
- `src/echelon/cli.py` and `src/echelon/cli_app.py`: route status, continue, and
  resume through the controller methods.
- `extension/agents/control/commander.md`: document the strict resolution
  contract and remove direct file/state ownership for this path.
- `extension/commands/echelon.resume.md`: describe the shared controller flow.

No provider adapter, Docker, usage ledger, workflow bundle, spec lifecycle, or
completion module is in this implementation surface.

## Verification

Unit tests:

- exact request and option validation;
- complete policy-registry coverage for every current producer;
- workflow context-key/path validation and the 32 KiB context bound;
- rejection of unregistered questions;
- Guided/Semi/Banzai/external-prerequisite mode matrix;
- Semi recommendation and risk rules;
- strict COMMANDER result validation;
- schema-v1 compatibility and schema-v2 decision/instruction pairing;
- provider advance atomically sealing v2 without schema-v1 synthesis;
- stale revision, wrong decision id, invalid option, and invalid graph target;
- interrupted `resolving` recovery, retry-once, and manual-diagnosis behavior;
- idempotent clarification append;
- each registered resolution handler;
- generic-save protection for unresolved decisions.

Integration tests:

- provider escalation through both initial inline handling and process restart;
- both human gates in all three modes;
- checkpoint-plan remains Semi-auto and checkpoint-assess remains Semi-human;
- Banzai gate resolution calls COMMANDER and can approve or reject;
- each gate option maps to one declared workflow outcome edge;
- investigation access requirement reaches the human even in Banzai;
- dispatch cap, repeated WHY failure, and stagnation safeguards;
- interruption after decision persistence and during COMMANDER resolution;
- `status`, `continue`, and `resume` use the same durable decision id;
- manual phase/override paths cannot bypass an unresolved decision;
- legacy Squad escalation adapts only when registered;
- RE schema-v1 behavior remains unchanged.

Static checks:

- no `input()` remains in Phase A Squad executor/controller paths;
- `HumanGateExecutor` and its executor registration are absent;
- no producer renders an escalation question before
  `handle_human_input(...)`;
- every question-bearing provider result uses `STOP_AND_ASK`, not `ESCALATE`;
- only `apply_human_input_resolution(...)` clears a schema-v2 decision;
- every workflow producer that permits `escalation_question` has one registry
  entry;
- the implementation diff does not touch the explicitly excluded subsystems.

## Planning Boundary

This is one plan-sized change with three implementation units:

1. Types, registry, durable schema, and state-store CAS operations.
2. Controller interception, mode policy, COMMANDER contract, and handlers.
3. Workflow/CLI migration, compatibility adapters, and end-to-end tests.

The plan must preserve this boundary. Any discovered requirement to redesign
provider execution, accounting, run lifecycle, workflow authority, or
completion is a separate design finding, not an expansion of this work.
