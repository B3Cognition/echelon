---
description: "Run full backpropagation verification — checks ALL requirements against ALL code"
---

## User Input

$ARGUMENTS

---

## Overview

This command runs the VERIFICATION agent to perform a complete backpropagation check: starting from EVERY requirement in spec.md, trace backward through the implementation to verify 100% coverage.

Unlike SPEC GUARD (which checks per-task, forward), VERIFICATION checks the ENTIRE spec against the ENTIRE codebase.

## When to Use

- After all build tasks are complete
- After rework tasks are completed
- When you want to confirm the implementation is truly done
- Before declaring the build complete

## Steps

### 0. QA Phase Entry Gate (v0.4.0)

Before verification begins, require a valid BUILD handoff package with:

1. All required tasks in `BUILD_COMPLETE`.
2. Zero required blocked tasks.
3. Optional blocked tasks allowed only when `OUT_OF_SCOPE` with rationale.

If any precondition fails, reject QA intake and keep workflow in `BUILD_IN_PROGRESS`.

### 1. Locate Artifacts

Read `.specify/squad/state.json` to find the active feature.
Load: spec.md, traceability-matrix.md, tasks.md, constitution.md

### 2. Dispatch VERIFICATION Agent

Use the Agent tool to dispatch a subagent:

- Read `agents/build/verification.md` for the full prompt
- Provide: spec.md (full), all source code paths, all test paths, traceability-matrix.md
- The agent will check EVERY FR-*, AC-*, and NFR-* against the codebase

### 2b. Batch QA Dispatch Order

For split BUILD/QA runs, execute batch reviewers before VERIFICATION:

1. SPEC_GUARD (batch requirement-to-task matrix)
2. CODE_REVIEWER (holistic inconsistency scoring)
3. TEST_GUARDIAN (aggregate QA test evidence)
4. INTEGRATOR
5. VISUAL_VALIDATOR (if applicable)
6. VERIFICATION (final deterministic coverage verdict)

### 3. Review Gap Report

Read the produced `gap-report.md`. Present summary:

- Coverage score (target: 100%)
- Number of gaps by category (NOT_IMPLEMENTED, PARTIAL, INCORRECT, UNTESTED)
- Constitution violations (aggregate count)

### 4. If Gaps Found — Trigger Rework Loop

Dispatch ENGINEERING MANAGER to:

1. Create rework tasks (RW-*) for each gap
2. Route rework through: IMPLEMENTER → SPEC GUARD → CODE REVIEWER
3. Re-run VERIFICATION after fixes
4. Loop until 100% or max 3 passes

Rework cap rule:

1. Increment `rework_iteration_count` on each failed QA pass.
2. If `rework_iteration_count > 3`, set workflow to `ESCALATED`, emit reason `QA_REWORK_CAP_EXCEEDED`, and require human checkpoint.

### 5. If 100% — Declare Build Complete

- Run INTEGRATOR one final time
- Run TEST GUARDIAN aggregate check
- Produce final build sign-off

### 6. QA Completion Gate

Set `QA_COMPLETE` only when all conditions are true:

1. `spec_guard_verdict = PASS`
2. `code_reviewer_verdict = PASS`
3. `test_guardian_verdict = PASS`
4. `integration_verdict = PASS`
5. `visual_verdict = PASS` (or explicitly N/A)
6. `rounded_qa_coverage == 1.00`
7. No requirement in `PARTIAL` or `MISSING` state

## Output

- `gap-report.md` — per-requirement verification results
- Updated `traceability-matrix.md` — comprehensive, verified version
- Rework tasks in `tasks.md` (if gaps found)
- `build-status.md` — updated with verification results
