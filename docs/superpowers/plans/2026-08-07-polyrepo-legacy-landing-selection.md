# Polyrepo Legacy Landing Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make polyrepo landing select the implementation branch proven by the current converged build and avoid comparing unrelated orchestration and target-repository branches, then land spec 911 without losing its existing dirty dependency changes.

**Architecture:** Add a current-build-aware legacy branch resolver in `harness.land` that validates the candidate against canonical fulfillment provenance before the numeric fallback runs. Keep the active Phase A checkout guard for single-repository landing and bypass only its branch-name comparison for polyrepo target landing, where Git operations cannot disturb the orchestration checkout.

**Tech Stack:** Python 3.11, pytest, Git CLI, existing Echelon `StateStore`/path/frontmatter/fulfillment helpers.

## Global Constraints

- Never select a branch that does not contain the fulfillment report's `verified_commit`.
- Current-build evidence that exists but conflicts with Git or fulfillment evidence fails closed; it does not fall back to another iteration.
- Multiple converged strategy candidates fail closed.
- Single-repository active-authoring protection remains unchanged.
- Polyrepo landing never switches or writes the orchestration workspace checkout.
- Preserve the existing Prosaic `package.json` and `package-lock.json` changes byte-for-byte.
- Do not delete legacy harness branches as part of stale-worktree cleanup.

---

### Task 1: Resolve The Proven Legacy Branch And Scope The Active Checkout Guard

**Files:**
- Modify: `src/harness/land.py:460-505,740-795`
- Modify: `tests/unit/test_land.py`

**Interfaces:**
- Consumes: `current_build_marker(harness_root, spec_id)`, `build_dir(harness_root, build_id)`, `latest_fulfillment_report(spec_dir)`, `read_fulfillment_metadata(report)`, and existing `_run_git()`.
- Produces: `_find_current_build_harness_branch(spec_id: str, project_dir: Path, harness_root: Path, spec_dir: Path | None) -> str | None`.
- Produces: legacy selection order of current-build-proven branch first, numeric `_find_latest_harness_branch()` only when current-build evidence is absent.

- [ ] **Step 1: Write failing current-build branch-selection tests**

Add `test_land_prefers_converged_current_build_iter_over_higher_failed_iter(self,
tmp_path: Path) -> None`. Use `_init_repo`, `_commit`, and `_git` to create
`harness/911/default/iter-1` containing the fulfillment `verified_commit` plus
an unrelated higher `harness/911/default/iter-4`. Create
`specs/911-demo/fulfillment-report.md`, `runs/.current-build-911`, and the current
build's `state/default.json` with `spec_id: 911-demo`, `strategy_id: default`,
`outer_iter: 1`, and `status: converged`. Call
`land("911", project_dir=wrapper, gitops=gitops, harness_root=wrapper)` with
`find_feature_branch()` returning `None`, patch the later readiness and landing
operations, and assert `merge_branch_into_default()` receives exactly
`harness/911/default/iter-1`.

Add `test_land_blocks_when_current_build_branch_misses_verified_commit(self,
tmp_path: Path) -> None`. Build the same marker/state structure, but make the
fulfillment `verified_commit` unrelated to the derived `iter-1` branch. Call
`land("911", project_dir=wrapper, gitops=gitops, harness_root=wrapper)`, assert
`False`, assert the banner title is
`LAND — BRANCH RESOLUTION BLOCKED`, and assert neither `iter-1` nor stale
`iter-4` is merged.

Also cover zero and multiple converged strategy states. Multiple candidates
must raise `RuntimeError`; an absent marker may return `None` so the legacy
numeric fallback remains available.

