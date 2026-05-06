# echelon.run.md Lightweight Orchestrator Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `extension/commands/echelon.run.md` from 2138 lines to ~15 lines by extracting per-phase execution detail into `workflow/phases/` and absorbing cross-cutting behavioral sections into `commander.md`.

**Architecture:** Content-only refactor — no logic changes, only relocation. Phase execution detail (context packs, dispatch prompts, expected outputs, gate checks) moves to `workflow/phases/{phase-id}.md`. COMMANDER behavioral framework stays in `commander.md` and absorbs cross-cutting sections currently duplicated in `echelon.run.md`. `definition.yaml` gets a `spec_file:` field per phase node linking graph to execution file.

**Tech Stack:** Markdown, YAML. No code compilation or test runner — verification is grep/wc/diff.

**Reference spec:** `docs/superpowers/specs/2026-05-06-echelon-run-lightweight-refactor-design.md`

**Source document:** `extension/commands/echelon.run.md` — sections are referenced by their `##` heading throughout this plan.

---

## File Map

**Create:**
```
workflow/phases/
  init.md
  phase1-discover.md
  phase1-synthesizer.md
  phase1-modeler.md
  phase1-tracker.md
  phase1-why1.md
  phase1-constitution.md
  phase1-what.md
  phase1-why2.md
  phase2-decide.md
  phase2-strategic-overview.md
  phase2-tracker-alignment.md
  phase3-specialists.md
  phase3-how.md
  phase3-sentinel.md
  phase3-plan.md
  phase3-consensus.md
  phase4-document.md
```

**Modify:**
```
workflow/definition.yaml                          add spec_file: per phase node
extension/agents/control/commander.md             absorb sections 13–21; update State Machine Contract
extension/commands/echelon.run.md                 replace body with thin wrapper
```

---

## Task 1: Create `workflow/phases/` and extract `init.md`

Content source: `echelon.run.md` section `## 1. Initialization (INIT)` — all subsections 1.0 through 1.8 inclusive, including "Spec-kit Availability", "Preflight: KB Evolution Validation".

**Files:**
- Create: `workflow/phases/init.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p /Users/michalbachorik/work/evolution/echelon/workflow/phases
```

- [ ] **Step 2: Verify directory exists**

```bash
ls /Users/michalbachorik/work/evolution/echelon/workflow/phases
```

Expected: empty directory listing (no error).

- [ ] **Step 3: Create `workflow/phases/init.md`**

Create the file with this header, then paste the full content of `echelon.run.md` section `## 1. Initialization (INIT)` verbatim below it:

```markdown
# Phase: init
# Source: echelon.run.md §1 — Initialization (INIT)
# Read by: COMMANDER before starting any phase dispatch

```

Copy the content from `echelon.run.md` starting at `## 1. Initialization (INIT)` and ending just before `## 2. DISCOVER Phase`. Include all subsections: 1.0 Anchor Project Root, 1.1 Detect Greenfield vs Brownfield, 1.2 Create Staging Area, 1.3 Initialize State, 1.4 Initialize Staging Reasoning Journal, 1.5 Load Prior Run Data, 1.6 Load Configuration, 1.7 Check Constitution Status, Spec-kit Availability, Preflight: KB Evolution Validation, 1.8 GOLDDIGGER Mode 1 dispatch.

- [ ] **Step 4: Verify content was extracted**

```bash
grep -c "1\." /Users/michalbachorik/work/evolution/echelon/workflow/phases/init.md
```

Expected: multiple matches (subsections 1.0–1.8 are present).

```bash
grep "GOLDDIGGER Mode 1" /Users/michalbachorik/work/evolution/echelon/workflow/phases/init.md
```

Expected: line found (confirms 1.8 is present).

- [ ] **Step 5: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/init.md
git commit -m "refactor: extract init phase to workflow/phases/init.md"
```

---

## Task 2: Extract phase1 — DISCOVER through WHY1

**Files:**
- Create: `workflow/phases/phase1-discover.md`
- Create: `workflow/phases/phase1-synthesizer.md`
- Create: `workflow/phases/phase1-modeler.md`
- Create: `workflow/phases/phase1-tracker.md`
- Create: `workflow/phases/phase1-why1.md`

- [ ] **Step 1: Create `workflow/phases/phase1-discover.md`**

Header:
```markdown
# Phase: phase1-discover
# Source: echelon.run.md §2 — DISCOVER Phase (UNDERSTAND)
# Agent: SCOUT
# Read by: COMMANDER before dispatching SCOUT
```

Copy content from `echelon.run.md` section `## 2. DISCOVER Phase (UNDERSTAND)` through (not including) `## 2b. SYNTHESIZER Phase`.

