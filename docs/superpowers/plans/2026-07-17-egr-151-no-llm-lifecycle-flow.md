# EGR-151 No-LLM Lifecycle Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the accepted multi-spec authoring and delivery lifecycle end-to-end with a temporary Git repository and no LLM, Docker, or network service.

**Architecture:** Add one integration-style pytest module that composes existing deterministic Phase A start, checkpoint, switch, and delivery-entrypoint services. It uses a local Git repository and mocks only the delivery runtime boundary, so Git branch, commit, dirt, and active-run pointer observations remain real.

**Tech Stack:** Python 3.11, pytest, unittest.mock, local Git subprocesses.

## Global Constraints

- Do not invoke an LLM CLI, Docker provider, or network service.
- Start every fresh spec through `start_phase_a_spec()` and use real local Git refs.
- Spec B must be a sibling from the recorded `main` commit while A remains non-final but checkpointed.
- Delivery must use requested-spec readiness; it must not change the active B checkout, dirty authoring file, or `runs/.current` pointer.
- An unready requested spec must stop before `harness.skills.run_skill.run`.

---

### Task 1: Add the composed temporary-Git lifecycle regression

**Files:**

- Create: `tests/integration/test_egr_151_lifecycle_flow.py`
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/findings/echelon-grounded-review-register.md`

**Interfaces:**

- Consumes: `start_phase_a_spec(project_root, run_id, description)`, `create_phase_checkpoint(...)`, and `echelon.cli._cmd_harness_run(args)`.
- Produces: `test_checkpointed_nonfinal_a_allows_sibling_b_and_isolated_delivery`, a deterministic regression for the accepted lifecycle.

- [x] **Step 1: Write the failing composed real-Git test**

```python
def test_checkpointed_nonfinal_a_allows_sibling_b_and_isolated_delivery(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path)
    main_commit = _git(repo, "rev-parse", "main^{commit}")
    a = start_phase_a_spec(repo, "run-a", "Spec A")
    _checkpoint_run(repo, a, phase="phase2-plan", next_phase="phase3-review")
    b = start_phase_a_spec(repo, "run-b", "Spec B")
    assert _git(repo, "rev-parse", f"{b.bootstrap.feature_branch}^{{commit}}") == main_commit
    _write_published_artifacts(repo / "specs" / a.bootstrap.spec_id, ready=True)
    (repo / "authoring-note.md").write_text("B remains dirty\\n")
    _run_delivery_with_mocked_runtime(repo, a.bootstrap.spec_id)
    assert _git(repo, "branch", "--show-current") == b.bootstrap.feature_branch
    assert (repo / "runs" / ".current").read_text() == "run-b\\n"
```

Helpers initialise a real `main` repository, configure identity, ignore run-local lifecycle metadata, write canonical Phase A artifact files, and patch only delivery runtime dependencies.

- [x] **Step 2: Run the new test to verify the composition gap**

Run: `pytest tests/integration/test_egr_151_lifecycle_flow.py -q`

Expected: FAIL until the fixture correctly prepares delivery dispatch and confirms the lifecycle assertions.

- [x] **Step 3: Implement only fixture and test wiring for existing services**

Do not modify lifecycle production code unless the composed test proves a real behavioral defect. The test is the deliverable; all external execution boundaries stay mocked.

- [x] **Step 4: Run the lifecycle and adjacent delivery matrix**

Run: `pytest tests/integration/test_egr_151_lifecycle_flow.py tests/unit/test_phase_a_start.py tests/unit/test_spec_switch.py tests/unit/test_cli_harness_run.py -q && git diff --check`

Expected: PASS.

- [x] **Step 5: Record evidence and commit**

Stage the test, this plan, and both EGR records, then commit with message `test: cover no-llm multi-spec lifecycle`.

## Self-Review

- Spec coverage: checkpointed non-final A, sibling B from main, explicit active selection, isolated ready-A delivery, and unready-B delivery refusal.
- Placeholder scan: none; fixture helpers and external boundaries are named explicitly.
- Type consistency: the test invokes the existing Phase A start outcome, checkpoint primitive, and legacy CLI entrypoint without new production interfaces.