- [ ] **Step 2: Run branch-selection tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_land.py -k 'current_build_harness_branch or prefers_converged_current_build or current_build_branch_misses'
```

Expected: failures because `_find_current_build_harness_branch` and the
current-build-first selection do not exist.

- [ ] **Step 3: Implement minimal fail-closed selection**

Implement the helper with this behavior:

```python
def _find_current_build_harness_branch(
    spec_id: str,
    project_dir: Path,
    harness_root: Path,
    spec_dir: Path | None,
) -> str | None:
    markers = [
        current_build_marker(harness_root, alias)
        for alias in spec_identity_aliases(spec_id)
        if current_build_marker(harness_root, alias).exists()
    ]
    if not markers:
        return None
    if len(markers) != 1:
        raise RuntimeError("multiple current-build markers match the spec")
    marker = markers[0]
    build_id = marker.read_text(encoding="utf-8").strip()
    state_root = build_dir(harness_root, build_id) / "state"
    candidates = []
    for state_file in sorted(state_root.glob("*.json")):
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state.get("status") == "converged" and _spec_id_matches(
            str(state.get("spec_id") or ""), spec_id
        ):
            candidates.append(state)
    if len(candidates) != 1:
        raise RuntimeError("current build must contain exactly one converged strategy")
    state = candidates[0]
    strategy = str(state.get("strategy_id") or "")
    iteration = state.get("outer_iter")
    if not strategy or not isinstance(iteration, int) or iteration < 0:
        raise RuntimeError("converged current build lacks branch identity")
    branch = f"harness/{spec_id}/{strategy}/iter-{iteration}"
    # Require the fully qualified local branch ref, read verified_commit, and
    # require the verified commit to be an ancestor of the branch.
    return branch
```

Use `spec_identity_aliases(spec_id)` both for marker discovery and when
constructing candidate branch names, and accept exactly one existing marker and
one existing branch alias. Treat unreadable/non-JSON state,
missing/invalid fulfillment metadata, missing candidate branch, ambiguous alias,
or failed ancestry as `RuntimeError` when the marker exists.

In `land()`, call this helper before `_find_latest_harness_branch()`. Numeric
fallback is allowed only when the helper returns `None` because the current
marker is absent.

- [ ] **Step 4: Write failing active-authoring guard tests**

Add `test_polyrepo_land_does_not_compare_wrapper_and_target_branch_names(
tmp_path: Path) -> None`. Create a wrapper repo with a target under
`sources/prosaic`, canonical spec target metadata, and an active Phase A run
whose branch is `911-demo`. Make target branch resolution return
`harness/911/default/iter-1`. Patch readiness, verification, preparation, and
finish operations to succeed. Assert landing reaches preparation and no
`LAND — ACTIVE AUTHORING SPEC` banner is emitted.

Keep `test_land_refuses_different_active_authoring_branch_without_git_mutation`
as the single-repository regression case. Its existing assertions must continue
to prove that `land()` returns `False`, leaves the active branch and pointer
unchanged, performs no merge, and emits `LAND — ACTIVE AUTHORING SPEC`.

- [ ] **Step 5: Run guard tests and verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_land.py -k 'polyrepo_land_does_not_compare or single_repo_land_still_blocks'
```

Expected: the polyrepo case fails at `_block_different_active_authoring_spec`.

- [ ] **Step 6: Scope the active checkout guard**

Change the call site, not the guard's single-repository semantics:

```python
if project_dir == wrapper_project_dir and _block_different_active_authoring_spec(
    wrapper_project_dir,
    feature_branch,
    spec_id,
):
    return False
```

- [ ] **Step 7: Run focused and affected tests**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_land.py \
  tests/unit/test_land_cli.py \
  tests/unit/test_run_skill.py \
  tests/integration/test_polyrepo_delivery_convergence.py
.venv/bin/python -m compileall -q src/harness
git diff --check
```

Expected: all tests pass; compilation and whitespace checks exit 0.

- [ ] **Step 8: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "fix: select converged polyrepo landing branch"
```

---

### Task 2: Install, Land Spec 911, Restore Dirty Changes, And Verify

**Files:**
- Modify only through normal lifecycle commands: `/Users/michalbachorik/work/md_distribution/specs/911-new-prosaic-distribution-feature/spec.md`
- Preserve: `/Users/michalbachorik/work/md_distribution/sources/prosaic/package.json`
- Preserve: `/Users/michalbachorik/work/md_distribution/sources/prosaic/package-lock.json`

