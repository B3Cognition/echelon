# First-Class Reverse-Engineering Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move reverse-engineering execution out of `echelon spec run` into an independently resumable `echelon re run/continue/resume` lifecycle while preserving published RE as optional read-only spec context.

**Architecture:** Add `harness.re_lifecycle` to own RE run selection, planning, controller execution, continuation, structured resume, and automatic complete publication. Add `harness.published_re_context` to create a bounded run-local snapshot from the canonical RE registry. Phase A keeps only the snapshot consumer and removes every GOLDDIGGER execution route.

**Tech Stack:** Python 3.10+, Typer, pytest, YAML workflow contracts, existing Echelon RE planner/controller/publication/state primitives.

## Global Constraints

- RE remains workspace-scoped; `target-only` and `target-changed` remain retired.
- `changed` is the default and a current publication must cause zero provider calls.
- Complete RE output publishes automatically; partial output never auto-publishes.
- RE uses `runs/.current-re`; spec keeps `runs/.current`; delivery markers remain unchanged.
- Spec runs never fingerprint, plan, execute, repair, or publish RE.
- Spec runs snapshot the latest registered publication unless `--ignore-re` is supplied.
- Removed spec RE options fail with migration guidance and are never parsed as description text.
- Preserve user changes already present in the working tree; stage only task-owned files.

---

### Task 1: Published RE context snapshotter

**Files:**
- Create: `src/harness/published_re_context.py`
- Create: `tests/unit/test_published_re_context.py`

**Interfaces:**
- Consumes: `load_published_index(project_root)` and `canonical_re_artifacts(project_root, index)`.
- Produces: `attach_published_re_context(project_root: Path, run_dir: Path, *, ignore: bool) -> dict[str, object]`.

- [ ] **Step 1: Write failing snapshot tests**

Cover `ignored`, `absent`, valid `attached`, unregistered-file exclusion, path containment, and snapshot stability after canonical files change. Assert this shape:

```python
context = attach_published_re_context(root, run_dir, ignore=False)
assert context["status"] == "attached"
assert context["generation"] == 3
assert Path(context["snapshot_root"]).is_relative_to(run_dir)
assert all(Path(path).is_relative_to(run_dir) for path in context["artifacts"]["re_contexts"])
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_published_re_context.py -q`

Expected: collection fails because `harness.published_re_context` does not exist.

- [ ] **Step 3: Implement the bounded snapshotter**

Implement exact statuses and atomic replacement:

```python
def attach_published_re_context(
    project_root: Path,
    run_dir: Path,
    *,
    ignore: bool,
) -> dict[str, object]:
    if ignore:
        return {"status": "ignored", "generation": 0, "artifacts": {}}
    index = load_published_index(project_root)
    if index is None:
        return {"status": "absent", "generation": 0, "artifacts": {}}
    canonical = canonical_re_artifacts(project_root, index)
    snapshot_root = run_dir / "context" / "published-re"
    artifacts = _copy_registered_artifacts(project_root, snapshot_root, canonical)
    return {
        "status": "attached",
        "generation": index.generation,
        "publication_status": index.publication_status,
        "snapshot_root": str(snapshot_root),
        "artifacts": artifacts,
    }
```

Copy only paths returned by the registry map plus registered manifests. Preserve artifact-map keys while rewriting values to snapshot paths. Reject any source path outside `project_root/re` and use a temporary sibling directory plus `Path.replace()` for atomic snapshot creation.

- [ ] **Step 4: Verify snapshot tests pass**

Run: `pytest tests/unit/test_published_re_context.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/published_re_context.py tests/unit/test_published_re_context.py
git commit -m "feat: snapshot published RE context"
```

---

### Task 2: RE lifecycle state, marker, and no-work planning

**Files:**
- Create: `src/harness/re_lifecycle.py`
- Create: `tests/unit/test_re_lifecycle.py`
- Modify: `src/harness/squad.py` to move the fingerprint-profile resolver into the new focused module or a shared RE helper.

**Interfaces:**
- Consumes: workspace discovery, RE fingerprint profile, planner, materializer, `SquadCliProvider`, `ReExtractionController`, and publication APIs.
- Produces: `ReLifecycleController`, `ReLifecycleResult`, `resolve_current_re_run()`, and `parse_re_max_inner()`.

- [ ] **Step 1: Write failing marker and no-work tests**

Test safe marker resolution, rejection of path-like/symlink-escaping IDs, independence from `runs/.current`, completed-run replanning, unfinished-run reuse, reset behavior, invalid policy/budget, and default-current no-op with a provider factory that raises if called.

```python
result = controller.run(policy="changed", re_max_inner=None, reset=False)
assert result.status == "done"
assert result.no_work is True
assert provider_calls == []
assert not (root / "runs" / ".current-re").exists()
```

- [ ] **Step 2: Verify the tests fail**

