# Phase: re-extract-2-specify
# Agent: echelon.re-specifier

## Context Pack

- `{state.output_dir}/state.json`
- `{state.output_dir}/re-execution-plan.json`
- `{state.output_dir}/re-source-index.json`
- `{state.output_dir}/re-workspace-inputs.json`
- `{state.output_dir}/workspace/architecture-map.json` and `domain-catalog.md`
  (controller-owned architecture composition and dependency order)
- `{state.output_dir}/analysis.json`
- `{state.output_dir}/cross-repo.json` when produced
- `{state.output_dir}/sources/{source-id}/analysis.json` and related staged extraction artifacts for every refresh source
- canonical source manifests/specs referenced by `re-workspace-inputs.json`

## Dispatch Prompt

The controller dispatches one manifest target at a time. For a `source-domain` target, RE-SPECIFIER writes exactly the requested source-owned `spec.md` and cites only the target's owned root using source-relative `` `path:line` `` evidence; do not create backup, temporary, alternate, or scratch siblings. A source-coverage repair target includes the exact uncovered files owned by that domain; incorporate every one as meaningful, valid evidence rather than appending a path list. A `source-support` target writes only `sources/{source-id}/supporting-artifacts.md` for visible configuration or test-support files outside all product-domain roots, citing every controller-listed file from the source root. The controller provides the exact architecture layer, migration wave, prerequisites, and cycle group from `architecture-map.json`; copy those values into the spec header without changing the map or catalog. After every required domain passes the deterministic gate, the controller dispatches one `workspace-synthesis` target to write source overviews and workspace documents. Cross-source APIs, events, schemas, dependencies, and migration ordering belong only in workspace synthesis. Treat all planner/publication JSON, domain manifests, and architecture artifacts as read-only. Every specification target is file-only and must return `state_updates: {}`; target queues, source inventory, lifecycle routing, and workspace-synthesis completion are controller-owned.

Every source-domain spec includes the shared `Behavior Coverage` table for
public operations, configuration keys, errors and recovery, boundaries,
operator-visible behavior, tests, and evidence scope. Use universal terms only
with `Evidence Scope: exhaustive` and evidence covering the invariant;
otherwise state the bounded observed behavior.

The controller runs the deterministic source-domain quality gate after each source-domain dispatch. If the gate fails, the controller records the target-quality report and routes bounded repair. Return `verdict: BLOCKED` only for a source/artifact blocker that prevents you from inspecting or updating the requested target; leave the canonical `spec.md` in place. Do not replace a deterministic quality concern with a generic dispatch error.

## Expected Outputs

- `{state.output_dir}/sources/{source-id}/domain-manifest.json` is controller-owned and required before dispatch
- `{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md` for the current `source-domain` target
- `{state.output_dir}/sources/{source-id}/supporting-artifacts.md` for a `source-support` target
- `{state.output_dir}/sources/{source-id}/overview.md` only for the `workspace-synthesis` target
- `{state.output_dir}/workspace/overview.md`
- `{state.output_dir}/workspace/relationships.md`
- `{state.output_dir}/workspace/contracts.md`
- `{state.output_dir}/workspace/architecture-map.json` and `domain-catalog.md`
  are controller-owned and must remain unchanged
- `{state.output_dir}/workspace/domains/{domain-id}.md` when workspace domains exist

An all-empty declared workspace requires the three workspace documents and empty decisions, but no source domain spec.

## echelon_result Schema

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  phase_id: re-extract-2-specify
  state_updates: {}
  output_files:
    - "{state.output_dir}/sources/{source-id}/overview.md"
    - "{state.output_dir}/sources/{source-id}/specs/{domain-id}/spec.md"
    - "{state.output_dir}/workspace/overview.md"
    - "{state.output_dir}/workspace/relationships.md"
    - "{state.output_dir}/workspace/contracts.md"
  journal_entries:
    - type: phase_complete
      phase: re-extract-2-specify
      data:
        summary: "Generated source-owned specs and workspace synthesis"
  blocked_reason: null
```
