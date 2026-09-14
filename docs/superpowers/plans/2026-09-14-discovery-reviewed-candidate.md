# Reviewed Discovery Candidate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the approved inline execution. Independently review before committing.

**Goal:** Join existing discovery turns, reservations and structural preview into a bounded, recoverable reviewed candidate, without publishing it or enabling public execution.

**Architecture:** The existing Squad state owner retains operation selection and consumes each attempt before dispatch. A discovery composition helper captures the selected source/input trees through the existing sealed inspector, sequences propose/reserve/author/preview/review, and reuses provider/reservation receipts on restart. It returns an exact reviewed candidate for the later existing Squad publication/completion integration, never another publication engine.

**Tech Stack:** Python, pytest, SquadStateStore, PreparedSquadPublication, IdentityStore, existing discovery semantic and recovery helpers.

**Spec:** `docs/superpowers/specs/2026-09-14-managed-discovery-integration-design.md` (approved).

## Global constraints

- Existing isolated convergence branch; no installation, live provider, rollout, migration, push, merge or stopped smoke edits.
- Caller owns Phase A/run leases. Completed bootstrap is required. No new allocator, publisher, provider adapter, provider prose or COMMANDER.
- Only existing discovery artifact roles, U/A create and same-subject revision. Preserve exact labels, subjects, captions, before-images and read-only dependencies.
- A selected operation binds immutable origin/findings, input/source/history fingerprint and edit scope. Initial attempt plus at most two automatic retries; begin each durably before its first proposal call. Reordered findings or changed candidate IDs do not select a new operation.
- Complete selected spec and caller-selected input trees are captured and rechecked. This helper does not establish that a runtime caller selected all configured RE/memory domains; positive Squad admission must prove that separately before invoking it.
- Existing no-tools turns, persistent budgets and receipt limits remain authoritative. A malformed or uncertain provider call blocks; semantic/structural rejection alone can consume a subsequent attempt. Repeated normalized findings plus scoped content stop early.
- Return values are not publication authority. Exact reviewed candidate/source/history associations must be authenticated again at existing Squad completion. No canonical artifact or accepted history mutation here.

## Task 1 — Protected operation and attempt transitions

**Files:** Create `src/harness/discovery_operation_state.py`; modify `src/harness/squad_state.py`, `src/harness/element_identity_legacy_guard.py`; create `tests/unit/test_discovery_operation.py`.

**Interfaces:** `SquadStateStore.advance_discovery_operation(binding, event, result=None)` owns `managed_discovery_operation`. Events are `prepare`, `begin`, `finish`. `prepare` binds a completed bootstrap, selection/scope and captured input fingerprint; `begin` consumes the next attempt; `finish` stores the exact candidate/findings digests and accepted/rejected disposition. Ordinary state writers cannot inject/change/remove the record. Presence alone blocks legacy execution.

- [x] Add failing transition tests for exact retry, immutable binding, owned writes, missing bootstrap, maximum three attempts and no begin after acceptance.
- [x] Implement pure validation/transition and wire the existing state owner. Test crash/retry through durable state APIs, not a substitute state store.

```python
state.advance_discovery_operation(binding, "prepare")
begun = state.advance_discovery_operation(binding, "begin")
assert begun["managed_discovery_operation"]["attempts"][0]["result"] is None
```

## Task 2 — Compose captured inputs through independent review

**Files:** Create `src/harness/discovery_operation.py`; add read-only cumulative usage observation to `src/harness/discovery_turns.py`; extend the new tests using real bootstrap, publisher inspection, allocation, candidate preview and recovery, scripting only external Prosaic/model responses.

**Interface:** `run_discovery_operation(project_root, state_store, executor, *, input_tree, artifact_paths, editable_revisions=(), unowned_writable_paths=(), intent, create=False, token_budget=None, dispatch_limit=297) -> DiscoveryOperationResult`. Result includes `status`, `reason`, cumulative usage/dispatch count and optional `ReviewedDiscoveryCandidate` (artifacts, operations, preview history, source fingerprint, exact review and candidate digest).

- [x] Capture the bootstrap-selected spec tree, explicit input tree and existing selected runtime templates using its empty sealed inspection transaction; confirm normal inspector exit and authenticate current managed source manifest. Require explicit known roles for every existing spec file; reject unsupported selected files rather than silently omit dependencies. Read-only selected inputs and template contents are included in the fingerprint; no fresh prose filesystem authority.
- [x] Persist operation/baseline selection and initialize the existing reservation journal explicitly. On resume require retained journals and exact selection; never reconstruct missing completed receipts. Consume attempt, call `run_discovery_step` with deterministic per-attempt IDs, bind proposal via `DiscoveryReservationJournal`, then author with the saved mapping.
- [x] Translate exact author texts with existing candidate helpers, look up existing subjects/revisions from retained history, and call `preview_identity_candidate` with explicit operations and edit scope. Structural rejection reaches bounded repair without reviewer dispatch or canonical writes.
- [x] Supply the reviewer with exact before/after texts, mapping, current/proposed history hashes and host-issued candidate/source citation tokens. Require each definition's assessment to cite its exact candidate occurrence; unknown/stale citation tokens block. Receipt context binds the whole candidate. Persist final outcome only after current inputs/history revalidate.
- [x] Repeat rejected attempts using immutable previous findings/candidate context; reuse unchanged proposal associations. Stop after three attempts or repeated normalized candidate content/findings. Resume reconstructs prior deterministic stages through saved replies without extra allocation/charges.

