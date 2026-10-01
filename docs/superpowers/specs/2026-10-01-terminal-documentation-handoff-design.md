# Terminal documentation handoff at amended Delivery admission

## Intent and scope

Let a fresh Delivery budget reuse checkpoint-proven task progress and a clean retained candidate after an earlier documentation operation ended with a recorded `BLOCKED` or `NEEDS_CONTEXT` verdict. The new run must perform fresh documentation review and final verification. This is a generic Echelon recovery rule, not a repair to a generated product or a one-off migration of run state.

The existing [published-Spec amendment design](2026-10-01-published-spec-runnability-plan-amendment-design.md) forbids skipping pending or unknown dispatches. That remains the default. A completed, terminal documentation verdict is a settled failure, not a pending dispatch or an accepted documentation result. Only a proof of that distinction permits this handoff.

Admission does not rewrite generated product files, old Delivery state, old journals, the amendment manifest, task checkboxes, or review gates. A newly dispatched documentation writer may still edit its ordinary permitted files under the new run. An unresolved task operation still blocks admission. The change is scoped to fresh admission with a promoted runnability-owner amendment; the existing exact-hash path is unchanged.

## Observed failure

The disposable `004-smoke` run `build-20261001-100459-635904` accepted T-002 at checkpoint `952a87dc4504`, then blocked in documentation. Its journal records a final tech-writer `NEEDS_CONTEXT` result with known token usage. Ralph retained the unreviewed README/CHANGELOG work at clean salvage commit `da8b016b581e`. The journal's final candidate and source fingerprints still match that checkout. The next native fresh command selected that salvage commit, but `proven_amended_task_ids` rejected the old state's `progress_applied=false` pointer before creating a new build.

`progress_applied=false` is correct: documentation reports were not accepted or published. The error is equating this settled failure with an unknown provider dispatch. An ordinary resume under changed Prosaic role text cannot replay the old sealed journal binding, and replaying its terminal verdict would not repair the docs.

## Recommended design

Keep `proven_amended_task_ids` a pure, fail-closed checkpoint proof. The fresh-run adapter may present a narrowly typed set of `(build_id, operation_id)` terminal-documentation handoff proofs. The pure function ignores an otherwise-pending pointer only when it is a documentation operation in that set. It never infers settlement from `kind`, `status`, `build_reason`, or a Git commit alone; absent or malformed proof preserves the current rejection.

The adapter establishes each proof from the old run's own state, journal, and retained candidate before advancing the current-build marker:

1. Target/spec/build identity and promoted-amendment admission match the selected target. The state is blocked in implementation with `termination_reason=build_blocked`, and its sole pending operation has `kind=documentation`, a nonempty ID, and `progress_applied=false`.
2. No live state-lock owner exists. Derive the journal path from that build's recorded run ID and operation ID, not from a supplied path or a directory scan. Require it to exist, then open the existing `DeliverySliceJournal` under its exclusive lock and apply the current strict documentation schema and receipt-chain validator. Keep admission and new-build reservation protected against a competing continuation; never create a replacement journal or reconcile an unknown dispatch.
3. The last normal receipt is a completed tech-writer `BLOCKED`/`NEEDS_CONTEXT` or docs-verifier `BLOCKED` result, not a pending receipt, provider error, ordinary `FAIL`, `PASS`, or incomplete publication. Every normal and retained rejected-review receipt has known token usage. The state's exact blocked reason matches that terminal step and summary.
4. The operation's worktree is the recorded worktree under that build. Its clean HEAD equals both the selected candidate and the state's recorded salvage commit. The journal's final candidate fingerprint and source fingerprint equal fresh read-only fingerprints of that worktree and the canonical Spec inputs. Existing checkpoint ancestry and amendment input/target checks still run independently. A later manual descendant is outside this exception.

If any check fails, admission stops before provider dispatch or a new build marker. A live or unknown dispatch cannot become terminal merely because a candidate was salvaged. The original state and journal remain available for recovery. This proof does not count as a successful documentation review, grant task credit, change attempt history, or publish reports. Only checkpoint commits can authorize old tasks; the new Delivery run obtains current runnability evidence, documentation author/reviewer results, and final acceptance normally.

The helper belongs beside the existing fresh-run admission logic, using the existing journal validator and fingerprint functions. The lineage function receives only the proven identity pairs; it does no filesystem I/O and retains its existing strict behavior by default. No CLI-specific repair rule or new controller/state pointer is introduced.

## Rejected alternatives

- Exempt every `kind=documentation` pointer: would skip an in-flight or unknown writer and weaken the amendment safety contract.
- Mark the old operation `progress_applied=true` or clear it: would falsely record successful documentation and mutate historical evidence.
- Revert roles or reset the disposable run: would hide the admission defect and discard the retained candidate without testing the intended recovery flow.

## Verification and stopping rule

First test the positive terminal handoff through fresh amended admission: retain only checkpoint-proven task IDs, preserve the salvage candidate, and require new documentation review. Negative cases include a task operation; missing, malformed, locked, or nonterminal journal; unknown token usage; mismatched blocked reason; dirty, changed, or non-salvage candidate; wrong target or amendment; and a live state lock. Existing pending-dispatch and exact-hash tests must remain green.

Then rerun one native command against the disposable `004-smoke` workspace without reset. Confirm that it selects the retained candidate and reaches fresh documentation dispatch, followed by independent review and final verification. Stop at the first new reproducible harness failure. Do not edit generated demo files or Delivery state, and do not claim convergence from a selected task or a passing runnability receipt alone.
