# Managed Tracker implementation plan

> **For agentic workers:** Use superpowers:executing-plans. Implementation is inline at the user's request; use independent read-only review at each verified checkpoint.

**Goal:** Continue managed greenfield runs through Tracker to WHY1, preserving stable UI/II identities and safe clarification/re-entry.

**Architecture:** Extend the existing selected-producer, human-input, source/publication and completion owners. Clarification preparation must consume captured text and produce detached candidate bytes before any live effects. Protected Tracker rounds retain their parent completion and exact resolved decision; no prior operation, receipt, allocation or budget is reset.

**Tech Stack:** Existing Python, SQLite, Prosaic, Squad state/publication/completion and pytest.

**Spec:** Inline design approved twice in chat: managed Tracker after Synthesizer, native greenfield Modeler skip, Codex/Claude through Prosaic, UI/II reservations, ALIGNED/DRIFT/STOP_AND_ASK routing, existing clarification policies and guarded clarification/re-entry extension. No WHY1 execution or rollout.

## Global constraints

- Preserve exact old IDs, immutable subjects and historical evidence assessments.
- No provider-specific prose or provider-native agent reads.
- No extra controller, allocator, checkpoint writer or mutable copy of prior producer state.
- Guided/semi/banzai use the existing human-input policy; no weakened automatic-answer eligibility.
- Preserve original requirements and intent when producing reconciliation findings. The legacy helper writes a report, not rewritten requirements.
- Keep legacy managed-execution exclusion until a specific authenticated path is integrated.
- No installation, migration, live spending, AGENTS.md/CLAUDE.md changes, legacy build changes or changes to the stopped game workspace.

## Task 1: Detached clarification preparation

**Files:** `src/echelon/feature_policy.py`, new `src/harness/clarification_candidate.py`, new `tests/unit/test_clarification_candidate.py`.

**Interfaces:** Extract `render_feature_policy_reconciliation(artifacts, policy) -> (report, text)` from the existing filesystem wrapper, which continues to own legacy writes. Add frozen `ClarificationRecord(decision_id, question, answer)` and `prepare_clarification_candidate(*, decision, previous, receipt_before, policy_before, artifacts) -> ClarificationCandidate`. `previous` is a tuple of exact records captured from the existing human-input authority, not parsed out of Markdown; `artifacts` is a dict of canonical relative Markdown paths to strings. The returned `decisions` tuple and `receipt_text`, `policy_text`, `policy_context_text`, `reconciliation_text`, `reconciliation_json` strings are immutable. This function owns no paths, files, state, publication, input authority or routing. Prior managed receipt/policy bytes must equal the rendering of that independently authenticated history. Legacy files without that history require explicit reconciliation; no automatic adoption is included.

- [x] Test preparation against literal expected receipt/report/policy bytes; prove originals stay unchanged and no live source reads occur.
- [x] Test exact retry, conflicting same-decision answer/question, multiple decisions, malformed prior receipt/policy and hostile artifact names.
- [x] Run tests to RED before production changes.
- [x] Extract only reconciliation rendering; keep original filesystem wrapper behavior unchanged.
- [x] Build the detached candidate with existing policy derivation/merge/render helpers. New decisions append exactly once; retry preserves exact prior bytes and rejects conflicting provenance.
- [x] Run focused preparation and existing feature-policy/human-input regressions, review, record and commit this inactive preparation checkpoint.

## Task 2: Guarded clarification publication and retained rounds

**Files:** existing `src/harness/squad.py`, `src/harness/squad_state.py`, `src/harness/discovery_completion.py`, `src/harness/discovery_producer.py`, `src/harness/discovery_receipts.py`; focused tests in `tests/unit/test_managed_tracker.py` and `tests/unit/test_squad_identity_exclusion.py`.

**Interfaces:** The existing human-input resolver consumes the detached candidate only after validating the exact pending decision, resolver, state revision and current parent completion. The existing `SquadPublicationTransaction` stages receipt, policy and reconciliation bytes; the existing completion context builder stages context from captured projected artifacts. The same identity publication/source claim binds the coherent before/after images and retained history. Extend protected producer selection with immutable per-round records, each binding a parent completion and resolved decision; historical completion readers select the exact retained round, never the mutable active round.

