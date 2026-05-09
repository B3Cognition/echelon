# echelon.build.md Workflow Externalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thin `echelon.build.md` from a 1260-line inline state machine to a ~40-line wrapper that delegates to `workflow/definition.yaml phases[]` + `workflow/phases/build-*.md` spec files — matching the pattern already used by `echelon.run.md` and `echelon.bugfix.md`.

**Architecture:** The inline build state machine (§1–§12 of `echelon.build.md`) is split into 8 phase spec files (`workflow/phases/build-*.md`). Eight phase nodes are appended to `phases[]` in `workflow/definition.yaml` — each with a `spec_file` pointer. The existing `build:` section in `definition.yaml` (machine-readable task-loop routing config) is **preserved untouched** — it serves a different orthogonal purpose. The command file becomes a thin bootstrap identical in structure to `echelon.run.md`.

**Tech Stack:** Markdown (phase spec files), YAML (`workflow/definition.yaml`). No application code changes.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `workflow/phases/build-1-init.md` | Sections §1.0–§1.5 of `echelon.build.md` |
| Create | `workflow/phases/build-2-implement.md` | Section §2 (BUILD_LOOP: wave lanes, IMPLEMENTER dispatch, handoff package) |
| Create | `workflow/phases/build-3-spec-guard.md` | Section §3 (SPEC_GUARD gate) |
| Create | `workflow/phases/build-4-code-review.md` | Section §4 (CODE_REVIEW gate) |
| Create | `workflow/phases/build-5-test-guard.md` | Section §5 (TEST_GUARD gate) |
| Create | `workflow/phases/build-6-progress.md` | Section §6 (PROGRESS TRACKER + MODELER + state update) |
| Create | `workflow/phases/build-7-integration.md` | Section §7 (INTEGRATOR + VISUAL VALIDATOR) |
| Create | `workflow/phases/build-8-finalize.md` | Sections §8–§12 (BUILD_DONE through harness integration) |
| Modify | `workflow/definition.yaml` | Append 10 build phase nodes to `phases[]` (after `bugfix-done`) |
| Modify | `extension/commands/echelon.build.md` | Replace with ~40-line thin wrapper |

---

## Task 1: Create `build-1-init.md`

**Files:**
- Create: `workflow/phases/build-1-init.md`

Content source: `extension/commands/echelon.build.md` — everything from the `## 1. Initialization (BUILD_INIT)` heading through the end of section `### 1.5 Initialize Build Reports` (lines 73–178 of the command file).

- [ ] **Step 1: Create the file with header + migrated content**

```markdown
# Phase: build-1-init
# Source: echelon.build.md §1 — Build Initialization (BUILD_INIT)
# Read by: COMMANDER before starting build workflow
```

Then paste the full content of `echelon.build.md` starting at `## 1. Initialization (BUILD_INIT)` (line 73) through and including `### 1.5 Initialize Build Reports` — ending with `**Transition:** Proceed to task iteration.`

Also prepend the Build Start State Update block that appears just before §1.0 (lines 74–80):

```markdown
## Build Start State Update (runs once before first task)

1. Set `state.json.spec_status` to `"in-progress"`.
2. Update `{spec_dir}/spec.md`: change `**Status**: Planned` to `**Status**: In Progress`.
3. Count all task lines in `{spec_dir}/tasks.md` (lines matching `^\s*- \[[ xX]\]`) — set as `state.json.build.total_tasks`.
4. Set `state.json.build.completed_tasks` to `0` and `state.json.build.tasks_completed_pct` to `0`.
```

- [ ] **Step 2: Verify content completeness**

Open both files side by side. Confirm all of these are present in `build-1-init.md`:
- `### 1.0 Anchor Project Root` with `PROJECT_ROOT=$(pwd)` bash block
- `### 1.0b Validate Deploy Infrastructure` with `validate-deploy.sh` invocation and HARD STOP rule
- `### 1.1 Validate Phase A Artifacts` with Required/Optional file lists
- `### 1.2 Parse Tasks` — all 8 fields listed
- `### 1.3 Determine Build Order` — 3 ordering rules
- `### 1.4 Initialize Build State` with the `state.json` JSON block
- `### 1.5 Initialize Build Reports` with 4 report file names

