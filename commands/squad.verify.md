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

### 1. Locate Artifacts

Read `.specify/squad/state.json` to find the active feature.
Load: spec.md, traceability-matrix.md, tasks.md, constitution.md

### 2. Dispatch VERIFICATION Agent

Use the Agent tool to dispatch a subagent:
- Read `agents/build/verification.md` for the full prompt
- Provide: spec.md (full), all source code paths, all test paths, traceability-matrix.md
- The agent will check EVERY FR-*, AC-*, and NFR-* against the codebase

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

### 5. If 100% — Declare Build Complete

- Run INTEGRATOR one final time
- Run TEST GUARDIAN aggregate check
- Produce final build sign-off

## Output

- `gap-report.md` — per-requirement verification results
- Updated `traceability-matrix.md` — comprehensive, verified version
- Rework tasks in `tasks.md` (if gaps found)
- `build-status.md` — updated with verification results