- [ ] **Step 2: Create `workflow/phases/phase1-synthesizer.md`**

Header:
```markdown
# Phase: phase1-synthesizer
# Source: echelon.run.md §2b — SYNTHESIZER Phase
# Agent: SYNTHESIZER
# Read by: COMMANDER before dispatching SYNTHESIZER
```

Copy content from `## 2b. SYNTHESIZER Phase` through (not including) `## 2b.1`.

- [ ] **Step 3: Create `workflow/phases/phase1-modeler.md`**

Header:
```markdown
# Phase: phase1-modeler
# Source: echelon.run.md §2b.1 — Dispatch MODELER
# Agent: MODELER
# Read by: COMMANDER before dispatching MODELER
```

Copy content from `## 2b.1 Dispatch MODELER — Initial Codebase Map` through (not including) `## 2c. TRACKER`.

- [ ] **Step 4: Create `workflow/phases/phase1-tracker.md`**

Header:
```markdown
# Phase: phase1-tracker
# Source: echelon.run.md §2c — TRACKER Intent Model Capture
# Agent: TRACKER
# Read by: COMMANDER before dispatching TRACKER
```

Copy content from `## 2c. TRACKER — Intent Model Capture` through (not including) `## 3. WHY1 Phase`.

- [ ] **Step 5: Create `workflow/phases/phase1-why1.md`**

Header:
```markdown
# Phase: phase1-why1
# Source: echelon.run.md §3 — WHY1 Phase (Assumption Challenge)
# Agent: SAGE (mode: WHY1)
# Read by: COMMANDER before dispatching SAGE WHY1
```

Copy content from `## 3. WHY1 Phase (Assumption Challenge — UNDERSTAND)` through (not including) `## 3.5 Constitution Creation`.

- [ ] **Step 6: Verify all five files exist with expected content**

```bash
for f in phase1-discover phase1-synthesizer phase1-modeler phase1-tracker phase1-why1; do
  echo "=== $f ===" && grep -m1 "Agent:" /Users/michalbachorik/work/evolution/echelon/workflow/phases/${f}.md
done
```

Expected: each file prints its `# Agent:` header line.

```bash
grep "SCOUT" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-discover.md | head -3
grep "SYNTHESIZER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-synthesizer.md | head -1
grep "MODELER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-modeler.md | head -1
grep "TRACKER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-tracker.md | head -1
grep "SAGE" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-why1.md | head -1
```

Expected: each grep returns a match.

- [ ] **Step 7: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/phase1-discover.md workflow/phases/phase1-synthesizer.md \
        workflow/phases/phase1-modeler.md workflow/phases/phase1-tracker.md \
        workflow/phases/phase1-why1.md
git commit -m "refactor: extract phase1-discover through phase1-why1 to workflow/phases/"
```

---

## Task 3: Extract phase1 — Constitution through WHY2

**Files:**
- Create: `workflow/phases/phase1-constitution.md`
- Create: `workflow/phases/phase1-what.md`
- Create: `workflow/phases/phase1-why2.md`

- [ ] **Step 1: Create `workflow/phases/phase1-constitution.md`**

Header:
```markdown
# Phase: phase1-constitution
# Source: echelon.run.md §3.5 — Constitution Creation
# Agent: COMMANDER internal (calls speckit.constitution)
# Read by: COMMANDER — this is a commander_internal phase
```

Copy content from `## 3.5 Constitution Creation (Bridge UNDERSTAND → DECIDE)` through (not including) `## 4. WHAT Phase`.

- [ ] **Step 2: Create `workflow/phases/phase1-what.md`**

Header:
```markdown
# Phase: phase1-what
# Source: echelon.run.md §4 — WHAT Phase (Requirements Definition)
# Agent: CARTOGRAPHER
# Read by: COMMANDER before dispatching CARTOGRAPHER
```

Copy content from `## 4. WHAT Phase (Requirements Definition)` through (not including) `## 5. WHY2 Phase`.

- [ ] **Step 3: Create `workflow/phases/phase1-why2.md`**

