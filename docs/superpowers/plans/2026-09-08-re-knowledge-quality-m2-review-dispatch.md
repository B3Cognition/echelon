# RE M2 Shared-account Review Dispatch Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development and test-driven development. Keep the next increment uncommitted for handoff.

**Goal:** Execute and recover one discovery-review turn against a ledger-committed producer proposal, charging the existing logical-run account.

**Architecture:** Extend the current account's event protocol for review reservation/application; reuse its captures, charging, store and ownership lock. A review step is an operation of the existing owner, not a scheduler. The committed application binds the passive review receipt to a distinct dispatch; offline execution does not certify real-model independence or enable analysis/publication.

**Tech Stack:** Existing Python durable ledger, canonical objects, pinned evidence, neutral roles and pytest synthetic repositories.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, sections 5, 7, 9 and M2.

## Global Constraints

- Stay in the user-selected checkout and branch; preserve untracked generated `runs/` and all source workspaces/stashes. No installation, migration, live calls, default changes or budget increases.
- One existing account, `KnowledgeDispatchPolicy` and `KnowledgeProviderContract`; no new per-review budget, retry policy or scheduler. Both producer and review turns consume `max_source_turns` and aggregate token/time ceilings, including unsettled reservations.
- Existing discovery event shapes and passive schema-1/schema-2 receipt identities remain readable and unchanged.
- Only `offline-scripted` transport is enabled. Review admission retains `execution_certification_required: true` and `analysis_certified: false`. No plan activation, producer repair loop, debt acceptance or publication in this increment.
- Provider requests contain only the separately frozen review role/phase bytes and `DiscoveryReviewBoundary.provider_bytes` context, not the producer role, transcript or previous verdict. Screen complete output before ordinary persistence and use closed diagnostics.

### Task 1: Shared accounting and recoverable review operation

**Files:**
- Modify `src/harness/re_v2/knowledge_accounting.py` for review reservation/application replay and shared ceilings.
- Modify `src/harness/re_v2/knowledge_dispatch.py` only for a narrow shared capture helper and discovery-history selection compatible with review events.
- Create `src/harness/re_v2/knowledge_review_dispatch.py` for the review operation.
- Create `tests/unit/test_re_v2_knowledge_review_dispatch.py`.

**Interfaces:**
```python
DiscoveryReviewController(
    producer: DiscoveryController,
    agent_bytes: bytes,
    backend: DiscoveryBackend,
    reservation: DispatchReservationV1,
    *, fault_hook: Callable[[str], None] | None = None,
)
DiscoveryReviewController.step() -> DiscoveryStep
```

The producer supplies authenticated acquisition, account and pinned producer authority; calling review must never call `producer.step()` or otherwise start producer work. Result states: `review_ready`, `revision_required`, `blocked`. Successful `receipt_id` is the existing passive review receipt and retains its flags. Feedback is readable with existing `read_review`; no new certification object is necessary.

- [x] RED: after a real scripted discovery call, review observes the same account's open reservation, receives only the review context, and consumes the second source turn. Illustrative integration assertion:
```python
proposal = producer.step()
assert proposal.state == "proposal_ready"
before = account.status().charged_tokens
result = reviewer.step()
assert result.state == "revision_required"
assert account.status().charged_tokens == before + 100_000
assert reviewer.step() == result
assert len(review_calls) == 1
```
Build the fixture from the existing real `_controller` and literal valid review in `test_re_v2_knowledge_review_handoff.py`; inject only the external provider seam. Do not compute expected receipts using the controller under test.

- [x] GREEN: add `review_reserved` and `review_applied` event handling to the SAME dispatch ledger. Review request uses the existing source/scope/agent/binding/revision/context/reservation/turn fields plus `producer_dispatch_id` and `proposal_receipt_id`. The event kind identifies review; do not alter old discovery request identities. Shared capture stays `dispatch_captured`. All dispatches remain in the aggregate charge and source-turn sequence. Discovery history selection excludes review turns but discovery cannot create another call after its terminal staged proposal.

- [x] RED/GREEN: reserve review only after that source's latest ledger-committed successful producer application is `proposal_ready`. Reject an uncommitted/passively admitted proposal, unfinished producer, a different binding/revision/scope/source/run, changed role/reservation/backend, or substituted capture. Freeze a distinct review agent identity from producer. Validate this transition in replay, not only the controller. Both existing account and acquisition must be the same run with the selected snapshot/security roots. Under the existing run lock, reauthenticate the proposal through `read_proposal`, the ledger-committed producer revision and its exact capture/admission chain. Recompute expected reviewer context and verify stored context bytes on recovery.

