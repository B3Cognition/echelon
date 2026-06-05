# Verify-Spec Reconcile Design

## Problem

`echelon verify-spec` can prove that real implementation exists while
`tasks.md` still records zero completed tasks. The audit currently writes strong
evidence (`implementation-map.md`, `progress-integrity.md`,
`fulfillment-report.md`, and `fulfillment-gaps.md`), but the user must manually
translate safe evidence back into task progress.

This creates two bad outcomes:

- A spec can look unimplemented even when code exists.
- Reopen/harness work starts from stale task progress and may duplicate work.

## Goals

- Add an explicit reconciliation mode to `verify-spec`.
- Keep normal `verify-spec` read-only.
- Apply only deterministic bookkeeping fixes.
- Use the same harness task-progress helper used during implementation.
- Tell users exactly where to inspect evidence for applied, skipped, and manual
  follow-up items.

## Non-Goals

- Do not modify application source code.
- Do not automatically resolve spec/plan/product divergences.
- Do not mark ambiguous task matches complete.
- Do not replace `echelon reopen`; fulfillment gaps still become follow-up tasks
  through reopen.

## User Experience

Read-only default remains:

```bash
echelon verify-spec 001
```

Dry-run reconciliation:

```bash
echelon verify-spec 001 --reconcile --dry-run
```

Apply reconciliation:

```bash
echelon verify-spec 001 --reconcile
```

Example terminal summary:

```text
Progress reconciliation:
- 14 tasks can be safely marked DONE
  Details: runs/verify-spec-.../progress-reconciliation-plan.md#safe-task-updates
- 3 tasks ambiguous, left unchanged
  Details: runs/verify-spec-.../progress-reconciliation-plan.md#ambiguous-task-matches
- 55 fulfillment-gap tasks already present from reopen-1
  Details: specs/001.../reopen-1.md
- spec/plan divergences require manual or reopen task handling
  Details: specs/001.../fulfillment-report.md#plan-spec-divergences
```

The summary must always include file paths for follow-up evidence, not only
category names.

## Safety Contract

`--reconcile` may decide which tasks are safe to mark, but it must apply each
progress change through the deterministic harness helper:

```bash
python -m harness mark-task-progress "{spec_dir}/tasks.md" "{task_id}" DONE
```

Then it must validate:

```bash
python -m harness validate-task-progress "{spec_dir}/tasks.md"
```

ALWAYS use the harness helper for `tasks.md` progress mutations. NEVER edit task
checkboxes or `**Status:**` lines directly from prompts.

## Reconciliation Inputs

Use the fresh verify-spec run artifacts:

- `implementation-map.md`
- `progress-integrity.json`
- `progress-integrity.md`
- `fulfillment-report.md`
- `fulfillment-gaps.md`
- verification `state.json`
- current `{spec_dir}/tasks.md`

Do not use stale brownfield or previous verify-spec artifacts when a fresh run
exists.

## Reconciliation Outputs

Dry-run writes:

```text
runs/verify-spec-.../progress-reconciliation-plan.json
runs/verify-spec-.../progress-reconciliation-plan.md
```

Apply writes:

```text
runs/verify-spec-.../progress-reconciliation-plan.json
runs/verify-spec-.../progress-reconciliation-plan.md
runs/verify-spec-.../progress-reconciliation-applied.json
runs/verify-spec-.../progress-reconciliation-applied.md
```

Apply mode may also update:

```text
specs/<id>-*/tasks.md
runs/verify-spec-.../progress-integrity.json
runs/verify-spec-.../progress-integrity.md
```

## Safe Match Rules

A task is safe to mark `DONE` only when all are true:

- The task ID exists in canonical `tasks.md`.
- The task requirement or title maps cleanly to an implemented item in
  `implementation-map.md` or `fulfillment-report.md`.
- The implementation evidence is `IMPLEMENTED`, not `PARTIAL`, `MISSING`,
  `DEVIATED`, or `UNVERIFIED`.
- The task has no open dependency in `tasks.md`, unless that dependency is also
  in the same safe update set.
- No existing fulfillment gap contradicts completion of that task.

If any condition is uncertain, leave the task unchanged and list it under
ambiguous task matches.

## Handling Fulfillment Gaps

`verify-spec --reconcile` does not replace `echelon reopen`.

It should detect existing reopen summaries such as `reopen-1.md` and report how
many fulfillment-gap tasks already exist. If gaps exist but no reopen file is
present, the summary should recommend:

```bash
echelon reopen <spec_id>
```

## Handling Spec/Plan Divergences

Spec/plan divergences require manual or reopen-task handling. Reconcile mode
must not rewrite `spec.md`, `plan.md`, or source code.

The terminal summary and reconciliation reports must point to the relevant
section in `fulfillment-report.md` or `fulfillment-gaps.md`.

## Command Semantics

Argument parsing in `verify-spec-1-init` should capture:

- `spec_id`
- `strict`
- `reconcile`
- `dry_run`

The command prompt should change from "always read-only" to:

- read-only by default
- source-code read-only always
- `tasks.md` mutable only when `--reconcile` is present and only through harness
  task-progress helpers

## Testing

Unit and prompt tests should cover:

- README/USAGE documents `--reconcile` and `--reconcile --dry-run`.
- `verify-spec-1-init` parses and records reconcile flags.
- Prompt text forbids direct task-row edits and requires
  `python -m harness mark-task-progress`.
- Dry-run mode writes plan artifacts but does not mutate `tasks.md`.
- Apply mode calls the deterministic helper and then validates progress.
- Ambiguous matches are left unchanged and reported with evidence paths.

## First Implementation Boundary

The first implementation should let the verify-spec prompt generate only a
candidate reconciliation plan. Python applies only candidate task IDs that pass
deterministic validation against canonical `tasks.md`, dependencies, and
allowed statuses. If a candidate cannot be validated deterministically, Python
must leave it unchanged and report it as ambiguous.

A later improvement can move candidate generation into Python if prompt-authored
plans prove too fuzzy in real runs.
