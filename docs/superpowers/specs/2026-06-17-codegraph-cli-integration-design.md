# CodeGraph CLI Integration Design

**Date**: 2026-06-17
**Branch**: `feature/codegraph-cli-integration`
**Status**: Draft for implementation

## Goal

Improve Echelon's CodeGraph integration by preferring the upstream `codegraph`
CLI when it is available, while preserving the current vendored bridge as a
deterministic fallback. The integration must not require or configure MCP.

## Non-Goals

- Do not run `codegraph install`.
- Do not mutate agent, MCP, Codex, Claude, Cursor, or other editor configs.
- Do not remove the vendored bridge in this slice.
- Do not add Perl support in this slice.
- Do not redesign verify-spec evidence mapping.

## Current Problems

Echelon currently invokes a vendored Node bridge directly. That keeps the
workflow local and deterministic, but misses newer upstream CodeGraph CLI
capabilities and hides some failure modes behind optional fail-open behavior.
The RE shell runner can currently mask bridge failures, and verify-spec can
only use the fixed installed bridge path.

## Design

### Provider Order

CodeGraph evidence generation uses this provider order:

1. Upstream `codegraph` CLI when present on `PATH` and able to produce usable
   structured evidence.
2. Existing vendored bridge at
   `.specify/extensions/echelon/scripts/node/re/codegraph-bridge.js`.
3. Degraded mode with `codegraph-error.txt` when neither provider succeeds.

The provider order is explicit in code and in error output so users can see
which path ran.

### CLI Behavior

The CLI provider must be local-only and non-MCP. It may invoke upstream
`codegraph` commands such as `status`, `index`, `sync`, or JSON-producing query
commands, but it must not invoke `codegraph install` or `codegraph serve --mcp`.

If the CLI output cannot satisfy Echelon's existing `codegraph-analysis.json`
contract, the provider should fail closed into the vendored bridge rather than
writing partial or misleading analysis. This keeps existing downstream
consumers stable.

### Artifacts

The existing artifact names remain unchanged:

- `codegraph-analysis.json`
- `codegraph-summary.json`
- `codegraph-error.txt`

When CodeGraph degrades, `codegraph-error.txt` records:

- provider attempted
- command executed where applicable
- exit code
- stdout and stderr snippets
- fallback provider result

When CodeGraph succeeds, stale `codegraph-error.txt` from a previous run should
be removed.

### Installer

`scripts/install.sh` should continue installing vendored bridge dependencies
with `npm ci --prefix "$RE_NODE_DIR"`.

Upstream CodeGraph CLI support is optional:

- If `codegraph` is already on `PATH`, print a success line.
- If it is absent, print a short installation hint.
- If `ECHELON_INSTALL_CODEGRAPH_CLI=1` is set, install
  `@colbymchenry/codegraph` through npm.

The installer must not run upstream `codegraph install`, because that command
can configure agent/MCP integrations outside Echelon's control.

## Error Handling

CodeGraph remains fail-open for Echelon workflows that treat it as optional
structural evidence. Fail-open must still be observable: absence of analysis
should be paired with a clear `codegraph-error.txt`.

If the CLI is installed but fails, Echelon should record the CLI failure and try
the vendored bridge. A vendored bridge success after CLI failure is a successful
overall run with diagnostic context preserved only if useful; stale errors must
not make downstream agents think the current evidence is degraded.

## Testing

Tests should cover:

- CLI provider is preferred when `codegraph` exists and returns valid evidence.
- Vendored bridge is used when CLI is missing.
- Vendored bridge is used when CLI fails.
- `codegraph-error.txt` is written when all providers fail.
- Successful runs remove stale error artifacts.
- Installer does not auto-install upstream CLI unless
  `ECHELON_INSTALL_CODEGRAPH_CLI=1` is present.
- Installer never invokes `codegraph install`.

## Rollout

This is safe as a branch-local change because the vendored bridge remains the
fallback and downstream artifacts keep their current names. Users who do not
install upstream CodeGraph should see the same behavior except for clearer
failure diagnostics.
