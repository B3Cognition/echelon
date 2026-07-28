# Design: Autonomy Decision Resolution

**Date:** 2026-07-27
**Status:** Corrected draft - human-input, workflow, filesystem, and usage authority specified

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
6. No provider artifact or non-artifact effect becomes durable before the
   complete phase attempt is known not to require a decision.
7. Full-run, manual, override, restart, and recovery entrypoints cannot bypass
   an unresolved decision or unconsumed continuation.

## Non-goals

- Changing ordinary deterministic recovery such as provider waits or runtime
  synchronization.
- Treating unavailable credentials, external resources, or legal authority as
  decisions COMMANDER may invent or assume.
- Broadening RE behavior through the shared `blocked_decision` helper.
- Providing a general network or process-security sandbox. The new provider
  capability enforces only the declared Phase A filesystem read/write boundary.

## Architecture

```
agent / gate / controller safeguard / recovery request
                |
                v
      PreparedHumanInput (controller-owned)
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
                    |
                    v
       pending completion + continuation
                    |
                    v
       exact redispatch, route, or return
```

There is exactly one active `blocked_decision` per Squad run. Resolved
decisions are appended to bounded controller-owned `decision_history` before
the active record may be replaced, and any associated continuation must be
consumed or atomically superseded by its own real dispatch. A decision is not
completed by writing a route, clearing a question, or setting a status field.
It is completed only when the controller validates and atomically applies a
permitted operation.

## Standard Human-Input Boundary

`allows_human_decision` is a static result-contract capability. It answers only
whether a provider result is permitted to propose a project decision; it is not
the runtime signal that human input is required.

Every Phase A runtime source that would otherwise ask a human calls one
controller-owned `prepare_human_input(...)` boundary before persistence or CLI
rendering. The boundary accepts an exact `PreparedHumanInput` value with these
ten fields:

- `schema_version: 1`;
- `source_kind`: `provider_result`, `human_gate`, `controller_safeguard`, or
  `recovery_request`;
- `source_identity`: the attested dispatch key or closed registry entry id;
- `dispatch_key`: the attested dispatch key for provider sources and null
  otherwise;
- `reason_code`: a closed producer-policy or recovery-bridge reason;
- `classification`: `operational`, `material`, or `execution_blocked`;
- `question`: a non-empty bounded string;
- `options`: a bounded canonical array of the existing validated escalation
  option objects;
- `prerequisite`: the validated prerequisite object or null; and
- `policy_digest`: the static producer-policy digest.

The controller constructs this value. Provider output may supply only the
question, option facts, and prerequisite ingress already allowed by its exact
result contract. Human gates, safeguards, and recovery bridges obtain every
field from closed controller registries. Unknown source identities, reasons,
classifications, or policies fail to non-decision `manual_diagnosis`; they are
never presented directly to a human and never sent to COMMANDER.
`PreparedHumanInput` is an ephemeral typed boundary value, not a third durable
decision or recovery record.

`prepare_human_input(...)` is the single policy interception point. Guided
seals the decision as `awaiting_human`; semi first applies the recommendation
rules below and seals `awaiting_human` only when they require confirmation;
banzai claims the sealed decision for COMMANDER unless its validated
classification is `execution_blocked`. No producer calls `input()`, renders a
question, or writes a human recovery instruction itself.

The durable runtime signal is the pair of a v2 `blocked_decision` and its
matching v2 `recovery_instruction`. A v2 instruction has
`requires_human_input: true` if and only if its kind is
`await_human_answer`, its decision id and generation match the one active
decision, and that decision is `awaiting_human`. Every other v2 instruction has
`requires_human_input: false`. An orphan or inconsistent human-input
instruction is `manual_diagnosis`; the classifier must not expose its question
or fall through to legacy `AWAIT_HUMAN_ANSWER`/`RESOLVE_ISSUE` behavior.

Existing recovery producers that classify directly as `AWAIT_HUMAN_ANSWER` or
`RESOLVE_ISSUE` are bridge inputs, not a second interception mechanism. Under
an authoritative v2 workflow bundle they must map through the closed
recovery-bridge registry into `PreparedHumanInput` before persistence. An
unmapped reason is manual diagnosis. Their current direct behavior remains
available only to a run whose authoritative workflow bundle records the v1
contract and supported v1 runtime semantics.

Deterministic operator prerequisites that cannot be chosen or assumed, such as
missing credentials, legal authority, external access, or manual state repair,
remain ordinary recovery/manual diagnosis. They do not become project
decisions. The only intentional banzai-to-human path is a decision already
classified `execution_blocked` by a declared policy and verified prerequisite
registry.

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
controller safeguard to a declared `decision_policy`. It then constructs
`PreparedHumanInput` and, after autonomy policy interception, creates the
transaction-owned `blocked_decision` and `recovery_instruction` in the same
state advance. Providers and COMMANDER cannot write either record directly.

An input with no declared policy is a controller validation failure. Because
no valid v2 decision can be sealed without a policy, the controller persists
the existing non-decision v1 `manual_diagnosis` recovery instruction with a
redacted `invalid_decision_policy` diagnostic. It must not synthesize a v2
decision, downgrade the request to `material`, or permit banzai to choose.

## Workflow Decision Policy

`allows_human_decision` is the standard compile-time provider capability. It is
a boolean field on the exact result contract and defaults to false. When false,
result validation rejects `escalation_question` for every verdict, including
the current `BLOCKED` fast path. When true, the dispatch must declare
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

`PhaseGraph` compiles every executable entry into an immutable
`DispatchDescriptor` with exactly `phase_id`, `dispatch_kind`, `entry_id`,
`stage_index`, `declaration_index`, and `dispatch_key`. `dispatch_kind` is one
of `phase`, `pre_dispatch`, `stage_agent`, or `sequential_agent`.
`stage_index` is a non-negative integer only for `stage_agent` and is null
otherwise. A simple phase uses its phase id as `entry_id`; every nested entry
must declare a non-empty `id`, and fallback from `id` to agent name is removed.
`declaration_index` is zero for a simple phase, the zero-based position in the
phase's complete YAML `pre_dispatch` list for a pre-dispatch entry, and the
zero-based position in the phase's complete YAML `agents` list for staged and
sequential entries; it is never renumbered after condition filtering or within a
stage. Thus two pre-dispatch entries, two peers in one stage, and two entries in
different stages cannot acquire the same ordering identity by local
renumbering.
The canonical key is
`<phase_id>/<dispatch_kind>/<stage-index-or-zero>/<entry_id>`. The workflow
validator rejects duplicate nested ids or dispatch keys and inconsistent stage
metadata.

`PhaseGraph` attaches the descriptor, exact result contract, compiled
`decision_policy`, normalized dependency dispatch keys, and static
`policy_digest` to the dispatch. Every `depends_on` value must resolve to the
exact id of another entry in the same phase, must target a lower stage, and is
compiled to that entry's `dispatch_key`; unknown ids, same-stage dependencies,
cycles, and dependencies on later stages are workflow errors. A nested executor
that returns a decision-bearing result wraps it in trusted
`ExecutorDecisionResult`, analogous to the existing `ExecutorBlockedResult`.
The wrapper contains the detached `SquadAgentResult`, complete descriptor, and
`policy_digest`; provider output cannot set these fields. Simple phase and gate
executors use the same wrapper.

Preparation verifies the wrapper against the compiled graph and seals
the complete descriptor, normalized dependency dispatch keys, and
`policy_digest` into `PreparedPhaseResult` attestation. The controller selects
policy only from this attested identity, never by trying to infer which nested
entry returned a plain result. A mismatch is an executor contract failure and
uses the existing non-decision recovery path.

`policy_digest` is SHA-256 over canonical JSON containing only recomputable
static authority: the complete dispatch descriptor, normalized dependency
dispatch keys, normalized cases, operation-family templates, context paths,
exact declared transition metadata, verifier ids, registered recovery-route ids
and mappings, and a controller-owned
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
2. With `allows_human_decision: true`, a question-bearing result requires
   verdict exactly `BLOCKED` or `STOP_AND_ASK`, exact `status: blocked`, a
   non-empty diagnostic `blocked_reason`, a non-empty bounded question, valid
   bounded options, and all case discriminator fields. Every decision-ingress
   state key must be present in that dispatch's explicit allowlist.
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

`SquadCliProvider` and every provider adapter return a typed
`ProviderResultValidationFailure` after exact-contract repair is exhausted.
They never fabricate a provider-shaped `BLOCKED` result. Only the executor may
translate that typed failure into the trusted, non-question
`ExecutorBlockedResult`, preserving the distinction between provider ingress
and controller failure recovery.

Before every claim, human confirmation, prerequisite submission, and apply,
the controller recompiles the run's authoritative workflow bundle and registry
entry using its recorded semantics versions and compares its static
`policy_digest` with the active decision. It separately recomputes
`operations_digest` from the persisted descriptors and validates every selected
descriptor against the bundled edge and the version-selected verifier and
recovery-route registries.
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
`allowed_state_updates` when the marker is false. Existing question producers
that currently allow `ESCALATE` migrate to `STOP_AND_ASK`; `ESCALATE` may not
carry a human question.

The existing generic COMMANDER routing judgment is not a decision producer and
cannot recursively escalate. Its static contract is split:

- `ROUTING_JUDGMENT_RESULT_CONTRACT` has
  `allows_human_decision: false` and accepts only `JUDGMENT_RESOLVED`, empty
  `state_updates`, empty `journal_entries`, and one exact `routing_judgment`
  object with fields `schema_version: 1`, `source_phase`,
  `transition_index`, `outcome`, `target_phase`, and `rationale`. `outcome` is
  `select_transition` or `condition_false`. `select_transition` requires
  `target_phase` to equal the indexed declared edge target;
  `condition_false` requires null `target_phase` and means that the controller
  may evaluate the next transition in declared order. The source and transition
  index must match the unresolved routing request. Arbitrary graph phases,
  omitted intent, extra fields, lifecycle fields, and every `escalation_*`
  field are rejected.
