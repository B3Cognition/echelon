# Controller Completion Outbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every controller route and terminal publication recover its bounded post-dispatch effects after a process restart without duplicate journals, timing events, checkpoint commits, context bytes, mining, routing, or token charges.

**Architecture:** A new `harness.squad_completion` module durably seals an exact bounded intent and receipt prefix. Every routed advance attests a pre-generated dispatch/completion ID and atomically commits a completion marker, with an external-publication marker when applicable. Recovery drains a receipt-backed monotonic completion state machine under the existing execution locks before either normal or manual phase logic.

**Tech Stack:** Python 3.11, dataclasses, pathlib/os/tempfile/fcntl/hashlib/json, existing Echelon state/routing attestation, Git checkpoint metadata, telemetry JSONL, pytest.

## Global Constraints

- The intent uses only existing prepared-result detached-value limits and canonical JSON of at most 4,194,304 bytes; receipts are at most 1,048,576 bytes.
- State stores only exact bounded identifiers/digests/enums and never raw provider output, stderr, arbitrary paths, or journal payloads.
- Routed dispatch ID equals completion ID and is routing-attested before `advance()`.
- Every route commits its completion marker in the original routing save; publication routes commit both applicable markers in that one save.
- Publication clearance and transition to the first completion step use one exact-CAS save.
- Completion steps move only to the immediate successor in the bound effect plan.
- Every effect has an intrinsic replay receipt; final marker removal requires all exact applicable receipts.
- Missing/malformed stages, markers, receipt prefixes, or diagnostics retain authority and block with a bounded code.
- Old state with neither marker remains valid; publication authority without completion authority blocks as `completion_missing`.
- Lock rank is Phase A execution → spec-run execution → publication → completion → journal → telemetry → state.
- TDD is mandatory for every production change; each task ends in a focused commit and independent review gate.

---

### Task 1: Exact Completion Marker, Intent, and Durable Stage

**Files:**
- Create: `src/harness/squad_completion.py`
- Create: `tests/unit/test_squad_completion.py`
- Modify: `src/harness/state_transaction_namespace.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`

**Interfaces:**
- Produces:
  - `PENDING_CONTROLLER_COMPLETION_KEY = "pending_controller_completion"`
  - `CompletionError(code: str)`
  - `CompletionMarker.to_dict() -> dict[str, object]`
  - `CompletionIntent`
  - `PreparedControllerCompletion`
  - `validate_pending_controller_completion(value: object) -> dict[str, object]`
  - `prepare_controller_completion(...) -> PreparedControllerCompletion`
  - `load_prepared_controller_completion(project_root, squad_dir, marker) -> PreparedControllerCompletion`
- Consumes: `validate_pending_external_publication()` and prepared-result bounded detachment rules.

- [ ] **Step 1: Write exact marker/namespace RED tests**

Add tests covering the exact seven marker fields, concrete `int` schema version, 32-hex completion ID, four 64-hex digests, origin enum, step enum, explicit null, extra fields, provider set/remove rejection, and trusted routing acceptance:

```python
VALID_COMPLETION_MARKER = {
    "schema_version": 1,
    "completion_id": "a" * 32,
    "intent_sha256": "b" * 64,
    "publication_binding_sha256": "c" * 64,
    "receipts_sha256": "d" * 64,
    "origin": "routed",
    "step": "journal",
}

@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: {**value, "extra": True},
        lambda value: {**value, "completion_id": None},
        lambda value: {**value, "step": "skipped"},
    ],
)
def test_completion_marker_is_exact(mutation):
    with pytest.raises(ValueError):
        validate_pending_controller_completion(
            mutation(VALID_COMPLETION_MARKER)
        )
```

- [ ] **Step 2: Run marker tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_completion.py \
  tests/kernel/test_prepared_phase_result.py \
  -k "completion_marker or pending_controller_completion"
```

Expected: FAIL because the module, key, and validator do not exist.

- [ ] **Step 3: Implement the exact marker and namespace reservation**

Use an exact-key validator and concrete types:

```python
_COMPLETION_MARKER_KEYS = frozenset(
    {
        "schema_version",
        "completion_id",
        "intent_sha256",
        "publication_binding_sha256",
        "receipts_sha256",
        "origin",
        "step",
    }
)

