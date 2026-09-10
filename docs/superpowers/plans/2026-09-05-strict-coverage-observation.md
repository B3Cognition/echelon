# Strict Coverage Observation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Fulfill required coverage only when Echelon's sandbox proves the exact planned test case ran and passed for the candidate under judgment.

**Architecture:** Add stack-owned structured coverage observers and normalize their output into an immutable, fingerprint-bound coverage observation. Reconcile that observation with the planning coverage map before judgment, fulfillment, status, and landing. The existing full verifier remains mandatory; isolated observers use fresh sandbox sessions and fresh sidecars so no test depends on database state left by another stage.

**Tech Stack:** Python 3.11, pytest, PyYAML, Echelon stack definitions, sandbox providers, immutable verification receipts, Playwright JSON, Vitest JSON, Markdown coverage contracts.

**Spec:** docs/superpowers/specs/2026-09-05-strict-coverage-observation-design.md

## Global Constraints

- Providers never run the full verifier, provision services, install browsers, or run Docker. Ralph owns authoritative sandbox execution.
- A planning coverage map is a declaration; delivery never rewrites it to manufacture a pass.
- Only an active owner-controlled deferred-scope ledger entry removes a requirement.
- Required coverage needs a passed structured observer result, source identity, and matching product/map/stack/observer-plan/contract fingerprints.
- Aggregate verify success never proves individual coverage cases.
- Browser-3D and browser-WASM initially support e2e through Playwright JSON and unit, integration, and contract through Vitest JSON; future lower-case hyphenated type names require their own adapter.
- Schema 1.2 stack files remain valid. Schema 1.3 alone permits coverage_observers.
- Isolated observers use a fresh sandbox and fresh services. Nothing runs on the user host.
- Artifacts retain redacted bounded diagnostics and digests only.
- Strict receipt validation remains for legacy callers. Equivalent-product carry-forward is opt-in and checks every authoritative content hash.
- Stacks without required observers retain their current delivery behavior.

---

## File and interface map

| File | Responsibility |
| --- | --- |
| src/harness/stacks/schema.py | Validate schema-1.3 observer declarations. |
| src/harness/stacks/resolver.py | Resolve observers, reject conflicts, and hash the plan. |
| src/harness/test_execution_evidence.py | Common normalized test and tag types. |
| src/harness/playwright_evidence.py | Adapt Playwright JSON without breaking visual evidence callers. |
| src/harness/vitest_evidence.py | Adapt Vitest JSON to the common type. |
| src/harness/coverage_contract.py | Normalize planning coverage-map rows into typed case obligations. |
| src/harness/coverage_observation.py | Validate source/tag identity and persist immutable observations. |
| src/harness/coverage_evidence.py | Normalize coverage-map obligations and reconcile observation state. |
| src/harness/coverage_observer_runner.py | Run captured or isolated observers in Ralph sandbox sessions. |
| src/harness/verification_evidence.py | Add a narrow equivalent-product receipt validator. |
| src/harness/ralph.py | Build a verification bundle before fulfillment. |
| src/harness/judgment_prepass.py | Use observed coverage instead of the impossible strong-evidence rule. |
| src/harness/fulfillment_runner.py | Require validated observation across direct, scoped, and full paths. |
| src/harness/land.py | Use equivalent-product validation only for carry-forward. |

## Task 1: Add stack observer schema and resolution

**Files:**
- Modify: src/harness/stacks/schema.py
- Modify: src/harness/stacks/resolver.py
- Modify: src/harness/stacks/renderer.py
- Test: tests/unit/test_stacks_schema.py
- Test: tests/unit/test_stacks_resolver.py

**Interfaces:**
- StackCoverageObserver(id, test_types, command, report_path, adapter, mode, required)
- ResolvedCoverageObserver(owner_stack_id, observer)
- resolved_coverage_observer_plan_sha256(resolved) returns a stable hash.
- adapter accepts only playwright-json or vitest-json. mode accepts only captured or isolated.

