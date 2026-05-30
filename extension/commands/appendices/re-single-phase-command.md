# Brownfield Single-Phase Command Contract

Shared contract for `speckit.echelon.re-*` commands that execute exactly one brownfield workflow phase.

## Required Context

ALWAYS read `agents/control/commander.md` first.
NEVER dispatch before loading the COMMANDER governance and role-separation rules.

ALWAYS read the calling command's named `workflow/definition.yaml` section before dispatch.
NEVER infer phase routing or outputs from memory.

## Execution

ALWAYS execute only the phase named by the calling command.
NEVER advance to the next transition after the single requested phase completes.

ALWAYS dispatch the phase agent, write the result to `.specify/echelon/re/state.json`, then stop.
NEVER write state anywhere else for these commands.

## Resumption

If `last_dispatch.phase_id` equals the calling command's phase and `post_dispatch_complete: false`, re-run that phase before writing results.