- `DecisionResolutionContract` owns all v2 decision resolution.
- `LEGACY_BANZAI_ESCALATION_RESULT_CONTRACT` retains the old cleanup fields only
  when resuming a pre-v2 active decision under an authoritative v1 workflow
  bundle.

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
Rejection marks the decision resolved, appends its history entry, preserves run
status `blocked` without a status update, writes terminal
`blocked_reason: gate_rejected`, advances to `terminal-blocked`, and clears the
decision-related recovery instruction atomically. It does not create another
question or a decision-related recovery loop.

## Interception Order

Decision interception is part of result preparation and precedes all ordinary
routing. A `PhaseAttemptTransaction` is required for every full-run or
manual-phase attempt that executes at least one provider. It covers every
provider-executing pre-dispatch, staged, sequential, or simple entry in that
phase. Pure deterministic controller phases and human gates do not create child
provider workspaces; they remain on the existing prepared-result and
publication/recovery path, but their decision results still enter at step 4
before ordinary routing. For each provider-executing attempt, the controller
performs these steps in order:

1. create one attempt-local `PhaseAttemptTransaction` for the entire phase,
   capture the begin-time preimages of every declared canonical artifact-effect
   destination, and create a child workspace for each provider-executing
   dispatch;
2. execute providers only through the child workspace and accumulate detached
   results, journal proposals, controller-normalized usage records,
   product-input proposals, state-update proposals, certificate updates, and
   staged artifact manifests in the parent transaction;
3. join every concurrent stage, then detach and validate all results in declared
   dispatch order against their exact contracts and descriptors;
4. collect question-bearing results for that stage in declared order. Exactly
   one may continue to decision sealing. More than one produces trusted
   non-decision `ambiguous_parallel_decision` manual diagnosis and discards the
   attempt; scheduler completion order never selects authority;
5. if one validated result contains a non-empty `escalation_question`, construct
   `PreparedHumanInput`, invoke the single autonomy interception boundary, and
   seal the v2 decision, matching recovery instruction, and any registry-owned
   safeguard seal effects in one CAS state advance;
6. abandon the complete phase attempt and return to the autonomy resolver
   without preparing external publication, evaluating ordinary transitions,
   recording phase completion, or applying accumulated ordinary effects;
7. only a complete phase execution with no decision request may seal its
   accumulated artifacts and non-artifact effects into the existing
   external-effects and routing pipeline.

Provider-executing entries do not call `SquadStateStore`, append journals,
charge durable token or USD counters, update product-input state, or prepare
controller completion while a `PhaseAttemptTransaction` is open. They return
proposals to the transaction. Pure deterministic controller phases retain their
existing store/publication APIs and cannot be nested inside a provider attempt.
The controller is the only component that may commit a provider attempt's
validated aggregate after it proves that the complete attempt contains no
decision request.

Provider-reported and controller-normalized usage is accounting, not a provider
phase effect. One backend invocation is one billable call. Result extraction
repair is therefore controller orchestration, not an internal second call hidden
inside `SquadCliProvider.exec_agent`: the controller receives and spools the
initial `CliRunResult`, validates it, and only then may issue a separately
indexed repair call.

Every billable sequence has a durable `billing_scope_id`: a phase provider
sequence uses its attempt id; a decision resolver sequence uses its decision
claim lease id; a continuation sequence uses its continuation dispatch lease
id; and controller routing/resolution without an existing claim creates a
random billing scope and fsyncs it before its first call. A retry or new claim
gets a new scope and restarts its index at zero. Initial and repair calls in one
sequence share the scope and use indices zero and one. Every call's
controller-generated `usage_id` is
`<billing-scope-id>/<encoded-dispatch-key-or-resolver>/<call-index>`, where the
middle component uses UTF-8 RFC 3986 percent-encoding, leaves only unreserved
ASCII characters unescaped, and uses uppercase hexadecimal, so it contains no
literal slash. The exclusive-created index-zero started record is the durable
creation of a random generic scope; no separate mutable call counter is used.

Before each backend invocation, after reserving a receipt slot, the controller
creates with exclusive-create semantics and fsyncs an exact twelve-field
usage-spool record below the Squad run directory. It has
`call_status: started`, unknown token and cost status, null deltas, and the
pre-call `token_budget_debit`. A pre-existing filename is never overwritten by
a new call. The controller then invokes the backend. After return, and before
output interpretation or a later call, it atomically replaces and fsyncs that record with
`call_status: returned` and normalized usage.

The twelve fields are exactly `schema_version: 1`, `usage_id`,
`billing_scope_id`, `call_index`, `call_status`, `provider_id`, `model_id`,
`token_status`, `token_delta`, `token_budget_debit`, `cost_status`, and
`cost_microusd_delta`. `call_index` is a non-negative integer and the parsed
scope and index components of `usage_id` must equal their explicit fields.
Provider and model ids are null or controller-normalized non-empty strings.
`token_status` is `reported` or `unknown`; `token_delta` is a non-negative
integer exactly when reported and is null otherwise. `token_budget_debit` is a
non-negative integer fixed by the rules below. `cost_status` is `reported`,
`estimated`, or `unknown`; `cost_microusd_delta` is a non-negative integer
exactly when reported or estimated and is null otherwise. Conversion from
provider currency data uses decimal arithmetic and round-half-even to one
micro-USD. A backend's default zero with no supporting usage field is
`unknown`, not a reported zero. The controller hashes `usage_id` for the spool
filename, so provider identity never selects a path.

The current hard safety budget is `token_budget`; `cost_microusd` is accounting
and display only until a separate cost-budget contract is designed. Each
controller-owned runtime profile declares `token_accounting_mode` as
`reported` or `reserved`. With a positive token budget, the adapter must also
support an enforceable positive per-call token limit. Under the run execution
lock, the controller derives an effective limit no greater than the remaining
budget, accounts for debit in all outstanding started/returned-but-unapplied
spool records, and writes that limit as the started record's
`token_budget_debit` before billable work.

For `reported`, a returned record replaces `token_budget_debit` with the exact
reported `token_delta`; a return above the reserved limit is an adapter contract
violation, debits the larger actual value, and enters manual diagnosis. For
`reserved`, the returned record keeps the full reservation as
`token_budget_debit`, even when the backend also reports a smaller token count.
An unknown return or interrupted started call keeps the reservation. If a
positive token budget is configured and the profile cannot provide reported
usage or an enforceable reservation, provider preflight fails before billable
work. With token budgeting disabled, unknown usage may run with zero budget
debit, but its unknown counter and audit record remain mandatory. Thus no
provider can continue indefinitely against a positive hard budget with unknown
usage.

On startup, the broker first terminates or proves absent every orphaned OCI call.
A remaining `started` record is finalized as `returned` with both statuses
unknown and its reservation unchanged, applied through deferred usage recovery,
and associated with the ordinary interrupted-attempt failure path; the same
usage id is never replayed. Usage remains deferred until outcome classification,
then joins the authoritative success, decision-seal, or failure state operation.

The store owns an exact `applied_usage_receipts` list and one
`_apply_usage_unlocked` primitive. Each receipt repeats the exact twelve fields
from its fsynced source record. A new id adds known reported token usage to
`token_usage`, adds `token_budget_debit` to the new monotonic
`token_budget_usage`, adds known reported or estimated cost to integer
`cost_microusd`, increments `unknown_token_usage_calls` or
`unknown_cost_calls` when the corresponding status is unknown, and appends the
receipt. Existing `cost_usd` becomes a derived display value and is never
independently incremented. `_budget_exhausted` and every pre-call hard-budget
check use `token_budget_usage` plus unapplied spool debits, never display
`token_usage` or cost. An existing identical id is an idempotent success; an
existing id with any different field is corruption and enters
`manual_diagnosis`.

The ledger permits at most 4,096 entries and 512 KiB of canonical JSON;
receipts are never evicted within a run. Before starting a provider or resolver
call, the controller checks that one receipt slot remains while holding the run
execution lock. Startup drains every fsynced unreceipted usage record before
another call, so the slot cannot be consumed by competing work. Exhaustion
blocks before billable work. After an ambiguous state-write or fsync exception,
authority reload determines whether the authoritative outcome already owns the
usage ids; only absent ids go through deferred fallback. Attempt and decision-
workspace cleanup preserve every fsynced usage record until its id has a durable
receipt, so cleanup can neither drop nor reapply usage.

The same ordering applies to `BLOCKED` and `STOP_AND_ASK`. The pre-dispatch
`phase_dispatch_limit` safeguard enters at sealing step 5 without a provider
attempt. Consecutive-WHY and WHY2-stagnation safeguards are post-result guards:
they inspect the attested prepared result and attempt-local declared effects,
seal exact triggering counters, baselines, and issue candidates into
controller-owned descriptors, and then abandon the attempt. They never reread a
previously persisted `issues.md` or quality state as evidence for the current
trigger. No transition may advance around the resolver because a
question-bearing prepared result never reaches ordinary transition evaluation.

A question-bearing agent result is a proposal to stop, not a partially
committable phase result. All ordinary provider updates, controller-contract
updates, output certification, publication preparation, completion intent, and
all peer or earlier-stage artifacts from the same phase attempt are discarded
after the decision ingress fields and case discriminator have been sealed.
They are never serialized into `blocked_decision`. After a clarification or
prerequisite resolves, the controller projects the answer, redispatches the
exact source phase, and requires the new result and artifacts to pass their
contracts again.

