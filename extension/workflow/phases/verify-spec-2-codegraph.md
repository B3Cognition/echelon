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
The harness command owns deterministic runtime resolution and writes the
normalized artifacts. It prefers a complete deployed runtime and otherwise uses
the installer-managed shared runtime. It also updates `{verify_run_dir}/state.json` with
`structural_evidence: ready` on success or `structural_evidence: degraded` on
degradation. Do not derive or call a physical bridge path from this phase.

Write:
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/codegraph-summary.json`

If the command exits non-zero, do not attempt fallback discovery. Treat
`{verify_run_dir}/codegraph-error.txt` as the diagnostic artifact and continue.
Do not hand-edit `state.json`; the command already recorded degradation.

Then run exactly:

```bash
python -m harness write-perlgraph-evidence "{project_root}" "{verify_run_dir}" "{spec_dir}"
```

ALWAYS use this deterministic harness command for verify-spec PerlGraph evidence.
NEVER locate, inspect, or infer PerlGraph CLI invocation from the prompt.
The harness command owns deterministic runtime resolution and writes normalized
artifacts. It prefers a complete deployed runtime and otherwise uses the
installer-managed shared runtime. It also updates `{verify_run_dir}/state.json` with
`perlgraph_evidence: ready` on success or `perlgraph_evidence: degraded` on
degradation. Do not derive or call a physical CLI path from this phase.

Write:
- `{verify_run_dir}/perlgraph-analysis.json`
- `{verify_run_dir}/perlgraph-summary.json`

If the command exits non-zero, do not attempt fallback discovery. Treat
`{verify_run_dir}/perlgraph-error.txt` as the diagnostic artifact and continue.
PerlGraph evidence degraded means Perl-specific structural evidence is weaker,
not that fulfillment failed. Do not hand-edit `state.json`; the command already
recorded degradation.

Then run exactly:

```bash
python -m harness write-topology-evidence-receipt "{project_root}" "{verify_run_dir}" "{spec_dir}"
```

This deterministic finalizer runs only after both providers. It always writes
`{verify_run_dir}/topology-receipt.json`, including explicit unavailable or
unsupported provider rows, and records `topology_evidence` as `ready`,
`degraded`, or `unavailable` in `{verify_run_dir}/state.json`.
It does not write `status` or `completed_at`; the final verify-spec lifecycle
phase owns completion.

## Output

Proceed to `verify-spec-3-audit`.
