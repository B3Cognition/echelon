# Phase: verify-spec-6-reconcile
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

When `state.json.reconcile == true`, reconcile deterministic task-progress
bookkeeping from the fresh verify-spec evidence.

This phase is skipped when `reconcile` is false.

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

ALWAYS use the deterministic harness command to apply progress changes.
NEVER edit task checkboxes or `**Status:**` lines directly.
NEVER modify application source code, `spec.md`, or `plan.md`.

The harness command applies updates through the same task-progress helper used
during implementation:

```bash
python -m harness mark-task-progress "{spec_dir}/tasks.md" "{task_id}" DONE
```

## Candidate Plan

Write `{verify_run_dir}/progress-reconciliation-candidates.json`.

Candidate schema:

```json
{
  "safe_task_updates": [
    {
      "task_id": "T-014",
      "status": "DONE",
      "evidence": "fulfillment-report.md#FR-003",
      "reason": "FR-003 is IMPLEMENTED and maps to task T-014"
    }
  ],
  "ambiguous_task_matches": [
    {
      "task_id": "T-021",
      "evidence": "implementation-map.md#FR-004",
      "reason": "Evidence is PARTIAL or dependency is open"
    }
  ],
  "fulfillment_gap_tasks": {
    "count": 55,
    "details": "specs/001-demo/reopen-1.md"
  },
  "manual_followups": [
    {
      "kind": "spec_plan_divergence",
      "details": "specs/001-demo/fulfillment-report.md#plan-spec-divergences"
    }
  ]
}
```

Only include a task in `safe_task_updates` when the fulfillment evidence is
`IMPLEMENTED`, the task ID exists in canonical `tasks.md`, and no fulfillment
gap contradicts completion.

If evidence is partial, deviated, missing, unverified, or ambiguous, put it in
`ambiguous_task_matches` or `manual_followups`.

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
echelon reopen {spec_id}
```

## Output

Proceed to `DONE`.