- [ ] **Step 3: Commit**

```bash
cd /Users/michalbachorik/work/evolution/echelon
git add workflow/phases/build-1-init.md
git commit -m "feat: add build-1-init phase spec file"
```

---

## Task 2: Create `build-2-implement.md`

**Files:**
- Create: `workflow/phases/build-2-implement.md`

Content source: `echelon.build.md` — `## 2. Task Iteration (BUILD_LOOP)` through the end of `### 2.5 Build Handoff Package` (lines 180–268).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-2-implement
# Source: echelon.build.md §2 — Task Iteration (BUILD_LOOP)
# Agent: IMPLEMENTER
# Read by: COMMANDER before each IMPLEMENTER dispatch
```

Then paste the full content of sections `## 2. Task Iteration (BUILD_LOOP)` through `### 2.5 Build Handoff Package` verbatim.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 2.0 v0.4.0 BUILD Lane Policy` — 5 numbered wave-lane rules
- `### 2.1 Check Dependencies` — blocked semantics (2 rules)
- `### 2.2 Update State` — JSON block with `current_task` and `current_phase_group`
- `### 2.3 Dispatch speckit-echelon-implementer` — full `<context>/<instructions>` XML template with `subagent_type`, `prompt`, `description` fields
- Inline execution mode note (paragraph starting "**Inline execution mode:**")
- `### 2.5 Build Handoff Package` — 6 numbered fields (tasks, gate_results, artifact_index, required_task_summary, blocked_optional_out_of_scope, scope_version) + `BUILD_QA_HANDOFF_REJECTED` rule

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-2-implement.md
git commit -m "feat: add build-2-implement phase spec file"
```

---

## Task 3: Create `build-3-spec-guard.md`

**Files:**
- Create: `workflow/phases/build-3-spec-guard.md`

Content source: `echelon.build.md` — `## 3. Spec Guard Gate (SPEC_GUARD)` (lines 272–318).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-3-spec-guard
# Source: echelon.build.md §3 — Spec Guard Gate (SPEC_GUARD)
# Agent: SPEC GUARD
# Read by: COMMANDER before each SPEC GUARD dispatch
```

Then paste the full content of `## 3. Spec Guard Gate (SPEC_GUARD)` verbatim through `### On Non-Obvious FAIL`.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 3.1 Dispatch speckit-echelon-spec-guard` — full XML dispatch template with 4 context_pack items
- `### 3.2 Handle Result` — PASS / FAIL / WARN verdicts with endocrine calls
- `### On Non-Obvious FAIL` — 5-step DEBUGGER routing rule

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-3-spec-guard.md
git commit -m "feat: add build-3-spec-guard phase spec file"
```

---

## Task 4: Create `build-4-code-review.md`

**Files:**
- Create: `workflow/phases/build-4-code-review.md`

Content source: `echelon.build.md` — `## 4. Code Review Gate (CODE_REVIEW)` (lines 320–354).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-4-code-review
# Source: echelon.build.md §4 — Code Review Gate (CODE_REVIEW)
# Agent: CODE REVIEWER
# Read by: COMMANDER before each CODE REVIEWER dispatch
```

Then paste the full content of `## 4. Code Review Gate (CODE_REVIEW)` verbatim.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 4.1 Dispatch speckit-echelon-code-reviewer` — full XML dispatch template with 4 context_pack items
- `### 4.2 Handle Result` — APPROVED / CHANGES_REQUESTED / BLOCKED verdicts with endocrine calls

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-4-code-review.md
git commit -m "feat: add build-4-code-review phase spec file"
```

---

## Task 5: Create `build-5-test-guard.md`

**Files:**
- Create: `workflow/phases/build-5-test-guard.md`

Content source: `echelon.build.md` — `## 5. Test Guardian Gate (TEST_GUARD)` (lines 358–393).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-5-test-guard
# Source: echelon.build.md §5 — Test Guardian Gate (TEST_GUARD)
# Agent: TEST GUARDIAN
# Read by: COMMANDER before each TEST GUARDIAN dispatch
```

Then paste the full content of `## 5. Test Guardian Gate (TEST_GUARD)` verbatim.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 5.1 Dispatch speckit-echelon-test-guardian` — full XML dispatch template with 5 context_pack items
- `### 5.2 Handle Result` — PASS / FAIL / WARN verdicts with endocrine calls

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-5-test-guard.md
git commit -m "feat: add build-5-test-guard phase spec file"
```

---

## Task 6: Create `build-6-progress.md`

**Files:**
- Create: `workflow/phases/build-6-progress.md`

Content source: `echelon.build.md` — `## 6. Progress Tracking (PROGRESS)` (lines 397–479).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-6-progress
# Source: echelon.build.md §6 — Progress Tracking (PROGRESS)
# Agents: PROGRESS TRACKER, then MODELER (COMMANDER-dispatched)
# Read by: COMMANDER after each task's quality gates complete
```

Then paste the full content of `## 6. Progress Tracking (PROGRESS)` verbatim through the `### speckit-echelon-modeler (MODELER) Update` block including the invariant alert gate.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 6.1 Dispatch speckit-echelon-progress-tracker` — full XML dispatch template with 6 context_pack items; instructions include `state.json.build.completed_tasks` increment
- `### 6.2 Handle Alerts` — DRIFT WARNING / PHASE OVERRUN rules
- `### 6.3 Update Task Result` — mandatory COMMANDER action block with JSON structure, `tasks_completed_pct` recompute formula, and "**This step MUST execute regardless of execution mode**" mandate
- `speckit-echelon-modeler (MODELER) Update` paragraph — files input, `mental-model-code.md` update
- Invariant alert gate — `invariant_violations` check, HIGH severity journal entry, warning format, non-blocking rule

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-6-progress.md
git commit -m "feat: add build-6-progress phase spec file"
```

---

## Task 7: Create `build-7-integration.md`

**Files:**
- Create: `workflow/phases/build-7-integration.md`

Content source: `echelon.build.md` — `## 7. Phase Checkpoint (INTEGRATION)` (lines 483–568).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-7-integration
# Source: echelon.build.md §7 — Phase Checkpoint (INTEGRATION)
# Agents: INTEGRATOR, then optionally VISUAL VALIDATOR
# Read by: COMMANDER after all tasks in a phase group complete
```

Then paste the full content of `## 7. Phase Checkpoint (INTEGRATION)` verbatim including subsections `### 7.1` through `### 7.3 Record Checkpoint`.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### When` — trigger rule ("after all tasks in a phase group")
- `### 7.1 Dispatch speckit-echelon-integrator` — full XML dispatch template
- `### 7.2 Handle Result` — PASS / FAIL verdicts with endocrine calls and fix cycle limit
- `### 7.2.1 Visual Validator Dispatch (MANDATORY for browser/SPA apps)` — stack detection list, full XML dispatch template, VISUAL_PASS / VISUAL_FAIL handling, "If not browser/SPA: skip" rule
- `### 7.3 Record Checkpoint` — JSON structure appended to `state.json.build.phase_checkpoints`

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-7-integration.md
git commit -m "feat: add build-7-integration phase spec file"
```

---

## Task 8: Create `build-8-finalize.md`

**Files:**
- Create: `workflow/phases/build-8-finalize.md`

Content source: `echelon.build.md` — `## 8. Build Complete (BUILD_DONE)` through `## 12. Harness Integration: Report Build Status` (lines 571–1260).

