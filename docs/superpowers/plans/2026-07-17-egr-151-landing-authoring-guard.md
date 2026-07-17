# EGR-151 Landing Authoring Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `echelon delivery land <spec>` from changing a shared checkout while another Phase A spec is active.

**Architecture:** The deterministic `runs/.current` pointer remains the authority for active Phase A authoring. Before any readiness check, branch preparation, PR merge, merge, cleanup, or status mutation, `harness.land.land()` resolves that pointer. If it names a different feature branch than the requested landing branch, land exits without Git mutation and tells the operator to checkpoint/cleanly switch to the requested spec first.

**Tech Stack:** Python 3.11, pytest, local Git subprocess fixtures, Echelon lifecycle state.

## Global Constraints

- Echelon is the sole owner of Phase A Git lifecycle actions.
- `runs/.current` identifies active Phase A authoring only.
- Delivery and landing must not stash, reset, check out, or otherwise disturb a different active Phase A checkout.
- An explicit landing request may proceed only when no authoring run is active or when the active run owns the requested feature branch.
- Tests must use temporary local Git repositories and mocks only; no LLM, Docker, or network dependency is permitted.

---

### Task 1: Block landing of a different active authoring branch

**Files:**
- Modify: `src/harness/land.py:500-545`
- Modify: `tests/unit/test_land.py:1160-1260`

**Interfaces:**
- Consumes: `echelon.spec_lifecycle.resolve_active_spec_run(project_root) -> SpecRun` and `gitops.find_feature_branch(spec_id) -> str | None`.
- Produces: `_block_different_active_authoring_spec(project_root, feature_branch, spec_id) -> bool`, where `True` means `land()` must return `False` before any Git mutation.

- [x] **Step 1: Write the failing real-Git regression test**

```python
def test_land_refuses_different_active_authoring_branch_without_git_mutation(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "-b", "002-authoring", "main")
    current = repo / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-b", encoding="utf-8")
    run_dir = repo / "runs" / "run-b"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        '{"run_id":"run-b","spec_id":"002-authoring",'
        '"feature_branch":"002-authoring","spec_dir":"runs/run-b/specs/002-authoring"}',
        encoding="utf-8",
    )
    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"

    assert land("001", project_dir=repo, gitops=gitops) is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-authoring"
    assert current.read_text(encoding="utf-8") == "run-b"
    gitops.merge_pr.assert_not_called()
    gitops.merge_branch_into_default.assert_not_called()
```

- [x] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/unit/test_land.py::test_land_refuses_different_active_authoring_branch_without_git_mutation -q`

Expected: FAIL because the current landing implementation performs readiness/checkout work without resolving `runs/.current`.

- [x] **Step 3: Add the deterministic guard before landing mutation**

```python
def _block_different_active_authoring_spec(
    project_root: Path,
    feature_branch: str,
    spec_id: str,
) -> bool:
    from echelon.spec_lifecycle import SpecLifecycleError, SpecRunNotFound, resolve_active_spec_run

    try:
        active = resolve_active_spec_run(project_root)
    except SpecRunNotFound:
        return False
    except SpecLifecycleError as exc:
        _banner("LAND — ACTIVE AUTHORING STATE BLOCKED", [("problem", str(exc))])
        return True
    if active.feature_branch == feature_branch:
        return False
    _banner(
        "LAND — ACTIVE AUTHORING SPEC",
        [
            ("active spec", active.spec_id),
            ("active branch", active.feature_branch),
            ("requested spec", spec_id),
            ("requested branch", feature_branch),
            ("next step", f"checkpoint/clean the active spec, then echelon spec switch {spec_id}"),
        ],
        subtitle="Landing is refusing to disturb a different active Phase A checkout.",
    )
    return True
```

Call the helper immediately after `feature_branch` is resolved and before `_check_ready_before_land(...)`. Pass `wrapper_project_dir` so single-repository lifecycle state is inspected before `resolve_land_repo()` can redirect a polyrepo target checkout.

- [x] **Step 4: Run focused landing tests**

Run: `pytest tests/unit/test_land.py -q`

Expected: PASS.

- [x] **Step 5: Commit the guard**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "fix: guard landing against active spec checkout"
```

### Task 2: Record the safe landing boundary

**Files:**
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/plans/2026-07-17-egr-151-landing-authoring-guard.md`

**Interfaces:**
- Consumes: the land guard introduced in Task 1.
- Produces: an EGR record that landing is explicitly guarded pending a future fully isolated landing worktree implementation.

- [x] **Step 1: Update the EGR record**

```markdown
- `echelon delivery land <spec>` now resolves `runs/.current` before any landing mutation and refuses when another feature branch is active. The output names the active/requested specs and gives the exact checkpoint/clean/switch recovery path.
```

- [x] **Step 2: Run the lifecycle boundary matrix**

Run: `pytest tests/unit/test_land.py tests/unit/test_cli_status.py tests/unit/test_run_skill.py tests/unit/test_spec_lifecycle.py tests/unit/test_spec_switch.py -q && git diff --check`

Expected: PASS with no LLM, Docker, or network access.

- [x] **Step 3: Mark executed plan steps complete and commit documentation**

```bash
git add docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md \
  docs/findings/echelon-grounded-review-register.md \
  docs/superpowers/plans/2026-07-17-egr-151-landing-authoring-guard.md
git commit -m "docs: record guarded landing lifecycle"
```