def validate_pending_controller_completion(
    value: object,
) -> dict[str, object]:
    if type(value) is not dict or frozenset(dict.keys(value)) != _COMPLETION_MARKER_KEYS:
        raise ValueError("pending controller completion has invalid fields")
    # Validate concrete scalar types and exact enums, then return a fresh dict.
```

Add the key to store-owned/provider-reserved/trusted-routing effect sets, but not trusted removal sets.

- [ ] **Step 4: Write durable intent RED tests**

Cover exact tagged unions, fixed effect order, duplicate/future effect rejection, detached-value depth/node/string/integer/finite-float limits, 4 MiB serialized limit, canonical digest reread, missing/corrupt intent, one completion directory only, initial exact empty receipts, symlink/type/path attacks, and discard idempotency.

Use both exact variants:

```python
publication_none = {"kind": "none"}
publication_external = {
    "kind": "external",
    "marker": VALID_PUBLICATION_MARKER,
}
route = {
    "kind": "routed",
    "from_phase": "phase3-plan",
    "to_phase": "phase3-consensus",
    "manual_phase_run": False,
    "record_completion": True,
}
```

- [ ] **Step 5: Run intent tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_squad_completion.py -k "intent or stage"
```

Expected: FAIL because completion preparation/loading is absent.

- [ ] **Step 6: Implement canonical stage preparation/loading**

Implement these immutable shapes:

```python
@dataclass(frozen=True)
class CompletionIntent:
    completion_id: str
    origin: str
    publication: dict[str, object]
    route: dict[str, object]
    effect_plan: tuple[str, ...]
    context_reason: str
    mine_phase_a: bool
    judgment_payload_sha256: tuple[str, ...]
    judgments: tuple[dict[str, object], ...]

@dataclass(frozen=True)
class PreparedControllerCompletion:
    marker: CompletionMarker
    intent: CompletionIntent
    _transaction_root: Path

    def discard(self) -> None: ...
```

Write `intent.json` and `receipts.json` through sibling temp files, flush/fsync, atomically replace, sync directories, reread, hash, and reject a canonical intent larger than 4,194,304 bytes.

- [ ] **Step 7: Run Task 1 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_completion.py \
  tests/kernel/test_prepared_phase_result.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 1**

```bash
git add src/harness/squad_completion.py \
  src/harness/state_transaction_namespace.py \
  tests/unit/test_squad_completion.py \
  tests/kernel/test_prepared_phase_result.py
git commit -m "feat: seal controller completion intents"
```

---

### Task 2: Attested Dispatch Identity and Exact State Machine

**Files:**
- Modify: `src/harness/prepared_phase_result.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/kernel/test_prepared_phase_result.py`
- Modify: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Consumes: Task 1 marker and typed intent.
- Produces:
  - `PreparedRoutingDecision.dispatch_id: str`
  - `SquadStateStore.handoff_external_publication(...)`
  - `SquadStateStore.advance_controller_completion(...)`
  - `SquadStateStore.record_controller_completion_failure(...)`
  - `SquadStateStore.complete_controller_completion(...)`

- [ ] **Step 1: Write dispatch-attestation RED tests**

Assert a pre-generated 32-hex dispatch ID changes the routing digest, tampering fails attestation, and `advance()` persists:

```python
{
    "dispatch_id": completion_id,
    "post_dispatch_complete": False,
    "completion_intent_sha256": marker["intent_sha256"],
    "completion_origin": marker["origin"],
    "completion_publication_binding_sha256": (
        marker["publication_binding_sha256"]
    ),
}
```

Also assert judgment hashes and completion binding match the typed intent.