**Interfaces:**
- Consumes: fixed `echelon delivery land 911` and target branch `harness/911/default/iter-1`.
- Produces: Prosaic default branch containing verified commit `f7d2e147cb8add7c41d5bd9c4224b6b44fe7becb`, canonical lifecycle `landed`, and restored dirty dependency changes.

- [ ] **Step 1: Reinstall the tested harness**

Run:

```bash
cd /Users/michalbachorik/work/echelon_r/echelon
bash scripts/install.sh
/Users/michalbachorik/.echelon/venv/bin/echelon delivery land --help
```

Expected: installer and CLI import exit 0.

- [ ] **Step 2: Capture exact pre-land safety evidence**

From `/Users/michalbachorik/work/md_distribution/sources/prosaic`, capture:

```bash
git rev-parse HEAD
git status --porcelain=v1
git diff --binary | shasum -a 256
git diff --cached --binary | shasum -a 256
git diff --binary -- package.json package-lock.json | shasum -a 256
```

Require only the known tracked dependency changes before stashing. Any extra
dirty path stops landing for inspection.

- [ ] **Step 3: Create a named reversible stash**

Run:

```bash
git stash push -m "echelon-preserve-before-landing-911" -- package.json package-lock.json
ECHELON_911_STASH_MATCHES=("${(@f)$(git stash list --format='%gd%x09%H%x09%gs' | grep $'\techelon-preserve-before-landing-911$')}")
(( ${#ECHELON_911_STASH_MATCHES[@]} == 1 ))
IFS=$'\t' read -r ECHELON_911_STASH_REF ECHELON_911_STASH_COMMIT ECHELON_911_STASH_SUBJECT <<< "$ECHELON_911_STASH_MATCHES[1]"
test -n "$ECHELON_911_STASH_REF" && test -n "$ECHELON_911_STASH_COMMIT"
git status --porcelain=v1
```

Record the stash commit. Require a clean target checkout. Do not drop the stash
until its restored patch hash matches Step 2.

- [ ] **Step 4: Run landing and verification**

Run from `/Users/michalbachorik/work/md_distribution`:

```bash
/Users/michalbachorik/.echelon/venv/bin/echelon delivery land 911
```

Expected: branch `harness/911/default/iter-1` is selected, verification passes,
the target default branch receives the verified implementation, and spec status
becomes `landed`.

- [ ] **Step 5: Restore the dependency changes**

Run in the Prosaic checkout:

```bash
ECHELON_911_STASH_MATCHES=("${(@f)$(git stash list --format='%gd%x09%H%x09%gs' | grep $'\techelon-preserve-before-landing-911$')}")
(( ${#ECHELON_911_STASH_MATCHES[@]} == 1 ))
IFS=$'\t' read -r ECHELON_911_STASH_REF ECHELON_911_STASH_COMMIT ECHELON_911_STASH_SUBJECT <<< "$ECHELON_911_STASH_MATCHES[1]"
git stash apply "$ECHELON_911_STASH_COMMIT"
git status --porcelain=v1
git diff --binary -- package.json package-lock.json | shasum -a 256
```

Require the restored path set and patch hash to equal Step 2. If apply reports
conflicts or hashes differ, stop and retain the stash. Only after exact equality:

```bash
test "$(git rev-parse "$ECHELON_911_STASH_REF")" = "$ECHELON_911_STASH_COMMIT"
git stash drop "$ECHELON_911_STASH_REF"
```

- [ ] **Step 6: Verify final target and lifecycle state**

Run:

```bash
git merge-base --is-ancestor f7d2e147cb8add7c41d5bd9c4224b6b44fe7becb main
npm test
/Users/michalbachorik/.echelon/venv/bin/echelon delivery status 911
```

Read canonical frontmatter and require `status: landed`. Confirm the only dirty
target paths are the restored `package.json` and `package-lock.json`, with the
same binary diff hash captured before landing.

- [ ] **Step 7: Report outcome**

Report the selected branch, merge commit/default-branch HEAD, verification
result, lifecycle status, restored dirty hash, and whether the named stash was
dropped or retained. Do not claim a PR merge because this delivery has no PR.
