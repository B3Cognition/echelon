# Phase: re-extract-2-specify
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-SPECIFIER
# Agent: speckit-echelon-re-specifier

## Context Pack

Provide RE-SPECIFIER with:
- `{state.output_dir}/analysis.json` — extracted codebase data
- `{state.output_dir}/workspace-manifest.json` — preferred source-root inventory for polyrepo work
- `{state.output_dir}/repos-manifest.json` — polyrepo structure (if exists)
- `{state.output_dir}/re-source-index.json` — source actions and materialized artifact paths
- `{state.output_dir}/cross-repo.json` — cross-source integration index (if exists)
- `{state.output_dir}/{source}/analysis.json` — per-source full extraction data for every source in `workspace-manifest.json`
- `{state.output_dir}/{source}/structure.json` — per-source file inventory
- `{state.output_dir}/{source}/dependencies.json` — per-source dependency data
- `{state.output_dir}/{source}/git-history.json` — per-source git evidence
- `{state.output_dir}/{source}/configs.json` — per-source configuration evidence
- `{state.output_dir}/{source}/codegraph-summary.json` — per-source structural summary when present
- `{state.output_dir}/{source}/codegraph-analysis.json` — per-source structural graph when needed
- `{state.output_dir}/state.json` — run state (output_dir, domains)

In polyrepo runs, root `analysis.json` is only an aggregate index. It is not
sufficient evidence for domain specs. The dispatch must direct RE-SPECIFIER to
read the per-source files above before writing any `specs/NNN-re-{domain}/spec.md`.

## Dispatch Prompt

Instruct RE-SPECIFIER to:
1. Read `workspace-manifest.json` and `re-source-index.json` first; in polyrepo mode, read each per-source `analysis.json` and CodeGraph summary before identifying functional domains
2. Determine starting spec number (highest existing NNN + 1)
3. Generate `specs/000-re-overview/overview.md` — migration summary
4. Generate one `specs/NNN-re-{domain}/spec.md` per domain
5. Write discovered domain list to `echelon_result: state_updates: domains`

## Expected Outputs

| File | Required |
|---|---|
| `specs/000-re-overview/overview.md` | Yes |
| `specs/NNN-re-{domain}/spec.md` | Yes, one per domain |

## echelon_result schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-2-specify
  state_updates:
    domains: [auth, api, data-layer]
  output_files:
    - specs/000-re-overview/overview.md
    - specs/NNN-re-{domain}/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      data:
        summary: "Generated {N} domain specs"
  blocked_reason: null
```