- [ ] **Step 1: Write schema failure tests**

  Add tests proving schema 1.2 rejects coverage_observers and schema 1.3 rejects duplicate ids, empty test_types, unsupported type, empty command, absolute or parent-traversing report_path, unsupported adapter, and unsupported mode.

  ~~~python
  raw = {**VALID_STACK, "coverage_observers": [{"id": "pw"}]}
  with pytest.raises(StackValidationError, match="schema_version 1.3"):
      parse_stack_definition(raw, Path("stack.yml"))
  ~~~

- [ ] **Step 2: Run schema tests red**

  Run: python -m pytest -q tests/unit/test_stacks_schema.py -k coverage_observer

  Expected: FAIL because coverage observer support does not exist.

- [ ] **Step 3: Implement strict parsing**

  Add the frozen StackCoverageObserver dataclass and coverage_observers field to StackDefinition. Permit the new root key only in schema version 1.3. Validate unique lower-case hyphenated test-type names, without hard-coding the initial browser vocabulary. Preserve every schema-1.0 through 1.2 parse path unchanged.

- [ ] **Step 4: Write resolver conflict tests**

  Add a pair of selected stacks that both require e2e and assert StackConflictError contains coverage observer and e2e. Add order-stable plan-hash and empty-schema-1.2 observer cases.

- [ ] **Step 5: Implement resolver and renderer**

  Resolve observers in deterministic stack order. Reject two required observers owning one type. Hash owner id, observer id, types, command, adapter, report path, mode, and required flag. Render a compact Coverage Observers section; redact command text using existing verification redaction.

- [ ] **Step 6: Run focused tests green**

  Run: python -m pytest -q tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py

  Expected: PASS.

- [ ] **Step 7: Commit**

  ~~~bash
  git add src/harness/stacks/schema.py src/harness/stacks/resolver.py src/harness/stacks/renderer.py tests/unit/test_stacks_schema.py tests/unit/test_stacks_resolver.py
  git commit -m "feat: add stack coverage observers"
  ~~~

## Task 2: Normalize runner output and logical test tags

**Files:**
- Create: src/harness/test_execution_evidence.py
- Create: src/harness/vitest_evidence.py
- Modify: src/harness/playwright_evidence.py
- Test: tests/unit/test_test_execution_evidence.py
- Test: tests/unit/test_vitest_evidence.py
- Modify: tests/unit/test_playwright_evidence.py

**Interfaces:**
- ObservedTestExecution(observer_id, test_type, file, title, project, status, retry_count, error)
- PhysicalTestIdentity(observer_id, file, title)
- parse_echelon_case_tags(title) returns ordered unique case ids.
- parse_vitest_json(stdout, observer_id, test_type) returns normalized executions.

- [ ] **Step 1: Write tag-parser tests**

  Test a single tag, several tags, case-insensitive echelon label, no tag, duplicate id, empty id, malformed comma, and a tag not at the end of the title.

  ~~~python
  assert parse_echelon_case_tags("journey [echelon:E2E-001, UT-002]") == ("E2E-001", "UT-002")
  with pytest.raises(TestExecutionEvidenceError, match="must end"):
      parse_echelon_case_tags("[echelon:E2E-001] journey")
  ~~~

- [ ] **Step 2: Run tag tests red**

  Run: python -m pytest -q tests/unit/test_test_execution_evidence.py

  Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement common types**

  Create the frozen data types and parser. A physical identity excludes retry, shard, and browser project. Retain each project result separately, so one source test can run in Chromium and WebKit without becoming a duplicate.

- [ ] **Step 4: Write adapter fixtures**

  Add Vitest JSON with passed, skipped, failed, and retried assertion results. Extend Playwright fixtures with two projects for one file/title and a failed first retry followed by a final pass. Assert final status, project, file, title, and retry count.

