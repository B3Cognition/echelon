# Design: Autonomy Decision Resolution

**Date:** 2026-07-27
**Status:** Approved - ready for implementation plan

## Problem

The squad controller has several ways to create a human-facing stop:

- agents set `escalation_question` and optional `escalation_options`;
- `human_gate` auto-approves in semi and banzai modes;
- controller safeguards such as phase dispatch limits write blocked state directly;
- CLI recovery classifies some blocks from `blocked_reason` and prose.

Only some of these paths invoke COMMANDER in banzai mode.  Consequently a
question can bypass COMMANDER, a banzai run can stop for a human answer, and
the CLI can disagree with controller behavior.

The recently added typed `recovery_instruction` contract establishes the
durable owner of a blocked run's next action.  It must remain controller-owned:
providers cannot write recovery instructions.  This design adds a typed input
for decisions, and has the controller translate it into the existing recovery
contract after applying autonomy policy.

## Goals

1. Every request for a project decision has one typed, validated form.
2. The controller is the only component that chooses between human and
   COMMANDER resolution.
3. Guided, semi, and banzai modes have deterministic, distinct behavior.
4. `status` and `continue` consume the same controller-owned recovery action.
5. Existing `escalation_*` state remains readable while producers migrate.

## Non-goals

- Changing ordinary deterministic failure recovery such as provider waits or
  runtime synchronization.
- Giving COMMANDER authority to perform unavailable technical actions, obtain
  credentials, or assume legal authority.
- Replacing the existing recovery-instruction module with a second recovery
  vocabulary.

## Architecture

```
agent / human_gate / controller safeguard
                 |
                 v
       decision_request (typed input)
                 |
                 v
 SquadController.resolve_pending_decision(mode)
                 |
       +---------+----------+
       |                    |
       v                    v
 COMMANDER             human confirmation
       |                    |
       +---------+----------+
                 v
 recovery_instruction + durable decision audit
                 |
                 v
 CLI status / continue / controller run
```

`decision_request` is a provider-facing request and temporary controller
input.  `recovery_instruction` remains the controller-owned authoritative
description of the next blocked-run action.  The controller creates or clears
both atomically with the state transition that records the decision outcome.

## Decision Request Contract

Persist a versioned `decision_request` object in squad state:

```yaml
decision_request:
  schema_version: 1
  id: "decision-..."
  source_phase: "phase1-what"
  kind: "scope" # scope | product | operational | authority | execution_blocked
  question: "Which supported format should be prioritized?"
  risk: "operational" # operational | material
  options:
    - id: "json"
      label: "Prioritize JSON"
      effect:
        next_phase: "phase1-why1"
  recommended_option: "json"
  recovery_context: {}
```

Validation rules:

- all fields except `recommended_option` and `recovery_context` are required;
- for every kind other than `execution_blocked`, option identifiers are unique
  and every option has an executable, validated effect;
- `recommended_option`, when present, names one option;
- `source_phase` must be a valid non-terminal workflow phase;
- `execution_blocked` describes a concrete unavailable prerequisite and does
  not offer speculative project choices or require an executable option;
- providers may create `decision_request`, but cannot write
  `recovery_instruction`, decision outcomes, or resolver identity.

The controller normalizes a legacy `escalation_question` and
`escalation_options` into a request at load time when no typed request exists.
It preserves the legacy fields as compatibility projections until all workflow
definitions and prompts have migrated.

## Autonomy Policy

| Mode | Operational decision | Material decision | Execution blocked |
|---|---|---|---|
| guided | Human chooses | Human chooses | Human resolves prerequisite |
| semi | COMMANDER chooses and records why | COMMANDER recommends; human confirms | Human resolves prerequisite |
| banzai | COMMANDER chooses and records why | COMMANDER chooses, records assumptions | Human resolves prerequisite |

Material decisions include irreversible scope, product, legal, cost, or
external-authority choices.  Operational decisions are bounded and reversible
within stated project intent.

In banzai, risk alone never changes a decision into a human stop.  Only a
concrete inability to execute can require human input.  A malformed request or
failed COMMANDER resolution is a controller failure, not an implicit approval.

## Resolution Flow

`SquadController.resolve_pending_decision(mode)` is the single interception
point.  It runs:

