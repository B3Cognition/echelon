# Design: Autonomy Decision Resolution

**Date:** 2026-07-27
**Status:** Corrected draft - implementation contracts reconciled with recovery and completion

## Problem

Squad has several paths that create or imply a human decision: agent
escalations, `human_gate`, phase-dispatch caps, and quality/convergence
guards. They currently use a mixture of `escalation_*` fields, direct blocked
state writes, auto-approval, and CLI prose heuristics. Banzai only intercepts
some of them.

Echelon already has two relevant durable contracts:

- `blocked_decision`, a typed decision record built from escalation fields and
  consumed by Squad and RE resume flows;
- `recovery_instruction`, a controller-owned, versioned description of the
  next action for a blocked Squad run.

The design extends those contracts. It does not create a second decision state
model and does not permit a provider to write controller-owned state.

## Scope

This change governs Phase A Squad decisions only. RE continues to use
`blocked_decision` v1 and ignores additive v2 fields. No RE autonomy policy,
COMMANDER dispatch, or resume behavior changes in this work.

All new Squad decision policy is controller-owned. Provider output is only
validated escalation input. The controller decides whether it is a decision,
how it is classified, and whether COMMANDER or a human resolves it.

## Goals

1. Every Squad request for a project decision reaches one controller resolver.
2. Guided, semi, and banzai have deterministic, distinct policy.
3. A persisted decision survives interruption without duplicate COMMANDER
   resolution or stale-result application.
4. `status`, `continue`, and `resume` consume the same typed recovery action.
5. Dispatch-cap and SAGE issue recovery retain their current evidence-backed
   safeguards.

## Non-goals

- Changing ordinary deterministic recovery such as provider waits or runtime
  synchronization.
- Treating unavailable credentials, external resources, or legal authority as
  decisions COMMANDER may invent or assume.
- Broadening RE behavior through the shared `blocked_decision` helper.

## Architecture

```
agent / gate / controller safeguard
                |
                v
  constrained escalation input (legacy-compatible)
                |
                v
  SquadController seals blocked_decision v2
                |
                v
  recovery_instruction v2
       |                         |
       v                         v
human resume             COMMANDER decision resolver
       |                         |
       +------------+------------+
                    v
      controller-validated operation + audit
```

There is exactly one active `blocked_decision` per Squad run. Resolved
decisions are appended to bounded controller-owned `decision_history` before
the active record may be replaced. A decision is not completed by writing a
route, clearing a question, or setting a status field. It is completed only
when the controller validates and atomically applies a permitted operation.

## Provider Ingress and Controller Ownership

Providers retain the existing escalation input surface:
`status: blocked`, `blocked_reason`, `escalation_question`, optional
`escalation_options`, and optional recommendation/risk hints. These are input
facts, not durable authority. A result contract must explicitly opt into this
surface with `allows_human_decision: true`. The provider's free-form
`blocked_reason` is a sanitized diagnostic hint only; the selected policy case
supplies the controller-owned durable reason code.

An `execution_blocked` case additionally requires exact provider ingress:

```yaml
echelon_result:
  escalation_prerequisite:
    capability_key: source_repository_read
    diagnostic_code: permission_denied
    diagnostic: "Repository access was denied by the configured provider."
```

`escalation_prerequisite` is a top-level decision-ingress field, not a
`state_updates` key. Its three fields are exact. `capability_key` and
`diagnostic_code` are non-empty enum-like strings of at most 128 characters;
`diagnostic` is a non-empty string of at most 2,000 characters. The object is
validated but not applied as phase state. It is accepted only when the
selected decision case is `execution_blocked`.

The controller accepts that input only when it can map the producing phase or
controller safeguard to a declared `decision_policy`. It then creates the
transaction-owned `blocked_decision` and `recovery_instruction` in the same
state advance. Providers and COMMANDER cannot write either record directly.

An input with no declared policy is a controller validation failure. Because
no valid v2 decision can be sealed without a policy, the controller persists
the existing non-decision v1 `manual_diagnosis` recovery instruction with a
redacted `invalid_decision_policy` diagnostic. It must not synthesize a v2
decision, downgrade the request to `material`, or permit banzai to choose.

## Workflow Decision Policy

`allows_human_decision` is the standard producer marker. It is a boolean field
on the exact result contract and defaults to false. When false, result
validation rejects `escalation_question` for every verdict, including the
current `BLOCKED` fast path. When true, the dispatch must declare
`decision_policy`, `escalation_question` is permitted, and `STOP_AND_ASK` may
be included in `allowed_verdicts`. Conversely, allowing `STOP_AND_ASK` requires
`allows_human_decision: true`.

This requirement is independent of verdict: both `STOP_AND_ASK` and `BLOCKED`
may carry a human question only through the marked contract. For a simple
agent phase the marker and policy are `PhaseNode` fields. For `agents[]` and
`pre_dispatch[]`, both are declared on the concrete nested entry, just like
nested `allowed_state_updates`. Nested entries do not inherit either value
implicitly.

Controller-generated producers use a closed Python registry keyed by exact
`blocked_reason` rather than workflow YAML. The initial registry covers
`phase_dispatch_limit`, `consecutive_why_fails`, and
`why2_metric_stagnation`. Unknown reasons are invalid policy, not a generic
decision.

```yaml
allows_human_decision: true
decision_policy:
  cases:
    - id: default
      when: always
      reason_code: human_clarification_required
      classification: material
      allowed_operations:
        - record_clarification
      context_pack:
        - spec.md
        - staging/quality-gates.md
      prerequisite_verifier: null
```

A policy contains an ordered, non-empty list of exact cases. Every case has a
`reason_code` matching `[a-z][a-z0-9_]{0,127}`. This code becomes
`blocked_decision.source_reason_code`, the durable `blocked_reason`, and the
matching recovery instruction `reason_code` while the decision is pending,
resolving, or awaiting human input. It is part of the policy digest.
Classification and durable reason are never inferred from an agent-provided
risk label or free-form `blocked_reason`.

`when` uses the existing condition grammar but may reference only `verdict` and
fields declared by that dispatch's result contract. Every referenced state
field must be in `allowed_state_updates` and `state_update_types`; fields used
in categorical comparisons must also have a closed `state_update_enums`
declaration. For a question-bearing result, every referenced field is required
even if the ordinary verdict path would not require it.

The controller evaluates cases against an immutable decision-case view built
only from the normalized detached result's `state_updates`, with the detached
result supplied separately for `verdict` expressions. It never falls back to
persisted Squad state. Exactly one case must evaluate true; an unrecognized
condition, missing discriminator, zero matches, or multiple matches is invalid
policy. Case order affects the policy digest but does not resolve overlapping
matches.

A case defines one classification, an operation-family allowlist, context
pack, and optional prerequisite verifier. The YAML names families only; the
controller materializes exact tagged operation descriptors from the compiled
policy, validated escalation options, graph edges, verifier registry, or
safeguard registry before sealing.