- [ ] **Step 2: Run dispatch tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  -k "dispatch_id or post_dispatch_complete or completion_binding"
```

Expected: FAIL because dispatch IDs are generated inside `advance()`.

- [ ] **Step 3: Attest and persist the supplied dispatch ID**

Add `dispatch_id` to routing facts and `PreparedRoutingDecision`; default the low-level factory to a fresh `secrets.token_hex(16)` only when callers do not supply one. Make `advance()` use the attested value rather than generating another ID.

- [ ] **Step 4: Write exact-CAS state transition RED tests**

Cover:

- both applicable markers committed in the original route save;
- no-publication completion starts at its first effect;
- publication handoff clears publication + diagnostic and advances completion in one save;
- only the immediate intent-bound step is legal;
- receipt prefix digest must be old or exact current one-ahead;
- final clear requires every effect receipt;
- routed final clear updates exact `last_dispatch`;
- terminal final clear writes `last_terminal_completion` and `status: done`;
- malformed marker/intent/receipt and raw-marker mismatch write nothing;
- malformed existing diagnostics are replaced canonically under exact raw-marker CAS;
- `_save_unlocked` pre-save and save-then-raise ambiguity at every method.

- [ ] **Step 5: Run state-machine tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_squad_state.py \
  -k "controller_completion or publication_handoff or malformed_external"
```

Expected: FAIL because completion state APIs do not exist.

- [ ] **Step 6: Implement exact monotonic state APIs**

Each method loads under the state lock, validates the exact marker plus typed intent digest, permits one legal transition, saves once, and never invokes an external callback. Final routed state includes:

```python
last_dispatch.update(
    {
        "post_dispatch_complete": True,
        "completion_intent_sha256": marker["intent_sha256"],
        "completion_receipts_sha256": receipts_sha256,
        "completed_publication_binding_sha256": (
            marker["publication_binding_sha256"]
        ),
    }
)
```

Phase 4 adds active-source and published-postimage inventory digests. Terminal completion writes the exact bounded terminal receipt in the same save.

- [ ] **Step 7: Run Task 2 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/harness/prepared_phase_result.py \
  src/harness/squad_state.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py
git commit -m "feat: persist controller completion state"
```

---

### Task 3: Replay-Safe Journal Receipt and Shared Lock

**Files:**
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/journal_entry_validator.py`
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_executors.py`
- Modify: `scripts/bash/phase-timing.sh`
- Modify: `scripts/bash/post-dispatch-hormone-update.sh`
- Test: `tests/unit/test_squad_completion.py`
- Test: `tests/unit/test_journal_entry_validator.py`
- Test: `tests/unit/test-phase-timing.sh`

**Interfaces:**
- Produces:
  - `reasoning_journal_lock(squad_dir)`
  - `prepare_completion_journal_plan(intent, journal) -> JournalPlan`
  - `apply_or_verify_completion_journal(plan) -> dict[str, object]`
- Consumes: Task 1 receipt-prefix helpers.

- [ ] **Step 1: Write journal replay RED tests**

Cover unrelated-row preservation, provider spoofing of `id`/`timestamp`/`phase`/completion fields, exact content digest calculation excluding generated metadata, durable replace, crash after replace before receipt, exact-row adoption, partial/missing/duplicate ordinal, same-ID drift, malformed unrelated JSON, concurrent shell append under the shared lock, and parent-directory fsync.

- [ ] **Step 2: Run journal tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_completion.py \
  tests/unit/test_journal_entry_validator.py \
  -k "completion_journal or journal_lock"
```

Expected: FAIL because journal completion identity and shared lock are absent.

- [ ] **Step 3: Implement exact journal plan/apply**

Define the reserved row stamp:

```python
row["controller_completion"] = {
    "completion_id": completion_id,
    "entry_index": index,
    "content_sha256": content_sha256,
}
```

Strip provider metadata before digesting, validate existing rows under one `fcntl` lock, preserve unrelated serialized rows, write the whole result with temp/fsync/replace/fsync, and accept an existing exact batch without regeneration.

- [ ] **Step 4: Move every repository journal writer under the shared lock**

Refactor both Python `_write_journal_entries()` implementations to one helper. Make shell Python snippets acquire the same lock file before append/index update. Do not change the unrelated KB mutation journal.

- [ ] **Step 5: Run Task 3 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_completion.py \
  tests/unit/test_journal_entry_validator.py \
  tests/unit/test-phase-timing.sh
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/harness/squad_completion.py \
  src/harness/journal_entry_validator.py \
  src/harness/squad.py src/harness/squad_executors.py \
  scripts/bash/phase-timing.sh \
  scripts/bash/post-dispatch-hormone-update.sh \
  tests/unit/test_squad_completion.py \
  tests/unit/test_journal_entry_validator.py \
  tests/unit/test-phase-timing.sh
