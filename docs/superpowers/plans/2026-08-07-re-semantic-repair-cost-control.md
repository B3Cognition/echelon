# RE Semantic-Preflight Repair Cost Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bound repeated repairs caused solely by semantic-preflight findings, using the execution profile’s existing `max_semantic_repair_rounds` limit.

**Architecture:** A source-domain quality failure can be structural/evidence-related or semantic-preflight-only. Structural failures retain the existing `max_domain_repairs` budget. A failure whose only finding is `unscoped_universal_claim` is routed through the existing repair prompt but uses `max_semantic_repair_rounds`; once exhausted, the source is recorded as partial quality debt and processing continues to the next source.

**Tech Stack:** Python 3.12, pytest, dataclasses, RE target-quality reports, execution profiles.

## Global Constraints

- Do not weaken or remove the `unscoped_universal_claim` quality rule.
- Do not change the meaning of `max_domain_repairs` for missing sections, invalid evidence, missing acceptance cases, or count shortfalls.
- Do not add a second profile or CLI option; use the frozen `max_semantic_repair_rounds` already recorded in `re_execution_profile`.
- Preserve the partial-quality-debt publication path.

---

## File Structure

- `src/harness/re_controller.py` owns target-quality routing, repair limits, partial-debt transitions, and telemetry.
- `src/harness/re_quality_gate.py` supplies `ReQualityReport` and `ReSpecQualityFailure`; it requires no behavior change.
- `src/harness/re_semantic_preflight.py` retains the universal-claim detector unchanged.
- `tests/unit/test_re_controller.py` owns unit and integration regressions for repair budgeting.
- `tests/unit/test_re_profiles.py` protects the built-in profile limits that the controller consumes.

### Task 1: Specify semantic-only target-quality budget selection

**Files:**
- Modify: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_re_controller.py::test_unscoped_universal_claim_uses_semantic_repair_limit`
- Test: `tests/unit/test_re_controller.py::test_structural_target_quality_failure_uses_domain_repair_limit`

**Interfaces:**
- Consumes: `ReQualityReport`, `ReSpecQualityFailure`, `SemanticPreflightFinding`, and `ReExtractionController._semantic_repair_limit(state)`.
- Produces: `ReExtractionController._target_quality_repair_limit(state, report) -> int`.

- [ ] **Step 1: Add the semantic-only report test fixture**

Construct a one-failure report with no missing sections, no invalid evidence, no count shortfall, no `semantic_findings`, and this sole preflight finding:

```python
SemanticPreflightFinding(
    code="unscoped_universal_claim",
    message="FR-001 uses a universal claim without exhaustive evidence scope",
    references=("`src/handler.ts:12`",),
)
```

Use state with:

```python
{
    "re_execution_profile": {
        "name": "balanced",
        "max_semantic_repair_rounds": 1,
    },
    "re_source_budgets": {"max_domain_repairs": 3},
}
```

- [ ] **Step 2: Write the failing limit-selection tests**

```python
assert controller._target_quality_repair_limit(state, semantic_only_report) == 1
assert controller._target_quality_repair_limit(state, structural_report) == 3
```

For `structural_report`, set `missing_sections=("Edge Cases",)` and no semantic-preflight finding.

- [ ] **Step 3: Run the tests and verify the current failure**

Run: `pytest tests/unit/test_re_controller.py -k 'target_quality_repair_limit' -v`

Expected: FAIL because `_target_quality_repair_limit` does not yet exist and all failures currently use `max_domain_repairs`.

- [ ] **Step 4: Commit the failing-test checkpoint**

```bash
git add tests/unit/test_re_controller.py
git commit -m "test: define semantic RE repair budget"
```

### Task 2: Route universal-claim-only failures through the semantic budget

**Files:**
- Modify: `src/harness/re_controller.py:1997-2073`
- Modify: `src/harness/re_controller.py:2172-2291`
- Test: `tests/unit/test_re_controller.py::test_unscoped_universal_claim_uses_semantic_repair_limit`
- Test: `tests/unit/test_re_controller.py::test_structural_target_quality_failure_uses_domain_repair_limit`

**Interfaces:**
- Consumes: `ReQualityReport` from `validate_staged_re_domain_quality()`.
- Produces: `_target_quality_repair_limit(state, report)` and `_is_unscoped_universal_claim_only(failure)` helpers.

- [ ] **Step 1: Implement the narrow failure classifier**

Add a private static helper that returns `True` only if all of the following hold for a `ReSpecQualityFailure`:

```python
bool(failure.semantic_preflight_findings)
and all(item.code == "unscoped_universal_claim" for item in failure.semantic_preflight_findings)
and not failure.missing_sections
and not failure.invalid_source_evidence
and not failure.scenarios_without_acceptance
and not failure.scenarios_without_evidence
and not failure.functional_requirements_without_evidence
and not failure.non_functional_requirements_without_evidence
and not failure.semantic_findings
and failure.scenario_count >= failure.expected_scenario_count
and failure.functional_requirement_count >= failure.expected_functional_requirement_count
and failure.non_functional_requirement_count >= failure.expected_non_functional_requirement_count
```

This keeps malformed Behavior Coverage, missing citations, and every other semantic-preflight category on the established generic repair path.

- [ ] **Step 2: Implement the limit selector**

Add this helper beside `_semantic_repair_limit`:

```python
def _target_quality_repair_limit(
    self, state: dict, report: ReQualityReport
) -> int:
    if report.failures and all(
        self._is_unscoped_universal_claim_only(failure)
        for failure in report.failures
    ):
        return self._semantic_repair_limit(state)
    if self._source_convergence_enabled(state):
        return self._source_budget(state, "max_domain_repairs")
    return self._metric(state, "max_verify_expand_iterations")
