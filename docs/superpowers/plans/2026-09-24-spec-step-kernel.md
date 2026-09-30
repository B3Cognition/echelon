# Phase A Spec-Step Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Phase A's overlapping completion and publication protocols with one current-only durable spec-step kernel while preserving secure publication and observable spec-authoring behavior.

**Architecture:** New runs carry one exact state version and at most one `pending_spec_step`. A sealed step binds routing, optional publication, ordered effects, receipts, and the final state postimage; recovery drains it before provider dispatch. `SquadStateStore` owns atomic persistence, `spec_step` owns durable documents, `spec_step_kernel` owns recovery, `spec_step_effects` owns effect application, and the existing publication transaction remains the secure filesystem boundary.

**Tech Stack:** Python 3.11, dataclasses, strict canonical JSON, descriptor-safe filesystem operations, pytest, Git.

**Spec:** `docs/superpowers/specs/2026-09-24-spec-step-kernel-design.md`

## Global Constraints

- Support only newly created Phase A state with `phase_a_state_version == 1`.
- Missing, older, or unknown versions fail closed with `echelon spec run --reset` guidance; never migrate them.
- Preserve CLI arguments, phase-graph semantics, provider-result validation, routing CAS, modes, and project topology support.
- Preserve `SquadPublicationTransaction` manifest, target-drift, pinned-descriptor, atomic-write, fsync, and postimage protections.
- Never redispatch a provider while `pending_spec_step` exists.
- Never reconstruct a missing authoritative intent, receipt, or publication stage.
- Never write old and new durable markers for the same phase completion.
- Do not create a generic workflow framework or change Delivery or RE.
- Every production task starts with behavioral RED, finishes green, and receives an independent commit.

Before Task 1, bind the implementation baseline to the reviewed plan commit and persist it outside the working tree so later verification does not depend on a shell session:

```bash
implementation_base=$(git rev-parse HEAD)
printf '%s\n' "$implementation_base" > "$(git rev-parse --git-dir)/last-s5-base"
```

## Review Focus

- An unversioned or future-version run blocks before migration, provider construction, or dispatch; Task 1 pins this.
- A saved-then-raised state write is adopted on retry without repeating an external effect; Tasks 3-5 pin this.
- A drifted publication postimage blocks without overwrite or false receipt adoption; Task 5 pins this.
- Manual replay recovers its pending step and stops without another provider dispatch; Task 6 pins this.
- A fully receipted step with a failed final commit retries only the commit; Tasks 4, 7, and 8 pin this.

---

### Task 1: Enforce the Current-Only Phase A State Version

**Files:**
- Create: `src/harness/phase_a_state_version.py`
- Modify: `src/harness/squad_state.py:4998-5100`
- Modify: `src/echelon/spec_service.py:5272-5354`
- Modify: `src/harness/squad.py:953-1040, 6894-6917, 7890-7910, 8652-8672`
- Test: `tests/unit/test_phase_a_state_version.py`
- Test: `tests/kernel/test_squad_state.py`
- Test: `tests/unit/test_spec_service_boundary.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `CURRENT_PHASE_A_STATE_VERSION: Final[int] = 1`.
- Produces: `UnsupportedPhaseAStateError(version: object)`.
- Produces: `require_current_phase_a_state(state: Mapping[str, object]) -> None`.
- Consumes: fresh state created only by `SquadStateStore.initialize(...)`.

- [ ] **Step 1: Write failing version-boundary tests**

Create exact current, missing, old, future, and non-integer cases:

```python
@pytest.mark.parametrize("version", [None, 0, 2, "1", True])
def test_non_current_phase_a_state_is_rejected(version: object) -> None:
    state = {} if version is None else {"phase_a_state_version": version}
    with pytest.raises(UnsupportedPhaseAStateError) as error:
        require_current_phase_a_state(state)
    assert error.value.version is version
```

In `test_spec_service_boundary.py`, construct an existing unversioned run and assert `run_spec(...)` exits before `SquadCliProvider` construction, leaves `state.json` byte-identical, and prints `echelon spec run --reset`. Add a future-version variant. In `test_squad_controller.py`, call `SquadController.run()` directly and assert the provider is not called.

- [ ] **Step 2: Run the version tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_phase_a_state_version.py tests/unit/test_spec_service_boundary.py \
  tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py \
  -k 'phase_a_state_version or unversioned or future_version' -x
```

Expected: collection fails because `harness.phase_a_state_version` does not exist.

