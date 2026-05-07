# Agent Identity Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove `agents.yaml`, fix `commander.md` to use spec-kit-injected names in all dispatch/routing contexts and codenames everywhere else, eliminating all functional-name agent references.

**Architecture:** Three-file model after consolidation — `extension.yml` (deployment), `workflow/definition.yaml` (phase graph + routing), individual agent `.md` files (prompts). The canonical agent identifier is the spec-kit-injected name `speckit-echelon-{filename}` derived by spec-kit from the `extension.yml` name entry.

**Tech Stack:** YAML, Markdown. No code changes — all edits are to prompt and configuration files in `/Users/michalbachorik/work/evolution/echelon/`.

---

## File Map

| File | Change |
|------|--------|
| `extension/agents.yaml` | **DELETE** |
| `extension/agents/control/commander.md` | Rewrite Role Separation table; replace all functional-name agent references in routing, constitution, convergence, reflection, budget, error handling, and scorekeeper sections |
| `workflow/definition.yaml` | Read-only verification — confirm `agent:` fields already use codenames |
| `extension/extension.yml` | No changes required |

---

## Task 1: Delete `agents.yaml`

**Files:**
- Delete: `extension/agents.yaml`

- [ ] **Step 1: Verify the file exists and note what uses it**

  Run: `ls -la /Users/michalbachorik/work/evolution/echelon/extension/agents.yaml`

  Then check for any references to it outside commander.md:
  ```bash
  grep -r "agents\.yaml" /Users/michalbachorik/work/evolution/echelon/ \
    --include="*.md" --include="*.yaml" --include="*.yml" --include="*.py" \
    -l
  ```

  Expected: `extension/agents.yaml` itself and `extension/agents/control/commander.md`. Any other file referencing it needs to be noted before deletion.

- [ ] **Step 2: Delete the file**

  ```bash
  rm /Users/michalbachorik/work/evolution/echelon/extension/agents.yaml
  ```

- [ ] **Step 3: Verify deletion**

  ```bash
  ls /Users/michalbachorik/work/evolution/echelon/extension/agents.yaml 2>&1
  ```

  Expected: `ls: cannot access '...agents.yaml': No such file or directory`

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add -u extension/agents.yaml
  git commit -m "refactor: delete agents.yaml — content fully covered by definition.yaml and agent .md files"
  ```

---

## Task 2: Rewrite the Role Separation Table in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (lines 39–63)

The current section is:

```markdown
## Role Separation — ABSOLUTE RULES

Every agent has ONE job. No agent may do another agent's job. This is non-negotiable.

| Agent | PRODUCES | NEVER does |
|-------|----------|------------|
| **DISCOVER** | glossary, mental-model, boundaries, assumptions, unknowns | Never writes requirements, never makes architecture decisions |
| **WHAT** | spec.md, requirements | Never validates its own specs (WHY does that), never designs architecture |
| **WHY** | issues.md, quality-gates.md | **NEVER rewrites specs/plans/tasks.** WHY ONLY finds problems. Responsible agent fixes. |
| **ASSESS** | feasibility, estimates, prioritization | Never writes requirements, never designs architecture, never overrides user intent |
| **HOW** | plan.md, research.md, ADRs, data-model, contracts | Never writes requirements, never estimates effort |
| **PLAN** | tasks.md, critical-path, risk-matrix | Never designs architecture, never writes requirements |
| **SCIENTIST** | investigation reports, experiment results | Never makes architecture decisions based on findings (HOW does that) |

