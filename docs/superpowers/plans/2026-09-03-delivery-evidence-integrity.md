# Delivery Evidence Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local run instructions complete for authenticated persistent applications and prevent skipped, deferred, or artifact-free browser tests from satisfying delivery fulfillment.

**Architecture:** Extend the existing runnability contract and documentation gate for local session setup and consumer-boundary probes. Add deterministic coverage-map and Playwright evidence parsing, then feed those controller-owned facts into existing task-progress, visual, and fulfillment decisions rather than creating a second delivery system.

**Tech Stack:** Python 3.11, PyYAML, pytest, existing sandbox providers, Playwright JSON, Markdown coverage contracts.

**Spec:** `docs/superpowers/specs/2026-09-03-delivery-evidence-integrity-design.md`

## Global Constraints

- Never execute candidate local-journey commands on the user's host.
- Candidate source and Markdown are claims; only harness execution and immutable receipts are evidence.
- Preserve existing schema-version-1 contracts unless selected stack obligations require new fields.
- Preserve owner-controlled `deferred-scope.json` as the only deferral authority.
- Do not remove, rename, or bypass existing verification, runnability, fulfillment, or CLI behavior.
- Keep the pre-existing `gitops.py` worktree-cleanup repair out of evidence-integrity commits.

---

### Task 1: Validate local session setup and service-boundary probes

**Files:**
- Modify: `src/harness/runnability_contract.py`
- Modify: `src/harness/runnability_runner.py`
- Modify: `src/harness/runnability_evidence.py`
- Test: `tests/unit/test_runnability_contract.py`
- Test: `tests/unit/test_runnability_runner.py`
- Test: `tests/unit/test_runnability_evidence.py`

**Interfaces:**
- Produces: `LocalBoundaryProbe(id: str, service: str, command: str)`
- Produces: `LocalUserJourney.session_commands: tuple[str, ...]`
- Produces: `LocalUserJourney.boundary_probes: tuple[LocalBoundaryProbe, ...]`
- Consumes: `PrimaryJourney.real_services_required`, `RunnabilityContract.identity`, and `PrimaryJourney.session_storage`

- [ ] Write contract tests proving identity-backed local journeys reject missing `session_commands`, required real services reject missing/duplicate/unknown probes, and unaffected contracts still load.
- [ ] Run `pytest -q tests/unit/test_runnability_contract.py` and confirm the new tests fail because the fields are unknown or unenforced.
- [ ] Add the immutable dataclass fields and strict YAML parsing while preserving existing field behavior.
- [ ] Run the contract suite and confirm it passes.
- [ ] Write runner/evidence tests proving missing local obligations produce stable failure classes and serialized commands include sessions and probes in lifecycle order.
- [ ] Run `pytest -q tests/unit/test_runnability_runner.py tests/unit/test_runnability_evidence.py` and confirm the tests fail for the missing fields/evidence.
- [ ] Add deterministic obligation checks and evidence serialization without executing local commands.
- [ ] Run all three focused suites and confirm they pass.

### Task 2: Require exact documentation for the executable local journey

**Files:**
- Modify: `src/harness/docs_verifier.py`
- Modify: `prosaic/subagents/echelon.tech-writer.md`
- Modify: `prosaic/subagents/echelon.docs-verifier.md`
- Modify: `runtime/workflow/phases/build-8-document.md`
- Test: `tests/unit/test_documentation_gate.py`
- Test: `tests/unit/test_stack_context_prompt.py`

**Interfaces:**
- Consumes: runnability evidence `local_journey.commands.session` and `local_journey.boundary_probes`
- Produces: deterministic README findings for omitted session setup, omitted host-boundary probes, and misleading verification claims

- [ ] Write documentation tests for an identity-backed README without session setup and for an internal-only Compose readiness command without the declared consumer-boundary probe.
- [ ] Run `pytest -q tests/unit/test_documentation_gate.py` and confirm both tests fail because the verifier currently accepts the README.
- [ ] Extend exact command parity and reporting to session commands and boundary probes.
- [ ] Update existing writer/verifier instructions to explain sandbox-equivalent versus host-unverified evidence.
- [ ] Run documentation and stack-context tests and confirm they pass.

### Task 3: Parse coverage obligations deterministically

