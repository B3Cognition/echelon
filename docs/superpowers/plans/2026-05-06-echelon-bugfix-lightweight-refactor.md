# echelon.bugfix.md Lightweight Orchestrator Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce `extension/commands/echelon.bugfix.md` to a thin wrapper (~20 lines) by extracting its 6-step workflow into `workflow/phases/bugfix-*.md` files and registering them in `workflow/definition.yaml`, giving COMMANDER the behavioral framework from `commander.md`.

**Architecture:** Same pattern as the `echelon.run.md` refactor: command file becomes a thin delegator (load commander.md + state entry phase), per-phase execution detail moves to `workflow/phases/`, and `workflow/definition.yaml` `phases[]` gets the phase graph with `spec_file:` links. Linear 5-phase workflow — no routing logic, all `always` transitions.

**Tech Stack:** Markdown, YAML. Verification via grep/wc/bash — no compilation.

**Reference spec:** `docs/superpowers/specs/2026-05-06-echelon-bugfix-lightweight-refactor-design.md`  
**Source document:** `extension/commands/echelon.bugfix.md` — steps are referenced by their `## Step N` headings.

---

## File Map

**Create:**
```
workflow/phases/bugfix-1-init.md
workflow/phases/bugfix-2-diagnose.md
workflow/phases/bugfix-3-test-strategy.md
workflow/phases/bugfix-4-spec-compliance.md
workflow/phases/bugfix-5-finalize.md
```

**Modify:**
```
workflow/definition.yaml                       add 6 nodes to phases[] (5 phases + terminal)
extension/commands/echelon.bugfix.md           replace body with thin wrapper
```

---

## Task 1: Extract bugfix-1-init.md and bugfix-2-diagnose.md

**Files:**
- Create: `workflow/phases/bugfix-1-init.md`
- Create: `workflow/phases/bugfix-2-diagnose.md`
- Source: `extension/commands/echelon.bugfix.md`

- [ ] **Step 1: Create `workflow/phases/bugfix-1-init.md`**

Read `extension/commands/echelon.bugfix.md`. Copy content from `## Step 0: Ensure on Default Branch` through the end of `## Step 1: Parse Input` (everything up to but NOT including `## Step 2: DEBUGGER`).

Create `workflow/phases/bugfix-1-init.md` with this header followed by that content:

```
# Phase: bugfix-1-init
# Source: echelon.bugfix.md §Steps 0–1 — Init
# Read by: COMMANDER before starting bugfix workflow
```

- [ ] **Step 2: Create `workflow/phases/bugfix-2-diagnose.md`**

Copy content of `## Step 2: DEBUGGER — Root Cause Analysis` (up to but NOT including `## Step 3: SENTINEL`).

Create `workflow/phases/bugfix-2-diagnose.md`:

```
# Phase: bugfix-2-diagnose
# Source: echelon.bugfix.md §Step 2 — DEBUGGER Root Cause Analysis
# Agent: DEBUGGER
# Read by: COMMANDER before dispatching DEBUGGER
```

- [ ] **Step 3: Verify both files exist with correct content**

```bash
grep "DEBUGGER" /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-2-diagnose.md | head -1
grep "Step 1: Parse Input" /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-1-init.md | head -1
```

Expected: each grep returns a match.

- [ ] **Step 4: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/bugfix-1-init.md workflow/phases/bugfix-2-diagnose.md
git commit -m "refactor: extract bugfix-1-init and bugfix-2-diagnose to workflow/phases/"
```

---

## Task 2: Extract bugfix-3-test-strategy.md, bugfix-4-spec-compliance.md, bugfix-5-finalize.md

**Files:**
- Create: `workflow/phases/bugfix-3-test-strategy.md`
- Create: `workflow/phases/bugfix-4-spec-compliance.md`
- Create: `workflow/phases/bugfix-5-finalize.md`
- Source: `extension/commands/echelon.bugfix.md`

- [ ] **Step 1: Create `workflow/phases/bugfix-3-test-strategy.md`**

Copy content of `## Step 3: SENTINEL — Test Strategy` (up to but NOT including `## Step 4: SPEC GUARD`).

Create `workflow/phases/bugfix-3-test-strategy.md`:

```
# Phase: bugfix-3-test-strategy
# Source: echelon.bugfix.md §Step 3 — SENTINEL Test Strategy
# Agent: SENTINEL
# Read by: COMMANDER before dispatching SENTINEL
```

- [ ] **Step 2: Create `workflow/phases/bugfix-4-spec-compliance.md`**

Copy content of `## Step 4: SPEC GUARD — Scope Validation` (up to but NOT including `## Step 5: Write Bugfix Artifacts`).

Create `workflow/phases/bugfix-4-spec-compliance.md`:

```
# Phase: bugfix-4-spec-compliance
# Source: echelon.bugfix.md §Step 4 — SPEC GUARD Scope Validation
# Agent: SPEC_GUARD
# Read by: COMMANDER before dispatching SPEC GUARD
```