- [ ] **Step 5: Implement adapters**

  Add Vitest parsing that rejects malformed JSON, missing result arrays, zero executed tests, absolute paths, and parent paths. Add a conversion function in playwright_evidence.py that leaves existing parse_playwright_json counts unchanged.

- [ ] **Step 6: Run adapter tests green**

  Run: python -m pytest -q tests/unit/test_test_execution_evidence.py tests/unit/test_vitest_evidence.py tests/unit/test_playwright_evidence.py

  Expected: PASS.

- [ ] **Step 7: Commit**

  ~~~bash
  git add src/harness/test_execution_evidence.py src/harness/vitest_evidence.py src/harness/playwright_evidence.py tests/unit/test_test_execution_evidence.py tests/unit/test_vitest_evidence.py tests/unit/test_playwright_evidence.py
  git commit -m "feat: normalize coverage test execution"
  ~~~

## Task 3: Normalize coverage contracts and persist immutable observations

**Files:**
- Create: src/harness/coverage_contract.py
- Create: src/harness/coverage_observation.py
- Test: tests/unit/test_coverage_contract.py
- Modify: src/harness/verification_evidence.py
- Test: tests/unit/test_coverage_observation.py
- Modify: tests/unit/test_verification_evidence.py

**Interfaces:**
- CoverageObligation(requirement_id, test_case_id, test_type, automation_status, coverage_status, evidence, gap_action)
- parse_coverage_obligations(requirement_cell, test_case_cell, test_type_cell, automation_status, coverage_status, evidence, gap_action, canonical_ids) returns typed obligations only for canonical requirements.
- CoverageObservationRef(path, receipt_sha256, observation_sha256, candidate_fingerprint, passed)
- write_coverage_observation(...)
- validate_coverage_observation(...)
- validate_equivalent_product_receipt(ref, candidate_fingerprint)

- [ ] **Step 1: Write planning-contract and observation tests**

  In tests/unit/test_coverage_contract.py, write the semicolon/type-pair contract regression first.

  ~~~python
  obligations = parse_coverage_obligations("AC-001 / FR-001", "UT-001; E2E-001", "unit/e2e", "deferred-automation", "deferred-automation", "oracle", "repair", {"AC-001", "FR-001"})
  assert {(item.requirement_id, item.test_case_id, item.test_type) for item in obligations} == {
      ("AC-001", "UT-001", "unit"), ("AC-001", "E2E-001", "e2e"),
      ("FR-001", "UT-001", "unit"), ("FR-001", "E2E-001", "e2e"),
  }
  ~~~

  In tests/unit/test_coverage_observation.py, build these planned obligations, executions, and a passing verification receipt. Assert an observed requirement passes. Add unbound, duplicate physical identity, tagged skipped result, failed project, missing source tag, map drift, plan drift, and symlinked latest-pointer tests.

  ~~~python
  assert result.test_cases["E2E-001"].status == "passed"
  assert result.requirements["FR-001"].status == "observed"
  ~~~

- [ ] **Step 2: Run contract and observation tests red**

  Run: python -m pytest -q tests/unit/test_coverage_contract.py tests/unit/test_coverage_observation.py

  Expected: FAIL because neither module exists.

- [ ] **Step 3: Implement the typed planning contract**

  Create coverage_contract.py with CoverageObligation and parse_coverage_obligations. Split canonical requirements on comma/slash and test cases on comma/slash/semicolon. Preserve Automation Status and Coverage Type independently. One test type applies to every case; otherwise pair types positionally. Reject invalid type syntax, type/case cardinality mismatch, and an identical case id declared with incompatible types. Do not decide whether a selected stack supports a syntactically valid type; Phase A does that.

