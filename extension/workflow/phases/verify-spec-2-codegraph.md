# Phase: verify-spec-2-codegraph
# Read by: speckit-echelon-commander (COMMANDER)
# Type: commander_internal

## Objective

Refresh structural evidence for the current source tree. Do not reuse stale
brownfield RE artifacts.

## Instructions

Run exactly:

```bash
python -m harness write-codegraph-evidence "{project_root}" "{verify_run_dir}" "{spec_dir}"
```

ALWAYS use this deterministic harness command for verify-spec CodeGraph evidence.
NEVER locate, inspect, or infer CodeGraph bridge invocation from the prompt.
The harness command owns the installed extension path and writes the normalized
artifacts. It also updates `{verify_run_dir}/state.json` with
`structural_evidence: ready` on success or `structural_evidence: degraded` on
degradation. The bridge path is fixed relative to `project_root`:
`.specify/extensions/echelon/scripts/node/re/codegraph-bridge.js`.

Write:
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/codegraph-summary.json`

If the command exits non-zero, do not attempt fallback discovery. Treat
`{verify_run_dir}/codegraph-error.txt` as the diagnostic artifact and continue.
Do not hand-edit `state.json`; the command already recorded degradation.

## Output

Proceed to `verify-spec-3-audit`.