```

- [ ] **Step 3: Apply the selected limit in target-quality routing**

In `_evaluate_specification_target`, compute `repair_limit = self._target_quality_repair_limit(state, target_report)` immediately after writing the target report. Pass `repair_limit` to `_report_target_quality_failure`, and compare the source-local `repair_count` to `repair_limit` before calling `_mark_active_source_partial`.

Do not change `re_domain_quality_attempts` accounting; it remains diagnostic history for every target-quality failure.

- [ ] **Step 4: Run the focused tests**

Run: `pytest tests/unit/test_re_controller.py -k 'target_quality_repair_limit or source_local_domain_budget' -v`

Expected: PASS.

- [ ] **Step 5: Commit the controller change**

```bash
git add src/harness/re_controller.py tests/unit/test_re_controller.py
git commit -m "fix: bound universal-claim RE repairs by profile"
```

### Task 3: Prove source progression after semantic retry exhaustion

**Files:**
- Modify: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_re_controller.py::test_semantic_preflight_exhaustion_marks_debt_and_advances_source`
- Test: `tests/unit/test_re_profiles.py::test_builtin_profiles_have_exact_limits`

**Interfaces:**
- Consumes: a balanced profile with `max_semantic_repair_rounds == 1` and a two-source execution plan.
- Produces: a completed controller run where the first source becomes `partial_quality_debt` after one repair, and the second source is dispatched.

- [ ] **Step 1: Write the controller integration regression**

Use `write_valid_re_run(tmp_path, ("api", "worker"))`. Monkeypatch `validate_staged_re_domain_quality` so `api/001-re-domain` returns the semantic-only report from Task 1 on every specification pass, while `worker/001-re-domain` returns `ReQualityReport(passed=True, failures=())`. Configure the inner state with source convergence enabled and:

```python
"re_execution_profile": {
    "name": "balanced",
    "semantic_audit_mode": "all",
    "max_semantic_repair_rounds": 1,
},
"re_source_budgets": {
    "max_source_cycles": 2,
    "max_domain_repairs": 3,
    "max_source_reanalysis": 2,
},
```

Assert exactly two `api` specification dispatches (initial plus one repair), at least one `worker` specification dispatch, and `state["re_source_states"]["api"]["status"] == "partial_quality_debt"`.

- [ ] **Step 2: Run the integration regression**

Run: `pytest tests/unit/test_re_controller.py::test_semantic_preflight_exhaustion_marks_debt_and_advances_source -v`

Expected: PASS.

- [ ] **Step 3: Run profile and controller suites**

Run: `pytest tests/unit/test_re_profiles.py tests/unit/test_re_controller.py -v`

Expected: PASS; the profile matrix remains `fast=0`, `balanced=1`, `high=5` semantic repair rounds.

- [ ] **Step 4: Commit the regression coverage**

```bash
git add tests/unit/test_re_controller.py tests/unit/test_re_profiles.py
git commit -m "test: continue RE after semantic repair debt"
```

### Task 4: Verify installation and operator behavior

**Files:**
- Modify: none unless verification exposes a regression.
- Test: `tests/unit/test_re_lifecycle.py`
- Test: `tests/unit/test_re_controller.py`
- Test: `tests/unit/test_re_profiles.py`

**Interfaces:**
- Consumes: the repaired lifecycle and controller contracts from the preceding plan.
- Produces: a validated development checkout ready for installation before a new OptaSearch RE run.

- [ ] **Step 1: Run the full focused RE suite**

Run: `pytest tests/unit/test_re_lifecycle.py tests/unit/test_re_planner.py tests/unit/test_re_controller.py tests/unit/test_re_profiles.py tests/unit/test_cli_re_lifecycle.py -v`

Expected: PASS.

- [ ] **Step 2: Reinstall the edited CLI**

Run: `bash scripts/install.sh`

Expected: exit code 0; `echelon` on PATH now uses this checkout’s changes.

- [ ] **Step 3: Confirm the intended first retry command before executing it**

Run: `echelon re run --help`

Expected: the output lists `--re-policy`, `--profile`, and `--reset`.

The next operational command is intentionally deferred until tests pass:

```bash
echelon re run --reset --re-policy changed --profile high
```

Use `high` only for the one-time quality-contract refresh; after publishing a complete run, normal incremental runs use `--re-policy changed --profile balanced`.

## Self-Review

- Spec coverage: Task 1 defines the distinction, Task 2 implements it, Task 3 proves it preserves workspace progress, and Task 4 verifies the installed operational path.
- Placeholder scan: every task includes named files, commands, assertions, and implementation code.
- Type consistency: the plan uses existing `ReQualityReport`, `ReSpecQualityFailure`, `SemanticPreflightFinding`, `ReExtractionController`, and profile fields.
