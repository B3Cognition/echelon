# RE v2 L4 Execution and Recovery Implementation Plan

**Goal:** Execute protocol-2.8 exhaustive slices through bounded producer and independent-verifier attempts, retain every durable accepted sibling, support L4-only checkpoint reuse, and recover every crash seam without duplicating live work or weakening exact root closure.

**Architecture:** Extend only `harness.re_v2.protocol_28` plus narrowly versioned checkpoint discovery. Frozen `SlicePlanEntryV1` values are realized into exact execution specs; provider results remain evidence until closed controller validation creates candidates, verification receipts, certification, and accepted-slice authority. A protocol-local append-only event/ledger projection owns attempts, paired resource reservations, plateau decisions, roots, and recovery. Checkpoint V2 is physically separate from V1 and keys reuse by target-local slice authority rather than global selection.

**Constraints:**

- One initial producer call plus two repairs; malformed producer output consumes one of those three and has no nested retry.
- A valid candidate always receives an independent verifier call; verifier contract failure has one verifier-only retry.
- Before producer dispatch, reserve producer plus minimum verifier capacity atomically.
- Two identical consecutive nonempty diagnostic ID sets terminate as `non_improving_verification`.
- Accepted siblings never reopen. Budget authorization never changes attempt/policy/work identity.
- Raw provider content is durably captured but excluded from ordinary events, telemetry, and status.
- V1 checkpoint files and protocol-2.2-through-2.7 bytes remain unchanged.

---

### Task 1: Close Producer, Verifier, Diagnostic, and Repair Schemas

**Files:**
- Create: `src/harness/re_v2/protocol_28/artifacts.py`
- Create: `tests/unit/test_re_v2_protocol_28_artifacts.py`

**Interfaces:**
- `EvidenceAnchorV1`, `ExhaustiveClaimV1`, `ExhaustiveObservationV1`
- `ExhaustiveEvidenceSliceV1`
- `ExhaustiveDiagnosticV1`, `ExhaustiveVerificationV1`
- `ExhaustiveRepairPacketV1`
- `validate_candidate(slice_spec, plan_entry, evidence_catalog, raw)`
- `validate_verification(slice_spec, candidate, raw)`

- [x] Write failing closed-schema and evidence-boundary tests.
- [x] Run RED.
- [x] Implement exact candidate acknowledgement, claim grounding, normalized diagnostic IDs, and PASS/REPAIR rules.
- [x] Add unknown path/shard/finding, duplicate result, unresolved PASS, output bound, and round-trip mutation tests.
- [x] Run GREEN with planning/evidence regressions.
- [x] Commit `feat(re): validate exhaustive slice evidence`.

### Task 2: Persist Captures and Controller-Owned Acceptance Authority

**Files:**
- Create: `src/harness/re_v2/protocol_28/execution.py`
- Create: `src/harness/re_v2/protocol_28/ledger.py`
- Create: `tests/unit/test_re_v2_protocol_28_execution.py`
- Create: `tests/unit/test_re_v2_protocol_28_ledger.py`

**Interfaces:**
- exact producer/verifier execution envelopes and fresh-context role separation;
- durable raw capture before parse;
- certification and acceptance constructors that create `AcceptedExhaustiveSliceV1` only from controller-validated PASS;
- append-only candidate, verifier, certification, and acceptance ledgers.

- [x] Write failing durability-order and independent-context tests.
- [x] Run RED.
- [x] Implement no-clobber captures, parsing seams, ledger prefix authentication, and controller receipts.
- [x] Inject faults before/after capture, parse, object write, certification, and acceptance.
- [x] Run GREEN with existing execution-kernel regressions.
- [x] Commit `feat(re): persist independent L4 verification`.

### Task 3: Enforce Paired Reservations, Attempts, and Plateau

**Files:**
- Create: `src/harness/re_v2/protocol_28/budget.py`
- Create: `src/harness/re_v2/protocol_28/scheduler.py`
- Create: `tests/unit/test_re_v2_protocol_28_budget.py`
- Create: `tests/unit/test_re_v2_protocol_28_scheduler.py`

**Interfaces:**
- protocol-local resource ledger with producer/verifier, known/unknown, generated/adopted dimensions;
- paired producer-plus-verifier reservation preview/commit;
- next-action state machine for producer, verifier, verifier-contract retry, producer repair, plateau, terminal failure, and acceptance.