`PhaseAttemptTransaction` is a controller-owned effect boundary, not a
best-effort cleanup pass. Artifact ownership uses a new exact
`artifact_effects` contract; the existing descriptive `outputs` list remains
documentation and grants no write authority. `artifact_effects` is nested on
the executable YAML entry that owns it: on the phase object for a simple agent,
or on the exact `pre_dispatch` or `agents` item for a nested dispatch. The
workflow never supplies owner identity. During compilation, `PhaseGraph` stamps
each effect with its trusted `DispatchDescriptor.dispatch_key`. The controller
assigns a random attempt id and creates the parent and child workspaces below
the Squad run directory using the existing no-follow and real-directory checks;
workflow or provider data never selects their paths:

```yaml
artifact_effects:
  - id: kill_report
    operation: upsert
    destination_root: spec
    destination_path: kill-report.md
    kind: file
    tree_mode: null
    presence_by_verdict:
      PASS: forbidden
      KILL: required
      DEFER: forbidden
    move_group: null
```

Every workflow descriptor has exactly `id`, `operation`, `destination_root`,
`destination_path`, `kind`, `tree_mode`, `presence_by_verdict`, and
`move_group`; the compiled descriptor additionally contains the controller-
stamped `owner_dispatch_key`. `operation` is `upsert` or `delete`. An `upsert`
publishes the complete postimage and covers create, amend, or replace; an
existing owned destination is seeded into the child so in-place tools can amend
it. A `delete` grants no provider-controlled publishable postimage and publishes
controller-staged removal after validating the begin-time preimage.
`destination_root` is one of the controller-resolved
aliases `spec`, `staging`, `squad`, or `memory`; broad `project` authority is
forbidden. `kind` is `file` or `tree`. `destination_path` is a normalized
relative path.

`presence_by_verdict` is an exact mapping whose keys equal the complete
effective `allowed_verdicts` set in that executable entry's compiled result
contract and whose values are `required`, `optional`, or `forbidden`. An entry
without a finite effective verdict set cannot declare artifact effects and is a
workflow error. There is no default or wildcard.
Validation occurs after result-contract validation and before publication. For
an upsert, `required` requires a staged postimage, `optional` publishes one only
when present, and `forbidden` rejects a staged postimage or matching
`output_files` claim. For a delete, `required` requires a begin-time preimage,
`optional` deletes only when that preimage exists, and `forbidden` performs no
delete. Both members of a move group must have identical presence mappings.
This makes verdict-dependent outputs such as `kill-report.md` required for
`KILL` and forbidden for `PASS` without trusting provider prose.

`tree_mode` is null for files and deletes and is `additive` or `replace` for an
upsert tree. An additive tree publishes only staged child-manifest changes and
does not delete absent canonical descendants. A replacement tree publishes its
complete child manifest and deletes canonical descendants absent from that
manifest. A `tree` owns all descendants and is the only way to declare variable
file sets; glob ownership is not supported.

`move_group` is null except for a controller-owned move. A move is exactly one
upsert and one delete owned by the same dispatch, with matching non-empty
`move_group`, equal `kind`, and distinct resolved destinations. The controller
copies the source preimage into the child's upsert location before dispatch and
later publishes both effects atomically; the provider never renames across
canonical roots. This represents CARTOGRAPHER's staging-to-spec promotion
without granting canonical staging writes.

Before overlap validation, every root alias is resolved through trusted run
state and normalized to a canonical host path using no-follow traversal. Aliases
may be equal or nested because current Echelon layouts place `spec`, `squad`,
`staging`, and `context_dir` within the project tree. The validator therefore
compares canonical destination identity, not alias names: the same host path
always maps to the same child path, and a `squad` tree cannot conceal a
collision with a `staging` effect.

Every canonical path belongs to one visibility class:

- `hidden`: `state.json`, `.controller`, publication and completion outboxes,
  usage spools, locks, credential workspaces, and attempt internals. These are
  neither mounted nor projected into prompts.
- `read_only_visible`: declared external input roots and immutable context
  inputs that are not within the child project tree. They are mounted
  separately read-only.
- `controller_projected`: controller state needed for reasoning. Raw
  `state.json` remains hidden; prompt assembly receives an immutable
  `AttemptStateProjection` containing only a closed allowlist of non-secret
  fields required by the dispatch contract.
- `publishable`: effect destinations in the private child project tree. They
  may be changed in the attempt, but only declared `artifact_effects` can be
  published.

An effect destination may not equal, contain, or be contained by a hidden,
read-only-visible, or controller-projected canonical source. The validator
rejects absolute paths, parent traversal, duplicate ids, overlapping file/tree
effect destinations after canonical physical resolution, visibility-class
overlap, undeclared roots, owner mismatch, malformed move groups, unresolved
placeholders, and any provider dispatch whose effects cannot be redirected.
Owner mismatch means a compiled effect is presented by any dispatch other than
its stamped `owner_dispatch_key`; owner is never read from provider output or
workflow YAML.

Prompt paths are instructions, not authority. Shared phase and agent documents
may continue to use controller-mapped `{spec_dir}`, `{staging_dir}`,
`{context_dir}`, `SQUAD_DIR`, and `STAGING_DIR` aliases. The attempt overlay
makes every provider write land in a disposable private child, regardless of how
broad those aliases look in text; `artifact_effects` defines the only paths
eligible for publication. `{artifact_effect.<id>}` is optional shorthand for an
exact dispatch-owned destination; it may appear only in a dispatch-specific
prompt fragment and must resolve to an effect owned by that dispatch. Shared
multi-mode role files do not use dispatch-specific effect placeholders. Because
the attempt boundary exists before a result is known, every Phase A provider-
executing dispatch, marked or unmarked, declares every publishable write or
delete through the schema. The decision marker controls ingress authority, not
filesystem isolation.

The controller creates one coherent `AttemptFilesystem` per provider dispatch.
It consists of one private child project tree plus any declared external
read-only input mounts. The canonical host project is controller-only input;
the provider-visible `AttemptPathMap.project_root` is the private child project
root and is the provider CWD. `spec_dir`, `staging_dir`, `squad_dir`,
`memory_dir`, and an in-project `context_dir` are canonical project-relative
paths within that same backing tree. Their equality and nesting relationships
are preserved exactly. An external `context_dir` is a separate
read-only-visible mount and is never an artifact destination.

The child project is initialized from the parent-attempt snapshot with hidden
paths omitted and controller-projected state replaced by
`AttemptStateProjection` in the prompt, not by a filesystem copy. It uses a
safe copy-on-write clone where supported and a full private copy otherwise; it
never uses writable hard links. A provider may create incidental files in the
child tree, but after execution the controller computes one complete tree diff
against the snapshot. Any change not covered by that dispatch's compiled
effects is `undeclared_artifact_effect`, rejects the attempt, and is discarded.
No child path is a canonical host path.

Prompt construction, context-pack resolution, environment variables including
`PROJECT_ROOT`, `CONTEXT_DIR`, `SQUAD_DIR`, and `STAGING_DIR`, phase documents,
and extra-file checks all use `AttemptPathMap`. No executor may reconstruct a
path from canonical `state.spec_dir`, `state.staging_dir`,
`state.context_dir`, `_project_root`, or `_squad_dir` while an attempt is open.

Provider execution uses an exact controller-created `ProviderExecutionRequest`
containing the `DispatchDescriptor`, private child CWD, `AttemptPathMap`,
`AttemptStateProjection`, declared external read-only inputs, exact publishable
effects, placeholder mapping, and `containment_required: true`. The AI backend capability
registry exposes `ENFORCED_WRITE_CONTAINMENT` only when its backend applies an
OS-enforced filesystem boundary that prevents writes to canonical and protected
host paths. It does not prohibit scratch writes inside the disposable child;
publication validation handles those. CLI permission flags, prompts, CWD
selection, and provider claims are insufficient. A provider dispatch fails
closed before provider execution when the selected provider lacks that
capability. `SquadCliProvider`, `AICodingCliProvider`, and every backend adapter
must preserve and attest the request rather than reducing it to `project_root`.

The containment interface is a new `AiExecutionSandbox`, distinct from the
existing build-oriented `SandboxProvider`: the latter owns a worktree lifecycle
and one broad worktree mount, while AI attempts require one isolated private
project plus exact external read-only inputs per dispatch. `AiExecutionSandbox` reuses
`HarnessConfig.container_cli`, resource-limit parsing, runtime invocation
helpers, and image-security utilities; it does not create a second generic
provider registry or reinterpret `HarnessConfig.provider`.

The first implementation is `OciAiExecutionSandbox`, through a Docker- or
Podman-compatible runtime on Linux or macOS. It has two closed adapters:

- `OciCliExecutionAdapter` executes `claude`, `codex`, `copilot`, and `opencode`
  as subprocess CLIs in a controller-selected, digest-pinned OCI image.
- `OciOpenAICompatibleWorker` starts a controller-owned Python worker in the
  same OCI boundary and runs the existing HTTP and structured-tool engine
  inside that worker. Its file tools see only the mounted attempt paths; the
  host process does not execute provider-selected file operations.

`plain`, an unknown LLM value, Windows, and host-only execution are unsupported
for v2 provider dispatches. Preflight covers every configured value in
`VALID_LLM_CLIS` and fails with `provider_containment_unavailable` when its
specific adapter is absent. The broker mounts only the private child project
tree read-write at `/workspace`, mounts declared external inputs read-only at
controller-selected paths, and supplies controller-created writable `HOME`,
cache, and temporary directories outside artifact roots. It does not mount the
canonical host project, `state.json`, `.controller`, outboxes, usage spools,
locks, or attempt internals into the container. Alias paths are ordinary paths
within `/workspace`, not independent overlay mounts.

