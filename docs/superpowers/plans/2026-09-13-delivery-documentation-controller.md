# Delivery Documentation Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair missing/invalid delivery documentation through bounded Python-owned author/reviewer dispatch, including when every canonical task is already complete.

**Architecture:** Add a documentation execution helper beneath Ralph, following the existing slice runner and reusing its locked durable journal primitive. TECH WRITER can change only candidate README/CHANGELOG; both roles return their existing Markdown report format as a dispatch-bound response value. Python stages, validates and publishes the two reports only after independent review and deterministic validation pass.

**Tech Stack:** Python, neutral Prosaic roles, existing provider scope metadata, durable JSON, documentation validators and pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-delivery-controller-ownership-design.md`, original phase 4. Release constraints: `docs/element-identity-convergence-boundary.md`.

## Global Constraints

- Keep the controlled path opt-in; support Claude and Codex through the same neutral contract on the accepted macOS host boundary.
- Ralph remains the acceptance/verification owner. No additional COMMANDER, allocator, public command, install, live provider execution, migration, push or default rollout.
- Preserve canonical task IDs and target scope; documentation returns no completed task IDs and cannot authorize source edits.
- Initial authoring plus at most two repairs, persisted before dispatch. No DEGRADED/skip acceptance in any mode. Unknown dispatch completion blocks reconciliation; changed evidence never inherits approval.
- Canonical reports are controller-owned. Candidate edits may remain unaccepted after failure, but rejected reports must not replace canonical reports.
- Preserve existing journal files/schema for implementation slices. A documentation operation uses the same lock/atomic storage mechanics with its own strict validator, not another recovery controller or state pointer.
- Retain legacy prose while the opt-in replacement is being tested. Add focused delivery profiles as already done for implementation/review roles; do not add provider names or invocation-environment conditionals to model prose.
- This checkpoint does not finish native entry/prose migration, default cutover, identity integration, or bundle/live smoke verification.

## Task 1: Durable documentation execution helper

**Files:**
- Create `src/harness/delivery_documentation.py` (dispatch, bounded repair and publication under Ralph).
- Create `src/harness/delivery_documentation_contract.py` if required to keep strict journal/result validation separate from execution.
- Modify `src/harness/delivery_slice_journal.py` only to accept an optional validator, retaining its default implementation-slice validation unchanged.
- Modify `src/harness/durable_json.py` only to share its descriptor-pinned durable replacement with text reports.
- Modify `src/harness/delivery_slice_runner.py` only for a narrowly optional protected-fingerprint exclusion of the two controller-owned report paths, retaining default behavior.
- Create `prosaic/subagents/echelon.delivery-tech-writer.md` and `prosaic/subagents/echelon.delivery-docs-verifier.md`.
- Create `tests/unit/test_delivery_documentation.py` and targeted durable-write regression cases in that file or existing durability tests.

**Interface:**

```python
class DeliveryDocumentationRunner:
    def __init__(self, executor, project_dir: Path): ...
    def run(
        self, *, worktree: Path, spec_dir: Path, evidence_root: Path,
        allowed_task_ids: set[str] | None = None, feedback: str = "",
        changed_files: list[str] | None = None,
        runnability_report: RunnabilityEvidenceRef | None = None,
        runnability_required: bool = False,
        containment_policy_file: str | None = None,
        token_budget: float | None = None, operation_id: str = "active",
        journal_required: bool = False, on_journal_ready=None,
        stop_requested=None,
    ) -> BuildResult: ...
