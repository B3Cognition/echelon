# RE M2 Discovery Admission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect structured discovery proposals and evidence requests to authenticated safe snapshot contexts, without giving model output execution authority.

**Architecture:** One RE-local admission boundary consumes the existing safe evidence reader and object store. It returns immutable, validated proposal/request records for the existing controller; it does not dispatch providers, activate revisions, certify semantics, or create a second scheduler.

**Tech Stack:** Python, canonical JSON, existing snapshot/partition/object-store primitives, temporary Git fixtures and scripted model responses.

**Spec:** `docs/superpowers/specs/2026-09-08-re-knowledge-quality-repair-design.md`, sections 5–7 and M2.

## Global Constraints

- "No live workspace reads, arbitrary shell access, network fetching, or undeclared-repository traversal are introduced."
- "Historical ledgers, accepted candidates and publications remain immutable."
- "Missing catalog entries or missing parser output are not evidence of non-applicability."
- "Do not build a second scheduler, generic agent framework or new parser platform."
- Same checkout; preserve untracked `runs/`, all real sources and stashes. No installation, live provider calls, budget changes or default routing changes.
- This admission slice is not the complete M2 controller loop. Aggregate accounting, two-round admission, durable request replay, atomic revision activation/invalidation, independent review and debt acceptance must be connected before execution is enabled.

## Record rationale

- Safe context: provider-visible inventory metadata and explicitly selected safe projections. Raw partition hashes/bytes never enter this payload.
- Private binding: binds that context to the controller's snapshot, source, depth, origin obligation and exact mapping receipts. Existing raw evidence contexts cannot substitute for safe projections.
- Validated response: preserves a screened, canonical proposal or normalized evidence request plus its context binding. It is a staged input, not an accepted analysis result or active revision. Existing immutable object storage provides durability; the controller's later event commit must grant activation authority.

## Task 1 — Safe context and discovery proposal admission

**Files:** create `src/harness/re_v2/knowledge_discovery.py` and `tests/unit/test_re_v2_knowledge_discovery.py`.

**Interfaces:**

```python
DiscoveryBoundary(snapshot, partition, source_id, depth, origin_obligation_id, objects, quarantine)
boundary.prepare(selectors: tuple[EvidenceSelectorV1, ...]) -> str  # private binding ID
boundary.provider_bytes(binding_id: str) -> bytes  # authenticated safe context
boundary.admit(binding_id: str, output: bytes) -> str  # staged response ID
```

- [x] RED: create a real snapshot of an application and orphan file. Build context from one safe selector; admit a scripted proposal containing domain/subject evidence, exactly-once file ownership and all seven domain/five source categories. Assert orphan visibility and stable IDs under repeated admission and array reordering. The production mutation caught is omission of inventory/category/reference validation, not model prose quality.

```python
receipt_id = boundary.admit(binding_id, canonical_json_bytes(proposal))
receipt = json.loads(objects.read_blob(receipt_id))
assert receipt["state"] == "proposal_validated"
assert receipt["unassigned_paths"] == ["worker.py"]
assert receipt["review_required"] is True
```

- [x] GREEN: strict bounded JSON, duplicate-key rejection, exact fields, source and context binding, safe nonempty evidence references, unique domain/subject keys, exhaustive inventory rows, no duplicate ownership, exact category pairs. All category entries mean pending assessment; discovery cannot declare PASS/not-applicable or waive categories. Configuration-only sources may have no domains. Truly empty Git source integration remains blocked by legacy capture, as recorded below.
- [x] RED/GREEN: reject forged, wrong-snapshot or edited contexts; foreign/raw/withheld factual references; omitted files/categories; duplicated owners/keys; unknown fields and unsafe output. Questions may cite withheld projections to explain unknowns without supporting factual domain/subject claims. Reopen against the same snapshot and reuse immutable IDs. Use the actual pinned reader and output quarantine, not pre-certified fixture subjects.

## Task 2 — Typed evidence-request admission

**Files:** same boundary and test file; no provider routing changes.

```python
request = {"schema_version": 1, "kind": "evidence_requests", "source_id": "api",
           "requests": [{"obligation_id": origin_id, "reason_class": "missing-behavior",
                         "selector": {"source_id": "api", "path": "worker.py",
                                      "byte_start": 0, "byte_end": 40}}]}
```

- [x] RED: requests must retain the exact controller origin, source and normalized selector. Reject path escapes, altered origin, duplicate requests, unknown actions and empty batches. Missing inventory yields an explicit unavailable outcome, never new source access. Calls cannot alter source files or create an active revision.
- [x] GREEN: admit at most 16 distinct requests per response, each within the existing 65,536-byte selector bound. Record `pending` or `unavailable` with a closed reason code and exact binding; do not resolve pending requests, reset counters or dispatch anything. The existing controller must first persist/admit requests and account for at most two rounds under one aggregate budget.

## Verification and checkpoint

- [x] Run new discovery/evidence tests, then the prior 427-test compatibility command with discovery included. Run whitespace checks and focused independent review, reproducing findings before fixes.
- [x] Update progress and report exact scope. Commit only the previously verified evidence slice first; leave this continuation separately reviewable.

## Self-review and remaining integration

This implements the structural boundary of the approved LLM-led proposal/request loop. It deliberately does not claim model dispatch, semantic review, complete discovery, revision activation, budget enforcement or end-to-end RE. Keeping it as a passive consumer avoids a parallel scheduler and preserves historical protocol contracts. Neutral prompts belong with the controller integration, where actual modes and response schemas can be exercised together; existing pinned analyst prompts remain unchanged here.

## Progress and integration findings

- Prior safe-evidence slice committed as `7e53e0e4`; fresh evidence verification before commit: 36 passed.
- Initial proposal suite: 18 cases failed at the missing admission boundary, then passed after implementation. Request positive cases failed before request admission; combined discovery/evidence suite subsequently passed 65 cases.
- Added RED→GREEN regressions for nested quarantine separation, withheld evidence as an unknown rationale, reason-class-sensitive request identity, and UTF-8 BOM/escaped-token output screening. The last case exposed a parser mismatch at the previously committed output gate; the correction is included in this continuation and pins the decoder in its policy identity.
- Final expanded offline compatibility suite: 463 passed in 172.66 seconds, including 36 discovery cases and the prior 427-case evidence/M1/protocol-2.8/pinned-reader/scanner/model/run-store suite. Independent focused correction review approved this passive admission slice with no remaining actionable findings. Whitespace checks produced no diagnostics.
- Legacy `plan_clean_workspace_sources` refuses an empty Git tree before snapshot capture. No historical snapshot behavior was changed or bypassed in fixtures. The repaired workflow still requires an explicit empty-source snapshot/disposition path before release; this is not covered by the configuration-only source test.
- Still required: provider dispatch under the existing aggregate budget, durable two-round expansion accounting and replay, staged revision/invalidation activation, orphan reconciliation, independent semantic review and new-debt acceptance, followed by M3 publication/refresh/consumer integration and M4 authorized live evaluation.
