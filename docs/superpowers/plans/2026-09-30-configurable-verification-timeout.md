# Configurable Delivery Verification Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an authoritative Delivery verify command run longer than the current hard-coded 600 seconds when the workspace explicitly requests it, without relaxing candidate immutability or test gates.

**Architecture:** Add a bounded `verification.command_timeout_ms` setting to the existing harness verification configuration. Use it only for the authoritative verify command and its one browser-runtime retry; leave bootstrap and all other stage timeouts unchanged. The disposable acceptance workspace can opt into 1,800,000 ms for its five-repeat browser suite.

**Tech Stack:** Python, pytest, existing `HarnessConfig` and `CandidateEvidenceRunner`.

**Spec:** The failed authoritative receipt at `/Users/michalbachorik/work/echelon_r/echelon-acceptance-hygiene.h0fKgr/workspace/runs/targets/demo/runs/build-20260929-223936-678430/evidence/verification/attempt-0003-ac40ffffb499.json` records `Process timed out after 600000ms` while the published task requires the five-repeat browser gate.

## Global Constraints

- Do not edit the generated demo manually or waive its independent reviews, candidate fingerprint check, or five-repeat browser requirement.
- Keep the default at 600,000 ms; accept explicit integer overrides from 60,000 through 3,600,000 ms and reject booleans/non-integers.
- Keep sandbox bootstrap at 600,000 ms; only the authoritative verify command and its browser retry consume the new setting.
- Test the setting with fake sandbox execution; do not run the full repository suite for this focused harness change.

## Review Focus

- An omitted setting still uses 600,000 ms.
- A boolean, string, zero, or out-of-range value cannot silently change the timeout.
- The configured timeout reaches both the first verify command and the browser retry.
- Bootstrap keeps its existing timeout.
- Receipt validation and candidate immutability remain unchanged.

---

### Task 1: Bound and apply the authoritative verify timeout

**Files:**
- Modify: `src/harness/config.py` (`VerificationConfig`, `_parse_verification`)
- Modify: `src/harness/candidate_evidence.py` (`CandidateEvidenceRunner.run_standard`)
- Test: `tests/unit/test_config.py`
- Create: `tests/unit/test_candidate_evidence_timeout.py`

**Interfaces:**
- Consumes: `HarnessConfig.verification.execution` and `SandboxProvider.exec(..., timeout_ms: int)`.
- Produces: `HarnessConfig.verification.command_timeout_ms: int`, default `600_000`.

- [x] **Step 1: Write failing config tests.** Assert default `600_000`, accepted `1_800_000`, and `ValidationError` for `True`, `"1800000"`, `59_999`, and `3_600_001` with field path `verification.command_timeout_ms`.
- [x] **Step 2: Run config tests to verify failure.** Run `uv run --extra dev pytest tests/unit/test_config.py -q -k verification_command_timeout`; expected: failure because the field is not parsed.
- [x] **Step 3: Write failing runner tests.** With a fake provider and no bootstrap, assert `run_standard` passes `1_800_000` on both a normal verify and one browser-runtime retry; with a bootstrap plan, assert bootstrap remains `600_000`.
- [x] **Step 4: Run runner tests to verify failure.** Run `uv run --extra dev pytest tests/unit/test_candidate_evidence_timeout.py -q`; expected: the verify calls still use `600_000`.
- [x] **Step 5: Implement the minimal code.** Validate the new config field with `type(value) is int` and inclusive bounds, then pass `config.verification.command_timeout_ms` to the two authoritative verify `exec` calls only.
- [x] **Step 6: Run focused tests.** Run `uv run --extra dev pytest tests/unit/test_config.py tests/unit/test_candidate_evidence_timeout.py -q`; expected: pass.
- [x] **Step 7: Commit.** Commit the code, tests, config template, and plan with message `Make authoritative delivery verify timeout configurable`.
