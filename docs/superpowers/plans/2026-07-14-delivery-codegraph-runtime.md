# Delivery CodeGraph Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give delivery worktrees a locked, host-platform CodeGraph runtime before LLM dispatch without copying `node_modules` through extension synchronization.

**Architecture:** CodeGraph becomes a named Node runtime at `scripts/node/codegraph`; reverse-engineering analysis and delivery verification both use that location. Extension synchronization always refreshes source files but never modules. Ralph worktree creation requests deterministic `npm ci` preparation; initialization fingerprint worktrees explicitly opt out.

**Tech Stack:** Python 3.11+, Node/npm, locked npm packages, pytest, Bash.

## Global Constraints

- Runtime source path: `extension/scripts/node/codegraph`.
- CodeGraph version remains locked by `package-lock.json`; preparation uses `npm ci --ignore-scripts --no-audit --no-fund --prefer-offline`.
- Never copy or stage `node_modules` between the workspace, target harness root, and worktree.
- Delivery worktrees prepare CodeGraph before the first LLM dispatch; `echelon delivery init` fingerprint worktrees do not.
- Keep Context7 and reverse-engineering agents outside the delivery runtime surface.
- Retain historical changelog and finding references to the old location.

---

### Task 1: Name and Move the CodeGraph Runtime

**Files:**
- Move: `extension/scripts/node/re/` -> `extension/scripts/node/codegraph/`
- Modify: `src/harness/codegraph_evidence.py:12-14`
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `extension/agents/re/analyzer.md:112-116`
- Modify: `scripts/install.sh:12,134-146,227-230`
- Modify: `scripts/test-codegraph-latest.sh:12-15`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`
- Test: `tests/kernel/test_codegraph_integration_contract.py`

**Interfaces:**
- Consumes: the bridge `codegraph-bridge.js` and adapter from the named runtime.
- Produces: `FIXED_BRIDGE_RELATIVE = Path(".specify/extensions/echelon/scripts/node/codegraph/codegraph-bridge.js")`.

- [ ] **Step 1: Write failing path-contract tests**

```python
def test_codegraph_runtime_uses_named_directory():
    assert CODEGRAPH_RUNTIME_DIR == EXT_ROOT / "extension/scripts/node/codegraph"
    assert "scripts/node/codegraph" in run_analysis
    assert "scripts/node/re" not in run_analysis
```

- [ ] **Step 2: Run the contract test to verify it fails**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/kernel/test_codegraph_integration_contract.py`

Expected: FAIL because the current bridge and RE caller use `scripts/node/re`.

- [ ] **Step 3: Move the runtime and update live callers**

```bash
git mv extension/scripts/node/re extension/scripts/node/codegraph
```

Set `FIXED_BRIDGE_RELATIVE` to the named location. Rename `RE_NODE_DIR` to
`CODEGRAPH_NODE_DIR` in live installer and RE analysis code, preserving
Context7's separate variable. Update the upstream smoke script and current
contract tests. Do not edit historical changelog or findings entries.