- [ ] **Step 3: Add the exact version validator**

```python
CURRENT_PHASE_A_STATE_VERSION: Final[int] = 1

class UnsupportedPhaseAStateError(ValueError):
    def __init__(self, version: object) -> None:
        self.version = version
        super().__init__(
            "unsupported Phase A run state; restart with echelon spec run --reset"
        )

def require_current_phase_a_state(state: Mapping[str, object]) -> None:
    version = state.get("phase_a_state_version")
    if type(version) is not int or version != CURRENT_PHASE_A_STATE_VERSION:
        raise UnsupportedPhaseAStateError(version)
```

Add the version to `SquadStateStore.initialize()`. In `spec_service._cmd_run`, validate non-fresh state immediately after `load()` and before missing-phase, authoring-mode, stack-contract, or input migrations. Remove those unreachable legacy mutations. Guard public controller entry points too, so direct callers cannot bypass the rule.

- [ ] **Step 4: Update current-run fixtures without weakening the guard**

Add `phase_a_state_version: 1` to fixtures representing newly created runs. Historical-state tests must now assert rejection or use reset; do not add a test-only bypass.

```bash
rg -n '"run_id"|state_store\.save\(' \
  tests/integration/test_squad_controller.py \
  tests/integration/test_human_input_routing.py tests/kernel/test_squad_state.py
```

- [ ] **Step 5: Run the state-version partition**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_phase_a_state_version.py tests/unit/test_spec_service_boundary.py \
  tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py \
  tests/integration/test_human_input_routing.py -x
```

Expected: PASS, including provider-not-called assertions.

- [ ] **Step 6: Commit**

```bash
git add src/harness/phase_a_state_version.py src/harness/squad_state.py \
  src/echelon/spec_service.py src/harness/squad.py \
  tests/unit/test_phase_a_state_version.py tests/unit/test_spec_service_boundary.py \
  tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py \
  tests/integration/test_human_input_routing.py
git commit -m "feat: require current Phase A run state"
```

---

### Task 2: Add Sealed Spec-Step Documents

**Files:**
- Create: `src/harness/spec_step.py`
- Create: `tests/unit/test_spec_step.py`
- Reference: `src/harness/squad_completion.py:90-1660`
- Reference: `src/harness/squad_publication.py:53-1754`

**Interfaces:**
- Produces: `SpecStepError`, `SpecStepFailure`, `SpecStepMarker`, `SpecStepIntent`, `PreparedSpecStep`, and `SpecStepEffectReceipt`.
- Produces: `prepare_spec_step(...) -> PreparedSpecStep`.
- Produces: `load_prepared_spec_step(squad_dir: Path, marker: object) -> PreparedSpecStep`.
- Produces: `append_spec_step_receipt(prepared, receipt) -> PreparedSpecStep`.
- Produces: `discard_unreferenced_spec_step(squad_dir, marker) -> None`.

- [ ] **Step 1: Write failing document and outbox tests**

Cover canonical preparation/reread, exact marker fields, detached views, duplicate-key JSON, oversized documents, non-regular files, symlinked outbox, replaced transaction roots, idempotent discard, and one-ahead receipts:

```python
def test_prepare_spec_step_seals_one_exact_intent(tmp_path: Path) -> None:
    prepared = prepare_spec_step(
        tmp_path,
        step_id="a" * 32,
        origin="routed",
        expected_state_revision=7,
        expected_previous_dispatch_sha256="b" * 64,
        route={"from_phase": "phase1", "to_phase": "phase2", "manual": False},
        effects=("publication", "journal"),
        publication={"schema_version": 1, "transaction_id": "a" * 32,
                     "manifest_sha256": "c" * 64},
        final_state={"phase_a_state_version": 1, "phase": "phase2"},
        provenance={"prepared_result_sha256": "d" * 64},
    )
    assert prepared.marker.step_id == "a" * 32
    assert prepared.marker.cursor == "publication"
    assert prepared.intent.effects == ("publication", "journal")
    assert load_prepared_spec_step(tmp_path, prepared.marker.to_dict()).marker \
        == prepared.marker
```

Also prove failure attempts are bounded to `0..1_000_000`, only the cursor-named effect may be appended, and append returns a marker at the next effect.

- [ ] **Step 2: Run document tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_spec_step.py -x
```

Expected: collection fails because `harness.spec_step` does not exist.

- [ ] **Step 3: Implement exact immutable types**

