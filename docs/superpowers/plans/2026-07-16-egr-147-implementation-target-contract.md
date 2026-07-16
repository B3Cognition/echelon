# EGR-147 Implementation Target Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make implementation targets authoritative from `echelon spec run` through Phase A task generation and target-scoped delivery, while removing implementation targets from reverse-engineering planning.

**Architecture:** `echelon spec run` resolves a repeatable implementation-target list before initializing the squad and persists it in Phase A state. A prompt-level target contract constrains all agents, canonical task rows carry explicit `target=` ownership, and delivery partitions and persists task scope from that metadata. Reverse engineering continues to discover and cache relevant workspace sources independently through `--re-policy`.

**Tech Stack:** Python 3.11+, Typer/Click, dataclasses, YAML, pytest, existing Phase A `SquadController`, task-contract parser, polyrepo orchestrator, and Ralph build harness.

## Global Constraints

- `--target` always means implementation destination.
- A multi-source workspace must not start Phase A without explicit implementation targets.
- A single-source workspace may resolve its sole source deterministically.
- Reverse-engineering planning never receives implementation targets.
- `targets.yml` is written from run intent, never inferred from generated file paths.
- Every newly generated canonical task has exactly one explicit `target=` value.
- Task file paths validate target ownership but cannot establish or replace it.
- Delivery persists target and task scope in state; environment variables are transport only.
- Build prompts name the implementation target, assigned tasks, and forbidden sibling targets.
- Existing canonical rows without `target=` remain parseable for migration and diagnostics.
- Preserve unrelated worktree changes and do not commit without explicit authorization.

---

### Task 1: Extend canonical task rows with explicit target ownership

**Files:**
- Modify: `src/kernel/task_contract.py`
- Modify: `src/harness/task_progress.py`
- Modify: `src/harness/task_targets.py`
- Modify: `extension/templates/tasks-template.md`
- Modify: `extension/templates/task-entry-fragment.md`
- Test: `tests/kernel/test_task_contract.py`
- Test: `tests/unit/test_task_targets.py`
- Test: `tests/unit/test_harness_task_progress.py`

**Interfaces:**
- Produces: `TaskRow.target: str | None`.
- Produces: explicit ownership analysis keyed by normalized target path.
- Preserves: parsing of legacy rows that omit `target=`.

- [x] Write tests proving `target=sources/api` parses, renders, and drives ownership even when `Files:` is absent.
- [x] Write tests proving a mismatched `Files:` source is rejected and legacy rows remain diagnosable as unowned.
- [x] Run focused tests and confirm failures are caused by missing `target=` support.
- [x] Add the optional task-row field, explicit ownership analysis, and template contract.
- [x] Run focused tests to green.

### Task 2: Establish implementation targets before Phase A

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_cli_mode_args.py`
- Test: `tests/unit/test_cli_typer_app.py`
- Test: `tests/unit/test_squad_re_context.py`

**Interfaces:**
- Consumes: repeatable `echelon spec run --target <source-id-or-path>`.
- Produces: `state.implementation_targets: list[str]` before the first dispatch.
- Produces: deterministic sole-source default; multi-source no-target preflight failure.

- [x] Write CLI tests for repeated targets, multi-source missing-target rejection, sole-source default, and multi-target `--init`.
- [x] Write squad tests proving implementation targets are persisted while the RE plan receives no target selector.
- [x] Run focused tests and confirm red state.
- [x] Replace singular `target_source` parsing with normalized repeatable implementation targets.
- [x] Stop passing implementation targets into `build_re_execution_plan()` and keep RE policy independent.
- [x] Run focused tests to green.

### Task 3: Materialize targets and constrain Phase A prompts

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/phases/phase3-how.md`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/agents/solution/orchestrator.md`
- Test: `tests/kernel/test_squad_executors_journal.py`
- Test: `tests/unit/test_squad_re_context.py`
- Test: `tests/unit/test_polyrepo_target_docs.py`

**Interfaces:**
- Produces: `## Implementation Target Contract` in every agent prompt.
- Produces: active and published `targets.yml` derived only from run state.
- Requires: Phase 3 architecture and tasks use only declared implementation targets.

- [x] Write prompt tests asserting target list, writable-boundary rules, and absence of `RE_TARGET_SOURCE`.
- [x] Write publication tests asserting `targets.yml` exists before target-dependent phases and after publication.
- [x] Run focused tests and confirm red state.
- [x] Add deterministic prompt rendering and target metadata synchronization.
- [x] Update HOW/PLAN contracts so new targets block instead of being inferred.
- [x] Run focused tests to green.

### Task 4: Replace target inference with validation and retire post-hoc mutation

**Files:**
- Modify: `src/harness/__main__.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Modify: `README.md`
- Test: `tests/unit/test_cli_spec_target.py`
- Test: `tests/unit/test_cli_spec_targets.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Produces: `python -m harness validate-task-targets <spec-dir>`.
- Changes: `echelon spec target` no longer mutates generated specs.
- Preserves: `echelon spec targets` as the read-only ownership report.

- [x] Write tests proving validation never writes `targets.yml` and rejects missing, undeclared, mismatched, or cross-target ownership.
- [x] Write tests proving the mutating `spec target` surface is removed or returns an invalidation-required error.
- [x] Run focused tests and confirm red state.
- [x] Convert sync behavior to validation and retire the public mutator.
- [x] Run focused tests to green.

### Task 5: Persist and expose target-scoped build context

**Files:**
- Modify: `src/echelon/orchestrator.py`
- Modify: `src/harness/coordinator.py`
- Modify: `src/harness/state.py`
- Modify: `src/harness/ralph.py`
- Modify: `extension/commands/echelon.harness-run.md`
- Test: `tests/unit/test_orchestrator.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_coordinator.py`

**Interfaces:**
- Consumes: explicit `TaskRow.target` ownership.
- Produces: `state.target_task_ids` and `state.implementation_target`.
- Produces: target contract in build and feedback prompts.
- Enforces: completion IDs are a subset of target-owned task IDs.

- [x] Write orchestration tests proving explicit targets partition tasks and target dependencies order delivery.
- [x] Write state/resume tests proving assigned task IDs survive without environment lookup.
- [x] Write prompt tests asserting implementation target, assigned task IDs, and forbidden sibling targets are present.
- [x] Run focused tests and confirm red state.
- [x] Implement explicit partitioning, durable state, bounded prompt context, and completion enforcement.
- [x] Run focused tests to green.

### Task 6: Documentation, migration checks, and full verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/workspace-model.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/specs/2026-07-09-source-scoped-re-cache-design.md`
- Test: relevant documentation and CLI contract tests

**Interfaces:**
- Documents: repeatable spec-run targets and independent RE policy.
- Records: EGR-147 / GitHub issue #162 implementation evidence.

- [x] Update examples and remove advice that uses implementation `--target` for RE selection.
- [x] Run focused target/task/prompt/harness suites.
- [x] Run the full pytest suite and compare failures against the recorded baseline.
- [x] Reinstall the CLI and verify help plus a temporary multi-target spec-run preflight.
- [x] Record exact verification evidence in the EGR register without staging unrelated changes.