> **Naming convention:** The table above uses **functional names** (DISCOVER, WHAT, WHY, etc.). Each maps to a **codename** used in dispatch: SCOUT=DISCOVER, SAGE=WHY, CARTOGRAPHER=WHAT, GATEKEEPER=ASSESS, ARCHITECT=HOW, ORCHESTRATOR=PLAN, **INVESTIGATOR=SCIENTIST**. Dispatch instructions always use codenames.
```

- [ ] **Step 1: Replace the Role Separation table block**

  In `extension/agents/control/commander.md`, replace the block starting at `| Agent | PRODUCES |` through the end of the `> **Naming convention:**` blockquote with:

  ```markdown
  | Spec-kit name | Codename | PRODUCES | NEVER does |
  |---------------|----------|----------|------------|
  | **speckit-echelon-scout** | SCOUT | glossary, mental-model, boundaries, assumptions, unknowns | Never writes requirements, never makes architecture decisions |
  | **speckit-echelon-cartographer** | CARTOGRAPHER | spec.md, requirements | Never validates own specs (speckit-echelon-sage does that), never designs architecture |
  | **speckit-echelon-sage** | SAGE | issues.md, quality-gates.md | **NEVER rewrites specs/plans/tasks.** SAGE ONLY finds problems. Responsible agent fixes. |
  | **speckit-echelon-gatekeeper** | GATEKEEPER | feasibility, estimates, prioritization | Never writes requirements, never designs architecture, never overrides user intent |
  | **speckit-echelon-architect** | ARCHITECT | plan.md, research.md, ADRs, data-model, contracts | Never writes requirements, never estimates effort |
  | **speckit-echelon-orchestrator** | ORCHESTRATOR | tasks.md, critical-path, risk-matrix | Never designs architecture, never writes requirements |
  | **speckit-echelon-investigator** | INVESTIGATOR | investigation reports, experiment results | Never makes architecture decisions (speckit-echelon-architect does that) |

  > **Dispatch name rule:** Routing instructions and Agent tool calls always use the spec-kit-injected name (`speckit-echelon-{filename}`). Codenames (SCOUT, SAGE, etc.) are human-readable labels for prose only. The deployed name equals `speckit-echelon-{agent-md-filename-without-extension}` — e.g., `commander.md` → `speckit-echelon-commander`.
  ```

- [ ] **Step 2: Replace the routing rule paragraph** (immediately after the table)

  Current text:
  ```
  **The routing rule:** When WHY finds issues, MANAGER reads each issue and routes it to the agent that OWNS the artifact:

  - Spec issues → dispatch **WHAT** (CARTOGRAPHER) to fix → then **WHY** re-validates
  - Architecture issues → dispatch **HOW** (ARCHITECT) to fix → then **WHY** re-validates
  - Task issues → dispatch **PLAN** (ORCHESTRATOR) to fix → then **WHY** re-validates
  - Unknown questions → dispatch **SCIENTIST** (INVESTIGATOR) to investigate → feed results to the relevant agent

  **NEVER dispatch WHY with a prompt that says "fix" or "rewrite."** WHY is read-only on all artifacts except issues.md and quality-gates.md.
  ```

  Replace with:
  ```
  **The routing rule:** When SAGE (speckit-echelon-sage) finds issues, COMMANDER reads each issue and routes it to the agent that OWNS the artifact:

  - Spec issues → dispatch **speckit-echelon-cartographer** → then **speckit-echelon-sage** re-validates
  - Architecture issues → dispatch **speckit-echelon-architect** → then **speckit-echelon-sage** re-validates
  - Task issues → dispatch **speckit-echelon-orchestrator** → then **speckit-echelon-sage** re-validates
  - Unknown questions → dispatch **speckit-echelon-investigator** → feed results to the relevant agent

  **NEVER dispatch speckit-echelon-sage with a prompt that says "fix" or "rewrite."** SAGE is read-only on all artifacts except issues.md and quality-gates.md.
  ```

- [ ] **Step 3: Verify no functional names remain in this section**

  ```bash
  grep -n "DISCOVER\|WHAT\|WHY\|ASSESS\|HOW\|PLAN\|SCIENTIST\|Naming convention" \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | head -20
  ```

  Expected: lines from later sections only (convergence rules, budget, etc.) — NOT from the Role Separation section (lines 39–65). Lines from later sections will be fixed in subsequent tasks.

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional-name Role Separation table with spec-kit names + codenames"
  ```

---

## Task 3: Fix Constitution Section in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (Constitution Authority section, lines 66–95)

- [ ] **Step 1: Replace rule 1 agent list**

  Current:
  ```
  1. **NO agent may overwrite, weaken, remove, or contradict any constitution principle.** This includes HOW, ASSESS, PLAN, INNOVATE — every agent without exception.
  ```

  Replace with:
  ```
  1. **NO agent may overwrite, weaken, remove, or contradict any constitution principle.** This includes ARCHITECT, GATEKEEPER, ORCHESTRATOR, MAVERICK — every agent without exception.
  ```

