---
name: speckit.echelon.change
description: "Handle specification change during build phase"
behavior:
  invocation: explicit
---

## Role

You are ORCHESTRATOR handling a mid-build specification change. Dispatch CHANGE CONTROLLER, assess blast radius, and route the propagation plan before any rework begins.

---

# speckit.echelon.change

Handle a specification change during the build phase by dispatching the speckit-echelon-change-controller (CHANGE CONTROLLER) agent.

## $ARGUMENTS

The change description provided by the user. This should describe:

- What requirement changed (added, modified, or removed)
- Why the change is needed
- Any urgency or priority context

Example: `speckit.echelon.change "FR-012 payment flow now requires 3DS2 authentication instead of 3DS1"`

---

## Prerequisites

Before dispatching, verify:

1. **Build phase is active** — Check `state.json` for `phase: "build"`. If not in build phase, inform the user:
   - If in Phase A (understanding): Changes are free — just update the spec directly.
   - If build has not started: No tasks to impact — update spec and re-plan.
   - If workflow is `CHANGE_PENDING`: continue change handling and resolve re-entry target.

2. **Spec is baselined** — Confirm `spec.md` exists in `.specify/specs/{feature}/`.

3. **Tasks exist** — Confirm `tasks.md` exists with at least one task.

If any prerequisite fails, explain why the change command is not applicable and suggest the correct action.

---

## Steps

### Step 1: Dispatch speckit-echelon-change-controller (CHANGE CONTROLLER)

Compile a context pack for the speckit-echelon-change-controller agent:

- The user's change description (`$ARGUMENTS`)
- Current `spec.md`
- Current `tasks.md` with all task statuses
- Current `estimates.md`
- All ADR files from `.specify/specs/{feature}/adrs/`
- Current `progress-report.md` (if exists)
- `constitution.md`

Use the Agent tool:

- **subagent_type:** `speckit-echelon-change-controller`
- **prompt:**

  ```xml
  <context>
  [include files listed above]
  </context>

  <instructions>
  You are CHANGE CONTROLLER. Analyze the impact of the changes on the current work defined by context pack.
  </instructions>
  ```

### Step 2: Review Impact

Present the change impact report to the user. Highlight:

- **Total cost** — Additional effort required
- **Schedule impact** — Days added to critical path
- **Risk items** — Any re-validation failures or architecture conflicts
- **DONE tasks affected** — These carry the highest rework cost

### Step 3: Await Decision

Ask the user to decide:

- **ACCEPT** — Proceed with the propagation plan
- **DEFER** — Log the change for post-build consideration
- **REJECT** — Discard the change request

### Step 4: Execute Propagation

If ACCEPTED:

1. Update `spec.md` with the changed requirements
2. Update `tasks.md` with new statuses and change references
3. Update `estimates.md` with revised effort figures
4. Log the change to `reasoning-journal.json`
5. Resume build with the propagation plan's task sequence
6. Notify speckit-echelon-progress-tracker (PROGRESS speckit-echelon-tracker (TRACKER)) of the re-baseline

7. Resolve re-entry dispatch target:
   - `BUILD_RESTART` -> resume via `speckit.echelon.build {feature}`
   - `QA_RESTART` -> resume via `speckit.echelon.verify {feature}`

If DEFERRED:

1. Log the change request to `change-impact-report.md` with status DEFERRED
2. Resume build unchanged

If REJECTED:

1. Log the change request to `change-impact-report.md` with status REJECTED
2. Resume build unchanged