Run: `pytest tests/unit/test_re_lifecycle.py -q`

Expected: collection fails because `harness.re_lifecycle` does not exist.

- [ ] **Step 3: Implement focused state and planning APIs**

Use a small result type and dependency-injected provider factory:

```python
@dataclass(frozen=True)
class ReLifecycleResult:
    status: Literal["done", "blocked", "failed"]
    run_id: str = ""
    phase: str = ""
    blocked_reason: str = ""
    generation: int = 0
    no_work: bool = False

class ReLifecycleController:
    def __init__(self, *, project_root: Path, extension_root: Path,
                 provider_factory: Callable[[], ReAgentProvider]) -> None:
        self._project_root = project_root.resolve()
        self._extension_root = extension_root.resolve()
        self._provider_factory = provider_factory

    def run(self, *, policy: str = "", re_max_inner: int | None = None,
            reset: bool = False) -> ReLifecycleResult:
        return self._start_or_resume(
            policy=policy,
            re_max_inner=re_max_inner,
            reset=reset,
        )
```

Write run state atomically. Use `runs/.current-re`, safe ID regex
`^[A-Za-z0-9._-]+$`, and `re-YYYYMMDD-HHMMSS-ffffff` IDs. Plan before provider
creation. Treat `cached-only` missing actions as a deterministic block with
named sources. Treat `none` and fully current `changed` plans as no-work success.

- [ ] **Step 4: Verify marker and planning tests pass**

Run: `pytest tests/unit/test_re_lifecycle.py -q`

Expected: marker, reset, and zero-provider no-work tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_lifecycle.py src/harness/squad.py tests/unit/test_re_lifecycle.py
git commit -m "feat: add RE lifecycle planning state"
```

---

### Task 3: RE execution, continuation, resume, and automatic publication

**Files:**
- Modify: `src/harness/re_lifecycle.py`
- Modify: `tests/unit/test_re_lifecycle.py`
- Modify: `tests/integration/test_re_publication_flow.py`

**Interfaces:**
- Consumes: Task 2 `ReLifecycleController` and existing controller/publication results.
- Produces: `continue_run(re_max_inner: int | None = None)` and `resume(answer: str, re_max_inner: int | None = None)`.

- [ ] **Step 1: Write failing lifecycle execution tests**

Test work-bearing execution, automatic publication, partial refusal, extraction-complete publication-only retry, interrupted continuation, budget raise persistence, typed answer capture, answer injection, and rejection of resume without a question.

```python
result = controller.run(policy="refresh-all", re_max_inner=8, reset=False)
assert result.status == "done"
assert load_published_index(root).generation == 2
state = json.loads((root / "runs" / result.run_id / "state.json").read_text())
assert state["extraction_complete"] is True
assert state["publication_complete"] is True
```

- [ ] **Step 2: Verify new tests fail**

Run: `pytest tests/unit/test_re_lifecycle.py tests/integration/test_re_publication_flow.py -q`

Expected: failures show missing execution/continue/resume behavior.

- [ ] **Step 3: Implement controller composition and recovery classification**

After materialization, set `re_max_inner` in `run_dir/re/state.json`, construct the provider lazily, run `ReExtractionController`, then publish only completed output:

```python
outcome = ReExtractionController(
    provider=self._provider_factory(),
    project_root=self._project_root,
    run_dir=run_dir,
    extension_root=self._extension_root,
).run()
if not outcome.completed:
    return self._persist_block(run_dir, outcome)
state["extraction_complete"] = True
self._save_state(run_dir, state)
publication = publish_re_run(
    self._project_root,
    run_dir,
    expected_generation=state["expected_generation"],
)
```

Persist publication failure separately so `continue_run()` retries publication without invoking the extraction controller. For typed escalations, use `ensure_blocked_decision`, `_resolve_escalation_option`-equivalent local logic, and `mark_blocked_decision_resolved`; set `resume_answer` in RE state so the next controller prompt builder can inject it once.

- [ ] **Step 4: Verify focused lifecycle and publication tests pass**

Run: `pytest tests/unit/test_re_lifecycle.py tests/integration/test_re_publication_flow.py -q`

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_lifecycle.py tests/unit/test_re_lifecycle.py tests/integration/test_re_publication_flow.py
git commit -m "feat: execute and resume RE lifecycle"
```

---

### Task 4: Public CLI and removed-option migration

**Files:**
- Modify: `src/echelon/cli_app.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_typer_app.py`
- Modify: `tests/unit/test_cli_mode_args.py`
- Create: `tests/unit/test_cli_re_lifecycle.py`

**Interfaces:**
- Consumes: Task 3 `ReLifecycleController`.
- Produces: public `re run`, `re continue`, `re resume`; spec `--ignore-re`; explicit removed-option errors.