- [ ] **Step 1: Create the file**

```markdown
# Phase: build-8-finalize
# Source: echelon.build.md §8–§12 — Build Complete through Harness Integration
# Read by: COMMANDER after all phase checkpoints pass
```

Then paste the full content of sections §8 through §12 verbatim.

- [ ] **Step 2: Verify content completeness**

Confirm all of these are present:
- `### 8.1 Final Integration` — final full-codebase INTEGRATOR dispatch
- `### 8.1b Engineering Manager Sign-Off` — full XML dispatch template, 4 confirmation items
- `### 8.1b.1 verify.sh Smoke Test Requirement (MANDATORY)` — minimum smoke test pattern for web + Node/Express/Python/FastAPI/static/no-HTTP variants, Next.js stricter rules
- `### 8.1b.2 verify.sh Security and License Gate (MANDATORY)` — security scan table (5 ecosystems) + license check table (5 ecosystems) + polyglot rule
- `### 8.1c Final Verification` — VERIFICATION dispatch template, 3 mandated outputs, PASS/FAIL handling, Specification Complete steps
- `### 8.2 Collect Reports` — 7 required report files
- `### 8.3 Update State` — JSON block + Run History Write (5 steps)
- `### 8.4 Run speckit-echelon-scorekeeper` — full XML dispatch template + build-specific scoring table
- `### 8.5 Auto-Feedback & Post-Build Validation (Phase 5)` — config gate, AUDITOR dispatch (Mode 4), COMMANDER triage table (5 finding types), post-build-validation (SAGE re-scan + TRACKER alignment), drift severity gate (ALIGNED/MINOR_DRIFT/MAJOR_DRIFT with and without banzai), auto-update KB (4 files), final feedback summary format
- `### 8.6 Consolidation Phase` — MIRROR + VETERAN parallel dispatch, merge/filter logic, constitution-amendment-candidates.md write, `[PROPOSED]` block format
- `### 8.7 Print Summary` — full terminal output block with all sections including HUMAN ACTIONS REQUIRED mandate
- `## 9. Error Handling` — task-level and phase-level failure tables + degraded mode banner format
- `## 10. Convergence Rules` — 6 bullet rules
- `## 11. Quick Reference: Build Flow` — ASCII flow diagram
- `## 12. Harness Integration: Report Build Status` — `HARNESS_BUILD_STATUS_FILE` bash block for done + impasse

