# Repair refresh inputs and ordered execution

> Use superpowers:executing-plans; implement inline with test-first checkpoints and independent read-only review.

**Approved outcome:** Preserve immutable repair origin, bind actual accepted execution inputs once, compare dependencies rather than whole-run bookkeeping, refresh affected Synthesis then evaluate Tracker against the resulting accepted inputs. Stop before WHY1 re-review.

**Owners:** Existing producer rounds, Squad state CAS, captured-source inspection, retained completion proofs, operation/receipt/publication/completion owners. No new controller, allocator, attempt ledger or provider-specific prose.

## Checkpoint A: Dependency observation and protected binding

- [x] Compare authenticated accepted postimages, not the predecessor's preimages or whole-run operation fingerprint. Retain exact IDs, revisions, subjects and evidence. Ignore only derived graph/checkpoint/runtime render bookkeeping; full source guards still authenticate these bytes.
- [x] Retain a closed optional `execution_input` on a refresh row, separate from immutable `refresh.repair_source` and `source`. Bind via the existing state owner with full-state CAS; reject generic mutation, rebinding and premature Tracker admission.
- [x] Authenticate the current released repair and predecessor again even on exact retry; reject changed live artifacts, context, templates and proof. This checkpoint admits Synthesis's repair input only. Tracker binding must wait for the ordered execution checkpoint, so it cannot accidentally bind the pre-Synthesis repair as its final input.
- [x] Keep operation/turn slots null and controller refresh guard closed until checkpoint B; no attempts, allocation, phase, usage or receipt changes.
- [x] Test real repair admission, restart, mutation/CAS rejection, semantic differences, unchanged dependencies and both provider paths. Independent review and verification are complete; this tested boundary is the local checkpoint commit.

## Checkpoint B: Ordered refresh execution (still part of approved scope)

- [x] Select active Synthesis round without changing the original flat source/operation/turn marker; isolate new receipts with existing round journal support.
- [x] Bind actual inputs into completion proof and authenticate repair ancestry during replay/recovery. Permit read-only post-WHY1 context without broadening producer writes.
- [ ] Automatically execute changed Synthesis through existing owners, then evaluate Tracker from that accepted publication (or retain the same accepted head if Synthesis dependencies are unchanged). Never dispatch from the repair-origin field merely because it names the round. Preserve native caps, cumulative accounting and retry/no-progress/unknown-completion behavior during automatic refresh.
- [x] Implement the historical human-input prerequisite: pin WHY1 clarification ancestry to its accepted Tracker parent and preserve chronological Tracker→WHY1→new Tracker answers. The automatic route must invoke this prerequisite before allowing new Tracker questions.
- [x] Bind and authenticate Tracker's accepted changed-Synthesis input, execute through existing owners with v10 proof and recover publication and subsequent clarification without rewriting historical answers. This prerequisite does not enable automatic refresh ordering or unchanged-input skips.
- [ ] Verify interruption/recovery, unchanged-input skips and changed-parent rejection for Codex and Claude; stop before WHY1 re-review. Independent review and local commit.

No installation, migration, live provider spending, push, merge, original smoke workspace, legacy build, AGENTS.md or CLAUDE.md edits. This plan does not represent checkpoint B as complete when only binding tests pass.

## Checkpoint A contract

The optional row field is `execution_input={source, dependencies}`. `source` has
the existing four completion proof fields. `dependencies` is closed
`{before_sha256, after_sha256, changed}`: sorted unique changed dependency keys,
with empty changes exactly when the two semantic fingerprints agree. Old rows
without the optional field remain valid. The existing round state owner is the
only mutator; initialization has full-state CAS, exact retries are no-ops, and
deletion/rebinding/generic save cannot change the binding. Operation/turn slots
remain null even after binding; it confers no dispatch or publication authority.