Each adapter declares a closed runtime profile naming its image by immutable
digest, command or worker entrypoint, authentication/config roots, a
`credential_mode` of `readonly_mount` or `ephemeral_copy`, and ephemeral cache
paths; workflow and provider output cannot add mounts. Image resolution calls a
new fail-closed image-security API: missing pin, inspection failure, timeout,
empty digest, or mismatch all fail v2 preflight. The existing fail-open
`validate_digest_pin` behavior is not used for v2.

`readonly_mount` exposes the host credential root read-only. `ephemeral_copy`
initializes a private controller-owned credential workspace once per
run-and-adapter, reuses it across initial, repair, retry, and resolver calls so
token refresh survives, excludes it from artifact manifests, never copies it
back to the host, and scrubs it when the run becomes terminal or is explicitly
abandoned. Secrets and token-refresh files are never copied into artifact
postimages.

The v2 capability is filesystem write containment only. Its initial exact
network mode is ordinary OCI bridge egress, allowing the selected provider API,
authentication endpoints, and configured OpenAI-compatible `base_url`; it does
not claim network isolation. The existing build-sandbox Squid/package allowlist
continues to govern build sandboxes and is not silently applied to AI provider
calls. A later network-contained AI profile requires a separate capability and
cannot change this behavior under the same capability name.

Containment ships before v2 workflow activation. Provider/backend support,
request attestation, OCI preflight, and attempt filesystems land first while the v1
workflow remains active. That precursor release also makes workflow authority
durable for every new run and adds exact top-level
`workflow_contract_version: 1` to the installed definition. Before state
initialization, `WorkflowBundleBuilder` resolves the installed definition,
extension agent mapping, every static prompt/result source actually used by an
executable entry, referenced controller contract registries, and all immutable
Phase A configuration into a canonical controller-owned workflow bundle at
`<squad_dir>/.controller/workflows/<workflow_digest>/`. The
`.controller/workflows` tree is never provider-mounted.

`manifest.json` has exactly these eight fields:

- `schema_version: 1`;
- `workflow_contract_version`;
- `workflow_runtime_semantics_version`;
- `prompt_assembly_semantics_version`;
- `result_repair_semantics_version`;
- `source_manifest_sha256`;
- `workflow_config_sha256`; and
- `workflow_digest`.

`sources.json` is a canonical array sorted by `(kind, logical_path)`. Each entry
has exactly `logical_path`, `kind`, and `sha256`; `kind` is one of
`workflow_definition`, `extension_mapping`, `phase_prompt`, `agent_prompt`,
`result_template`, or `controller_contract`. Source bytes live under
`sources/<sha256>`. `workflow-config.json` contains the closed normalized
values read by Phase A workflow compilation, prompt assembly, decision policy,
quality/convergence gates, and dispatch limits, including
`analysis.decision_resolution`, quality thresholds, governance settings, and
`max_iterations`. It excludes the mutable token budget, selected
provider/profile, and credentials, whose separate authority is defined below.

`source_manifest_sha256` is SHA-256 of the exact canonical `sources.json`
bytes, and `workflow_config_sha256` is SHA-256 of the exact canonical
`workflow-config.json` bytes.
`workflow_digest` is SHA-256 over one canonical JSON object with exactly
`manifest`, `sources`, and `workflow_config`: `manifest` contains the seven
manifest fields other than `workflow_digest`, while the other members contain
the parsed values whose canonical encodings are the two hashed files. Contract
and semantics versions are positive integers; every digest is lowercase
64-character hexadecimal.
Logical paths are normalized relative POSIX paths. Absolute paths, parent
traversal, duplicates, unknown kinds, missing content, content/hash mismatch,
or unknown configuration keys reject the bundle.

The bundle stores validated sources, not a second serialized graph authority.
`PhaseGraph.from_bundle(...)` recompiles the workflow definition with the
closed compiler registered for
`workflow_runtime_semantics_version`. `PromptSourceResolver` is the only
runtime loader for phase prompts, agent prompts, result templates, extension
mappings, and controller contracts. It selects controller-generated shared
agent/result-contract fragments with the recorded
`prompt_assembly_semantics_version`; result extraction and the controller-owned
repair prompt use the recorded `result_repair_semantics_version`. Unsupported
compiler, prompt, or repair semantics fail closed before provider execution.
No runtime prompt or repair path reads the currently installed extension.

An explicit immutable-config consumer registry identifies every Phase A
consumer that must read `workflow-config.json`; activation fails if a registered
consumer still reads mutable installed config. Mutable operational controls are
separate from workflow authority: the token budget may only increase through
the existing authorized recovery path; selected provider/profile changes are
accepted only after per-dispatch containment, image, credential, and accounting
preflight and are recorded in invocation attestation; credentials remain
external secret inputs. No other Phase A workflow, prompt, policy, or gate
setting may change for an active run.

State initialization stores `workflow_contract_version` and `workflow_digest`
in exact top-level fields. The complete bundle is fsynced and atomically sealed
before state creation and is immutable; resume, continue, manual phase replay,
decision migration, policy validation, and prompt construction load authority
from it rather than rereading the currently installed extension. Every load
revalidates manifest, source, config, semantics-version, and state digests.
Display-only extension drift warnings remain permitted.
`PhaseGraph.from_installed(...)` is used only by `WorkflowBundleBuilder` while
preparing a new or explicitly eligible migration bundle;
`PhaseGraph.from_bundle(...)` is the only runtime dispatch constructor.
A v1 bundle may continue only while the runtime supports every semantics
version recorded by that bundle.

The policy and `artifact_effects` migration then bumps the exact top-level
workflow contract version to `2`. Starting a new v2 run performs backend
preflight before writing the bundle or run state and reports
`provider_containment_unavailable` when the required image, runtime, or profile
is missing. A v1 run with a valid v1 bundle continues against that bundle. A
legacy unversioned run created before the precursor release is automatically
migratable only while pristine, before its first provider dispatch. Pristine
means all of the following: `last_dispatch` is null; `completed_phases` and
`phase_dispatch_counts` are empty; there are no usage receipts or usage spool
records; there is no pending publication, completion, continuation, decision,
or recovery authority; there is no provider/controller phase output; state is
at the declared entry phase with status `preparing` or `running`; and any
initial context/product-input setup passes its current structural validation.

For that one case, an explicit controller migration performs v2 graph and
provider preflight, installs and fsyncs the content-addressed bundle, then uses
one state CAS to write the v2 version and digest. A crash before that CAS leaves
an unreferenced immutable bundle that a retry may revalidate and reuse; a crash
after it cannot expose missing bundle bytes. An unversioned run that is not
pristine requires the matching legacy runtime and cannot be projected onto the
current graph. The current runtime persists
`workflow_migration_required` manual diagnosis without replacing its workflow
authority. Validation failure likewise leaves workflow authority unchanged.
The validator never substitutes an installed graph for bundle authority,
attempts arbitrary mid-run state/artifact projection, or downgrades a v2
dispatch to host execution.

Concurrent child dispatches are seeded from the same parent-attempt snapshot and
cannot read or write peer child workspaces. After a stage joins and all results
pass validation with no question, child manifests are merged into the parent in
declared dispatch order. Overlapping ownership is already a workflow error, so
merge never resolves last-writer-wins conflicts. Later stages and sequential
dispatches receive the merged parent-attempt snapshot as read-only input plus
their own writable child workspace. Nothing is promoted to canonical roots
between stages.

Non-artifact proposal merging is equally deterministic. Parallel dispatches
must have disjoint declared state-update and certificate ownership; the
validator rejects overlapping allowlists. Product-input proposals use normalized
`input_unit_id` as their identity. Proposals for the same input unit collapse
only when their complete canonical objects are identical; divergent values fail
the attempt as
`ambiguous_parallel_product_input`. Journal entries and detached results append
in `declaration_index` order, never `as_completed` order. After a stage is
validated and merged, a later stage or sequential entry may supersede an earlier
state, certificate, or product-input proposal; the exact later value wins in
stage order and then `declaration_index` order. No same-stage peer may use this
sequential supersession rule.

After a complete non-question phase passes result, artifact, and
controller-contract validation, provider-staged effects are imported into the
same `SquadPublicationTransaction` builder used by controller-owned external
effects. Import lowers every effect to the builder's existing regular-file
operations before sealing; the durable publication schema gains no tree or move
action:

- a file upsert becomes one `add_write`, and a file delete becomes one
  `add_delete`;
- an additive tree is walked in normalized lexical order, rejects symlinks and
  special files, and adds writes only for staged regular files whose postimage
  differs from the begin-time snapshot;
- a replacement tree performs the same walk and additionally adds file deletes
  for regular canonical descendants present in the begin-time snapshot but
  absent from the staged tree;
- a file move becomes one write seeded from the source preimage plus one delete;
  a tree move enumerates the source and lowers to paired file writes and deletes
  in normalized lexical order.

All lowered operations retain the compiled owner dispatch key and source effect
id in the aggregate effect digest. Empty required trees fail validation; empty
optional additive trees are no-ops. Directory creation and removal are
consequences of file publication and cleanup, not manifest operations. The
builder seals one combined manifest and one existing
`pending_external_publication` marker containing begin-time destination
preimage hashes, staged hashes, dispatch identities, aggregate effect digest,
and completion intent. There is never a second provider-publication marker.
A destination changed since phase-attempt begin is stale state and rejects
publication without overwriting the newer artifact.

