# Spec Identity And Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make numeric and canonical spec identities interoperable while preventing false landing and routing normal `echelon spec verify` through the complete fulfillment pipeline.

**Architecture:** Add one pure identity-alias helper and consume it at branch and evidence lookup boundaries. Keep lifecycle decisions in `harness.land`, verification ownership in `FulfillmentRunner`, and make the Typer command a thin resolver/adapter over those existing owners.

**Tech Stack:** Python 3, Typer, pytest, existing Echelon harness and MemPalace modules.

## Global Constraints

- New verify runs use the canonical spec directory name; numeric selectors remain accepted inputs.
- Branch absence alone must never advance a non-landed spec to `landed`.
- Direct verify audits the declared target repository at its currently checked-out commit.
- Existing numeric verify runs remain readable; no migration or renaming is introduced.
- V1 remains single-target and does not add a registry, historical checkout, or new persistence layer.

---

### Task 1: Shared Spec Identity Aliases

**Files:**
- Create: `src/kernel/spec_identity.py`
- Create: `tests/kernel/test_spec_identity.py`

**Interfaces:**
- Consumes: a user-facing spec selector or canonical directory name as `str`.
- Produces: `spec_identity_aliases(value: str) -> tuple[str, ...]`, ordered canonical input first and leading numeric alias second when present.

- [ ] **Step 1: Write failing alias tests**

```python
from kernel.spec_identity import spec_identity_aliases


def test_slug_exposes_numeric_compatibility_alias() -> None:
    assert spec_identity_aliases("906-cli-output-styling") == (
        "906-cli-output-styling",
        "906",
    )


def test_numeric_and_nonnumeric_values_stay_stable() -> None:
    assert spec_identity_aliases("906") == ("906",)
    assert spec_identity_aliases("feature-without-number") == (
        "feature-without-number",
    )
```

- [ ] **Step 2: Run the tests and confirm the module is missing**

Run: `pytest -q tests/kernel/test_spec_identity.py`

Expected: collection fails with `ModuleNotFoundError: No module named 'kernel.spec_identity'`.

- [ ] **Step 3: Implement the pure helper**

```python
from __future__ import annotations

import re


_NUMERIC_PREFIX = re.compile(r"^(?P<number>\d+)-.+$")


def spec_identity_aliases(value: str) -> tuple[str, ...]:
    match = _NUMERIC_PREFIX.fullmatch(value)
    if match is None:
        return (value,)
    return (value, match.group("number"))
```

- [ ] **Step 4: Run the focused tests**

Run: `pytest -q tests/kernel/test_spec_identity.py`

Expected: all tests pass.

- [ ] **Step 5: Commit the identity helper**

```bash
git add src/kernel/spec_identity.py tests/kernel/test_spec_identity.py
git commit -m "feat: normalize spec identity aliases"
```

---

### Task 2: Safe Alias-Aware Landing

**Files:**
- Modify: `src/harness/gitops.py:435`
- Modify: `src/harness/land.py:456`
- Modify: `src/harness/land.py:555`
- Modify: `tests/unit/test_gitops.py`
- Modify: `tests/unit/test_land.py:457`

**Interfaces:**
- Consumes: `spec_identity_aliases(spec_id)` from Task 1 and existing fulfillment metadata from `latest_fulfillment_report`.
- Produces: alias-aware `GitOpsManager.find_feature_branch`; alias-aware legacy branch lookup; `_finish_branchless_landing(...) -> bool` that uses lifecycle status and verified-commit ancestry.

- [ ] **Step 1: Write failing feature and legacy branch alias tests**

Add a `GitOpsManager.find_feature_branch("906-cli-output-styling")` test whose mirror contains branch `906`, and add a land test where only `harness/906/default/iter-3` exists while the command receives the slug. Assert the numeric branches are selected.

```python
assert manager.find_feature_branch("906-cli-output-styling") == "906"
gitops.merge_branch_into_default.assert_called_once_with(
    "harness/906/default/iter-3", str(tmp_path)
)
```

- [ ] **Step 2: Run alias tests and confirm lookup failure**

Run: `pytest -q tests/unit/test_gitops.py tests/unit/test_land.py -k 'alias or numeric_legacy'`

Expected: tests fail because current lookups use only the supplied slug.

- [ ] **Step 3: Apply ordered aliases to both branch lookup paths**

