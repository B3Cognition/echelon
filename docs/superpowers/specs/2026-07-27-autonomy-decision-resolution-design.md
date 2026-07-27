# Design: Autonomy Decision Resolution

**Date:** 2026-07-27
**Status:** Corrected draft - fourth review findings incorporated

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
surface with `allows_human_decision: true`.

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
  classification: operational | material | execution_blocked
  allowed_operations:
    - approve_gate
    - reject_gate
  context_pack:
    - spec.md
    - staging/quality-gates.md
  prerequisite_verifier: null
```

A simple agent phase uses its phase policy. A policy may restrict the valid
option ids and require an exact context pack. Nested agent entries always use
their own policy. Classification is never inferred from an agent-provided risk
label.

`PhaseGraph` parses `decision_policy` into an immutable compiled policy with a
stable `dispatch_key` and `policy_digest`, attached to the exact dispatch
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

`workflow_validator` rejects a `human_gate`, a marked dispatch, or a registered
controller producer with a missing/malformed policy, unknown operation,
invalid context path, or operation that cannot apply to one of the source
phase's declared transitions. It also rejects `STOP_AND_ASK` without the
marker, the marker without a policy, and `escalation_question` in ordinary
`allowed_state_updates` when the marker is false.

`execution_blocked` policies require a named `prerequisite_verifier`. YAML may
contain only an enum-like verifier id. A closed Python registry maps that id to
a deterministic controller function; YAML cannot provide a shell command,
module path, callable, or arguments. The provider supplies a declared
capability key and observed diagnostic; the controller runs the verifier. Only
a failed verification can create a human prerequisite request. Missing,
malformed, or unverifiable evidence becomes `manual_diagnosis`, not an
execution blocker.

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

Successful `approve_gate` or `reject_gate` resolution writes the
phase-scoped controller value
`gate_results.<source_phase> = {decision_id, outcome}`. Gate transitions depend
only on the matching phase-scoped outcome; all direct `autonomy = banzai`,
`autonomy in [semi, banzai]`, and `human_approved` bypass conditions are
removed. The controller evaluates the declared gate edge against the projected
scoped value, advances the phase, and removes that scoped value in the same
state transaction. It therefore cannot satisfy a later gate or be replayed
after restart.

Both outcomes must have declared transitions. `checkpoint-assess` is material
because semi already requires human review there. `checkpoint-plan` is
operational because semi currently auto-proceeds there. Each receives an
approve transition to its current next phase and an explicit rejected
transition to `terminal-blocked`; no unmatched reject result is permitted.
Rejection marks the decision resolved, appends its history entry, sets run
status to `blocked`, advances to `terminal-blocked`, and clears the
decision-related recovery instruction atomically. It does not create another
question or a decision-related recovery loop.

## Interception Order

Decision interception is part of result preparation and precedes all ordinary
routing. For every full-run and manual-phase dispatch, the controller performs
these steps in order:

1. detach and validate the result against its exact dispatch contract;
2. verify and attest its executor-supplied dispatch identity;
3. if the validated result contains a non-empty `escalation_question`, seal the
   v2 decision and matching recovery instruction in one CAS state advance;
4. return to the autonomy resolver without preparing external publication,
   evaluating ordinary transitions, recording phase completion, or applying
   provider state updates;
5. only results with no decision request enter the existing external-effects
   and routing pipeline.

The same ordering applies to `BLOCKED` and `STOP_AND_ASK`. Controller safeguards
enter at step 3 through their closed registry. No transition may advance around
the resolver because a question-bearing prepared result never reaches ordinary
transition evaluation.

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
  dispatch_key: "phase1-what/agents/chief-product-owner"
  policy_digest: "<sha256>"
  classification: operational | material | execution_blocked
  question: "..."
  allowed_operations:
    - id: approve
      operation: approve_gate
      label: "Approve the checkpoint"
  recommended_operation_id: approve
  resolution_attempts: 0
  resolution_lease_id: null
  resolution_lease_expires_at: null
  audit: []
```

The controller assigns a cryptographically random id and the source,
classification, operations, attempt count, and audit fields. Phase and gate
decisions require the attested `dispatch_key` and `policy_digest`.
Controller-safeguard decisions use a registry key and registry digest in the
same fields. It may derive question text and legacy display options from
provider input, but it never treats provider-provided `next_phase` as an
operation.

