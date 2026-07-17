# EGR-151 Python-Owned Phase A Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the terminal Phase A checkpoint commit the complete validated published spec set without allowing an agent to stage, commit, or change branches.

**Architecture:** The squad controller already copies run-local artifacts, writes finalization outputs, generates `ARTIFACTS.md`, and validates readiness before entering a terminal phase. Extend the deterministic checkpoint primitive to add the matching published spec directory to its owned pathspec only for Phase 4 terminal transitions. The Phase 4 workflow then records that Python owns publication and final checkpointing, replacing the legacy shell-finalizer/checkout instruction.

**Tech Stack:** Python 3.11, pytest, local Git subprocess fixtures, Markdown workflow contracts.

## Global Constraints

- Echelon is the sole owner of Phase A Git lifecycle actions.
- Phase A finalization must validate the complete published artifact set before its final checkpoint commit.
- A terminal Phase A checkpoint may commit only the active run-local spec tree and its corresponding published spec tree; unrelated staged, tracked, and untracked changes must remain untouched.
- No Phase 4 agent instruction may stage files, create commits, push, stash, reset, or check out a branch.
- Tests must use local Git and scripted controller results only; no LLM, Docker, or network service is permitted.

---

### Task 1: Add the published spec tree to an owned final checkpoint

**Files:**
- Modify: `src/harness/phase_checkpoints.py:110-205`
- Modify: `src/harness/squad.py:1260-1285`
- Modify: `tests/unit/test_phase_checkpoints.py:100-180`
- Modify: `tests/unit/test_squad_phase_checkpoints.py:1-115`

**Interfaces:**
- Consumes: `create_phase_checkpoint(project_root, spec_dir, phase, next_phase, run_id, spec_id, additional_spec_dirs=())`.
- Produces: a checkpoint commit containing `spec_dir` and every validated `additional_spec_dirs` path, while writing the checkpoint ledger only under `spec_dir`.

- [x] **Step 1: Write the failing real-Git multi-tree checkpoint test**

```python
def test_create_phase_checkpoint_commits_active_and_published_spec_only(tmp_path):
    repo, active = _checkpoint_repo(tmp_path)
    published = repo / "specs" / "001-demo"
    published.mkdir(parents=True)
    (active / "tasks.md").write_text("# Run-local tasks\n", encoding="utf-8")
    (published / "ARTIFACTS.md").write_text("# Artifacts\n", encoding="utf-8")
    (repo / "README.md").write_text("unrelated\n", encoding="utf-8")

    checkpoint = create_phase_checkpoint(
        project_root=repo,
        spec_dir=active,
        phase="phase4-document",
        next_phase="done",
        run_id="spec-run",
        additional_spec_dirs=(published,),
    )

    assert _git(repo, "show", "--format=", "--name-only", checkpoint.commit).splitlines() == [
        "runs/spec-run/specs/001-demo/tasks.md",
        "specs/001-demo/ARTIFACTS.md",
    ]
    assert "README.md" in _git(repo, "status", "--short")
```

- [x] **Step 2: Run the focused test to verify it fails**

Run: `pytest tests/unit/test_phase_checkpoints.py::test_create_phase_checkpoint_commits_active_and_published_spec_only -q`

Expected: FAIL because `create_phase_checkpoint()` does not accept `additional_spec_dirs`.

- [x] **Step 3: Generalize owned pathspec creation and checkpoint commit**

```python
def create_phase_checkpoint(
    *,
    project_root: Path,
    spec_dir: Path,
    phase: str,
    next_phase: str,
    run_id: str,
    spec_id: str = "",
    additional_spec_dirs: tuple[Path, ...] = (),
) -> PhaseCheckpoint:
    commit = _commit_spec_changes(
        project_root,
        (spec_dir, *additional_spec_dirs),
        message,
    )
```