**Files:**
- Create: `src/harness/coverage_evidence.py`
- Create: `tests/unit/test_coverage_evidence.py`
- Modify: `src/harness/__main__.py`

**Interfaces:**
- Produces: `CoverageEvidenceRow(requirement_ids, test_case_ids, test_type, automation_status, coverage_type, evidence, gap_action)`
- Produces: `build_coverage_evidence(spec_dir: Path, canonical_ids: Iterable[str], deferred_ids: set[str]) -> CoverageEvidenceResult`
- Produces: JSON/Markdown evidence artifacts in the verify-spec run directory

- [ ] Write parser tests using the existing coverage-map template, multi-ID/range cells, `automated`, `deferred-automation`, `escalate`, missing rows, and malformed contradictions.
- [ ] Run `pytest -q tests/unit/test_coverage_evidence.py` and confirm import failure.
- [ ] Implement the strict table parser, requirement normalization, status aggregation, and active-deferral exception.
- [ ] Run the parser suite and confirm it passes.
- [ ] Write a CLI test for `python -m harness write-coverage-evidence ...` and confirm the missing command fails.
- [ ] Add the bounded CLI entry point and verify it writes deterministic JSON and Markdown.
- [ ] Run the parser suite again and confirm it passes.

### Task 4: Fail task progress and fulfillment closed on contrary coverage

**Files:**
- Modify: `src/harness/judgment_prepass.py`
- Modify: `src/harness/fulfillment_runner.py`
- Modify: `src/harness/progress_reconciliation.py`
- Modify: `runtime/workflow/phases/verify-spec-4-map.md`
- Modify: `runtime/workflow/phases/verify-spec-5-judge.md`
- Test: `tests/unit/test_judgment_prepass.py`
- Test: `tests/unit/test_fulfillment_runner.py`
- Test: `tests/unit/test_progress_reconciliation.py`

**Interfaces:**
- Consumes: coverage-evidence JSON keyed by canonical requirement ID
- Produces: pre-pass reason codes `coverage_deferred`, `coverage_escalated`, `coverage_missing`, and `coverage_contradictory`
- Produces: actionable completed-task evidence-integrity gaps

- [x] Write judgment tests proving planning-time `deferred-automation` becomes `IMPLEMENTED` only with strong/high source-and-test evidence, while weak/runtime-threshold evidence remains `UNVERIFIED`.
- [ ] Run the judgment test and confirm it fails with `source_and_test_strong`.
- [ ] Make the judgment pre-pass consult deterministic coverage evidence before implementation-map labels.
- [ ] Run judgment tests and confirm they pass.
- [ ] Write fulfillment-runner tests proving coverage evidence is always generated before judgment and malformed/missing required evidence fails closed.
- [ ] Run the focused fulfillment tests and confirm failure.
- [ ] Wire coverage generation through direct, full, and scoped verify paths and include the artifact in prompt context.
- [ ] Write progress tests proving a completed task mapped to deferred/missing required coverage becomes an actionable integrity gap while an active owner deferral remains valid.
- [ ] Implement the task-to-coverage reconciliation and run all focused suites.

### Task 5: Normalize Playwright execution results

**Files:**
- Create: `src/harness/playwright_evidence.py`
- Create: `tests/unit/test_playwright_evidence.py`
- Modify: `src/harness/visual_ralph.py`
- Test: `tests/unit/test_visual_ralph.py`

**Interfaces:**
- Produces: `PlaywrightEvidence(total: int, passed: int, failed: int, skipped: int, tests: tuple[PlaywrightTestEvidence, ...])`
- Produces: `parse_playwright_json(stdout: str) -> PlaywrightEvidence`
- Consumes: owner-controlled deferred requirement/test IDs where configured by the caller

- [ ] Write tests for malformed JSON, zero tests, all skipped, mixed passed/skipped, failed/timed-out, and fully passing reports.
- [ ] Run `pytest -q tests/unit/test_playwright_evidence.py` and confirm import failure.
- [ ] Implement the recursive normalized parser without depending on process exit status.
- [ ] Run the parser tests and confirm they pass.
- [ ] Replace the private visual parser with the normalized parser and write controller tests proving exit zero with zero/skipped tests blocks.
- [ ] Run `pytest -q tests/unit/test_visual_ralph.py tests/unit/test_playwright_evidence.py` and confirm pass.

