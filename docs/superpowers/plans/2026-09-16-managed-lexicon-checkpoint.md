# Managed Lexicon and Phase 1 Checkpoint Implementation Plan

> For agentic workers: use superpowers:executing-plans, inline as requested.

**Goal:** Continue managed WHY2 through derived Lexicon validation and the native
Phase 1 checkpoint, stopping before Phase 2 execution.

**Architecture:** Extend existing managed producer rounds and sealed completion
proofs. Reuse native Lexicon and human-decision owners; keep the guarded publisher
as the sole canonical writer and the identity store as the sole ID authority.

**Tech Stack:** Python, pytest, neutral Prosaic roles, existing SQLite identity
authority and Squad file/completion transactions.

**Spec:** `docs/superpowers/specs/2026-09-16-managed-lexicon-checkpoint-design.md`

## Global constraints

- Implement inline in the existing isolated worktree.
- Stop before executing Phase 2.
- No installation, live migration, live model spending, push, merge, legacy build,
  AGENTS.md or CLAUDE.md changes.
- Preserve Codex/Claude neutrality, existing policies, identity history,
  cumulative accounting and recovery.
- All tests use the existing repository virtualenv and
  `-o tmp_path_retention_count=200 -o tmp_path_retention_policy=all`.
- Performance optimization is deferred; do not weaken retained ancestry checks.

## Task 1: Closed derivation contract

Files: `src/harness/discovery_lexicon.py`, `discovery_semantics.py`,
`discovery_producer.py`; `tests/unit/test_managed_lexicon_contract.py`.

Consumes: `DiscoveryAssignment`, existing reply decoding and identity adapters.
Produces: the `lexicon` producer assignment, no allocation/revision scope,
`validate_lexicon_routing(value)` and `validate_lexicon_artifacts(artifacts)`.

- [x] Add failing tests for the single derived output, exact DONE/FAIL routing,
  no controller state updates, no new/revised identities and exact replay binding.
  The positive reply is `routing={"verdict": "DONE", "state_updates": {}}` with
  `artifacts={"requirements.lexicon.md": <captured text>}`; additional paths,
  fabricated state and identity proposals must raise `ValueError`.
- [x] Run `pytest tests/unit/test_managed_lexicon_contract.py -q` with the global
  retention options and confirm failures name unsupported managed derivation.
- [x] Implement the closed producer schema and syntax contract through existing
  assignment/reply owners; leave grammar certification to the deterministic gate.
- [x] Re-run the contract plus existing semantic/WHAT/WHY2 contract regressions.

## Task 2: Retained derivation and publication

Status: in progress. Low-level retained-round/provider-receipt foundations and
the ordinary first-derivation handoff/publication are implemented. Repaired
rounds and accepted-debt inputs remain to be connected alongside the gate.

- [x] Verified incremental checkpoint: ordinary passing WHY2 → first derivation
  → guarded publication/checkpoint completion → stop at `phase1-lexicon`, for
  both scripted providers. This is not completion of Task 2 or the milestone.

Files: existing producer, operation, turn, receipt, publication, completion and
Squad state modules; neutral `echelon.lexicon-producer.md` and reviewer counterpart;
`tests/unit/test_managed_lexicon.py`.

Consumes: the closed contract, actual released predecessor and native quality/debt
prerequisite. Produces: authenticated retained derivation rounds and publication
of exactly the derived artifact plus the existing graph projection.

- [ ] Add failing first-derivation and repaired-round tests using real retained
  WHY2 completions and scripted replies, not hand-authored authority markers.
- [ ] Bind initial/repair rounds once through the existing state transaction,
  capture exact source/glossary/findings and inspect neutral roles via Prosaic.
- [ ] Extend receipt decoding and guarded publication to the narrow producer;
  authenticate reference integrity without asserting unearned grammar success.
- [ ] Verify source/ID/history preservation, out-of-scope refusal, changed-input
  refusal, interrupted publication and zero-call replay for both providers.

## Task 3: Provider-free Lexicon gate

