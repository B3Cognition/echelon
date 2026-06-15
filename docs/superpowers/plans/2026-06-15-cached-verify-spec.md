# Cached Verify-Spec Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Avoid rerunning full LLM-backed verify-spec when the latest fulfillment report is already valid for the current commit and spec inputs.

**Architecture:** Keep the cache decision inside `FulfillmentRunner`, because it owns verify-spec execution and report stamping. Ralph receives a structured refresh result so it can distinguish refreshed, cached, missing-skill, and failed outcomes without duplicating cache logic.

**Tech Stack:** Python 3.11, pytest, existing fulfillment metadata helpers, git CLI commit lookup.

---

### Task 1: Structured Fulfillment Refresh Result

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Test: `tests/unit/test_fulfillment_runner.py`

- [x] Add tests that assert `refresh()` returns a result object with `status`, `exit_code`, and `used_cache` for successful refresh and missing skill.
- [x] Implement `FulfillmentRefreshResult`.
- [x] Keep backward compatibility for callers by updating Ralph in Task 3.
- [x] Run `pytest tests/unit/test_fulfillment_runner.py -q`.

### Task 2: Full Verify-Spec Cache Metadata

**Files:**
- Modify: `src/harness/fulfillment_runner.py`
- Test: `tests/unit/test_fulfillment_runner.py`

- [x] Add tests for cache hit, spec input change, commit change, missing metadata, and invalid report validation.
- [x] Compute deterministic `spec_input_hash` from known scope input files.
- [x] Stamp reports with `verify_scope=full`, `spec_input_hash`, and `verify_cache_key`.
- [x] Skip provider execution only when metadata, commit, spec input hash, and report validation all match.
- [x] Run `pytest tests/unit/test_fulfillment_runner.py -q`.

### Task 3: Ralph Accepts Cached Refresh

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

- [x] Add a Ralph test proving cached refresh is accepted as fulfillment-refresh success.
- [x] Update Ralph to consume `FulfillmentRefreshResult`.
- [x] Preserve existing failure behavior for nonzero exit codes.
- [x] Run `pytest tests/unit/test_ralph_outer.py -q`.

### Task 4: Verify Focused and Fast Suites

**Files:**
- No production changes expected.

- [x] Run `pytest tests/unit/test_fulfillment_runner.py tests/unit/test_ralph_outer.py -q`.
- [x] Run `pytest tests/unit -q`.
