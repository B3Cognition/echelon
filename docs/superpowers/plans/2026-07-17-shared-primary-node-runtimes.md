# Shared Primary-Workspace Node Runtimes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install CodeGraph, PerlGraph, and Context7 under one shared Echelon Node runtime root for primary-workspace use while retaining worktree-local CodeGraph/PerlGraph delivery execution.

**Architecture:** Tracked extension directories remain runtime source inputs. The host installer refreshes complete shared runtime trees under `${ECHELON_HOME:-$HOME/.echelon}/node`, Bash callers resolve explicit override → complete local runtime → complete shared runtime, and Python verify-spec evidence writers apply the same contract. Delivery preparation remains unchanged and worktree-local.

**Tech Stack:** Bash 3.2-compatible shell, Python 3.11+, Node.js/npm, pytest, existing CodeGraph and PerlGraph locked packages.

## Global Constraints

- Primary shared root is exactly `${ECHELON_HOME:-$HOME/.echelon}/node/<tool>`.
- Tracked source, manifests, lockfiles, and provenance remain under `extension/scripts/node/<tool>`.
- Extension synchronization never copies `node_modules`; PerlGraph `dist` remains generated.
- Delivery CodeGraph and PerlGraph remain worktree-local and fail before LLM dispatch when preparation fails.
- Agents invoke only `run-analysis.sh`, `context7-docs.sh`, or deterministic `python -m harness write-*-evidence` commands.
- Explicit incomplete runtime overrides fail without silently falling through.
- Existing `ECHELON_CONTEXT7_BIN` behavior remains backwards compatible.
- No new third-party dependency is introduced.

---

### Task 1: Shared Installer Layout for All Managed Node Runtimes

**Files:**
- Modify: `scripts/install.sh`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`
- Modify: `tests/kernel/test_perlgraph_integration_contract.py`
- Modify: `tests/unit/test_architect_context7_tool.py`

**Interfaces:**
- Consumes: tracked runtime trees under `$ECHELON_DIR/extension/scripts/node`.
- Produces: `CODEGRAPH_NODE_DIR`, `PERLGRAPH_NODE_DIR`, and `CTX7_NODE_DIR` under `$NODE_RUNTIME_ROOT`; `_refresh_node_runtime(source, destination, excluded_names...)`.

- [ ] **Step 1: Write failing installer contract tests**

Update the three existing installer tests to require:

```python
assert 'NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"' in install_script
assert 'CODEGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/codegraph"' in install_script
assert 'CODEGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/codegraph"' in install_script
assert 'PERLGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/perlgraph"' in install_script
assert 'PERLGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/perlgraph"' in install_script
assert 'CTX7_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/context7"' in install_script
assert 'CTX7_NODE_DIR="$NODE_RUNTIME_ROOT/context7"' in install_script
assert '_refresh_node_runtime "$CODEGRAPH_SOURCE_DIR" "$CODEGRAPH_NODE_DIR" vendor dist' in install_script
assert '_refresh_node_runtime "$PERLGRAPH_SOURCE_DIR" "$PERLGRAPH_NODE_DIR" dist' in install_script
assert '_refresh_node_runtime "$CTX7_SOURCE_DIR" "$CTX7_NODE_DIR" dist' in install_script
```

Also assert installer diagnostics say `rerun this installer` instead of recommending `npm ci` against a deployed extension.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
pytest -q \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py \
  tests/unit/test_architect_context7_tool.py
```

Expected: FAIL because CodeGraph/PerlGraph destinations still point into the checkout and no shared refresh function exists.

- [ ] **Step 3: Implement deterministic runtime refresh and installation**

At the top of `scripts/install.sh`, define:

```bash
NODE_RUNTIME_ROOT="${ECHELON_HOME:-$HOME/.echelon}/node"
CODEGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/codegraph"
PERLGRAPH_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/perlgraph"
CTX7_SOURCE_DIR="$ECHELON_DIR/extension/scripts/node/context7"
CODEGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/codegraph"
PERLGRAPH_NODE_DIR="$NODE_RUNTIME_ROOT/perlgraph"
CTX7_NODE_DIR="$NODE_RUNTIME_ROOT/context7"
```