`decision_history` is a controller/store-owned transaction key containing at
most 50 sanitized resolution summaries. Successful or failed terminal
resolution appends one summary in the same transaction that updates the active
decision. Appending the fifty-first removes the oldest. A later decision may
replace the active resolved record only after its summary is present in
`decision_history`; pending, resolving, or awaiting-human records may never be
replaced.

`state_transaction_namespace` registers `decision_history` and the
phase-scoped `gate_results` map beside `blocked_decision` and
`recovery_instruction` as store-owned transaction keys. Only prepared
controller routing effects may update or remove them. They are never added to
provider control intents or phase `allowed_state_updates`.

Migration rules:

1. Existing v1 records remain valid and are consumed unchanged by RE.
2. On a Squad write, a v1 pending decision is normalized once to v2 only when
   its original source phase or blocked reason resolves to a declared policy.
   The conversion preserves its question, options, recommendation, blocked
   phase, timestamps, and v1 resume metadata. A v1 decision without a
   reconstructable policy remains on the existing legacy compatibility path.
3. The state helper must validate and preserve all v2 fields; it must not
   rebuild a v2 record from `escalation_*` fields on later saves.
4. Legacy `escalation_*` fields remain ingress and terminal-display
   compatibility projections until old active runs are no longer supported.

## Closed Controller Operations

The controller accepts only these operation families:

- `approve_gate` and `reject_gate`: set the declared gate result and follow the
  gate's declared transition.
- `continue_current_phase`: clear a recoverable block and redispatch the exact
  source phase.
- `route_declared_transition`: select a policy-listed destination that is a
  declared transition from the source phase.
- `record_clarification`: record a bounded answer to the sealed question and
  redispatch the exact source phase. It cannot change phase or apply arbitrary
  state.
- `select_evidence_backed_issue`: select exactly one controller-read SAGE
  candidate with the existing eligible flag, exact suggested option, and
  evidence-backed validation.
- `record_prerequisite`: records a verifier-confirmed missing prerequisite and
  awaits a human response; it is never a COMMANDER-selected escape route.

No option may contain a free-form `next_phase`, state update, shell command, or
issue decision. `answer_text` is accepted only with `record_clarification` and
is limited to 4,000 characters after trimming. The controller maps an accepted
operation to one exact state transaction and validates the workflow edge before
applying it.

## Autonomy Policy

| Classification | guided | semi | banzai |
|---|---|---|---|
| operational | human selects an allowed operation | COMMANDER selects | COMMANDER selects |
| material | human selects an allowed operation | COMMANDER recommends; human confirms that option | COMMANDER selects and records assumptions |
| execution_blocked | human supplies the verified prerequisite | human supplies the verified prerequisite | human supplies the verified prerequisite |
| unknown/invalid | manual diagnosis | manual diagnosis | manual diagnosis |

For a semi material choice, human confirmation accepts only the recommended
operation id. For a semi material clarification, the human may accept the
bounded COMMANDER recommendation or provide a bounded replacement answer.
Free-text `resume` is otherwise valid only for `record_clarification` or the
verifier-confirmed `record_prerequisite` operation.

## Recovery Instruction v2 and Idempotency

Recovery instruction v1 retains its current exact five fields and all existing
kinds. Schema version 2 is used only for decision-related instructions and has
exactly six fields:

```yaml
recovery_instruction:
  schema_version: 2
  kind: resolve_pending_decision | await_human_answer | manual_diagnosis
  reason_code: decision_pending | human_decision_required | decision_resolution_failed
  phase: phase1-what
  requires_human_input: false
  decision_id: dec-<random-token>
```

The only v2 kinds are `resolve_pending_decision`, `await_human_answer`, and
`manual_diagnosis`. All require a non-empty `decision_id` matching the v2
record. Kind and reason are exact pairs: `resolve_pending_decision` uses
`decision_pending`, `await_human_answer` uses `human_decision_required`, and
`manual_diagnosis` uses `decision_resolution_failed`.
`resolve_pending_decision` requires `requires_human_input: false`, a retryable
source phase, and decision status `pending` or an expired `resolving`.
`await_human_answer` requires `true` and status `awaiting_human`.
Decision-related `manual_diagnosis` requires `false` and status `failed`.
Non-decision manual diagnosis continues to use v1.

When `spec continue` sees `resolve_pending_decision`, it invokes the controller
without clearing blocked state. The existing execution locks serialize local
controller entry but are not the decision lease. The controller creates a new
CAS-backed durable claim by matching state revision, decision id, and pending
status, then setting decision status `resolving`, incrementing
`resolution_attempts`, and writing a random lease id and expiry.

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