- [ ] **Step 3: Create `workflow/phases/bugfix-5-finalize.md`**

Copy content from `## Step 5: Write Bugfix Artifacts` through the end of `## Step 6: Handoff` (the end of the file, before the current thin sections like Professional Conduct).

Create `workflow/phases/bugfix-5-finalize.md`:

```
# Phase: bugfix-5-finalize
# Source: echelon.bugfix.md §Steps 5–6 — Write Artifacts + Handoff
# Read by: COMMANDER before executing finalization sequence
```

- [ ] **Step 4: Verify all three files**

```bash
grep "SENTINEL" /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-3-test-strategy.md | head -1
grep "SPEC GUARD\|SPEC_GUARD" /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-4-spec-compliance.md | head -1
grep "bugfix-{n}.md\|Handoff\|harness-run" /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-5-finalize.md | head -1
```

Expected: each grep returns a match.

```bash
ls /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-*.md | wc -l
```

Expected: `5`

- [ ] **Step 5: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/bugfix-3-test-strategy.md workflow/phases/bugfix-4-spec-compliance.md \
        workflow/phases/bugfix-5-finalize.md
git commit -m "refactor: extract bugfix-3 through bugfix-5 to workflow/phases/ — all 5 bugfix phase files complete"
```

---

## Task 3: Add bugfix phases to `workflow/definition.yaml`

**Files:**
- Modify: `workflow/definition.yaml`

- [ ] **Step 1: Read `workflow/definition.yaml`**

Find the `escalate` terminal node at the end of `phases[]`. Append the following 6 nodes immediately after it (still inside the `phases:` list):

```yaml
  # --------------------------------------------------------------------------
  # BUGFIX WORKFLOW
  # Invoked via speckit.echelon.bugfix. Entry point: bugfix-1-init.
  # --------------------------------------------------------------------------
  - id: bugfix-1-init
    label: "Bugfix Init"
    spec_file: workflow/phases/bugfix-1-init.md
    type: commander_internal
    description: >
      Parse arguments, verify default branch, locate spec dir,
      identify relevant source files. No agent dispatch.
    steps:
      - id: branch_check
        label: "Ensure on default branch"
      - id: parse_args
        label: "Parse spec_id and description from $ARGUMENTS"
      - id: locate_spec
        label: "Locate specs/{spec_id}-{spec_name}/ directory"
      - id: read_context
        label: "Read spec files and source files into context"
        files:
          - spec.md
          - coverage-map.md
          - tasks.md
          - deploy-state.json
        missing_files: skip_gracefully
      - id: identify_source_files
        label: "Identify relevant source files from description"
    transitions:
      - to: bugfix-2-diagnose
        condition: always

  - id: bugfix-2-diagnose
    label: "Root Cause Analysis (DEBUGGER)"
    spec_file: workflow/phases/bugfix-2-diagnose.md
    type: agent
    agent: DEBUGGER
    tier: build
    context_pack:
      - user description
      - spec.md
      - relevant source files (from bugfix-1-init)
      - deploy-state.json (if exists)
    outputs:
      - debugger_report (root cause, fix description, risk surface)
    transitions:
      - to: bugfix-3-test-strategy
        condition: always

  - id: bugfix-3-test-strategy
    label: "Test Strategy (SENTINEL)"
    spec_file: workflow/phases/bugfix-3-test-strategy.md
    type: agent
    agent: SENTINEL
    tier: solution
    context_pack:
      - debugger_report
      - spec.md
      - coverage-map.md (if exists)
      - existing test files for affected component
    outputs:
      - test_strategy (failing test spec + regression coverage)
    transitions:
      - to: bugfix-4-spec-compliance
        condition: always

  - id: bugfix-4-spec-compliance
    label: "Spec Compliance (SPEC GUARD)"
    spec_file: workflow/phases/bugfix-4-spec-compliance.md
    type: agent
    agent: SPEC_GUARD
    tier: build
    context_pack:
      - spec.md
      - coverage-map.md (if exists)
      - debugger_report
    outputs:
      - spec_guard_report (scope validation, requirement mapping)
    transitions:
      - to: bugfix-5-finalize
        condition: always

  - id: bugfix-5-finalize
    label: "Bugfix Finalize"
    spec_file: workflow/phases/bugfix-5-finalize.md
    type: commander_internal
    description: >
      Write bugfix-{n}.md from all three reports. Append BF{n} tasks
      to tasks.md. Switch to feature branch for artifact commit.
      Return to default branch. Print handoff banner.
    context_pack:
      - debugger_report
      - test_strategy
      - spec_guard_report
    outputs:
      - specs/{spec_id}-{spec_name}/bugfix-{n}.md
      - specs/{spec_id}-{spec_name}/tasks.md
    transitions:
      - to: bugfix-done
        condition: always

  - id: bugfix-done
    label: "Bugfix Complete"
    type: terminal