```python
SpecStepOrigin = Literal["routed", "terminal", "resolution"]
SpecStepEffect = Literal[
    "publication", "journal", "timing", "quality", "checkpoint",
    "context", "mining", "retarget", "commit",
]

@dataclass(frozen=True)
class SpecStepMarker:
    schema_version: int
    step_id: str
    intent_sha256: str
    receipts_sha256: str
    cursor: SpecStepEffect
    origin: SpecStepOrigin
    publication_binding_sha256: str | None
    failure: SpecStepFailure | None

@dataclass(frozen=True)
class SpecStepEffectReceipt:
    step_id: str
    effect: SpecStepEffect
    postimage_sha256: str
    payload: Mapping[str, object]
```

`SpecStepIntent` and `PreparedSpecStep` expose detached route, publication, final-state, provenance, and receipt views backed by canonical bytes. Follow existing bounded-read, atomic-write, directory-identity, fsync, and cleanup patterns, using `.spec-step-outbox/{step_id}/intent.json` and `receipts.json`.

Reject duplicate or out-of-order effects, explicit `commit` before the final cursor, a publication effect without a marker, and a marker without a publication effect.

- [ ] **Step 4: Run document and adjacent durability tests**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step.py tests/unit/test_squad_completion.py \
  tests/unit/test_squad_publication.py tests/unit/test_squad_publication_inspection.py -x
```

Expected: PASS; production routing remains unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/harness/spec_step.py tests/unit/test_spec_step.py
git commit -m "feat: add sealed Phase A spec steps"
```

---

### Task 3: Add Atomic Spec-Step State Transitions

**Files:**
- Modify: `src/harness/state_transaction_namespace.py`
- Modify: `src/harness/squad_state.py:969-1058, 5320-5734, 5777-7195`
- Create: `tests/kernel/test_spec_step_state.py`
- Modify: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces: `PENDING_SPEC_STEP_KEY = "pending_spec_step"`.
- Produces: `SquadStateStore.begin_spec_step(prepared, *, snapshot) -> None`.
- Produces: `SquadStateStore.record_spec_step_failure(marker, *, effect, code) -> None`.
- Produces: `SquadStateStore.advance_spec_step(current, advanced) -> None`.
- Produces: `SquadStateStore.complete_spec_step(prepared) -> AdvanceReceipt`.

- [ ] **Step 1: Write failing atomic-transition tests**

Cover exact begin CAS, stale revision, saved-then-raised begin, bounded failure replacement, wrong-marker failure, one-ahead cursor movement, receipt mismatch, saved-then-raised advance, exact final commit, saved-then-raised final adoption, and denial of ordinary marker removal.

```python
def test_complete_spec_step_installs_postimage_and_clears_marker(
    current_store: SquadStateStore,
    prepared_commit_step: PreparedSpecStep,
) -> None:
    receipt = current_store.complete_spec_step(prepared_commit_step)
    state = current_store.load()
    assert state["phase"] == "phase2"
    assert "pending_spec_step" not in state
    assert state["last_dispatch"]["dispatch_id"] \
        == prepared_commit_step.marker.step_id
    assert receipt.dispatch_id == prepared_commit_step.marker.step_id
```

- [ ] **Step 2: Run state tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/kernel/test_spec_step_state.py -x
```

Expected: collection fails because the store methods do not exist.

- [ ] **Step 3: Implement exact marker ownership**

Add `PENDING_SPEC_STEP_KEY` to store-owned keys and deny provider or ordinary routing removal authority. Implement the four interfaces exactly. Begin verifies revision and previous-dispatch identity under the exclusive lock. Completion accepts only cursor `commit`, verifies the exact prestate, installs the sealed postimage with one new revision/timestamp, and removes only the matching marker. A retry after saved-then-raised completion returns the existing `AdvanceReceipt` without another revision.

- [ ] **Step 4: Run state and routing contract tests**

```bash
../../.venv/bin/python -m pytest -q \
  tests/kernel/test_spec_step_state.py tests/kernel/test_squad_state.py \
  tests/kernel/test_prepared_phase_result.py -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/state_transaction_namespace.py src/harness/squad_state.py \
  tests/kernel/test_spec_step_state.py tests/kernel/test_squad_state.py