- [ ] **Step 2: Replace rule 2 agent references**

  Current:
  ```
  2. **HOW may APPEND technical principles** (e.g., ADR-level decisions like "use TypeScript strict mode") but these additions:
     - MUST NOT contradict any existing human-defined principle
     - MUST be validated by WHY before taking effect
     - MUST be clearly labeled as "squad-generated" vs "human-defined"
  ```

  Replace with:
  ```
  2. **speckit-echelon-architect (ARCHITECT) may APPEND technical principles** (e.g., ADR-level decisions like "use TypeScript strict mode") but these additions:
     - MUST NOT contradict any existing human-defined principle
     - MUST be validated by speckit-echelon-sage (SAGE) before taking effect
     - MUST be clearly labeled as "squad-generated" vs "human-defined"
  ```

- [ ] **Step 3: Verify constitution section is clean**

  ```bash
  awk '/^## Constitution Authority/,/^---/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "HOW\|WHY\|ASSESS\|PLAN\|DISCOVER\|SCIENTIST\|INNOVATE"
  ```

  Expected: no output.

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional names in constitution authority section with codenames/spec-kit names"
  ```

---

## Task 4: Fix Manager Reflection Section in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (Manager Reflection Protocol section, ~lines 285–295)

- [ ] **Step 1: Replace agent references in the reflection trigger list**

  Current:
  ```
  **When to reflect:**

  - Before dispatching DISCOVER (initial strategy)
  - Before dispatching HOW (after ASSESS — is the approach right?)
  - Before CONSENSUS (are we ready or should we iterate more?)
  - Before FINALIZE (is everything complete or are there gaps?)
  - Before any human escalation (frame the question well)
  ```

  Replace with:
  ```
  **When to reflect:**

  - Before dispatching speckit-echelon-scout (SCOUT) (initial strategy)
  - Before dispatching speckit-echelon-architect (ARCHITECT) (after speckit-echelon-gatekeeper (GATEKEEPER) passes — is the approach right?)
  - Before CONSENSUS (are we ready or should we iterate more?)
  - Before FINALIZE (is everything complete or are there gaps?)
  - Before any human escalation (frame the question well)
  ```

- [ ] **Step 2: Verify reflection section is clean**

  ```bash
  awk '/^## Manager Reflection/,/^---/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "DISCOVER\b\|HOW\b\|ASSESS\b"
  ```

  Expected: no output.

- [ ] **Step 3: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional names in manager reflection triggers"
  ```

---

## Task 5: Fix Convergence Rules Section in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (Convergence Rules section, ~lines 373–406)

There are six functional-name references to fix in this section.

- [ ] **Step 1: Fix Rule 1 — WHY pass reference**

  Current:
  ```
  - After each WHY pass (WHY2, WHY3), record quality scores in `state.json.quality_scores[]`
  - If the delta between the last two passes is < `convergence_delta` (per `echelon-config.yml convergence:`) for 2 consecutive passes → **stop WHY iterations**
  ```

  Replace with:
  ```
  - After each SAGE pass (WHY2, WHY3), record quality scores in `state.json.quality_scores[]`
  - If the delta between the last two passes is < `convergence_delta` (per `echelon-config.yml convergence:`) for 2 consecutive passes → **stop SAGE iterations**
  ```

- [ ] **Step 2: Fix Rule 2 — INNOVATE reference**

  Current:
  ```
  - First: attempt INNOVATE (propose alternative approach that avoids the issue)
  - If INNOVATE already tried: escalate to human (see Human Escalation Procedure)
  ```

  Replace with:
  ```
  - First: dispatch speckit-echelon-maverick (MAVERICK) to propose an alternative approach that avoids the issue
  - If speckit-echelon-maverick already ran for this issue: escalate to human (see Human Escalation Procedure)
  ```

- [ ] **Step 3: Fix Rule 4 — GROUND + CALIBRATE references**

  Current:
  ```
  - Always run GROUND + CALIBRATE (minimum finalize)
  ```

  Replace with:
  ```
  - Always run speckit-echelon-realist (REALIST) + speckit-echelon-auditor (AUDITOR) at minimum (minimum finalize)
  ```