Status: in progress. The first gate after ordinary passing WHY2/initial
derivation is implemented through report publication and native completion.
This increment deliberately stops at its repair or checkpoint handoff; it does
not yet execute repaired derivation, accepted-debt input or checkpoint approval.
Configured non-default artifact/source/glossary/report paths fail closed rather
than silently using the defaults. Disabled-gate/checkpoint continuation and the
complete gate fault/retry matrix remain unfinished.

- [x] Verified incremental checkpoint: ordinary initial derivation → captured
  native validation → guarded report/graph publication and completion → first
  repair or approval-checkpoint handoff. No successor execution is enabled.

Files: `src/harness/discovery_lexicon.py`, `spec_lexicon_gate.py`, existing
completion/controller integration; `tests/unit/test_managed_lexicon_gate.py`.

Consumes: actual accepted derivation, captured source/glossary/configuration and
native prior attempts. Produces: exact native gate result/report and a sealed
managed completion, without an LLM turn or identity revision.

- [ ] Add failing tests for pass, grammar failure, missing inputs, changed report
  and retries. Assert literal native outcomes: a failing validation increments
  attempts once; pass resets attempts; restart repeats neither validation charge
  nor provider work.
- [ ] Reuse existing captured-text validation and projection association, derive
  native state updates, and publish the exact report through the existing owner.
- [ ] Reuse native routing, no-progress and exhaustion checks; do not create a
  parallel repair policy or reopen WHAT from a grammar failure.
- [ ] Test gate-disabled routing, source/glossary drift and failure recovery.

## Task 4: Native Phase 1 checkpoint handoff

Files: `src/harness/discovery_checkpoint_resolution.py`, existing human-input,
completion and Squad owners; `tests/unit/test_managed_checkpoint_assess.py`.

Consumes: the authenticated managed gate or disabled-gate WHY2/debt route and the
existing checkpoint recommendation/resolution. Produces: durable native approve
or reject completion with retained proof, ending before Phase 2 execution.

- [ ] Add failing guided/semi/Banzai tests against the existing recommendation
  owner, including ordinary quality and exact accepted-debt authorization.
- [ ] Bind only native checkpoint outcomes to the existing publication/completion
  transaction. Preserve original decisions and resolver provenance on recovery.
- [ ] Verify stale quality/Lexicon/debt evidence refusal, no invented approval,
  no extra COMMANDER/provider calls and exact restart after each fault boundary.

## Task 5: Combined acceptance and closeout

Files: the four test modules above, convergence boundary and this verification
record. No rollout/configuration cutover.

- [ ] Run both scripted provider paths from released WHY2 through native checkpoint
  approval/rejection, including repaired derivation and accepted debt.
- [ ] Run targeted existing identity, completion, quality/debt, Lexicon and human
  decision regressions. Record exact commands/results; do not sum overlapping
  runs as a full-suite claim.
- [ ] Obtain independent read-only review; fix actionable findings test-first.
- [ ] Update the convergence boundary and commit only verified milestone work.

## Verification record

- Starting HEAD `cf03006c`; existing linked worktree, clean baseline.
- Pre-implementation Lexicon validator/projection/gate baseline: **32 passed in
  0.52s**. No installed workspace or live provider was used.
- Closed contract red: **15 failed, 3 passed** because the producer was not yet
  supported; green with existing semantic/spec/validator regressions: **149 passed
  in 0.67s**.
- Retained-round red: **5 failed** for unsupported selection. The exact retry test
  also caught and fixed initial selection being mistaken for a repair. Contract
  plus round regressions: **35 passed in 1.87s**.
- Provider-turn red: **6 failed, 1 passed** before roles/turn ownership existed.
  Neutral roles, Codex/Claude replay, changed input/role/provider/receipt refusal
  and forbidden control-root reads then passed. Eight interruption cases exercise
  the existing journal without repeating uncertain provider calls.