git commit -m "feat: add atomic Phase A step state"
```

---

### Task 4: Add the Single Recovery Kernel

**Files:**
- Create: `src/harness/spec_step_kernel.py`
- Create: `tests/unit/test_spec_step_kernel.py`
- Modify: `src/harness/spec_step.py`
- Modify: `src/harness/squad_state.py`

**Interfaces:**
- Consumes: Task 2 document functions and Task 3 store methods.
- Produces: `SpecStepRecoveryOutcome(recovered, blocked, step_id, origin, manual)`.
- Produces: `SpecStepEffectApplier.apply(prepared, state) -> SpecStepEffectReceipt`.
- Produces: `drain_pending_spec_step(state_store, squad_dir, effect_applier) -> SpecStepRecoveryOutcome`.

- [ ] **Step 1: Write failing recovery-boundary tests**

Use a recording in-memory effect applier with real state/outbox files. Cover no marker, one effect, every cursor, repeated drain, apply-before-receipt crash, receipt-written-before-state-advance crash, saved-then-raised advance, fully receipted commit failure, corrupt stage, missing stage, and bounded effect failure.

```python
def test_recovery_never_reapplies_a_receipted_effect(step_fixture) -> None:
    calls: list[str] = []
    applier = RecordingApplier(calls)
    first = drain_pending_spec_step(
        step_fixture.store, step_fixture.squad_dir, applier
    )
    second = drain_pending_spec_step(
        step_fixture.store, step_fixture.squad_dir, applier
    )
    assert first.recovered
    assert not second.recovered
    assert calls == ["journal"]
```

The fully receipted case patches only `complete_spec_step`; retry must invoke no effect and complete state once.

- [ ] **Step 2: Run kernel tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_spec_step_kernel.py -x
```

Expected: collection fails because `harness.spec_step_kernel` does not exist.

- [ ] **Step 3: Implement the bounded drain loop**

```python
@dataclass(frozen=True)
class SpecStepRecoveryOutcome:
    recovered: bool
    blocked: bool = False
    step_id: str = ""
    origin: str = ""
    manual: bool = False

class SpecStepEffectApplier(Protocol):
    def apply(
        self,
        prepared: PreparedSpecStep,
        state: Mapping[str, object],
    ) -> SpecStepEffectReceipt: ...
```

`drain_pending_spec_step()` reloads state and the exact prepared step after every durable change. Cursor `commit` calls only `complete_spec_step`. Other cursors call the applier, append or verify the receipt, then atomically advance the marker. Convert `SpecStepError` and bounded effect errors to one marker failure; do not catch `KeyboardInterrupt` or `SystemExit`.

- [ ] **Step 4: Run kernel and state tests**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step_kernel.py tests/unit/test_spec_step.py \
  tests/kernel/test_spec_step_state.py -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/spec_step.py src/harness/spec_step_kernel.py \
  src/harness/squad_state.py tests/unit/test_spec_step_kernel.py
git commit -m "feat: add Phase A step recovery kernel"
```

---

### Task 5: Adapt Existing Effects and Secure Publication

**Files:**
- Create: `src/harness/spec_step_effects.py`
- Create: `tests/unit/test_spec_step_effects.py`
- Modify: `src/harness/squad_completion.py:1661-3966`
- Modify: `src/harness/squad_publication.py:2396-2990`
- Modify: `src/harness/squad.py:1752-2158, 2617-2835`
- Test: `tests/unit/test_squad_completion.py`
- Test: `tests/unit/test_squad_publication.py`
- Test: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Consumes: `PreparedSpecStep` and `SpecStepEffectReceipt`.
- Produces: `PhaseASpecStepEffects.apply(prepared, state) -> SpecStepEffectReceipt`.
- Preserves: current journal, timing, quality, checkpoint, context, mining, retarget, and publication postimage validation.

- [ ] **Step 1: Write failing adapter tests for every effect**

Parameterize the canonical effects and assert exactly one low-level primitive call and one receipt bound to the step and effect:

```python
@pytest.mark.parametrize(
    "effect",
    ["publication", "journal", "timing", "quality", "checkpoint",
     "context", "mining", "retarget"],
)
def test_effect_adapter_returns_one_bound_receipt(effect_fixture, effect: str) -> None:
    prepared, effects = effect_fixture(effect)
    receipt = effects.apply(prepared, effect_fixture.state)
    assert receipt.step_id == prepared.marker.step_id
    assert receipt.effect == effect
```

Add publication success, publish-before-receipt recovery, target drift, marker/stage mismatch, and saved-then-raised outcome tests. Mutating a target after an uncertain write must raise bounded `target_drift` without another write.

- [ ] **Step 2: Run effect tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_spec_step_effects.py -x
```

Expected: collection fails because `PhaseASpecStepEffects` does not exist.

