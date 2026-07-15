# Echelon PerlGraph Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate pinned PerlGraph runtime to Echelon for Perl reverse engineering, delivery worktrees, and verify-spec fulfillment evidence.

**Architecture:** PerlGraph lives beside CodeGraph under `extension/scripts/node/perlgraph`. Install and delivery preparation run locked npm install plus TypeScript build. RE and verify-spec produce PerlGraph artifacts as additive structural evidence while preserving CodeGraph's existing path.

**Tech Stack:** Python 3.11+, Bash, Node.js >=20, npm lockfiles, TypeScript-built PerlGraph CLI, pytest.

## Global Constraints

- Runtime source path: `extension/scripts/node/perlgraph`.
- Provenance source: `git@github.com:B3Cognition/perlgraph.git`, package version `0.1.0`, pinned by commit metadata and `package-lock.json`.
- PerlGraph preparation uses `npm ci --no-audit --no-fund --prefer-offline` followed by `npm run build`.
- Do not use `--ignore-scripts` for PerlGraph because Tree-sitter native dependencies need install/build scripts.
- Never copy `node_modules` or generated `dist` through runtime extension synchronization.
- Low-confidence and dynamic PerlGraph edges are fallback evidence, not proof of fulfillment.

---

### Task 1: Add The Pinned PerlGraph Runtime

**Files:**
- Create: `extension/scripts/node/perlgraph/**`
- Create: `extension/scripts/node/perlgraph/ECHELON-PROVENANCE.md`
- Modify: `scripts/install.sh`
- Test: `tests/kernel/test_perlgraph_integration_contract.py`

**Interfaces:**
- Produces runtime CLI: `extension/scripts/node/perlgraph/dist/cli/perlgraph.js` after preparation.

- [ ] Write failing contract tests that assert the runtime path, package version `0.1.0`, lockfile presence, provenance doc, and installer preparation commands.
- [ ] Copy PerlGraph source from the pinned upstream checkout into `extension/scripts/node/perlgraph`, excluding `.git`, `node_modules`, and `dist`.
- [ ] Add install script preparation for `PERLGRAPH_NODE_DIR`.
- [ ] Run `pytest -q tests/kernel/test_perlgraph_integration_contract.py`.

### Task 2: Provision PerlGraph In Delivery Worktrees

**Files:**
- Modify: `src/harness/gitops.py`
- Test: `tests/unit/test_gitops_worktree.py`

**Interfaces:**
- Produce `prepare_perlgraph_runtime(extension_root: Path) -> None`.
- Extend delivery sync to copy `scripts/node/perlgraph` source while excluding `node_modules` and `dist`.

- [ ] Write failing tests for `prepare_perlgraph_runtime`, source-copy boundaries, and absence of copied build artifacts.
- [ ] Implement preparation with `npm ci` and `npm run build`.
- [ ] Call preparation during normal delivery runtime sync when requested.
- [ ] Run focused gitops worktree tests.

### Task 3: Add RE PerlGraph Artifacts

**Files:**
- Modify: `src/kernel/re_state.py`
- Modify: `extension/workflow/phases/re-extract-0-preflight.md`
- Modify: `extension/workflow/phases/re-extract-1-analyze.md`
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `extension/agents/re/specifier.md`
- Modify: `extension/agents/exploration/scout.md`
- Test: `tests/kernel/test_perlgraph_integration_contract.py`

**Interfaces:**
- Produce `perlgraph-analysis.json` and `perlgraph-summary.json` beside CodeGraph artifacts.

- [ ] Write failing tests for default RE state artifacts, preflight state paths, RE script artifact names, and prompts that describe per-source PerlGraph artifacts.
- [ ] Extend RE state and prompt contracts.
- [ ] Run PerlGraph from `run-analysis.sh` in single-repo and manifest-driven modes when the runtime is prepared.
- [ ] Run focused RE contract tests.

### Task 4: Add Verify-Spec PerlGraph Evidence

**Files:**
- Create: `src/harness/perlgraph_evidence.py`
- Modify: `src/harness/__main__.py`
- Modify: `extension/workflow/phases/verify-spec-2-codegraph.md`
- Modify: `extension/workflow/phases/verify-spec-4-map.md`
- Test: `tests/unit/test_harness_main_perlgraph_evidence.py`
- Test: `tests/unit/test_verify_spec_codegraph_prompt.py`

**Interfaces:**
- Produce CLI command: `python -m harness write-perlgraph-evidence <project-root> <verify-run-dir> <spec-dir>`.
- Produce artifacts: `{verify_run_dir}/perlgraph-analysis.json`, `{verify_run_dir}/perlgraph-summary.json`, `{verify_run_dir}/perlgraph-error.txt`.

- [ ] Write failing CLI tests for ready evidence, stale repo rejection, missing runtime degradation, and state stamping.
- [ ] Implement deterministic evidence writer using the fixed installed extension path.
- [ ] Update verify-spec phase contracts to run PerlGraph after CodeGraph and include artifacts in mapping context.
- [ ] Run focused verify-spec tests.

### Task 5: Verify And Document

**Files:**
- Modify: `docs/re-overview.md`
- Modify: `README.md` or `INSTALLATION.md` only where existing CodeGraph install/runtime docs need PerlGraph parity.

- [ ] Search for live CodeGraph-only structural evidence wording that should mention PerlGraph.
- [ ] Run focused pytest suites for PerlGraph, CodeGraph evidence, RE contracts, and delivery runtime sync.
- [ ] Run `git diff --check`.
