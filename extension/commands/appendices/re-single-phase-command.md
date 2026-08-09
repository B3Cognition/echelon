# Brownfield Single-Phase Command Contract

Shared contract for `echelon.re-*` commands that execute exactly one brownfield workflow phase.

## Required Context

ALWAYS use the invoking command's declared workflow section and phase id as the
authoritative routing contract.
NEVER read `agents/control/commander.md` or `workflow/definition.yaml` to infer
governance, routing, or outputs for these single-phase commands.

ALWAYS use the resolved RE state path and output directory provided by the
invoking Echelon command context.
NEVER infer phase routing or outputs from memory.

## Execution

ALWAYS execute only the phase named by the calling command.
NEVER advance to the next transition after the single requested phase completes.

ALWAYS dispatch the phase agent, write the result to the resolved RE `state.json`, then stop.
NEVER write state outside the resolved RE output directory for these commands.

## Resumption

If `last_dispatch.phase_id` equals the calling command's phase and `post_dispatch_complete: false`, re-run that phase before writing results.
