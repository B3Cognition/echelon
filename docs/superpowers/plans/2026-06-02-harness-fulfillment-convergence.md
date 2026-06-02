# Harness Fulfillment Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the harness/Ralph loop iterate until normal verification passes and spec fulfillment verification has no blocking gaps.

**Architecture:** Treat fulfillment gaps as verification failures inside Ralph, not as a separate land-time concern. Add a small pure helper that turns the latest `fulfillment-report.md` into a synthetic `VerifyResult`; call it after sandbox verification passes in both outer and inner loops. Then make `echelon land` block on unresolved fulfillment gaps by default with an explicit override flag.

**Tech Stack:** Python harness code, existing `kernel.fulfillment` parser, pytest, Markdown command prompts.

---

### Task 1: Ralph Fulfillment Gate

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `tests/unit/test_ralph_outer.py`

- [ ] Write failing tests showing Ralph does not converge when sandbox verification passes but `fulfillment-report.md` contains `MISSING`.
- [ ] Implement `_apply_fulfillment_gate()` in `src/harness/ralph.py`.
- [ ] Call the gate after `_exec_verify()` in the outer loop and after re-verify in the inner loop.
- [ ] Verify `tests/unit/test_ralph_outer.py -k fulfillment` passes.
- [ ] Commit `feat: gate harness convergence on fulfillment`.

### Task 2: Land Blocks by Default

**Files:**
- Modify: `src/harness/land.py`
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_land.py`
- Modify: `tests/unit/test_land_cli.py` if present

- [ ] Write failing tests showing land blocks on `MISSING/PARTIAL/DEVIATED`.
- [ ] Add `LandOptions.allow_fulfillment_gaps`.
- [ ] Parse `--allow-fulfillment-gaps` in `echelon land`.
- [ ] Keep `UNVERIFIED` warning-only by default.
- [ ] Commit `feat: block land on fulfillment gaps`.

### Task 3: Docs and Focused Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-02-spec-fulfillment-verification-design.md`

- [ ] Document the harness convergence behavior and land override.
- [ ] Run focused tests for Ralph, land, CLI, fulfillment, prompt refs.
- [ ] Commit `docs: document fulfillment convergence loop`.

## Self-Review

- Spec coverage: covers loop convergence, recovery through gaps, and final land guardrail.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: uses existing `VerifyResult`, `FailureEntry`, `LandOptions`, and `kernel.fulfillment` helpers.
