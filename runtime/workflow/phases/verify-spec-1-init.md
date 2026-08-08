# Phase: verify-spec-1-init
# Read by: echelon.commander (COMMANDER) before verification dispatch
# Type: commander_internal

## Objective

Parse `spec_id`, optional `spec_dir=<absolute-or-repo-relative-path>`,
optional `scope=scoped`, optional `scoped_ids=<comma-separated requirement IDs>`,
optional `base_full_verify_commit=<git-sha>`, optional `strict=true`,
optional `--reconcile`, and optional `--dry-run`.
When `spec_dir=` is present, treat it as authoritative.
Do not locate, glob, list, or search `specs/` from the current project root.
If `spec_dir=` is absent, hard stop with BLOCKED and report that the caller must
pass the authoritative spec directory.

Set `project_root` to the absolute current project root.

This split matters for workspace/source delivery: `project_root` is the
implementation tree used for CodeGraph/source evidence, while
`orchestration_root` owns `specs/` and `runs/`.

If `scope=scoped` is present, set `verify_scope: scoped`; otherwise set
`verify_scope: full`. For scoped runs, parse `scoped_ids` into a
comma-separated list for the deterministic init command. Also pass
`base_full_verify_commit` when supplied. Scoped runs may judge only these
requirement IDs and must preserve unaffected fulfillment rows from the base full
report.

`--dry-run` only has meaning with `--reconcile`; if `--dry-run` is present
without `--reconcile`, set `dry_run: true` but keep `reconcile: false` and do
not mutate any artifacts.
Initialize the verification runtime with the deterministic harness command.
Do not read `runs/.current`, derive `orchestration_root`, create directories,
choose timestamps, or write `state.json` yourself.

```bash
python -m harness init-verify-spec-run "{project_root}" "{spec_id}" "{spec_dir}" \
  --scope "{verify_scope}" \
  --scoped-ids "{comma-separated scoped_ids or empty string}" \
  --base-full-verify-commit "{base_full_verify_commit or empty string}" \
  {--strict when strict=true} \
  {--reconcile when reconcile=true} \
  {--dry-run when dry_run=true}
```

The command prints JSON containing `project_root`, `orchestration_root`,
`spec_dir`, `verify_run_dir`, and `state_path`. Treat those values as
authoritative for all later verify-spec phases. The command owns
`{orchestration_root}/runs/.current` handling: it uses an active run pointer
when present and valid, otherwise it creates a timestamped verify-spec run under
`{orchestration_root}/runs/`. Do not list, sort, or search `runs/` to infer the
latest run.

## State

The harness command writes `state.json` in the verification runtime directory
with:
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