- [x] Write failing no-orphaned-producer-spend and fixed-attempt tests.
- [x] Run RED.
- [x] Implement deterministic reservation and attempt transitions.
- [x] Add unknown usage, authorization raise, malformed producer, verifier-only retry, semantic repair, identical-diagnostic plateau, and accepted-sibling tests.
- [x] Run GREEN with protocol-2.5 budget regressions.
- [x] Commit `feat(re): bound exhaustive repair scheduling`.

### Task 4: Add Physically Versioned L4 Checkpoints

**Files:**
- Create: `src/harness/re_v2/protocol_28/checkpoints.py`
- Create: `src/harness/re_v2/protocol_28/checkpoint_cache.py`
- Create: `tests/unit/test_re_v2_protocol_28_checkpoints.py`
- Modify narrowly: `src/harness/re_v2/protocol_26/reconstruction.py`
- Test: `tests/unit/test_re_v2_protocol_26_*.py`

**Interfaces:**
- `CheckpointManifestV2`, `CheckpointSelectionBundleV2` for L4-only kinds;
- `index-v2.json`, `manifests-v2/`, `quarantine-v2.json`;
- exact target-local compatibility and child-local copying before adoption;
- manifest-first V1/V2 origin dispatch that silently skips recognized adjacent versions.

- [x] Freeze V1 bytes with and without adjacent schema-7 origins.
- [x] Run RED.
- [x] Implement closed V2 selection/ranking/cache and the narrow origin discriminator.
- [x] Add selection expansion, changed unrelated domain, changed shard/policy/verifier, missing object, and origin/cache deletion tests.
- [x] Run GREEN with every protocol-2.6 checkpoint test.
- [x] Commit `feat(re): add L4 checkpoint schema v2`.

### Task 5: Add Events, Projection, and Authority-First Recovery

**Files:**
- Create: `src/harness/re_v2/protocol_28/events.py`
- Create: `src/harness/re_v2/protocol_28/controller.py`
- Create: `src/harness/re_v2/protocol_28/recovery.py`
- Create: `tests/unit/test_re_v2_protocol_28_events.py`
- Create: `tests/unit/test_re_v2_protocol_28_controller.py`
- Create: `tests/unit/test_re_v2_protocol_28_recovery.py`

**Interfaces:**
- closed content-free event allowlist and projection states;
- sole-writer controller transitions;
- recovery action planner for every producer/verifier/acceptance/root seam;
- deterministic root construction and zero-call closure successor handoff.

- [x] Write failing replay and crash-matrix tests.
- [x] Run RED.
- [x] Implement event validation, replay invariants, idempotent recovery actions, root sequencing, and closure link.
- [x] Add live-owner, dead-owner, durable-raw-before-parse, acceptance-before-export, root-before-materialization, projection loss, changed/missing source, and closure-integrity tests.
- [x] Run GREEN with protocol-2.2/2.5 recovery regressions.
- [x] Commit `feat(re): recover exhaustive L4 execution`.

### Task 6: Add Neutral L4 Roles and Execution Gate

**Files:**
- Create: `prosaic/subagents/echelon.re-exhaustive-analyst.md`
- Create: `prosaic/subagents/echelon.re-exhaustive-verifier.md`
- Create: `tests/unit/test_re_v2_protocol_28_roles.py`
- Modify: `tests/unit/test_prosaic_execution_policy.py`

**Interfaces:**
- neutral analyst/verifier roles with dispatcher/protocol split and paired ALWAYS/NEVER invariants;
- distinct response schemas and fresh verifier context;
- no provider-specific model naming or state-writing authority.

- [ ] Write failing role/resource-resolution tests.
- [ ] Run RED.
- [ ] Implement role prose and runtime contracts.
- [ ] Run dry-run and focused execution/recovery gate.
- [ ] Verify older protocol and V1 checkpoint bytes remain unchanged.
- [ ] Commit `feat(re): register exhaustive analyst and verifier`.

## Execution Completion Gate

```bash
pytest -q tests/unit/test_re_v2_protocol_28_*.py \
  tests/unit/test_re_v2_protocol_22_execution.py \
  tests/unit/test_re_v2_protocol_25_budget.py \
  tests/unit/test_re_v2_protocol_25_recovery.py \
  tests/unit/test_re_v2_protocol_26_*.py
git diff --check
bash scripts/bash/dry-run.sh
```

This plan ends with a recoverable protocol-local execution engine. Durable L3-to-L4 orchestration, CLI selection/continue/shadow/status/materialization, installed-provider pilots, and real-workspace proof remain in the third implementation plan.