A simple agent phase uses its phase policy. A case may restrict valid option
ids. Nested agent entries always use their own policy. Agent-originated cases
may expose only `record_clarification`, `continue_current_phase`, or
`record_prerequisite`; they cannot expose direct route or issue-selection
operations because their prepared phase effects are deliberately not
persisted.

`PhaseGraph` parses `decision_policy` into an immutable compiled policy with a
stable `dispatch_key` and static `policy_digest`, attached to the exact dispatch
contract. A nested executor that returns a decision-bearing result wraps it in
trusted `ExecutorDecisionResult`, analogous to the existing
`ExecutorBlockedResult`. The wrapper contains the detached
`SquadAgentResult`, `dispatch_key`, and `policy_digest`; provider output cannot
set these fields. Simple phase and gate executors use the same wrapper.

Preparation verifies the wrapper against the compiled graph and seals
`dispatch_key` and `policy_digest` into `PreparedPhaseResult` attestation. The
controller selects policy only from this attested identity, never by trying to
infer which nested entry returned a plain result. A mismatch is an executor
contract failure and uses the existing non-decision recovery path.

`policy_digest` is SHA-256 over canonical JSON containing only recomputable
static authority: the dispatch key, normalized cases, operation-family
templates, context paths, exact declared transition metadata, verifier ids,
registered recovery-route ids and mappings, and a controller-owned
`decision_operation_semantics_version`. It never contains provider options,
issue candidates, answers, or other dispatch-time material. Controller-
safeguard registry entries use the same canonical form. Mapping keys are
sorted, arrays preserve declared order, and paths and enum strings are
normalized before hashing.

After validating a decision-bearing result, the controller materializes the
exact concrete operation descriptors once and computes `operations_digest` as
SHA-256 over their canonical JSON array in sealed order. This second digest
binds fixed provider options, generated-operation descriptors, verifier
arguments, and immutable issue evidence. It is stored with the active decision
and its history summary. Recomputing `operations_digest` uses only the sealed
descriptors; it never rereads provider output, `issues.md`, or another mutable
source.

Decision ingress has a dedicated validation preflight inside
`validate_echelon_result_contract`. It runs after the base envelope and verdict
allowlist checks but before the existing `BLOCKED` fast path and before ordinary
state-update quarantine:

1. With `allows_human_decision: false`, any non-empty
   `escalation_question` is rejected for every verdict.
2. With `allows_human_decision: true`, a question-bearing result requires exact
   `status: blocked`, a non-empty diagnostic `blocked_reason`, a non-empty
   bounded question, valid bounded options, and all case discriminator fields.
   Every decision-ingress state key must be present in that dispatch's explicit
   allowlist.
3. The preflight validates the discriminator types and enums, selects exactly
   one policy case from the detached decision-case view, then validates
   `escalation_prerequisite` against that case.
4. Only a non-question `BLOCKED` result may then take the legacy fast path.
   Question-bearing `BLOCKED` and `STOP_AND_ASK` results complete the remaining
   dispatch-contract validation and only then continue to decision sealing.

`escalation_prerequisite` and any future top-level decision-ingress fields are
validated by this preflight; ordinary top-level provider extras do not become
decision authority.

Every provider-originated result, including direct and nested `BLOCKED` and
`STOP_AND_ASK`, must pass `validate_echelon_result_contract` with its exact
compiled dispatch contract. The current raw `validate_echelon_result` blocking
branch in `PhaseExecutor._validate_result_state_updates` is removed. Base-
envelope-only validation remains available solely for a controller-created
non-question `ExecutorBlockedResult`; that trusted envelope rejects every
`escalation_*` field and cannot enter decision sealing.

Before every claim, human confirmation, prerequisite submission, and apply,
the controller recompiles the current workflow or registry entry and compares
its static `policy_digest` with the active decision. It separately recomputes
`operations_digest` from the persisted descriptors and validates every selected
descriptor against the current edge, verifier, and recovery-route registries.
A missing producer, either digest mismatch, incompatible descriptor, or
operation-semantics version change atomically fails the v2 decision with audit
code `decision_policy_changed` and decision-related v2 `manual_diagnosis`. It
never executes an old descriptor under new handler semantics and never rereads
mutable evidence to make an old decision current. Existing extension drift
warnings remain informational for runs without an active v2 decision; an active
decision always uses this fail-closed check.

`workflow_validator` rejects a `human_gate`, a marked dispatch, or a registered
controller producer with a missing/malformed policy, unknown operation,
invalid context path, or operation that cannot apply to one of the source
phase's declared transitions. It also rejects `STOP_AND_ASK` without the
marker, the marker without a policy, and `escalation_question` in ordinary
`allowed_state_updates` when the marker is false.

The existing generic COMMANDER routing judgment is not a decision producer and
cannot recursively escalate. Its current static contract is split:

- `ROUTING_JUDGMENT_RESULT_CONTRACT` retains routing intent only. It has
  `allows_human_decision: false`, rejects every `escalation_*` field, and
  accepts only `JUDGMENT_RESOLVED`.
- `DecisionResolutionContract` owns all v2 decision resolution.
- `LEGACY_BANZAI_ESCALATION_RESULT_CONTRACT` retains the old cleanup fields only
  when resuming a pre-v2 active decision.

The COMMANDER instructions remove the rule that existential routing judgments
may preserve `escalation_question`. If an ordinary routing judgment cannot
select a contract-valid route, its result fails the routing contract and the
controller atomically installs non-decision v1 `manual_diagnosis`; there is no
second generic `BLOCKED` interpretation. A v2 COMMANDER resolver must select one
sealed operation or fail boundedly; it cannot request another COMMANDER or a
human. The sole banzai-to-human exception remains a decision already classified
`execution_blocked` by its source policy and verifier.

`execution_blocked` policies require a named `prerequisite_verifier`. YAML may
contain only an enum-like verifier id. A closed Python registry maps that id to
a deterministic controller function; YAML cannot provide a shell command,
module path, callable, or arguments. The provider supplies a declared
capability key and observed diagnostic; the controller runs the verifier. Only
a failed verification can create a human prerequisite request. Missing,
malformed, or unverifiable evidence becomes `manual_diagnosis`, not an
execution blocker.

## Existing Producer Policy

The initial workflow migration is closed and explicit:

| Producer or case | Durable reason code | Classification | Allowed operation | Resolution effect |
|---|---|---|---|---|
| `phase1-tracker` | `human_clarification_required` | material | `record_clarification` | record answer, redispatch `phase1-tracker` |
| `phase1-why1` | `human_clarification_required` | material | `record_clarification` | record answer, redispatch `phase1-why1` |
| `phase1-why2` provider question | `human_clarification_required` | material | `record_clarification` | record answer, redispatch `phase1-why2` |
| `phase1-investigate`, `evidence_resolution_status = inconclusive` | `human_clarification_required` | material | `record_clarification` | record answer, redispatch `phase1-investigate` |
| `phase1-investigate`, `evidence_resolution_status = access_required` | `investigation_access_required` | execution_blocked | `record_prerequisite` | verify prerequisite, redispatch `phase1-investigate` |
| `phase2-tracker-alignment` | `human_clarification_required` | material | `record_clarification` | record answer, redispatch `phase2-tracker-alignment` |
| `checkpoint-assess` | `checkpoint_assess_decision_required` | material | `approve_gate`, `reject_gate` | follow the declared gate edge |
| `checkpoint-plan` | `checkpoint_plan_decision_required` | operational | `approve_gate`, `reject_gate` | follow the declared gate edge |
| `phase_dispatch_limit` | `phase_dispatch_limit` | material | `select_evidence_backed_issue` | apply exact sealed issue decision and registered repair route |
| `consecutive_why_fails` | `consecutive_why_fails` | material | `select_evidence_backed_issue` | apply exact sealed issue decision and registered repair route |
| `why2_metric_stagnation` | `why2_metric_stagnation` | material | `select_evidence_backed_issue` | apply exact sealed issue decision and registered repair route |

