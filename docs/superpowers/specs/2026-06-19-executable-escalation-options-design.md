# Executable Escalation Options Design

## Goal

Escalation prompts must only offer choices that the harness can execute, and `echelon resume` must apply the selected choice as structured control flow rather than preserving it as inert text.

## Problem

A checkpoint escalation recommended returning to `phase1-what`, but the checkpoint workflow only had a forward transition to `phase2-decide`. The resume command wrote the user answer to `staging/user-clarifications.md`, cleared the block, and reran the same checkpoint. Because the answer was not mapped to an executable route, the run advanced into planning while stale WHY2 blockers still told `echelon status` to return to CARTOGRAPHER.

## Design

Add a small escalation-option contract carried in `state.json`:

- `escalation_options`: list of offered actions.
- Each option has an `id`, `label`, and optional `next_phase`.
- `echelon resume` resolves the user answer to one option by id, label, or A/B/C position.
- If the option has `next_phase`, the phase must exist in the workflow graph before the run continues.
- Invalid or ambiguous answers keep the run blocked instead of guessing.
- Escalations without structured options are rejected by `echelon resume`; text-only prompts are not executable and must be regenerated or rewound.

## Status Reconciliation

`echelon status` should not report old quality-gate blockers once the active squad state has advanced past the phase that produced those blockers. If the run is done and has already completed HOW/PLAN artifacts, status should surface the current executable state first. Stale quality-gate failures can still appear as warnings, but they must not claim the next step is `echelon continue` back to CARTOGRAPHER unless the current state is actually blocked on that route.

## Tests

Regression tests cover:

- Resume option `A` routes to `phase1-what` when the blocked state offered that executable option.
- Resume refuses an option whose `next_phase` is not in the phase graph and keeps the run blocked.
- Status does not let stale WHY2 quality gates override a completed current state.
