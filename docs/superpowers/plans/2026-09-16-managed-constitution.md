# Managed Constitution implementation plan

> Use superpowers:executing-plans inline, test first, with independent read-only review.

**Goal:** Continue managed WHY1 through guarded publication of the canonical
workspace constitution to the existing WHAT boundary.

**Architecture:** Reuse selected producer operations, Prosaic inspection turns,
receipts, candidate review, guarded Squad publication and completion recovery.
The registered identity source remains spec-only; the canonical constitution is
an exactly captured additional write/read target, not a new identity authority.

**Tech stack:** Existing Python, SQLite, Prosaic and pytest.

**Spec:** User approved the inline shared-file boundary on 2026-09-16: existing
guarded publisher/recovery for `.echelon/constitution.md`, neutral providers and
unchanged legacy behavior. This records that approved design, not another rollout.

## Constraints

- Exactly one host-selected shared target; no model-selected paths or `.echelon`
  directory write authority. No canonical write before accepted semantic review.
- CHIEF stewardship through neutral Constitution producer/reviewer contracts;
  no direct filesystem tools or provider-native role lookup.
- Create if absent. Preserve a valid existing constitution byte-for-byte; a new
  spec does not authorize a shared-policy amendment. Invalid existing text blocks.
- No identity allocation, revision or spec-scoped ID references in shared policy.
- Existing attempts, cumulative budgets, source guards, checkpoint/context and
  completion receipts remain owners. No legacy fallback or new publication engine.
- No installation, migration, live models, push/merge, original smoke workspace,
  legacy build or AGENTS.md/CLAUDE.md changes. Skip optimization remains deferred.

## 1. Closed producer and selected state

Files: `discovery_constitution.py`, `discovery_producer.py`,
`discovery_semantics.py`, `discovery_candidate.py`, `discovery_operation_state.py`,
`discovery_reservations.py`, `discovery_receipts.py`, `discovery_turns.py`,
`squad_state.py`; `tests/unit/test_managed_constitution_contract.py`.

Interface: `prepare_constitution(source, *, expected_state)` binds the exact
released WHY1 source once under full-state CAS. Flat `managed_constitution_source`,
operation and turn markers use the existing owner methods and private receipts.
Assignment v5 has only `constitution.md`, no editable/assigned IDs, and empty
proposal lists. Three existing propose/author/review turns preserve shared recovery.

- [x] RED: accepted state selects once; stale/generic mutation rejects; isolated
  operation consumes one dispatch; proposal cannot allocate; candidate cannot
  replace existing policy, retain markers or embed spec-scoped IDs.
- [x] Implement closed selection/contract and run the focused tests to GREEN.

## 2. Capture, publication and retained proof

Files: `discovery_operation.py`, `discovery_publication.py`,
`discovery_completion.py`, `discovery_constitution.py`, and two neutral roles.

Capture exact accepted WHY1 ancestry and WHY1→Constitution route, canonical file
including absence, template, upstream spec and runtime/human context. Map only
logical `constitution.md` to the canonical path. Candidate/history operations stay
empty; existing spec/graph publication remains guarded. Closed completion v12
binds the exact WHY1 source. Authenticate source, candidate and history equality,
canonical pre/postimage, and all receipts on recovery. Retained context projection
verifies canonical postimage before using its historical preimage for admission.

- [x] RED: real scripted controller reaches Constitution but cannot author/publish.
- [x] Implement same-owner capture/publication, including existing-file modes.
- [x] Reject source/target/template drift, broadened targets and proof downgrade.

## 3. Controller and acceptance

Files: `squad.py`; `tests/unit/test_managed_constitution.py`.

Extend internal `through_phase` to Constitution, preserving existing selections.
Authenticate input before `prepare_constitution`; set `constitution_status=exists`
only in the accepted publication completion. Follow the existing always→WHAT
transition; stop before unsupported WHAT execution. Include Constitution in
cumulative dispatch validation; exact restart must not redispatch or recharge.

```python
result = controller(case, executor).run(managed_discovery=selected)
assert result.phase == "phase1-what"
assert (root / ".echelon/constitution.md").read_text() == CONSTITUTION
assert not (root / "specs/game/constitution.md").exists()
assert store.load()["token_usage"] == 105  # five producers, three 7-token turns
```

- [x] GREEN: Codex and Claude, existing shared file, normal native routing.
- [x] Interrupt publication/identity/completion and resume with exact calls,
  history, original producer state and shared-file content preserved.
- [x] Run affected regressions and legacy Constitution tests; independent review.
- [x] Record exact evidence and commit the verified checkpoint; continue required
  convergence without claiming whole-spec or installed/live acceptance.

## Implementation findings and verification

- Initial contract RED: three tests failed on missing Constitution producer and
  state selection. Initial real-controller RED rejected the new through-phase.
- Full-flow verification exposed the context generator's spec-relative-only
  mapping. It now uses the same fixed publication target and captured shared
  postimage, without live discovery or a second writer.
- Independent review identified missing Constitution→WHAT proof enforcement;
  a failing route test reproduced it before the existing completion validator
  gained that exact destination check.
- Review also identified that the existing checkpoint reader verified only
  spec blobs. Its read-only verifier now accepts explicit additional file images;
  Constitution supplies only the canonical postimage. Three real-Git tests cover
  correct, missing and wrong committed policy with correct live bytes.
- The context interruption hook was narrowed to the actual context effect after
  review. The final recovery test passed all seven boundaries in one run:
  accepted, staged, routed, identity applied, context, completed and released.
  It also rejects canonical/template drift after review and canonical drift after
  release. **1 passed in 246.77s**; 15 scripted turns, 105 cumulative tokens and
  one Constitution dispatch remain exact.
- Contract/semantic/legacy batch: **183 passed in 9.98s**.
- Checkpoint/completion/turn/operation batch: **420 passed in 82.58s**.
- Final two-provider full-flow and original WHY1 regression batch:
  **3 passed, 43 deselected in 477.63s**. Codex creates the canonical policy;
  Claude preserves existing bytes and mode. Both authenticate released ancestry,
  reject forged proofs and canonical tampering, and restart without redispatch.
  The original guided/checkpointed Codex WHY1 selection still stops before
  Constitution. With the batches above this is **607 distinct selected passing
  tests**, not a full-suite or live-provider claim.
- Independent read-only review is closed; no remaining production findings.
  Whitespace validation passed. No install, migration, live provider, push or
  merge was performed. Managed execution stops before WHAT; remaining producer
  families, whole-run identity acceptance and public activation remain unfinished.
- Verification history:
  An earlier superseded run passed both provider cases before being deliberately
  interrupted; it is not used as final verification evidence.