- [ ] **Step 4: Implement evidence builder**

  Define write_coverage_observation with explicit candidate commit/fingerprint, map hash, resolved stack hash, observer plan hash, contract hash, full verifier receipt, observer receipts, obligations, executions, and candidate worktree. Read only relative candidate test files; verify the tagged title and store a source SHA-256. Group by physical identity, require one source identity per case, and require every final project result to pass.

- [ ] **Step 5: Make persistence safe**

  Use exclusive create, symlink checks, digest-bound latest pointer, and numbered attempt paths modeled on verification receipts. Write JSON plus Markdown summary. Keep only identifiers, relative paths, statuses, hashes, and redacted bounded diagnostics.

- [ ] **Step 6: Add narrow carry-forward tests**

  Prove strict validate_verification_receipt still rejects a new commit. Prove validate_equivalent_product_receipt accepts only a passed untampered receipt with the same candidate fingerprint.

  
- [ ] **Step 7: Run focused tests green**

  Run: python -m pytest -q tests/unit/test_coverage_contract.py tests/unit/test_coverage_observation.py tests/unit/test_verification_evidence.py

  Expected: PASS.

- [ ] **Step 8: Commit**

  ~~~bash
  git add src/harness/coverage_contract.py src/harness/coverage_observation.py src/harness/verification_evidence.py tests/unit/test_coverage_contract.py tests/unit/test_coverage_observation.py tests/unit/test_verification_evidence.py
  git commit -m "feat: record coverage observations"
  ~~~

## Task 4: Normalize and reconcile the coverage map

**Files:**
- Modify: src/harness/coverage_evidence.py
- Modify: src/harness/__main__.py
- Modify: tests/unit/test_coverage_evidence.py
- Modify: tests/unit/test_harness_main_fulfillment_artifacts.py

**Interfaces:**
- coverage-evidence schema version 2 holds declaration and observation state.
- write_coverage_evidence accepts observation and observer_required inputs.

- [ ] **Step 1: Write reconciliation tests**

  Use CoverageObligation values produced by Task 3 and test that a valid observation overlays a deferred declaration as observed, while unbound, skipped, failed, missing observer, invalid report, and provenance mismatch stay blocking. Include an active owner deferral that remains owner_deferred.

  ~~~python
  assert result.by_requirement["FR-001"].status == "observed"
  assert result.by_requirement["FR-002"].status == "unbound"
  ~~~

- [ ] **Step 2: Run coverage tests red**

  Run: python -m pytest -q tests/unit/test_coverage_evidence.py

  Expected: FAIL because observation reconciliation does not exist.

- [ ] **Step 3: Wire the typed planning contract**

  Replace local opaque CoverageEvidenceRow parsing with coverage_contract.parse_coverage_obligations. Keep coverage-map table discovery and canonical requirement filtering in coverage_evidence.py. A syntactically valid type with no selected observer is reported by Phase A rather than treated as malformed here.

- [ ] **Step 4: Implement schema-version-2 reconciliation**

  For observer-required stacks, neither automated nor deferred-automation declaration alone passes. Overlay valid observed or owner_deferred states. Keep named unbound, skipped, failed, observer_missing, invalid_report, and provenance_mismatch states. Update completed-task integrity gaps to include logical case ids and reasons.

- [ ] **Step 5: Extend the harness command**

  Extend write-coverage-evidence with explicit observation path and observer-required parameters. Test that observer-required invocation without valid observation exits nonzero and does not write a ready state.

- [ ] **Step 6: Run focused tests green**

  Run: python -m pytest -q tests/unit/test_coverage_evidence.py tests/unit/test_harness_main_fulfillment_artifacts.py

  Expected: PASS.

- [ ] **Step 7: Commit**

  ~~~bash
  git add src/harness/coverage_evidence.py src/harness/__main__.py tests/unit/test_coverage_evidence.py tests/unit/test_harness_main_fulfillment_artifacts.py
  git commit -m "feat: reconcile observed coverage"
  ~~~

## Task 5: Run coverage observers in fresh Ralph-owned sandboxes

