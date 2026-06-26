# Phase: re-extract-1-analyze
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-ANALYZER
# Agent: speckit-echelon-re-analyzer

## Context Pack

Provide RE-ANALYZER with:
- `{state.output_dir}/state.json` — current run state (output_dir, mode)
- `echelon-config.yml` `re:` section — analysis scope, extensions, depth settings

## Dispatch Prompt

Instruct RE-ANALYZER to:
1. Run `discover-repos.sh` to detect single vs. polyrepo workspace
2. Resolve echelon `re:` config and export `ECHELON_CFG_RE_*` env vars
3. Run `run-analysis.sh` to produce `analysis.json` (and per-repo files if polyrepo)
4. Summarize outputs and return `echelon_result:`

## Expected Outputs

| File | Required |
|---|---|
| `{state.output_dir}/analysis.json` | Yes |
| `{state.output_dir}/repos-manifest.json` | Yes |
| `{state.output_dir}/cross-repo.json` | Polyrepo only |
| `{state.output_dir}/codegraph-analysis.json` | Optional (Node.js) |
| `{state.output_dir}/codegraph-summary.json` | Optional (Node.js) |

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-1-analyze
  state_updates:
    mode: single | polyrepo
    domains: []
    artifacts:
      analysis_json: "{state.output_dir}/analysis.json"
      repos_manifest: "{state.output_dir}/repos-manifest.json"
      cross_repo: null
      codegraph_analysis: "{state.output_dir}/codegraph-analysis.json" | null
      codegraph_summary: "{state.output_dir}/codegraph-summary.json" | null
  output_files:
    - "{state.output_dir}/analysis.json"
    # Include only when produced:
    - "{state.output_dir}/codegraph-analysis.json"
    - "{state.output_dir}/codegraph-summary.json"
  journal_entries:
    - type: phase_complete
      phase: re-extract-1-analyze
      data:
        summary: "Analyzed {N} files across {M} repo(s)"
  blocked_reason: null
```