```

Successful results have `task_ids=[]`, cumulative operation token usage and
reason `delivery_documentation_passed`. Failures have status `blocked`; retry
exhaustion reason is `delivery_documentation_repair_limit`. No caller receives
success until both canonical reports have been durably published.

**Dispatch/result contract:** a JSON object with exact assignment fields
`schema_version: 1`, `dispatch_id`, `step` (`tech_writer`/`docs_verifier`),
`task_ids` (actual sorted scope), `candidate_fingerprint`, `input_fingerprint`;
response adds exactly `verdict`, `summary`, `findings`, `report_markdown`.
Writer verdicts: DONE/BLOCKED/NEEDS_CONTEXT; reviewer: PASS/FAIL/BLOCKED.
Passing verdicts require no unresolved findings and a nonempty report. Bound
JSON/report sizes and types; no free-text/legacy marker acceptance.

- [ ] Write consuming tests before implementation. Reuse the existing temporary project and scripted Prosaic inspection boundary; copy the two new role profiles into that fixture's installed bundle. Model-process doubles write only permitted candidate files and return complete result payloads. Assertions exercise the actual runner, files, journal, validators and scope metadata.

```python
def test_rejected_docs_are_repaired_before_publication(documentation_project):
    runner, provider, paths = documentation_project(reject_first=True)
    result = runner.run(**paths)
    assert result.succeeded and result.task_ids == []
    assert provider.steps == ["tech_writer", "docs_verifier"] * 2
    assert provider.canonical_report_snapshots_before_acceptance == [None] * 4
    assert (paths["spec_dir"] / "docs-verification-report.md").is_file()

def test_repeated_rejection_survives_reconstruction(documentation_project):
    runner, provider, paths = documentation_project(always_reject=True)
    first = runner.run(**paths)
    assert first.reason == "delivery_documentation_repair_limit"
    second = type(runner)(provider, runner._project_dir).run(**paths, journal_required=True)
    assert second.reason == first.reason
    assert provider.steps == ["tech_writer", "docs_verifier"] * 3
```

- [ ] Run the tests RED, then implement the same alternating author/review sequence with three total author attempts. No provider work on cancellation, exhausted/tightened budget, unknown usage under a finite budget, unsupported host boundary, invalid scope, missing role, changed source/context or unknown prior completion.
- [ ] Writer tool metadata is exclusive with exactly README.md/CHANGELOG.md writable. Reviewer metadata is exclusive with no writable files. Both prohibit spec/evidence/control writes. Capture specification and verification context in Python; include current runnability evidence without giving providers write access. Required missing/stale runnability evidence blocks rather than generating commands.
- [ ] Preserve existing documentation schemas and detailed first-run/evidence invariants in the new neutral profiles. Profiles never invoke another agent, run the deterministic verifier themselves, write state/journals/canonical reports or prescribe retry/publication routing. The reviewer consumes Python's deterministic baseline and must retain its failures while adding independent source-backed findings.
- [ ] Stage the writer's impact report outside the candidate; run existing deterministic docs verification there. Supply the baseline and staged impact content to the independent reviewer. Validate returned report/frontmatter consistency and call `evaluate_documentation_gate` against the staged pair and real candidate. A semantic PASS cannot override deterministic failure. Carry both kinds of findings into the next author attempt.
- [ ] Bind operation to scope, roles, source/config/spec inputs, source-only candidate content, immutable evidence content and original feedback. Candidate-after receipts include README/CHANGELOG. Only these two candidate paths may change during authoring; reviewer writes or spec/control mutations block. Canonical report before-images are separately guarded, not ignored as writable product files.
- [ ] Reuse `DeliverySliceJournal` locking and atomic storage with a strict documentation validator: exact fields, ordered receipts, bounded attempts, unique dispatches, candidate chain, usage, valid outcomes and publication data. Persist intent before provider entry and completion before the next step. Resume matching receipts only; an unrecorded provider return remains unresolved. Tightened finite ceilings cannot widen on reconstruction.
- [ ] Before canonical publication, persist both exact report after-images and before-images in the journal. Publish each through the existing descriptor-pinned atomic-write mechanics. Recovery may finish a partially published pair only when each current file equals its recorded before/after image; unrelated edits, unsafe paths, changed source/candidate or missing journals block. Never overwrite a report changed by another writer. Keep managed identity exclusion intact; do not enroll or bypass authority guards.
- [ ] Tests must cover happy path, deterministic rejection despite model PASS, persistent three-attempt exhaustion, malformed/mismatched results, source/spec/reviewer mutation, exact native scopes, existing report preservation, internal/external spec paths, unsafe/symlink outputs, cancellation, finite budgets/unknown usage, crash after intent/after completion/between report writes, stale source/evidence and no duplicate usage on runner replay.
- [ ] Run focused runner/durability and existing delivery recovery/provider suites GREEN. Commit only Task 1 files and report test evidence and any limitations for independent review.

## Task 2: Ralph routes documentation repair and owns operation lifecycle

**Files:** `src/harness/ralph.py`, new `tests/unit/test_delivery_documentation_integration.py`, and the existing convergence/design records.

**Consumes:** `DeliveryDocumentationRunner.run` and its cumulative `BuildResult` contract from Task 1.

- [ ] Add integration regressions through actual `_exec_feedback`, `_exec_build` restart and the inner verification loop. Script only external providers/sandbox processes; preserve real docs gate/report validation. Cover completed tasks with no last implementation pointer, repair after an accepted task, unrelated source failure routing, mixed failures, all modes, external specs, unknown pending completion and token accounting after reconstruction.

```python
def test_completed_tasks_docs_failure_routes_writer_not_implementer(completed_project):
    controller, provider, docs_failure = completed_project
    result = controller._exec_feedback(
        None, docs_failure, "echelon build", "",
        worktree_path=str(provider.worktree), prompt="repair documented failure",
    )
    assert result["passed"] and result["task_ids"] == []
    assert provider.steps == ["tech_writer", "docs_verifier"]
    assert controller._apply_documentation_gate(
        VerifyResult(passed=True), str(provider.worktree)
    ).passed