Header:
```markdown
# Phase: phase1-why2
# Source: echelon.run.md §5 — WHY2 Phase (Spec Validation)
# Agent: SAGE (mode: WHY2)
# Read by: COMMANDER before dispatching SAGE WHY2
```

Copy content from `## 5. WHY2 Phase (Spec Validation)` through (not including) `## 6. ASSESS Phase`.

- [ ] **Step 4: Verify**

```bash
grep "speckit.constitution" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-constitution.md | head -1
grep "CARTOGRAPHER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-what.md | head -1
grep "Understanding" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase1-why2.md | head -1
```

Expected: each grep returns a match.

- [ ] **Step 5: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/phase1-constitution.md workflow/phases/phase1-what.md \
        workflow/phases/phase1-why2.md
git commit -m "refactor: extract phase1-constitution through phase1-why2 to workflow/phases/"
```

---

## Task 4: Extract phase2 files

**Files:**
- Create: `workflow/phases/phase2-decide.md`
- Create: `workflow/phases/phase2-strategic-overview.md`
- Create: `workflow/phases/phase2-tracker-alignment.md`

- [ ] **Step 1: Create `workflow/phases/phase2-decide.md`**

Header:
```markdown
# Phase: phase2-decide
# Source: echelon.run.md §6 — ASSESS Phase (Kill Gate)
# Agent: GATEKEEPER
# Read by: COMMANDER before dispatching GATEKEEPER
```

Copy content from `## 6. ASSESS Phase (Kill Gate)` through (not including) `### 6b. STRATEGIC OVERVIEW`.

- [ ] **Step 2: Create `workflow/phases/phase2-strategic-overview.md`**

Header:
```markdown
# Phase: phase2-strategic-overview
# Source: echelon.run.md §6b — STRATEGIC OVERVIEW (Risk Map)
# Agent: STRATEGIST
# Read by: COMMANDER before dispatching STRATEGIST
```

Copy content from `### 6b. STRATEGIC OVERVIEW (Risk Map)` through (not including) `### 6c. TRACKER`.

- [ ] **Step 3: Create `workflow/phases/phase2-tracker-alignment.md`**

Header:
```markdown
# Phase: phase2-tracker-alignment
# Source: echelon.run.md §6c — TRACKER Intent Alignment Check
# Agent: TRACKER (mode: alignment-check)
# Read by: COMMANDER before dispatching TRACKER for alignment check
```

Copy content from `### 6c. TRACKER — Intent Alignment Check` through (not including) `## 7. Specialist Summoning`.

- [ ] **Step 4: Verify**

```bash
grep "GATEKEEPER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase2-decide.md | head -1
grep "STRATEGIST" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase2-strategic-overview.md | head -1
grep "alignment-check" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase2-tracker-alignment.md | head -1
```

Expected: each grep returns a match.

- [ ] **Step 5: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/phase2-decide.md workflow/phases/phase2-strategic-overview.md \
        workflow/phases/phase2-tracker-alignment.md
git commit -m "refactor: extract phase2 files to workflow/phases/"
```

---

## Task 5: Extract phase3 files

**Files:**
- Create: `workflow/phases/phase3-specialists.md`
- Create: `workflow/phases/phase3-how.md`
- Create: `workflow/phases/phase3-sentinel.md`
- Create: `workflow/phases/phase3-plan.md`
- Create: `workflow/phases/phase3-consensus.md`

Note: `definition.yaml` ordering is `phase3-how → phase3-specialists`. The content from `echelon.run.md` goes into the appropriately-named files regardless of the section numbering in `echelon.run.md`. The ordering discrepancy is fixed in Task 7 when `spec_file` references are added to `definition.yaml`.

- [ ] **Step 1: Create `workflow/phases/phase3-specialists.md`**

Header:
```markdown
# Phase: phase3-specialists
# Source: echelon.run.md §7 — Specialist Summoning
# Agent: conditional_parallel (GUARDIAN mandatory; INVESTIGATOR, ORACLE, BENCHMARK, ADVOCATE, MAVERICK conditional)
# Read by: COMMANDER before dispatching specialists
```

Copy content from `## 7. Specialist Summoning` through (not including) `## 8. HOW Phase`.

- [ ] **Step 2: Create `workflow/phases/phase3-how.md`**

Header:
```markdown
# Phase: phase3-how
# Source: echelon.run.md §8 — HOW Phase (Architecture)
# Agent: ARCHITECT
# Read by: COMMANDER before dispatching ARCHITECT
```

