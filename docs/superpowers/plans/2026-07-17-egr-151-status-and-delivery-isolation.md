# EGR-151 Status and Delivery Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the active Phase A spec visible in `echelon spec status` and ensure explicitly addressed Phase B delivery never changes that authoring checkout.

**Architecture:** `runs/.current` remains the sole pointer for the active authoring run. The status command reads that pointer deterministically, renders its declared branch and validated checkpoint when available, and lists alternative switchable runs. Delivery continues to resolve and validate the requested published spec by ID, but its run skill must use the mirror/worktree Git boundary rather than preparing the shared workspace branch.

**Tech Stack:** Python 3.11, pytest, standard-library `subprocess` Git fixtures, existing Echelon lifecycle and harness modules.

## Global Constraints

- Echelon, not spec-kit, is the sole owner of Phase A Git lifecycle actions.
- A new spec may start independently of another spec’s workflow status; each starts from the default branch.
- `runs/.current` identifies active Phase A authoring only; delivery must neither read nor rewrite it.
- `echelon delivery run <spec>` must not stash, reset, or check out the shared Phase A workspace.
- Phase A readiness is evaluated for the explicitly requested spec before a build provider is launched.
- Tests must use mocks and local Git only; no test may require an LLM, Docker, or a network service.

---

### Task 1: Render deterministic active-spec lifecycle state

**Files:**
- Modify: `src/echelon/cli.py:5876-5950`
- Modify: `tests/unit/test_cli_status.py:1-340`

**Interfaces:**
- Consumes: `echelon.spec_lifecycle.resolve_active_spec_run(project_root) -> SpecRun`, `discover_spec_runs(project_root) -> tuple[SpecRun, ...]`, and `echelon.spec_switch.validate_spec_checkpoint(project_root, run) -> ValidatedSpecCheckpoint`.
- Produces: an `ACTIVE SPEC` status banner that names the active run, declared feature branch, latest validated checkpoint (or an explicit unavailable reason), recorded managed stash, and other selectable runs.

- [x] **Step 1: Write the failing active-state presentation test**

```python
def test_status_lists_active_spec_checkpoint_stash_and_other_runs(tmp_path, capsys):
    active = _write_run(tmp_path, "run-a", spec_id="001-spec-a")
    _write_run(tmp_path, "run-b", spec_id="002-spec-b")
    (tmp_path / "runs" / ".current").write_text("run-a", encoding="utf-8")
    state = json.loads((active / "state.json").read_text(encoding="utf-8"))
    state["phase_a_stash"] = {"commit": "stash-commit"}
    (active / "state.json").write_text(json.dumps(state), encoding="utf-8")

    with patch("echelon.spec_switch.validate_spec_checkpoint") as checkpoint:
        checkpoint.return_value = SimpleNamespace(checkpoint_id="cp-a", phase="plan", commit="abc123")
        _cmd_status(tmp_path)

    output = capsys.readouterr().out
    assert "ACTIVE SPEC" in output
    assert "001-spec-a" in output
    assert "cp-a" in output
    assert "stash-commit" in output
    assert "002-spec-b" in output
```

- [x] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/unit/test_cli_status.py::test_status_lists_active_spec_checkpoint_stash_and_other_runs -q`

Expected: FAIL because `echelon spec status` does not yet render lifecycle-specific state.

- [x] **Step 3: Add lifecycle-aware status rendering**

```python
def _print_active_spec_status(project_root: Path) -> None:
    from echelon.spec_lifecycle import SpecRunNotFound, discover_spec_runs, resolve_active_spec_run
    from echelon.spec_switch import SpecSwitchError, validate_spec_checkpoint

    try:
        active = resolve_active_spec_run(project_root)
    except SpecRunNotFound:
        return
    fields = [("Run", active.run_dir_name), ("Spec", active.spec_id), ("Branch", active.feature_branch)]
    try:
        checkpoint = validate_spec_checkpoint(project_root, active)
        fields.append(("Checkpoint", f"{checkpoint.checkpoint_id} ({checkpoint.phase})"))
    except SpecSwitchError as exc:
        fields.append(("Checkpoint", f"unavailable: {exc}"))
    others = [run.spec_id for run in discover_spec_runs(project_root) if run.run_dir != active.run_dir]
    if others:
        fields.append(("Switchable", ", ".join(others)))
    _banner("ACTIVE SPEC", fields)