**Files:**
- Create: src/harness/coverage_observer_runner.py
- Modify: src/harness/ralph.py
- Modify: src/harness/verification_plan.py
- Test: tests/unit/test_coverage_observer_runner.py
- Modify: tests/unit/test_ralph_outer.py
- Modify: tests/integration/test_ralph_controller.py

**Interfaces:**
- CoverageObserverRun(observer_id, receipt, executions, status, reason)
- CoverageVerificationBundle(standard_receipt, observer_runs, observation)
- run_coverage_observers(...) returns a bundle.

- [ ] **Step 1: Write isolation tests**

  Use a fake provider to prove isolated execution creates/destroys its own session, starts fresh services, has different materialized PostgreSQL credentials, and never calls a host executor. Add captured mode proving it creates no extra session.

  ~~~python
  assert provider.created_session_ids == ["standard", "observer-playwright"]
  assert provider.host_exec_calls == []
  ~~~

- [ ] **Step 2: Run runner tests red**

  Run: python -m pytest -q tests/unit/test_coverage_observer_runner.py

  Expected: FAIL because the runner does not exist.

- [ ] **Step 3: Implement captured and isolated modes**

  Captured mode accepts only a structured report retained by the matching successful standard receipt. Isolated mode creates a new provider handle, calls build_verification_plan and materialize_services, runs normal bootstrap, executes only the trusted observer command, writes a redacted receipt, parses its configured adapter, and always destroys the handle.

- [ ] **Step 4: Attach the bundle in Ralph**

  Resolve the workspace-owned stack observer plan after the candidate worktree is repaired and its runnability contract reloads. After standard sandbox verification passes, run observers, write observation, and attach its reference to VerifyResult evidence. Return named coverage-observer failures without routing the provider to solve a host environment problem.

- [ ] **Step 5: Add Ralph regressions**

  Assert repair prompts still forbid full provider verification. Assert passing standard verification plus unbound coverage cannot converge, while matching observed coverage reaches fulfillment.

- [ ] **Step 6: Run sandbox tests green**

  Run: python -m pytest -q tests/unit/test_coverage_observer_runner.py tests/unit/test_ralph_outer.py tests/integration/test_ralph_controller.py

  Expected: PASS.

- [ ] **Step 7: Commit**

  ~~~bash
  git add src/harness/coverage_observer_runner.py src/harness/ralph.py src/harness/verification_plan.py tests/unit/test_coverage_observer_runner.py tests/unit/test_ralph_outer.py tests/integration/test_ralph_controller.py
  git commit -m "feat: verify coverage in sandbox"
  ~~~

## Task 6: Require the bundle in fulfillment and landing

**Files:**
- Modify: src/harness/judgment_prepass.py
- Modify: src/harness/fulfillment_runner.py
- Modify: src/harness/__main__.py
- Modify: src/harness/land.py
- Modify: runtime/workflow/phases/verify-spec-4-map.md
- Modify: tests/unit/test_judgment_prepass.py
- Modify: tests/unit/test_fulfillment_runner.py
- Modify: tests/unit/test_cli_fulfillment_commands.py
- Modify: tests/unit/test_land.py

**Interfaces:**
- write_judgment_prepass accepts coverage_observation and observer_required.
- coverage_observed_passed is the only deferred-coverage promotion reason.
- All refresh paths call one validated observation helper before judgment.

- [ ] **Step 1: Replace the deadlock regression**

  Rewrite the deferred-coverage test with source_and_test medium, confidence high, runtime false, and a valid observation. Assert IMPLEMENTED with coverage_observed_passed. Add the same implementation map without observation and assert UNVERIFIED.

- [ ] **Step 2: Run pre-pass tests red**

  Run: python -m pytest -q tests/unit/test_judgment_prepass.py

  Expected: FAIL because current promotion depends on strong and regenerates declaration-only evidence.

