# Phase: verify-spec-1-init
# Read by: speckit-echelon-commander (COMMANDER) before verification dispatch
# Type: commander_internal

## Objective

Parse `spec_id`, optional `spec_dir=<absolute-or-repo-relative-path>`,
optional `scope=scoped`, optional `scoped_ids=<comma-separated requirement IDs>`,
optional `base_full_verify_commit=<git-sha>`, optional `strict=true`,
optional `--reconcile`, and optional `--dry-run`.
When `spec_dir=` is present, treat it as authoritative and do not locate or
glob `specs/{spec_id}-*/`. When `spec_dir=` is absent, locate
`specs/{spec_id}-*/` from the current project root.

Set `project_root` to the absolute current project root. Set
`orchestration_root` as follows:
- If `spec_dir=` is present and resolves under a `specs/` directory, derive
  `orchestration_root` from `spec_dir.parent.parent`.
- Otherwise, use `project_root`.

This split matters for workspace/source delivery: `project_root` is the
implementation tree used for CodeGraph/source evidence, while
`orchestration_root` owns `specs/` and `runs/`.

If `scope=scoped` is present, set `verify_scope: scoped`; otherwise set
`verify_scope: full`. For scoped runs, parse `scoped_ids` into a stable,
de-duplicated list and write it as `scoped_ids` in state. Also write
`base_full_verify_commit` when supplied. Scoped runs may judge only these
requirement IDs and must preserve unaffected fulfillment rows from the base full
report.

`--dry-run` only has meaning with `--reconcile`; if `--dry-run` is present
without `--reconcile`, set `dry_run: true` but keep `reconcile: false` and do
not mutate any artifacts.
Create a verification runtime directory:
- active run: read `{orchestration_root}/runs/.current` exactly once and use
  `{orchestration_root}/runs/<run-id>/verify-spec/{spec_id}/`
- no active run: `{orchestration_root}/runs/verify-spec-{spec_id}-{timestamp}/`
When `orchestration_root` differs from `project_root`, do not read
`{project_root}/runs/.current` in this case; that reads the target source repo,
not the workspace run state. Do not list, sort, or search `runs/` to infer the
latest run.
`{orchestration_root}/runs/.current` is the only active-run pointer; if it is
absent or points to a missing directory, create the timestamped no-active-run
directory under `{orchestration_root}/runs/`.

## State

Write `state.json` in the verification runtime directory with:
- `spec_id`
- `project_root` as the absolute current project root
- `orchestration_root`
- `spec_dir`
- `strict`
- `reconcile`
- `dry_run`
- `verify_scope`
- `scoped_ids`
- `base_full_verify_commit`
- `verify_run_dir`
- `status: in_progress`
- `structural_evidence: pending`

## Output

Proceed to `verify-spec-2-codegraph`.