The investigator policy has two mutually exclusive cases selected from its
validated `evidence_resolution_status`. Its `access_required` case also
requires the `investigation_access` verifier and
`escalation_prerequisite`. Any future question producer must be added to this
matrix and workflow policy in the same change; merely adding
`escalation_question` to an allowlist fails workflow validation.

## Human Gate Interception

`HumanGateExecutor` no longer reads stdin and no longer branches on autonomy.
If no matching gate decision has been applied, it returns a deterministic
`ExecutorDecisionResult` whose detached result is:

```yaml
echelon_result:
  verdict: STOP_AND_ASK
  state_updates:
    status: blocked
    blocked_reason: human_gate
    escalation_question: "Approve or reject <gate label>?"
    escalation_options:
      - id: approve
        label: Approve
      - id: reject
        label: Reject
```

The ordinary phase-result preparation path validates this result and hands it
to the same controller policy resolver as an agent escalation. This is the
single gate interception point; the executor never invokes COMMANDER or a
human itself.

Each gate transition declares exact metadata
`decision_outcome: approved | rejected`. Successful `approve_gate` or
`reject_gate` resolution validates that the descriptor's transition index,
target, and outcome match that metadata, then routes through the attested
prepared decision. No gate outcome is written to general state; the resolved
decision and history are the durable record. All direct `autonomy = banzai`,
`autonomy in [semi, banzai]`, and `human_approved` bypass conditions are
removed. Because the outcome exists only in the sealed operation and matching
edge metadata, it cannot satisfy a later gate or be replayed after restart.

Both outcomes must have declared transitions. `checkpoint-assess` is material
because semi already requires human review there. `checkpoint-plan` is
operational because semi currently auto-proceeds there. Each receives an
approve transition to its current next phase and an explicit rejected
transition to `terminal-blocked`; no unmatched reject result is permitted.
`workflow_validator` requires exactly one `approved` and one `rejected`
`decision_outcome` edge for every human gate, rejects this metadata on
non-gate transitions, and rejects autonomy or `human_approved` conditions on a
gate.
Rejection marks the decision resolved, appends its history entry, sets run
status to `blocked`, writes terminal `blocked_reason: gate_rejected`, advances
to `terminal-blocked`, and clears the decision-related recovery instruction
atomically. It does not create another question or a decision-related recovery
loop.

## Interception Order

Decision interception is part of result preparation and precedes all ordinary
routing. For every full-run and manual-phase dispatch, the controller performs
these steps in order:

1. create one attempt-local `ProviderArtifactTransaction` for the entire phase
   execution, including its nested and staged dispatches;
2. detach and validate each result against its exact dispatch contract;
3. verify and attest its executor-supplied dispatch identity;
4. if a validated result contains a non-empty `escalation_question`, seal the
   v2 decision and matching recovery instruction in one CAS state advance;
5. discard the complete phase artifact transaction and return to the autonomy
   resolver without preparing external publication,
   evaluating ordinary transitions, recording phase completion, or applying
   provider or controller-certificate state updates;
6. only a complete phase execution with no decision request may seal its
   artifact transaction into the existing external-effects and routing
   pipeline.

The same ordering applies to `BLOCKED` and `STOP_AND_ASK`. Controller safeguards
enter at sealing step 4 through their closed registry and use no provider
artifact transaction. No transition may advance around
the resolver because a question-bearing prepared result never reaches ordinary
transition evaluation.

A question-bearing agent result is a proposal to stop, not a partially
committable phase result. All ordinary provider updates, controller-contract
updates, output certification, publication preparation, completion intent, and
all peer or earlier-stage artifacts from the same phase attempt are discarded
after the decision ingress fields and case discriminator have been sealed.
They are never serialized into `blocked_decision`. After a clarification or
prerequisite resolves, the controller projects the answer, redispatches the
exact source phase, and requires the new result and artifacts to pass their
contracts again.

`ProviderArtifactTransaction` is a controller-owned output boundary, not a
best-effort cleanup pass. A marked phase and every marked nested dispatch must
have a complete normalized `outputs` declaration. The workflow validator
rejects absolute paths, parent traversal, overlapping ownership, undeclared
write roots, and a marked dispatch whose outputs cannot be redirected. Before
provider execution, the controller creates a private attempt workspace under
the run directory, seeds declared inputs, substitutes output placeholders with
attempt-local paths, and gives provider tools write access only to that
workspace. Canonical Squad, spec, and source-root artifacts are read-only to the
attempt. Nested and staged dispatches share the phase transaction so no peer
output is promoted early.

After a complete non-question phase result passes result, artifact, and
controller-contract validation, the transaction prepares an exact promotion
manifest containing destination paths, preimage hashes, staged hashes, and the
dispatch identity. Promotion joins the existing prepared external-effects
protocol and occurs only under its state/publication binding. A changed
destination preimage is stale state and rejects promotion without overwriting
the newer artifact. A decision request, provider failure, invalid result, stale
state, or abandoned prepared route calls `discard()` and removes the private
workspace. No provider process in a marked phase receives a writable canonical
output path, so a discarded decision attempt cannot influence later context
reconciliation or redispatch.

Consequently, agent-originated policies cannot route directly from the stopped
result. Gates have no provider effects and may route through their exact gate
descriptor. Controller safeguards construct their operations entirely from
controller-owned state and sealed evidence, so they may use their exact repair
edge without replaying a provider result.

## Blocked Decision v2

`blocked_decision` v2 is the controller-owned durable record for Squad. It
extends v1 rather than replacing it:

```yaml
blocked_decision:
  schema_version: 2
  id: "dec-<random-token>"
  status: pending | resolving | awaiting_human | resolved | failed
  source: phase | human_gate | controller_safeguard
  source_phase: phase1-what
  source_reason_code: human_clarification_required
  dispatch_key: "phase1-what/agents/chief-product-owner"
  policy_digest: "<sha256>"
  operations_digest: "<sha256>"
  invocation_kind: full_run | manual_phase
  classification: operational | material | execution_blocked
  created_at: "<UTC timestamp>"
  question: "..."
  allowed_operations:
    - id: approve
      kind: approve_gate
      label: "Approve the checkpoint"
      transition_index: 0
      target_phase: phase2-decide
      outcome: approved
  recommended_operation_id: null
  recommended_answer_text: null
  selected_operation_id: null
  answer_text: null
  resolved_by: null
  resolved_at: null
  failure_code: null
  resolution_attempts: 0
  resolution_lease_id: null
  resolution_lease_expires_at: null
  audit: []
```