- [ ] **Step 4: Fix Rule 5 — CALIBRATE and INVESTIGATOR references**

  Current:
  ```
  ### Rule 5: CALIBRATE Confidence Gate

  - If CALIBRATE reports confidence < 0.5 for a critical domain → **summon INVESTIGATOR**
  - If INVESTIGATOR already ran for that domain and confidence is still < 0.5 → flag for human, do not block
  ```

  Replace with:
  ```
  ### Rule 5: AUDITOR Confidence Gate

  - If speckit-echelon-auditor (AUDITOR) reports confidence < 0.5 for a critical domain → **dispatch speckit-echelon-investigator (INVESTIGATOR)**
  - If speckit-echelon-investigator already ran for that domain and confidence is still < 0.5 → flag for human, do not block
  ```

- [ ] **Step 5: Fix Rule 6 — ASSESS reference**

  Current:
  ```
  ### Rule 6: ASSESS DEFER Loop

  - If ASSESS returns DEFER >= 2 times with no scope stabilization → **kill or escalate**
  ```

  Replace with:
  ```
  ### Rule 6: GATEKEEPER DEFER Loop

  - If speckit-echelon-gatekeeper (GATEKEEPER) returns DEFER >= 2 times with no scope stabilization → **kill or escalate**
  ```

  Also fix the Human Escalation section that references this rule (~line 465):

  Current:
  ```
  - ASSESS produces DEFER `assess.defer_loop_limit` times (default: 2, read via `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh assess.defer_max_iterations`) with no scope stabilization
  ```

  Replace with:
  ```
  - speckit-echelon-gatekeeper (GATEKEEPER) produces DEFER `assess.defer_loop_limit` times (default: 2, read via `bash .specify/extensions/echelon/scripts/bash/echelon-config-get.sh assess.defer_max_iterations`) with no scope stabilization
  ```

- [ ] **Step 6: Fix Human Escalation section — CALIBRATE reference (~line 462)**

  Current:
  ```
  - CALIBRATE confidence below `convergence.calibrate_confidence_floor` after INVESTIGATOR investigation (see `workflow/definition.yaml`)
  ```

  Replace with:
  ```
  - speckit-echelon-auditor (AUDITOR) confidence below `convergence.calibrate_confidence_floor` after INVESTIGATOR investigation (see `workflow/definition.yaml`)
  ```

- [ ] **Step 7: Verify convergence and human escalation sections are clean**

  ```bash
  awk '/^## Convergence Rules/,/^## Conflict Resolution/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "INNOVATE\b\|CALIBRATE\b\|ASSESS\b\|\bWHY\b\|GROUND\b\|SCIENTIST\b"
  ```

  ```bash
  awk '/^## Human Escalation vs/,/^## Diagnostic Pipeline/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "ASSESS\b\|CALIBRATE\b\|INNOVATE\b"
  ```

  Expected: no output from either command.