- [ ] **Step 3: Extract reusable effect primitives from completion lifecycle**

Move or generalize the current effect implementations so they consume sealed intent fields and an existing receipt rather than `CompletionMarker`. Preserve their filesystem algorithms and provide these names:

```python
apply_or_verify_step_journal(...)
apply_or_verify_step_timing(...)
apply_or_verify_step_quality(...)
create_or_recover_step_checkpoint(...)
install_or_verify_step_context(...)
apply_or_verify_step_mining(...)
apply_or_verify_step_retarget(...)
```

Keep internal receipt payloads unchanged and wrap them in `SpecStepEffectReceipt` only at the adapter boundary.

- [ ] **Step 4: Implement the explicit Phase A adapter**

`PhaseASpecStepEffects` receives project root, squad directory, phase graph, telemetry store, and the existing context-drawer loader. Its `apply()` uses a closed `if`/`elif` over the eight effects and rejects `commit`; it is not a registry.

For publication, load only the marker authenticated by the intent, call the existing `PreparedSquadPublication.publish()`, verify its exact postimage, and return a bounded receipt. Use `prepared.marker.step_id` as the publication transaction ID. Do not remove the old production path yet.

- [ ] **Step 5: Run effect and durability partitions**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step_effects.py tests/unit/test_squad_completion.py \
  tests/unit/test_squad_publication.py tests/unit/test_squad_publication_inspection.py \
  tests/integration/test_squad_controller.py \
  -k 'completion or publication or journal or timing or checkpoint or context or mining or retarget' -x
```

Expected: PASS; old production recovery remains available until cutover.

- [ ] **Step 6: Commit**

```bash
git add src/harness/spec_step_effects.py src/harness/squad_completion.py \
  src/harness/squad_publication.py src/harness/squad.py \
  tests/unit/test_spec_step_effects.py tests/unit/test_squad_completion.py \
  tests/unit/test_squad_publication.py tests/integration/test_squad_controller.py
git commit -m "refactor: adapt Phase A completion effects"
```

---

### Task 6: Cut Over Routed and Manual Phase Completion

**Files:**
- Modify: `src/harness/squad.py:2509-2586, 7579-8345, 8596-8944, 13296-13580, 14888-15369`
- Modify: `src/harness/squad_state.py:5320-5734`
- Modify: `src/harness/spec_step_effects.py`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/kernel/test_squad_state.py`

**Interfaces:**
- Produces: `SquadController._prepare_routed_spec_step(...) -> PreparedSpecStep`.
- Produces: `SquadController._drain_pending_spec_step() -> SpecStepRecoveryOutcome`.
- Removes routed/manual use of both old pending markers.

- [ ] **Step 1: Add routed and manual RED tests**

Prove one route stores `pending_spec_step` before an effect, never stores either old pending key, publishes only after state authority, and clears the marker only with final phase advancement. Add crash/recovery at every routed cursor and this manual case:

```python
def test_manual_replay_recovers_step_and_stops_without_redispatch(
    controller_fixture,
) -> None:
    controller, provider, store = controller_fixture.manual_pending_step()
    result = controller.run_single_phase("phase1-what")
    assert result.status == "running"
    provider.run.assert_not_called()
    assert "pending_spec_step" not in store.load()
```

- [ ] **Step 2: Run routed tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/integration/test_squad_controller.py \
  -k 'spec_step and (routed or manual)' -x
```

Expected: FAIL because routed paths still persist old completion authority.

- [ ] **Step 3: Seal one routed step before effects**

Build the final postimage from the prepared routing decision without calling `SquadStateStore.advance()`. Seal manual flag, conditional skip, checkpoint policy, token delta, judgments, and optional publication into the step. Allocate the step ID before publication staging so both use one identity. Begin once, drain through the kernel, and continue only after the marker clears. Manual replay returns after recovered or newly completed work.

- [ ] **Step 4: Run routed/manual and adjacent phase tests**

```bash
../../.venv/bin/python -m pytest -q \
  tests/integration/test_squad_controller.py tests/kernel/test_squad_state.py \
  tests/unit/test_squad_phase_checkpoints.py tests/unit/test_phase_a_readiness.py -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py src/harness/squad_state.py \
  src/harness/spec_step_effects.py tests/integration/test_squad_controller.py \
  tests/kernel/test_squad_state.py tests/unit/test_squad_phase_checkpoints.py
