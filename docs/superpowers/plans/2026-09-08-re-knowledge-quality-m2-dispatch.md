# RE M2 Discovery Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Drive the existing discovery/acquisition phase with bounded provider turns, durable capture/recovery and one run-wide resource account.

**Architecture:** Reuse `ReV2Paths`, `ObjectStore`, `DurableLedger`, the existing run ownership lock, `DispatchReservationV1`, normalized usage and conservative charging. Add an internal knowledge execution receipt contract, not another scheduler. A single-step controller is called by the owning workflow; it never spawns another controller or grants a child budget. One account covers all sources and context revisions. It must reject legacy execution stores rather than silently place a fresh account alongside existing charges. Legacy protocols and installed routing remain unchanged.

**Boundary:** The backend seam receives only screened bytes and a frozen reservation, and returns bytes plus normalized usage; it cannot write ordinary RE artifacts. Offline scripted backends exercise this seam. A production adapter must separately prove tool isolation, bounded execution and pre-log screening before being enabled. This increment does not enable paid execution, publish analysis plans or certify knowledge. Remaining M2 work includes that production adapter, semantic review, orphan reconciliation and analysis revision/invalidation; M3/M4 gates are unchanged.

## Task 1 — Shared execution accounting

- [x] RED: reservation precedes backend invocation; open reservations and uncertain outcomes count at their full ceilings; settled trusted usage uses the existing normalizer/charging contract.
- [x] GREEN: freeze absolute limits and provider contract in one run opening. Require exact reopening identity. Reject a legacy run and missing/corrupt receipt closure. All sources use this account; a revision cannot reset it.
- [x] RED/GREEN: cap turns per pinned source, reject changed origin/provider/limits, reject out-of-budget dispatch before invocation, and block further dispatch after a reservation breach.

## Task 2 — Single-step discovery controller

- [x] RED/GREEN: proposal → staged proposal receipt; evidence request → durable acquisition → next provider turn against the committed context. Never label a proposal accepted knowledge.
- [x] RED/GREEN: persist reservation, screen and capture response, then apply admission/acquisition. Recovery after capture or context commit repeats no backend call. An interrupted uncaptured dispatch remains an actionable indeterminate outcome with its reservation retained, not a fresh call.
- [x] RED/GREEN: fixed errors for unsafe output, malformed results and backend exceptions; quarantine unsafe bytes before ordinary retention. Preserve resource charge even when admission fails. No automatic loop for repeated unknown evidence, invalid output or exhausted expansion rounds.
- [x] Keep semantic discovery behavior in a neutral role and dispatch inputs/output in a runtime phase contract. Pin rendered authority in dispatch receipts. Do not expose private mappings or local paths to the backend.

## Task 3 — Verification and handoff

- [x] Run focused offline tests and the prior 491-case compatibility selection. Final combined verification: **816 passed in 299.36s**, including 57 dispatch cases, the prior compatibility selection, neutral prompt/workflow checks, catalog, packaging and tool-contract tests. Separate final dispatch/admission focus: **93 passed**. `git diff --check` passed.
- [x] Independent read-only review while compatibility verification runs; address actionable findings with regression tests. Reviewer approved the offline increment and rechecked the passive-receipt compatibility correction without further findings.
- [x] Update implementation status and report remaining release prerequisites accurately. No installation, live model calls, generated `runs/` commits, real workspace changes or budget/default changes.

## Review-driven corrections

- Reopening an empty account is a blocker, never a refund. Completed turn reuse reauthenticates the actual ledger-committed context and pinned evidence.
- The legacy guard includes `captures` and dangling authority paths. It checks canonical run paths under ownership before constructing the object store.
- Store a typed `KnowledgeProviderContract` and validate its content on replay. This increment accepts only `offline-scripted` execution and `utf8-byte-upper-bound` input accounting. Metadata is not a sandbox: the production adapter still must prove complete wire accounting, isolation and pre-log screening. No exact-token transport is claimed here.
- Pin snapshot, partition, security policy and selected source IDs in the run account. Selection may be a subset of declared partition sources; unselected sources cannot spend it.
- Validate application state, reason, receipt kind, binding, revision, capture and admission closure. New internal admission receipts use schema 2 and bind the exact screened authorial response; old passive schema-1 request receipts remain readable. Legacy execution protocols are unchanged.
- Separate invalid authorial responses from storage/authority failures. Temporary admission persistence failure leaves the paid capture recoverable without a new call.
- A breached dispatch blocks new calls globally, but does not invalidate another source's previously captured clean result. Apply/recovery checks the individual dispatch reservation.

## Remaining boundary

### Verification command

```bash
pytest -q tests/unit/test_re_v2_knowledge_dispatch.py tests/unit/test_re_v2_knowledge_acquisition.py tests/unit/test_re_v2_knowledge_discovery.py tests/unit/test_re_v2_knowledge_evidence.py tests/unit/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_knowledge_quality.py tests/integration/test_re_v2_protocol_28_*.py tests/unit/test_re_v2_run_store.py tests/unit/test_re_v2_model.py tests/unit/test_re_v2_protocol_22_evidence.py tests/unit/test_secret_scan.py tests/unit/test_prosaic_agent_authoring.py tests/kernel/test_workflow_validator.py tests/kernel/test_prompt_references.py tests/unit/test_runtime_prompt_paths.py tests/unit/test_prompt_markdown.py tests/kernel/test_agent_role_catalog_docs.py tests/unit/test_prosaic_package_install.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_prompt_tool_contracts.py
```

### Release prerequisites

This is an offline controller integration, not an enabled production provider or a
complete RE workflow. The account currently drives discovery turns; subsequent
analysis/review/synthesis integration must extend the same logical-run receipt
contract rather than open phase-local budgets. Production adapter proof,
orphan/semantic reconciliation, analysis invalidation and reviewed debt handling
remain M2 work. The true-empty-source capture gap, M3 publication/refresh/consumer
path and M4 separately authorized live trials remain release prerequisites.
