# Shared Primary-Workspace Node Runtimes Design

## Problem

Echelon ships three managed Node runtimes: CodeGraph, PerlGraph, and Context7.
Their tracked source and lockfiles live under `extension/scripts/node`, but the
primary-workspace installation paths are inconsistent.

Context7 is installed under `~/.echelon/node/context7`, so wrappers copied into
a project's `.specify/extensions/echelon` tree can find it. CodeGraph and
PerlGraph are installed inside the Echelon source checkout. A deployed RE or
verify-spec caller resolves those tools relative to the deployed extension,
where extension synchronization intentionally omitted `node_modules` and
PerlGraph's generated `dist`. The caller therefore skips structural analysis or
writes degraded evidence despite a successful Echelon installation.

Delivery has a separate, correct requirement: CodeGraph and PerlGraph must be
prepared inside each delivery worktree so verification does not depend on the
developer's shared installation.

## Selected Approach

Use a hybrid runtime model:

- Primary-workspace tools are installed once under
  `${ECHELON_HOME:-$HOME/.echelon}/node/<tool>`.
- Delivery CodeGraph and PerlGraph are prepared and invoked only from the
  delivery worktree's installed extension.
- Tracked extension directories remain the immutable source of package
  manifests, lockfiles, bridge/build source, and provenance.
- Agents call deterministic Echelon commands or scripts, never physical Node
  executable paths.

This keeps installation systematic without weakening delivery isolation.

### Alternatives Rejected

1. **Install dependencies in every deployed project extension.** This duplicates
   native packages and builds across workspaces, makes `specify extension
   add/update` responsible for mutable runtime state, and repeats the original
   source-versus-deployment coupling.
2. **Use only shared runtimes everywhere.** This is simple, but delivery results
   would depend on host-global state instead of the lockfile prepared inside the
   worktree.
3. **Copy checkout `node_modules` into projects or worktrees.** Installed modules
   may be stale or platform-specific, and copied native dependencies violate the
   existing delivery synchronization contract.

## Filesystem Contract

After `bash scripts/install.sh`, the shared runtime layout is:

```text
${ECHELON_HOME:-$HOME/.echelon}/node/
├── codegraph/
│   ├── codegraph-bridge.js
│   ├── codegraph-adapter.js
│   ├── integration-types.js
│   ├── package.json
│   ├── package-lock.json
│   └── node_modules/
├── perlgraph/
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── scripts/
│   ├── src/
│   ├── node_modules/
│   └── dist/cli/perlgraph.js
└── context7/
    ├── package.json
    ├── package-lock.json
    └── node_modules/.bin/ctx7
```

The installer refreshes each runtime from its tracked source before running its
locked install/build. It must not depend on pre-existing files in the shared
destination. A failed install leaves that tool unavailable and prints a command
to rerun the Echelon installer; callers must not recommend `npm ci` inside a
deployed project extension.

The tracked extension remains free of installed dependencies and generated
PerlGraph output. Delivery continues to materialize this shape:

```text
<worktree>/.specify/extensions/echelon/scripts/node/
├── codegraph/{bridge source,package.json,package-lock.json,node_modules/}
└── perlgraph/{build source,package.json,package-lock.json,node_modules/,dist/}
```

## Runtime Resolution

### Primary Workspace

RE and verify-spec use the same semantic resolution order:

1. A tool-specific runtime-directory override, when present:
   `ECHELON_CODEGRAPH_RUNTIME_DIR`, `ECHELON_PERLGRAPH_RUNTIME_DIR`, or
   `ECHELON_CONTEXT7_RUNTIME_DIR`.
2. A complete local runtime beside the deployed caller. This preserves source
   checkout development and explicitly prepared environments.
3. The shared runtime under `${ECHELON_HOME:-$HOME/.echelon}/node/<tool>`.
4. A clear unavailable/degraded result that identifies the checked paths and
   directs the operator to rerun `scripts/install.sh`.

The existing `ECHELON_CONTEXT7_BIN` override remains supported for backwards
compatibility and takes precedence over Context7 runtime-directory resolution.

A runtime is complete only when its executable/source entry point and required
installed artifacts exist:

- CodeGraph: bridge, adapter, and locked SDK under `node_modules`.
- PerlGraph: executable `dist/cli/perlgraph.js` and `node_modules`.
- Context7: executable `node_modules/.bin/ctx7`.

Presence of a tracked bridge or package manifest alone is not runtime readiness.

### Delivery

Delivery does not use primary-workspace fallback. `GitOpsManager` continues to:

