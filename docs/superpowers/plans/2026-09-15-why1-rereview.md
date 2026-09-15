# Requesting WHY1 re-review

> Use superpowers:executing-plans inline, test first, with independent read-only review.

**Goal:** Complete the approved repair → Synthesis → Tracker → requesting WHY1
return, preserving exact evidence and normal verdict/clarification routing.

**Architecture:** Extend existing producer rounds, full-state CAS, capture,
publication and completion proofs. No new controller, allocator or history ledger.
The user approved proceeding toward install readiness and deferring skip
optimization until functional E2E works. This implements step 3 of the approved
inline design recorded in `2026-09-15-repair-refresh-rounds.md`.

## Contract and files

`discovery_producer.py`, `squad_state.py`: bind WHY1's `execution_input` to the
current released Tracker, never to immutable repair origin. Atomically retain
`tracker_parent` naming the exact accepted Tracker operation, including a later
Tracker clarification round descended from this repair's refresh. Full-state CAS,
immutable retries and the existing operation/receipt namespaces remain owners.

`tracker_clarification.py`: a bound WHY1 refresh prefixes history from its pinned
Tracker (which already carries requesting WHY1 history), then appends subsequent
WHY1 answers. Unbound associations continue to expose their prior WHY1 history.
Old accepted reports and answers are not rewritten.

`discovery_repair_admission.py`, `discovery_operation.py`: authenticate the current
Tracker→WHY1 route, complete ancestry, same repair association, nearest requesting
WHY1 and exact live source domains. Recompute the retained dependency comparison
at binding, operation capture and proof traversal. Synthesis, Tracker and WHY1
always execute an authenticated refresh, even if that comparison is empty.
Skipping unchanged work is deferred; no source or proof checks are relaxed.

`discovery_publication.py`, `discovery_completion.py`: closed v11 adds the existing
refresh/input/predecessor association plus `tracker_parent` to WHY1's first
re-review proof. Reject v6 downgrade, wrong parent, foreign repair, altered input
or dependency claims. Existing v6/v7 clarification descendants remain readable.
Traverse v11→Tracker (including clarification descendants)→v9→repair→original
WHY1 with each required dependency comparison independently authenticated.

`squad.py`: continue after authenticated Tracker into WHY1 using native limits,
verdict routing, human-input and completion recovery. No provider-specific prose,
installation, migration, live model spending, push, merge or legacy-build changes.

## Verification and execution

- [x] Reproduce missing WHY1 binding/execution/history/parent support in state tests.
- [x] Reproduce the old controller stop instead of returning through WHY1 to Constitution.
- [x] Reproduce empty-comparison WHY1 execution refusal; retain exact comparison but allow mandatory review.
- [x] Reproduce empty-comparison Synthesis/Tracker execution and activation refusal; allow conservative execution under the same limits.
- [x] Reproduce stale resolved Tracker/WHY1 answers incorrectly selecting a clarification instead of a fresh refresh; require the current producer's completed dispatch without deleting history.
- [x] Pass real Codex and Claude repair→refresh→WHY1 PASS paths, preserving old rounds, identities and accounting.
- [x] Reject v6 downgrade and altered v11 source/parent/predecessor/comparison; independently recompute dependencies and traverse wrong retained parent.
- [x] Recover interrupted WHY1 input binding, publication and human answer; preserve chronological answers through Tracker and WHY1 continuation.
- [x] Run affected state/proof/original mode regressions and isolated previous refresh checks; independent review and local commit.

Reaching Constitution is the next guarded stop, not full spec completion
or installed/live acceptance. Continue the remaining convergence work after this
checkpoint without treating optimization as a prerequisite.

## Verification evidence

The four empty Synthesis/Tracker operation/activation cases failed before removing
the changed-only execution gate. Exact comparison and source authentication stay
mandatory. Independent review also found the stale-answer selection defect: both
isolated controller cases reproduced it, then passed after requiring the latest
completed dispatch to belong to the current producer. Current focused state and
Squad completion partition: 261 passed in 9.36s.

The full guided recovery case reproduced a failure before new WHY1 publication
(1 failed in 671.34s). The real two-provider proof test initially expected the
wrong public exception for rejected parent traversal; its assertion now matches
the existing CompletionError boundary. Neither failing run is acceptance evidence.
The fresh full controller and recovery checks below replace those failed attempts.

Additional affected regression partitions passed: 80 candidate/receipt/history/
Synthesis-selection cases in 4.27s; 12 Tracker-round/dependency cases in 0.55s;
and five original WHY1 clarification/native-routing cases in 783.75s. The
independent reviewer cleared the corrected dispatch predicate and public exception
expectation, and found no remaining changed-only gate across binding, activation,
capture, publication or retained traversal. Full re-review recovery remains the
acceptance gate; these narrower results are not a full-suite or live-run claim.

Fresh full guided recovery passed: 1 case in 1043.77s. The real controller resumes
after interrupted input binding, v11 publication, and v7 human-answer publication,
then completes its v6 WHY1 continuation to the Constitution stop. Both old and new
WHY1 answers, original rounds and identity history remain intact; usage is exactly
210 tokens / 30 scripted calls. Final replay adds no calls, charges or history.

Fresh two-provider re-review passed: 2 cases in 1101.07s. Both paths perform 24
scripted calls / 168 tokens, preserve original rounds and identity history, and
stop at Constitution. Valid v11 proofs pass independent dependency recomputation;
altered version/source/parent/predecessor/comparison and a wrong retained Tracker
parent reject. Repeating the completed path adds no calls, charges or history.

The three existing isolated refresh-ordering/recovery cases passed in 1407.44s.
Their test boundary now stops after authenticating and binding WHY1 input, before
dispatching re-review. Both provider/mode paths, source drift, interrupted
selection/publication and post-refresh Tracker clarification remain covered.
The separate new WHY1 tests use the unmodified controller beyond this boundary.

Final verification: the consolidated focused suite passed 353 cases in 13.06s
(3 real-flow cases deselected). The original text-identical repair regression
passed in 370.30s with the updated authenticated pre-re-review test boundary.
Together with the 11 full-flow cases above, 365 distinct selected cases pass.
Earlier focused runs overlap and are not added to that total. Independent review
has no remaining findings, and `git diff --check` passes. Empty comparisons are
covered by operation/activation tests; wholly unchanged repeated repair cycles
are not separately claimed as full-flow acceptance.

This completes requesting WHY1 re-review, not downstream Constitution execution,
whole-spec success, public/default activation, installed-bundle or live-provider
acceptance. No installation, migration, provider spending, push or merge occurred.