The read-only admission helper reauthenticates the current repair and complete
retained ancestry, derives the exact predecessor producer, inspects the union of
their captured sources, and compares the predecessor's **accepted postimages**
and candidate history to the current accepted head. Predecessor-only Synthesis
templates must remain unchanged. Captured repair domains, including generated
context, remain fully guarded; the semantic comparison is not a replacement for
source authentication or the existing operation/publication fingerprint.

Semantic comparison includes artifacts, independent inputs/templates, admitted
runtime policy, identity history and human staging/reasoning context. It excludes
derived spec graph, spec checkpoint metadata and rendered runtime context.
Identity comparison preserves subjects, revisions, content, lineage and evidence
targets/anchors/report identities. It omits publication owner/index bookkeeping
and, specifically for evidence bindings, the checksum derived from those same
fields. It does not edit the retained history or evidence rows.

At this boundary only Synthesis may bind the current released repair. Tracker
and WHY1 input binding reject, including when their inactive round exists.
Checkpoint B must extend actual-input admission and proof together: Tracker may
consume the accepted refreshed Synthesis publication, not the immutable repair
origin stored on its row. Do not lift this guard by changing the row's `source`.

## Verification log

Starting HEAD `9d738f1f`, existing clean linked worktree.

- Three initial comparator cases RED (missing module), 0.42s; owner RED (missing
  entry point), 0.45s; real Codex repair→binding RED (missing admission entry
  point after accepted repair), 182.90s.
- First six cases GREEN, 388.54s: pure comparison, owner refusal, real Codex and
  Claude binding, immutable origin/old state, retries and changed live inputs.
- Independent review found evidence payload checksums reintroduced publication
  bookkeeping indirectly. Two regressions using real materialized reference and
  issue rows reproduced the false `identity` change (0.44s). The correction
  excludes only that derived checksum; substantive target revision and report
  occurrence changes still invalidate. Ten fast cases then passed in 0.45s.
- Existing Tracker round, Discovery operation and repair retention regressions:
  61 passed in 105.22s.
- Review cleared the corrected production code and strengthened test design;
  the reviewer independently ran 9 comparator cases. Final integration checks
  add exact expected dependency differences, rejection of the predecessor's
  preimage baseline, a real concurrent state revision before CAS, and damaged
  retained proof on exact retry. All 12 final new cases passed in 397.65s.
- Clarification candidate regressions: 23 passed in 0.22s.
- Discovery completion, Squad completion and all three refresh-round regressions:
  278 passed in 868.77s. The combined Claude guided Tracker-question → WHY1-question
  → repair case retains both answers and stops at the unchanged refresh guard.

Final current evidence is 12 new cases plus 362 distinct regression cases
(61 + 23 + 278), all passing in offline partitions. Earlier six-case and fast
reruns/reviewer checks overlap and are not added again. `git diff --check` passes.
All provider responses were scripted; state, identity, publication, completion,
retained ancestry and recovery owners were real. This is not a full-suite or
live-provider/activation claim. Checkpoint A is complete and independently
reviewed; checkpoint B remains open within the user's existing approval.

## Checkpoint B: selection and receipt isolation slice

After checkpoint A, verification fixtures escaped their temporary repositories
through inherited Git environment variables. Recovery and the reviewed fix are
recorded in [the isolation incident](2026-09-15-git-fixture-isolation.md), commit
`404d0472`. Working files were preserved; this did not change the refresh design.

The first checkpoint-B slice separates active Synthesis refresh selection from
the original flat run. Default component readers select the active refresh;
historical proof readers and the flat-state protection owner explicitly select
the original operation. Unknown explicit selections cannot fall back to that
original. The existing receipt owner retains original filenames and gives each
refresh its own round files/locks, reservations and usage reads. Admission counts
the original plus retained round operations, not just the active empty slot.

This slice does **not** lift the null-operation/null-turn constraint or the
controller refresh guard. Actual-input completion proofs, read-only post-WHY1
capture, ordered execution, clarification ancestry pinning and unchanged-input
skips remain required before dispatch. Do not publish a refresh using the old
Synthesis v3 proof/source or grant round writes using the flat-state permissions.

Verification:

- Initial RED reproduced six selection/namespace failures (6 failed, 7 passed in
  0.85s). A separate usage case reproduced reading the original receipt (0.41s),
  and count tests reproduced rejecting count 1 while admitting count 0 (2 failed,
  1 passed in 1.30s).
- Final 17 new focused cases plus 63 existing round/receipt cases pass: 80 in
  6.10s, including the flat-owner assertion.
- Final-code original Synthesis across both providers/all modes, Discovery
  completion/recovery and operation regressions pass: 103 in 498.27s. A prior
  103-case run and smaller reruns overlap and are not added to the total.
- Real offline repair-input/retention partition passes: 15 in 1098.87s, including
  both provider bindings, exact retries, proof/source tampering, unchanged old
  records and the combined Tracker/WHY1 human-history case. An earlier superseded
  run was interrupted and is not counted.
- Independent review confirmed the count correction and found no further issues
  in this slice. Whitespace checks pass.

Final evidence is 17 new cases plus 181 distinct existing cases (198 total), all
passing. This first selection/receipt slice is complete and independently reviewed;
checkpoint B as a whole remains unfinished within the existing approval. Next is
actual-input completion proof/capture and ordered execution through the existing
owners, including the clarification-ancestry prerequisite. No installation,
live-provider spending or full activation is established by these offline tests.

## Checkpoint B: actual-input proof and low-level Synthesis execution slice

This slice supersedes the earlier null-operation/null-turn boundary only for a
Synthesis refresh with a bound, nonempty dependency change. The existing state
owner permits writes only to its active operation/turn slots, preserves original
flat records and immutable input/origin, and charges the existing cumulative
dispatch count once. The existing three-attempt operation limit and round
receipt/reservation journals remain the only execution authorities.

Capture uses the actual bound accepted repair, not original Discovery. It
authenticates the complete retained repair ancestry, resolves the nearest
accepted Synthesis before entering source inspection, and recomputes the bound
dependency comparison from that predecessor's accepted postimages. WHY1 reports,
human staging/policy files and the reasoning journal are read-only inputs.
Synthesis's writable artifact roles do not expand; issue report occurrence
provenance survives unchanged reports.

Refresh completions use a closed v9 proof containing `refresh`, `execution_input`
and `predecessor`, with `source_completion` equal to the actual input. Replay and
recovery authenticate the exact accepted repair and nearest previous Synthesis,
recompute semantic dependencies, and enforce the WHY1 return destination. Original
Synthesis retains v3 and explicitly rejects refresh operation IDs. No retained
proof is rewritten or migrated.

Automatic controller refresh remains guarded. The end-to-end test selects the
inactive Synthesis phase explicitly, then uses the real operation, publication,
completion, identity, retained-proof and recovery owners with scripted provider
responses. It does not establish native controller sequencing or live acceptance.
Next remains Synthesis-first controller ordering, Tracker's resulting actual
input, unchanged-input skips and historical WHY1-to-Tracker clarification pinning.
WHY1 re-review remains outside this checkpoint. No installation or live trial.

This proof/capture slice is complete and independently reviewed. Checkpoint B as
a whole remains unfinished within the existing approval.

- Test-first failures reproduced the null-operation guard (1 failed, 3 passed in
  0.63s), wrong flat-state write permission (1 failed in 0.49s), missing actual-input
  reader, and original-input capture in a real Codex refresh (1 failed in 184.78s).
- The initial end-to-end Codex publication then passed in 284.34s. Tests were
  subsequently strengthened with pre-dispatch source drift, shape-valid v3
  downgrade and v9 field tampering, independent dependency recomputation,
  post-identity-apply interruption/recovery and prior Claude human answers.
- Independent read-only review found no production issue and identified the
  downgrade test's early field-shape rejection. The corrected case removes v9-only
  fields to exercise the original-proof operation-ID boundary. A superseded test
  run was explicitly interrupted while strengthening tests and is not counted.