- Selected foundation regression: **325 passed in 18.00s** using
  `test_managed_lexicon_contract.py`, `test_managed_lexicon_rounds.py`,
  `test_managed_lexicon_turns.py`, `test_managed_spec_contract.py`,
  `test_managed_spec_rounds.py`, `test_discovery_semantics.py`,
  `test_discovery_turns.py`, `test_discovery_reservations.py`,
  `test_why1_tracker_parent.py`, `test_spec_lexicon_gate.py`,
  `test_element_artifact_lexicon.py`, and `test_lexicon_gates.py`, all under
  `tests/unit/`, with `-q` and the global retention options.
- Independent read-only foundation review found no actionable issues; reviewer
  separately ran **38 new tests** and **149 existing regressions**. These overlap
  the selected run, are not additional coverage totals, and do not prove the
  unfinished predecessor/publication/gate/checkpoint integration.
- Ordinary first-derivation corridor red: **1 failed in 330.92s**, after a real
  passing WHY2 completion, at the unsupported derivation selection. Fast entry
  and operation tests separately prove that structural parent markers do not
  authorize execution or mutate state/history.
- The retained corridor exposed a missing schema-8 entry in the reservation
  decoder after one accepted proposal turn. A focused empty-proposal test failed
  at that exact decoder, then passed with the existing reservation regressions:
  **79 passed in 8.42s**. The empty journal never allocates or changes the database.
- Current-code retained Codex continuation from that WHY2 fixture passed:
  remaining **2 scripted calls**, **168 cumulative tokens**, unchanged source
  files/history, real guarded publication/checkpoint completion, and zero-call
  restart at `phase1-lexicon`. No receipts or counters were reset.
- Closed v28 proof and detached, rehashed tamper checks passed against the real
  released fixture: wrong version/producer/parent, expanded writes, fabricated
  gate authority and identity proposals are refused. The real retained receipt
  mismatch also fails closed. This does not prove gate or repair completion.
- Host-computed exact UTF-8/CRLF source metadata was added test-first, avoiding
  model-computed digests. Contract suite: **19 passed in 0.21s**.
- Updated selected regression (the preceding file list plus
  `test_managed_lexicon.py`, excluding its two long corridor cases with
  `-k 'not managed_derivation_publishes'`): **330 passed, 2 deselected in 20.90s**.
- Fresh Claude first-derivation corridor: **1 passed in 461.45s**. This process
  started before the host-source-metadata addition; the fresh Codex run includes
  that addition. Both use scripted provider responses, real prerequisite phases
  and real publication/completion owners; neither spends live provider tokens.
- Incremental independent review found no actionable first-derivation issues.
  Reviewer completion/publication/reservation regression: **156 passed in
  248.42s**. Overlapping results are not summed into a full-suite claim.
- Fresh Codex first-derivation corridor with host source metadata: **1 passed in
  463.52s**. The standalone pytest commands selected
  `tests/unit/test_managed_lexicon.py::test_managed_derivation_publishes_only_projection_and_preserves_history[claude]`
  and its `[codex]` counterpart, each with `-xq` and the global retention options.
- Final current-code `assert_retained_lexicon` checks passed against both released
  fresh provider fixtures, including the detached rehashed tamper cases added
  while their long-running tests were already loaded. No provider calls or state
  mutations occurred during these final proof checks.
- The verified first-derivation slice is a local commit checkpoint. Continue
  the same approved plan with gate publication, repaired/debt inputs and native
  checkpoint resolution; do not reinterpret this checkpoint as installation or
  completion of the overall convergence work.

### Initial deterministic gate increment

- Starting commit `28476058`; existing isolated worktree, clean baseline.
- Captured evaluator red: **12 failed** for the missing write-free native gate
  boundary. The native validator and shared attempt policy now produce exact
  report bytes/state updates without project-file I/O. First green with existing
  native gate tests: **17 passed in 0.30s**. The I/O test was narrowed to project
  files after it initially also blocked loading the bundled grammar.
- Managed gate entry/corridor red: **2 failed** for unsupported selection.
  Initial capture admits only the real released derivation, authenticates its
  ordinary WHY2 ancestry and current quality authority, then seals exactly the
  controller report and regenerated graph. Passing projections additionally use
  the existing explicit source association/read-only identity candidate check.