Copy content from `## 8. HOW Phase (Architecture)` through (not including) `## 9. TEST ARCHITECT Phase`.

- [ ] **Step 3: Create `workflow/phases/phase3-sentinel.md`**

Header:
```markdown
# Phase: phase3-sentinel
# Source: echelon.run.md §9 — TEST ARCHITECT Phase
# Agent: SENTINEL
# Read by: COMMANDER before dispatching SENTINEL
```

Copy content from `## 9. TEST ARCHITECT Phase (Mandatory)` through (not including) `## 10. PLAN Phase`.

- [ ] **Step 4: Create `workflow/phases/phase3-plan.md`**

Header:
```markdown
# Phase: phase3-plan
# Source: echelon.run.md §10 — PLAN Phase (Task Breakdown)
# Agent: ORCHESTRATOR
# Read by: COMMANDER before dispatching ORCHESTRATOR
```

Copy content from `## 10. PLAN Phase (Task Breakdown)` through (not including) `## 11. CONSENSUS Phase`.

- [ ] **Step 5: Create `workflow/phases/phase3-consensus.md`**

Header:
```markdown
# Phase: phase3-consensus
# Source: echelon.run.md §11 — CONSENSUS Phase (Parallel Validation)
# Agent: parallel — SAGE (WHY3), GATEKEEPER (ASSESS2), ORCHESTRATOR (PLAN2)
# Read by: COMMANDER before dispatching consensus agents
```

Copy content from `## 11. CONSENSUS Phase (Parallel Validation)` through (not including) `## 12. FINALIZE Phase`.

- [ ] **Step 6: Verify**

```bash
grep "GUARDIAN" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase3-specialists.md | head -1
grep "ARCHITECT" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase3-how.md | head -1
grep "SENTINEL" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase3-sentinel.md | head -1
grep "ORCHESTRATOR" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase3-plan.md | head -1
grep "WHY3" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase3-consensus.md | head -1
```

Expected: each grep returns a match.

- [ ] **Step 7: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/phase3-specialists.md workflow/phases/phase3-how.md \
        workflow/phases/phase3-sentinel.md workflow/phases/phase3-plan.md \
        workflow/phases/phase3-consensus.md
git commit -m "refactor: extract phase3 files to workflow/phases/"
```

---

## Task 6: Extract `phase4-document.md`

**Files:**
- Create: `workflow/phases/phase4-document.md`

- [ ] **Step 1: Create `workflow/phases/phase4-document.md`**

Header:
```markdown
# Phase: phase4-document
# Source: echelon.run.md §12 — FINALIZE Phase
# Agent: COMMANDER internal (sequential: REALIST, MIRROR, ADAPTIVE, AUDITOR, SCOREKEEPER)
# Read by: COMMANDER before executing finalization sequence
```

Copy content from `## 12. FINALIZE Phase` through (not including) `## 13. Scorekeeper Protocol`.

This section contains subsections 12.1 through 12.11 — all of them, including the SCOREKEEPER dispatch (12.7), artifact manifest (12.6), final state update (12.8), final summary banner (12.8), archive/cleanup (12.9), branch return (12.10), and branch stacking note (12.11).

- [ ] **Step 2: Verify**

```bash
grep "12\." /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase4-document.md | head -5
```

Expected: subsection numbers 12.1–12.11 visible.

```bash
grep "SQUAD COMPLETE\|ECHELON RUN COMPLETE" /Users/michalbachorik/work/evolution/echelon/workflow/phases/phase4-document.md
```

Expected: the completion banner template is present.

- [ ] **Step 3: Verify all 18 phase files exist**

```bash
ls /Users/michalbachorik/work/evolution/echelon/workflow/phases/ | wc -l
```

Expected: `18`

```bash
ls /Users/michalbachorik/work/evolution/echelon/workflow/phases/
```

Expected output:
```
init.md
phase1-constitution.md
phase1-discover.md
phase1-modeler.md
phase1-synthesizer.md
phase1-tracker.md
phase1-what.md
phase1-why1.md
phase1-why2.md
phase2-decide.md
phase2-strategic-overview.md
phase2-tracker-alignment.md
phase3-consensus.md
phase3-how.md
phase3-plan.md
phase3-sentinel.md
phase3-specialists.md
phase4-document.md
```