```python
result = run_discovery_operation(root, state, executor,
    input_tree="inputs", artifact_paths=("unknowns.md", "assumptions.md"),
    unowned_writable_paths=("unknowns.md", "assumptions.md"),
    intent={"kind": "create", "request": "Create an isometric game"}, create=True)
assert result.status == "reviewed"
assert result.candidate.artifacts[0].after_text
assert list((root / "specs/game").iterdir()) == []
```

- [x] Test both provider IDs, exact IDs/references, malformed/uncertain calls, structural/semantic rejection, no-progress/exhaustion, scope/subject/citation drift, changed inputs and missing journals, state-save interruptions, and replay with real reservation/history/source checks.

## Task 3 — Review, regressions and commit

- [x] Obtain independent read-only review; reproduce substantive findings before fixes.
- [x] Run discovery/state/candidate/source/publication/inspection/legacy guard regressions and whitespace checks. Record exact results and remaining runtime configuration, publication/completion and facade acceptance duties in the convergence records.
- [x] Commit the tested checkpoint on the existing branch. Retain the worktree; no push or merge.

## Explicit recovery boundary

An already selected operation with a missing reservation or provider journal
requires reconciliation, including an interruption during initial journal setup.
Resume does not infer whether an absent file was never initialized or was lost
after an uncertain side effect. Reissuing `create=True` cannot erase the durable
selection. Tests exercise both setup gaps with zero model calls and both blocked
entry modes. This intentionally conservative boundary is inherited from the
reservation/provider checkpoints; it is not automatic recovery of every setup
failure. Do not add an initializer reset to make this case proceed.

Once stage receipts exist, interrupted reservation handoff and final state saves
replay the exact work without duplicate allocation/calls/charges. A separate
read-only usage observation retains known provider totals on an unrelated early
source/template/reservation failure; it grants no permission to resume.

## Remaining integration duties

The tests invoke this composition under real Phase A and run execution leases,
but not through positive managed Squad dispatch. Input-tree evidence is explicitly
read-only reference material; selected spec files must use the existing discovery
roles. The runtime owner must still select all configured inputs (including
constitution/context and admitted typed evidence), prove unsupported RE/external
memory domains absent, authenticate the reviewed result at guarded publication,
and drain existing Squad completion/pending recovery. Returned artifacts include
read-only dependencies and must not all be treated as publication targets.

The existing sealed publisher is used only in a fixture to establish a genuine
accepted baseline for same-subject repair. No production publication engine or
completion selector is introduced. The actual provider facades, guided/semi/
banzai managed entry and the complete original renumbering/evidence regression
remain runtime acceptance duties, not claims made by this component checkpoint.

## Verification and review receipt

- Clean baseline: **148 tests passed in 21.76s** across provider turns,
  reservations and real graph/publication composition.
- Protected operation/attempt/legacy admission tests first produced 15 expected
  failures, then **107 passed** after the owned transitions. The initial composed
  tests failed on the missing execution module before implementation.
- Templates were initially absent from the host context; two failing tests
  preceded capture/supply of the existing selected runtime template files.
  Additional exact source citations initially failed; the host now issues their
  captured-byte tokens alongside the mandatory per-definition candidate token.
- Independent review reproduced two Important defects: early reconciliation
  dropped known provider accounting, and mutable caller intent could change a
  later attempt after selection. Three accounting regressions and a nested-intent
  regression preceded the fixes. The reviewer independently reran **41 operation
  tests**, **109 operation/provider tests** and **1,718 broader regressions**, and
  reported no remaining blocking findings.
- Parent affected acceptance: **1,734 passed in 87.50s**. The final test-only
  strengthening added real caller execution leases to every composition call;
  **41 passed in 18.85s** afterward. Exact broad command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest \
  tests/unit/test_discovery*.py tests/unit/test_element_identity_candidate*.py \
  tests/unit/test_element_identity_legacy_guard.py tests/unit/test_squad_source*.py \
  tests/unit/test_squad_publication*.py tests/unit/test_identity_graph_publication_composition.py \
  tests/unit/test_controller_lock_order.py tests/unit/test_durable*.py \
  tests/unit/test_inspection*.py tests/unit/test_host_serviced_inspection.py \
  tests/kernel/test_squad_state.py -q --tb=short
```

Final focused operation/provider/legacy-guard verification: **207 passed in
22.07s**. Whitespace checks passed. This is offline component acceptance, not a full-branch
test run, actual provider process execution, positive Squad admission or real-use
release evidence. No new deferred capability, role, provider adapter, installation,
default, AGENTS.md/CLAUDE.md, legacy build, stopped workspace, push or merge changed.