A result applies only if its decision id and lease id still match. A stale
result is discarded. An expired lease is reclaimable on the next continue.
Reaching `max_attempts` changes the decision to `failed` and persists v2
`manual_diagnosis`.

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
either null or a trimmed non-empty string and must be null unless the selected
operation is `record_clarification`. `rationale` is limited to 2,000
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
`record_clarification`, its validated `answer_text` is persisted as the
recommended or resolved answer as appropriate.

The controller, not COMMANDER, maintains
`staging/user-clarifications.md` as an idempotent projection of resolved
`record_clarification` decisions. Before redispatch it writes the projection
from authoritative state using an atomic file replacement. Repeating the
projection produces identical content; COMMANDER never owns or edits this
file as part of decision resolution.

## Specialized Safeguards

Phase-dispatch caps and consecutive WHY failures remain specialized
`select_evidence_backed_issue` policies. The controller, not COMMANDER, reads
eligible SAGE candidates. COMMANDER may select only an exact controller-supplied
candidate and its exact suggested decision. If none is eligible, resolution
fails into `manual_diagnosis`; it must not invent a scope, policy, security, or
quality-waiver decision.

`human_gate` becomes a controller decision producer. Its existing automatic
semi/banzai path is removed. Each gate must declare its `decision_policy` and
the controller supplies its approve/reject operations and context pack.

## CLI Behavior

- `status` classifies valid recovery instructions before legacy prose.
- `continue` invokes `resolve_pending_decision` without pre-clearing its state.
- `resume` accepts input only for a matching v2 `await_human_answer`
  instruction and `blocked_decision` with status `awaiting_human`.
- CLI commands submit the decision id, expected state revision, selected
  operation, and optional answer to one controller method. They do not write
  `blocked_decision`, `recovery_instruction`, phase, status, or clarification
  files directly.
- A structured decision accepts only an allowed operation id/label.
  `record_clarification` accepts bounded answer text. A verified prerequisite
  accepts bounded free text and re-runs its verifier before continuation.
- Old runs without v2 records retain the existing escalation and recovery
  compatibility paths.

## Audit, Errors, and Cleanup

The v2 audit records decision id, source phase, policy classification, mode,
resolver, lease id, selected operation, rationale, assumptions, verifier
evidence, timestamps, and human confirmation where applicable. It stores at
most 20 entries per decision. A dedicated deterministic audit sanitizer reuses
the high-confidence patterns from `harness.secret_scan.RULES`, replaces every
matched token with `[REDACTED:<rule-id>]`, and truncates each free-text field to
2,000 characters. The audit never stores raw prompts, complete provider output,
or context-pack contents.

Invalid ingress or unknown policy persists non-decision v1
`manual_diagnosis`. Invalid COMMANDER output or exhausted attempts marks the
valid v2 decision failed, appends its history summary, and persists
decision-related v2 `manual_diagnosis`. A stale lease result is discarded
without changing the current claim; if no valid claim remains, the next
`continue` reclaims an expired lease or reports the current recovery action.
All diagnostics are redacted. No such failure auto-approves a gate or routes
to another phase.

After a successful operation, the controller marks the decision resolved and
appends its sanitized `decision_history` summary, clears the matching recovery
instruction, and clears legacy escalation display fields in the same state
transaction. The active resolved record remains available until a later
decision replaces it under the history-before-replacement rule.

## Verification

Unit tests cover v1-to-v2 migration, v2 preservation across save, bounded
decision history, policy registry validation, exact nested dispatch identity,
operation authorization, clarification projection, prerequisite verifier
behavior, recovery-instruction v1/v2 validation, config parsing, lease
claiming, expiry, and stale-result rejection.

Integration tests cover each producer path in guided, semi, and banzai:
`STOP_AND_ASK` escalation, `BLOCKED` escalation, nested-agent escalation, both
human gates, phase-dispatch cap, consecutive WHY block, manual single-phase
execution, `status`, `continue`, process interruption, and `resume`. Tests
assert that decision interception occurs before external effects and ordinary
routing, gate outcomes cannot leak across checkpoints, and CLI resume does not
mutate decision state outside the controller. RE regression tests prove that
v1 records and existing RE resume behavior remain unchanged.

The primary invariant is: every Squad decision with a declared policy records
either a controller-validated human or COMMANDER operation, or a bounded
`manual_diagnosis` failure. Banzai never presents a non-prerequisite project
decision directly to a human and never bypasses the controller resolver.
