# Provider Finalization / Workspace Acceptance Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the unverified provider-finalization work and the operational Delivery fixes with one repository-bound checkpoint and one clean end-to-end workspace acceptance run.

**Architecture:** Treat `62a43bdfe655705594b32c5354e7ad8b232dc746` as the last repository-verified baseline. Freeze S6/S7 and all unrelated behavior, finish the already-running Delivery smoke, then validate one newly initialized Phase A-to-Delivery workspace against the installed final candidate. Only after the candidate stops changing do the complete repository gates, record the receipt, close tracking, and push `main`.

**Tech Stack:** Python 3.11, pytest, Git, Echelon CLI, Prosaic/runtime bundle, npm/Vitest for the smoke target.

**Spec:** `docs/superpowers/specs/2026-09-26-provider-dispatch-finalization-design.md`; milestone authority is `docs/simplification-control.md`

## Global Constraints

- S6 and S7 remain parked; this milestone adds no RE protocol or compatibility refactor.
- Support only newly initialized current-version runs; do not migrate historical state.
- `pending_spec_step` remains the only durable authority for incomplete Phase A work.
- Fix one observed failure at a time and verify its regression before resuming the smoke.
- Do not override Commander, reviewer, or fulfillment decisions and do not fabricate receipts.
- Full-repository verification binds the final unchanged candidate, not an intermediate head.
- Push only after the exact final candidate has a recorded receipt and clean range review.

## Review Focus

- A transient provider failure must resume its durable operation without reclassifying a genuine owner-decision blocker.
- Provider output publication must reject stale or unauthorized artifacts while preserving legitimate domain-blocked results.
- A resumed Delivery run must retain its latest safe product checkpoint and not consume a task twice.
- A fresh installed bundle must complete Phase A publication without relying on state from the existing smoke workspace.
- The final receipt must name the exact commit and tree that are pushed.

## Starting Evidence

| Boundary | Evidence at activation |
| --- | --- |
| Last repository-verified candidate | `62a43bdfe655705594b32c5354e7ad8b232dc746` |
| Provider implementation tasks 1–6 | `cfbff48b`, `455338ad`, `622b40a1`, `4041f5d1`, `6050583e`, `eb2e50b5` |
| Provider review and dry-run corrections | `ceb6ead1`, `da06d973` |
| Operational fixes found by workspace execution | 15 commits from `17e8a0bb` through `91fbe33e` |
| Open acceptance evidence | current-head unit gate, complete suite, install/dry-run, full-range review, repository receipt, clean greenfield workspace run |

---

### Task 1: Establish the Stabilization Control Boundary

**Files:**
- Create: `docs/superpowers/plans/2026-09-27-provider-finalization-workspace-acceptance.md`
- Modify: `docs/simplification-control.md`

**Interfaces:**
- Consumes: verified baseline `62a43bdfe655705594b32c5354e7ad8b232dc746`.
- Produces: one active `STAB-1` milestone and an explicit freeze on S6/S7.

- [ ] Record `STAB-1` as the sole active milestone and link this plan.
- [ ] Record the six provider implementation commits and the still-open acceptance gates.
- [ ] Run `git diff --check` and verify exactly the two tracking documents changed.
- [ ] Commit with `docs: track provider workspace stabilization`.

### Task 2: Finish the Existing Delivery Smoke

**Files:**
- Existing workspace: `/Users/michalbachorik/work/echelon_r/echelon-threejs-scope-smoke.u7k6gi`
- Echelon fixes, only if a reproduced harness failure requires them: `src/echelon/`, `src/harness/`, and the directly covering tests.
- Product fixes, only through the Delivery controller: `sources/rugby-demo/` and its run worktree.

**Interfaces:**
- Consumes: Echelon commit `91fbe33e` and the preserved T-009 Delivery operation.
- Produces: accepted T-009 through T-012, completed sandbox verification, and final Delivery/fulfillment evidence.

- [ ] Install the current Echelon checkout with `bash scripts/bash/install.sh`.
- [ ] Resume with `echelon delivery continue 001` from the existing workspace.
- [ ] For each blocker, preserve the run, identify whether the fault is Echelon or the product, and fix only the reproduced fault using RED→GREEN tests.
- [ ] Continue until all 12 tasks and final Delivery/fulfillment gates complete, or record an external blocker that cannot be repaired in-repo.
- [ ] Commit every Echelon regression fix independently; retain product commits through the Delivery checkpoint protocol.