```

- [ ] Route only a nonempty all-documentation failure set to documentation execution; mixed or source failures keep existing implementation repair behavior. Preserve deterministic failure IDs under prefixes `documentation-`, `docs-`, `readme-`, `changelog-`; missing required runnability evidence must block inside the documentation helper.
- [ ] Use the existing `delivery_slice_operation` pointer with `kind="documentation"`; absence of kind remains the existing task operation. A pending documentation operation resumes through `_exec_build` before any new selection. Persist the pointer after the empty journal is durable and before provider intent, as implementation already does. Do not create a parallel state pointer/controller.
- [ ] Existing eligible applied task operations can advance into documentation repair. Repeated documentation feedback against the same pending/accepted documentation operation must not reset its attempt ceiling. A completed documentation operation may advance on the next outer iteration or explicit non-documentation repair; retain the last real implementation task as the source-repair target. Never clear unresolved state or replace an expected journal.
- [ ] Return no completed task IDs, account only the unseen token delta, and preserve the pending candidate on crash. Mark documentation progress only after journaled report publication; existing same-iteration recovery protects the uncommitted checkpoint window. Existing downstream budget plumbing supplies current remaining allowance.
- [ ] `_apply_documentation_gate` must not rewrite controlled independently reviewed canonical reports with a deterministic baseline. It still runs the existing read-only validators and current runnability checks. Keep legacy behavior unchanged when the flag is off.
- [ ] Scope `_enforce_completed_task_ids` so a controller-produced documentation operation can finish with no task IDs even during partial delivery; provider prose cannot claim that exemption. No broader completion-marker fallback or canonical progress change.
- [ ] Run focused new integration tests RED/GREEN, then delivery, Ralph inner/outer, documentation, runnability and provider regressions. Request read-only review; resolve important findings before the checkpoint commit. Record exact evidence and unfinished phase-4/identity work in the existing convergence record.

## Execution and acceptance boundary

This is necessary original delivery convergence, not activation of deferred
identity features. Use the existing isolated worktree. No production defaults,
installation or live-model smoke are authorized. Compatibility limits from
phase 3 remain conservative: genuinely changed source or controller evidence
requires reconciliation instead of stale receipt reuse. Do not claim full
phase-4 completion until the later native entry/prose and bundle milestones.