git commit -m "feat: make completion journals replay safe"
```

---

### Task 4: Completion-Tagged Timing and Dispatch-Bound Checkpoints

**Files:**
- Modify: `src/echelon/telemetry/model.py`
- Modify: `src/echelon/telemetry/phase_timing.py`
- Modify: `src/echelon/telemetry/store.py`
- Modify: `src/echelon/commit_messages.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `src/harness/squad_completion.py`
- Test: `tests/unit/test_phase_timing.py`
- Test: `tests/unit/test_phase_checkpoints.py`
- Test: `tests/unit/test_squad_completion.py`

**Interfaces:**
- Produces:
  - optional `PhaseTimingEvent.completion_id` and `effect_id`
  - `apply_or_verify_completion_timing(...)`
  - optional checkpoint `completion_id`
  - `create_or_recover_completion_checkpoint(...)`

- [ ] **Step 1: Write timing crash RED tests**

Inject a crash after tagged close, after tagged open, and before receipt update. Require exact completion/effect IDs, no duplicate telemetry events, rejection of same-ID field drift, and exact one-ahead receipt adoption.

- [ ] **Step 2: Run timing tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase_timing.py \
  tests/unit/test_squad_completion.py -k "completion_timing"
```

Expected: FAIL because timing events have no completion identity.

- [ ] **Step 3: Implement completion-tagged timing**

Add optional fields without changing legacy events. Completion effects use stable IDs:

```python
effect_id = f"{completion_id}:timing:{kind}:{phase}"
```

Search and validate that exact event before appending. A legacy untagged event cannot satisfy a completion receipt.

- [ ] **Step 4: Write checkpoint crash RED tests**

Cover commit-created/ledger-missing, exact ledger present, same phase under two completion IDs, a matching commit no longer at HEAD, duplicate matches in bounded history, no owned diff with intent-captured HEAD (`no_change`), no active spec (`not_applicable`), and crash before state step.

- [ ] **Step 5: Run checkpoint tests to verify RED**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase_checkpoints.py \
  tests/unit/test_squad_completion.py -k "completion_checkpoint"
```

Expected: FAIL because commits and ledger entries lack completion identity.

- [ ] **Step 6: Implement checkpoint receipts**

Add `completion_id` to commit metadata/trailer and checkpoint ledger records. Before committing, validate the exact ledger receipt or search at most 256 `--all` commits for one unique exact trailer identity. Use `no_change` only when current HEAD equals the intent-captured HEAD.

- [ ] **Step 7: Run Task 4 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_phase_timing.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_squad_completion.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/echelon/telemetry/model.py \
  src/echelon/telemetry/phase_timing.py \
  src/echelon/telemetry/store.py \
  src/echelon/commit_messages.py \
  src/harness/phase_checkpoints.py \
  src/harness/squad_completion.py \
  tests/unit/test_phase_timing.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_squad_completion.py
git commit -m "feat: receipt timing and checkpoint completion"
```

---

### Task 5: Frozen Context and Deterministic Mining Receipts

**Files:**
- Modify: `src/echelon/context_builder.py`
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/squad.py`
- Test: `tests/unit/test_context_builder.py`
- Test: `tests/integration/test_squad_context_memory.py`
- Test: `tests/unit/test_squad_completion.py`

**Interfaces:**
- Produces:
  - context builder `output_dir: Path | None`
  - `prepare_or_load_completion_context(...)`
  - `install_or_verify_completion_context(...)`
  - `CompletionMiningOutcome`
  - `apply_or_verify_completion_mining(...)`

- [ ] **Step 1: Write frozen-context RED tests**

Generate into a completion substage, persist the one-ahead plan, crash before visible install, then change the clock, state revision, and MemPalace inputs. Require restart to install the original bytes/digests without calling the generator. Cover partial visible install, target drift, missing/corrupt substage, and fixed-path enforcement.