The controller assigns a cryptographically random id and the source,
`source_reason_code`, classification, operations, attempt count, and audit
fields. The source reason comes only from the selected compiled policy case.
Phase and gate decisions require the attested `dispatch_key` and
`policy_digest`. `operations_digest` binds the exact materialized
`allowed_operations`. `invocation_kind` comes from the controller entrypoint,
never provider state. Controller-safeguard decisions use a registry key and
registry digest in the dispatch and policy fields. The controller may derive
question text and legacy display options from provider input, but it never
treats provider-provided `blocked_reason` or `next_phase` as lifecycle or
operation authority.

All shown v2 fields are exact and required; nullable fields use explicit null
rather than omission. Status-specific validation controls which nullable
fields may be populated.

`decision_history` is a controller/store-owned transaction key containing at
most 50 exact, sanitized resolution summaries:

```yaml
decision_history:
  - schema_version: 1
    decision_id: dec-<random-token>
    source: phase | human_gate | controller_safeguard
    source_phase: phase1-what
    source_reason_code: human_clarification_required
    dispatch_key: "phase1-what/agents/chief-product-owner"
    policy_digest: "<sha256>"
    operations_digest: "<sha256>"
    invocation_kind: full_run | manual_phase
    classification: operational | material | execution_blocked
    final_status: resolved | failed
    resolver: COMMANDER-banzai | COMMANDER-semi | human | controller
    selected_operation_id: approve | null
    selected_operation_kind: approve_gate | record_clarification | null
    question: "sanitized question"
    answer_preview: "sanitized audit preview" | null
    failure_code: null | decision_policy_changed | resolution_attempts_exhausted | operation_precondition_failed | clarification_ledger_full
    completed_at: "<UTC timestamp>"
    audit: []
```

Every history entry has exactly these nineteen fields. String enums and digest
formats use the active-decision validators. `question`, `answer_preview`, and
every audit free-text value are sanitized and truncated to 2,000 characters;
history is an audit summary and is never authoritative clarification context.
`audit` contains at most 20 entries with exactly:

```yaml
schema_version: 1
event: sealed | claimed | retry_scheduled | recommended | human_submitted | prerequisite_checked | applied | failed
at: "<UTC timestamp>"
resolver: COMMANDER-banzai | COMMANDER-semi | human | controller | null
lease_id: "<lease id>" | null
operation_id: "<operation id>" | null
rationale: "sanitized text" | null
assumptions: []
diagnostic_code: "<closed code>" | null
```

`assumptions` follows the COMMANDER count and string bounds. The initial closed
diagnostic codes are `invalid_contract`, `provider_timeout`,
`provider_failure`, `prerequisite_missing`, `decision_policy_changed`,
`resolution_attempts_exhausted`, `operation_precondition_failed`, and
`history_integrity_failed`, plus `clarification_ledger_full`. A stale result
has no authority to append audit.

Successful or failed terminal resolution appends one history entry in the same
transaction that updates the active decision. Append is idempotent by
`decision_id`: an identical existing entry is a no-op, while a different entry
with the same id is a controller integrity failure. Appending the fifty-first
removes the oldest. A later decision may replace the active resolved record
only after its summary is present in `decision_history`; pending, resolving,
or awaiting-human records may never be replaced. Malformed persisted history
blocks all decision methods. The existing snapshot-bound failure recovery path
preserves the malformed value byte-for-byte and persists non-decision v1
`manual_diagnosis`; history is never silently repaired or dropped.

`decision_clarifications` is a separate controller/store-owned semantic ledger:

```yaml
decision_clarifications:
  - schema_version: 1
    decision_id: dec-<random-token>
    source_phase: phase1-what
    question: "sanitized question"
    answer_text: "sanitized effective answer"
    resolver: COMMANDER-banzai | COMMANDER-semi | human
    completed_at: "<UTC timestamp>"
```

Each entry has exactly the seven shown fields, is unique by `decision_id`, and
preserves sanitized question and effective answer text up to the decision
limits of 4,000 characters. Only a successful `record_clarification`
application appends it, in the same transaction that resolves the decision.
The semantic sanitizer applies the same secret-replacement rules as audit but
uses the 4,000-character decision bounds; it does not apply the 2,000-character
audit-preview truncation.
The ledger permits at most 500 entries and 2 MiB of canonical JSON. An append
that would exceed either bound fails the decision with
`clarification_ledger_full` and matching manual diagnosis; entries are never
evicted or truncated to make room.

`state_transaction_namespace` registers `decision_history`,
`decision_clarifications`, `blocked_decision`, and `recovery_instruction` as
store-owned transaction keys. These keys may be changed only by the exact
`SquadStateStore` decision methods below or by an attested prepared routing
decision applying a resolved operation. They are never added to provider
control intents, generic queued updates, or phase `allowed_state_updates`. Gate
outcomes do not require a new state key.

## Durable Store Operations

Decision lifecycle writes use four dedicated store APIs. Each validates exact
input types before locking, acquires the existing exclusive state lock,
matches phase, `state_revision`, previous-dispatch digest, active decision id,
expected status, and lease identity as applicable, increments
`state_revision`, and uses the existing atomic state-file replacement. A CAS
mismatch returns a stale outcome without mutation.

- `seal_decision(snapshot, prepared_identity, decision, instruction)` accepts
  only a newly validated decision-bearing prepared result or a registered
  controller safeguard. It archives an existing resolved/failed active record
  if necessary, then writes the new active decision, recovery instruction, and
  blocked lifecycle state. It does not update `last_dispatch` or phase
  completion.
- `claim_decision(snapshot, decision_id)` accepts only `pending` or an expired
  `resolving` decision below its attempt limit. It writes `resolving`,
  increments attempts, and installs a new random lease and expiry. It does not
  route.
- `settle_decision(snapshot, decision_id, lease_id, outcome)` handles
  state-only transitions to `pending`, `awaiting_human`, or `failed`, including
  recovery-generation replacement, lease clearing, audit append, and
  idempotent history append for failure. It cannot change phase.
- `apply_decision(snapshot, decision_id, expected_lease_id, operation,
  prepared_route, completion_marker)` accepts only controller-prepared,
  mutually attested application artifacts. It revalidates the sealed operation,
  static policy digest, concrete operations digest, current workflow edge or
  registered recovery route, exact transaction effects, completion-marker
  binding, and absence of an older pending publication or completion under the
  state lock. It then performs the same-phase redispatch, gate edge, or
  safeguard repair through the single state-advance commit primitive while
  atomically resolving the decision, applying the operation-specific run-status
  effect, and installing the pending completion marker.
  Human resolutions use `expected_lease_id: null` and require
  `awaiting_human`; COMMANDER resolutions require the current lease.