- Final Codex and guided Claude refresh cases both passed in 937.74s. Each rejects
  changed live reports/templates before dispatch or accounting changes, rejects
  altered completion fields and semantic decisions, and recovers after identity
  application without duplicate calls, charges or revisions. Claude's earlier
  Tracker/WHY1 answers reach the refresh evidence and remain byte-identical with
  policy/reasoning context. Original Synthesis and report/receipt bytes stay exact.
- Final focused and regression partition: 349 passed in 1396.83s, comprising six
  new operation/state/input-reader cases and 343 existing selection, repair-input,
  original Synthesis, Discovery completion and Squad completion cases. This
  includes original Codex/Claude guided/semi/Banzai paths and recovery checks.
- Independent review confirmed the corrected downgrade case and accurate scope
  records, with no remaining findings. `git diff --check` passes.

Final evidence is eight new cases plus 343 distinct regressions (351 total).
Earlier RED/GREEN runs and partial progress overlap and are not added again.
Provider responses were scripted; this is neither a full-suite result nor live
acceptance/activation. Only this bounded actual-input proof/capture/execution
slice is complete; the remaining ordered execution and clarification work above
is still approved and required.

## Checkpoint B: historical human-input prerequisite (complete)

The original `previous_records` prefixed WHY1 history with `tracker.active`.
After a later Tracker answer, that would change historical v7 proof decoding.
Also, a refreshed Tracker that retained only its own earlier answers would omit
the intervening WHY1 answers and fail exact receipt/policy reconstruction.

Initial WHY1 selection now retains an optional immutable `tracker_parent` on its
root row, naming the accepted Tracker operation that supplied that root's source.
Legacy roots can be pinned once through the existing state owner with full-state
CAS after authenticating the complete released repair and the root's retained
Tracker completion. No operation, answer, receipt or proof is rewritten. The
pin is a state association, not independent proof authority: retained traversal
and pending initial WHY1 authentication compare it with the actual proven parent.
Pure decoding/state validation perform no new filesystem or database reads.

WHY1 history uses that root pin. Legacy roots without it remain readable before
Tracker refresh execution; empty associations alone do not invalidate history.
At a Tracker refresh boundary, history uses the same repair unit's retained WHY1
refresh association to select its requesting WHY1 predecessor, prefixes that
complete history, and appends only subsequent Tracker answers. Missing/ambiguous
associations and cross-producer cycles reject. This reuses protected round
associations rather than introducing a second human-history ledger.

**Ordering constraint:** call `pin_why1_tracker_history` at released-repair
admission, before Synthesis executes. Its full authentication requires the repair
to remain the current accepted head. Prepare the inactive WHY1 refresh association
before a refreshed Tracker can ask questions. Initial-root pinning does not solve
future WHY1 re-review's new history boundary; that remains outside this checkpoint.

Automatic dispatch, Tracker actual-input binding and unchanged-input skips remain
guarded and unfinished. This prerequisite adds no controller route or provider
prose, makes no installation/live-provider changes, and is not full activation.

Verification:

- Starting clean HEAD `c5ee30f0`; 33 baseline checks passed in 2.47s.
- Test-first failures reproduced the absent pin field (0.41s), absent initial
  selection/legacy CAS owner (two cases, 0.48s), lost WHY1 answer and missing-origin
  admission (two cases, 0.51s), and missing authenticated-parent helper (0.40s).
- The initial real Codex legacy pin and historical v5/v7 replay passed in 390.84s.
  Final tests additionally check damaged parent proof on retry and a valid-shaped
  wrong pin through historical traversal before v7 answer comparison can mask it.
- Independent review confirmed the existing-owner approach, chronological history,
  immutable CAS boundary and pure parent check. It identified the traversal test
  coverage gap above, which was addressed. The final provider run was restarted
  after that test enhancement; superseded/partial runs are not final evidence.
- Final shared regression partition: 346 passed in 171.72s, including 13 new
  history/state cases and 333 existing receipt, round, candidate, selection and
  completion checks.
