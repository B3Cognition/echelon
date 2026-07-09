# EGR-123 Source-Scoped RE Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add target-aware, source-fingerprint-aware reverse-engineering cache planning so Phase A reuses unchanged source RE artifacts and refreshes only selected changed sources.

**Architecture:** Build deterministic Python primitives first: cache records, policy planning, and run-local materialization. Then wire Phase A CLI/state/executor flow so GOLDDIGGER runs only when the plan contains refresh work, while existing consumers keep reading run-local `runs/<run-id>/re/` paths through `golddigger_artifacts`.

**Tech Stack:** Python 3.11, pytest, existing `echelon.workspace_model`, `harness.squad`, and markdown workflow/agent prompts.

## Global Constraints

- Work on branch `feature/egr-123-source-scoped-re-cache` in `.worktrees/egr-123-source-scoped-re-cache`.
- Preserve the existing run-local RE artifact contract for SCOUT, MODELER, stack detection, and RE agents.
- Materialize cache artifacts by copying, not symlinking, so runs are self-contained and archivable.
- Recompute `cross-repo.json` cheaply during materialization from selected source metadata.
- `target-only` must list excluded sibling roots as forbidden roots without exposing sibling RE content.
- Ordinary `echelon spec run` must not require canonical `specs/NNN-re-*` output from GOLDDIGGER.
- Follow TDD: write each behavior test first, verify it fails, then implement.

---

## File Structure

- Existing `src/harness/re_fingerprint.py`: source fingerprinting, already present on `main`.
- Create `src/harness/re_cache.py`: persistent cache records, cache key paths, cache hit checks, atomic cache writes, run-local copy helpers.
- Create `src/harness/re_planner.py`: resolve `--target`/`--re-policy`, compute per-source actions, write `re-execution-plan.json`.
- Create `src/harness/re_materializer.py`: assemble `runs/<run-id>/re/` compatibility view from cache/source outputs.
- Modify `src/harness/squad_state.py`: persist optional `target_source`, `re_policy`, and `re_execution_plan` fields at initialization.
- Modify `src/echelon/cli.py`: parse Phase A `--target` and `--re-policy`, pass them to `SquadController.run()`.
- Modify `src/harness/squad.py`: accept target/policy and initialize state with them.
- Modify `src/harness/squad_executors.py`: plan/materialize before GOLDDIGGER; skip GOLDDIGGER on cache-only plans; inject forbidden sibling roots for target-only.
- Modify `extension/workflow/definition.yaml`: allow RE planning state keys.
- Modify `extension/agents/exploration/golddigger.md`: accept source-scoped plans and no longer require canonical RE specs for ordinary feature runs.
- Add focused pytest coverage under `tests/unit/` and `tests/kernel/`.

---

### Task 1: Cache Record And Copying Materialization Primitive

**Files:**
- Create: `src/harness/re_cache.py`
- Test: `tests/unit/test_re_cache.py`

**Interfaces:**
- Consumes: `SourceFingerprint` from `harness.re_fingerprint`.
- Produces: `ReCacheRecord`, `cache_source_dir(cache_root, source_id, fingerprint)`, `cache_hit(cache_root, source_id, fingerprint)`, `write_cache_record(source_output_dir, cache_dir, record)`, `copy_cached_source(cache_dir, run_source_dir)`.

- [ ] **Step 1: Write failing tests for cache hit and copied materialization**

Create tests that write a source cache directory containing `analysis.json` and `re-context.md`, assert `cache_hit()` returns false before `manifest.json`, true after `write_cache_record()`, and assert `copy_cached_source()` copies files into a run-local directory without creating symlinks.

- [ ] **Step 2: Run failing tests**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_cache.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'harness.re_cache'`.

- [ ] **Step 3: Implement `re_cache.py`**

Implement dataclass serialization, required artifact checks, atomic manifest write, and recursive copy with `shutil.copy2()`.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_cache.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add source RE cache primitives`.

---

### Task 2: RE Policy Planner

**Files:**
- Create: `src/harness/re_planner.py`
- Test: `tests/unit/test_re_planner.py`

**Interfaces:**
- Consumes: `WorkspaceManifest`, `SourceRoot`, `ReFingerprintProfile`, `fingerprint_source()`, and `re_cache.cache_hit()`.
- Produces: `RePlanSource`, `ReExecutionPlan`, `resolve_re_policy(target_source, requested_policy)`, `build_re_execution_plan(project_root, manifest, cache_root, target_source, requested_policy, profile)`.

- [ ] **Step 1: Write failing policy/default/action tests**

Tests cover default policy resolution, `changed` with three cache hits and one miss, `target-only` selecting only the target and listing siblings as forbidden roots, and `cached-only` never producing refresh actions.

- [ ] **Step 2: Run failing tests**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_planner.py -q`

Expected: FAIL because `harness.re_planner` does not exist.

- [ ] **Step 3: Implement the planner**

Implement policy enum validation, source target resolution by ID or path, per-source fingerprint computation, cache hit lookup, and forbidden sibling root recording.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_planner.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: add target-aware RE planner`.

---

### Task 3: Run-Local RE Materializer

**Files:**
- Create: `src/harness/re_materializer.py`
- Test: `tests/unit/test_re_materializer.py`