- [ ] **Step 2: Run context tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_context_builder.py \
  tests/integration/test_squad_context_memory.py \
  tests/unit/test_squad_completion.py \
  -k "completion_context or frozen_context"
```

Expected: FAIL because context writes directly to visible paths.

- [ ] **Step 3: Implement completion context preparation/install**

Allow `build_run_context()` to read from the real run but write its fixed output set under an explicit completion-local output root. Persist exact bytes/digests/source revision/preparation time before any visible write, then install with preimage/postimage checks.

- [ ] **Step 4: Write mining outcome RED tests**

Cover `written`, `already_present`, `unavailable`, `failed`, and `not_applicable`; crash after deterministic drawer write before receipt; exact one-ahead adoption; canonical spec drift; malformed drawer IDs; and guaranteed advancement for best-effort terminal outcomes.

- [ ] **Step 5: Implement and verify mining receipts**

Return a bounded result instead of `None`, validate deterministic drawer IDs/spec digest, and never retry a receipted `unavailable` or `failed` outcome.

- [ ] **Step 6: Run Task 5 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_context_builder.py \
  tests/integration/test_squad_context_memory.py \
  tests/unit/test_squad_completion.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add src/echelon/context_builder.py \
  src/harness/squad_completion.py \
  src/harness/squad.py \
  tests/unit/test_context_builder.py \
  tests/integration/test_squad_context_memory.py \
  tests/unit/test_squad_completion.py
git commit -m "feat: freeze context and mining completion"
```

---

### Task 6: Controller Orchestration, Recovery Gate, and Ambiguous Saves

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `_prepare_controller_completion(...)`
  - `_drain_pending_controller_completion() -> CompletionRecoveryOutcome`
  - exact routed/terminal orchestration and structured manual-stop result.

- [ ] **Step 1: Write route and terminal orchestration RED tests**

Assert:

- every ordinary/skip/manual route commits completion in the original advance;
- publication routes commit both markers in that save;
- commander recovery commits journal+checkpoint completion and has no caller-side checkpoint;
- terminal begins with explicit terminal origin;
- completion validates before any additional visible publication;
- publication handoff is one state save;
- normal/manual entry drains publication then completion before status/phase logic;
- recovered manual completion stops without redispatch;
- terminal never consults stale route work;
- completed Phase 4 active-source/published-postimage digests suppress only an exact redundant terminal reconciliation.

- [ ] **Step 2: Run orchestration tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  -k "controller_completion or completion_recovery or terminal_reconciliation"
```

Expected: FAIL because controller completion is not orchestrated.

- [ ] **Step 3: Implement the structured drain loop**

Use a result independent of stale `last_dispatch`:

```python
@dataclass(frozen=True)
class CompletionRecoveryOutcome:
    recovered: bool
    origin: str
    manual_phase_run: bool
    completion_id: str
```

Under both execution locks: validate state key membership, load/validate intent and receipts, recover publication if present, drain one legal effect at a time, finalize, clean stages after fresh proof, then decide whether a manual runner may execute.

- [ ] **Step 4: Write save-then-raise/token RED tests**

Inject route and terminal `_save_unlocked()` functions that durably save then raise. Use nonzero deferred token usage and assert exact routing/dispatch/markers prove the commit, publication/completion resumes, `advance()` runs once, token total increments once, and no stale failure diagnostic is merged.

Inject the same ambiguity after publication handoff, every effect step, and final clear.

- [ ] **Step 5: Implement exact ambiguity resolution**

After a caught state error, reload and accept only:

- the exact old marker (operation did not win);
- the exact immediate next marker and receipt digest (operation won); or
- final marker absence plus exact durable routed/terminal receipt.

Any third state fails closed. Precommit cleanup proves neither marker nor incomplete bound dispatch authorizes either stage.

- [ ] **Step 6: Write terminal/legacy/orphan RED tests**

Cover:

- valid publication marker without completion marker → bounded `completion_missing`, no publish;
- malformed marker including explicit null;
- corrupt existing diagnostic replaced canonically;
- corrupt/missing completion intent preserves both authorities;
- routed orphan retained while matching dispatch is incomplete;
- orphan removed only after no marker and completed/nonmatching dispatch;
- final-clear fresh controller does not restage exact Phase 4 publication;
- active or published inventory drift does restage.

- [ ] **Step 7: Run Task 6 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_squad_completion.py
```