- [ ] **Step 3: Commit**

```bash
git add workflow/phases/build-8-finalize.md
git commit -m "feat: add build-8-finalize phase spec file"
```

---

## Task 9: Add build phase nodes to `workflow/definition.yaml`

**Files:**
- Modify: `workflow/definition.yaml`

Location: append immediately after the `bugfix-done` terminal node (currently around line 849) and before the `# =============================================================================` separator that opens the `build:` section.

- [ ] **Step 1: Insert the build workflow comment block and 10 nodes**

Insert the following YAML block between `  - id: bugfix-done` ... `    type: terminal` and the `# ====` separator for `build:`:

```yaml
  # --------------------------------------------------------------------------
  # BUILD WORKFLOW
  # Invoked via speckit.echelon.build. Entry point: build-1-init.
  # Routing config (task loop ordering, verdict routing, wave lanes) lives in
  # the top-level build: section below — COMMANDER reads both.
  # --------------------------------------------------------------------------
  - id: build-1-init
    label: "Build Init"
    spec_file: workflow/phases/build-1-init.md
    type: commander_internal
    description: >
      Anchor project root, validate deploy infrastructure,
      validate Phase A artifacts, parse tasks, determine build order,
      initialize state.json and report files.
    transitions:
      - to: build-2-implement
        condition: always

  - id: build-2-implement
    label: "Task Implementation (IMPLEMENTER)"
    spec_file: workflow/phases/build-2-implement.md
    type: agent
    agent: speckit-echelon-implementer
    tier: build
    context_pack:
      - task definition (from tasks.md)
      - spec.md (relevant FRs only)
      - constitution.md
      - research.md (relevant ADRs)
      - existing code from completed tasks
      - test-strategy.md (relevant section)
      - data-model.md (if present)
      - contracts/ (if present)
    transitions:
      - to: build-3-spec-guard
        condition: verdict in [DONE, DONE_WITH_CONCERNS]
      - to: build-2-implement
        condition: verdict = NEEDS_CONTEXT and retry_count < 2
      - to: build-2-implement
        condition: verdict = BLOCKED
        state_update:
          task_status: BLOCKED
          note: skip task, check if blocked_task_count >= 3

  - id: build-3-spec-guard
    label: "Spec Compliance Gate (SPEC GUARD)"
    spec_file: workflow/phases/build-3-spec-guard.md
    type: agent
    agent: speckit-echelon-spec-guard
    tier: build
    context_pack:
      - files changed by IMPLEMENTER
      - task definition (acceptance criteria, FR references)
      - spec.md (full, for cross-reference)
    transitions:
      - to: build-4-code-review
        condition: verdict = PASS
      - to: build-2-implement
        condition: verdict = FAIL and fix_cycle < 2
      - to: build-4-code-review
        condition: verdict = FAIL and fix_cycle >= 2
        state_update:
          task_status: DEGRADED

  - id: build-4-code-review
    label: "Code Review Gate (CODE REVIEWER)"
    spec_file: workflow/phases/build-4-code-review.md
    type: agent
    agent: speckit-echelon-code-reviewer
    tier: build
    context_pack:
      - files changed by IMPLEMENTER
      - constitution.md
      - research.md (relevant ADRs)
      - existing codebase patterns (prior completed tasks)
    transitions:
      - to: build-5-test-guard
        condition: verdict = APPROVED
      - to: build-2-implement
        condition: verdict = CHANGES_REQUESTED and fix_cycle < 2
      - to: build-5-test-guard
        condition: verdict = CHANGES_REQUESTED and fix_cycle >= 2
        state_update:
          task_status: DEGRADED
      - to: escalate
        condition: verdict = BLOCKED

  - id: build-5-test-guard
    label: "Test Quality Gate (TEST GUARDIAN)"
    spec_file: workflow/phases/build-5-test-guard.md
    type: agent
    agent: speckit-echelon-test-guardian
    tier: build
    context_pack:
      - test files from IMPLEMENTER
      - source files from IMPLEMENTER
      - task acceptance criteria
      - test-strategy.md (relevant section)
      - coverage-map.md
    transitions:
      - to: build-6-progress
        condition: verdict in [PASS, WARN]
      - to: build-2-implement
        condition: verdict = FAIL and fix_cycle < 2
      - to: build-6-progress
        condition: verdict = FAIL and fix_cycle >= 2
        state_update:
          task_status: DEGRADED

  - id: build-6-progress
    label: "Progress Tracking (PROGRESS TRACKER + MODELER)"
    spec_file: workflow/phases/build-6-progress.md
    type: agent
    agent: speckit-echelon-progress-tracker
    tier: build
    description: >
      Records task effort and checks for drift. COMMANDER then dispatches
      MODELER to update mental-model-code.md and increments
      state.json.build.completed_tasks. Loops to build-2-implement for
      the next task, or to build-7-integration when the phase group ends.
    context_pack:
      - completed task ID and estimated effort
      - count of review cycles
      - estimates.md
      - knowledge-base/calibration-profile.yaml
      - knowledge-base/estimates-log.yaml
      - progress-report.md (current)
    transitions:
      - to: build-7-integration
        condition: phase_group_complete
      - to: build-2-implement
        condition: more_tasks_in_phase_group
      - to: build-8-finalize
        condition: all_tasks_complete and no_more_phase_checkpoints

  - id: build-7-integration
    label: "Phase Checkpoint (INTEGRATOR + VISUAL VALIDATOR)"
    spec_file: workflow/phases/build-7-integration.md
    type: agent
    agent: speckit-echelon-integrator
    tier: build
    description: >
      Integration check after each phase group. Optionally dispatches
      VISUAL VALIDATOR for browser/SPA stacks after INTEGRATOR PASS.
      Also runs as final full-system check (all phases complete).
    context_pack:
      - all code produced in this phase group
      - build configuration files
      - contracts/
      - data-model.md (if present)
      - prior integration-report.md (if any)
    transitions:
      - to: build-2-implement
        condition: verdict = PASS and more_phase_groups
      - to: build-8-finalize
        condition: verdict = PASS and all_phase_groups_complete
      - to: build-2-implement
        condition: verdict = FAIL and fix_cycle < 2
      - to: build-8-finalize
        condition: verdict = FAIL and fix_cycle >= 2
        state_update:
          phase_status: DEGRADED

  - id: build-8-finalize
    label: "Build Finalize"
    spec_file: workflow/phases/build-8-finalize.md
    type: commander_internal
    description: >
      Final integration pass, Engineering Manager sign-off,
      Verification (backpropagation), Scorekeeper, auto-feedback loop
      (Auditor + post-build validation + KB update), constitution
      amendment candidates (Mirror + Veteran), run history write,
      harness status report, print summary.
    transitions:
      - to: build-done
        condition: always

  - id: build-done
    label: "Build Complete"
    type: terminal
```