No decision path calls generic `SquadStateStore.save`. State-only methods do
not fabricate `last_dispatch`; phase-changing or redispatch operations always
use the existing prepared-routing attestation and advance path. Failed
application preconditions settle the decision as failed rather than falling
back to an inferred route.

There is exactly one routing commit implementation. The existing body of
`SquadStateStore.advance` is factored into private
`_advance_unlocked(current_state, prepared_route, transaction_effects)`.
Public `advance` performs its existing input validation, acquires the exclusive
lock, performs its current CAS checks, and calls that primitive. `apply_decision`
performs its stricter decision validation, acquires the same lock once, checks
decision and lease preconditions against that loaded state, and calls the same
primitive with controller-owned lifecycle effects. The private method neither
locks nor accepts provider-controlled transaction keys. No decision method
calls public `advance` while holding the lock and no second implementation may
construct `last_dispatch`.

Before `apply_decision`, `SquadController` performs a visible-effect-free
`prepare_decision_application` staging step:

1. Build a synthetic controller result containing no provider state effects.
2. Build an attested `PreparedRoutingDecision` with
   routing source `decision_resolution`, `increment_iteration: false`, and the
   operation-specific completion flags below.
3. Call the existing `_prepare_controller_completion` before the authorizing
   state write. Its route retains the current exact
   `from_phase`/`to_phase`/`manual_phase_run`/`record_completion` shape. The
   normalized judgment record contains the decision id and operation id, so the
   existing `judgment_payload_sha256` binds them into the completion intent.
   The prepared routing decision separately binds state revision, route, and
   completion id. The judgment record contains only controller-owned decision
   audit data; it never contains raw human input, raw provider output, or
   context-pack contents.
4. Pass the prepared route and marker to `apply_decision`, which rejects any
   mismatch rather than rebuilding either artifact under the lock.

The prepared completion remains caller-owned until `apply_decision` returns a
committed receipt. Every stale outcome, validation exception, failed operation
precondition, or state-write failure calls
`PreparedControllerCompletion.discard()` in `finally`. A committed receipt
transfers ownership to the durable pending marker, after which normal completion
drain owns cleanup.

The state advance writes `pending_controller_completion` and a
`last_dispatch` with `post_dispatch_complete: false` in the same transaction
that resolves the decision. The controller drains that completion before
clarification projection or redispatch. Restart and `spec continue` drain an
existing completion before claiming another decision or dispatching an agent.
Successful drain marks the dispatch complete through the current completion
protocol. Source-phase completion follows the route's sealed
`record_completion` value: true only for gate outcomes and false for replay and
safeguard operations.

A completion failure uses the existing standard controller-completion recovery
generation. It does not reopen the resolved decision or dispatch COMMANDER a
second time. After completion recovery succeeds, the controller follows the
operation-specific continuation behavior below.

Operation application has two closed continuation behaviors:

- Replay-source operations are `continue_current_phase`,
  `record_clarification`, and `record_prerequisite`. Their synthetic route has
  `record_completion: false` and `manual_phase_run: false`. After completion
  drain and clarification projection, `full_run` re-enters the normal loop at
  `source_phase`; `manual_phase` calls the locked single-phase path for
  `source_phase` exactly once and returns after that real dispatch.
- Route-and-finish operations are `approve_gate`, `reject_gate`,
  `route_declared_transition`, and `select_evidence_backed_issue`. They do not
  redispatch the source. Gate operations use `record_completion: true`;
  safeguard route operations use `record_completion: false`. Their synthetic
  route uses `manual_phase_run: true` only when the durable invocation kind is
  `manual_phase`, because that operation is the real conclusion of the manual
  control point. A full run continues from the applied target; a manual run
  returns after completion drain.

Restart, `continue`, and `resume` derive this behavior from the persisted
operation and `invocation_kind`. Process interruption therefore cannot turn a
one-phase request into a full run, stop before a required source replay, or
replay a gate that has already been decided.

Migration rules:

1. Existing v1 records remain valid and are consumed unchanged by RE.
2. On a Squad write, a v1 pending decision is normalized once to v2 only when
   its original source phase or blocked reason resolves to a declared policy
   and its invocation kind is proven by the current sealing entrypoint or
   matching persisted manual-dispatch metadata. The conversion preserves its
   question, options, recommendation, blocked phase, timestamps, and v1 resume
   metadata, computes both digests from reconstructed static policy and
   concrete operations, but takes `source_reason_code` from the reconstructed
   compiled policy case. The same
   transaction replaces durable `blocked_reason` and recovery instruction with
   that controller-owned code. A v1 decision without reconstructable policy or
   invocation authority remains on the existing legacy compatibility path;
   conversion never guesses `full_run`.
3. The state helper must validate and preserve all v2 fields; it must not
   rebuild a v2 record from `escalation_*` fields on later saves.
4. Legacy `escalation_*` fields remain ingress and terminal-display
   compatibility projections until old active runs are no longer supported.

## Closed Controller Operations

`allowed_operations` is a sealed tagged union. Every member has exactly the
common fields `id`, `kind`, and `label`, followed by the exact fields for its
kind:

| `kind` | Additional exact fields | Controller meaning |
|---|---|---|
| `approve_gate` | `transition_index`, `target_phase`, `outcome: approved` | follow the exact edge declared with `decision_outcome: approved` |
| `reject_gate` | `transition_index`, `target_phase: terminal-blocked`, `outcome: rejected` | follow the exact edge declared with `decision_outcome: rejected` |
| `continue_current_phase` | `target_phase` equal to `source_phase` | clear a recoverable block and redispatch the source |
| `route_declared_transition` | `transition_index`, `target_phase` | follow one exact declared controller-safeguard edge |
| `record_clarification` | `answer_mode: generated \| fixed`, optional `fixed_answer_text` | record an answer and redispatch the exact source phase |
| `select_evidence_backed_issue` | `issue_id`, `exact_decision`, `evidence_sha256`, `repair_phase`, `recovery_route_id` | apply one controller-read, evidence-backed SAGE suggestion and its exact registered repair route |
| `record_prerequisite` | `verifier_id`, `capability_key`, `diagnostic_code` | accept human prerequisite input, rerun that exact verifier, and redispatch the source only after it passes |

All strings are trimmed and bounded by the general decision limits.
`transition_index` is a non-negative integer and must identify an edge whose
current `to` value equals `target_phase`. Gate descriptors additionally require
the indexed edge's `decision_outcome` metadata to equal the descriptor outcome
before the routing decision is sealed. A generated
clarification omits `fixed_answer_text` and requires resolver `answer_text`; a
fixed clarification requires `fixed_answer_text` and rejects resolver
`answer_text`. The controller normalizes each validated provider
`escalation_option` into a fixed clarification operation whose
`fixed_answer_text` is the option's normalized label; a free-text question
creates one generated clarification operation.

The controller computes one `effective_answer_text` and uses it everywhere:

- fixed clarification: the sealed descriptor's `fixed_answer_text`;
- generated clarification resolved by COMMANDER or guided human: the validated
  submitted `answer_text`;
- generated semi recommendation accepted without replacement: the persisted
  `recommended_answer_text`;
