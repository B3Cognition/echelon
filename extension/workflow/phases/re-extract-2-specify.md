# Phase: re-extract-2-specify
# Read by: speckit-echelon-commander (COMMANDER) before dispatching RE-SPECIFIER
# Agent: speckit-echelon-re-specifier

## Context Pack

Provide RE-SPECIFIER with:
- `.specify/echelon/re/analysis.json` — extracted codebase data
- `.specify/echelon/re/repos-manifest.json` — polyrepo structure (if exists)
- `.specify/echelon/re/state.json` — run state (output_dir, domains)

## Dispatch Prompt

Instruct RE-SPECIFIER to:
1. Read `analysis.json` and identify functional domains
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
    - specs/001-re-auth/spec.md
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      summary: "Generated {N} domain specs"
  blocked_reason: null
```