- [ ] **Step 2: Verify YAML is valid**

```bash
cd /Users/michalbachorik/work/evolution/echelon
python3 -c "import yaml; yaml.safe_load(open('workflow/definition.yaml')); print('YAML valid')"
```

Expected output: `YAML valid`

- [ ] **Step 3: Verify the 10 nodes are present**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('workflow/definition.yaml'))
build_ids = [p['id'] for p in d['phases'] if p['id'].startswith('build-')]
print('\n'.join(build_ids))
print(f'Total: {len(build_ids)}')
"
```

Expected output:
```
build-1-init
build-2-implement
build-3-spec-guard
build-4-code-review
build-5-test-guard
build-6-progress
build-7-integration
build-8-finalize
build-done
Total: 9
```

- [ ] **Step 4: Verify `build:` section is still present and untouched**

```bash
python3 -c "
import yaml
d = yaml.safe_load(open('workflow/definition.yaml'))
assert 'build' in d, 'build: section missing!'
assert 'task_loop' in d['build'], 'task_loop missing from build: section!'
assert 'pre_build' in d['build'], 'pre_build missing from build: section!'
print('build: section intact')
"
```

Expected output: `build: section intact`

- [ ] **Step 5: Commit**

```bash
git add workflow/definition.yaml
git commit -m "feat: add build phase nodes to workflow/definition.yaml phases[]"
```

---

## Task 10: Replace `echelon.build.md` with thin wrapper

**Files:**
- Modify: `extension/commands/echelon.build.md`

- [ ] **Step 1: Replace the file content**

The new content of `extension/commands/echelon.build.md`:

```markdown
---
name: speckit.echelon.build
description: "Execute building phase — implement tasks with role-based agents and quality gates. Run after speckit.echelon.run completes Phase A."
argument-hint: "...you will be assimilated"
scripts:
  sh: ../../scripts/bash/startup-banner.sh
