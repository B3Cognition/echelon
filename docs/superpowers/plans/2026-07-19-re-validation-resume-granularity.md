# RE Validation Resume Granularity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `echelon re continue` retain completed semantic domain audits and retry only unresolved or invalidated domains.

**Architecture:** Extend the existing RE controller with a versioned per-domain audit cache stored in `re/state.json`. The validation phase derives one pending domain at a time, validates and persists its result, then assembles the unchanged aggregate quality report after all current domain fingerprints have records.

**Tech Stack:** Python 3, pytest, JSON run state, existing `ReExtractionController` and `re_quality_gate` contracts.

## Global Constraints

- Preserve the public `semantic-quality-review.json` schema.
- Preserve legacy active-run compatibility.
- Do not change analysis, initial specification, coverage, checklist, constitution, or publication behavior.
- Use source and staged-spec fingerprints to reject stale records.
- Follow red-green-refactor for every behavior change.

---

### Task 1: Persist and Resume One Domain Audit at a Time

**Files:**
- Modify: `tests/unit/test_re_controller.py`
- Modify: `src/harness/re_controller.py`

**Interfaces:**
- Produces: controller state key `re_semantic_domain_audits`, keyed by `<source-id>/<domain-id>`.
- Produces: `_next_semantic_validation_target(state, plan) -> dict[str, str] | None`.
- Produces: `_semantic_validation_payload(state, plan) -> dict[str, object]`.

- [ ] **Step 1: Write the failing interrupted-dispatch test**

Add a provider that returns a valid PASS for the first requested domain, exits
non-zero on the second, then succeeds after reconstructing the controller. Assert
that the first domain appears in the persisted audit map and is not dispatched
again by the continued controller.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pytest -q tests/unit/test_re_controller.py -k semantic_validation_continue_reuses_completed_domain`

Expected: FAIL because validation still requests every domain in one dispatch and
no `re_semantic_domain_audits` state exists.

- [ ] **Step 3: Implement minimal target selection and persistence**

In `ReExtractionController`, derive canonical source/domain targets from the
execution plan manifests, select the first record without a current audit, add
that target to the validator prompt, validate the one-record response, and store
the record immediately. Remain in `re-extract-5-validate` until no target remains.

- [ ] **Step 4: Run focused and controller tests**

Run: `pytest -q tests/unit/test_re_controller.py -k 'semantic_validation_continue_reuses_completed_domain or semantic_quality'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_controller.py tests/unit/test_re_controller.py
git commit -m "fix: resume RE validation by domain"
```

### Task 2: Fingerprint-Based Selective Invalidation

**Files:**
- Modify: `tests/unit/test_re_controller.py`
- Modify: `src/harness/re_controller.py`

**Interfaces:**
- Produces: `_semantic_target_fingerprints(target, plan) -> tuple[str, str]`.
- Consumes: `re_semantic_domain_audits` from Task 1.

- [ ] **Step 1: Write failing fingerprint tests**

Add tests that seed two current PASS records, modify one staged `spec.md`, and
assert only that domain is dispatched. Add a source-file mutation case and assert
only domains owned by the affected source are invalidated.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/unit/test_re_controller.py -k 'semantic_audit_spec_fingerprint or semantic_audit_source_fingerprint'`

Expected: FAIL because cached records are not fingerprint-aware.

- [ ] **Step 3: Implement deterministic fingerprints**

Compute SHA-256 for the staged domain spec and use the execution plan source
fingerprint for source identity. Save both with each audit and accept a cached
record only when identifiers, fingerprints, and protocol version match.

- [ ] **Step 4: Run focused tests**

Run: `pytest -q tests/unit/test_re_controller.py -k 'semantic_audit_spec_fingerprint or semantic_audit_source_fingerprint or semantic_validation_continue'`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_controller.py tests/unit/test_re_controller.py
git commit -m "fix: invalidate stale RE domain audits"
```

### Task 3: Selective Repair and Aggregate Compatibility

**Files:**
- Modify: `tests/unit/test_re_controller.py`
- Modify: `src/harness/re_controller.py`
- Modify: `extension/workflow/phases/re-extract-5-validate.md`
- Modify: `extension/agents/re/validator.md`

**Interfaces:**
- Consumes: per-domain audit records from Tasks 1 and 2.
- Produces: existing aggregate payload passed to `validate_semantic_quality_review`.

- [ ] **Step 1: Adapt/add failing repair and compatibility tests**

Assert a REPAIR for one domain invalidates only that record, retains PASS siblings
through specification, and writes the existing aggregate report once all domains
are current. Assert legacy state without the audit map validates every domain.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/unit/test_re_controller.py -k 'source_local_semantic_repair or semantic_aggregate or legacy_semantic'`

Expected: FAIL until selective invalidation and aggregation are connected.

- [ ] **Step 3: Implement aggregation and repair invalidation**

Build `{"schema_version": 1, "domains": [...]}` in execution-plan order from
current cached records, feed it through the existing validator, and remove only
records for domains scheduled for semantic repair. Update validator instructions
to require exactly the requested domain rather than every refreshed domain.

- [ ] **Step 4: Run the complete RE controller suite**

Run: `pytest -q tests/unit/test_re_controller.py tests/kernel/test_re_state.py tests/unit/test_re_prompt_output_contracts.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/re_controller.py tests/unit/test_re_controller.py extension/workflow/phases/re-extract-5-validate.md extension/agents/re/validator.md
git commit -m "fix: retain passing RE audits across repair"
```

### Task 4: Final Verification

**Files:**
- Modify only if verification reveals a regression in files already listed.

- [ ] **Step 1: Run formatting and lint checks for changed Python files**

Run: `ruff check src/harness/re_controller.py tests/unit/test_re_controller.py`

Expected: PASS.

- [ ] **Step 2: Run the relevant unit suite**

Run: `pytest -q tests/unit/test_re_controller.py tests/unit/test_cli_re_lifecycle.py tests/kernel/test_re_state.py tests/unit/test_re_prompt_output_contracts.py`

Expected: PASS.

- [ ] **Step 3: Inspect the final diff and state compatibility**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intentional implementation files remain.