- [ ] **Step 1: Write failing CLI tests**

Assert RE help, argument forwarding, exit codes, root alias parity, spec help removal, `--ignore-re`, and both `--flag value` and `--flag=value` migration errors.

```python
result = runner.invoke(app, ["spec", "run", "feature", "--re-policy", "changed"])
assert result.exit_code != 0
assert "moved to echelon re run" in result.output
```

- [ ] **Step 2: Verify CLI tests fail**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py tests/unit/test_cli_re_lifecycle.py -q`

Expected: RE commands and `--ignore-re` are absent; old options are still accepted.

- [ ] **Step 3: Implement typed commands and legacy dispatch**

Declare:

```python
@re_app.command("run")
def re_run(re_policy: str = typer.Option("changed", "--re-policy"),
           re_max_inner: int | None = typer.Option(None, "--re-max-inner", min=1),
           reset: bool = typer.Option(False, "--reset")) -> None:
    args = ["--re-policy", re_policy]
    if re_max_inner is not None:
        args.extend(["--re-max-inner", str(re_max_inner)])
    if reset:
        args.append("--reset")
    _legacy_cli()._cmd_re_run(args)

@re_app.command("continue")
def re_continue(re_max_inner: int | None = typer.Option(None, "--re-max-inner", min=1)) -> None:
    args = [] if re_max_inner is None else ["--re-max-inner", str(re_max_inner)]
    _legacy_cli()._cmd_re_continue(args)

@re_app.command("resume")
def re_resume(answer: str, re_max_inner: int | None = typer.Option(None, "--re-max-inner", min=1)) -> None:
    args = [answer]
    if re_max_inner is not None:
        args.extend(["--re-max-inner", str(re_max_inner)])
    _legacy_cli()._cmd_re_resume(args)
```

Add `_cmd_re_run`, `_cmd_re_continue`, and `_cmd_re_resume` adapters in
`cli.py`. Parse `--ignore-re` into the spec controller. Remove typed spec RE
options. In the legacy spec parser, detect obsolete RE options before generic
message collection and exit with migration guidance.

- [ ] **Step 4: Verify CLI tests pass**

Run: `pytest tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py tests/unit/test_cli_re_lifecycle.py -q`

Expected: all focused CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli_app.py src/echelon/cli.py tests/unit/test_cli_typer_app.py tests/unit/test_cli_mode_args.py tests/unit/test_cli_re_lifecycle.py
git commit -m "feat: expose RE lifecycle commands"
```

---

### Task 5: Remove RE execution from the spec controller and attach snapshots

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/unit/test_squad_re_context.py`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: Task 1 `attach_published_re_context()` and CLI `ignore_re` boolean.
- Produces: `state.published_re_context` with `attached|absent|ignored`; no spec-owned RE execution.

- [ ] **Step 1: Replace old squad RE tests with failing decoupling tests**

Assert fresh initialization never calls planner/fingerprint/controller/publication, valid publication snapshots before SCOUT, ignore and absent states persist, later publication does not alter the snapshot, and GOLDDIGGER pre-dispatch helpers are unreachable.

```python
state = state_store.load()
assert state["published_re_context"]["status"] == "attached"
assert "re_execution_plan" not in state
assert "golddigger_requests" not in state
```

- [ ] **Step 2: Verify decoupling tests fail**

Run: `pytest tests/unit/test_squad_re_context.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py -q`

Expected: current squad initializes and executes RE/GOLDDIGGER.

- [ ] **Step 3: Implement snapshot-only Phase A state**

Add `ignore_re: bool = False` to `SquadController.__init__`. Replace `_initialize_re_context()` with:

```python
state["published_re_context"] = attach_published_re_context(
    self._project_root,
    self._squad_dir,
    ignore=self._ignore_re,
)
self._state_store.save(state)
```

Remove generation guards tied to mutable canonical paths, RE recovery dispatch-count resets, Mode 1 controller/publication helpers, Mode 2 queue execution, and RE-only state cleanup. Keep unrelated generic pre-dispatch behavior intact.

- [ ] **Step 4: Verify decoupling tests pass**

Run: `pytest tests/unit/test_squad_re_context.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py -q`

Expected: all focused spec-controller tests pass without RE execution.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py src/harness/squad_executors.py src/harness/squad_state.py tests/unit/test_squad_re_context.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py
git commit -m "refactor: decouple RE from spec runs"
```

---

### Task 6: Remove GOLDDIGGER routing from Phase A prompts and workflow

**Files:**
- Modify: `extension/workflow/definition.yaml`
- Modify: `extension/workflow/phases/phase1-discover.md`
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `extension/agents/exploration/scout.md`
- Modify: `extension/agents/exploration/cartographer.md`
- Delete: `extension/agents/exploration/appendices/cartographer-golddigger-deep-dive-reference.md`
- Modify: `tests/kernel/test_prompt_references.py`
- Modify: `tests/unit/test_static_contracts_pytest.py`
- Modify: `tests/contract/static_contracts.py`

