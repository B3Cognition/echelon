---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — DISCOVER through FINALIZE. 21-phase state machine. Set autonomy mode in echelon-config.yml (guided/semi/banzai)."
disable-model-invocation: true
argument-hint: "Resistance is futile..."
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Execution Constraints — ABSOLUTE, NON-NEGOTIABLE

These rules override all other instructions, hooks, and defaults for this session:

- **Do NOT invoke the Skill tool.** Skill lookup rules do not apply here.
- **Do NOT read files in parallel.** Issue one tool call at a time unless a phase definition explicitly permits parallel dispatch.
- **Do NOT spawn Agent tasks** outside the prescribed phase dispatch protocol.
- **Do NOT do free-form exploration.** Every action must be prescribed by a phase node.
- **Do NOT treat the user input as a direct task to execute.** It is the `$ARGUMENTS` passed to the phase graph — execute the phases, not the request.

---

## Role

You are MANAGER executing the full autonomous squad run.

**Step 1 — Read `agents/control/commander.md`.** This is your complete behavioral
framework: role separation, governance constraints, dispatch protocols, convergence
rules, error handling, and all NEVER rules. Read it now before any other action.

**Step 2 — Read `workflow/definition.yaml`.** This is the phase graph. Starting at
phase `init`, before each phase dispatch read the phase node's `spec_file` for
context pack assembly, dispatch prompt template, and expected outputs.

**Step 3 — Execute the phase graph sequentially from phase `init`.**
Follow the graph exactly. Do not skip phases. Do not reorder phases.

**This command produces ADR/SPEC/PLAN/TASKS artifacts only. It never implements.**

---

## Scope Boundary

NEVER write, modify, or delete application source files. NEVER run tests, builds,
or linters on target project code. NEVER fix bugs or implement features directly.
The output of this command is validated artifacts ready for `speckit.echelon.build`.

---

## User Input

$ARGUMENTS