- generated semi recommendation replaced by the human: the validated
  replacement text.

The effective value, never the raw nullable resolver field, is written in full
to the active decision and `decision_clarifications`; history stores only its
bounded `answer_preview`. The clarification projection is rebuilt from
`decision_clarifications`.

Issue candidates and their evidence are read once when the decision is sealed.
`evidence_sha256` covers canonical JSON containing the issue id, exact
suggested decision, evidence basis, repair phase, and recovery route id.
`recovery_route_id` is resolved through the closed controller-safeguard
registry. The static registry id and mapping are included in `policy_digest`;
the selected route id and concrete evidence are included in
`operations_digest`. This preserves the current controller-override pattern for
dispatch caps, whose source phase may not have a workflow edge to the issue
repair phase. Apply recomputes the evidence digest from the sealed descriptor,
not from mutable `issues.md`, and verifies that the current registry maps the
route id to the same repair phase. A descriptor is rejected at seal time if any
target, verifier, candidate, workflow edge, or registered recovery route is
invalid.

No operation may contain a free-form `next_phase`, arbitrary state update,
shell command, module path, or unsealed issue decision. `answer_text` is
accepted only with a generated `record_clarification` and is limited to 4,000
characters after trimming. COMMANDER and the CLI select only an operation id;
they cannot supply or override operation parameters.

## Autonomy Policy

| Classification | guided | semi | banzai |
|---|---|---|---|
| operational | human selects an allowed operation | COMMANDER selects | COMMANDER selects |
| material | human selects an allowed operation | COMMANDER recommends; human confirms that option | COMMANDER selects and records assumptions |
| execution_blocked | human supplies the verified prerequisite | human supplies the verified prerequisite | human supplies the verified prerequisite |
| unknown/invalid | manual diagnosis | manual diagnosis | manual diagnosis |

For a semi material choice, human confirmation accepts only the recommended
operation id. For a semi material clarification, the human may accept the
bounded COMMANDER recommendation or, only for a generated clarification,
provide a bounded replacement answer for that same recommended operation id.
A fixed clarification accepts the exact recommended operation and rejects
replacement text.

CLI selection is deterministic. An explicit selection resolves by exact
operation id. An exact label is compatibility input only and is accepted when
it identifies exactly one allowed operation; zero or multiple matches are
invalid input. Bare free text is accepted only when the active decision has
exactly one generated `record_clarification`, or exactly one
`record_prerequisite`; it binds to that operation. Fixed clarification options
require an explicit id or unique exact label. For semi material clarification,
acceptance or replacement always binds to `recommended_operation_id`. No input
order, fuzzy label match, or first-operation fallback selects authority.
Prerequisite free text is a non-authoritative acknowledgment recorded only as
sanitized audit rationale; it is never an operation parameter and cannot make a
verifier pass.

## Recovery Instruction v2 and Idempotency

Recovery instruction v1 retains its current exact five fields and all existing
kinds. Schema version 2 is used only for decision-related instructions and has
exactly six fields:

```yaml
recovery_instruction:
  schema_version: 2
  kind: resolve_pending_decision | await_human_answer | manual_diagnosis
  reason_code: <current durable blocked_reason>
  phase: phase1-what
  requires_human_input: false
  decision_id: dec-<random-token>
```

The only v2 kinds are `resolve_pending_decision`, `await_human_answer`, and
`manual_diagnosis`. All require a non-empty `decision_id` matching the v2
record. For every unresolved or failed decision-related blocked v2 state,
`recovery_instruction.reason_code == state.blocked_reason`; a mismatch is an
invalid recovery generation and cannot drive routing.

For `pending`, `resolving`, and `awaiting_human`, both reason fields equal the
active decision's controller-owned `source_reason_code`.
`resolve_pending_decision` requires `requires_human_input: false`, a retryable
source phase, and decision status `pending` or `resolving`. Execution may claim
`pending`, reclaim expired `resolving`, or report an unexpired lease without
mutation; the persisted instruction remains valid in all three states.
`await_human_answer` requires `true` and status `awaiting_human`. On a terminal
decision-resolution failure, the controller atomically starts a new recovery
generation: it preserves `blocked_decision.source_reason_code`, sets both
durable reason fields to `decision_resolution_failed`, records the more
specific closed `failure_code` in the decision, and writes
`manual_diagnosis` with `requires_human_input: false`. Non-decision manual
diagnosis continues to use v1.

Sealing or settling a decision follows the existing recovery supersession
rule: remove diagnostics owned by the previous generation, write the new
durable reason and decision diagnostic, and replace the instruction in one
state transaction. Provider `blocked_reason` text may appear only as sanitized
audit context and never participates in the generation equality check.

The status, lease, recovery, and Squad run-status state machine is exhaustive:

| Event | Required pre-state | Decision post-state | Squad `status` | Durable `blocked_reason` | Lease fields | Recovery instruction |
|---|---|---|---|---|---|---|
| seal guided operational/material | no unresolved active decision | `awaiting_human` | `blocked` | source reason | null | `await_human_answer` |
| seal semi operational or semi material | no unresolved active decision | `pending` | `blocked` | source reason | null | `resolve_pending_decision` |
| seal banzai operational/material | no unresolved active decision | `pending` | `blocked` | source reason | null | `resolve_pending_decision` |
| seal execution-blocked in any mode | no unresolved active decision | `awaiting_human` | `blocked` | source reason | null | `await_human_answer` |
| claim | `pending`, attempts below maximum | `resolving`, attempts + 1 | `blocked` | source reason | new lease and expiry | `resolve_pending_decision` |
| reclaim expired lease | expired `resolving`, attempts below maximum | `resolving`, attempts + 1 | `blocked` | source reason | replace lease and expiry | `resolve_pending_decision` |
| valid COMMANDER operational or banzai material result | matching `resolving` lease | `resolved` through apply | operation-specific | operation-specific | clear | clear |
| valid semi material recommendation | matching `resolving` lease | `awaiting_human` with recommendation | `blocked` | source reason | clear | `await_human_answer` |
| invalid result, timeout, or provider failure below maximum | matching `resolving` lease | `pending` | `blocked` | source reason | clear | `resolve_pending_decision` |
| invalid result, timeout, or provider failure at maximum | matching `resolving` lease | `failed` | `blocked` | `decision_resolution_failed` | clear | `manual_diagnosis` |
| policy or operations digest mismatch | `pending`, `resolving`, or `awaiting_human` | `failed` | `blocked` | `decision_resolution_failed` | clear | `manual_diagnosis` |
| valid human choice/clarification | matching `awaiting_human` decision | `resolved` through apply | operation-specific | operation-specific | null | clear |
| valid prerequisite submission and verifier pass | matching `awaiting_human` prerequisite | `resolved` through apply | `running` | clear | null | clear |
| invalid human input | matching `awaiting_human` decision | unchanged | `blocked` | source reason | null | unchanged |
| prerequisite verifier still reports missing | matching `awaiting_human` prerequisite | unchanged with sanitized audit entry | `blocked` | source reason | null | unchanged |
| operation precondition, edge, or clarification-ledger failure | matching `resolving` lease or `awaiting_human` decision | `failed` | `blocked` | `decision_resolution_failed` | clear | `manual_diagnosis` |
| stale COMMANDER result | decision id, status, or lease does not match | unchanged | unchanged | unchanged | unchanged | unchanged |

