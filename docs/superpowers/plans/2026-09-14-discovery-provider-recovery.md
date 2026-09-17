# Discovery Provider Recovery Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for approved inline execution. Independently review the completed checkpoint before committing.

**Goal:** Execute a selected discovery semantic step through the existing inspection interface with durable replies, bounded reads and restart-safe accounting, without activating Squad discovery.

**Architecture:** Reuse the reservation journal's secure file boundary for a separate provider receipt file. Protect its selection in SquadStateStore so losing a selected journal cannot reset the operation. Neutral Prosaic roles and the existing no-tools executor/read channel handle model interaction; the future discovery orchestrator still owns proposal/reservation/author/preview/review ordering and candidate acceptance.

**Tech Stack:** Python, pytest, ProsaicPromptLoader, BoundedReadChannel, existing inspection executor, existing durable state/file writers.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md`.

## Global Constraints

- Inactive component only: no CLI/default activation, live provider calls, installation, candidate publication, Squad completion or stopped smoke edits.
- Claude and Codex use the same neutral role and inspection interface. No native agents lookup or extra COMMANDER.
- Existing Phase A/run execution leases remain caller-owned. Already completed managed bootstrap and independent assignment spec/run/operation must agree with retained authority.
- Preserve six-digit-minimum/unbounded IDs and existing reservation journal schema/recovery behavior.
- Maximum 32 host reads plus a final turn, 300-second absolute step deadline, 1 MiB prompt and 256 KiB reply. Limits persist across restarts. A nine-step receipt ceiling is defensive, not the future durable three-attempt repair policy.
- Shared operation token/dispatch ceilings can tighten but never increase. Every saved intent counts conservatively; missing usage is explicit. Unknown external completion blocks all further dispatch for the operation.
- A validated review reply is not semantic approval, citation truth or publication authority. The later orchestrator must authenticate complete candidate/baseline/history/citation associations and dependency-domain admission.

## Task 1 — Shared secure receipt files and protected selection

**Files:** Create `src/harness/discovery_receipts.py`, `src/harness/discovery_turn_state.py`, `tests/unit/test_discovery_turns.py`; modify `src/harness/discovery_reservations.py`, its existing tests' fault-injection boundary, `src/harness/squad_state.py`, and the existing legacy guard/presence tests for the new state key.

**Interfaces:** `DiscoveryReceiptFile(run_dir, name)` owns the existing no-follow lock, pinned directory checks, bounded reads and compare-before-replace writes; names are restricted to the two discovery receipt families. The reservation owner retains its exact schema and semantic validation. `SquadStateStore.prepare_discovery_turns(marker)` attaches immutable `managed_discovery_turns` metadata only after completed bootstrap. Marker fields are integer schema_version 1, selected operation_id and binding_sha256; ordinary save/load cannot inject, change, remove or detach it from bootstrap.

- [x] Run existing reservation/bootstrap tests before extraction. Move only their file/lock machinery; keep allocator and source authentication in the reservation owner. Existing crash/link/directory tests must pass unchanged in behavior.
- [x] Add RED tests for protected provider-marker initialization, exact retry, missing bootstrap and generic mutation/removal. Implement the narrow owned transition and load/save validation.

```python
selected = state_store.prepare_discovery_turns(marker)
assert state_store.prepare_discovery_turns(marker) == selected
with pytest.raises(StateAdvanceError):
    state_store.save({key: value for key, value in selected.items() if key != "managed_discovery_turns"})
```

## Task 2 — Durable bounded semantic-step execution

**Files:** Create `src/harness/discovery_turns.py`; extend `tests/unit/test_discovery_turns.py`.

**Interface:** `run_discovery_step(project_root, state_store, executor, assignment, context, *, roots, check_inputs, forbidden_paths=(), token_budget=None, dispatch_limit=297, create=False) -> DiscoveryStepResult`. Result fields are `reply`, `reason`, cumulative `token_usage` (None when unknown), and cumulative `dispatch_count`. `check_inputs()` must recompute the independently assigned input fingerprint; the selected producer orchestrator owns that capture. Roots and exclusions, provider/configuration, role contents, bootstrap and retained source context bind the operation; assignment/context bind each step.

- [x] Add RED tests using real bootstrap, journal, state owner and bounded reader; script only external Prosaic inspection and the model executor. Test propose, author and review through the same host API for both provider IDs; preserve exact IDs and UTF-8 texts.
- [x] Persist the state marker before journal initialization and refuse missing journals on resume. Save step assignment/context digest and absolute deadline before dispatch. Before each model call save a pending record; save validated reply/usage before processing its host read or accepting its final result. Persist read responses separately and revalidate all completed reads and input fingerprints before another dispatch or replay.

```python
first = run_discovery_step(root, state_store, executor, assignment, context,
    roots={"spec": spec}, check_inputs=lambda: fingerprint, create=True)
