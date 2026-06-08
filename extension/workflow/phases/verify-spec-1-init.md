# Phase: verify-spec-1-init
# Read by: speckit-echelon-commander (COMMANDER) before verification dispatch
# Type: commander_internal

## Objective

Parse `spec_id`, optional `spec_dir=<absolute-or-repo-relative-path>`,
optional `strict=true`, optional `--reconcile`, and optional `--dry-run`.
When `spec_dir=` is present, treat it as authoritative and do not locate or
glob `specs/{spec_id}-*/`. When `spec_dir=` is absent, locate
`specs/{spec_id}-*/` from the current project root.

`--dry-run` only has meaning with `--reconcile`; if `--dry-run` is present
without `--reconcile`, set `dry_run: true` but keep `reconcile: false` and do
not mutate any artifacts.
Create a verification runtime directory:
- active run: `runs/<run-id>/verify-spec/{spec_id}/`
- no active run: `runs/verify-spec-{spec_id}-{timestamp}/`

## State

Write `state.json` in the verification runtime directory with:
- `spec_id`
- `project_root` as the absolute current project root
- `spec_dir`
- `strict`
- `reconcile`
- `dry_run`
- `verify_run_dir`
- `status: in_progress`
- `structural_evidence: pending`

## Output

Proceed to `verify-spec-2-codegraph`.