---

## Role

You are MANAGER executing the build phase.

**Read `agents/control/commander.md` first** — it contains your complete behavioral
framework: role separation, governance constraints, dispatch protocols, convergence
rules, error handling, and all NEVER rules.

Then read `workflow/definition.yaml` `phases[]`. Start at phase `build-1-init`,
before each dispatch read the phase node's `spec_file` for context pack assembly,
dispatch prompt, and expected outputs.

Also read `workflow/definition.yaml` `build:` for the task loop routing config:
wave lane ordering, per-agent verdict routing, state field names, and
force-complete conditions. COMMANDER consults this section throughout the build
loop — it is not replaced by the phase nodes above.

**This command implements. It never produces ADR/SPEC/PLAN/TASKS artifacts.**

---

## Scope Boundary

NEVER skip quality gates. NEVER mark a task DONE without spec guard, code review,
and test guardian passing (or explicitly flagged as DEGRADED after max fix cycles).
BUILD_DONE is forbidden while `verification-summary.md` is FAIL or `gap-report.md`
contains open gaps.

---

## Execution Continuity — MANDATORY

**Tool completions are never stopping points.** After any `Agent`, `Skill`, or
`Bash` tool returns — however complete or final its output looks — immediately
execute the next step in the build state machine without ending your response.
Stop only when: (a) the state machine reaches DONE, (b) a BLOCKED/ERROR condition
cannot be self-resolved, or (c) a human checkpoint is reached in `guided`/`semi`
mode.

---

## User Input