Add a Bash 3.2-compatible source refresh function before Node installation:

```bash
_refresh_node_runtime() {
  local source_dir="$1"
  local runtime_dir="$2"
  shift 2

  if [ ! -d "$source_dir" ]; then
    echo "  ✗ Node runtime source not found: $source_dir" >&2
    return 1
  fi

  rm -rf "$runtime_dir"
  mkdir -p "$(dirname "$runtime_dir")"
  cp -R "$source_dir" "$runtime_dir"
  rm -rf "$runtime_dir/node_modules"
  while [ "$#" -gt 0 ]; do
    rm -rf "$runtime_dir/$1"
    shift
  done
}
```

Before each locked install, call `_refresh_node_runtime` with the tracked source and exclusions. Validate lockfiles from the source tree before refresh. Keep CodeGraph's locked `npm ci`, PerlGraph's `CXXFLAGS` install and build, and Context7's locked `npm ci`. Update completion output to report shared paths and rerun-installer recovery.

- [ ] **Step 4: Run focused tests and syntax check to verify GREEN**

Run:

```bash
bash -n scripts/install.sh
pytest -q \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py \
  tests/unit/test_architect_context7_tool.py
```

Expected: PASS.

- [ ] **Step 5: Commit the installer unit**

```bash
git add scripts/install.sh \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py \
  tests/unit/test_architect_context7_tool.py
git commit -m "fix: align shared node runtime installs"
```

---

### Task 2: Bash Runtime Resolution for Context7 and Reverse Engineering

**Files:**
- Create: `extension/scripts/bash/node-runtime-resolver.sh`
- Modify: `extension/scripts/bash/context7-docs.sh`
- Modify: `extension/scripts/bash/re/run-analysis.sh`
- Modify: `tests/unit/test_architect_context7_tool.py`
- Modify: `tests/kernel/test_codegraph_integration_contract.py`
- Modify: `tests/kernel/test_perlgraph_integration_contract.py`
- Create: `tests/unit/test_node_runtime_resolver_shell.py`

**Interfaces:**
- Consumes: a local extension Node root and environment overrides.
- Produces: `echelon_resolve_codegraph_runtime(local_root)`, `echelon_resolve_perlgraph_runtime(local_root)`, and `echelon_resolve_context7_runtime(local_root)`, each printing a complete runtime directory or returning nonzero with a diagnostic.

- [ ] **Step 1: Write failing shell resolver behavior tests**

Create Python-driven shell tests that source the resolver and assert:

```python
def resolve(script: Path, function: str, local_root: Path, env: dict[str, str]):
    return subprocess.run(
        ["bash", "-c", f'source "$1"; {function} "$2"', "bash", str(script), str(local_root)],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )

def test_codegraph_uses_shared_runtime_when_local_is_source_only(...):
    # local contains bridge only; shared contains bridge, adapter, and SDK marker
    assert result.returncode == 0
    assert Path(result.stdout.strip()) == shared_runtime

def test_perlgraph_complete_local_runtime_wins(...):
    assert Path(result.stdout.strip()) == local_runtime

def test_explicit_incomplete_override_fails_without_fallback(...):
    assert result.returncode != 0
    assert "ECHELON_CODEGRAPH_RUNTIME_DIR" in result.stderr

def test_echelon_home_relocates_context7_runtime(...):
    assert Path(result.stdout.strip()) == custom_home / "node/context7"
```

Update static tests to require `context7-docs.sh` and `run-analysis.sh` to source `node-runtime-resolver.sh`, and to reject inline primary-workspace `npm ci` instructions.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
pytest -q \
  tests/unit/test_node_runtime_resolver_shell.py \
  tests/unit/test_architect_context7_tool.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py
```

Expected: FAIL because the resolver does not exist and callers still construct deployed-extension paths inline.

- [ ] **Step 3: Implement the shared Bash resolver**

Create `node-runtime-resolver.sh` with readiness predicates and exact override semantics:

```bash
echelon_codegraph_runtime_ready() {
  local runtime_dir="$1"
  [ -f "$runtime_dir/codegraph-bridge.js" ] &&
    [ -f "$runtime_dir/codegraph-adapter.js" ] &&
    [ -f "$runtime_dir/node_modules/@colbymchenry/codegraph/package.json" ]
}