- Closed v29 proofs retain captured inputs, unchanged history, empty identity
  operations, native result and routing prestate. Independent review exposed a
  destination-validation gap and an unbound saved iteration limit. Literal
  routing tests first failed **5 cases**; a real released-proof test also caught
  acceptance of a rehashed changed limit before the fix. Native exhaustion is
  now shared with ordinary Squad; the existing condition evaluator replays the
  exact admitted workflow transitions. Live and detached completion validation
  bind the destination, and state-aware decoding binds the actual run limit.
- Initial fresh Codex failure corridor: **1 passed in 482.97s**, before final
  proof hardening. The concurrent passing corridor stopped before publication
  because its already-loaded Squad caller used the earlier preparation
  signature. No authority or counters were reset. Current-code preparation and
  continuation from its retained derivation then passed with **zero calls**,
  **168 cumulative tokens**, current native passing evidence and exact restart.
- Current-code retained Claude failure gate likewise passed with zero calls.
  Current `assert_retained_gate` checks passed against both released outcomes:
  rehashed limit, wrong destinations, changed result, parent, prior attempts and
  version are refused. Captured-image checks also refused source, glossary,
  derived artifact and report drift for both outcomes without changing files.
- Current-code retained Codex fault check interrupted after real report
  publication/checkpoint creation but before the checkpoint effect receipt.
  Restart completed the same operation with **one** failed gate attempt,
  unchanged report/history, zero provider calls and an exact second restart.
  This is one real recovery boundary, not the unfinished full fault matrix.
- Selected regression before the final additional snapshot tests: **421 passed,
  4 deselected in 21.98s**. It used the preceding selected file list plus
  `test_managed_lexicon_gate.py`, `test_artifact_validation_snapshots.py` and
  `test_supplemental_identity_bundle.py`, excluding both long derivation and
  both long gate cases. Native controller regression:
  `tests/integration/test_squad_controller.py -k lexicon`: **54 passed,
  463 deselected in 26.91s**.
- Latest fast gate tests: **25 passed, 2 deselected in 0.85s**, including
  configured-path refusal, captured-versus-live source selection and validator
  outage without certification or report writes. Independent final read-only
  review found no further actionable issues, conditional on fresh corridors.
- Fresh post-hardening scripted Claude passing corridor:
  **1 passed in 499.38s**. Fresh scripted Codex failing corridor:
  **1 passed in 500.61s**. Commands selected
  `tests/unit/test_managed_lexicon_gate.py::test_managed_gate_pass_reaches_checkpoint_without_executing_it`
  and `::test_managed_gate_publishes_native_failure_once_without_provider_work`,
  each with `-xq` and the global retention options. Both include real predecessor
  phases, publication/completion, the final v29 proof checks and zero-call
  restart. The later-added captured source-drift checks were independently run
  against both retained outcomes as recorded above.
- Final selected regression using the same preceding command and exclusions:
  **428 passed, 4 deselected in 23.22s**. Existing completion, publication and
  reservation regression (`test_discovery_completion.py`,
  `test_discovery_publication.py`, `test_discovery_reservations.py`):
  **156 passed in 247.88s**. These overlapping runs are not a full-suite claim.

### Next continuation within the same approved scope

- Admit repaired derivation only from the actual released failed gate. Replace
  the explicit first-round-only guards with authenticated retained-round and
  prior-attempt checks; never reset attempts or rewrite the original receipt.
- Capture the controller report as exact read-only diagnostic evidence, not as
  a provider-editable identity definition. Compare the staged repaired artifact
  against that report for native no-progress detection before publication.
- Extend ordinary/debt parent admission only with the existing accepted-debt
  authorization and actual source-context head. Do not fabricate passing quality.
- Then complete disabled-gate routing and native checkpoint resolution, with
  guided/semi/Banzai policy and recovery coverage, stopping before Phase 2.