$ARGUMENTS
```

- [ ] **Step 2: Verify line count is reasonable**

```bash
wc -l extension/commands/echelon.build.md
```

Expected: 50–55 lines (thin wrapper).

- [ ] **Step 3: Verify the three key references are present**

```bash
grep -c "commander.md\|phases\[\]\|build:" extension/commands/echelon.build.md
```

Expected output: `3` (one match each for `commander.md`, `phases[]`, and `build:`).

- [ ] **Step 4: Commit**

```bash
git add extension/commands/echelon.build.md
git commit -m "refactor: thin echelon.build.md to phase-delegating wrapper"
```

---

## Task 11: Cross-reference verification

**Files:**
- Read: `extension/commands/echelon.build.md`
- Read: `workflow/definition.yaml`
- Read: `workflow/phases/build-*.md` (all 8)

- [ ] **Step 1: Verify every spec_file pointer resolves**

```bash
cd /Users/michalbachorik/work/evolution/echelon
python3 -c "
import yaml, os
d = yaml.safe_load(open('workflow/definition.yaml'))
missing = []
for p in d['phases']:
    sf = p.get('spec_file')
    if sf and not os.path.exists(sf):
        missing.append(sf)
if missing:
    print('MISSING:', missing)
else:
    print('All spec_file paths resolve')
"
```

Expected output: `All spec_file paths resolve`

- [ ] **Step 2: Verify all 8 build phase files have correct header format**

```bash
for f in workflow/phases/build-*.md; do
  echo "=== $f ==="
  head -5 "$f"
done
```

Each file must start with:
```
# Phase: build-N-name
# Source: echelon.build.md §N — ...
```

- [ ] **Step 3: Verify section coverage — no content lost**

For each of the following sections confirm it exists in EXACTLY ONE of the 8 phase files (not zero, not two):

```bash
for term in \
  "Anchor Project Root" \
  "Validate Deploy Infrastructure" \
  "BUILD Lane Policy" \
  "Build Handoff Package" \
  "On Non-Obvious FAIL" \
  "endocrine.sh on_gate_pass" \
  "invariant_violations" \
  "Visual Validator Dispatch" \
  "verify.sh Smoke Test Requirement" \
  "verify.sh Security and License Gate" \
  "Auto-Feedback" \
  "Constitution Amendment" \
  "HARNESS_BUILD_STATUS_FILE" \
  "Quick Reference"; do
  count=$(grep -rl "$term" workflow/phases/build-*.md | wc -l)
  echo "$count  $term"
done
```

Expected: every line shows `1  <term>`. Any `0` means content was lost during migration.

- [ ] **Step 4: Verify `echelon.run.md` structural parity**

Both `echelon.run.md` and `echelon.build.md` should follow the same wrapper pattern:

```bash
echo "=== echelon.run.md ===" && cat extension/commands/echelon.run.md
echo "=== echelon.build.md ===" && cat extension/commands/echelon.build.md
```

Confirm both have: frontmatter, `## Role`, `commander.md` reference, `workflow/definition.yaml phases[]` + start-phase reference, scope boundary, `$ARGUMENTS`.

- [ ] **Step 5: Final commit**

```bash
git add -p  # stage any cleanup tweaks found during verification
git commit -m "chore: verify echelon.build.md externalization complete" --allow-empty
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All 12 sections of `echelon.build.md` are mapped — §1→T1, §2→T2, §3→T3, §4→T4, §5→T5, §6→T6, §7→T7, §8–12→T8. Phase nodes in T9 cover all 8 spec files.
- [x] **No placeholders:** All task steps contain exact file content, exact commands, exact expected output.
- [x] **Type consistency:** Phase IDs in YAML (T9) match `spec_file` paths exactly (`build-1-init` → `workflow/phases/build-1-init.md`). Agent names match extension.yml convention (`speckit-echelon-*`).
- [x] **`build:` section preserved:** T9 includes explicit YAML validation that `task_loop` and `pre_build` keys survive.
- [x] **Execution Continuity block:** Preserved verbatim from original `echelon.build.md` in the new wrapper (T10).
- [x] **`argument-hint` preserved:** `"...you will be assimilated"` carried into T10 wrapper.
