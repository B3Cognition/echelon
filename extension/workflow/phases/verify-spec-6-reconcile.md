# Phase: verify-spec-6-reconcile
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

When `state.json.reconcile == true`, reconcile deterministic task-progress
bookkeeping from the fresh verify-spec evidence.

This phase is skipped when `reconcile` is false.

Reconciliation is two-stage:
1. Fill missing task requirement metadata from interpreted evidence.
2. Mark only deterministic safe task-progress updates.

## Inputs

- `{verify_run_dir}/state.json`
- `{verify_run_dir}/implementation-map.md`
- `{verify_run_dir}/progress-integrity.json`
- `{verify_run_dir}/progress-integrity.md`
- `{spec_dir}/fulfillment-report.md`
- `{spec_dir}/fulfillment-gaps.md`
- `{spec_dir}/tasks.md`
- existing `{spec_dir}/reopen-*.md` summaries, when present

## Safety Rules

ALWAYS use the deterministic harness commands `python -m harness write-task-requirement-mapping-candidates`, `python -m harness apply-task-requirement-mapping`, and `python -m harness mark-task-progress` for metadata or progress changes.
NEVER edit task checkboxes or `**Status:**` lines directly.
NEVER edit task `req=` metadata directly.
NEVER modify application source code, `spec.md`, or `plan.md`.

The metadata harness command applies only task-row `req=` changes:

```bash
python -m harness apply-task-requirement-mapping \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/task-requirement-map.candidates.json" \
  "{verify_run_dir}"
```

The progress harness command applies updates through the same task-progress
helper used during implementation:

```bash
python -m harness mark-task-progress "{spec_dir}/tasks.md" "{task_id}" DONE
```

## Task Requirement Mapping Plan

When canonical tasks carry `req=UNMAPPED`, generate
`{verify_run_dir}/task-requirement-map.candidates.json` with the deterministic
harness command:

```bash
python -m harness write-task-requirement-mapping-candidates \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/task-requirement-map.candidates.json" \
  "{verify_run_dir}/state.json"
```

The command only includes mappings in `task_requirement_mappings` when an
unmapped task's own text explicitly names canonical requirement IDs such as
`FR-001`, `NFR-004`, or `EDGE-009`. Tasks without explicit requirement IDs
remain in `ambiguous_task_requirement_mappings`. Do not hand-write
`task-requirement-map.candidates.json`. The command stamps
`task_requirement_mapping_candidates: ready` and safe/ambiguous mapping counts
in `{verify_run_dir}/state.json`.

Run task requirement mapping before progress reconciliation:

```bash
python -m harness apply-task-requirement-mapping \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/task-requirement-map.candidates.json" \
  "{verify_run_dir}"
```

When `state.json.dry_run == true`, append `--dry-run`.

The harness writes:

- `{verify_run_dir}/task-requirement-map-plan.json`
- `{verify_run_dir}/task-requirement-map-plan.md`
- `{verify_run_dir}/task-requirement-map-applied.json` in apply mode
- `{verify_run_dir}/task-requirement-map-applied.md` in apply mode

## Candidate Plan

Generate `{verify_run_dir}/progress-reconciliation-candidates.json` with the
deterministic harness command:

```bash
python -m harness write-progress-reconciliation-candidates \
  "{spec_dir}/tasks.md" \
  "{spec_dir}/fulfillment-report.md" \
  "{spec_dir}/fulfillment-gaps.md" \
  "{verify_run_dir}/progress-reconciliation-candidates.json" \
  "{verify_run_dir}/state.json"
```

The command includes a task in `safe_task_updates` only when the task is pending,
has mapped requirement metadata, and every mapped requirement is `IMPLEMENTED`
in `fulfillment-report.md`. Tasks with `req=UNMAPPED`, partial/deviated/missing/
unverified/unknown fulfillment status, or insufficient evidence are emitted as
`ambiguous_task_matches`. Do not hand-write
`progress-reconciliation-candidates.json`. The command stamps
`progress_reconciliation_candidates: ready` and safe/ambiguous task counts in
`{verify_run_dir}/state.json`.

## Deterministic Apply

Run:

```bash
python -m harness apply-progress-reconciliation \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/progress-reconciliation-candidates.json" \
  "{verify_run_dir}"
```

When `state.json.dry_run == true`, append `--dry-run`:

```bash
python -m harness apply-progress-reconciliation \
  "{spec_dir}/tasks.md" \
  "{verify_run_dir}/progress-reconciliation-candidates.json" \
  "{verify_run_dir}" \
  --dry-run
```

The harness writes:

- `{verify_run_dir}/progress-reconciliation-plan.json`
- `{verify_run_dir}/progress-reconciliation-plan.md`
- `{verify_run_dir}/progress-reconciliation-applied.json` in apply mode
- `{verify_run_dir}/progress-reconciliation-applied.md` in apply mode

## Output Summary

Print:

```text
Progress reconciliation:
- {n} tasks can be safely marked DONE
  Details: {verify_run_dir}/progress-reconciliation-plan.md#safe-task-updates
- {n} tasks ambiguous, left unchanged
  Details: {verify_run_dir}/progress-reconciliation-plan.md#ambiguous-task-matches
- {n} fulfillment-gap tasks already present from {reopen-file}
  Details: {spec_dir}/{reopen-file}
- spec/plan divergences require manual or reopen task handling
  Details: {spec_dir}/fulfillment-report.md#plan-spec-divergences
```

If no reopen summaries exist but fulfillment gaps exist, recommend:

```bash
echelon spec reopen {spec_id}
```

## Output

Proceed to `DONE`.