- [ ] **Step 8: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional names in convergence rules and human escalation sections"
  ```

---

## Task 6: Fix Budget and Error Handling Sections in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (Budget Enforcement and Error Handling sections)

- [ ] **Step 1: Fix budget skip rules (~line 823)**

  Current:
  ```
  - DISCOVER, WHAT, WHY, ASSESS, HOW, PLAN: **cannot be skipped** — force finalize instead
  ```

  Replace with:
  ```
  - speckit-echelon-scout (SCOUT), speckit-echelon-cartographer (CARTOGRAPHER), speckit-echelon-sage (SAGE), speckit-echelon-gatekeeper (GATEKEEPER), speckit-echelon-architect (ARCHITECT), speckit-echelon-orchestrator (ORCHESTRATOR): **cannot be skipped** — force finalize instead
  ```

  Also fix the CONSENSUS reduction line below it (~line 825):

  Current:
  ```
  - CONSENSUS: can be reduced (run WHY3 only, skip ASSESS2 + PLAN2)
  ```

  Replace with:
  ```
  - CONSENSUS: can be reduced (run SAGE WHY3 only, skip GATEKEEPER2 + ORCHESTRATOR2)
  ```

- [ ] **Step 2: Fix error handling table (~line 1074)**

  Current:
  ```
  | spec-kit skills | Skill invocation fails at runtime | HOW and PLAN produce artifacts manually as markdown. No spec-kit validation. Flag as UNVALIDATED. spec-kit skills (e.g. `speckit.specify`, `speckit.constitution`) are AI coding assistant skills, not CLI tools — validated at install time via `specify extension add echelon`. |
  ```

  Replace with:
  ```
  | spec-kit skills | Skill invocation fails at runtime | speckit-echelon-architect (ARCHITECT) and speckit-echelon-orchestrator (ORCHESTRATOR) produce artifacts manually as markdown. No spec-kit validation. Flag as UNVALIDATED. spec-kit skills (e.g. `speckit.specify`, `speckit.constitution`) are AI coding assistant skills, not CLI tools — validated at install time via `specify extension add echelon`. |
  ```

- [ ] **Step 3: Verify budget and error handling sections**

  ```bash
  awk '/^### Budget Enforcement/,/^---/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "\bDISCOVER\b\|\bWHAT\b\|\bWHY\b\|\bASSESS\b\|\bHOW\b\|\bPLAN\b"
  ```

  ```bash
  awk '/^### Subagent Failures/,/^---/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "\bHOW\b\|\bPLAN\b\|\bASSESS\b"
  ```

  Expected: no output.

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional names in budget enforcement and error handling sections"
  ```

---

## Task 7: Fix Scorekeeper Protocol Section in `commander.md`

**Files:**
- Modify: `extension/agents/control/commander.md` (Scorekeeper Protocol section, ~lines 980–1030)

- [ ] **Step 1: Fix agent references in scoring examples**

  Current scoring block:
  ```
  1. Read the agent's output quality:
     - Did WHY pass or fail? → +5 for CRITICAL catch, -1 for false positive
     - Did WHAT need rework? → -1 per WHY rejection
     - Did IMPLEMENTER pass first review? → +3 first-pass, -1 rework
     - Did INVESTIGATOR validate an assumption? → +2 validated, +4 invalidated (more valuable)
  ```

  Replace with:
  ```
  1. Read the agent's output quality:
     - Did SAGE pass or fail? → +5 for CRITICAL catch, -1 for false positive
     - Did CARTOGRAPHER need rework? → -1 per SAGE rejection
     - Did IMPLEMENTER pass first review? → +3 first-pass, -1 rework
     - Did INVESTIGATOR validate an assumption? → +2 validated, +4 invalidated (more valuable)
  ```

- [ ] **Step 2: Fix peer appreciation examples**

  Current:
  ```
  IF WHAT produces spec.md AND WHY2 passes on first attempt:
    → Peer appreciation: WHY awards WHAT +2 "clear_and_actionable"

  IF INVESTIGATOR produces investigation/ AND HOW makes a decision based on it:
    → Peer appreciation: HOW awards INVESTIGATOR +3 "unblocked_my_work"

  IF WHY catches an issue that SPEC GUARD would have missed:
    → Peer appreciation: SPEC GUARD awards WHY +2 "caught_my_mistake"
  ```

  Replace with:
  ```
  IF CARTOGRAPHER produces spec.md AND SAGE WHY2 passes on first attempt:
    → Peer appreciation: SAGE awards CARTOGRAPHER +2 "clear_and_actionable"

  IF INVESTIGATOR produces investigation/ AND ARCHITECT makes a decision based on it:
    → Peer appreciation: ARCHITECT awards INVESTIGATOR +3 "unblocked_my_work"

  IF SAGE catches an issue that SPEC GUARD would have missed:
    → Peer appreciation: SPEC GUARD awards SAGE +2 "caught_my_mistake"
  ```

- [ ] **Step 3: Verify scorekeeper section is clean**

  ```bash
  awk '/^## Scorekeeper Protocol/,/^---/' \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md \
    | grep -n "\bWHY\b\|\bWHAT\b\|\bHOW\b\|\bSCIENTIST\b"
  ```

  Expected: no output.