Import `spec_identity_aliases`. In `find_feature_branch`, inspect each alias in order, using exact then prefix patterns for that alias. In `_find_latest_harness_branch`, collect matching branches for every alias, deduplicate them, prefer the first alias with candidates, and preserve the existing highest-iteration ambiguity check.

```python
for alias in spec_identity_aliases(spec_id):
    for pattern in (alias, f"{alias}-*"):
        branches = _list_branches(pattern)
        if branches:
            return branches[0]
```

- [ ] **Step 4: Replace unsafe no-branch tests with the positive-evidence matrix**

Create real temporary git repositories and reports covering:

```python
def test_no_branch_blocks_unmerged_verified_commit_and_preserves_status(...): ...
def test_no_branch_marks_ready_spec_landed_when_verified_commit_is_ancestor(...): ...
def test_no_branch_keeps_legacy_landed_spec_idempotent_without_report(...): ...
def test_no_branch_blocks_non_landed_spec_without_report(...): ...
```

For blocked cases, assert `write_status`, `_cleanup_worktrees`, and `_delete_harness_branches` are not called. For merged verified commits, assert status becomes `landed` and selector-related cleanup runs.

- [ ] **Step 5: Run matrix tests and confirm the current false-success behavior**

Run: `pytest -q tests/unit/test_land.py -k 'no_branch or branch_already_deleted'`

Expected: unmerged and reportless non-landed cases fail because current code returns success and writes `landed`.

- [ ] **Step 6: Implement branchless landing reconciliation**

Add a focused helper that reads frontmatter status and the latest report metadata, checks verified commit ancestry against the target default checkout with `git merge-base --is-ancestor`, and implements the design matrix. Return false with a `LAND - BRANCH NOT LANDED` banner for insufficient evidence. Do not call the normal branch deletion path when no branch exists.

```python
if status == "landed" and not verified_commit:
    return True
if not verified_commit:
    return _block_branchless_landing(spec_id, "no verified commit is recorded")
if not _is_ancestor(verified_commit, project_dir):
    return _block_branchless_landing(
        spec_id,
        f"verified commit {verified_commit} is not on the default branch",
    )
write_status(spec_dir, "landed")
_cleanup_worktrees(spec_id, wrapper_project_dir, gitops)
_delete_harness_branches(spec_id, project_dir)
return True
```

- [ ] **Step 7: Run all landing and gitops tests**

Run: `pytest -q tests/unit/test_gitops.py tests/unit/test_land.py`

Expected: all tests pass, including the existing merge, prepare-only, and cleanup behavior.

- [ ] **Step 8: Commit safe landing**

```bash
git add src/harness/gitops.py src/harness/land.py tests/unit/test_gitops.py tests/unit/test_land.py
git commit -m "fix: require positive evidence for branchless landing"
```

---

### Task 3: Complete Normal-Pipeline Spec Verify

**Files:**
- Modify: `src/harness/fulfillment_runner.py:129`
- Modify: `src/echelon/cli_app.py:2990`
- Modify: `tests/unit/test_fulfillment_runner.py`
- Modify: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: canonical spec directory from `find_spec_dir`, targets from `read_targets`, configuration from `load_config`, and `AICodingCliProvider`.
- Produces: `run_spec_verify(project_root: Path, selector: str, *, reconcile: bool, dry_run: bool) -> FulfillmentRefreshResult`; extended `FulfillmentRunner.refresh(..., reconcile: bool = False, dry_run: bool = False)`.

- [ ] **Step 1: Write failing runner tests for orchestration-owned workflow and flags**

Add tests where the target checkout has no verify skill but the orchestration root does. Assert the generated prompt contains canonical `spec_dir`, deterministic phase content, and `--reconcile --dry-run`. Add a cache fixture and assert reconciliation causes a provider call, while standalone dry-run fails before dispatch.

```python
result = runner.refresh(
    str(target),
    "906-cli-output-styling",
    spec_dir=spec_dir,
    orchestration_root=workspace,
    reconcile=True,
    dry_run=True,
)
provider.exec_prompt.assert_called_once()
assert "--reconcile" in provider.exec_prompt.call_args.args[1]
assert "--dry-run" in provider.exec_prompt.call_args.args[1]
```

- [ ] **Step 2: Run the focused runner tests**

Run: `pytest -q tests/unit/test_fulfillment_runner.py -k 'orchestration_skill or reconcile or dry_run'`

Expected: tests fail because flags are unsupported and skill lookup is target-only.

