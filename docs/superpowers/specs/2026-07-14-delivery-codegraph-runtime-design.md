# Delivery CodeGraph Runtime Design

## Problem

Delivery verification invokes the CodeGraph bridge from the host. The bridge
currently lives under `extension/scripts/node/re`, a legacy reverse-engineering
path, and its `node_modules` directory is copied through workspace, target, and
worktree extension syncs. The generic sync intentionally excludes
`node_modules`, so a target staging hop could leave a bridge without its SDK.
The LLM then spent tokens manually compensating for degraded structural
evidence.

## Scope

This change covers the CodeGraph runtime used by delivery verification and
reverse-engineering analysis. It does not move or deploy reverse-engineering
agents, and it does not change the workspace-only Context7 runtime.

## Design

### Named Runtime Location

Move the CodeGraph bridge, adapter, package manifest, lockfile, and retained
CodeGraph vendor metadata from `extension/scripts/node/re` to
`extension/scripts/node/codegraph`. Update every deterministic caller and
contract to use the named CodeGraph location, including the reverse-engineering
`run-analysis.sh` caller. The reverse-engineering `re` directory remains
separate from delivery.

Historical changelog and finding entries retain their recorded paths; live
commands, scripts, tests, and current design documents use the new path.

### Runtime Preparation

Extension sync always refreshes tracked runtime source and package metadata,
including for reused worktrees, and never copies `node_modules`. It also removes
any legacy staged CodeGraph modules. After the delivery worktree extension is
present, the harness prepares the CodeGraph runtime in that worktree with:

```bash
npm ci --prefix <worktree>/.specify/extensions/echelon/scripts/node/codegraph \
  --ignore-scripts --no-audit --no-fund --prefer-offline
```

This uses the lockfile, selects packages for the host platform, and lets npm
reuse its local cache. The prepared modules live inside the worktree, so they
also remain visible when that worktree is bind-mounted into a container.

Preparation runs for both fresh and reused Ralph delivery worktrees. It does
not run for the temporary fingerprint worktree created by `echelon delivery
init`, so initialization remains independent of Node and npm. Target-specific
staging roots contain no installed CodeGraph modules.

### Failure Behavior

CodeGraph is required for delivery verification. If Node, npm, the lockfile, or
the locked install is unavailable, Ralph worktree preparation fails before an
LLM is dispatched. The resulting harness error names the missing prerequisite
and the runtime path. This prevents a costly manual-evidence fallback caused by
a missing local dependency. A successfully prepared runtime can still report
genuine CodeGraph analysis errors as degraded evidence.

### Other Dependencies

Context7 is the only other Echelon-managed Node package. Its wrapper and
runtime are intentionally excluded from delivery and remain installed in the
primary workspace for planning. Python Echelon dependencies remain in the host
virtual environment; target-project dependencies remain owned by the selected
target image. Neither crosses the delivery extension synchronization boundary.

## Tests

- Unit tests assert that target staging never carries `node_modules`, reused
  worktrees receive refreshed bridge source, `delivery init` skips preparation,
  and Ralph delivery worktrees request the locked CodeGraph preparation command.
- An integration test begins with an extension tree without `node_modules`,
  creates a target worktree, prepares the locked runtime, runs the real
  CodeGraph bridge against a TypeScript fixture, and validates the generated
  analysis.
- Reverse-engineering analysis tests prove `run-analysis.sh` uses the named
  CodeGraph runtime after the move.
- The pinned and upstream-latest CodeGraph bridge smoke tests continue to run
  without LLM calls.

## Non-Goals

- Do not install Echelon into target Docker images.
- Do not change Docker provider execution semantics.
- Do not deploy Context7 or reverse-engineering agents into delivery worktrees.