- [ ] **Step 3: Implement one shared fulfillment sequence**

  All direct, scoped, and full paths must reload candidate runnability, validate standard/observer receipts, validate coverage observation, reconcile coverage, then execute pre-pass and semantic fulfillment. If an observer is required but evidence is absent or stale, return an actionable coverage integrity gap; never use declaration-only coverage in that path.

- [ ] **Step 4: Preserve semantic judgment**

  Put the coverage oracle, tagged source file/title, project outcomes, and observation hashes in the fulfillment prompt. Observation proves execution, not semantics. Existing semantic review may reject an unrelated or empty test.

- [ ] **Step 5: Make landing equivalence narrow**

  Use validate_equivalent_product_receipt only in landing carry-forward. Keep legacy callers strict. Test merge-only SHA carry-forward succeeds only when product/map/stack/observer-plan/contract hashes match; all drift, failed receipts, and tampering fail.

- [ ] **Step 6: Update verify-spec workflow**

  Replace the categorical deferred/strong prohibition with the observation rule. Make workflow call the shared evidence sequence before judgment.

- [ ] **Step 7: Run fulfillment tests green**

  Run: python -m pytest -q tests/unit/test_judgment_prepass.py tests/unit/test_fulfillment_runner.py tests/unit/test_cli_fulfillment_commands.py tests/unit/test_land.py

  Expected: PASS.

- [ ] **Step 8: Commit**

  ~~~bash
  git add src/harness/judgment_prepass.py src/harness/fulfillment_runner.py src/harness/__main__.py src/harness/land.py runtime/workflow/phases/verify-spec-4-map.md tests/unit/test_judgment_prepass.py tests/unit/test_fulfillment_runner.py tests/unit/test_cli_fulfillment_commands.py tests/unit/test_land.py
  git commit -m "feat: require observed coverage for fulfillment"
  ~~~

## Task 7: Activate browser stacks and Phase A checks

**Files:**
- Modify: runtime/stacks/browser-3d-game/stack.yml
- Modify: runtime/stacks/browser-wasm-game/stack.yml
- Modify: src/harness/stacks/preflight.py
- Modify: src/harness/stacks/context.py
- Modify: src/echelon/cli.py
- Test: tests/unit/test_stacks_preflight.py
- Modify: tests/unit/test_cli_stack.py
- Modify: tests/unit/test_cli_fulfillment_commands.py

**Interfaces:**
- Both browser stacks declare playwright-e2e for e2e and vitest-core for unit/integration/contract.
- Preflight reports coverage_observer_unavailable before delivery for unsupported types.
- Delivery status reports observed counts, observer counts, and fingerprint tuple state.

- [ ] **Step 1: Write Phase A capability tests**

  Create a coverage map with rust-unit and assert preflight error code coverage_observer_unavailable names rust-unit. Add unit/e2e coverage for the same stack and assert no error.

- [ ] **Step 2: Run preflight tests red**

  Run: python -m pytest -q tests/unit/test_stacks_preflight.py

  Expected: FAIL because preflight does not evaluate coverage test types.

- [ ] **Step 3: Declare browser observer plans**

  Upgrade the browser stack YAML files to schema 1.3. Add isolated observer commands that emit JSON under .echelon/coverage-reports. Keep the iOS stack's runner as macos_simulator and add no observer because the current Linux runner cannot verify it.

- [ ] **Step 4: Implement preflight, stack context, and status**

  Normalize Phase A coverage types with the Task 4 parser. A missing observer produces coverage_observer_unavailable with type and stack names. For a selected iOS stack, render coverage_observer_unavailable: macos_simulator_required rather than claiming observation. Add test coverage for both messages. Render observer requirements in stack context. Add this delivery summary section.

  ~~~text
  coverage   <observed> / <required> requirements observed
  observers  <id>: <passed>/<total> passed
  evidence   product + map + stack + observer-plan + contract match
  ~~~