- [ ] **Step 3: Extend the runner without changing its ownership**

Add boolean parameters. Reject `dry_run=True` when `reconcile=False` before any provider or artifact work. Skip both the full-report cache and deterministic-artifact short path for reconciliation, because neither path executes requested reconciliation work. Resolve the verify skill and phases from the orchestration root when provided, pass that workflow root into prompt construction, and append valid flags to the verify arguments.

```python
if dry_run and not reconcile:
    return FulfillmentRefreshResult(
        status="failed",
        exit_code=2,
        reason="dry_run requires reconcile",
    )
force_execution = reconcile
if not force_execution and _latest_full_report_matches_cache(...):
    return cached_result
if not force_execution:
    direct_result = _try_direct_no_fallback_refresh(...)
    if direct_result is not None:
        return direct_result

skill_root = Path(orchestration_root) if orchestration_root is not None else worktree
skill_path = find_skill("echelon.verify-spec", skill_root, self._prompt_executor.cli)
flags = [flag for enabled, flag in ((reconcile, "--reconcile"), (dry_run, "--dry-run")) if enabled]
arguments = " ".join([spec_id, f"spec_dir={resolved_spec_dir}", *flags])
prompt = _build_verify_spec_prompt(skill_root, skill_path, arguments)
```

- [ ] **Step 4: Run all fulfillment runner tests**

Run: `pytest -q tests/unit/test_fulfillment_runner.py`

Expected: all tests pass, including cache, report validation, provenance stamping, and ledger writing.

- [ ] **Step 5: Write failing CLI adapter tests**

Test from a workspace containing `specs/906-cli-output-styling/spec.md` with one declared target `sources/prosaic`. Monkeypatch config/provider/runner and assert:

```python
assert call == {
    "worktree_path": str(target.resolve()),
    "spec_id": "906-cli-output-styling",
    "spec_dir": spec_dir.resolve(),
    "orchestration_root": workspace.resolve(),
    "reconcile": True,
    "dry_run": False,
}
```

Also test no target falls back to the workspace, multiple targets exit nonzero before runner construction, missing target exits nonzero, and failed runner results produce a nonzero CLI exit.

- [ ] **Step 6: Run the CLI tests and confirm legacy dispatch is still used**

Run: `pytest -q tests/unit/test_cli_typer_app.py -k 'spec_verify'`

Expected: tests fail because `spec_verify` calls `_dispatch_skill_command` directly.

- [ ] **Step 7: Implement the thin direct-verify adapter**

Resolve the canonical spec and target before creating `AICodingCliProvider(load_config(workspace, squad_only=True))`. Invoke `FulfillmentRunner.refresh` with the canonical directory name, print `status`, `reason`, `report`, and ledger counts when present, and raise `typer.Exit(code=result.exit_code or 1)` unless status is `cached` or `refreshed` with exit code zero.

```python
spec_dir = find_spec_dir(selector, project_root)
if spec_dir is None:
    raise typer.BadParameter(f"spec not found: {selector}")
targets = read_targets(spec_dir)
if len(targets) > 1:
    raise typer.BadParameter("spec verify requires exactly one target repo")
target = project_root if not targets else (project_root / targets[0]).resolve()
result = FulfillmentRunner(AICodingCliProvider(load_config(project_root, squad_only=True))).refresh(
    str(target),
    spec_dir.name,
    spec_dir=spec_dir,
    orchestration_root=project_root,
    reconcile=reconcile,
    dry_run=dry_run,
)
```

- [ ] **Step 8: Run direct verify and CLI compatibility tests**

Run: `pytest -q tests/unit/test_cli_typer_app.py tests/unit/test_cli_fulfillment_commands.py`

Expected: all tests pass and both help surfaces still document the flags.

- [ ] **Step 9: Commit normal-pipeline verify**

```bash
git add src/harness/fulfillment_runner.py src/echelon/cli_app.py tests/unit/test_fulfillment_runner.py tests/unit/test_cli_typer_app.py
git commit -m "fix: route spec verify through fulfillment runner"
```

---

### Task 4: Legacy-Compatible Evidence Discovery

**Files:**
- Modify: `src/echelon/mempalace_spec_evidence.py:396`
- Modify: `tests/unit/test_mempalace_spec_evidence.py`

**Interfaces:**
- Consumes: `spec_identity_aliases(spec_id)` from Task 1.
- Produces: evidence run resolution across canonical and numeric standalone/nested layouts, preserving latest-valid-artifact selection.