Cleanup is authority-aware. After any CAS, replacement, or fsync exception, the
controller reloads state. It preserves or reloads a transaction referenced by
the exact durable decision, routing, publication, or completion marker and
removes a workspace only after proving that no durable record references it.
Provider failure, invalid result, stale state, or an abandoned uncommitted route
therefore requests cleanup but does not unconditionally call `discard()`.
No Phase A provider process receives a writable canonical output path, so an
abandoned decision attempt cannot influence later context reconciliation or
redispatch.

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
only after its summary is present in `decision_history` and its continuation is
consumed or is being consumed by the same real-dispatch transaction; pending,
resolving, or awaiting-human records may never be replaced. Malformed persisted
history blocks all decision methods. The existing snapshot-bound failure
recovery path preserves the malformed value byte-for-byte and persists
non-decision v1 `manual_diagnosis`; history is never silently repaired or
dropped.

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

`decision_continuation` is the store-owned durable record of work owed after a
successful decision apply:

```yaml
decision_continuation:
  schema_version: 1
  id: "cont-<random-token>"
  decision_id: "dec-<random-token>"
  operation_id: record-clarification
  invocation_kind: full_run | manual_phase
  kind: replay_source | route_and_finish
  disposition: dispatch_source | dispatch_target | finish_without_dispatch
  stage: awaiting_completion | ready | dispatching | blocked | consumed
  completion_id: "<controller completion id>"
  source_phase: phase1-why1
  target_phase: phase1-why1
  dispatch_lease_id: null
  dispatch_lease_expires_at: null
  failure_dispatch_sha256: null
  recovery_instruction_sha256: null
  consumed_at: null
```

The record has exactly these sixteen fields. Lease fields are non-null only in
`dispatching`. `failure_dispatch_sha256` and
`recovery_instruction_sha256` are non-null only in `blocked`; `consumed_at` is
non-null only in `consumed`. A replay-source operation has
`disposition: dispatch_source`. A route-and-finish operation has
`dispatch_target` only for a full run whose target is an executable graph phase;
manual routes, terminal targets, and controller-only targets use
`finish_without_dispatch`. The disposition is computed and attested during
application preparation, never inferred from current status after restart.

The record is bound to the resolved active decision, selected operation,
completion marker, source, target, disposition, and durable invocation kind. A
resolved decision with an unconsumed continuation cannot be replaced, except
when the continuation's own real dispatch atomically consumes it while sealing
a new decision from that dispatch. A `blocked` continuation has no lease and
retains the exact invocation scope owed after a retryable real-dispatch failure.
A consumed record remains until the associated resolved decision is archived,
so restart can distinguish completed work from work still owed.

`legacy_decision_history` is a separate bounded compatibility ledger for a
terminal v1 active decision that cannot be reconstructed as v2:

```yaml
legacy_decision_history:
  - schema_version: 1
    legacy_fingerprint: "<sha256 of canonical exact v1 record>"
    source_phase: phase1-why1
    final_status: resolved | failed
    question: "sanitized question"
    selected_option: "sanitized option" | null
    completed_at: "<UTC timestamp>" | null
```

Every entry has exactly these seven fields, is idempotent by
`legacy_fingerprint`, and follows the same 50-entry oldest-first bound and
2,000-character audit sanitization as `decision_history`. It has no routing or
operation authority. A pending v1 record is never archived to make room for a
new decision.

`state_transaction_namespace` registers `decision_history`,
`legacy_decision_history`, `decision_clarifications`, `decision_continuation`,
`applied_usage_receipts`, `token_budget_usage`, `cost_microusd`,
`unknown_token_usage_calls`,
`unknown_cost_calls`, `blocked_decision`, and `recovery_instruction` as
store-owned transaction keys. `workflow_contract_version` and `workflow_digest`
are immutable workflow-authority keys: only initialization or the dedicated
pristine legacy-unversioned workflow migration may write them.
`why2_metric_stagnation_count` is added to atomic store control keys and trusted
routing effects before safeguard migration. These keys may be changed only by
the exact `SquadStateStore` decision methods below, controller-completion
finalization, or an attested prepared routing decision applying a resolved
operation. They are never added to provider control intents, generic queued
updates, or phase `allowed_state_updates`. Gate outcomes do not require another
state key. `applied_usage_receipts` may additionally change through ordinary
prepared outcome methods or deferred-usage recovery, but only through
`_apply_usage_unlocked`.

## Durable Store Operations

Decision lifecycle writes use dedicated store APIs. Each validates exact
input types before locking, acquires the existing exclusive state lock,
matches phase, `state_revision`, previous-dispatch digest, active decision id,
expected status, and lease identity as applicable, increments
`state_revision`, and uses the existing atomic state-file replacement. A CAS
mismatch returns a stale outcome without mutation.

The existing ordinary prepared phase-advance and prepared failure-settlement
APIs also accept `usage_records` and call `_apply_usage_unlocked` in their
authoritative state operation. No success, decision, or failure path calls
`increment_cost` or increments `token_usage` separately.

- `seal_decision(snapshot, prepared_identity, decision, instruction,
  continuation_receipt, usage_records)` accepts only a newly validated
  decision-bearing prepared result or a registered controller safeguard.
  `continuation_receipt` is null for an ordinary source and must be the exact
  current claim receipt when the producer is a continuation dispatch. The method
  archives an existing resolved/failed active record only after validating its
  history and continuation preconditions, then writes the new active decision,
  recovery instruction, blocked lifecycle state, and idempotent normalized
  source usage records. A decision produced by the exact
  dispatch that owns a `dispatching` continuation consumes and archives that
  continuation in the same transaction before installing the new decision. It
  does not update `last_dispatch` or phase completion.
- `claim_decision(snapshot, decision_id)` accepts only `pending` or an expired
  `resolving` decision below its attempt limit. It writes `resolving`,
  increments attempts, and installs a new random lease and expiry. It returns an
  exact seven-field `DecisionClaimReceipt` containing `schema_version: 1`,
  `decision_id`, `lease_id`, `lease_expires_at`, committed `state_revision`,
  `phase`, and `previous_dispatch_sha256`. Resolver prompt construction and
  every later settle/apply CAS use that receipt; callers never reconstruct
  lease identity from a stale pre-claim snapshot. It does not route.
- `settle_decision(snapshot, decision_id, lease_id, outcome,
  usage_records)` handles state-only transitions to `pending`,
  `awaiting_human`, or `failed`, including recovery-generation replacement,
  lease clearing, audit append, idempotent history append for failure, and the
  idempotent normalized resolver usage records. It cannot
  change phase.
- `apply_decision(snapshot, decision_id, expected_lease_id, operation,
  prepared_route, completion_marker, continuation, usage_records)` accepts only
  controller-prepared, mutually attested application artifacts. It revalidates
  the sealed operation, static policy digest, concrete operations digest,
  bundled workflow edge or version-selected registered recovery route, exact
  transaction effects, completion-marker and continuation binding, disposition,
  and absence
  of an older pending publication, completion, or unconsumed continuation under
  the state lock. It then records the replay-source route, gate edge, or
  safeguard repair through the single state-advance commit primitive while
  atomically resolving the decision, applying idempotent normalized resolver
  usage records, applying the operation-specific run-status
  effect, installing the pending completion marker, and writing
  `decision_continuation.stage: awaiting_completion`.
  Human resolutions use `expected_lease_id: null` and require
  `awaiting_human`; COMMANDER resolutions require the current lease. A commit
  returns an exact six-field `DecisionApplyReceipt` containing
  `schema_version: 1`, `decision_id`, `continuation_id`, `completion_id`,
  committed `state_revision`, and `last_dispatch_sha256`.
- `claim_decision_continuation(snapshot, continuation_id,
  recovery_attestation)` accepts `ready`, or `blocked` only when the shared
  recovery classifier attests that the exact previous continuation dispatch has
  a retryable phase failure and names the same dispatch phase. For `blocked`, it
  recomputes the canonical hash of current `last_dispatch` and the canonical
  five-field `RecoveryInstruction`, requires exact equality with
  `failure_dispatch_sha256` and `recovery_instruction_sha256`, and rejects stale
  same-phase recovery generations. It rejects `finish_without_dispatch`. It
  verifies the active resolved decision, disposition, and invocation kind, then
  writes `dispatching` with a random dispatch lease and expiry and clears both
  failure hashes. It returns an exact ten-field
  `ContinuationClaimReceipt` containing `schema_version: 1`, `continuation_id`,
  `dispatch_lease_id`, `dispatch_lease_expires_at`, committed `state_revision`,
  `invocation_kind`, `disposition`, `source_phase`, `target_phase`, and
  `previous_dispatch_sha256`. An expired `dispatching` lease may be reclaimed
  under the same execution-lock and CAS rules.
- `settle_decision_continuation(snapshot, continuation_id,
  dispatch_lease_id, prepared_outcome, usage_records)` runs inside the first
  authoritative state advance produced by the real source/target dispatch. The
  controller-prepared outcome is exactly `success`, `retryable_failure`, or
  `terminal_failure`; a `new_decision` outcome uses `seal_decision` above so
  there is only one active-decision replacement transaction. Failure
  classification uses the existing `retry_phase_recovery(dispatch_phase,
  reason_code)` constructor and writes the normal failure fields consumed by
  `echelon.cli._classify_run_recovery`; the continuation method does not invent
  a second retry policy. A new continuation-recovery binding validator, called
  by both settlement and the shared classifier, hashes the exact canonical
  `last_dispatch` object written by the normal prepared-failure path and the
  canonical recovery instruction. Settlement derives `last_dispatch` from the
  prepared dispatch attestation once, writes it, and stores the hash of those
  exact bytes in the same CAS.
  `retryable_failure` writes `blocked`, clears the lease, retains null
  `consumed_at`, installs that prepared standard recovery instruction, stores
  both binding hashes, and preserves invocation kind and disposition. Every
  other outcome writes `consumed`, clears the lease and failure hashes, and
  records `consumed_at`. Both paths apply the same idempotent usage records.