- [ ] **Step 4: Run path and bridge smoke tests**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py
bash tests/integration/re/test-codegraph-pinned-runtime.sh
bash scripts/test-codegraph-latest.sh
```

Expected: all tests pass; both smoke tests produce a ready CodeGraph analysis.

- [ ] **Step 5: Commit the path migration**

```bash
git add extension src/harness/codegraph_evidence.py scripts tests/kernel tests/unit/test_harness_main_codegraph_evidence.py
git commit -m "refactor: name CodeGraph runtime"
```

### Task 2: Prepare CodeGraph in Delivery Worktrees

**Files:**
- Modify: `src/harness/gitops.py:55-105,650-710`
- Modify: `src/echelon/cli.py:1469-1493`
- Modify: `src/harness/init.py:462`
- Test: `tests/unit/test_gitops_worktree.py`
- Test: `tests/unit/test_cli_polyrepo_runtime_extension.py`

**Interfaces:**
- Consumes: `prepare_codegraph_runtime(extension_root: Path) -> None`.
- Produces: `GitOpsManager.sync_runtime_extension(worktree_dir: str | Path, *, prepare_codegraph: bool = False) -> None` and `GitOpsManager.create_worktree(spec_id: str, strategy_id: str, outer_iter: int, base_branch: str | None = None, build_id: str = "", prepare_codegraph: bool = True) -> str`.

- [ ] **Step 1: Write failing preparation tests**

```python
def test_prepare_codegraph_runtime_runs_locked_npm_ci(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime" / "scripts" / "node" / "codegraph"
    runtime.mkdir(parents=True)
    (runtime / "package-lock.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("harness.gitops.shutil.which", lambda name: f"/usr/bin/{name}")
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr("harness.gitops.subprocess.run", run)

    prepare_codegraph_runtime(runtime.parent.parent.parent)

    assert run.call_args.args[0] == [
        "/usr/bin/npm", "ci", "--prefix", str(runtime),
        "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline",
    ]
```

Also add tests proving a ready destination receives refreshed bridge source,
target staging has no CodeGraph modules, and
`create_worktree("init", "fingerprint", 0, prepare_codegraph=False)` does
not invoke preparation.

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_gitops_worktree.py tests/unit/test_cli_polyrepo_runtime_extension.py -k "codegraph or runtime_extension"`

Expected: FAIL because modules are copied, ready destinations are not fully
refreshed, and no locked preparation function exists.

- [ ] **Step 3: Implement deterministic preparation**

```python
def prepare_codegraph_runtime(extension_root: Path) -> None:
    runtime_dir = extension_root / "scripts" / "node" / "codegraph"
    if not runtime_dir.exists():
        return
    if not (runtime_dir / "package-lock.json").is_file():
        raise GitOpsError(
            f"CodeGraph package-lock.json is missing at {runtime_dir / 'package-lock.json'}",
            command="prepare_codegraph_runtime",
        )
    node, npm = shutil.which("node"), shutil.which("npm")
    if node is None or npm is None:
        raise GitOpsError(
            "CodeGraph delivery runtime requires Node.js and npm on PATH",
            command="prepare_codegraph_runtime",
        )
    result = subprocess.run(
        [npm, "ci", "--prefix", str(runtime_dir), "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"],
        cwd=runtime_dir,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise GitOpsError(
            f"CodeGraph runtime preparation failed (exit {result.returncode}): {result.stderr.strip()}",
            command="prepare_codegraph_runtime",
        )
```

Remove `sync_codegraph_node_modules`. Make `sync_runtime_extension` validate
and copy source on every invocation, prune the delivery surface, and prepare
only when requested. Ensure the polyrepo staging sync deletes any stale
`scripts/node/codegraph/node_modules` directory and never runs npm. Ralph's
normal `create_worktree` path requests preparation; `harness.init` passes
`prepare_codegraph=False` for its fingerprint worktree.

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_gitops_worktree.py tests/unit/test_cli_polyrepo_runtime_extension.py tests/unit/test_harness_init_summary.py`

Expected: PASS, including no Node/npm requirement during delivery initialization.

- [ ] **Step 5: Commit runtime preparation**

```bash
git add src/harness/gitops.py src/echelon/cli.py src/harness/init.py tests/unit/test_gitops_worktree.py tests/unit/test_cli_polyrepo_runtime_extension.py
git commit -m "fix: prepare CodeGraph runtime in delivery worktrees"
```

### Task 3: Exercise the Real Staged Worktree Boundary

**Files:**
- Create: `tests/integration/test_codegraph_delivery_runtime.py`
- Modify: `tests/integration/re/test-codegraph-pinned-runtime.sh`

**Interfaces:**
- Consumes: `GitOpsManager.sync_runtime_extension(worktree_dir, prepare_codegraph=True)`.
- Produces: a worktree-local CodeGraph analysis JSON with `index_state == "ready"`.

- [ ] **Step 1: Write the failing integration test**

```python
def test_delivery_worktree_hydrates_codegraph_without_staged_modules(tmp_path):
    workspace = copy_extension_without_node_modules(tmp_path / "workspace")
    stage = workspace / "runs" / "targets" / "target"
    _sync_polyrepo_runtime_extension(workspace, stage)
    worktree = stage / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)
    gitops = make_gitops(stage)

    gitops.sync_runtime_extension(worktree, prepare_codegraph=True)

    assert not (stage / "scripts/node/codegraph/node_modules").exists()
    analysis = run_bridge_against_typescript_fixture(worktree)
    assert analysis["index_stats"]["index_state"] == "ready"
```

- [ ] **Step 2: Run it to verify it fails before preparation is implemented**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/integration/test_codegraph_delivery_runtime.py`

Expected before Task 2: FAIL with `Cannot find module '@colbymchenry/codegraph'`.

- [ ] **Step 3: Complete integration helpers using real subprocesses**

Use `copytree(source, destination, ignore=shutil.ignore_patterns("node_modules"))`, a temporary
TypeScript function fixture, the real `npm ci`, and the bridge under the staged
worktree. Skip only when Node or npm is absent; never invoke an LLM.

- [ ] **Step 4: Run full focused verification**

Run:

```bash
/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q \
  tests/unit/test_gitops_worktree.py \
  tests/unit/test_cli_polyrepo_runtime_extension.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/unit/test_harness_main_codegraph_evidence.py \
  tests/integration/test_codegraph_delivery_runtime.py
bash tests/integration/re/test-codegraph-pinned-runtime.sh
bash scripts/test-codegraph-latest.sh
```

Expected: all pass; latest CodeGraph analysis prints its resolved package
version and finds the fixture symbol.

- [ ] **Step 5: Commit integration coverage**

```bash
git add tests/integration/test_codegraph_delivery_runtime.py tests/integration/re/test-codegraph-pinned-runtime.sh
git commit -m "test: exercise staged CodeGraph delivery runtime"
```

### Task 4: Final Regression and Publish

**Files:**
- Modify: `CHANGELOG.md` only if the repository's release convention requires an unreleased entry.

- [ ] **Step 1: Search for accidental live old paths**

Run:

```bash
rg -n "scripts/node/re|node/re|RE_NODE_DIR" \
  src extension scripts tests .github \
  --glob '!**/node_modules/**' --glob '!extension/scripts/node/codegraph/vendor/**'
```

Expected: no live CodeGraph caller remains; historical documentation is not in
this search scope.

- [ ] **Step 2: Run the broader relevant test suite**

Run: `/Users/michalbachorik/.echelon/venv/bin/python -m pytest -q tests/unit/test_gitops_worktree.py tests/unit/test_cli_polyrepo_runtime_extension.py tests/kernel/test_codegraph_integration_contract.py tests/unit/test_harness_main_codegraph_evidence.py tests/unit/test_architect_context7_tool.py tests/integration/test_codegraph_delivery_runtime.py`

Expected: PASS.

- [ ] **Step 3: Inspect the final change set**

Run: `git diff --check origin/main...HEAD && git status --short --branch`

Expected: no whitespace errors and only intentional files changed.

- [ ] **Step 4: Rebase and publish**

```bash
git fetch origin
git rebase origin/main
git push origin main
```

Expected: `main` is pushed with the runtime migration and tests.