```

- [ ] **Step 2: Verify spec_file count and targets**

```bash
grep -c "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml
```

Expected: `23` (18 from run refactor + 5 new bugfix phases).

```bash
grep "spec_file:.*bugfix" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml \
  | awk '{print $2}' \
  | while read f; do
      [ -f "/Users/michalbachorik/work/evolution/echelon/$f" ] \
        && echo "OK: $f" || echo "MISSING: $f"
    done
```

Expected: 5 lines, all `OK:`.

- [ ] **Step 3: Verify bugfix-done terminal exists**

```bash
grep -A2 "id: bugfix-done" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml
```

Expected: `type: terminal` on the following line.

- [ ] **Step 4: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/definition.yaml
git commit -m "refactor: add bugfix phase nodes to definition.yaml phases[]"
```

---

## Task 4: Slim `echelon.bugfix.md` to thin wrapper

**Files:**
- Modify: `extension/commands/echelon.bugfix.md`

- [ ] **Step 1: Read the current file**

Keep the YAML frontmatter (lines 1–6, between `---` delimiters) EXACTLY unchanged. Replace everything after the closing `---` with:

```markdown
## Role

You are MANAGER executing a diagnostic triage for a delivered spec.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, and all NEVER rules.

Then read `workflow/definition.yaml` `phases[]`. Start at phase `bugfix-1-init`,
before each dispatch read the phase node's `spec_file` for context pack assembly,
dispatch prompt, and expected outputs.

**This command diagnoses and plans only. It never implements.**

---

## Scope Boundary

NEVER write, modify, or delete application source files. NEVER run tests, builds,
or linters on target project code. NEVER fix bugs or implement features directly.
The output of this command is `bugfix-{n}.md` + updated `tasks.md`, ready for
`speckit.echelon.harness-run`.

---

## User Input

$ARGUMENTS
```

- [ ] **Step 2: Verify line count**

```bash
wc -l /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
```

Expected: ≤ 35 lines.

- [ ] **Step 3: Verify frontmatter intact**

```bash
head -7 /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
```

Expected: YAML frontmatter with `name`, `description`, `behavior` fields unchanged.

- [ ] **Step 4: Verify delegation references present**

```bash
grep "agents/control/commander.md" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
grep "workflow/definition.yaml" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
grep "bugfix-1-init" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
grep "ARGUMENTS" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
```

Expected: each returns a match.

- [ ] **Step 5: Verify original step headings are gone**

```bash
grep "## Step [0-9]\|## Overview\|## Professional Conduct\|## Execution Continuity" \
  /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
```

Expected: no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add extension/commands/echelon.bugfix.md
git commit -m "refactor: slim echelon.bugfix.md to thin orchestrator wrapper (~30 lines)"
```

---

## Task 5: Final verification — nothing orphaned

- [ ] **Step 1: All 5 bugfix phase files exist and are non-empty**

```bash
for f in /Users/michalbachorik/work/evolution/echelon/workflow/phases/bugfix-*.md; do
  lines=$(wc -l < "$f")
  echo "$lines $(basename $f)"
done
```

Expected: 5 files, each > 10 lines.

- [ ] **Step 2: echelon.bugfix.md is ≤ 35 lines**

```bash
wc -l /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
```

Expected: ≤ 35.

- [ ] **Step 3: definition.yaml has 23 spec_file entries, all existing**

```bash
grep -c "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml
```

Expected: `23`.

```bash
grep "spec_file:" /Users/michalbachorik/work/evolution/echelon/workflow/definition.yaml \
  | awk '{print $2}' \
  | while read f; do
      [ -f "/Users/michalbachorik/work/evolution/echelon/$f" ] \
        && echo "OK: $f" || echo "MISSING: $f"
    done
```

Expected: all `OK:`.

- [ ] **Step 4: MANAGER + commander.md delegation consistent with echelon.run.md**

```bash
grep "You are MANAGER" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.bugfix.md
grep "You are MANAGER" /Users/michalbachorik/work/evolution/echelon/extension/commands/echelon.run.md
```

Expected: both return a match — consistent phrasing.

- [ ] **Step 5: Run test suite — confirm no regressions**

```bash
bash /Users/michalbachorik/work/evolution/echelon/tests/test-unit-registry-sync.sh 2>&1 | tail -5
bash /Users/michalbachorik/work/evolution/echelon/tests/test-unit-commander-loading.sh 2>&1 | tail -5
```

Expected: both print `ALL PASSED` or results with 0 new failures.

- [ ] **Step 6: Final commit if any loose files remain**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git status
```

Expected: clean (all changes committed in prior tasks). If anything remains uncommitted, stage and commit with message `refactor: final cleanup for echelon.bugfix lightweight refactor`.