echelon_perlgraph_runtime_ready() {
  local runtime_dir="$1"
  [ -x "$runtime_dir/dist/cli/perlgraph.js" ] &&
    [ -d "$runtime_dir/node_modules" ]
}

echelon_context7_runtime_ready() {
  [ -x "$1/node_modules/.bin/ctx7" ]
}
```

Each resolver must check its tool-specific override exclusively when set, then complete local runtime, then `${ECHELON_HOME:-$HOME/.echelon}/node/<tool>`. Diagnostics list checked directories and say to rerun Echelon's installer.

- [ ] **Step 4: Route Context7 and RE through the resolver**

In `context7-docs.sh`, preserve `ECHELON_CONTEXT7_BIN` precedence. Otherwise call `echelon_resolve_context7_runtime` and append `/node_modules/.bin/ctx7`.

In `run-analysis.sh`, source the resolver once and add one initialization function:

```bash
resolve_structural_runtimes() {
  local local_node_root
  local_node_root="$(dirname "$(dirname "$SCRIPT_DIR")")/node"
  CODEGRAPH_RUNTIME_DIR="$(echelon_resolve_codegraph_runtime "$local_node_root" 2>/dev/null || true)"
  PERLGRAPH_RUNTIME_DIR="$(echelon_resolve_perlgraph_runtime "$local_node_root" 2>/dev/null || true)"
  CODEGRAPH_BRIDGE="${CODEGRAPH_RUNTIME_DIR:+$CODEGRAPH_RUNTIME_DIR/codegraph-bridge.js}"
  PERLGRAPH_CLI="${PERLGRAPH_RUNTIME_DIR:+$PERLGRAPH_RUNTIME_DIR/dist/cli/perlgraph.js}"
}
```

Use those resolved entry points in both manifest/polyrepo and single-repository branches. Emit one installer-oriented skip diagnostic per unavailable tool; remove duplicated inline runtime paths and npm instructions.

- [ ] **Step 5: Run focused tests and shell syntax to verify GREEN**

Run:

```bash
bash -n extension/scripts/bash/node-runtime-resolver.sh \
  extension/scripts/bash/context7-docs.sh \
  extension/scripts/bash/re/run-analysis.sh
pytest -q \
  tests/unit/test_node_runtime_resolver_shell.py \
  tests/unit/test_architect_context7_tool.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py
```

Expected: PASS.

- [ ] **Step 6: Commit the Bash caller unit**

```bash
git add extension/scripts/bash/node-runtime-resolver.sh \
  extension/scripts/bash/context7-docs.sh \
  extension/scripts/bash/re/run-analysis.sh \
  tests/unit/test_node_runtime_resolver_shell.py \
  tests/unit/test_architect_context7_tool.py \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py