- [ ] **Step 5: Run stack and CLI tests green**

  Run: python -m pytest -q tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py tests/unit/test_cli_fulfillment_commands.py

  Expected: PASS.

- [ ] **Step 6: Commit**

  ~~~bash
  git add runtime/stacks/browser-3d-game/stack.yml runtime/stacks/browser-wasm-game/stack.yml src/harness/stacks/preflight.py src/harness/stacks/context.py src/echelon/cli.py tests/unit/test_stacks_preflight.py tests/unit/test_cli_stack.py tests/unit/test_cli_fulfillment_commands.py
  git commit -m "feat: require browser coverage observers"
  ~~~

## Task 8: Prove convergence, document it, and validate the demo

**Files:**
- Modify: tests/integration/test_polyrepo_delivery_convergence.py
- Modify: tests/e2e/test_ralph_convergence.py
- Modify: README.md
- Modify: CHANGELOG.md
- Modify: pyproject.toml
- Modify: src/echelon/cli.py
- Modify: uv.lock
- Validation workspace: /Users/michalbachorik/work/browser-3d-game-stack-smoke

- [ ] **Step 1: Write end-to-end fixtures**

  Add one browser fixture where deferred planned cases have matching structured results and one where aggregate verify succeeds but one logical case is unbound. The first converges. The second is a named repairable coverage gap, never outer_cap, blocker_escalation, or a host prerequisite.

- [ ] **Step 2: Run integration tests red**

  Run: python -m pytest -q tests/integration/test_polyrepo_delivery_convergence.py tests/e2e/test_ralph_convergence.py

  Expected: the new assertions fail before their implementation wiring is complete.

- [ ] **Step 3: Run the full focused regression suite**

  Run:
  ~~~bash
  python -m pytest -q \
    tests/unit/test_stacks_schema.py \
    tests/unit/test_stacks_resolver.py \
    tests/unit/test_test_execution_evidence.py \
    tests/unit/test_vitest_evidence.py \
    tests/unit/test_playwright_evidence.py \
    tests/unit/test_coverage_observation.py \
    tests/unit/test_coverage_evidence.py \
    tests/unit/test_verification_evidence.py \
    tests/unit/test_coverage_observer_runner.py \
    tests/unit/test_judgment_prepass.py \
    tests/unit/test_fulfillment_runner.py \
    tests/unit/test_land.py \
    tests/integration/test_ralph_controller.py \
    tests/integration/test_polyrepo_delivery_convergence.py \
    tests/e2e/test_ralph_convergence.py
  ~~~

  Expected: PASS with no host-execution failure.

- [ ] **Step 4: Update documentation and version**

  Document the exact title syntax [echelon:CASE-ID], supported adapters, evidence location, and sandbox-vs-local journey boundary. Bump the patch version consistently in pyproject.toml, src/echelon/cli.py, README.md, CHANGELOG.md, and uv.lock using the current release pattern.

- [ ] **Step 5: Install and check the CLI**

  ~~~bash
  /Users/michalbachorik/.echelon/venv/bin/python -m pip install -e .
  echelon --version
  ~~~

  Expected: installed CLI shows the bumped version.

- [ ] **Step 6: Validate with the browser-3D smoke workspace**

  Use the CLI’s one displayed recovery command in /Users/michalbachorik/work/browser-3d-game-stack-smoke. Let Echelon add or repair tagged tests, then verify browser/database commands execute only in sandbox. Inspect final receipts and observation hashes before landing. Do not hand-edit planning coverage artifacts or user-host dependencies.

- [ ] **Step 7: Commit documentation and regression fixtures**

  ~~~bash
  git add tests/integration/test_polyrepo_delivery_convergence.py tests/e2e/test_ralph_convergence.py README.md CHANGELOG.md pyproject.toml src/echelon/cli.py uv.lock
  git commit -m "docs: explain coverage observation"
  ~~~