- [ ] **Step 1: Write failing discovery tests**

Add fixtures for `runs/build-old/verify-spec/906`, `runs/build-new/verify-spec/906-cli-output-styling`, and incomplete candidates. Test automatic lookup, explicit `run_id`, newest-valid choice, and error text listing both aliases.

```python
resolved = _resolve_verify_evidence_run_dir(
    tmp_path,
    "906-cli-output-styling",
    "build-old",
)
assert resolved == tmp_path / "runs" / "build-old" / "verify-spec" / "906"
```

- [ ] **Step 2: Run tests and confirm numeric fallback is absent**

Run: `pytest -q tests/unit/test_mempalace_spec_evidence.py -k 'numeric or alias or incomplete'`

Expected: numeric nested discovery fails for a canonical slug.

- [ ] **Step 3: Implement ordered, deduplicated candidate collection**

Generate standalone and nested patterns for every alias, include both alias directories for explicit `run_id`, append the direct run once, then deduplicate paths before applying the existing completeness and modification-time rules.

```python
aliases = spec_identity_aliases(spec_id)
candidates: list[Path] = []
for alias in aliases:
    candidates.extend(runs.glob(f"verify-spec-{alias}-*"))
    candidates.extend(runs.glob(f"*/verify-spec/{alias}"))
candidates = list(dict.fromkeys(candidates))
```

Include `", ".join(aliases)` in the not-found diagnostic.

- [ ] **Step 4: Run evidence tests**

Run: `pytest -q tests/unit/test_mempalace_spec_evidence.py tests/unit/test_cli_spec_evidence_memory.py`

Expected: all publication, mining, and compatibility tests pass.

- [ ] **Step 5: Commit evidence compatibility**

```bash
git add src/echelon/mempalace_spec_evidence.py tests/unit/test_mempalace_spec_evidence.py
git commit -m "fix: discover numeric and canonical verify evidence"
```

---

### Task 5: User Documentation And End-to-End Regression

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/integration/test_spec_graph_workflow.py`

**Interfaces:**
- Consumes: the completed CLI behavior from Tasks 1-4.
- Produces: documented normal workflow and one integration regression proving verify artifacts remain usable by evidence publication and graph refresh.

- [ ] **Step 1: Add an integration regression around the normal flow**

Use a temporary orchestration workspace and declared target. Stub only the provider execution so it writes valid verify artifacts, then invoke the normal pipeline pieces and assert canonical provenance plus evidence availability.

```python
assert refresh.status == "refreshed"
assert metadata["spec_id"] == "906-cli-output-styling"
assert metadata["verified_commit"] == target_head
assert publication.status == "published"
```

- [ ] **Step 2: Run the integration regression**

Run: `pytest -q tests/integration/test_spec_graph_workflow.py`

Expected: all tests pass.

- [ ] **Step 3: Document the actual operator flow and safety behavior**

Add a concise README sequence:

```bash
echelon spec verify 906 --reconcile
echelon spec evidence publish 906
echelon graph workspace refresh
echelon graph view --renderer vis
```

State that verify uses the spec's declared target at its checked-out commit, that numeric and canonical selectors address the same spec, that legacy numeric evidence runs are readable, and that no-branch landing requires positive commit/status evidence. Add a matching changelog entry.

- [ ] **Step 4: Run focused and full verification**

Run:

```bash
pytest -q \
  tests/kernel/test_spec_identity.py \
  tests/unit/test_gitops.py \
  tests/unit/test_land.py \
  tests/unit/test_fulfillment_runner.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_mempalace_spec_evidence.py \
  tests/unit/test_cli_spec_evidence_memory.py \
  tests/integration/test_spec_graph_workflow.py
pytest -q
git diff --check
```

Expected: all tests pass; `git diff --check` prints no output.

- [ ] **Step 5: Smoke-test selector compatibility in md_distribution**

From `/Users/michalbachorik/work/md_distribution`, run read-only or provider-stubbed checks that resolve both `906` and `906-cli-output-styling` to the same spec and find existing numeric evidence. Do not alter the user's restored `package.json`, `package-lock.json`, or spec 910 graph artifacts.

- [ ] **Step 6: Commit docs and integration coverage**

```bash
git add README.md CHANGELOG.md tests/integration/test_spec_graph_workflow.py
git commit -m "docs: describe verified spec lifecycle flow"
```