git commit -m "refactor: route Phase A through durable steps"
```

---

### Task 7: Cut Over Terminal Phase A Completion

**Files:**
- Modify: `src/harness/squad.py:10117-10385`
- Modify: `src/harness/spec_step_effects.py`
- Modify: `src/harness/squad_state.py`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_phase_a_readiness.py`

**Interfaces:**
- Produces: a terminal `PreparedSpecStep` with `origin == "terminal"`.
- Preserves: terminal publication, mining, retargeting, and exact done-state postimage.

- [ ] **Step 1: Add terminal crash-boundary RED tests**

Cover recovery before each terminal effect, after each durable receipt, and after final state commit. Include the narrow regression:

```python
def test_terminal_commit_failure_retries_only_commit(controller_fixture) -> None:
    controller, effects, store = controller_fixture.terminal_commit_failure()
    controller.run()
    recovered = controller.run()
    assert recovered.status == "done"
    effects.assert_no_completed_effect_replayed()
```

- [ ] **Step 2: Run the terminal tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/integration/test_squad_controller.py \
  tests/unit/test_phase_a_readiness.py -k 'terminal and spec_step' -x
```

Expected: FAIL because terminal completion still has its own recovery path.

- [ ] **Step 3: Express terminal completion as one spec step**

Replace `_publish_terminal_phase_a_artifacts_if_available` orchestration with a terminal step. Seal optional publication, mining and retarget effects plus the exact final `done` postimage before applying any effect. Use the same step ID for publication staging. Keep existing effect primitives and readiness semantics.

- [ ] **Step 4: Run terminal and readiness tests**

```bash
../../.venv/bin/python -m pytest -q tests/integration/test_squad_controller.py \
  tests/unit/test_phase_a_readiness.py -k 'terminal or readiness or spec_step' -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py src/harness/spec_step_effects.py \
  src/harness/squad_state.py tests/integration/test_squad_controller.py \
  tests/unit/test_phase_a_readiness.py
git commit -m "refactor: reconcile terminal Phase A with spec steps"
```

---

### Task 8: Cut Over Human Resolution and Managed Completion

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/spec_step_effects.py`
- Modify: `src/harness/discovery_completion.py`
- Modify: `src/harness/discovery_restoration_completion.py`
- Test: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_discovery_completion.py`
- Test: `tests/unit/test_discovery_restoration_completion.py`
- Test: `tests/unit/test_managed_alignment_answer_publication.py`
- Test: `tests/unit/test_managed_alignment_publication.py`
- Test: `tests/unit/test_managed_feasibility_publication.py`
- Test: `tests/unit/test_managed_strategy_publication.py`

**Interfaces:**
- Changes: `_HumanInputResolutionEffects.completion` returns `PreparedSpecStep | None`.
- Preserves: decision identity, managed locks/read-set validation, restoration behavior, and publication security.

- [ ] **Step 1: Add resolution and managed-flow RED tests**

Prove that a submitted decision creates exactly one step carrying the exact decision ID, and that replay after each effect boundary does not repeat publication, quality recording, context update, or restoration. Cover managed publication conflicts and restoration failures without adding a second recovery protocol.

- [ ] **Step 2: Run resolution tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_discovery_completion.py \
  tests/unit/test_discovery_restoration_completion.py \
  tests/unit/test_managed_alignment_answer_publication.py \
  tests/unit/test_managed_alignment_publication.py \
  tests/unit/test_managed_feasibility_publication.py \
  tests/unit/test_managed_strategy_publication.py \
  -k 'resolution or managed or restoration or human_input' -x
```

Expected: FAIL because these paths still prepare or recover completion independently.

- [ ] **Step 3: Seal resolution work into the common step**

Make `_HumanInputResolutionEffects.completion` return the prepared step when completion work exists. Seal quality, managed publication, context, restoration and final state into that step, using the exact submitted decision ID as authority. Retain existing managed locks and read-set checks inside their current adapters; do not move domain policy into the kernel.

- [ ] **Step 4: Run all resolution and managed-flow tests**

