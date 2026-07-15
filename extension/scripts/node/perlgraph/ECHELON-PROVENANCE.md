# PerlGraph Runtime Provenance

This directory contains the PerlGraph runtime used by Echelon reverse
engineering and verify-spec structural evidence.

- Source repository: `git@github.com:B3Cognition/perlgraph.git`
- Source commit: `364d1a8 chore: release 0.0.1`
- Package name: `perlgraph`
- Authority: source commit `364d1a8` with package version `0.0.1`
- Lockfile: `package-lock.json`
- License evidence: the repository includes `LICENSE`.

PerlGraph is not currently a published npm package, so the source commit and
lockfile are the provenance boundary. Do not update this runtime without
updating this file and the PerlGraph integration contract tests.

Unlike CodeGraph, PerlGraph uses native Tree-sitter dependencies. Its runtime
preparation intentionally runs npm install scripts and then builds the
TypeScript CLI:

```bash
CXXFLAGS="${CXXFLAGS:--std=c++20}" npm ci --prefix "$PERLGRAPH_NODE_DIR" --no-audit --no-fund --prefer-offline
npm run build --prefix "$PERLGRAPH_NODE_DIR"
```

Do not copy `node_modules` or generated `dist` directories through delivery
runtime synchronization; they are host-local build artifacts.
