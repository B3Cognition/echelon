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

- [ ] Select active Synthesis round without changing the original flat source/operation/turn marker; isolate new receipts with existing round journal support.
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