```bash
../../.venv/bin/python -m pytest -q \
  tests/integration/test_squad_controller.py \
  tests/unit/test_discovery_completion.py \
  tests/unit/test_discovery_restoration_completion.py \
  tests/unit/test_managed_alignment_answer_publication.py \
  tests/unit/test_managed_alignment_publication.py \
  tests/unit/test_managed_feasibility_publication.py \
  tests/unit/test_managed_strategy_publication.py -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py src/harness/squad_state.py \
  src/harness/spec_step_effects.py src/harness/discovery_completion.py \
  src/harness/discovery_restoration_completion.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_discovery_completion.py \
  tests/unit/test_discovery_restoration_completion.py \
  tests/unit/test_managed_alignment_answer_publication.py \
  tests/unit/test_managed_alignment_publication.py \
  tests/unit/test_managed_feasibility_publication.py \
  tests/unit/test_managed_strategy_publication.py
git commit -m "refactor: resolve Phase A input through spec steps"
```

---

### Task 9: Delete the Retired Phase A Protocols

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/squad_state.py`
- Modify: `src/harness/squad_completion.py`
- Modify: `src/harness/squad_publication.py`
- Modify: `src/harness/squad_publication_snapshot.py`
- Create: `tests/unit/test_spec_step_ownership.py`
- Modify: affected completion/publication/controller tests

**Interfaces:**
- Removes: `pending_controller_completion`, `pending_external_publication`, `external_publication_failure`, `controller_completion_failure`.
- Removes: the old completion outbox, intent, recovery and orphan-cleanup lifecycle.
- Retains: low-level effect primitives and descriptor-safe `SquadPublicationTransaction`.

- [ ] **Step 1: Add a structural ownership RED test**

Parse active production modules and assert that retired state keys and lifecycle entry points are absent, `squad_state` imports the sealed spec-step schema rather than completion/publication protocols, and `squad.py` contains no receipt-file or outbox-recovery mechanics. Allow the physical `.publication-outbox` and secure publication transaction explicitly.

- [ ] **Step 2: Run the ownership test to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_spec_step_ownership.py -x
```

Expected: FAIL while the retired protocols remain.

- [ ] **Step 3: Remove old protocol code and compatibility-only tests**

Delete the four retired keys, their failure lifecycles, completion outbox/intent/recovery code, and orphan cleanup that exists only for those formats. Keep current-version behavioral and recovery coverage. Break the direct `squad_publication` / `squad_publication_snapshot` import cycle if it still exists by moving shared immutable data to the narrowest existing schema module.

- [ ] **Step 4: Run structural and behavioral suites**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_step_ownership.py \
  tests/unit/test_spec_step.py tests/unit/test_spec_step_kernel.py \
  tests/unit/test_spec_step_effects.py tests/kernel/test_spec_step_state.py \
  tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_squad_completion.py tests/unit/test_squad_publication.py \
  tests/unit/test_squad_publication_inspection.py -x
```

Expected: PASS with no compatibility branches for old Phase A run state.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py src/harness/squad_state.py \
  src/harness/squad_completion.py src/harness/squad_publication.py \
  src/harness/squad_publication_snapshot.py tests/unit/test_spec_step_ownership.py \
  tests/unit/test_spec_step.py tests/unit/test_spec_step_kernel.py \
  tests/unit/test_spec_step_effects.py tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py tests/unit/test_squad_completion.py \
  tests/unit/test_squad_publication.py tests/unit/test_squad_publication_inspection.py
git commit -m "refactor: remove retired Phase A completion protocols"
```

---

### Task 10: Flatten the Controller Around One Step Loop

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_spec_step_ownership.py`

**Interfaces:**
- Produces: `SquadController._run_current_phase_step(*, mode, next_phase_override) -> SquadResult | None`.
- Meaning: `None` continues the controller loop; `SquadResult` is a terminal, blocked, or manual-stop result.

- [ ] **Step 1: Add public-behavior and structural RED tests**

Cover routed, manual, blocked, terminal and recovery outcomes through public controller entry points. Add an AST assertion that `_run_locked` contains no effect names, receipt operations, outbox mechanics, or retired completion helpers.

- [ ] **Step 2: Run the flattening tests to verify RED**

```bash
../../.venv/bin/python -m pytest -q tests/unit/test_spec_step_ownership.py \
  tests/integration/test_squad_controller.py -k 'controller_shape or public_step_loop' -x
