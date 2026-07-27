# Executor Block Provenance Design

## Problem

Agent executors validate provider output before checking required artifacts.
When required artifacts are absent, an executor replaces the validated provider
result with a controller-generated `BLOCKED` result containing recovery data
such as `missing_outputs` and `recovery_state_updates`.

`SquadController` currently treats that replacement as raw provider output and
passes it through provider ownership validation. Recovery keys are intentionally
not in phase provider allowlists, so preparation fails with
`controller_state_contract_validation_failed`. Retrying repeats the same
failure. The behavior is independent of installation method.

## Design

Introduce an immutable `ExecutorBlockedResult` envelope in
`harness.squad_executors`. It contains:

- the sanitized block reason;
- the controller-generated `SquadAgentResult` used by existing blocked-state
  persistence;
- no routing or state-store write authority.

Only executor code constructs this envelope, and only after the underlying
provider result has passed the phase result contract. `SquadController`
recognizes the envelope immediately after executor dispatch, captures the
current routing snapshot, and persists it through the existing
`_block_after_executor_failure` transaction. Ordinary `SquadAgentResult`
instances continue through provider/controller preparation unchanged.

This separates provenance by type instead of adding a trusted flag to an
untrusted result object.

## Scope

All executor-generated recovery blocks that contain controller recovery
metadata use the envelope:

- required phase outputs are missing;
- an evidence inventory is invalid;
- a consensus prerequisite is missing.

Provider-originated `BLOCKED` results are not wrapped and remain subject to full
provider ownership validation.

## Recovery Behavior

For the active failure:

1. `phase1-what` returns a valid provider result.
2. The executor notices that `requirements-overview.md` is missing.
3. It returns `ExecutorBlockedResult(reason="missing_phase_outputs", ...)`.
4. The controller persists `blocked_reason=missing_phase_outputs`,
   `missing_outputs`, and `phase_output_recovery`.
5. `echelon spec continue` retries `phase1-what` with targeted output-repair
   context.

No rewind, runtime sync, or manual state editing is required.

## Safety

- Providers cannot claim the trusted envelope through `echelon_result`.
- The envelope does not write state directly.
- The existing routing snapshot and state-store transaction remain the only
  persistence path.
- Unknown or malformed internal block reasons fail closed.
- Provider ownership allowlists are not broadened.

## Verification

An integration regression must drive a real `SquadController` with an agent
result that omits one mandatory phase artifact. It must assert:

- the run blocks with `missing_phase_outputs`;
- the controller contract diagnostic and typed contract recovery instruction
  are absent;
- the missing artifact and prior valid routing updates are preserved in
  `phase_output_recovery`;
- the phase is not marked complete.

Executor tests continue to verify exact recovery payloads. Provider-injected
recovery keys must still fail ownership validation.
