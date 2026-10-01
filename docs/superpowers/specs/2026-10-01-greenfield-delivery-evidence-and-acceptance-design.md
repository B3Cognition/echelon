# Greenfield Delivery evidence identity and full-flow acceptance

## Purpose

Make a new Echelon Spec-to-Delivery run reach final acceptance without confusing a settled failed documentation dispatch with a pending one, racing a continuation, or deadlocking documentation review on a report that the controller has not yet published. This is a targeted correction to the existing single-Delivery-controller flow, not a replacement evidence store or another orchestration framework.

The user-approved finish line is one uninterrupted fresh-workspace Spec publication → Delivery run → final verification, using ordinary Echelon commands and the agents' own product edits. Focused tests must prove each boundary before that run. Do not edit generated product files or Delivery state by hand, weaken independent reviews, reset a run to conceal a failure, or call a passing intermediate gate convergence.

## Current evidence and failure boundaries

The current [terminal documentation handoff design](2026-10-01-terminal-documentation-handoff-design.md) and its implementation proved the intended ordinary admission path: a native run selected retained candidate `da8b016b581e` and inherited only checkpoint-backed T-001/T-002. The fresh run `build-20261001-160800-775151` then blocked in documentation. Its durable sequence was writer `DONE`, verifier `FAIL`, writer `NEEDS_CONTEXT`; a runnability checkpoint was complete and runnable, but documentation publication and final verification did not occur.

Review of the handoff implementation reproduced two independent safety gaps:

1. The documentation journal does not store its Delivery operation ID. Copying its internally valid bytes to another operation's derived path, then changing the state pointer, can make the handoff helper grant the copied identity.
2. The helper checks the old state's PID lock only once. Another continuation can acquire that lock afterward while fresh admission is still running. The journal lock cannot exclude the old controller after the fresh marker is reserved.

The documentation failure is a separate stage of the same user-visible flow. The writer must return the impact report as `report_markdown` and may edit only README/CHANGELOG; Echelon stages that text and publishes the canonical Spec report only after successful independent review. In the observed run, the reviewer treated absence of that not-yet-published canonical file as a current defect, and the writer treated the requested file write as forbidden. Genuine report-content and README findings still require repair; only the publication-order confusion is wrong.

## Scope and invariant boundaries

- Keep the existing Delivery state, task-slice journals, browser receipts, Git checkpoint lineage, runnability evidence, verification evidence, and report-publication transaction. Do not bulk-rewrite or migrate their formats.
- Change only new controlled **documentation** journals by adding an immutable operation identity. New journals may use a versioned additive field; old documentation journal versions remain readable for their existing replay semantics only where supported, but cannot authorize the new terminal handoff. Historical runs are not migrated.
- Keep `proven_amended_task_ids` pure: only accepted checkpoint commits grant task credit. A documentation handoff grants neither task completion nor successful documentation review.
- Add a target-local native execution lease for the single controller path. It coordinates fresh admission and continuation; it is not a new persisted run state or CLI recovery rule.
- Correct the documentation writer/reviewer context at the existing staged-report boundary. Reviewer independence, deterministic findings, source evidence checks, and final verification remain mandatory.
- The old disposable `004-smoke` runs cannot be used as proof of the new greenfield format. Preserve them as diagnostic evidence; do not retrofit them.

## Design

### 1. Exact operation provenance in new documentation journals

At the controlled documentation operation's first journal creation, Ralph supplies an exact binding containing `build_id`, the Delivery state's `run_id`, `spec_id`, and `delivery_slice_operation.id`. The documentation runner writes this binding before provider dispatch and never changes it. Its strict journal validator checks the new schema and field shapes; resume and any handoff proof additionally compare all four values with the current controller state and derived journal path. The journal's existing input, source, candidate, receipt-chain, token-usage, and publication validation remains in force.

A new controlled operation must not resume a journal lacking this binding or accept one whose binding differs. A copied journal under another operation or build path therefore fails before fresh admission or provider dispatch. A terminal-looking legacy journal with no binding cannot be upgraded by reading `delivery.json.bak`, inferring identity from a directory name, or writing a sidecar after the fact. Exact provenance is local state consistency, not a claim of tamper-proof cryptographic signing against an actor allowed to rewrite all local evidence.

The terminal handoff helper continues to require blocked state, final terminal receipt with known usage, exact reason, clean retained Git HEAD, matching candidate and source fingerprints, and checkpoint ancestry. It adds the new journal binding check and fails closed for old versions. It never mutates the old state, journal, candidate, or canonical reports.

