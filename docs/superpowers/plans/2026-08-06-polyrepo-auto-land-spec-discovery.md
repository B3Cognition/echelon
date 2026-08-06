# Polyrepo Auto-Land Spec Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

**Goal:** Make converged target-side polyrepo deliveries auto-land through the orchestration workspace that owns the canonical spec, and report spec lookup failure separately from missing lifecycle status.

**Architecture:** Introduce an explicit orchestration-root input alongside the existing target harness root. Resolve and validate both roots once in `run_skill.run()`, propagate the workspace root through every CLI/resume adapter, and use it only for canonical spec/history/landing operations while the target-scoped `GitOpsManager` and harness state remain rooted at `base_dir`. Guard multi-target specs before auto-land because aggregate landing is not part of this change.

**Tech Stack:** Python 3.11+, pathlib, pytest, unittest.mock, existing Echelon CLI/UI and harness modules.

## Global Constraints

- Preserve `find_spec_dir()`'s Git-boundary rule; do not make discovery walk across repository boundaries.
- Preserve single-repository behavior by defaulting `orchestration_root` to `base_dir`.
- Keep coordinator state, build markers, garbage collection, mirrors, worktrees, and target Git operations rooted at `base_dir` and the supplied target `gitops`.
- Use the resolved orchestration workspace for canonical spec discovery, run history, and `land(project_dir=...)`.
- Do not infer `ECHELON_POLYREPO_ROOT` inside `land()`; CLI adapters own environment/config interpretation.
- Do not let per-target workers auto-land a multi-target spec.
- Do not clean, reset, land, or otherwise mutate the dirty Prosaic source checkout during verification.
- Add no dependencies. Follow test-driven development: add a failing regression, run it, implement the smallest change, and rerun it.
- Make one focused commit after each task; do not amend unrelated existing commits.

---

## Task 1: Add an explicit, validated run context

**Files:**

- Modify: `src/harness/skills/run_skill.py`
- Modify: `tests/unit/test_run_skill.py`

### Step 1: Add failing root-resolution tests

Add `Path` and `pytest` imports and import the new symbols from `harness.skills.run_skill`. Add focused tests for this public contract:

```python
from harness.skills.run_skill import RunContextError, _resolve_run_roots


def test_resolve_run_roots_defaults_workspace_to_harness_root(tmp_path: Path) -> None:
    harness_root, workspace_root = _resolve_run_roots(str(tmp_path), None)

    assert harness_root == tmp_path.resolve()
    assert workspace_root == tmp_path.resolve()


def test_resolve_run_roots_keeps_polyrepo_roots_distinct(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    harness = workspace / "runs" / "targets" / "api"
    harness.mkdir(parents=True)

    harness_root, workspace_root = _resolve_run_roots(harness, workspace)

    assert harness_root == harness.resolve()
    assert workspace_root == workspace.resolve()


def test_resolve_run_roots_rejects_missing_explicit_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(
        RunContextError,
        match=f"orchestration root is not a directory: {missing.resolve()}",
    ):
        _resolve_run_roots(tmp_path, missing)
```

Extend the existing `run()` tests with two coordinator-construction guards. Patch `parse_intent()` to return the same valid intent fixture already used in the file, patch `find_spec_dir()`, and patch `DeliveryCoordinator`:

- an explicitly supplied nonexistent orchestration root raises `RunContextError` before `DeliveryCoordinator` is called;
- an existing explicit orchestration root whose `find_spec_dir()` result is `None` raises `RunContextError` containing the spec id and resolved root before `DeliveryCoordinator` is called.

Run the narrow tests and confirm they fail because the API does not exist:

```bash
pytest -q tests/unit/test_run_skill.py -k 'resolve_run_roots or explicit_orchestration'
```

Expected: import/signature failures for `RunContextError`, `_resolve_run_roots`, or `orchestration_root`.

### Step 2: Implement the root contract

In `src/harness/skills/run_skill.py`, add:

```python
class RunContextError(ValueError):
    """The delivery caller supplied an invalid orchestration context."""


def _resolve_run_roots(
    base_dir: str | Path,
    orchestration_root: str | Path | None,
) -> tuple[Path, Path]:
    harness_root = Path(base_dir).resolve()
    workspace_root = (
        Path(orchestration_root).resolve()
        if orchestration_root is not None
        else harness_root
    )
    if orchestration_root is not None and not workspace_root.is_dir():
        raise RunContextError(
            f"orchestration root is not a directory: {workspace_root}"
        )
    return harness_root, workspace_root
```

Add the backwards-compatible final parameter to `run()`:

```python
orchestration_root: str | Path | None = None,
```

Resolve the roots before intent parsing. After intent parsing, discover the spec from `workspace_root`. If an explicit workspace was supplied and the spec is absent, raise:

```python
raise RunContextError(
    f"spec directory for {intent.spec_id} was not found from "
    f"orchestration root {workspace_root}"
)
```

Perform both validations before constructing `StrategyCoordinator`, writing a build marker, or starting garbage collection. Pass the resolved `spec_dir` into `_print_delivery_summary()` instead of letting that helper call `_resolve_spec_dir(base_dir, ...)` again. Use the same `spec_dir` for both history calls and `_append_harness_history()`. Retain `harness_root` for coordinator/state/GC paths, and delete `_resolve_spec_dir()` after its final caller is removed.

### Step 3: Verify Task 1

```bash
pytest -q tests/unit/test_run_skill.py -k 'resolve_run_roots or explicit_orchestration'
pytest -q tests/unit/test_run_skill.py
```

Expected: all `test_run_skill.py` tests pass.

### Step 4: Commit Task 1

```bash
git add src/harness/skills/run_skill.py tests/unit/test_run_skill.py
git commit -m "fix: separate delivery harness and orchestration roots"
```

---

## Task 2: Propagate orchestration context through every adapter

**Files:**

- Modify: `src/echelon/cli.py`
- Modify: `src/harness/skills/resume_skill.py`
- Modify: `src/harness/__main__.py`
- Modify: `src/harness/skills/run_skill.py`
- Modify: `tests/unit/test_cli_harness_run.py`
- Modify: `tests/unit/test_cli_harness_resume.py`
- Modify: `tests/unit/test_resume_skill.py`
- Create: `tests/unit/test_harness_main_run_context.py`

### Step 1: Add failing delivery CLI forwarding tests

In the existing polyrepo run test that patches `harness.skills.run_skill.run`, add:

```python
kwargs = mock_run.call_args.kwargs
assert kwargs["base_dir"] == str(target.harness_root)
assert kwargs["orchestration_root"] == spec_search_root.resolve()
```

Use the actual `HarnessWorkspaceTarget` and `spec_search_root` variables already constructed by that fixture; do not recreate root-discovery logic in the assertion.

In `tests/unit/test_cli_harness_resume.py`, extend the retry, recovery, normal re-entry, and answer/re-entry cases that already patch `run_skill.run`. For each call assert:

```python
assert mock_run.call_args.kwargs["orchestration_root"] == spec_search_root.resolve()
```

If a branch performs more than one call, use `mock_run.call_args_list` and assert every re-entry receives the same workspace root.

Run:

```bash
pytest -q tests/unit/test_cli_harness_run.py -k polyrepo
pytest -q tests/unit/test_cli_harness_resume.py -k 'retry or recover or reentry or answer'
```

Expected: failures showing `orchestration_root` is absent.

### Step 2: Forward the root in the delivery CLI

At `_cmd_harness_run`'s `run_skill.run(...)` call, pass the already-resolved canonical search root:

```python
orchestration_root=spec_search_root,
```

Do the same at all four `_cmd_harness_resume` re-entry call sites. Do not recompute the workspace from the target harness path.

Keep the delivery CLI's existing broad exception boundary, harness error rendering, blocked-state recording, and exit semantics unchanged.

### Step 3: Add failing legacy and standalone adapter tests

In `tests/unit/test_resume_skill.py`, call:

```python
resume(
    "resume 042",
    provider,
    gitops,
    base_dir=str(harness_root),
    orchestration_root=workspace,
)
```

Assert the patched `run()` receives the same `orchestration_root`.

Add `tests/unit/test_harness_main_run_context.py` with two entry-boundary tests using `monkeypatch`/`unittest.mock`:

- a `RunContextError` from standalone `run()` exits with status 1, prints `HARNESS — INVALID ORCHESTRATION CONTEXT`, includes `problem`, and does not print `Traceback`;
- the legacy `resume_skill.resume()` boundary does the same when its delegated `run()` raises `RunContextError`.

Capture output with `capsys` and assert the exact next-step text from the design:

```text
run delivery from the workspace that owns specs/, or repair the supplied orchestration root
```

Run:

```bash
pytest -q tests/unit/test_resume_skill.py tests/unit/test_harness_main_run_context.py
```

Expected: signature/forwarding failures and an uncontrolled exception until the adapters are changed.

### Step 4: Implement controlled context-error rendering

Add a shared helper in `run_skill.py` so both thin adapters render one format through `echelon.ui.banner`:

```python
def print_run_context_error(spec_id: str, error: RunContextError) -> None:
    banner(
        "HARNESS — INVALID ORCHESTRATION CONTEXT",
        [
            ("spec", spec_id),
            ("problem", str(error)),
            (
                "next step",
                "run delivery from the workspace that owns specs/, or repair "
                "the supplied orchestration root",
            ),
        ],
        file=sys.stderr,
    )
```