again = run_discovery_step(root, state_store, executor, assignment, context,
    roots={"spec": spec}, check_inputs=lambda: fingerprint)
assert again.reply == first.reply
assert again.dispatch_count == first.dispatch_count
```

- [x] Reject malformed/blocked/provider-failed output without an automatic repair loop; persist known usage and failure. Unknown call completion or missing read receipt cannot be bypassed by a new dispatch ID. Reuse completed replies without recharging. Keep stdout bounds and fresh private working directories through the existing inspection executor.
- [x] Test interruptions around pending/result/read writes, executor exceptions, restart after response persistence, missing/corrupt/symlinked journals, changed roles/provider/configuration/inputs/read policy, stale admitted reads, finite/unknown/exhausted budgets, persisted tighter ceilings, read/deadline/step/dispatch limits and cumulative usage across producer/reviewer steps. Assert no accepted source/history writes.

## Task 3 — Review and checkpoint

- [x] Obtain independent read-only review; reproduce and fix demonstrated defects with RED regressions.
- [x] Run new tests plus reservation/bootstrap/state/semantic/inspection/fulfillment regressions and `git diff --check`. Record exact receipts and remaining integration duties in this plan and convergence/deferred records.
- [x] Commit on the existing branch, preserving the worktree. No merge, push, installation or positive Squad activation.

## Execution receipt

- Baseline reservation/bootstrap: **126 passed in 10.74s**. Extracted secure
  file/lock boundary: **63 reservation tests passed in 6.47s**; schema and allocator
  behavior stayed unchanged. New marker tests failed before implementation and
  then passed; six presence-only legacy-guard failures preceded its extension.
- Initial provider tests failed on the absent execution module. Real temporary
  bootstrap, Squad state, bounded reads and registry queries surround scripted
  external Prosaic inspection/model responses. Propose/author/review and replay
  use both provider IDs through the same host API. Mixed legacy/six-digit/
  seven-digit IDs, exact CRLF and non-ASCII author text survive receipt replay.
  SQL dumps and accepted-artifact checks prove no registry/history/source changes.
- Fault tests reproduced a final-reply recovery gap: a crash after reply storage
  could return it before post-response validation had completed. The separate
  final `accepted` receipt now records only completed transport/input/budget
  checks, not semantic approval. Missing final/read completion blocks; interrupted
  pending calls never repeat. Journal/header crashes, corruption, stale reads,
  bindings, explicit unknown usage and persistent ceilings are covered.
- Independent read-only review found role-loading/pre-dispatch deadline gaps;
  its recheck found the same gap after final input verification. Five RED tests
  preceded fixes: role loads receive remaining preparation time, new steps retain
  the entry deadline, incomplete steps retain their prior deadline, and expiry is
  checked after preparation/writes and before final acceptance. Completed final
  replies can still replay later without reopening their dispatch window.
- Final re-review reported **no remaining substantive findings**. It independently
  ran 66 discovery-turn tests in 17.23s before the final two additional exact-text
  replay cases; these change tests only, not the reviewed implementation.
- Final affected acceptance: **1,096 tests passed in 76.20s**, including all
  **68 discovery-turn tests**. Command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest \
  tests/unit/test_discovery*.py tests/unit/test_inspection*.py \
  tests/unit/test_host_serviced_inspection.py tests/unit/test_prosaic_prompt_loader.py \
  tests/unit/test_controlled_fulfillment*.py tests/unit/test_fulfillment_recovery.py \
  tests/unit/test_fulfillment_semantics.py tests/unit/test_element_identity_legacy_guard.py \
  tests/unit/test_durable_json.py tests/unit/test_durable_tree.py \
  tests/unit/test_controller_lock_order.py tests/kernel/test_squad_state.py -q --tb=short
```

`git diff --check` passed. This is not whole-branch or live-provider acceptance.
No provider adapter or neutral role changed. No installation, public/default
activation, stopped smoke edit, AGENTS.md/CLAUDE.md edit, legacy build change,
push or merge occurred. Work remains on the existing convergence worktree.

## Next checkpoint — unchanged integrated owner responsibilities

Wire complete input/domain capture and semantic ordering into the selected
discovery path using these receipts and existing reservation/candidate owners.
The orchestrator must authenticate exact candidate, baseline, history and cited
evidence; persist the real three-attempt repair unit before its first dispatch;
and use existing guarded Squad publication/completion and pending recovery.
These duties were not replaced by receipt checks or a model review verdict.
Both provider facades and guided/semi/banzai still need composed managed-discovery
acceptance; neither provider IDs in this fixture nor the nine-step ceiling prove it.
