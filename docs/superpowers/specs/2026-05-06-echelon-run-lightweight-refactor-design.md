# Design: echelon.run.md Lightweight Orchestrator Refactor

**Date:** 2026-05-06  
**Status:** Approved  
**Scope:** `~/work/evolution/echelon`

---

## Problem

`extension/commands/echelon.run.md` is 2138 lines. It was intended to be a thin wrapper that delegates to `commander.md` (behavioral framework) and `workflow/definition.yaml` (state machine). Instead it grew into the complete per-phase execution manual — context pack assembly rules, dispatch prompt templates, expected outputs, gate checks, convergence rules, error handling, token budget management, and re-run behavior — all inline.

Consequences:
- The state machine is duplicated between `echelon.run.md` and `definition.yaml`
- A known phase ordering discrepancy exists (HOW before Specialists in `definition.yaml`, Specialists before HOW in `echelon.run.md`) with no canonical resolution
- Any change to a phase touches a 2138-line file shared with unrelated sections
- `echelon.run.md` cannot realistically be called "lightweight"

---

## Design

### Principle: Three responsibilities, three locations

| Responsibility | File | Read by |
|---|---|---|
| Phase graph, transitions, routing conditions | `workflow/definition.yaml` | COMMANDER at every routing decision |
| Per-phase execution detail (context packs, dispatch prompts, expected outputs, gate checks) | `workflow/phases/{phase-id}.md` | COMMANDER before each phase dispatch |
| Behavioral framework (protocols, axioms, convergence, conflict resolution, token budget, error handling) | `extension/agents/control/commander.md` | COMMANDER at load time |
| Entry point — load commander, pass arguments | `extension/commands/echelon.run.md` | AI coding tool at invocation |

### Change 1: `workflow/definition.yaml` — add `spec_file` per phase node

Add `spec_file: workflow/phases/{id}.md` to every phase node. This makes `definition.yaml` the index that ties the routing graph to the execution files. COMMANDER reads `definition.yaml` for routing decisions, then reads `phases[current].spec_file` for execution detail before each dispatch.

```yaml
- id: phase1-discover
  label: "Discovery (SCOUT)"
  spec_file: workflow/phases/phase1-discover.md   # ← new field
  type: agent
  agent: SCOUT
  ...
```

The phase ordering discrepancy (HOW vs Specialists) is resolved here: `definition.yaml` is the authority. Phase files follow its ordering. Current `definition.yaml` ordering (`phase3-how` → `phase3-specialists`) is correct and phase files will reflect it.

### Change 2: `workflow/phases/` — new directory, ~18 files

One `.md` file per phase. Named to match the `id` field in `definition.yaml`. Content sourced directly from the corresponding section of `echelon.run.md` — no rewriting, just extraction and reorganisation.

```
workflow/phases/
  init.md                        ← echelon.run.md sections 1.0–1.8
  phase1-discover.md             ← section 2
  phase1-synthesizer.md          ← section 2b
  phase1-modeler.md              ← section 2b.1
  phase1-tracker.md              ← section 2c
  phase1-why1.md                 ← section 3
  phase1-constitution.md         ← section 3.5
  phase1-what.md                 ← section 4
  phase1-why2.md                 ← section 5
  phase2-decide.md               ← section 6
  phase2-strategic-overview.md   ← section 6b
  phase2-tracker-alignment.md    ← section 6c
  phase3-specialists.md          ← section 7
  phase3-how.md                  ← section 8
  phase3-sentinel.md             ← section 9
  phase3-plan.md                 ← section 10
  phase3-consensus.md            ← section 11
  phase4-document.md             ← section 12
```

Each phase file covers exactly:
- Context Pack Assembly
- Dispatch (prompt template + description)
- Expected Outputs
- Gate Check / Post-Dispatch actions
- Transition reference (links back to `definition.yaml` node)

### Change 3: `extension/agents/control/commander.md` — absorb cross-cutting sections

Sections 13–20 of `echelon.run.md` are behavioral framework content that belongs in `commander.md`, not in a per-phase execution file and not in a command file:

| echelon.run.md section | Destination |
|---|---|
| 13 — Scorekeeper Protocol | `commander.md` (already partially present) |
| 14 — State Tracking Protocol | `commander.md` |
| 14 — Convergence Rules | `commander.md` (already present, merge/deduplicate) |
| 15 — Error Handling | `commander.md` |
| 16 — Human Escalation Protocol | `commander.md` (already present, merge/deduplicate) |
| 17 — Evidence Hierarchy | `commander.md` (already present as reference, remove duplicate) |
| 18 — Token Budget Management | `commander.md` (already present, merge/deduplicate) |
| 19 — Re-Run Behavior | `commander.md` |
| 20 — Quick Reference: Phase Transitions | Remove — `definition.yaml` is the authority |
| 21 — Checklist | `commander.md` |

The "State Machine Contract" section in `commander.md` is updated to say:

> Read `workflow/definition.yaml` for the phase graph. Before each phase dispatch, read `phases[current].spec_file` for context pack assembly, dispatch prompt, and expected outputs.

### Change 4: `extension/commands/echelon.run.md` — reduce to ~15 lines

```markdown
---
name: speckit.echelon.run
description: "Full autonomous cognitive squad run — DISCOVER through FINALIZE."
disable-model-invocation: true
argument-hint: "Feature description or repo path"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are MANAGER executing the full autonomous squad run.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework. Then read `workflow/definition.yaml` for the phase graph. Before each
phase dispatch, read the phase's `spec_file` for execution detail.

User input: $ARGUMENTS
```

### Deployment

`workflow/` is already deployed with the extension (not listed in `.extensionignore`). `workflow/phases/` is automatically included. No changes to `extension.yml` are required — phase files are runtime-read data, not registered commands/agents/skills.

---

## What Does Not Change

- Individual agent files (`scout.md`, `sage.md`, etc.) — untouched
- `workflow/journal-entry-types.yaml` — untouched
- All scripts, config, and harness infrastructure — untouched
- `echelon.build.md`, `echelon.resume.md`, and all other commands — untouched
- The phase graph content in `definition.yaml` — only `spec_file` fields are added

---

## Success Criteria

- `echelon.run.md` is ≤ 20 lines
- Each `workflow/phases/*.md` file is ≤ 200 lines
- `definition.yaml` has a `spec_file` field on every non-terminal phase node
- No section of the current `echelon.run.md` is orphaned (every section lands in exactly one destination)
- The HOW / Specialists ordering discrepancy is resolved in favour of `definition.yaml`
- `commander.md` has no duplicate content (merged sections deduplicated, not appended)