```

Read the active run’s `state.json` only to render a recorded `phase_a_stash.commit`; malformed or absent stash data must be shown as unavailable rather than preventing the broader status report. Invoke this helper immediately after the status header.

- [x] **Step 4: Run the status tests**

Run: `pytest tests/unit/test_cli_status.py -q`

Expected: PASS.

- [x] **Step 5: Commit the self-contained status change**

```bash
git add src/echelon/cli.py tests/unit/test_cli_status.py
git commit -m "feat: show active spec lifecycle status"
```

### Task 2: Stop delivery from changing the shared authoring checkout

**Files:**
- Modify: `src/harness/skills/run_skill.py:393-416`
- Modify: `tests/unit/test_run_skill.py:240-310`

**Interfaces:**
- Consumes: `StrategyCoordinator(provider, gitops, config, base_dir, build_id)` and spec-scoped `harness.paths.current_build_marker(base_path, spec_id)`.
- Produces: `run(...)` that creates only the requested spec’s build marker and never calls `gitops.ensure_on_default_branch`.

- [x] **Step 1: Replace the branch-recovery expectation with an isolation test**

```python
def test_delivery_run_does_not_prepare_or_switch_target_checkout(
    self,
    mock_coordinator_cls: MagicMock,
    mock_gc: MagicMock,
    mock_parse: MagicMock,
    tmp_path: Path,
) -> None:
    from harness.config import HarnessConfig
    from harness.paths import current_build_marker
    from harness.run_intent import RunIntent
    from harness.skills.run_skill import run

    target = tmp_path / "repo-a"
    target.mkdir()
    runtime = tmp_path / "wrapper" / "runs" / "targets" / "repo-a"
    runtime.mkdir(parents=True)
    config = HarnessConfig(target_repo=str(target), target_default_branch="main", provider="docker")
    mock_parse.return_value = RunIntent(spec_id="012", mode="semi", auto_merge=False)
    coordinator_instance = MagicMock()
    coordinator_instance.start.return_value = [_make_converged_result()]
    coordinator_instance.compare_results.return_value = {
        "strategies": {},
        "summary": {"converged": 1, "failed": 0, "total_tokens": 0},
    }
    mock_coordinator_cls.return_value = coordinator_instance
    gitops = MagicMock()

    run(
        "spec 012 semi",
        provider=MagicMock(),
        gitops=gitops,
        base_dir=str(runtime),
        config=config,
    )

    gitops.ensure_on_default_branch.assert_not_called()
    assert current_build_marker(runtime, "012").exists()
```

- [x] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/unit/test_run_skill.py::TestRunSkill::test_delivery_run_does_not_prepare_or_switch_target_checkout -q`

Expected: FAIL because `run()` calls `gitops.ensure_on_default_branch(...)`.

- [x] **Step 3: Remove shared-workspace Git preparation from delivery**

```python
    # Delivery operates through the GitOps mirror and its ephemeral worktrees.
    # Do not prepare the Phase A authoring checkout: an explicitly selected
    # spec may be delivered while another spec remains active there.
```

Delete the `project_working_dir` / `target_repo` selection and the `try: gitops.ensure_on_default_branch(...)` block. Keep the existing spec-scoped build-marker creation unchanged.

- [x] **Step 4: Run run-skill and delivery preflight tests**

Run: `pytest tests/unit/test_run_skill.py tests/unit/test_cli_harness_run.py -q`

Expected: PASS, with no LLM, Docker, or network access.

- [x] **Step 5: Commit the isolation change**

```bash
git add src/harness/skills/run_skill.py tests/unit/test_run_skill.py
git commit -m "fix: isolate delivery from active spec checkout"
```

### Task 3: Verify EGR-151 lifecycle boundaries and record progress

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Test: `tests/unit/test_cli_status.py`
- Test: `tests/unit/test_run_skill.py`
- Test: `tests/unit/test_cli_harness_run.py`

**Interfaces:**
- Consumes: the status and delivery guarantees introduced in Tasks 1 and 2.
- Produces: an EGR progress record that declares status visibility and delivery isolation completed, while retaining landing-worktree isolation as a later step.

- [x] **Step 1: Write the explicit requested-spec readiness regression test**

```python
def test_delivery_blocks_unready_requested_spec_before_runner(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ready_spec = tmp_path / "specs" / "001-ready"
    unready_spec = tmp_path / "specs" / "002-unready"
    _write_phase_a_build_inputs(ready_spec)
    unready_spec.mkdir(parents=True)
    (unready_spec / "spec.md").write_text(SPEC_WITH_LOCAL_TARGET, encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with patch("harness.skills.run_skill.run") as run:
        with pytest.raises(SystemExit):
            _cmd_harness_run(["002-unready"])

    run.assert_not_called()
    assert "002-unready" in capsys.readouterr().err
```

Use the existing CLI harness fixture pattern and assert the error identifies `002-unready`; do not use `runs/.current` in this test.

- [x] **Step 2: Run the focused readiness test to verify the existing protection**

Run: `pytest tests/unit/test_cli_harness_run.py -q`

Expected: PASS because `_cmd_harness_run` validates the `spec_dir` it resolved from the requested ID before it calls `run(...)`.

- [x] **Step 3: Update the EGR implementation record**

```markdown
### Completed: active authoring visibility and delivery isolation

- `echelon spec status` renders the exact `runs/.current` authoring run, branch, checkpoint/stash state, and other selectable runs.
- Explicit delivery uses the requested spec’s readiness and its own `.current-build-<spec>` marker; it no longer prepares or changes the active Phase A checkout.
- Landing remains a separately guarded follow-up because its existing default-branch operation must move to an isolated worktree.
```

- [x] **Step 4: Run the combined regression suite and whitespace check**

Run: `pytest tests/unit/test_cli_status.py tests/unit/test_run_skill.py tests/unit/test_cli_harness_run.py tests/unit/test_spec_lifecycle.py tests/unit/test_spec_switch.py -q && git diff --check`

Expected: PASS and no output from `git diff --check`.

- [x] **Step 5: Commit the EGR record and tests**

```bash
git add docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md \
  docs/findings/echelon-grounded-review-register.md \
  tests/unit/test_cli_harness_run.py
git commit -m "test: cover explicit spec delivery lifecycle"
```
