# Phase: re-extract-0-preflight
# Read by: RE controller - brownfield extraction preflight
# Type: controller_internal - no agent dispatch

The RE controller owns preflight. No LLM agent is dispatched for this phase.

## Controller Responsibilities

1. Resolve the active run and RE output directory.
2. Initialize `state.json` when it is absent.
3. Load RE thresholds, repair budgets, source-cycle budgets, and execution profile values from Echelon config.
4. Materialize or reuse the run-local analysis manifest and workspace source inventory.
5. Treat an empty declared workspace as valid and continue without source analysis.
6. Record any hard preflight failure as controller state, not as an agent-authored blocker.

## Agent Contract

Agents must not run preflight commands, install dependencies, initialize state, or mutate run-control files. Downstream agents receive controller-produced state, manifests, and analysis artifacts as read-only context.

Preflight complete. Advance to `re-extract-1-analyze`.