- [ ] Add a real STOP_AND_ASK/answer/re-entry test through the normal controller API. Assert no live writes before the guarded publication is bound and no ordinary legacy execution is admitted.
- [ ] Stage the Task 1 candidate and captured context through existing publication/completion owners. On source drift, stale decision or changed answer reject without promotion.
- [ ] Retain separate Tracker round/receipt paths. Tie the next round to the exact resolved decision and accepted parent completion; preserve total token/dispatch accounting and prior receipts.
- [ ] Extend retained source/context proof traversal across Synthesizer, Tracker and clarification completions, rejecting missing/cyclic/foreign ancestry. Never ignore unverified context or metadata.
  - Discovery/Synthesizer prerequisite: verify the entire retained context chain
    back to original admission inputs, with exact parent artifact/history links.
    Tracker/clarification completion bindings still need their own integration;
    this prerequisite does not complete this checklist item.
- [ ] Test interruption before/after staging, route, promotion, context, receipt, release and cleanup; exact resume produces no duplicate IDs, charges or ledger append.

## Task 3: Normal Tracker execution and verification

**Files:** `src/harness/discovery_semantics.py`, `discovery_candidate.py`, `discovery_operation.py`, `discovery_operation_state.py`, `discovery_turns.py`, `discovery_publication.py`, `squad.py`; `prosaic/subagents/echelon.tracker-producer.md`; `tests/unit/test_managed_tracker.py`.

**Interfaces:** Keep existing discovery/synthesis reply encodings exact. Tracker adds its own closed assignment/reply contract: explicit intent routing verdict, optional stakeholder output, UI/II proposal/reservations and exact row authoring. Authenticated routing output must be included in candidate/reviewer/completion binding, never substituted with DONE. Managed selection admits `through_phase: phase1-tracker` only through the existing internal entry; defaults remain unchanged.

- [x] Add initial normal-entry acceptance: both provider cases currently fail at `managed_discovery_selection_requires_reconciliation`, before any dispatch.
- [ ] Extend closed producer selection and native Modeler skip; preserve the workflow's Tracker output/verdict/human-input contracts.
- [ ] Exercise required intent plus optional stakeholder output, UI/II creation/revision, preserved U/A evidence, ALIGNED/DRIFT continuation and STOP_AND_ASK through Task 2.
- [ ] Verify both providers and all three autonomy modes, source tampering, semantic rejection, missing receipts, bounded retries and restart accounting.
- [ ] Independent read-only review; run affected regressions. Record exact evidence and remaining WHY1/repair/live acceptance work in existing convergence records; commit only verified changes.

## Initial evidence

- Baseline discovery-turn and Tracker-template tests: 77 passed in 6.67s.
- Two new normal Tracker acceptance tests: expected RED at unsupported managed selection. These are pending integration tests, not a passing checkpoint.
- Inspection corrected the mutation description: `reconcile_feature_artifacts` writes the reconciliation report and does not rewrite its source requirements. `build_run_context` still writes context directly in the legacy resolver; the managed bridge must use staged captured context.

## Task 1 review and verification

- Initial candidate tests: 18 failed because the new preparation entry did not
  exist, one existing-wrapper behavior test passed. After implementation,
  candidate and feature-policy tests: 25 passed in 0.26s.
- A nested-file regression reproduced a changed finding order from string sorting.
  Rendering now uses the original Path ordering; no legacy ordering change ships.
- Human-input, managed-exclusion and feature-policy regressions: 382 passed in
  52.15s before the final review additions.
- Final rerun including all review fixes: **385 passed in 51.65s** using:
  ```sh
  python -m pytest tests/unit/test_clarification_candidate.py tests/unit/test_feature_policy.py tests/unit/test_human_input.py tests/unit/test_human_input_resolution_contract.py tests/unit/test_human_input_static_contract.py tests/unit/test_squad_identity_exclusion.py tests/integration/test_human_input_routing.py -q --tb=short
  ```
- `git diff --check` passed. This local commit contains only Task 1 and its
  records; Tasks 2/3 remain authorized work, not completed integration.