**Interfaces:**
- Consumes: `state.published_re_context.artifacts`.
- Produces: Phase A context packs that read published RE but never request or execute RE.

- [ ] **Step 1: Write failing static contracts**

Add assertions that Phase A workflow nodes contain no `golddigger_mode1` or
`golddigger_mode2_queue`, allowed state updates contain no `golddigger_*`, and
SCOUT/CARTOGRAPHER refer to `published_re_context` without executable RE command
instructions.

- [ ] **Step 2: Verify static contracts fail**

Run: `pytest tests/kernel/test_prompt_references.py tests/unit/test_static_contracts_pytest.py -q`

Expected: failures identify current Mode 1/Mode 2 routing and prompt text.

- [ ] **Step 3: Update workflow and agent contracts**

Replace discovery context wording with:

```markdown
- If `state.json.published_re_context.status == attached`, include the bounded
  paths from `published_re_context.artifacts` as read-only brownfield evidence.
- Never invoke or request reverse engineering from Phase A. Missing or ignored
  published RE context is a valid state; continue normal scoped discovery.
```

Delete execution queues, their allowlists, and their pre-dispatch entries. Keep
the standalone RE workflow sections in `definition.yaml` unchanged.

- [ ] **Step 4: Run workflow and prompt validation**

Run: `pytest tests/kernel/test_prompt_references.py tests/kernel/test_workflow_validator.py tests/kernel/test_phase_graph.py tests/unit/test_static_contracts_pytest.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add extension/workflow extension/agents/exploration tests/kernel/test_prompt_references.py tests/unit/test_static_contracts_pytest.py tests/contract/static_contracts.py
git commit -m "refactor: remove RE dispatch from Phase A"
```

---

### Task 7: Documentation, versioning, and final verification

**Files:**
- Modify: `README.md`
- Modify: `docs/re-overview.md`
- Modify: `docs/re-config.md`
- Modify: `CHANGELOG.md`
- Modify: `src/echelon/cli.py` (`CLI_VERSION`)
- Modify: `pyproject.toml`
- Modify: `extension/extension.yml`
- Modify: `uv.lock`
- Modify: `docs/findings/echelon-grounded-review-register.md` only for the already-filed EGR-149 row if it is not yet committed; preserve all unrelated rows.
- Test: affected documentation and version contract tests.

**Interfaces:**
- Consumes: completed CLI and lifecycle behavior.
- Produces: accurate operator migration docs and synchronized release versions.

- [ ] **Step 1: Update operator documentation and changelog**

Document this migration verbatim:

```text
before: echelon spec run "Build dashboards" --re-policy changed --re-max-inner 10
after:  echelon re run --re-policy changed --re-max-inner 10
        echelon spec run "Build dashboards"
```

Document `--ignore-re`, automatic complete publication, current no-op behavior,
separate continuation/resume, and the fact that spec runs do not check RE
freshness.

- [ ] **Step 2: Bump synchronized patch versions**

Increment the current patch version consistently in `CLI_VERSION`,
`pyproject.toml`, `extension/extension.yml`, README version text, and `uv.lock`.

- [ ] **Step 3: Run focused tests**

Run:

```bash
pytest tests/unit/test_published_re_context.py \
       tests/unit/test_re_lifecycle.py \
       tests/unit/test_cli_re_lifecycle.py \
       tests/unit/test_cli_typer_app.py \
       tests/unit/test_cli_mode_args.py \
       tests/unit/test_squad_re_context.py \
       tests/integration/test_re_publication_flow.py \
       tests/kernel/test_squad_executors_journal.py \
       tests/kernel/test_prompt_references.py \
       tests/kernel/test_workflow_validator.py -q
```

Expected: all focused tests pass.

- [ ] **Step 4: Run repository verification**

Run:

```bash
bash scripts/bash/dry-run.sh
pytest
```

Expected: dry-run succeeds and pytest passes, apart from any explicitly recorded pre-existing failures reproduced against the parent commit.

- [ ] **Step 5: Reinstall and smoke-test the CLI and extension**

Run:

```bash
bash scripts/install.sh
specify extension update --dev /Users/michalbachorik/work/echelon/extension
echelon re run --help
echelon re continue --help
echelon re resume --help
echelon spec run --help
```

Expected: RE lifecycle commands and options are visible; spec help contains
`--ignore-re` and no spec-owned RE policy/budget options.

- [ ] **Step 6: Commit final docs and version changes**

```bash
git add README.md docs/re-overview.md docs/re-config.md CHANGELOG.md \
        src/echelon/cli.py pyproject.toml extension/extension.yml uv.lock
git commit -m "docs: document first-class RE lifecycle"
```
