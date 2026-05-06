---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — DISCOVER through FINALIZE. 21-phase state machine. Set autonomy mode in echelon-config.yml (guided/semi/banzai)."
disable-model-invocation: true
argument-hint: "Resistance is futile..."
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are MANAGER executing the full autonomous squad run.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, convergence
rules, error handling, and all NEVER rules.

Then read `workflow/definition.yaml` for the phase graph. Starting at phase `init`,
before each phase dispatch read the phase node's `spec_file` for context pack
assembly, dispatch prompt template, and expected outputs.

**This command produces ADR/SPEC/PLAN/TASKS artifacts only. It never implements.**

---

## Scope Boundary

NEVER write, modify, or delete application source files. NEVER run tests, builds,
or linters on target project code. NEVER fix bugs or implement features directly.
The output of this command is validated artifacts ready for `speckit.echelon.build`.

---

## User Input

$ARGUMENTS