1. before normal dispatch when persisted state has a pending request;
2. immediately after an executor or transition produces a request;
3. in the phase-dispatch-limit and other controller-generated blocking paths;
4. in `run_single_phase`, before it returns a blocked result;
5. when `spec continue` resumes a blocked run.

For a human outcome, the controller persists the request and emits a typed
`await_human_answer` recovery instruction with `requires_human_input: true`.
For a COMMANDER outcome, it dispatches a structured decision judgment, validates
the selected option, journals the rationale and assumptions, applies the
option's executable effect, and persists the ordinary retry/continuation state.

`human_gate` becomes only a decision-request producer.  It must not auto-approve
in semi or banzai modes.  Phase dispatch limits and quality/convergence blocks
likewise create a typed request rather than writing a question then returning
through a terminal path.

## Commander Contract

COMMANDER receives the request, relevant state, source phase, user intent, and
the permitted options.  It returns a structured result with:

- `selected_option`, or an explicit `execution_blocked` result;
- rationale;
- assumptions made;
- resolver identity (`COMMANDER-semi` or `COMMANDER-banzai`).

COMMANDER may select only one supplied option.  It cannot retain an
`escalation_question` as an alternative outcome.  For semi material decisions,
its selected option is stored as the recommendation and the controller creates
the human-confirmation recovery instruction.

The controller uses a bounded judgment retry budget.  Invalid results or
exhaustion persist `manual_diagnosis` and a diagnostic audit entry.  They never
fall through to an arbitrary route or auto-approved gate.

## Recovery Integration

Extend the current `harness.recovery_instruction` vocabulary only where
necessary; preserve its strict versioned validation and controller ownership.
The existing meaning of `requires_human_input` remains literal:

- human outcomes persist `await_human_answer` with `true`;
- banzai COMMANDER outcomes do not persist a human-input instruction;
- controller/COMMANDER failures use `manual_diagnosis` with `false` and retain
  diagnostics for an operator.

CLI classification reads the typed recovery instruction first, as it does for
controller failures today.  Legacy reason/prose heuristics are a read-only
adapter only.  `spec continue` invokes the controller resolver for a pending
decision; it must not independently convert a decision request into manual
issue resolution.  `spec resume` is accepted only when the current instruction
is `await_human_answer`.

## Durable Audit and Cleanup

Every resolution records the original request id, mode, source phase, resolver,
selected option, rationale, assumptions, and confirmation status in the
existing journal/run evidence.  Successful application clears the pending
request and stale recovery instruction together.  A pending human confirmation
retains both until the response is validated and applied.

## Error Handling

- Invalid request shape or option effect: block with `manual_diagnosis`.
- Invalid COMMANDER result: retry within the bounded budget, then block with
  `manual_diagnosis`.
- `execution_blocked`: retain a human intervention/recovery action containing
  the factual missing prerequisite.
- Legacy escalation without executable options: preserve context but require
  controller normalization to produce a safe human request or diagnostic;
  never invent a route.

## Migration

1. Add the decision-request schema, validation, controller ownership rules,
   and legacy escalation adapter.
2. Route existing agent escalations through the resolver while retaining the
   legacy fields as projections.
3. Convert `human_gate`, phase-dispatch caps, and quality/convergence blockers
   into typed producers.
4. Update COMMANDER instructions to return structured decisions and remove the
   instruction that permits banzai to leave an existential escalation pending.
5. Make CLI continue/resume consume controller decisions and typed recovery
   instructions exclusively; retain legacy recovery heuristics only for old
   persisted runs.
6. Remove legacy projections only after workflow definitions, prompts, and
   active-run compatibility support no longer require them.

## Verification

Unit tests cover decision-request validation, policy classification, option
effect validation, recovery-instruction mapping, legacy normalization, and
COMMANDER-result validation.

Integration tests cover agent-originated escalation, `human_gate`, phase
dispatch caps, quality/convergence blocks, `run_single_phase`, `spec continue`,
and `spec resume` in all three autonomy modes.

The core invariant test is: every non-`execution_blocked` decision request in
banzai records either a validated COMMANDER choice or a bounded
`manual_diagnosis` failure.  It never surfaces a human decision, auto-approves,
or bypasses resolution.