git commit -m "fix: resolve shared node runtimes in workspace scripts"
```

---

### Task 3: Python Runtime Resolution for Verify-Spec Evidence

**Files:**
- Create: `src/harness/node_runtime.py`
- Modify: `src/harness/codegraph_evidence.py`
- Modify: `src/harness/perlgraph_evidence.py`
- Create: `tests/unit/test_node_runtime.py`
- Modify: `tests/unit/test_harness_main_codegraph_evidence.py`
- Modify: `tests/unit/test_harness_main_perlgraph_evidence.py`

**Interfaces:**
- Produces: `NodeRuntimeResolutionError`, `resolve_codegraph_bridge(project_root, env=None) -> Path`, and `resolve_perlgraph_cli(project_root, env=None) -> Path`.
- Consumers: `write_codegraph_evidence` and `write_perlgraph_evidence`.

- [ ] **Step 1: Write failing Python resolver tests**

Create readiness fixtures and assert:

```python
def test_codegraph_shared_runtime_follows_echelon_home(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shared = tmp_path / "home/node/codegraph"
    write_complete_codegraph(shared)
    monkeypatch.setenv("ECHELON_HOME", str(tmp_path / "home"))
    assert resolve_codegraph_bridge(project) == shared / "codegraph-bridge.js"

def test_perlgraph_complete_local_runtime_precedes_shared(...):
    assert resolve_perlgraph_cli(project) == local / "dist/cli/perlgraph.js"

def test_incomplete_codegraph_override_is_terminal(...):
    monkeypatch.setenv("ECHELON_CODEGRAPH_RUNTIME_DIR", str(incomplete))
    with pytest.raises(NodeRuntimeResolutionError, match="override"):
        resolve_codegraph_bridge(project)
```

Extend CLI evidence tests so a project with source-only or no local extension succeeds using a fake complete shared runtime under a temporary `ECHELON_HOME`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
pytest -q \
  tests/unit/test_node_runtime.py \
  tests/unit/test_harness_main_codegraph_evidence.py \
  tests/unit/test_harness_main_perlgraph_evidence.py
```

Expected: FAIL because `harness.node_runtime` does not exist and evidence writers still use fixed project-relative paths.

- [ ] **Step 3: Implement the Python resolver**

Create a focused module with complete-runtime predicates and explicit override handling:

```python
class NodeRuntimeResolutionError(RuntimeError):
    pass

def _shared_root(env: Mapping[str, str]) -> Path:
    configured = env.get("ECHELON_HOME", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".echelon"

def resolve_codegraph_bridge(project_root: Path, env: Mapping[str, str] | None = None) -> Path:
    values = os.environ if env is None else env
    local = project_root / ".specify/extensions/echelon/scripts/node/codegraph"
    shared = _shared_root(values) / "node/codegraph"
    runtime = _resolve_runtime(
        tool="CodeGraph",
        override_name="ECHELON_CODEGRAPH_RUNTIME_DIR",
        local=local,
        shared=shared,
        ready=_codegraph_ready,
        env=values,
    )
    return runtime / "codegraph-bridge.js"
```

Implement the equivalent PerlGraph function and diagnostics containing every checked path plus the installer recovery command.

- [ ] **Step 4: Integrate evidence writers**

Replace fixed entry-point construction with resolver calls. On `NodeRuntimeResolutionError`, write the existing degraded error and summary artifacts, preserving state stamping in `harness.__main__`. Do not change worktree preparation in `harness.gitops`.

- [ ] **Step 5: Run focused and delivery regression tests to verify GREEN**

Run:

```bash
pytest -q \
  tests/unit/test_node_runtime.py \
  tests/unit/test_harness_main_codegraph_evidence.py \
  tests/unit/test_harness_main_perlgraph_evidence.py \
  tests/unit/test_gitops_worktree.py \
  tests/integration/test_codegraph_delivery_runtime.py
```

Expected: PASS, including the real worktree-local CodeGraph integration test.

- [ ] **Step 6: Commit the Python harness unit**

```bash
git add src/harness/node_runtime.py \
  src/harness/codegraph_evidence.py \
  src/harness/perlgraph_evidence.py \
  tests/unit/test_node_runtime.py \
  tests/unit/test_harness_main_codegraph_evidence.py \
  tests/unit/test_harness_main_perlgraph_evidence.py
git commit -m "fix: resolve shared node runtimes in verify spec"
```

---

### Task 4: Agent, Workflow, and Operator Contract Alignment

**Files:**
- Modify: `extension/workflow/phases/verify-spec-2-codegraph.md`
- Modify: `extension/agents/re/analyzer.md`
- Modify: `README.md`
- Modify: `INSTALLATION.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/unit/test_verify_spec_codegraph_prompt.py`
- Modify: `tests/unit/test_readme_tool_policy_docs.py`

**Interfaces:**
- Consumes: deterministic Bash and Python runtime resolvers from Tasks 2 and 3.
- Produces: path-independent agent instructions and operator documentation for the shared/worktree split.

- [ ] **Step 1: Write failing prompt and documentation contracts**

Require the verify-spec phase to state:

```python
assert "harness owns deterministic runtime resolution" in text
assert "fixed relative to `project_root`" not in text
assert "~/.echelon/node" not in text
```

Require RE agent guidance to name `run-analysis.sh` as owner without raw executable paths. Require README/INSTALLATION to document the shared primary runtime root and worktree-local delivery exception.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
pytest -q \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/unit/test_readme_tool_policy_docs.py
```

Expected: FAIL because verify-spec still claims fixed project-relative paths and operator docs omit the unified layout.

- [ ] **Step 3: Update live prompts and documentation**

Keep the exact deterministic commands unchanged. Replace physical entry-point claims with harness ownership. Document:

```text
Primary RE/planning/verify-spec: ${ECHELON_HOME:-$HOME/.echelon}/node/<tool>
Delivery CodeGraph/PerlGraph: prepared inside each worktree extension
Recovery: rerun scripts/install.sh, never npm ci inside .specify
```

Add an Unreleased changelog entry describing the root cause, shared locations, resolver behavior, and unchanged delivery isolation.

- [ ] **Step 4: Run contract tests and dry-run validation to verify GREEN**

Run:

```bash
pytest -q \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/unit/test_readme_tool_policy_docs.py \
  tests/unit/test_prompt_tool_contracts.py \
  tests/unit/test_extension_capability_policy.py
bash scripts/bash/dry-run.sh
```

Expected: tests PASS and dry-run reports zero failures.

- [ ] **Step 5: Commit the contract/documentation unit**

```bash
git add extension/workflow/phases/verify-spec-2-codegraph.md \
  extension/agents/re/analyzer.md README.md INSTALLATION.md CHANGELOG.md \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/unit/test_readme_tool_policy_docs.py
git commit -m "docs: define shared node runtime contract"
```

---

### Task 5: End-to-End Verification and Live Migration Check

**Files:**
- Modify only files required by failures attributable to Tasks 1–4.

**Interfaces:**
- Consumes: completed shared installer and caller resolution changes.
- Produces: fresh evidence that primary shared runtimes and delivery-local runtimes both work.

- [ ] **Step 1: Run all focused runtime suites**

```bash
bash -n scripts/install.sh \
  extension/scripts/bash/node-runtime-resolver.sh \
  extension/scripts/bash/context7-docs.sh \
  extension/scripts/bash/re/run-analysis.sh
pytest -q \
  tests/kernel/test_codegraph_integration_contract.py \
  tests/kernel/test_perlgraph_integration_contract.py \
  tests/unit/test_architect_context7_tool.py \
  tests/unit/test_node_runtime_resolver_shell.py \
  tests/unit/test_node_runtime.py \
  tests/unit/test_harness_main_codegraph_evidence.py \
  tests/unit/test_harness_main_perlgraph_evidence.py \
  tests/unit/test_gitops_worktree.py \
  tests/integration/test_codegraph_delivery_runtime.py \
  tests/unit/test_verify_spec_codegraph_prompt.py
```

Expected: PASS.

- [ ] **Step 2: Run the full repository verification gate**

```bash
pytest
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: all selected tests pass, dry-run has zero failures, and diff check is empty.

- [ ] **Step 3: Exercise the real shared-runtime migration**

Run the supported installer and smoke-test each installed entry point:

```bash
bash scripts/install.sh
test -f "${ECHELON_HOME:-$HOME/.echelon}/node/codegraph/node_modules/@colbymchenry/codegraph/package.json"
node "${ECHELON_HOME:-$HOME/.echelon}/node/codegraph/codegraph-bridge.js" --help >/dev/null
test -x "${ECHELON_HOME:-$HOME/.echelon}/node/perlgraph/dist/cli/perlgraph.js"
node "${ECHELON_HOME:-$HOME/.echelon}/node/perlgraph/dist/cli/perlgraph.js" --help >/dev/null
test -x "${ECHELON_HOME:-$HOME/.echelon}/node/context7/node_modules/.bin/ctx7"
"${ECHELON_HOME:-$HOME/.echelon}/node/context7/node_modules/.bin/ctx7" --help >/dev/null
```

Expected: every command exits zero and the installer summary reports all three
shared paths.

- [ ] **Step 4: Review final scope and commit any verification repairs**

```bash
git status --short
git diff --check
```

If verification required an in-scope repair, commit it with an exact message describing that repair. Otherwise leave the four task commits as the implementation history.