The operation-specific status effect is closed: `approve_gate`,
`continue_current_phase`, `route_declared_transition`,
`record_clarification`, `record_prerequisite`, and
`select_evidence_backed_issue` require and atomically apply
`blocked -> running`. `reject_gate` requires `blocked`, keeps it `blocked`, and
routes to `terminal-blocked` with terminal `blocked_reason: gate_rejected`.
Every other successful operation clears the durable blocked reason. No
successful non-rejection operation may leave a resolved decision attached to a
blocked run.

Every transition to `pending`, `awaiting_human`, `resolved`, or `failed`
clears both lease fields. `resolution_attempts` counts only successful durable
COMMANDER claims; human submissions do not increment it. Before a claim, a
decision already at the maximum is failed without dispatch. Below the maximum,
the same controller invocation immediately makes the next CAS claim and retry;
if interrupted between attempts, `continue` resumes from the persisted
`pending` instruction.

When `spec continue` sees `resolve_pending_decision`, it invokes the controller
without clearing blocked state. The existing execution locks serialize local
controller entry but are not the decision lease. Claims and reclaims use
`claim_decision` exactly as defined above.

Decision resolution settings are explicit configuration with validated bounds:

```yaml
analysis:
  decision_resolution:
    max_attempts: 2       # allowed: 1..5
    lease_ttl_seconds: 3600  # allowed: 300..7200
```

These values belong to the existing top-level `analysis:` section. The
controller reads them through `get_full_resolved_config`, not `HarnessConfig`.
A dedicated parser applies defaults, rejects non-mappings and booleans used as
integers, and enforces the stated numeric bounds before a resolver claim.

A result applies only if its decision id, status, lease id, static policy
digest, concrete operations digest, and operation preconditions still match.
Stale results are discarded. Expired leases are reclaimable on the next inline
attempt or `continue`.

Inline resolution uses the same claim-and-apply path, so its crash behavior is
identical to `spec continue`.

## COMMANDER Contract

For non-human outcomes, COMMANDER receives only the sealed v2 decision, its
declared context pack, the user request, and its allowed operations. It returns
an exact top-level `decision_resolution` object:

```yaml
echelon_result:
  verdict: JUDGMENT_RESOLVED
  state_updates: {}
  decision_resolution:
    schema_version: 1
    decision_id: dec-<random-token>
    lease_id: <current durable lease id>
    operation_id: approve
    answer_text: null
    rationale: "..."
    assumptions: []
  journal_entries: []
```

`decision_resolution` has exactly the seven shown fields. `answer_text` is
either null or a trimmed non-empty string. It is required only for a generated
`record_clarification` descriptor and must be null for every fixed
clarification and every other operation kind. `rationale` is limited to 2,000
characters. `answer_text` is limited to 4,000 characters. `assumptions`
contains at most 20 non-empty strings of at most 1,000 characters each.
Decision questions are limited to 4,000 characters and a policy may expose at
most 50 operations. All limits are checked before retry classification and
audit sanitization.

A dedicated `DecisionResolutionContract` validates this object after the
normal `echelon_result` envelope validation. Missing or extra fields,
non-empty `state_updates`, non-empty `journal_entries`, quarantined updates, or
any verdict other than `JUDGMENT_RESOLVED` reject the result.

The controller validates the identity, operation id, policy classification,
and operation preconditions before it writes any state. This decision contract
replaces the current banzai cleanup-intent output for the new path; the
controller alone clears lifecycle state. Legacy banzai escalation recovery
keeps its old contract only for pre-v2 active runs.

For semi material decisions, COMMANDER's operation becomes
`recommended_operation_id`; the controller changes the record to
`awaiting_human` and persists `await_human_answer`. For banzai material
decisions, the controller applies the same operation and appends the stated
assumptions to the audit record. When the operation is
`record_clarification`, the controller computes and persists the
`effective_answer_text` defined by the sealed descriptor and autonomy flow. A
fixed operation therefore persists its sealed text even though COMMANDER's
nullable `answer_text` field is null.

The controller, not COMMANDER, maintains
`staging/user-clarifications.md` as an idempotent projection of resolved
`record_clarification` entries in `decision_clarifications`. After decision
apply, the controller first drains `pending_controller_completion`; only then
may the pre-dispatch reconciler write the projection from authoritative state
using an atomic file replacement. Before every later agent dispatch, the same
reconciler repairs any missing projection. Entries are ordered by completion
time then decision id and deduplicated by decision id. Repeating the projection
produces identical content. Bounded audit-history eviction cannot remove
clarification context. A crash after state apply but before completion drain or
projection is therefore repaired before redispatch; COMMANDER never owns or
edits this file as part of decision resolution.

## Specialized Safeguards

Phase-dispatch caps, consecutive WHY failures, and WHY2 metric stagnation
remain specialized `select_evidence_backed_issue` policies. The controller,
not COMMANDER, reads eligible SAGE candidates and seals their exact evidence
and registered recovery routes. COMMANDER may select only one supplied
operation id. If none is eligible, sealing fails into non-decision v1
`manual_diagnosis`; it must not invent a scope, policy, security, or
quality-waiver decision.

Each safeguard registry entry also defines one exact controller-owned effect
template, covered by the static policy digest and operation-semantics version.
The selected descriptor and its evidence remain covered by
`operations_digest`. Successful apply performs the common issue-ledger updates
and these source-reason-specific effects atomically:

- `phase_dispatch_limit`: remove only `source_phase` from
  `phase_dispatch_counts`; remove `phase_dispatch_limit_phase` and
  `phase_dispatch_limit`; and write the existing exact
  `phase_dispatch_limit_recovery` record with that phase and resolver.
- `consecutive_why_fails`: set `why_fail_count` to `0`.
- `why2_metric_stagnation`: set both `why_fail_count` and
  `why2_metric_stagnation_count` to `0`.

The v2 safeguard is sealed before any legacy forced terminal transition. Its
authoritative `source_phase` equals the persisted current phase, and sealing
leaves `state.phase` there while setting `status: blocked`. In particular,
dispatch-cap and WHY guard code must not first write `terminal-blocked`.
`apply_decision` therefore satisfies the existing `from_phase` CAS and the
registered recovery route is the only phase change. Pre-v2 compatibility paths
retain their current terminal-phase reconstruction.

`human_gate` becomes a controller decision producer. Its existing automatic
semi/banzai path is removed. Each gate must declare its `decision_policy` and
the controller supplies its approve/reject operations and context pack.

## CLI Behavior

- `status` classifies valid recovery instructions before legacy prose.
- `continue` invokes `resolve_pending_decision` without pre-clearing its state.
- `resume` accepts input only for a matching v2 `await_human_answer`
  instruction and `blocked_decision` with status `awaiting_human`.
