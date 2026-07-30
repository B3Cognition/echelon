# Standard Failure Recovery Design

## Goal

Give every blocked Echelon run one controller-owned, typed recovery instruction
that `spec status`, `spec continue`, and the controller interpret consistently.
Unknown failures must preserve diagnostics and request manual diagnosis; they
must never guess that a rewind or human answer is required.

## Recovery Instruction

Blocked state may contain:

```yaml
recovery_instruction:
  schema_version: 1
  kind: sync_runtime_then_retry
  reason_code: controller_state_contract_validation_failed
  phase: phase1-why2
  requires_human_input: false
```

The day-one `kind` vocabulary is:

- `retry_phase`
- `sync_runtime_then_retry`
- `await_human_answer`
- `resolve_issue`
- `safe_rewind`
- `manual_repair`
- `increase_budget`
- `wait_for_provider`
- `manual_diagnosis`

The instruction contains semantics, not display copy or shell commands. The CLI
owns rendering commands. The state transaction owns writing and removing the
instruction; provider results cannot set it.

## Failure Flow

The `harness.recovery_instruction` module is deliberately separate from
`harness.recovery`, which owns delivery/build commit salvage.

The controller records a recovery instruction atomically with a blocked
diagnostic. A controller-state-contract failure records
`sync_runtime_then_retry` for the phase whose result could not be committed.
The failed phase remains incomplete.

`spec status` reads the instruction and shows the exact next action.
`spec continue` validates the action's precondition:

- If the installed extension has changed or missing source files, it asks the
  operator to update the extension and does not dispatch an agent.
- If the extension is compatible, it retries the recorded phase.
- Extra installed files do not constitute an incompatible runtime because they
  cannot remove or alter a required contract.

After a successful state advance, the transaction removes the stale recovery
instruction. A repeated failure replaces it with a fresh instruction.

## Supersession

`blocked_reason`, its diagnostic fields, and `recovery_instruction` are one
recovery generation. Whenever a controller transaction records a newer block,
it must atomically:

1. remove diagnostics owned by the previous generation;
2. write the new durable reason and any current diagnostic;
3. replace the old instruction with one whose `reason_code` matches the new
   durable reason.

Trusted executor blocks such as `missing_phase_outputs` use `retry_phase`.
Their phase-output repair payload remains controller-owned context and is not
added to provider state-update allowlists.

Readers validate generation consistency. For a current-format state, a
`recovery_instruction.reason_code` that differs from `blocked_reason` is
invalid and cannot drive routing. The read-only legacy adapter may reconcile a
known older state when the current durable reason and its typed evidence are
complete. In particular, a valid `phase_output_recovery` record supersedes an
older controller-contract instruction and yields `retry_phase` for the
recorded repair phase.

Pending background workflows, including issue resolution, do not override a
newer typed recovery instruction. They remain persisted and resume after the
immediate recovery action succeeds.

## Compatibility

Existing runs without `recovery_instruction` use a legacy adapter. The adapter
maps known state to the typed vocabulary but does not write state merely to
render status. The current
`controller_state_contract_validation_failed` state maps to
`sync_runtime_then_retry` using the current phase, not `last_dispatch`, because
the rejected dispatch was intentionally never published as `last_dispatch`.

Existing special recovery paths remain intact while their producers are
migrated. The typed vocabulary is complete from the first release; production
evidence may refine eligibility checks and diagnostics without inventing
unstructured recovery commands.

## Safety

- Recovery phase IDs must be non-empty workflow phases and cannot be
  `terminal-blocked`.
- Human input is required only for `await_human_answer` and `resolve_issue`.
- Runtime reconciliation never rewinds artifacts.
- Unknown or malformed instructions become `manual_diagnosis`.
- Mismatched recovery generations never execute the stale instruction.
- Recovery execution is idempotent: retrying clears the consumed block before
  dispatch, and a new failure writes a new instruction.

## Verification

Tests cover instruction validation, atomic persistence with controller contract
diagnostics, legacy-state adaptation, compatible and incompatible runtime
handling, `status` output, and `continue` dispatch selection. The active
`md_distribution` state is used only for read-only classification verification;
the test suite must not launch its provider.