Expected: PASS.

- [ ] **Step 8: Commit Task 6**

```bash
git add src/harness/squad.py src/harness/squad_state.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_squad_completion.py
git commit -m "fix: recover controller completion before phase work"
```

---

### Task 7: Lock-Order and Full Fresh-Process Fault Matrix

**Files:**
- Modify: `src/harness/squad_completion.py`
- Modify: `tests/integration/test_squad_controller.py`
- Create: `tests/unit/test_controller_lock_order.py`
- Modify: `tests/unit/test_squad_completion.py`

**Interfaces:**
- Consumes: complete protocol.
- Produces: static/runtime lock-order assertion and full crash evidence.

- [ ] **Step 1: Write lock-order RED tests**

Assign ranks to every lock and assert no code path acquires a lower rank while a higher rank is held. Add a two-thread barrier test for every used nested pair; require both threads to complete without timeout and the reverse-order test helper to raise immediately.

- [ ] **Step 2: Implement lock-rank assertions**

Keep a thread-local rank stack in test/debug helpers and ensure state-store methods never invoke controller/external callbacks. All reasoning-journal writers use the shared rank-5 lock.

- [ ] **Step 3: Write full fresh-controller restart matrix**

For each boundary, discard the original controller instance and construct a new controller over the same project/run:

- route CAS with and without publication;
- every file operation;
- publication handoff;
- journal replace before receipt and before step CAS;
- tagged timing close/open;
- checkpoint Git commit and ledger write;
- frozen context preparation and each install operation;
- mining side effect and bounded outcome receipt;
- every step save-then-raise;
- final completion clear;
- manual and terminal variants.

Assert exact effect counts/identities, no duplicate route/token/commit/journal/timing/mining, and no runner before recovery.

- [ ] **Step 4: Run Task 7 GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_controller_lock_order.py \
  tests/unit/test_squad_completion.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add src/harness/squad_completion.py \
  tests/unit/test_controller_lock_order.py \
  tests/unit/test_squad_completion.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
git commit -m "test: prove controller completion crash recovery"
```

---

### Task 8: Expanded Verification and Final Report

**Files:**
- Modify: `.superpowers/sdd/final-fix-report.md`
- Modify: `docs/superpowers/plans/2026-07-23-controller-publication-outbox.md`

**Interfaces:**
- Consumes: Tasks 1–7.
- Produces: fresh blocker evidence and updated original-plan status.

- [ ] **Step 1: Run focused protocol suite**

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_completion.py \
  tests/unit/test_controller_lock_order.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  tests/unit/test_phase_timing.py \
  tests/unit/test_phase_checkpoints.py \
  tests/unit/test_context_builder.py \
  tests/integration/test_squad_context_memory.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

Expected: PASS.

- [ ] **Step 2: Run original expanded publication boundary suite**

```bash
.venv/bin/pytest -q \
  tests/unit/test_squad_publication.py \
  tests/unit/test_product_inputs.py \
  tests/integration/test_squad_context_memory.py \
  tests/kernel/test_prepared_phase_result.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_phase_checkpoints.py
```

Expected: PASS.

- [ ] **Step 3: Run compile/static checks**

```bash
.venv/bin/python -m py_compile \
  src/harness/squad_completion.py \
  src/harness/squad.py \
  src/harness/squad_state.py \
  src/harness/prepared_phase_result.py
git diff --check
```

Expected: both commands exit 0. Run Ruff if installed; otherwise record exact unavailability.

- [ ] **Step 4: Update report and original plan**

Record exact commits, test totals, crash boundaries, lock-order evidence, and independent review findings. Mark original Task 5 as superseded by and completed through this plan; do not retain the old one-marker instructions as executable guidance.

- [ ] **Step 5: Commit Task 8**

```bash
git add .superpowers/sdd/final-fix-report.md \
  docs/superpowers/plans/2026-07-23-controller-publication-outbox.md
git commit -m "docs: report durable completion recovery"
```