### Task 6: Retain fingerprint-bound visual artifacts

**Files:**
- Create: `src/harness/visual_evidence.py`
- Create: `tests/unit/test_visual_evidence.py`
- Modify: `src/harness/visual_ralph.py`
- Modify: `src/harness/coordinator.py`
- Modify: `src/harness/delivery_results.py`
- Modify: `src/harness/state.py`
- Test: `tests/unit/test_visual_ralph.py`
- Test: `tests/unit/test_coordinator.py`

**Interfaces:**
- Produces: immutable `VisualEvidenceRef` with candidate fingerprint, Playwright counts, retained artifact paths/digests, and receipt digest
- Consumes: `VisualTestsConfig.screenshot_dir`, registered candidate worktree, build/spec/strategy identity
- Produces: `VisualResult.evidence` and persisted delivery-state visual evidence

- [ ] Write evidence tests for exclusive receipt creation, digest validation, candidate mismatch, missing artifacts, and a required visual gate with zero screenshots.
- [ ] Run `pytest -q tests/unit/test_visual_evidence.py` and confirm import failure.
- [ ] Implement immutable receipt writing/validation following `verification_evidence.py` and `runnability_evidence.py` patterns.
- [ ] Run the evidence suite and confirm it passes.
- [ ] Write visual-runner tests proving successful runs retrieve and retain screenshots outside temporary directories, while a required gate without screenshots blocks.
- [ ] Run focused tests and confirm failure.
- [ ] Pass build/evidence identity into `VisualRalphController`, retain artifacts on success and failure, attach the receipt to `VisualResult`, and persist it through coordinator state.
- [ ] Run visual/coordinator suites and confirm they pass.

### Task 7: Surface evidence integrity and preserve autonomous repair

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/harness/provider_attempt_summary.py`
- Test: `tests/unit/test_ralph_outer.py`
- Test: `tests/unit/test_cli_delivery_status.py`
- Test: `tests/unit/test_provider_attempt_summary.py`

**Interfaces:**
- Consumes: coverage/task integrity failures, Playwright counts, and visual evidence receipt
- Produces: delivery repair context with concrete task/requirement/test IDs
- Produces: status fields for sandbox journey, local journey, Playwright counts, and visual artifact count

- [ ] Write Ralph tests proving evidence-integrity failures return targeted repair feedback and do not request user adjudication.
- [ ] Run the Ralph tests and confirm failure.
- [ ] Route deterministic evidence failures through the existing outer repair loop.
- [ ] Write CLI/summary tests for the distinct evidence statuses and autonomous next action.
- [ ] Add concise presentation fields and run the focused reporting suites.

### Task 8: Regression verification and demo proof

**Files:**
- Modify only through Echelon delivery: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/sources/browser-3d-game`
- Observe: `/Users/michalbachorik/work/browser-3d-game-stack-smoke/specs/003-create-browser-first-3d`

**Interfaces:**
- Consumes: installed Echelon with all preceding evidence-integrity changes
- Produces: a new delivery run that cannot converge until the demo has a complete local session journey, host-boundary PostgreSQL probe, executed five-step Playwright test, updated automated coverage, and retained visual artifacts

- [ ] Run all focused Echelon suites from Tasks 1-7.
- [ ] Run `pytest -q tests/unit` and record exact pass/fail/skip counts.
- [ ] Run `bash tests/run-all.sh` and separate genuine new failures from pre-existing failures by exact test identity.
- [ ] Inspect `git diff --stat`, `git diff --check`, and deleted-file status for accidental removals.
- [ ] Install the verified Echelon build using the repository's existing installation path.
- [ ] Start or resume a demo delivery without hand-editing its product/spec artifacts.
- [ ] Confirm the first run rejects the known deferred/skipped/missing-session state with concrete autonomous repair feedback.
- [x] Require stack-owned user runnability before fulfillment refresh and force visual validation for required browser-DOM stacks.
- [ ] Let Echelon repair and rerun until it either converges with bound evidence or reports a genuine external blocker.
- [ ] From the landed demo checkout, execute the documented local user journey and confirm the authenticated Three.js scene and PostgreSQL persistence path from the user's boundary.
