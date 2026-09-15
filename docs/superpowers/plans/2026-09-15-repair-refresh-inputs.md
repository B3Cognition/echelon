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
- [ ] Bind actual inputs into completion proof and authenticate repair ancestry during replay/recovery. Permit read-only post-WHY1 context without broadening producer writes.
- [ ] Execute changed Synthesis through existing owners, then evaluate Tracker from that accepted publication (or retain the same accepted head if Synthesis dependencies are unchanged). Never dispatch from the repair-origin field merely because it names the round.
- [ ] Pin historical WHY1 clarification ancestry to its accepted Tracker parent before allowing new Tracker questions. Preserve old answers and native caps, cumulative accounting, retry/no-progress/unknown-completion behavior.
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