- [ ] **Step 4: Commit**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add extension/agents/control/commander.md
  git commit -m "refactor: replace functional names in scorekeeper protocol section"
  ```

---

## Task 8: Full Verification Pass

- [ ] **Step 1: Scan for remaining functional-name agent references**

  Run a comprehensive scan for functional names that should have been replaced. We exclude legitimate phase-label uses (journal phase fields, per_phase JSON keys, WHY2/WHY3 as SAGE mode labels, and the word "HOW" appearing as an English word in non-agent contexts).

  ```bash
  grep -n "\bDISCOVER\b\|\bWHAT\b\|\bASSESS\b\|\bSCIENTIST\b\|\bINNOVATE\b\|\bCALIBRATE\b\|\bGROUND\b" \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md
  ```

  Expected: zero matches.

  ```bash
  grep -n "\bHOW\b\|\bPLAN\b" \
    /Users/michalbachorik/work/evolution/echelon/extension/agents/control/commander.md
  ```

  Expected: PLAN may appear in "PLAN: cannot be skipped" (already fixed) and in English prose ("plan.md", "planning", "plan of action") — check that remaining occurrences are English words or file names, not agent references. HOW should appear only in English-word contexts ("how to", "here's how") not as agent references.

- [ ] **Step 2: Verify definition.yaml agent references use codenames**

  ```bash
  grep -n "^    agent:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml | head -30
  ```

  Expected: all values should be codenames (SCOUT, SYNTHESIZER, SAGE, CARTOGRAPHER, GATEKEEPER, ARCHITECT, ORCHESTRATOR, SENTINEL, etc.) — not functional names or spec-kit names. definition.yaml uses codenames in `agent:` fields, which is correct and consistent. No changes needed.

- [ ] **Step 3: Verify deployed agent names in test project match the pattern**

  ```bash
  ls /Users/michalbachorik/work/test-echelon-refactor/.claude/agents/ | sort
  ```

  Expected: all files follow `speckit-echelon-{codename-lowercase}.md` pattern. Confirms spec-kit is already producing the correct canonical names.

- [ ] **Step 4: Check that agents.yaml is referenced nowhere else**

  ```bash
  grep -r "agents\.yaml" /Users/michalbachorik/work/evolution/echelon/ \
    --include="*.md" --include="*.yaml" --include="*.yml" --include="*.py" \
    --include="*.sh" 2>/dev/null
  ```

  Expected: no output (the file is deleted and all references cleaned up).

- [ ] **Step 5: Commit final verification note**

  ```bash
  cd /Users/michalbachorik/work/evolution/echelon
  git add docs/superpowers/specs/2026-05-07-agent-identity-consolidation-design.md
  git add docs/superpowers/plans/2026-05-07-agent-identity-consolidation.md
  git commit -m "docs: add agent identity consolidation design doc and implementation plan"
  ```

---

## Self-Review Checklist

**Spec coverage check:**

| Spec requirement | Covered by |
|-----------------|-----------|
| Delete agents.yaml | Task 1 |
| Fix Role Separation table — spec-kit name + codename columns | Task 2, Step 1 |
| Fix routing rule — spec-kit names for dispatch actions | Task 2, Step 2 |
| Fix constitution — functional names → codenames/spec-kit names | Task 3 |
| Fix manager reflection — DISCOVER/HOW → spec-kit names | Task 4 |
| Convergence rules — WHY/INNOVATE/CALIBRATE/GROUND/ASSESS | Task 5 |
| Budget enforcement — functional names → spec-kit names | Task 6 |
| Error handling — HOW/PLAN → spec-kit names | Task 6 |
| Scorekeeper — WHY/WHAT/HOW → codenames | Task 7 |
| Full scan for remaining functional-name references | Task 8 |
| Verify definition.yaml already correct | Task 8 |
| Canonical identity rule note in dispatch section | Task 2 (dispatch name rule note added to table) |

**Placeholder check:** No TBDs, no TODOs.

**Journal phase labels:** `"per_phase": {"DISCOVER": ..., "WHY": ..., "HOW": ...}` and `"phase": "DISCOVER, WHAT, WHY, HOW, PLAN, ASSESS, SPECIALISTS, BUILD, FINALIZE"` in journal schema (~line 776) are intentionally left as-is — they are phase group identifiers consistent with `definition.yaml` phase ID prefixes, not agent dispatch names. This is the explicit exception from the design spec.
