# Echelon PerlGraph Runtime Design

## Goal

Add PerlGraph to Echelon as a separate, pinned structural-analysis runtime for Perl projects. PerlGraph follows the current CodeGraph integration shape, but remains its own runtime package, evidence source, installation target, and delivery worktree dependency.

## Scope

PerlGraph is sourced from `git@github.com:B3Cognition/perlgraph.git` at the `0.1.0` package release. Because PerlGraph is not currently a published npm package, the Git commit and package lockfile are the provenance authority. If PerlGraph is later published to npm, Echelon can switch to npm tarball integrity the way CodeGraph does.

The integration includes:

- installation with Echelon
- reverse-engineering artifacts for Perl projects and files
- runtime provisioning in delivery worktrees
- verify-spec structural evidence for fulfillment reports

## Architecture

Create `extension/scripts/node/perlgraph` as a separate Node runtime beside `extension/scripts/node/codegraph`. It contains PerlGraph source, `package.json`, and `package-lock.json`; `node_modules` and generated build output are local runtime artifacts and are never copied through extension synchronization.

Installer and delivery preparation run:

```bash
npm ci --prefix "$PERLGRAPH_NODE_DIR" --no-audit --no-fund --prefer-offline
npm run build --prefix "$PERLGRAPH_NODE_DIR"
```

Unlike CodeGraph delivery preparation, PerlGraph must not use `--ignore-scripts` because its parser stack uses native Tree-sitter packages.

Reverse engineering writes `perlgraph-analysis.json` and `perlgraph-summary.json` in the same places CodeGraph writes its artifacts: root RE output for single-repo analysis and `sources/{source-id}/` for workspace/polyrepo analysis. The aggregate root summary records per-source PerlGraph summaries when present.

Verify-spec gets a deterministic Python-owned PerlGraph evidence writer. It runs only from the fixed installed-extension path `.specify/extensions/echelon/scripts/node/perlgraph/dist/cli/perlgraph.js`, validates that any emitted `repo_path` matches the current project root, writes degraded summaries on failure, and stamps verify-spec state. Requirement evidence mapping consumes PerlGraph as an additive source for Perl call/module relationships without treating `low` or `dynamic` confidence as proof. PerlGraph `unsupported_patterns` are preserved as source-backed uncertainty notes and candidate future PerlGraph improvements, not fulfillment proof.

## Error Handling

PerlGraph is fail-open for RE and verify-spec:

- missing Node/npm, missing runtime, build failure, parser failure, or unsupported/no Perl files writes diagnostics instead of blocking unrelated projects
- verify-spec records `perlgraph_evidence: degraded` when PerlGraph cannot produce usable evidence
- dynamic or low-confidence PerlGraph edges remain bounded fallback evidence

Delivery runtime preparation fails closed before LLM dispatch if a copied PerlGraph runtime exists but cannot be installed or built. That mirrors the CodeGraph delivery rule: target-visible runtime support must be ready before agents rely on it.

## Testing

Coverage should include:

- install script has a PerlGraph runtime path and preparation commands
- runtime package is pinned to `0.1.0` with a lockfile and provenance metadata
- RE analysis writes PerlGraph artifacts in single-repo and per-source modes
- delivery sync copies PerlGraph runtime source without `node_modules` or generated build output
- delivery preparation runs `npm ci` and `npm run build`
- verify-spec writes ready and degraded PerlGraph evidence artifacts and state
- evidence mapping preserves confidence boundaries for PerlGraph dynamic/low edges