- [x] RED/GREEN: `tokens=150_000` after a 100,000-token producer cannot reserve a 100,000-token review; `max_source_turns=1` also refuses before review call. Review cannot reopen an account with new limits. Another source's breach blocks new calls but must not prevent safe application of this review's already-paid unbreached capture. Bound role/context bytes against the frozen reservation before recording a call. Return the actionable context/overlap bound before spending.

- [x] GREEN: factor existing invoke/capture logic into one narrow internal helper used by discovery and review, preserving old behavior and canonical capture receipts. No generic framework. Review applies `DiscoveryReviewBoundary.admit` to captured bytes. Invalid authorial review becomes durable `review-result-invalid`; unsafe/provider/breach outcomes remain closed blocked results with conservative charges. Local storage/authority failures propagate without recording model rejection, leaving a paid capture recoverable.

- [x] RED/GREEN: crash at `review_reserved` leaves an indeterminate open reservation and no automatic retry; crash at `dispatch_captured` or `review_applied` replays without another provider call. Failure during admission persistence retries application only. Reopening with changed agent/reservation/backend, corrupted context/proposal/capture/review objects or missing admission closure must fail closed, never grant success or refund charges. Screen canaries before ordinary capture; forged authorial replay remains rejected without writes. Keep ready/revise results distinct and feedback intact after reopening. Reject double review or producer replay interpreted as review.

- [x] Run focused new tests then existing evidence/discovery/acquisition/dispatch/review/handoff tests. Report actual RED/GREEN commands and output; no live providers or commits. Freeze changes for task review.

### Task 2: Runtime handoff and verification

**Files:** `runtime/workflow/phases/re-knowledge-discovery-review.md`, `runtime/workflow/phases/re-knowledge-discovery.md`, spec implementation status, this plan; optional separate cross-component test in `tests/unit/test_re_v2_knowledge_review_handoff.py`.

- [x] Document the concrete review operation and shared charges/recovery. Keep installed routing disabled and state that distinct offline dispatch is not semantic certification. Document preserved feedback and terminal no-repeat behavior. No new role or role-count changes.
- [x] Independent read-only review checks task compliance and code quality; resolve actionable defects with covering regressions and scoped re-review.
- [x] Run the prior 853-case compatibility selection plus the new dispatch tests, `git diff --check`; record exact outcomes and remaining gates. Leave this increment uncommitted, no install.

## Preflight and remaining scope

Task 1 owns account/driver/tests; task 2 consumes `DiscoveryReviewController.step` in prose and compatibility tests, without concurrent edits to task 1 files. Request/application events are needed because discovery-only readiness forbids a review turn and passive receipts cannot prove which paid call produced them. Existing capture and application envelopes serve recovery; no second execution ledger is introduced.

Remaining approved work: production adapter isolation/pre-log screening and real independent invocation certification; bounded producer revisions, semantic target/source reconciliation, analysis invalidation/debt; M3 unified publication/refresh/consumer path; M4 explicitly authorized live evaluations. This bounded step does not satisfy those gates.

## Progress

Previous increment committed as `a22dd87c`. Both tasks complete. Independent review identified two replay defects; fixes passed focused verification and scoped re-review approved the increment with no remaining findings. Final full compatibility: **881 passed in 332.88s**. This new increment remains uncommitted; no installation or live execution occurred.

Initial verification: new 24 tests passed; old discovery/handoff 58 passed; parent full selection 877 passed in 288.74s. Review fixes: four RED failures reproduced contradictory transport reasons and an invented overlap list; all four passed after the fix. Final focused review-dispatch selection: 28 passed in 23.16s; existing discovery/handoff: 58 passed in 52.38s. Both fixes are confined to replay validation and preserve existing discovery behavior.

Final verification used the preceding review-admission plan's full 853-case selection plus `tests/unit/test_re_v2_knowledge_review_dispatch.py` (28 cases). `git diff --check` passed. Independent reviewer approved both task compliance and code quality after scoped re-review. Offline dispatch receipts do not certify real-model independence; production adapter safety/invocation certification and the remaining M2/M3/M4 product gates above are still required. Generated `runs/`, source workspaces, stashes, installed defaults and existing run ceilings were untouched.