### 2. One shared target-local native execution lease

The existing native fresh, resume, and continue paths all enter `run_skill._execute_delivery_run`. Acquire one OS-released, nonblocking lease under that target's harness root **before** reading the prior baseline or admitting a handoff; retain it through new-build reservation and the controller's terminal return or exception. A competing command for the same target receives a clear contention result without dispatching a provider or advancing the current-build marker. Separate targets remain independent. Process death releases the lease, after which normal state/journal recovery rules still apply.

Keep the existing `StateStore` per-build PID lock and `DeliverySliceJournal` per-operation file lock for their current jobs. Neither is treated as cross-build exclusion. The handoff helper's one-time PID check can remain a diagnostic rejection of an already-live old run, but the target lease is the authority preventing a new continuation from entering between that check and fresh admission. Direct unit calls to the helper do not themselves reserve a build.

Use one existing native entry boundary rather than adding special cases to the CLI service or Ralph. Verify that every supported native `run`, `resume`, and `continue` path reaches this lease before implementation; if any bypass exists, route it through the same boundary before relying on the lease.

### 3. Documentation review of staged, not-yet-published reports

The controller already stages the writer's `report_markdown` and passes its text to the independent verifier. Make that stage explicit in the controller-captured review context: the impact report is present as text for review, while the canonical Spec file is intentionally absent until successful publication. Label the earlier verification failure as historical repair context, not current proof that the staged report is missing. The writer's repair assignment must continue to forbid direct writes to the Spec directory and instruct it to correct the returned `report_markdown` when report content is defective.

The verifier may still `FAIL` on invalid frontmatter, unsupported claims, missing source evidence, incomplete README/CHANGELOG, stale runnability, or other current defects. It must not demand that the writer create the canonical report before the controller's publication step. Do not suppress deterministic findings automatically or translate an agent `FAIL` into `PASS`; make current evidence and publication order unambiguous so ordinary bounded repair can proceed.

### 4. Stepwise verification and whole-flow gate

First, write reproductions and prove each correction separately:

1. A copied terminal journal, wrong build/run/spec/operation binding, unbound legacy journal, pending/error receipt, or changed retained candidate cannot authorize handoff. A genuine new-format terminal receipt can. No documentation verdict grants checkpoint credit.
2. Two native commands targeting the same harness root cannot overlap admission and continuation. Exercise the race at the previous check-to-marker window, contention before marker creation, exception release, and process-death release. Different targets are unaffected.
3. A staged impact report is independently reviewed as content before canonical publication. Historical `documentation-impact-report-missing` feedback does not cause a demand for a forbidden file write; a genuinely malformed report still fails and enters bounded repair. Only a passing review publishes the exact returned reports.

Run focused suites after each correction, then relevant integration/recovery suites. Record the existing unrelated canonical-Spec fixture failure separately rather than claiming the full repository suite passes.

Finally, create a **new disposable workspace** with a normal stack selection and publish a small Spec through Echelon. Run Delivery natively without manually editing product code or state. Inspect durable receipts for task selection/checkpoints, current runnability, independent documentation author and verifier, canonical report publication, final verification, and terminal `converged` status. One passing task, runnability journey, or documentation receipt is insufficient. If the first new reproducible harness failure occurs, stop the run, preserve evidence, diagnose that boundary, and test its correction before another native attempt; do not stack speculative patches or weaken gates.

## Alternatives not chosen

- Rebuild every evidence type under a new store: broadens risk and does not address the observed publication-order confusion.
- Infer missing operation identity from state backups or copied journal location: can accidentally authorize substituted receipts and makes recovery depend on incidental backup contents.
- Add a second PID-lock check or hold only the journal lock through marker reservation: neither excludes an old controller after marker release.
- Auto-clear the documentation verifier's missing-file finding: hides genuine report defects and weakens independent review.
- Reuse the old blocked workspace as the sole end-to-end gate: its journals predate the new identity contract and cannot prove the greenfield path.

## Completion criteria

This milestone is complete only when the new journal identity and shared lease pass their race/substitution regressions, the staged-report repair path passes without a forbidden write, and a fresh native Spec→Delivery run reaches final convergence with durable task, runnability, documentation, and verification evidence. Until then, describe the tested boundary reached—not "Delivery fixed."