1. Copy tracked CodeGraph and PerlGraph source into the worktree extension.
2. Run locked CodeGraph `npm ci` in that worktree.
3. Run locked PerlGraph `npm ci` and `npm run build` in that worktree.
4. Fail before LLM dispatch if either required preparation fails.

Delivery callers retain fixed worktree-local paths. Context7 remains excluded
from delivery because architecture documentation lookup is a Phase A concern.

## Caller Ownership

### Reverse Engineering

`extension/scripts/bash/re/run-analysis.sh` owns optional RE structural-analysis
invocation. It resolves complete local runtimes first and shared runtimes second,
then passes the resolved CodeGraph bridge or PerlGraph CLI to its existing
analysis functions. Both single-repository and manifest/polyrepo paths use the
same resolver functions; duplicated inline path construction is removed.

The RE-ANALYZER agent continues to call `run-analysis.sh`. Agent instructions
describe capability and artifacts, not `~/.echelon` or `.specify` executable
paths.

### Verify-Spec Harness

The deterministic Python evidence writers own their runtime selection:

```bash
python -m harness write-codegraph-evidence \
  "{project_root}" "{verify_run_dir}" "{spec_dir}"

python -m harness write-perlgraph-evidence \
  "{project_root}" "{verify_run_dir}" "{spec_dir}"
```

`harness.codegraph_evidence` and `harness.perlgraph_evidence` resolve a complete
local runtime or the shared primary-workspace runtime before invoking Node. The
verify-spec phase no longer claims that an entry point is always fixed under the
project extension. It states that the harness owns deterministic resolution.

COMMANDER and other agents never search for runtimes, call raw Node paths, run
`npm ci`, or fall back manually after a deterministic command reports
degradation.

### Delivery Harness

`harness.gitops.prepare_codegraph_runtime` and
`prepare_perlgraph_runtime` remain worktree-local preparation functions. Their
paths and fail-closed behavior do not change. Delivery prompts and verification
code continue to reference the prepared worktree extension, never the shared
runtime.

## Error Handling

- Missing Node/npm during installation reports the affected tools and requests
  an installer rerun after prerequisites are installed.
- A missing or incomplete primary runtime is fail-open for optional RE evidence
  and produces an explicit skip diagnostic.
- Verify-spec writes its existing degraded summary and diagnostic artifact when
  resolution or execution fails.
- Delivery preparation stays fail-closed before model dispatch.
- An explicit override pointing to an incomplete runtime is an error; it does
  not silently fall through to another runtime and conceal configuration drift.
- Diagnostics may include runtime paths but never dump environment contents or
  project secrets.

## Testing

### Installer Contracts

- Assert all three source directories are distinct from all three shared
  destination directories.
- Assert CodeGraph bridge inputs and PerlGraph build inputs are refreshed into
  the shared destinations before locked installation/build.
- Assert completion messages report shared paths.
- Exercise installation in a temporary `HOME` with fake `npm`/`node` commands
  where practical, avoiding writes to the developer's actual Echelon home.

### Resolver Contracts

- A deployed extension without installed modules resolves the shared runtime.
- A complete local runtime wins over the shared runtime.
- Each explicit override wins and fails clearly when incomplete.
- `ECHELON_HOME` relocates all shared runtime defaults consistently.
- CodeGraph and PerlGraph readiness checks reject source-only deployed copies.

### RE Contracts

- Single-repository and manifest/polyrepo analysis use the same resolved paths.
- Fake shared CodeGraph and PerlGraph runtimes produce expected evidence without
  project-local `node_modules` or `dist`.
- Missing shared tools preserve current optional/degraded behavior and recommend
  the installer rather than a project-local npm command.

### Harness and Delivery Contracts

- Verify-spec evidence writers invoke resolved shared runtimes in a primary
  workspace and preserve normalized artifacts/state.
- Existing worktree preparation and real CodeGraph delivery integration tests
  continue to prove local locked execution.
- Existing PerlGraph worktree tests continue to prove local install/build.
- Prompt contract tests ensure agents invoke only deterministic wrapper/harness
  commands and contain no raw shared-runtime paths.

## Compatibility and Migration

Re-running `bash scripts/install.sh` populates the new CodeGraph and PerlGraph
shared locations. Existing checkout-local modules are ignored but not required
for migration. No tracked project configuration changes are needed.

The installer and runtime resolvers continue to honor `ECHELON_HOME`. Existing
Context7 binary overrides remain valid. Existing delivery worktrees are
re-prepared through the current worktree synchronization lifecycle.

Historical design documents and changelog entries retain their recorded paths;
live documentation, tests, prompts, and diagnostics use the new contract.