- `migrate_legacy_squad_decision(snapshot, bundled_policy,
  invocation_attestation)` is the only v1-to-v2 migration API. It may reconstruct
  a pending v1 decision only from policy compiled from the run's authoritative
  workflow bundle and exact full/manual invocation proof; it never reads policy
  from the currently installed extension. It archives a terminal v1 record only
  through `legacy_decision_history` and never reconstructs terminal operation
  authority. Generic save has no migration authority.

No decision or continuation path calls generic `SquadStateStore.save`.
State-only methods do not fabricate `last_dispatch`; phase-changing or
redispatch operations always use the existing prepared-routing attestation and
advance path. Generic save validates and preserves v1 and v2 records byte-for-
byte and rejects phase, status, recovery, or escalation mutations while an
unresolved v2 decision or unconsumed continuation exists. Failed application
preconditions settle the decision as failed rather than falling back to an
inferred route.

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
committed receipt. A stale outcome, validation exception, or failed operation
precondition proven to occur before any state replacement may discard it
directly. After any state-write, replacement, or durability exception, the
caller reloads state under the existing authority-check helper. The completion
is preserved when the exact pending marker or matching incomplete
`last_dispatch` is durable and is discarded only after both are proven absent.
A committed receipt or reloaded durable authority transfers ownership to the
pending marker, after which normal completion drain owns cleanup.

The state advance writes `pending_controller_completion` and a
`last_dispatch` with `post_dispatch_complete: false` in the same transaction
that resolves the decision and writes an `awaiting_completion` continuation.
The controller drains that completion before clarification projection or
redispatch. Restart, every controller entrypoint, and `spec continue` treat a
valid pending completion as the highest-priority shared recovery action,
regardless of run status or blocked reason; `resume` refuses decision input
until it drains. Successful drain marks the dispatch complete through the
current completion protocol. In the same completion-finalization state
transaction it advances `dispatch_source` and `dispatch_target` continuations to
`ready` and marks `finish_without_dispatch` continuations `consumed` with
`consumed_at`. This consumes full-run gate rejection at `terminal-blocked`, as
well as manual route-and-finish, without waiting for a target executor that will
never run. Source-phase completion follows the route's sealed
`record_completion` value: true only for gate outcomes and false for replay and
safeguard operations.

A completion failure uses the existing standard controller-completion recovery
generation. It does not reopen the resolved decision or dispatch COMMANDER a
second time. After completion recovery succeeds, the controller follows the
operation-specific continuation behavior below.

Operation application has two closed continuation behaviors:

- Replay-source operations are `continue_current_phase`,
  `record_clarification`, and `record_prerequisite`. Their synthetic route has
  `record_completion: false`, `manual_phase_run: false`, and
  `disposition: dispatch_source`. After completion drain and clarification
  projection, the controller claims the `ready` continuation. `full_run`
  re-enters the normal loop at `source_phase`; `manual_phase` calls a dedicated
  `run_prepared_decision_continuation` entrypoint for `source_phase`. That
  entrypoint requires the continuation receipt, skips the existing
  single-phase initialization/reset save, runs one real phase attempt, and
  returns after its authoritative state outcome. A retryable failure leaves the
  continuation `blocked`; a later claim uses the same dedicated manual
  entrypoint rather than `_cmd_run`.
- Route-and-finish operations are `approve_gate`, `reject_gate`,
  `route_declared_transition`, and `select_evidence_backed_issue`. They do not
  redispatch the source. Gate operations use `record_completion: true`;
  safeguard route operations use `record_completion: false`. Their synthetic
  route uses `manual_phase_run: true` only when the durable invocation kind is
  `manual_phase`, because that operation is the real conclusion of the manual
  control point. A full run targeting an executable graph phase uses
  `dispatch_target`, claims the `ready` continuation, and continues from the
  applied target; the target dispatch settles it with its first authoritative
  outcome. A full run targeting a terminal or controller-only phase and every
  manual route use `finish_without_dispatch`; completion drain marks the
  continuation consumed and returns.

Restart, `continue`, and `resume` derive this behavior from the persisted
continuation, not by reinterpreting the resolved operation. A `ready`,
`blocked`, or expired `dispatching` continuation is a shared recovery action
even when run status is `running` and no decision recovery instruction remains.
The classifier handles continuation authority before its generic
`retry_phase` action. A blocked manual continuation can only invoke
`run_prepared_decision_continuation`; it cannot call `_cmd_run`. Process
interruption therefore cannot turn a one-phase request into a full run, lose an
owed source replay, strand a terminal route, or replay a gate that has already
been decided. Exactly-once here means one committed continuation outcome; an
interrupted provider attempt with no authoritative outcome may be retried under
the existing phase-attempt recovery rules.

Migration rules:

1. Existing v1 records remain valid and are consumed unchanged by RE. Generic
   load/save validates and preserves them but never migrates them.
2. The explicit Squad migration API normalizes a pending v1 decision once to v2
   only when its original source phase or blocked reason resolves to the
   policy compiled from the run's authoritative workflow bundle and its
   invocation kind is proven by an attested full-run entrypoint or matching
   persisted manual-dispatch metadata. The
   conversion preserves its question, options, recommendation, blocked phase,
   timestamps, and v1 resume metadata, computes both digests from reconstructed
   static policy and concrete operations, and takes `source_reason_code` from
   the reconstructed policy case. The same transaction replaces durable
   `blocked_reason` and recovery instruction with that controller-owned code.
   Missing policy or invocation authority leaves the pending record on the
   existing legacy compatibility path; conversion never guesses `full_run`.
3. Before sealing a new v2 decision over a resolved or failed v1 active record,
   the explicit API appends the exact sanitized `legacy_decision_history` entry
   and only then replaces the active record. Terminal v1 records are never
   reconstructed into authoritative v2 operations. Pending v1 records are
   nonreplaceable. The history projection sets `source_phase` from exact
   `blocked_decision.blocked_phase`; if that value is absent, it may use
   `resume_metadata.blocked_phase` only when resume metadata has
   `schema_version: 1`, its `answered_at` equals the decision's `resolved_at`,
   its `answer_text` equals the decision's `answer_text`, and any selected option
   ids are either both absent or equal. If neither source is valid,
   migration stops with `legacy_decision_source_missing` manual diagnosis. It
   never substitutes current `state.phase` or `resumed_phase`.
4. The state helper validates and preserves all v2 and continuation fields; it
   must not rebuild a v2 record from `escalation_*` fields on later saves.
5. Legacy `escalation_*` fields remain ingress and terminal-display
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
| `select_evidence_backed_issue` | `issue_snapshot`, `trigger_snapshot`, `evidence_sha256` | apply one controller-read, evidence-backed SAGE suggestion and its exact registered repair route |
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
`issue_snapshot` is an exact immutable object containing `issue_id`, `title`,
`decision_required`, `suggested_decision`, `evidence_basis`, `repair_phase`, and
`recovery_route_id`; all fields are non-empty bounded strings.
`evidence_sha256` covers canonical JSON of that complete object.
`trigger_snapshot` is an exact reason-tagged object. `phase_dispatch_limit`
contains `kind`, `source_phase`, `phase_dispatch_count`, and
`phase_dispatch_limit`; `consecutive_why_fails` contains `kind`,
`source_phase`, `why_fail_count`, `why_failure_baseline_recorded_at`, and
`artifact_progress: false`; `why2_metric_stagnation` contains `kind`,
`source_phase`, `why_fail_count`, `why2_metric_stagnation_count`, and
`certified_metrics_improved: false`. Counts are non-negative integers and the
baseline is a normalized UTC timestamp. The trigger snapshot is included in
`operations_digest`.
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

Successful apply projects the snapshot into the existing issue-resolution
state shape exactly: the selected ledger entry copies `issue_id`, `title`,
`decision_required` to `guidance`, `suggested_decision` to `decision`, and
`repair_phase`; sets `severity: ISSUE`, `status: selected`,
`evidence_backed: true`, and `confidence: controller-validated`; and uses the
sanitized resolver rationale. It also writes `selected_issue_resolution`, the
existing repair baseline with controller timestamp, and the existing recovery
record with source phase, repair phase, and `reason: issue_resolution`.
Apply never reconstructs these fields from mutable `issues.md`.

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

Continuation transitions are also closed:

| Event | Required pre-state | Continuation post-state |
|---|---|---|
| successful decision apply | no older unconsumed continuation | `awaiting_completion` with exact completion and disposition binding |
| successful completion drain for `dispatch_source` or `dispatch_target` | matching pending completion and `awaiting_completion` | `ready` |
| successful completion drain for `finish_without_dispatch` | matching pending completion and `awaiting_completion` | `consumed` |
| initial continuation claim | `ready`, dispatching disposition | `dispatching` with new lease |
| retry continuation claim | `blocked`, matching dispatch and recovery hashes, standard retry attestation, and dispatch phase | `dispatching` with new lease and cleared failure hashes |
| expired continuation reclaim | expired `dispatching` | `dispatching` with replacement lease |
| successful, terminal-failure, or new-decision outcome of exact real dispatch | matching `dispatching` lease | `consumed` with cleared failure hashes |
| retryable-failure outcome of exact real dispatch | matching `dispatching` lease | `blocked` with exact dispatch and recovery hashes; invocation kind and disposition retained |
| process loss before authoritative dispatch outcome | `dispatching` | unchanged until lease expiry, then reclaimable |
| stale continuation result | id, stage, lease, disposition, source, or target mismatch | unchanged |