### Task 3: Run a Clean End-to-End Workspace Acceptance

**Files:**
- Create at runtime: `/Users/michalbachorik/work/echelon_r/echelon-threejs-final-smoke.XXXXXX`
- Do not copy `runs/`, `specs/`, `.echelon/`, or product Git history from the existing smoke workspace.

**Interfaces:**
- Consumes: the installed candidate produced by Task 2.
- Produces: a greenfield Phase A specification, published artifacts, one exercised resume, and completed Delivery for the rugby-pitch demo prompt.

- [ ] Create a new workspace and a new Git-backed target repository with `mktemp -d` and `git init`.
- [ ] Initialize Echelon from the installed bundle; configure the same available providers and host verification used by the existing smoke.
- [ ] Run Phase A for: `simple three.js demo with shaders rendering rugby pitch, have sun shine through clouds and camera flying over pitch`.
- [ ] After a durable Phase A or Delivery checkpoint, stop once and resume through the documented command; do not edit state by hand.
- [ ] Run Delivery through publication, sandbox verification, fulfillment, and final status.
- [ ] Fix only reproduced Echelon defects one at a time with RED→GREEN coverage, reinstall, and restart the fresh acceptance from a newly initialized workspace when a fix invalidates earlier evidence.

### Task 4: Verify the Final Unchanged Candidate

**Files:**
- Verify: repository production, tests, runtime bundle, and the full `62a43bdf..HEAD` range.
- Create: one merge-verification receipt under `tests/reports/merge-verification/`.

**Interfaces:**
- Consumes: the unchanged candidate that passed Task 3.
- Produces: focused provider evidence, unit and complete-suite evidence, install/dry-run evidence, and a commit/tree-bound receipt.

- [ ] Run `git diff --check 62a43bdf..HEAD` and the stale-authority search from the provider-finalization plan.
- [ ] Run the provider-finalization focused suites named in Tasks 1–6 of `2026-09-26-provider-dispatch-finalization.md`.
- [ ] Run `.venv/bin/python -m pytest -m unit`.
- [ ] Run `.venv/bin/python -m pytest`.
- [ ] Run `bash scripts/bash/dry-run.sh` and `bash scripts/bash/install.sh`.
- [ ] Run `python scripts/merge_verification.py run --base 62a43bdf` and retain the generated receipt.
- [ ] Review `git log`, `git diff --stat`, and `git diff --check` for `62a43bdf..HEAD`.

### Task 5: Close Tracking Against the Verified Commit

**Files:**
- Modify: `docs/superpowers/plans/2026-09-26-provider-dispatch-finalization.md`
- Modify: `docs/superpowers/plans/2026-09-27-provider-finalization-workspace-acceptance.md`
- Modify: `docs/simplification-control.md`

**Interfaces:**
- Consumes: the exact receipt, final commit, tree, smoke paths, and outcomes from Tasks 2–4.
- Produces: closed provider-finalization and `STAB-1` records while leaving S6/S7 pending.

- [ ] Add a closure evidence table mapping the six provider implementation tasks to their commits and final verification.
- [ ] Mark only gates supported by recorded evidence complete.
- [ ] Mark `STAB-1` done with the exact commit/tree/receipt and workspace acceptance outcome.
- [ ] Confirm the tracker still identifies S6 as next but inactive.
- [ ] Commit with `docs: close provider workspace stabilization`.

### Task 6: Final Review and Push

**Files:**
- Review-only: `62a43bdf..HEAD` plus the stabilization ledger and recorded receipts.

**Interfaces:**
- Consumes: all completed milestone evidence.
- Produces: one reviewed and pushed stabilization checkpoint.

- [ ] Request one fresh whole-range code review with the review focus above.
- [ ] Resolve Critical/Important findings one at a time with RED→GREEN tests; record or defer Minor findings explicitly.
- [ ] Re-run affected gates and the repository receipt if review fixes change the candidate.
- [ ] Verify `git status --short` is empty and the receipt binds `HEAD` and its tree.
- [ ] Push `main` to `origin` and verify the remote-tracking ref equals `HEAD`.

## Completion Contract

This milestone is complete only when Tasks 1–6 are checked, both workspace runs have recorded outcomes, the exact pushed commit/tree has passing final gates and a repository receipt, `main` is clean, and S6/S7 remain pending.