- [ ] **Step 4: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/phase4-document.md
git commit -m "refactor: extract phase4-document to workflow/phases/ — all 18 phase files complete"
```

---

## Task 7: Add `spec_file:` to `workflow/definition.yaml`

Add a `spec_file:` field to every non-terminal phase node. Terminal nodes (`done`, `escalate`) and `checkpoint-assess`/`checkpoint-plan` (human_gate type) get no `spec_file` — they have no agent dispatch and no execution detail file.

**Files:**
- Modify: `workflow/definition.yaml`

- [ ] **Step 1: Add `spec_file:` to each phase node**

For each phase node listed below, insert `spec_file: workflow/phases/{filename}` immediately after the `label:` field. The ordering in `definition.yaml` is authoritative — do not change phase node order.

| Phase `id` | `spec_file` value |
|---|---|
| `init` | `workflow/phases/init.md` |
| `phase1-discover` | `workflow/phases/phase1-discover.md` |
| `phase1-synthesizer` | `workflow/phases/phase1-synthesizer.md` |
| `phase1-modeler` | `workflow/phases/phase1-modeler.md` |
| `phase1-tracker` | `workflow/phases/phase1-tracker.md` |
| `phase1-why1` | `workflow/phases/phase1-why1.md` |
| `phase1-constitution` | `workflow/phases/phase1-constitution.md` |
| `phase1-what` | `workflow/phases/phase1-what.md` |
| `phase1-why2` | `workflow/phases/phase1-why2.md` |
| `checkpoint-assess` | *(skip — human_gate, no dispatch)* |
| `phase2-decide` | `workflow/phases/phase2-decide.md` |
| `phase2-strategic-overview` | `workflow/phases/phase2-strategic-overview.md` |
| `phase2-tracker-alignment` | `workflow/phases/phase2-tracker-alignment.md` |
| `phase3-how` | `workflow/phases/phase3-how.md` |
| `phase3-specialists` | `workflow/phases/phase3-specialists.md` |
| `phase3-sentinel` | `workflow/phases/phase3-sentinel.md` |
| `phase3-plan` | `workflow/phases/phase3-plan.md` |
| `phase3-consensus` | `workflow/phases/phase3-consensus.md` |
| `checkpoint-plan` | *(skip — human_gate, no dispatch)* |
| `phase4-document` | `workflow/phases/phase4-document.md` |
| `done` | *(skip — terminal)* |
| `escalate` | *(skip — terminal)* |

Example of the edit for `phase1-discover`:

```yaml
  - id: phase1-discover
    label: "Discovery (SCOUT)"
    spec_file: workflow/phases/phase1-discover.md   # ← add this line
    type: agent
    agent: SCOUT
```

Also remove the note block at lines ~470–473 of `definition.yaml` (the comment about the HOW/Specialists ordering discrepancy) — it is now resolved: `definition.yaml` ordering is canonical, and phase files follow it.

- [ ] **Step 2: Verify `spec_file` count**

```bash
grep -c "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml
```

Expected: `20` (one per non-terminal, non-checkpoint phase node as listed above).

- [ ] **Step 3: Verify all referenced files exist**

```bash
grep "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml \
  | awk '{print $2}' \
  | while read f; do
      [ -f "/Users/michalbachorik/work/evolution/echelon/$f" ] \
        && echo "OK: $f" \
        || echo "MISSING: $f"
    done
```

Expected: all lines print `OK:`.

- [ ] **Step 4: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/definition.yaml
git commit -m "refactor: add spec_file references to definition.yaml phase nodes; resolve HOW/Specialists ordering"
```

---

## Task 8: Absorb cross-cutting sections into `commander.md`

`echelon.run.md` sections 13–21 are behavioral framework content. They move to `commander.md` with deduplication where content already exists.

**Files:**
- Modify: `extension/agents/control/commander.md`

- [ ] **Step 1: Handle section 13 — Scorekeeper Protocol**

`echelon.run.md` section `## 13. Scorekeeper Protocol` has two parts: "After Every Agent Dispatch" scoring rules and "During FINALIZE — Full Scorecard" dispatch. `commander.md` already has a "Per-Agent Internalization Data Handoff" section that handles the FINALIZE dispatch partially.

Action: append the full section 13 content to `commander.md` under the heading `## Scorekeeper Protocol`. If any paragraph is already present verbatim in `commander.md`, keep one copy and discard the duplicate.

- [ ] **Step 2: Handle section 14 — State Tracking Protocol**