- Final scripted Codex proof case passed in 425.12s and Claude in 485.20s. Each
  authenticates and pins a legacy root, rejects state races, damaged proofs,
  changed live sources and a shape-valid wrong parent through retained traversal,
  and preserves original v5/v7 proofs, receipts, accounting and answer chronology.
- All 16 selected existing WHY1 mode, multiple-answer and WHY1/Tracker restart
  cases passed in 2212.38s. These include Codex/Claude guided, semi and Banzai
  paths with and without checkpoint metadata, plus interrupted clarification
  promotion/release recovery.
- Independent review is closed with no remaining findings. `git diff --check`
  passes. Final evidence is 15 new cases plus 349 distinct regressions (364
  total); earlier overlapping and superseded runs are not added again.

Only this historical human-input prerequisite is complete. Automatic ordering,
Tracker actual-input execution and unchanged-input skips remain unfinished under
the existing approval. Scripted offline verification is not a full-suite result,
live acceptance, installation or activation.

## Checkpoint B: Tracker actual-input proof/execution prerequisite (complete)

Tracker refresh must bind the current released Synthesis v9 result, while retaining
its original repair source and nearest accepted Tracker separately. The input
owner reuses the existing full-state CAS and dependency comparison. Admission
authenticates the complete current ancestry and requires the prior WHY1 root pin
and same-repair WHY1 history association. No old record is rewritten.

The first Tracker refresh needs a distinct closed proof (v10); it must reject a
v4 downgrade and authenticate both the immediate refreshed Synthesis and the
older Tracker dependency baseline. Subsequent Tracker clarification rounds keep
their existing v4/v5 contracts and include read-only post-WHY1 context. Writable
Tracker roles, attempt limits, receipts and accounting do not expand.

Automatic ordering and unchanged-input skips remain guarded and are not
implemented in this slice. This slice only admits a changed Synthesis predecessor;
the unchanged-Synthesis branch remains an explicit ordered-execution task.

Verification:

- Starting clean HEAD `39f3aa9e`; 36 baseline checks passed in 3.48s.
- Test-first failures reproduced Tracker's repair-source fallback and missing
  input binding (two cases, 0.70s), inactive execution guard (1.16s), and missing
  immediate-parent proof validation (0.38s). Real Codex admission initially
  rejected at the old guard (273.18s), then passed in 286.09s. Real Claude capture
  subsequently reproduced rejection of inherited human answers (699.47s).
- The initial v10 Codex execution/publication/recovery reached a wrong test
  expectation: unchanged intent correctly retains its old revision, rather than
  fabricating another. The assertion was corrected, with no production change.
  A superseded Claude run was terminated; partial/superseded runs are not counted
  as final evidence.
- Independent read-only review found no production issue. Its two coverage
  recommendations were added: independent Tracker dependency recomputation and
  post-binding source drift rejected before dispatch/accounting. The additional
  real clarification case covers a third human answer and interrupted identity
  application before subsequent Tracker continuation. Review is closed with no
  remaining findings.
- Final shared/regression partition: 366 passed in 559.04s, comprising 10 new
  state/parent cases and 356 existing receipt, round, candidate, completion and
  selected mode/restart cases. Earlier overlapping partitions are not added again.
- Final scripted refresh execution/proof cases: Codex passed in 436.22s and
  Claude passed in 953.26s. They cover input/proof tampering, independent
  dependency recomputation, source drift before dispatch, interrupted identity
  application, exact retry and unchanged intent revision preservation.
- The real-controller Claude clarification/restart case passed in 1130.70s:
  all three answers remain chronological, interrupted answer publication recovers,
  and subsequent Tracker continuation adds no duplicate calls or charges.

Final evidence is 13 new cases plus 356 distinct regressions (369 total).
`git diff --check` passes. Earlier overlapping and superseded runs are not added
again. Provider responses were scripted; this is not full-suite verification,
live acceptance, installation or activation. Only this prerequisite is complete;
automatic ordering, unchanged-input skips and their whole-flow recovery checks
remain approved and unfinished. WHY1 re-review stays outside this checkpoint.