The operation-specific status effect is closed: `approve_gate`,
`continue_current_phase`, `route_declared_transition`,
`record_clarification`, `record_prerequisite`, and
`select_evidence_backed_issue` require and atomically apply
`blocked -> running`. `reject_gate` requires existing `blocked` state and omits
the status transaction effect, thereby preserving `blocked` without requesting
an unsupported `blocked -> blocked` transition. It routes to
`terminal-blocked` with terminal `blocked_reason: gate_rejected`.
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
bundle builder reads them through `get_full_resolved_config`, normalizes them
into `workflow-config.json`, and the active controller reads only that immutable
bundle value. A dedicated parser applies defaults, rejects non-mappings and
booleans used as integers, and enforces the stated numeric bounds before bundle
creation and again on bundle load.
`lease_ttl_seconds` governs both decision-resolution and continuation-dispatch
leases; only decision-resolution claims consume `max_attempts`.
Malformed installed configuration blocks new bundle creation. Malformed or
unsupported bundled configuration is a non-mutating pre-claim failure:
decision status, instruction, lease, attempt count, phase, and run status remain
unchanged; the CLI reports the exact bundle field and does not reread a mutable
installed correction. The parser never broadly catches an error and substitutes
defaults. Full-run, manual-phase, `continue`, and `resume` controller
construction all use this one parser. Both `extension/echelon-config.yml` and
`extension/config-template.yml` ship the same default section and bounds.

A result applies only if its decision id, status, lease id, static policy
digest, concrete operations digest, and operation preconditions still match.
Stale results are discarded. Expired leases are reclaimable on the next inline
attempt or `continue`.

Inline resolution uses the same claim-and-apply path, so its crash behavior is
identical to `spec continue`.

## COMMANDER Contract

For non-human outcomes, COMMANDER receives only the sealed v2 decision, its
declared context pack, the user request, its allowed operations, and identity
from the committed `DecisionClaimReceipt`. Prompt construction uses the
receipt's lease, phase, revision, and previous-dispatch digest and rejects a
state reload that no longer matches it. COMMANDER returns an exact top-level
`decision_resolution` object:

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
keeps its old contract only for pre-v2 active runs with an authoritative v1
workflow bundle.

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
`operations_digest`. Decision sealing applies only the registry-owned trigger
effects needed to preserve the triggering observation: the dispatch-cap count
and capped phase for `phase_dispatch_limit`; the computed `why_fail_count` and
`why_failure_baseline` for `consecutive_why_fails`; and the computed
`why_fail_count` and `why2_metric_stagnation_count` for
`why2_metric_stagnation`. Those values must equal the sealed
`trigger_snapshot`. No ordinary provider or certificate update is retained.
Successful apply performs the common issue-ledger updates and these
source-reason-specific reset effects atomically:

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
the controller supplies its approve/reject operations and context pack, builds
`PreparedHumanInput`, and invokes the same interception boundary as every other
producer.

## CLI Behavior

- Phase A run selection is deterministic and has no stdin question. `spec run`
  accepts mutually exclusive `--continue-current` and `--new-run`. Without a
  flag, an empty request or a request identical to the active run continues it;
  a different non-empty request starts a new run and preserves the old one.
  `--continue-current` requires a resumable active run and rejects a different
  non-empty request rather than changing or ignoring its task.
  `--new-run` requires a non-empty request and preserves any active run;
  existing `--reset` becomes a deprecated alias for `--new-run`. Supplying both
  modes, continuing with no active run, or any other invalid flag/input
  combination fails before mutation. This removes the current active-run
  `input()` choice instead of creating a pre-run decision model.
- The shared recovery classifier recognizes a valid
  `pending_controller_completion` as `drain_controller_completion` before run
  status, blocked-reason, decision-instruction, or legacy-prose classification.
  Its controller drain first performs any standard pending-publication recovery
  required by that completion. `status` displays `spec continue`; `continue`
  invokes the controller; `resume` refuses input until the completion drains.
- After completion authority, the classifier recognizes `ready`, `blocked`, or
  expired `dispatching` `decision_continuation` before generic `retry_phase` or
  ordinary running dispatch. A `blocked` continuation is claimable only with a
  matching standard retry attestation. The controller resumes only the
  persisted disposition, source/target, and invocation kind; manual continuation
  retries use the dedicated one-phase entrypoint.
- `status` loads the run-local workflow bundle and renders phase names,
  transitions, and the roadmap only from that authoritative graph. It may load
  the installed definition separately to display a drift warning, but never
  substitutes it. An invalid or unsupported bundle renders manual diagnosis
  without guessing the current roadmap.
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
- V2 structured syntax is
  `echelon spec resume --operation <exact-id> [--answer <text>]`.
  Positional text remains compatibility input only when there is exactly one
  generated clarification or exactly one prerequisite operation. `status` and
  `continue` display every exact operation id and label; positional letters and
  list order never carry v2 authority.
- Structured input accepts an exact operation id, or a unique exact label only
  for compatibility. Free text follows the sole-operation and semi-
  recommendation binding rules above. `record_clarification` accepts bounded
  answer text; `record_prerequisite` accepts bounded prerequisite text and
  reruns its sealed verifier before continuation.
- Old runs without v2 decision records retain the existing escalation and
  recovery compatibility paths. This concerns decision schema only: any later
  provider dispatch still requires a valid run-local workflow bundle or the
  exact pristine legacy-unversioned workflow migration described above.
- Before `spec run`, `phase run`, `spec run --next-phase`, `continue`, `resume`,
  or any override mutates phase or dispatches a provider, the shared controller
  guard validates active decision, completion, and continuation authority.
  While a decision is `pending`, `resolving`, or `awaiting_human`, manual phase
  changes and provider dispatch are rejected and only its matching recovery
  action is exposed. An unconsumed continuation similarly permits only its
  exact prepared continuation entrypoint.

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
  inputs, the complete immutable `DispatchDescriptor`, normalized dependency
  dispatch keys, pre-dispatch declaration positions, disjoint parallel proposal
  ownership, executable-entry-local `artifact_effects`, exact
  `presence_by_verdict`, canonical destination and visibility-class overlap,
  and gate outcome edges.
- new `harness.workflow_bundle`, `harness.phase_graph`, and
  `harness.squad_state`: capture and fsync the exact run-local source manifest,
  immutable workflow config, and compiler/prompt/repair semantics versions
  before state creation; persist exact workflow version and digest; load all
  resumed graph, prompt, template, repair, gate, and policy authority through
  `PhaseGraph.from_bundle` and `PromptSourceResolver`; fail closed on an
  unsupported registry version; and permit legacy-unversioned migration only
  for the exact pristine pre-dispatch state.
- new `harness.human_input` and the shared recovery classifier: define
  `PreparedHumanInput`, route provider, gate, safeguard, and registered recovery
  requests through one controller interception function, enforce the v2
  decision/instruction pair, and retain direct legacy classifications only
  under authoritative supported v1 bundle semantics.
- `harness.squad_provider`, `harness.llm_provider`,
  `harness.llm_tool_policy`, `harness.provider_capability`,
  `harness.ai_cli_backend`, the new controller-owned `AiExecutionSandbox`, and
  every AI backend adapter: preserve and attest the exact
  `ProviderExecutionRequest`, `AttemptFilesystem`, `AttemptPathMap`, and
  `AttemptStateProjection`; implement the closed CLI and
  OpenAI-compatible OCI worker adapters, bridge-network declaration,
  digest-pinned runtime profiles, persistent per-run ephemeral credentials, and
  ephemeral home/cache/tmp mounts; declare `token_accounting_mode` and an
  enforceable per-call token limit for hard-budget operation; expose
  `ENFORCED_WRITE_CONTAINMENT` only for
  these OCI adapters; run complete backend-matrix preflight before state
  creation; fail closed for unsupported dispatches; move result-repair call
  orchestration to the controller; and return typed provider-validation
  failures instead of fabricated provider-shaped blocks.
- `harness.image_security`: add the v2 fail-closed digest resolution API. The
  existing fail-open build-sandbox compatibility function remains separate and
  cannot authorize `OciAiExecutionSandbox`.
- `harness.squad_executors` and `harness.prepared_phase_result`: introduce the
  trusted decision envelope, remove provider blocking-contract bypasses, attest
  the complete dispatch descriptor without giving it state authority, route
  prompt/context/extra-file resolution only through `PromptSourceResolver`,
  `AttemptPathMap`, and sanitized `AttemptStateProjection`, remove raw
  `state.json` prompt injection and provider-attempt direct
  state/journal/cost writes, reject complete private-project diffs not covered
  by compiled effects, and accumulate all child
  artifact effects, results, journals, exact per-call usage records, product-
  input, certificate, and state proposals inside one phase-scoped
  `PhaseAttemptTransaction`.
- `harness.squad_publication` and `harness.state_transaction_namespace`: import
  provider-staged upserts and deletes, lower move pairs and
  additive/replacement trees to existing regular-file operations, bind
  begin-time preimages and aggregate effect identity to its one durable marker,
  and register decision, continuation, legacy-history, usage-receipt, and
  safeguard-counter ownership.
- `harness.blocked_decision`, `harness.recovery_instruction`,
  `harness.state_transaction_namespace`, and `harness.squad_state`: implement
  exact v2 records, dual digests, invocation kind, recovery-generation equality,
  clarification and legacy-ledger ownership, exact continuation state,
  `DecisionClaimReceipt`, dedicated decision/migration/continuation CAS methods,
  failure-dispatch and recovery-instruction hashes for blocked continuation
  retry, exact v1 source-phase projection, generic-save mutation guards, the
  shared unlocked advance and idempotent twelve-field usage primitives,
  claim-scoped billing ids, `token_budget_usage`, bounded usage receipts,
  integer micro-USD and unknown-usage counters, operation-specific status
  effects, authority-aware cleanup, and completion-bound application.