```

Expected: FAIL because orchestration remains distributed across controller branches.

- [ ] **Step 3: Extract one current-phase step loop**

Make `_run_locked` perform startup recovery, call `_run_current_phase_step`, continue on `None`, and return otherwise. Keep phase-specific preparation in named helpers, but route every durable effect and state transition through the common kernel. Remove now-empty wrappers and duplicated branch plumbing.

- [ ] **Step 4: Run the complete focused S5 suite**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_service_boundary.py \
  tests/unit/test_phase_a_state_version.py \
  tests/unit/test_spec_step.py tests/unit/test_spec_step_kernel.py \
  tests/unit/test_spec_step_effects.py tests/unit/test_spec_step_ownership.py \
  tests/kernel/test_spec_step_state.py tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_discovery_completion.py \
  tests/unit/test_discovery_restoration_completion.py \
  tests/unit/test_managed_alignment_answer_publication.py \
  tests/unit/test_managed_alignment_publication.py \
  tests/unit/test_managed_feasibility_publication.py \
  tests/unit/test_managed_strategy_publication.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_a_readiness.py -x
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/squad.py tests/integration/test_squad_controller.py \
  tests/unit/test_spec_step_ownership.py
git commit -m "refactor: flatten Phase A step orchestration"
```

---

### Task 11: Document and Verify the S5 Cutover

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/simplification-control.md`
- Create: repository verification receipt under the repository's existing receipt path

- [ ] **Step 1: Update current-run documentation**

Document the single Phase A authority (`pending_spec_step`), state version 1, explicit reset requirement for old/unversioned state, publication as one step effect backed by the retained secure transaction, and the absence of migrations. Mark S5 implementation complete in the tracker only after the verification receipt exists.

- [ ] **Step 2: Run the structural removal check**

```bash
rg -n 'pending_controller_completion|pending_external_publication|external_publication_failure|controller_completion_failure' \
  src/harness tests/unit/test_spec_step_ownership.py
```

Expected: matches only in the ownership test's forbidden-name data, not active production code.

- [ ] **Step 3: Run the focused S5 suite again**

```bash
../../.venv/bin/python -m pytest -q \
  tests/unit/test_spec_service_boundary.py \
  tests/unit/test_phase_a_state_version.py \
  tests/unit/test_spec_step.py tests/unit/test_spec_step_kernel.py \
  tests/unit/test_spec_step_effects.py tests/unit/test_spec_step_ownership.py \
  tests/kernel/test_spec_step_state.py tests/kernel/test_squad_state.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_discovery_completion.py \
  tests/unit/test_discovery_restoration_completion.py \
  tests/unit/test_managed_alignment_answer_publication.py \
  tests/unit/test_managed_alignment_publication.py \
  tests/unit/test_managed_feasibility_publication.py \
  tests/unit/test_managed_strategy_publication.py \
  tests/unit/test_squad_phase_checkpoints.py \
  tests/unit/test_phase_a_readiness.py -x
```

Expected: PASS.

- [ ] **Step 4: Commit the candidate documentation**

```bash
git add AGENTS.md README.md docs/simplification-control.md
git commit -m "docs: record single Phase A step authority"
candidate_commit=$(git rev-parse HEAD)
candidate_tree=$(git rev-parse HEAD^{tree})
printf '%s %s\n' "$candidate_commit" "$candidate_tree"
```

Record both values in the verification ledger. Recover the baseline recorded before Task 1:

```bash
implementation_base=$(cat "$(git rev-parse --git-dir)/last-s5-base")
git cat-file -e "$implementation_base^{commit}"
```

- [ ] **Step 5: Run repository verification against the recorded base**

Use the repository's existing verification runner and the ledger's exact `implementation_base` value:

```bash
verification_log=$(mktemp)
../../.venv/bin/python scripts/merge_verification.py plan \
  --base "$implementation_base" --head "$candidate_commit" | tee "$verification_log"
../../.venv/bin/python scripts/merge_verification.py run \
  --base "$implementation_base" --head "$candidate_commit" | tee -a "$verification_log"
receipt_path=$(sed -n 's/^receipt: //p' "$verification_log" | tail -n 1)
test -n "$receipt_path"
test -f "$receipt_path"
```

Expected: the repository-required suite passes and emits a receipt bound to the candidate commit/tree and exact base.

- [ ] **Step 6: Record verification evidence**

Update `docs/simplification-control.md` with the candidate commit, tree, implementation base, exact focused command/result, repository verification result, and receipt path. Commit only the evidence update and force-add the ignored receipt when required by repository policy.

```bash
git add docs/simplification-control.md
git add -f "$receipt_path"
git commit -m "docs: record S5 verification evidence"
```

- [ ] **Step 7: Final audit**

Confirm a clean worktree; confirm the receipt identifies the verified candidate tree; inspect the branch diff from `implementation_base`; and request one strongest whole-branch review focused on state ownership, crash recovery, exactly-once effect adoption, secure publication preservation, and accidental compatibility code.
