# RE M2 Durable Discovery Acquisition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Actually resolve admitted discovery evidence requests against the frozen snapshot, retaining outcomes and the two-round limit across interruptions.

**Architecture:** Use the existing `ReV2Paths`, `ObjectStore`, `DurableLedger` and `protocol_22_run_lock`. A controller-owned discovery phase records request intent, individual outcomes and a manifest-last context commit. Each selected source has one pinned discovery namespace under the same logical run and ownership lock; changing its origin cannot reset counters. It has no provider dispatch loop, budget allocation or analysis-plan publication authority; legacy run manifests and artifact ledgers stay unchanged.

**Tech Stack:** Python, canonical JSON, existing durable ledger and snapshot reader, offline temporary Git fixtures.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, section 5 and M2.

## Global Constraints

- "No live workspace reads, arbitrary shell access, network fetching, or undeclared-repository traversal are introduced."
- "Repeated identical requests reuse the recorded outcome."
- "Each analysis obligation permits at most two evidence-expansion rounds."
- "All revisions share one aggregate run budget, including unsettled reservations."
- Same checkout. Preserve generated `runs/`, real workspaces and stashes. No installation, live model calls, budget or default-routing changes.
- This implements **pre-analysis discovery acquisition**, not post-activation analysis-plan revision/invalidation. It cannot publish an analysis plan or accept knowledge. The complete shared-budget provider/controller integration, analysis-origin split/merge inheritance, independent review and publication are still release prerequisites.
- Discovery context commits retain the same run/source/snapshot/depth/origin/security identity. The phase neither creates a child run nor writes a budget authorization, so it cannot supply a new budget. Paid discovery dispatch must still be connected to the existing aggregate reservation path before enabling the new workflow.

## Task 1 — Resolve authenticated requests

**Files:** modify `src/harness/re_v2/knowledge_discovery.py`; create `tests/unit/test_re_v2_knowledge_acquisition.py`.

**Interfaces:** `DiscoveryBoundary.read_requests(binding_id, batch_id)` reconstructs admission and rejects forged staged receipts; `resolve_request(binding_id, batch_id, request_id)` returns an immutable outcome ID. Available/redacted evidence carries a safe projection and private mapping; missing/withheld evidence carries an explicit unknown. Unsafe projection is a blocker, never a successful unknown. The phase builds a cumulative binding with `prepare(...)`.

- [x] RED: use the existing real two-file snapshot fixture and request `worker.py`, a missing path and an excluded `.env` file. Assert the worker is safely projected, unknowns are explicit and canaries never appear in provider input.

```python
result = phase.resolve(binding_id, batch_id)
assert result.rounds == 1
assert b"def retry" in phase.provider_bytes()
assert b"unavailable-evidence" in phase.provider_bytes()
```

- [x] GREEN: normalize and re-admit stored requests before resolving, preserving immutable mapping receipts and closed errors. Reject another source/origin, forged pending availability and malformed selectors before recording execution intent.

## Task 2 — Durable controller-owned acquisition and recovery

**Files:** create `src/harness/re_v2/knowledge_acquisition.py`; same test file.

**Interfaces:** `DiscoveryAcquisition(paths, boundary, initial_binding_id, fault_hook=None)` exposes `resolve(binding_id, batch_id)`, `recover()`, `status()` and `provider_bytes()`. Mutations take the existing run ownership lock; locked internal helpers allow recovery to complete the current batch without issuing a provider request. Immutable progress exposes active binding/revision, consumed rounds and pending request ID.

- [x] RED: first and second request batches succeed; the third fails with `evidence-expansion-limit`, including after reopening. Repeating a completed batch reuses recorded outcomes without consuming a round and returns current progress, never a stale active revision/counter. A stale or different pending batch cannot advance the context.

```python
first = phase.resolve(binding_id, batch_id)
reopened = DiscoveryAcquisition(paths, boundary, binding_id)
assert reopened.resolve(binding_id, batch_id) == first
assert reopened.status().rounds == 1
```