`echelon.run.md` section `## 14. State Tracking Protocol` describes per-phase `state.json` updates and issue tracking. `commander.md` has a `## State Management` section that covers the fields but not the per-transition update procedure.

Action: append the full section 14 content to `commander.md` under `## State Tracking Protocol`. Merge the `issues_log` JSON block with the existing `## State Management` field list — keep one copy.

- [ ] **Step 3: Handle section 14 (second) — Convergence Rules**

`echelon.run.md` has a second `## 14. Convergence Rules` section (Rules 1–6). `commander.md` has a `## Convergence Rules` section that covers thresholds by reference but not the six named rules.

Action: append Rules 1–6 to `commander.md`'s existing `## Convergence Rules` section.

- [ ] **Step 4: Handle section 15 — Error Handling**

`echelon.run.md` section `## 15. Error Handling` has the External Tool Failures table and Subagent Failures and Degraded Mode Artifacts sections. These are not currently in `commander.md`.

Action: append the full section 15 content to `commander.md` under `## Error Handling`.

- [ ] **Step 5: Handle section 16 — Human Escalation Protocol**

`echelon.run.md` section `## 16. Human Escalation Protocol` has the five-step escalation procedure (produce escalation-request.md, write to file, update state, print terminal banner, STOP). `commander.md` has `## Human Escalation vs Autonomous Resolution` which covers the decision framework but not the procedure.

Action: append the five-step escalation procedure to `commander.md` under a new heading `## Human Escalation Procedure` (distinct from the existing decision-framework section).

- [ ] **Step 6: Handle section 17 — Evidence Hierarchy**

`echelon.run.md` section `## 17. Evidence Hierarchy (Conflict Resolution)` is a pure reference: "See `agents/control/commander.md`". No content to move — delete this section entirely when slimming `echelon.run.md` in Task 9.

No change to `commander.md` needed.

- [ ] **Step 7: Handle section 18 — Token Budget Management**

`echelon.run.md` section `## 18. Token Budget Management` adds phase-specific skip rules (which phases can be deferred when budget runs low). `commander.md` has `## Token Budget Management` covering the allocation tiers and cap.

Action: append the "Budget Enforcement (phase-specific skip rules)" subsection to `commander.md`'s existing `## Token Budget Management` section.

- [ ] **Step 8: Handle section 19 — Re-Run Behavior**

`echelon.run.md` section `## 19. Re-Run Behavior` (5 bullet points about INIT detecting prior artifacts, EVOLVE diffing, INNOVATE on stagnation, etc.) is not in `commander.md`.

Action: append the full section to `commander.md` under `## Re-Run Behavior`.

- [ ] **Step 9: Handle section 20 — Quick Reference: Phase Transitions**

`echelon.run.md` section `## 20. Quick Reference: Phase Transitions` is the ordered phase list. This is fully superseded by `workflow/definition.yaml` (which is now the authoritative source with `spec_file` links).

Action: do not copy to `commander.md`. Delete when slimming `echelon.run.md` in Task 9.

- [ ] **Step 10: Handle section 21 — Checklist**

`echelon.run.md` section `## 21. Checklist (MANAGER Self-Verification)` is not in `commander.md`.

Action: append the full checklist to `commander.md` under `## Run Completion Checklist`.

- [ ] **Step 11: Update the State Machine Contract paragraph in `commander.md`**

Find the existing paragraph in `commander.md`'s `## State Machine Contract` section that reads:

> The operational state machine — phases, transitions, dispatch sequences — is defined by the command that invoked COMMANDER. Follow the invoking command's state machine exactly.

Replace it with:

> The operational state machine — phases, transitions, routing conditions — is defined in `workflow/definition.yaml`. Read it at init and before every routing decision. Before each phase dispatch, read `phases[current].spec_file` for context pack assembly, dispatch prompt, and expected outputs.

- [ ] **Step 12: Verify key sections are present in `commander.md`**

```bash
grep -l "Re-Run Behavior\|Error Handling\|Human Escalation Procedure\|Run Completion Checklist\|Scorekeeper Protocol\|phase-specific skip rules" \
  /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md
```

Expected: the file path is printed (all terms found in one file).

```bash
grep "spec_file" /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md
```

Expected: the updated State Machine Contract line is present.