- Before classifying any v2 action, all readers require
  `recovery_instruction.reason_code == blocked_reason`, matching decision id,
  and status/kind consistency. A mismatch renders manual diagnosis and never
  executes an older generation.
- CLI commands submit the decision id, expected state revision, selected
  operation, and optional answer to one controller method. They do not write
  `blocked_decision`, `recovery_instruction`, phase, status, or clarification
  files directly.
- Structured input accepts an exact operation id, or a unique exact label only
  for compatibility. Free text follows the sole-operation and semi-
  recommendation binding rules above. `record_clarification` accepts bounded
  answer text; `record_prerequisite` accepts bounded prerequisite text and
  reruns its sealed verifier before continuation.
- Old runs without v2 records retain the existing escalation and recovery
  compatibility paths.

## Audit, Errors, and Cleanup

The v2 audit records decision id, source phase, source reason code, policy
classification, mode, resolver, lease id, selected operation, rationale,
assumptions, verifier evidence, timestamps, and human confirmation where
applicable. It stores at most 20 entries per decision. A dedicated deterministic
audit sanitizer reuses the high-confidence patterns from
`harness.secret_scan.RULES`, replaces every matched token with
`[REDACTED:<rule-id>]`, and truncates each free-text field to 2,000 characters.
The audit never stores raw prompts, complete provider output, or context-pack
contents.

Invalid ingress or unknown policy persists non-decision v1
`manual_diagnosis`. Invalid COMMANDER output or exhausted attempts marks the
valid v2 decision failed, appends its history summary, and persists
decision-related v2 `manual_diagnosis` with matching durable
`blocked_reason: decision_resolution_failed`. A stale lease result is discarded
without changing the current claim; if no valid claim remains, the next
`continue` reclaims an expired lease or reports the current recovery action.
All diagnostics are redacted. No such failure auto-approves a gate or routes
to another phase.

After a successful operation, the controller marks the decision resolved and
appends its sanitized `decision_history` summary, appends a clarification ledger
entry when applicable, applies the operation-specific `running` or `blocked`
status, and clears the matching recovery instruction, durable `blocked_reason`,
and legacy escalation display fields in the same state transaction. A rejected
gate replaces the decision-generation reason with terminal
`blocked_reason: gate_rejected` rather than clearing it. The active resolved
record remains available until a later decision replaces it under the
history-before-replacement rule.

## Implementation Migration Surface

The implementation change is incomplete unless all of these existing surfaces
move together:

- `harness.echelon_result_schema`: add the producer marker and decision-ingress
  preflight before the `BLOCKED` fast path; reserve base-envelope-only blocking
  validation for trusted non-question controller envelopes.
- `harness.phase_graph` and `harness.workflow_validator`: parse, compile, hash,
  and validate static policy cases, reason codes, concrete-operation digest
  inputs, nested dispatch identity, redirectable output ownership, and gate
  outcome edges.
- `harness.squad_executors` and `harness.prepared_phase_result`: introduce the
  trusted decision envelope, remove provider blocking-contract bypasses, attest
  dispatch identity without giving it state authority, and execute marked
  phases inside one phase-scoped `ProviderArtifactTransaction`.
- `harness.blocked_decision`, `harness.recovery_instruction`,
  `harness.state_transaction_namespace`, and `harness.squad_state`: implement
  exact v2 records, dual digests, invocation kind, recovery-generation equality,
  clarification-ledger ownership, dedicated CAS methods, the shared unlocked
  advance primitive, operation-specific status effects, and completion-bound
  application.
- `harness.squad`: centralize interception, autonomy resolution, completion
  preparation/drain and discard ownership, invocation-aware redispatch,
  safeguard resets, clarification projection, and the split COMMANDER
  contracts. Safeguards seal before legacy terminal-phase writes.
- `echelon.cli`: consume v2 instructions through the existing shared recovery
  classifier and route `status`, `continue`, and `resume` through controller
  APIs rather than direct state/file writes.
- `extension/workflow/definition.yaml`: declare the complete producer matrix,
  policies, result contracts, redirectable output sets, and gate outcomes.
- `extension/agents/control/commander.md`: remove recursive/existential human
  escalation and legacy file ownership from v2 instructions; document the
  exact routing, decision-resolution, and explicitly labeled legacy contracts.
- `extension/commands/echelon.resume.md`: replace the direct clarification and
  state-clearing description with the v2 controller submission flow while
  retaining an explicitly labeled pre-v2 compatibility path.

## Verification

Unit tests cover v1-to-v2 migration and non-migration when invocation authority
is absent, v2 preservation across save, exact history and audit validation,
idempotent bounded history append, non-evicting clarification-ledger append and
capacity failure, decision-case selection from detached result state with no
persisted-state fallback, the complete existing-producer policy matrix, policy
reason codes, static policy drift, concrete operations drift, exact nested
dispatch identity, every tagged operation descriptor, fixed/generated
effective answer selection, immutable issue evidence and registered recovery
routes, phase-scoped artifact promotion/discard, clarification projection,
prerequisite verifier behavior, recovery-instruction v1/v2 validation and
reason equality, config parsing, every decision and Squad status transition,
lease claiming and expiry, retry exhaustion, prepared-completion discard, and
stale-result rejection. Validator regressions prove malformed question-bearing
`BLOCKED` results cannot use a base-validator fast path.

Integration tests cover each producer path in guided, semi, and banzai:
`STOP_AND_ASK` escalation, `BLOCKED` escalation, nested-agent escalation, both
investigator decision cases, human gates, phase-dispatch cap from a phase
without a direct issue-repair edge, consecutive WHY block, metric stagnation,
manual single-phase execution, `status`, `continue`, process interruption at
each durable state, and `resume`. Tests assert that decision interception
occurs before external effects and ordinary routing, a nested question discards
all peer/stage artifacts from that phase attempt, discarded phase effects are
recomputed after redispatch, generic `save` is never used, public `advance` is
not called recursively under the decision lock, successful non-rejection
operations restore `running`, gate rejection remains terminal-blocked,
safeguard counters reset exactly once, gate outcomes cannot leak across
checkpoints, clarification projection survives audit-history eviction and
repairs a post-commit crash, pending controller completion drains before
invocation-aware redispatch, a manual replay operation reruns one real source
phase and stops, a manual route-and-finish operation returns after its applied
route, completion failure does not repeat COMMANDER resolution, either digest
drift fails closed, and CLI resume does not mutate decision state outside the
controller. Static contract tests prove generic routing COMMANDER can emit
neither a human question nor `BLOCKED`, v2 COMMANDER cannot write clarification
files or cleanup fields, and the installed COMMANDER/resume documentation no
longer advertises legacy behavior as the v2 path. RE regression tests prove
that v1 records and existing RE resume behavior remain unchanged.

The primary invariant is: every Squad decision with a declared policy records
either a controller-validated human or COMMANDER operation, or a bounded
`manual_diagnosis` failure. Banzai never presents a non-prerequisite project
decision directly to a human and never bypasses the controller resolver.