- [x] GREEN: use a discovery-specific nested receipt protocol in `DurableLedger` under the existing run directory. The first receipt pins the logical run and initial context. An intent consumes a round before resolution; resolved outcomes are individually durable. Commit references all outcomes and the cumulative context, advances active revision only as the final ledger record and retains the original run budget identity. Never infer an active context from orphan object files.
- [x] RED/GREEN: inject crashes after intent, an outcome blob before its ledger record, each recorded outcome, context staging and commit. Reopen/recover, assert exactly one consumed round, the same request keys and committed context, no repeated resolution of recorded outcomes, and no provider input while a batch remains pending. Simulate a competing writer using the same run lock. Reject wrong initial binding, missing/tampered object closure and corrupt journal; do not reset counters or publish partial input. A blob without a ledger record may be recomputed; it is not accepted authority.
- [x] RED/GREEN: preserve existing budget/event bytes and source bytes. Context capacity overflow remains a recoverable blocker with durable intent and recorded outcomes; do not truncate or waive limits. Provider-visible unknowns use only screened selector/status fields, not private mapping hashes.

### Review-driven corrections

- [x] A real two-source fixture exposed a single-ledger collision. Separate pinned source namespaces now coexist under one run lock/budget identity; a renamed origin in either source is rejected.
- [x] The replay-cost regression observed five base-context request authentications for one two-request batch. Replay now authenticates each batch once and validates each selected range, retaining authenticated outcomes only within that replay. A later pinned-source mutation is still rejected.
- [x] Read-only replay previously called object persistence through projection/admission reconstruction. Split pure `read_projection`/`verify_selection` and request receipt construction from persistence; status and provider input succeed with all `ObjectStore.put_blob` calls forbidden.
- [x] Repeating a selector against an expanded binding previously spent a second round. A historical origin/reason/selector index now makes repeat-only batches no-ops, even at the ceiling. Mixed batches use explicit `evidence_reused` receipts that bind recorded outcomes to the current request/context, resolving only new selectors.
- [x] Fresh discovery namespace parents were not fsynced. Both parent directory entries are now synced with no-follow directory descriptors under the existing run lock, including on reopen after an interrupted initialization.
- [x] Raw source IDs could alias on case-insensitive filesystems. Namespace directories now use a digest of the exact source ID, excluding origin/revision; a real `api`/`API` two-source fixture reproduced the collision before the fix and verifies independent counters afterward.

## Task 3 — Compatibility, review and handoff

- [x] Run focused acquisition/discovery/evidence tests, then the 463-case prior offline compatibility selection plus acquisition tests. Final acquisition suite: **28 passed**. Final full selection: **491 passed in 138.01 seconds**. `git diff --check` is clean.
- [x] Read-only independent review while local verification runs; resolve any actionable findings with regression tests. Final review: no remaining Critical, Important or Minor findings in this bounded slice; approval conditioned on the now-passing compatibility selection and these recorded counts.
- [x] Update the spec implementation status accurately. Initial requested commit: `f67dde8c` (discovery admission). The verified acquisition increment remains explicitly short of a release-ready RE workflow; no installation, live execution or default changes.

## Coverage boundary

This phase closes deterministic acquisition and crash-replay gaps left by the passive boundary. It does not claim to implement every M2 requirement: initial provider scheduling/accounting, orphan reconciliation, analysis-plan revision with dependency invalidation, split/merge inheritance and independent review/debt acceptance remain. The true-empty-Git-source capture gap recorded in the preceding plan also remains. M3 CLI/refresh/publication and M4 authorized real-model trials are unchanged.

## Verification command

All providers in this selection are offline/scripted fixtures; no paid calls or real-workspace mutations were performed.

```bash
pytest -q tests/unit/test_re_v2_knowledge_acquisition.py tests/unit/test_re_v2_knowledge_discovery.py tests/unit/test_re_v2_knowledge_evidence.py tests/unit/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_knowledge_quality.py tests/integration/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_model.py tests/unit/test_re_v2_protocol_22_evidence.py tests/unit/test_secret_scan.py
```