Import `banner` locally from `echelon.ui` and write to `sys.stderr`, matching the existing `banner(title, fields, ..., file=...)` signature.

Update `resume_skill.resume()` to accept and forward:

```python
orchestration_root: str | Path | None = None,
```

Wrap the final delegated `run(...)` call in `resume_skill.resume()` with `except RunContextError`, call the shared renderer with the already-parsed `spec_id`, then raise `SystemExit(1)`. In `_run()` in `harness.__main__`, catch `RunContextError` around the direct `run()` call, render it with the environment-derived `spec_id`, then raise `SystemExit(1)`. `_resume()` needs no duplicate catch because `resume_skill.resume()` is already its controlled boundary. Leave direct `run()` behavior typed and exception-based; do not swallow provider, coordinator, or Git errors.

### Step 5: Verify and commit Task 2

```bash
pytest -q tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py
pytest -q tests/unit/test_resume_skill.py tests/unit/test_harness_main_run_context.py
git add src/echelon/cli.py src/harness/__main__.py src/harness/skills/run_skill.py src/harness/skills/resume_skill.py tests/unit/test_cli_harness_run.py tests/unit/test_cli_harness_resume.py tests/unit/test_resume_skill.py tests/unit/test_harness_main_run_context.py
git commit -m "fix: propagate orchestration context through delivery adapters"
```

---

## Task 3: Route auto-land correctly and separate lookup diagnostics

**Files:**

- Modify: `src/harness/skills/run_skill.py`
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_run_skill.py`
- Modify: `tests/unit/test_land.py`

### Step 1: Add failing auto-land routing tests

Extend the existing auto-merge/converged `run()` test rather than building a second coordinator fixture. Create a workspace and nested target harness root, write or mock a canonical single-target spec under the workspace, and call:

```python
run(
    "run 042 mode=banzai",
    provider=provider,
    gitops=gitops,
    base_dir=str(harness_root),
    orchestration_root=workspace,
)
```

Using that test's existing `mock_land` and coordinator patch, assert:

```python
mock_land.assert_called_once_with(
    "042",
    project_dir=workspace.resolve(),
    gitops=gitops,
)
assert mock_coordinator.call_args.kwargs["base_dir"] == harness_root.resolve()
```

Because `StrategyCoordinator` is constructed with keywords, assert `mock_coordinator.call_args.kwargs["base_dir"] == harness_root.resolve()` after implementation normalizes that argument to the resolved `Path`.

Add a second converged test whose canonical spec declares two targets. Assert `land()` is never called and `caplog` contains exactly once:

```text
auto-land skipped for spec 042: aggregate multi-target landing is unsupported (2 targets)
```

Run:

```bash
pytest -q tests/unit/test_run_skill.py -k 'polyrepo_auto_land or multi_target_auto_land'
```

Expected: current code lands from `base_dir` and does not guard multiple targets.

### Step 2: Implement single-target routing and multi-target guard

Extend the existing import to `from harness.spec_frontmatter import find_spec_dir, read_targets`. In the converged auto-merge branch, operate on the already-resolved `spec_dir`:

```python
targets = read_targets(spec_dir) if spec_dir is not None else []
if len(targets) > 1:
    logger.warning(
        "auto-land skipped for spec %s: aggregate multi-target landing is "
        "unsupported (%d targets)",
        intent.spec_id,
        len(targets),
    )
else:
    landed = land(
        intent.spec_id,
        project_dir=workspace_root,
        gitops=gitops,
    )
```

Keep the existing controlled `False` and exception warnings around `land()`. Each target worker logs its own warning once; do not add parent-process deduplication.

### Step 3: Add failing branchless diagnostic tests

Locate the existing direct tests of `_finish_branchless_landing()` in `tests/unit/test_land.py`. Add two cases while reusing their `gitops`, UI capture, and status-update patches:

1. `spec_dir=None` returns `False` and emits:

   ```text
   spec directory for 042 was not found from orchestration root <resolved wrapper_project_dir>
   ```

2. A real spec directory with frontmatter but no `status` returns `False` and retains:

   ```text
   spec status is (missing), not ready_to_land or landed
   ```

The first test must assert the old `(missing)` message is absent, proving the two cases cannot collapse again.

Run:

```bash
pytest -q tests/unit/test_land.py -k 'branchless and (spec_not_found or missing_status)'
```

Expected: the not-found case currently reports `(missing)`.

### Step 4: Implement the branchless diagnostic split

In `_finish_branchless_landing()`, keep the existing status/report reads guarded by `spec_dir is not None`, then make spec absence the first `problem` branch:

```python
problem: str
if spec_dir is None:
    problem = (
        f"spec directory for {spec_id} was not found from orchestration root "
        f"{wrapper_project_dir.resolve()}"
    )