Make `_commit_spec_changes` build an ordered, de-duplicated include/exclude pathspec list from every directory, reject any path outside `project_root`, and use that list consistently for `git add -f -A`, staged-diff detection, and `git commit --only`. Preserve the ledger write under the primary `spec_dir` only.

- [x] **Step 4: Pass the published directory only for a terminal Phase 4 checkpoint**

```python
additional_spec_dirs: tuple[Path, ...] = ()
if phase == "phase4-document" and next_phase in TERMINAL_PHASES:
    published = self._published_phase_a_spec_dir(state, spec_dir)
    if published.exists() and published.resolve() != spec_dir.resolve():
        additional_spec_dirs = (published,)
create_phase_checkpoint(
    project_root=self._project_root,
    spec_dir=spec_dir,
    phase=phase,
    next_phase=next_phase,
    run_id=str(state.get("run_id") or ""),
    spec_id=_checkpoint_spec_id_from_state(state, spec_dir),
    additional_spec_dirs=additional_spec_dirs,
)
```

- [x] **Step 5: Run checkpoint and squad checkpoint tests**

Run: `pytest tests/unit/test_phase_checkpoints.py tests/unit/test_squad_phase_checkpoints.py -q`

Expected: PASS.

- [x] **Step 6: Commit the deterministic final checkpoint**

```bash
git add src/harness/phase_checkpoints.py src/harness/squad.py \
  tests/unit/test_phase_checkpoints.py tests/unit/test_squad_phase_checkpoints.py
git commit -m "fix: commit published artifacts at final checkpoint"
```

### Task 2: Remove agent-owned Phase A Git finalization

**Files:**
- Modify: `extension/workflow/phases/phase4-document.md:445-490`
- Modify: `tests/unit/test_phase_output_paths.py:1-145`
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/superpowers/plans/2026-07-17-egr-151-python-owned-phase-a-finalization.md`

**Interfaces:**
- Consumes: the controller-owned terminal checkpoint introduced in Task 1.
- Produces: a Phase 4 contract that requires no agent Git command and documents sibling new-spec creation through `echelon spec run`.

- [x] **Step 1: Write the workflow contract regression test**

```python
def test_phase4_finalization_keeps_git_under_python_ownership() -> None:
    text = (ROOT / "extension/workflow/phases/phase4-document.md").read_text(encoding="utf-8")
    assert "Python-owned finalization" in text
    assert "finalize-run.sh" not in text
    assert "git checkout" not in text
    assert "sibling branch from the configured default branch" in text
```

- [x] **Step 2: Run the contract test to verify it fails**

Run: `pytest tests/unit/test_phase_output_paths.py::test_phase4_finalization_keeps_git_under_python_ownership -q`

Expected: FAIL because Phase 4 still invokes `finalize-run.sh`, describes branch stacking, and instructs a default-branch checkout.

- [x] **Step 3: Replace the finalizer section with the controller contract**

```markdown
### 12.10 Python-owned finalization — mandatory boundary

The controller publishes the run-local artifacts, validates the complete published spec set, writes `ARTIFACTS.md`, and commits the active/published Phase A trees in its terminal checkpoint. Report the Phase 4 result only; do not call Git, `finalize-run.sh`, or `echelon spec artifacts` from this phase.

### 12.11 Next spec

Start another spec only through `echelon spec run`. Echelon creates its sibling branch from the configured default branch after the active run passes checkpoint and cleanliness validation.
```

- [x] **Step 4: Run finalization controller and workflow contract tests**

Run: `pytest tests/integration/test_squad_controller.py tests/unit/test_phase_output_paths.py -q`

Expected: PASS.

- [x] **Step 5: Update EGR evidence, mark plan complete, and commit**

```bash
git add extension/workflow/phases/phase4-document.md tests/unit/test_phase_output_paths.py \
  docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md \
  docs/findings/echelon-grounded-review-register.md \
  docs/superpowers/plans/2026-07-17-egr-151-python-owned-phase-a-finalization.md
git commit -m "docs: make phase a finalization git-owned"
```
