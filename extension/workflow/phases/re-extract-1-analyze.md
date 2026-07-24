# Phase: re-extract-1-analyze
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-ANALYZER
# Agent: speckit-echelon-re-analyzer

## Context Pack

Provide RE-ANALYZER with:
- `{state.output_dir}/state.json` — current run state (output_dir, mode)
- `{state.output_dir}/re-execution-plan.json` — per-source refresh decisions
- `{state.output_dir}/re-analysis-manifest.json` — refresh-only source selection
- `{state.output_dir}/workspace-manifest.json` — full workspace inventory; preserve unchanged
- `{state.output_dir}/re-source-index.json` — source decisions and run paths
- `echelon-config.yml` `re:` section — analysis scope, extensions, depth settings

## Dispatch Prompt

Instruct RE-ANALYZER to:
1. Prefer `re-analysis-manifest.json` as the controller-owned selection record
2. Summarize only analysis artifacts already present under `{state.output_dir}`
3. Report the explicit resolved profile, depth, max-lines, and git-history values recorded in `analysis.json`
4. Treat an empty source selection as a successful no-op
5. Summarize exact profile values and outputs, then return `echelon_result:`

## Expected Outputs

| File | Required |
|---|---|
| `{state.output_dir}/analysis.json` | Yes |
| `{state.output_dir}/re-analysis-manifest.json` | Active run |
| `{state.output_dir}/sources/{source-id}/analysis.json` | Each refresh source |
| `{state.output_dir}/repos-manifest.json` | Compatibility |
| `{state.output_dir}/cross-repo.json` | Multiple selected sources only |
| `{state.output_dir}/codegraph-analysis.json` | Optional (Node.js) |
| `{state.output_dir}/codegraph-summary.json` | Optional (Node.js) |
| `{state.output_dir}/perlgraph-analysis.json` | Optional (Node.js, Perl sources) |
| `{state.output_dir}/perlgraph-summary.json` | Optional (Node.js, Perl sources) |

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-1-analyze
  state_updates:
    mode: workspace
    domains: []
    artifacts:
      analysis_json: "{state.output_dir}/analysis.json"
      analysis_manifest: "{state.output_dir}/re-analysis-manifest.json"
      workspace_manifest: "{state.output_dir}/workspace-manifest.json"
      repos_manifest: "{state.output_dir}/repos-manifest.json"
      cross_repo: null
      codegraph_analysis: "{state.output_dir}/codegraph-analysis.json" | null
      codegraph_summary: "{state.output_dir}/codegraph-summary.json" | null
      perlgraph_analysis: "{state.output_dir}/perlgraph-analysis.json" | null
      perlgraph_summary: "{state.output_dir}/perlgraph-summary.json" | null
  output_files:
    - "{state.output_dir}/analysis.json"
    # Include only when produced:
    - "{state.output_dir}/codegraph-analysis.json"
    - "{state.output_dir}/codegraph-summary.json"
    - "{state.output_dir}/perlgraph-analysis.json"
    - "{state.output_dir}/perlgraph-summary.json"
  journal_entries:
    - type: phase_complete
      phase: re-extract-1-analyze
      data:
        summary: "Analyzed {N} files across {M} selected workspace source(s) with explicit profile settings"
  blocked_reason: null
```