- Independent read-only review found no Critical/Important issue. Its two minor
  items were non-UTF-8 path rejection and stronger exact serialization/older-retry
  coverage. The path test reproduced the defect before adding encoding validation;
  the other cases verify the existing intended contract without changing behavior.
- The record list is a detached projection, not a second decision ledger. The
  integration must authenticate it against the existing human-input owner. No
  provenance is inferred from Markdown even when user text contains decision-like
  headings. Prior files without authenticated history remain inadmissible.

The normal Tracker acceptance file remains uncommitted pending Tasks 2/3. A
passing preparation test group is not a passing managed Tracker run.

## Task 2 source-ancestry prerequisite

The existing released-completion reader projected only one context generation.
After real Discovery and Synthesis completions, it therefore returned Discovery's
generated identity-bearing context instead of original admission inputs. The
regression reproduced both with and without checkpoint policy (2 failed in
41.54s); extending the existing reader made those same cases pass (2 passed in
42.05s). No runtime-domain check was removed or relaxed.

The reader now follows exact retained completion associations iteratively,
rejects repeated operation IDs, verifies each parent's accepted artifacts,
identity history and context against the child's captured before-images, and
returns a pure projection back to the original runtime context. Current raw
captures, source guards and model evidence remain current; no live context,
state, source history, receipt encoding, ID or budget is rewritten. Existing
version-2 checkpoint proofs retain their original encoding; releases without a
full proof remain inadmissible.

This is a partial Task 2 checkpoint. Guarded human resolution, per-round Tracker
state/receipts, Tracker-specific historical decoding and normal dispatch remain
open. No new approval is required for those already-approved tasks. The pending
normal Tracker acceptance file remains RED and is not part of this checkpoint.

Independent read-only review found no outstanding Critical/Important/Minor issue.
Its initial suggestion for direct multi-round cycle/relationship tests was checked
against current reachable states: the closed Discovery encoding terminates the
chain, only Synthesis can have a parent, and protected state plus the existing
source owner reject mismatched parent/context/predecessor links before traversal.
The reviewer agreed not to fake successful authority responses to reach defensive
branches. Add those direct tests with retained Tracker rounds, when further links
become representable; keep the current real stored-proof corruption tests now.

Expanded ancestry verification: **13 passed in 302.26s** using
`python -m pytest tests/unit/test_managed_source_ancestry.py -q --tb=short`.
This includes both checkpoint modes, corrupted/missing/foreign parent proofs,
current context/spec/ledger/source drift, and exact old version-2 proof retention.
The two normal Tracker acceptance cases were rerun separately and remain expected
RED at `managed_discovery_selection_requires_reconciliation` (2 failed in 0.85s).

Broader regression verification: **201 passed in 1181.25s** using:
```sh
python -m pytest tests/unit/test_managed_synthesizer.py tests/unit/test_discovery_completion.py tests/unit/test_discovery_checkpoint.py tests/unit/test_discovery_repair_inputs.py tests/unit/test_discovery_repair_retention.py tests/unit/test_squad_identity_exclusion.py -q --tb=short
```
Together these are 214 passing selected checks, not a full-suite or Tracker
acceptance claim. `git diff --check` passed. Only the source-ancestry code,
its passing tests and these convergence records belong to this local checkpoint.

Integration seams confirmed for the remaining Task 2 work:

- `SquadController.apply_human_input_resolution` already validates the decision,
  resolver and revision before committing a resolved postimage with an optional
  prepared completion. Preserve that owner and its CAS boundary.
- `squad_completion.py` currently permits resolution-origin completions only for
  the quality effect and no publication. Its closed validator must explicitly
  admit the managed clarification association; do not relabel a human resolution
  as an ordinary routed dispatch or weaken all resolution validation.
- `SquadStateStore.apply_human_input_state_resolution` must bind publication and
  completion together with the exact resolved decision. Current quality-only
  completion assumptions cannot be reused unchanged.
- Completion release/recovery must select the existing human-resolution receipt
  owner (`last_human_input_completion`), preserving `last_dispatch` as the parent
  Tracker result. A second controller/decision ledger is not needed.