- [ ] **Step 13: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add extension/agents/control/commander.md
git commit -m "refactor: absorb echelon.run.md sections 13-21 into commander.md; update State Machine Contract"
```

---

## Task 9: Slim `echelon.run.md` to thin wrapper

**Files:**
- Modify: `extension/commands/echelon.run.md`

- [ ] **Step 1: Replace the entire body of `echelon.run.md`**

Keep the existing YAML frontmatter block (lines 1–8) unchanged. Replace everything after the closing `---` of the frontmatter with exactly the following:

```markdown
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
```

- [ ] **Step 2: Verify line count**

```bash
wc -l /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.run.md
```

Expected: ≤ 35 lines (frontmatter 8 lines + body ~25 lines).

- [ ] **Step 3: Verify frontmatter is intact**

```bash
head -8 /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.run.md
```

Expected: the YAML frontmatter block with `name`, `description`, `disable-model-invocation`, `argument-hint`, `scripts` fields — unchanged from original.

- [ ] **Step 4: Verify no section headings from the original remain**

```bash
grep "^## [0-9]\|^## 1\.\|Initialization\|DISCOVER Phase\|WHY1\|WHY2\|ASSESS Phase\|Specialist Summoning\|HOW Phase\|CONSENSUS\|FINALIZE\|Scorekeeper Protocol\|Convergence Rules\|Error Handling\|Token Budget\|Re-Run Behavior" \
  /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.run.md
```

Expected: no output (no original section headings remain).

- [ ] **Step 5: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add extension/commands/echelon.run.md
git commit -m "refactor: slim echelon.run.md to thin orchestrator wrapper (~30 lines)"
```

---

## Task 10: Final verification — nothing orphaned

- [ ] **Step 1: Confirm all 18 phase files are present and non-empty**

```bash
for f in /Users/michalbachorik/work/evolution/echelon/workflow/phases/*.md; do
  lines=$(wc -l < "$f")
  echo "$lines $f"
done
```

Expected: 18 files, each with > 10 lines. Flag any file with ≤ 10 lines as potentially empty/incomplete.

- [ ] **Step 2: Confirm no phase file exceeds 250 lines**

```bash
for f in /Users/michalbachorik/work/evolution/echelon/workflow/phases/*.md; do
  lines=$(wc -l < "$f")
  [ "$lines" -gt 250 ] && echo "OVER LIMIT ($lines): $f"
done
```

Expected: no output. If a file exceeds 250 lines, split it (open a new task to investigate — out of scope here).

- [ ] **Step 3: Confirm `echelon.run.md` is ≤ 35 lines**

```bash
wc -l /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.run.md
```

Expected: ≤ 35.

- [ ] **Step 4: Confirm `definition.yaml` has 20 `spec_file:` entries and all target files exist**

```bash
grep "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml | wc -l
```

Expected: `20`.

```bash
grep "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml \
  | awk '{print $2}' \
  | while read f; do
      [ -f "/Users/michalbachorik/work/evolution/echelon/$f" ] \
        && echo "OK: $f" \
        || echo "MISSING: $f"
    done
```

Expected: 20 lines, all `OK:`.

- [ ] **Step 5: Confirm ordering discrepancy note is gone from `definition.yaml`**

```bash
grep -n "ordering discrepancy\|NOTE: echelon.run.md" \
  /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml
```

Expected: no output.

- [ ] **Step 6: Confirm cross-cutting sections are in `commander.md`**

```bash
for term in "Re-Run Behavior" "Error Handling" "Human Escalation Procedure" \
            "Run Completion Checklist" "Scorekeeper Protocol" \
            "phase-specific skip rules" "spec_file"; do
  grep -q "$term" /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    && echo "OK: $term" \
    || echo "MISSING: $term"
done
```

Expected: all 7 lines print `OK:`.

- [ ] **Step 7: Spot-check that COMMANDER behavioral framework is intact**

```bash
for term in "Post-Dispatch Protocol" "Pre-Dispatch Enforcement" "NEVER Rules" \
            "Convergence Rules" "Conflict Resolution Protocol" \
            "Token Budget Management" "Endocrine System"; do
  grep -q "$term" /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    && echo "OK: $term" \
    || echo "MISSING: $term"
done
```

Expected: all 7 lines print `OK:`.

- [ ] **Step 8: Final commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add -A
git status
```

Review `git status` — expected: clean (all changes already committed in prior tasks). If any files remain modified, stage and commit them now with message `refactor: final cleanup for echelon.run lightweight refactor`.