elif status not in {"ready_to_land", "landed"}:
    problem = f"spec status is {status or '(missing)'}, not ready_to_land or landed"
```

Let both branches fall through to the function's existing `LAND - BRANCH NOT LANDED` banner and `False` return. Use `_finish_branchless_landing()`'s existing `wrapper_project_dir` parameter in the message; this is the root supplied to `find_spec_dir()`. Do not reconstruct it from `gitops`. Retain every later provenance/readiness branch unchanged. Do not change branchful legacy behavior when `spec_dir` is absent.

### Step 5: Verify and commit Task 3

```bash
pytest -q tests/unit/test_run_skill.py tests/unit/test_land.py
git add src/harness/skills/run_skill.py src/harness/land.py tests/unit/test_run_skill.py tests/unit/test_land.py
git commit -m "fix: resolve polyrepo auto-land specs from workspace"
```

---

## Task 4: Document, verify, install, and smoke-test without landing

**Files:**

- Modify: `CHANGELOG.md`

### Step 1: Update the changelog

Under the current unreleased `Fixed` section, add one concise entry covering both user-visible defects:

```markdown
- Fixed target-side polyrepo auto-land using the target harness directory for canonical spec discovery, and distinguished an unfound spec directory from a spec whose lifecycle status is missing.
```

Do not update README: the command surface and normal user workflow do not change.

### Step 2: Run the focused regression suite

```bash
pytest -q \
  tests/unit/test_run_skill.py \
  tests/unit/test_resume_skill.py \
  tests/unit/test_harness_main_run_context.py \
  tests/unit/test_cli_harness_run.py \
  tests/unit/test_cli_harness_resume.py \
  tests/unit/test_land.py \
  tests/unit/test_land_cli.py
```

Expected: all selected tests pass.

### Step 3: Run the full suite and install the tested build

```bash
pytest
bash scripts/install.sh
```

Expected: full suite passes and the installer exits 0. If an unrelated pre-existing test fails, record its complete command/output and prove the focused suite still passes before deciding whether it blocks completion.

### Step 4: Snapshot Prosaic before the smoke test

This is a read-only safety check around the known dirty checkout:

```bash
git -C /Users/michalbachorik/work/md_distribution/sources/prosaic rev-parse HEAD
git -C /Users/michalbachorik/work/md_distribution/sources/prosaic status --porcelain=v1
git -C /Users/michalbachorik/work/md_distribution/sources/prosaic diff --binary | shasum -a 256
git -C /Users/michalbachorik/work/md_distribution/sources/prosaic diff --cached --binary | shasum -a 256
```

Save the four outputs in the task transcript; do not write them into the repository.

### Step 5: Smoke-test installed root/spec resolution only

Run the installed Echelon Python, not the source-tree interpreter:

```bash
cd /tmp
/Users/michalbachorik/.echelon/venv/bin/python - <<'PY'
from pathlib import Path

from harness.skills.run_skill import _resolve_run_roots
from harness.spec_frontmatter import find_spec_dir, read_frontmatter

workspace = Path("/Users/michalbachorik/work/md_distribution")
harness = workspace / "runs" / "targets" / "prosaic"
expected = workspace / "specs" / "911-new-prosaic-distribution-feature"

harness_root, workspace_root = _resolve_run_roots(harness, workspace)
spec_dir = find_spec_dir("911", workspace_root)

assert harness_root == harness.resolve()
assert workspace_root == workspace.resolve()
assert spec_dir == expected.resolve()
assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
print(f"resolved {spec_dir} with status ready_to_land")
PY
```

Do not invoke `land()`, `delivery continue`, `delivery resume`, or any command that can mutate branches, lifecycle state, worktrees, or the target checkout.

### Step 6: Prove the Prosaic checkout was untouched

Repeat the four commands from Step 4 and compare byte-for-byte with the saved outputs. HEAD, porcelain status, unstaged diff hash, and staged diff hash must all match.

Also inspect, without changing it:

```bash
git -C /Users/michalbachorik/work/md_distribution/harness/prosaic worktree list --porcelain
```

Record that live landing remains intentionally deferred while the source checkout is dirty and the stale `iter-4` worktree remains registered.

### Step 7: Final repository checks and commit

```bash
git diff --check
git status --short
git add CHANGELOG.md
git commit -m "docs: record polyrepo auto-land context fix"
git status --short
```

Expected: no whitespace errors and no uncommitted files from this implementation. Do not claim the Prosaic spec was landed; report only that installed, non-mutating discovery found the canonical spec with `status: ready_to_land` and left its dirty checkout unchanged.