- `harness.squad`: centralize interception, autonomy resolution, completion
  preparation/drain and authority ownership, phase-attempt aggregation,
  deterministic parallel-question arbitration, dedicated prepared continuation
  dispatch, disposition-aware terminal completion, invocation-preserving retry,
  declared-order proposal merge, usage-journal recovery, safeguard trigger
  sealing and resets, clarification projection, and the exact split COMMANDER
  contracts.
  Safeguards seal before legacy terminal-phase writes.
- `echelon.cli`: consume v2 instructions through the existing shared recovery
  classifier with continuation-generation binding, prioritize pending
  completion and ready/blocked/expired continuation authority before generic
  phase retry, load the run-local workflow bundle before dispatch, keep manual
  retries on the dedicated one-phase path, guard every full/manual/override
  entrypoint, implement exact `--operation`/`--answer` syntax, replace the
  active-run stdin choice with mutually exclusive `--continue-current` and
  `--new-run` plus deterministic defaults, render `status` roadmap authority
  from the run-local bundle, and route `status`, `continue`, and `resume`
  through controller APIs rather than direct state/file writes.
- `extension/workflow/definition.yaml`: declare the complete producer matrix,
  exact top-level `workflow_contract_version: 2`, policies, result contracts,
  explicit nested ids, valid exact dependencies,
  executable-entry-local `artifact_effects` with complete verdict presence
  mappings for every provider dispatch, question-bearing verdict migration, and
  gate outcomes. In particular, PLAN2's current
  `speckit-echelon-gatekeeper-assess2` dependency is corrected to the declared
  `speckit-echelon-gatekeeper` id before dependency validation is enabled.
- prompt migration follows bundle-declared prompt sources, not filesystem globs.
  `PromptSourceResolver` replaces direct extension-directory reads, result
  template reads, hardcoded repair prompt selection, and raw-state prompt
  injection. For
  each Phase A provider dispatch, inspect only the phase fragment actually
  included by its executor and its referenced agent role file. Retain
  `{spec_dir}`, `{staging_dir}`, `{context_dir}`, `SQUAD_DIR`, and `STAGING_DIR`
  as controller-mapped attempt roots; use `{artifact_effect.<id>}` only in
  dispatch-specific fragments; and remove instructions that reconstruct a
  writable project or run path. Shared multi-mode role files keep mapped root
  aliases. `commander_internal` no-op documents and phase documents intentionally
  excluded by staged prompt assembly, including `phase3-consensus.md`, are not
  mechanically rewritten. Build, RE, and verify-spec documents remain outside
  this Phase A attempt migration.
- `extension/echelon-config.yml` and `extension/config-template.yml`: ship the
  bounded `analysis.decision_resolution` defaults and closed OCI provider
  runtime-profile selection, adapter-specific immutable image digest,
  credential mode, token-accounting mode, enforceable per-call limit, and
  explicit `bridge` AI network mode consumed by the shared strict parser.
- `extension/agents/control/commander.md`: remove recursive/existential human
  escalation and legacy file ownership from v2 instructions; document the
  exact routing, decision-resolution, and explicitly labeled legacy contracts.
- `extension/commands/echelon.resume.md`: replace the direct clarification and
  state-clearing description with the v2 controller submission flow while
  retaining an explicitly labeled pre-v2 compatibility path.

## Verification

Unit tests cover workflow-bundle source/config capture, source hashing,
fsync-before-state ordering, immutable reload after installed extension drift,
compiler/prompt/repair registry selection, rejection of unsupported semantics,
absence of runtime extension/config reads, version/digest state validation,
pristine pre-dispatch legacy-unversioned-to-v2 migration, rejection of every
non-pristine migration condition, migration rollback on preflight or graph
failure, generic-save non-migration, terminal v1 legacy-history archival, and
non-migration when invocation authority is absent.
They cover v2 and continuation preservation across save, generic-save mutation
guards, exact history and audit validation, idempotent bounded history append,
non-evicting clarification-ledger append and capacity failure, decision-case
selection from detached result state with no persisted-state fallback, the
complete existing-producer policy matrix, policy reason codes, static policy
drift, concrete operations drift, immutable dispatch-key derivation and
uniqueness, pre-dispatch and agent declaration-index derivation, dependency-key
compilation and rejection of the current mismatched dependency id, every tagged
operation and trigger descriptor, fixed/generated effective answer selection,
immutable issue snapshots and exact ledger projection, and registered recovery
routes.

Artifact tests cover executable-entry ownership stamping, complete
`presence_by_verdict` mappings, conditional required/optional/forbidden effects,
canonical alias identity, nesting, and visibility-class overlap,
in-project and external read-only `context_dir`,
upsert/delete/move and additive/replacement tree semantics, special-file
rejection, complete private-project diffing and undeclared-change rejection,
deterministic tree lowering to existing file manifest operations, begin-time
preimage capture,
`AttemptFilesystem`/`AttemptPathMap` identity preservation, hidden controller
paths, sanitized `AttemptStateProjection`, shared multi-mode prompts without
unresolved dispatch placeholders, deterministic child-workspace and
non-artifact proposal merge, and one combined publication manifest.

Usage tests cover exact twelve-field started/returned spool records, exclusive
creation, billing-scope uniqueness across retries and claims, usage-id field
agreement, reported/reserved/unknown normalization, conservative
`token_budget_debit`, positive-budget preflight failure without enforceable
accounting, integer micro-USD rounding, unknown-call counters, idempotent
receipts, and pre-call capacity and hard-budget checks. Crash
tests cover loss after pre-call intent fsync, during an orphaned OCI call, after
the initial call but before interpretation, between initial and repair calls,
after repair but before settlement, and during deferred receipt application.
Remaining unit coverage includes clarification projection, prerequisite
verifier behavior, recovery-instruction v1/v2 validation and reason equality,
blocked-continuation failure and recovery hash equality, stale same-phase
recovery rejection, valid and invalid config parsing with no mutation, every
decision, continuation, and Squad status transition, decision and continuation
lease claiming and expiry, retry exhaustion, authority-aware prepared-
completion cleanup, and stale-result rejection. Validator regressions prove
malformed question-bearing `BLOCKED` results cannot use a base-validator fast
path, question-bearing `ESCALATE` is rejected, and provider validation repair
failure becomes the typed controller failure path.

Integration tests cover each producer path in guided, semi, and banzai:
`STOP_AND_ASK` escalation, `BLOCKED` escalation, nested-agent escalation, both
investigator decision cases, human gates, phase-dispatch cap from a phase
without a direct issue-repair edge, consecutive WHY block, metric stagnation,
manual single-phase execution, `status`, `continue`, process interruption at
each durable state, and `resume`. Tests assert that decision interception
occurs through `PreparedHumanInput` before all artifact and non-artifact effects
and ordinary routing, and that every v2 human recovery instruction has one
matching active v2 decision while orphan/mismatched instructions fail closed,
parallel peers are joined and arbitrated in declaration order, multiple peer
questions fail as `ambiguous_parallel_decision`, a nested question abandons all
peer/stage work from that phase attempt, later stages see only validated parent-
attempt output through mapped `{spec_dir}`, `{context_dir}`, and extra-file
paths, providers without enforced containment fail before execution, missing
OCI runtime/profile blocks before run-state creation, host fallback is
impossible, and discarded phase effects are recomputed after redispatch. The
backend matrix runs one contained dispatch through each configured CLI adapter
and the contained OpenAI-compatible worker; digest inspection failure is fail-
closed, refreshed ephemeral credentials survive a repair/retry and are scrubbed
only at terminal cleanup, and bridge egress behavior is explicit. A v1 bundled
run continues with its bundled graph and prompt after the installed extension
becomes v2, while an unversioned run never silently acquires v2 authority. Tests
also assert that `status` renders the bundled roadmap after installed workflow
drift, active-run selection performs no stdin read, the shared Phase A
execution/entry paths contain no direct `input()` call, and
CARTOGRAPHER's staging-to-spec promotion publishes one atomic move without a
canonical provider write, KB proposal trees merge additively, one publication
marker owns provider and controller effects, changed begin-time preimages never
overwrite newer files, ambiguous state-write exceptions never duplicate usage
records, and authority-aware cleanup drains every fsynced usage record.

Lifecycle integration asserts that generic `save` is never used, public
`advance` is not called recursively under the exclusive state lock, every
manual/full/override entrypoint refuses to bypass an unresolved decision,
successful non-rejection operations restore `running`, gate rejection preserves
blocked status without a blocked-to-blocked transition, safeguard trigger
counters and issue evidence survive sealing and reset exactly once, and gate
outcomes cannot leak across checkpoints. Clarification projection survives
audit-history eviction and repairs a post-commit crash. Pending controller
completion drains before every other decision/continuation action; each
continuation stage survives interruption; a manual replay uses the dedicated
prepared entrypoint, a retryable failure leaves it blocked, and `continue`
retries only that phase; a manual route-and-finish returns after its consumed
continuation; a full executable route continues only at its persisted target;
and a full gate rejection consumes at completion without trying to dispatch
`terminal-blocked`. Completion failure does not repeat
COMMANDER resolution, either digest drift fails closed, malformed config does
not claim or mutate a decision, and exact CLI resume syntax cannot mutate
decision state outside the controller. Static contract tests prove generic
routing COMMANDER emits one exact edge-bound outcome and can emit neither a
human question nor `BLOCKED`, v2 COMMANDER cannot write clarification files or
cleanup fields, and the installed COMMANDER/resume documentation no longer
advertises legacy behavior as the v2 path. RE regression tests prove that v1
records and existing RE resume behavior remain unchanged.

The primary invariant is: every Squad decision with a declared policy records
either a controller-validated human or COMMANDER operation, or a bounded
`manual_diagnosis` failure. Banzai never presents a non-prerequisite project
decision directly to a human and never bypasses the controller resolver.