**Interfaces:**
- Consumes: `ReExecutionPlan`, cache source dirs, and workspace manifest.
- Produces: `materialize_re_run_view(project_root, run_re_dir, workspace_manifest, plan, cache_root) -> dict[str, object]`.

- [ ] **Step 1: Write failing materializer tests**

Tests assert copied per-source artifacts, `re-source-index.json`, `re-execution-plan.json`, aggregate `analysis.json`, cheap recomputed `cross-repo.json`, and `golddigger_artifacts` with run-local paths.

- [ ] **Step 2: Run failing tests**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_materializer.py -q`

Expected: FAIL because `harness.re_materializer` does not exist.

- [ ] **Step 3: Implement the materializer**

Copy selected cache artifacts into `runs/<run-id>/re/<source-id>/`, write JSON indexes, and render aggregate files from selected per-source `analysis.json` metadata.

- [ ] **Step 4: Verify green**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_materializer.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: materialize run-local RE views`.

---

### Task 4: Phase A CLI And State Wiring

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/unit/test_cli_mode_args.py` or new `tests/unit/test_cli_re_policy.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `SquadController.run(..., target_source: str = "", re_policy: str = "")`.
- State fields: `target_source`, `re_policy`.

- [ ] **Step 1: Write failing CLI/state tests**

Tests assert `echelon spec run --target prosaic` defaults `re_policy` to `target-changed`, explicit `--re-policy refresh-all` is preserved, and missing values are rejected.

- [ ] **Step 2: Run failing tests**

Run focused CLI/state tests.

- [ ] **Step 3: Implement parsing and state plumbing**

Parse `--target`, `--target=<value>`, `--re-policy`, and `--re-policy=<value>` in `_cmd_run()`. Pass values into `SquadController.run()` and `SquadStateStore.initialize()`.

- [ ] **Step 4: Verify green**

Run focused CLI/state tests.

- [ ] **Step 5: Commit**

Commit message: `feat: wire Phase A RE target policy`.

---

### Task 5: Executor Planning And GOLDDIGGER Skip

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/kernel/test_squad_executors_journal.py`

**Interfaces:**
- Consumes: state fields `target_source` and `re_policy`.
- Produces: state fields `re_execution_plan`, `re_source_index`, `golddigger_artifacts`, `golddigger_status`, `golddigger_mode`, `forbidden_source_roots`.

- [ ] **Step 1: Write failing executor tests**

Tests assert all-cache-hit plans skip provider GOLDDIGGER execution and still populate `golddigger_artifacts`; refresh plans invoke GOLDDIGGER; target-only plans populate forbidden sibling roots.

- [ ] **Step 2: Run failing tests**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/kernel/test_squad_executors_journal.py -k "golddigger or re_policy or forbidden" -q`

Expected: FAIL.

- [ ] **Step 3: Implement pre-dispatch planning**

In `_run_pre_dispatch()`, before the `golddigger_mode1` agent dispatch, build the plan and materialize cache-hit artifacts. If no refresh sources remain, write state updates and skip provider execution. If refresh sources exist, include plan paths in the GOLDDIGGER prompt.

- [ ] **Step 4: Verify green**

Run focused executor tests.

- [ ] **Step 5: Commit**

Commit message: `feat: plan RE before GOLDDIGGER dispatch`.

---

### Task 6: GOLDDIGGER Prompt And Docs Contract

**Files:**
- Modify: `extension/agents/exploration/golddigger.md`
- Modify: `docs/re-overview.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Test: `tests/unit/test_re_prompt_output_contracts.py`

**Interfaces:**
- Documents source-scoped refresh plans, run-local compatibility artifacts, and no canonical RE spec publication during ordinary feature runs.

- [ ] **Step 1: Write failing prompt-contract tests**

Tests assert GOLDDIGGER mentions source-scoped refresh plans, run-local compatibility artifacts, and does not require canonical `specs/NNN-re-*` completion for ordinary feature runs.

- [ ] **Step 2: Run failing tests**

Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_re_prompt_output_contracts.py -q`

Expected: FAIL.

- [ ] **Step 3: Update prompts/docs/changelog/register**

Edit GOLDDIGGER and RE docs to match the implemented contract. Add EGR-123 `[Unreleased]` changelog entry and mark EGR-123 fixed with evidence after code is verified.

- [ ] **Step 4: Verify green**

Run prompt-contract and focused RE tests.

- [ ] **Step 5: Commit**

Commit message: `docs: document source-scoped RE cache behavior`.

---

### Task 7: Final Verification

**Files:**
- No new source files.

**Interfaces:**
- Verifies all EGR-123 slices together.

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest \
  tests/unit/test_re_fingerprint.py \
  tests/unit/test_re_cache.py \
  tests/unit/test_re_planner.py \
  tests/unit/test_re_materializer.py \
  tests/unit/test_re_prompt_output_contracts.py \
  tests/kernel/test_squad_executors_journal.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI smoke tests affected by Phase A parsing**

Run:

```bash
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest \
  tests/unit/test_cli_mode_args.py \
  tests/unit/test_cli_continue.py \
  tests/integration/test_squad_controller.py \
  -q
```

Expected: PASS or report pre-existing unrelated failures with exact failing tests.

- [ ] **Step 3: Confirm branch state**

Run:

```bash
git status --short
git log --oneline --decorate -5
```

Expected: clean worktree except intentional user-owned files outside this feature worktree.
