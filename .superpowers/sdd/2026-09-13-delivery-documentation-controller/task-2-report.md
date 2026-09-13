# Task 2 implementation report

## Scope and implementation

Implemented the approved documentation runner integration in the designated
`delivery-controller-contract` worktree, based on `f3146044`. Ralph remains the
operation and acceptance owner; there is no second pointer or controller.

- A nonempty all-documentation failure set (the `documentation-`, `docs-`,
  `readme-`, and `changelog-` prefixes) enters the documentation runner. Actual
  failure IDs, errors, details and verification evidence become structured
  input. Legacy MANAGER instructions are not forwarded to documentation roles.
  Source, mixed and empty sets retain implementation repair routing.
- The existing `delivery_slice_operation` stores `kind="documentation"`.
  Missing kind remains a task operation; unknown kinds block. The callback
  persists the pointer after the empty journal is durable and before intent.
  Build restart dispatches the retained kind before new task selection.
- Only eligible applied operations advance. Documentation repair preserves
  the last real implementation task ID. Repeated rejected documentation work
  retains its ceiling; repeated feedback against accepted documentation and
  changed pending failure evidence require reconciliation. Unresolved operation
  kinds cannot replace each other. Applied documentation can advance on the
  next outer iteration or explicit source repair.
- The original controller-derived changed-file inventory is persisted in that
  operation. This permits replay after the writer changes README/CHANGELOG;
  runner source/candidate guards still validate the actual bytes.
- Cumulative runner usage is translated to the unseen delta and accounted once.
  Publication success marks documentation progress without completing tasks.
  A private dictionary subtype plus matching durable operation ID/path provides
  the narrow task-ID exemption; provider JSON/prose cannot grant it.
- Controlled documentation validation requires an independent passing report,
  including no-impact declarations, and does not rewrite either canonical
  report. The new gate option defaults to false for legacy compatibility.
- The adapter validates supplied runnability receipt integrity/currentness and
  current resolved stack/contract. Missing required evidence blocks in the
  documentation runner. Malformed supplied runnable evidence fails closed.
  Initial candidate validation and replay byte guards remain with Task 1;
  documentation-owned edits must not invalidate the captured receipt.

## Tests and TDD evidence

Commands below ran from:
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
All providers are scripted fixtures; Git and the consuming Ralph/runner/gates
are real. No live model/provider, installation, push, merge, migration, rollout,
or full repository test suite was run.

### Environment correction

Initial command:

```text
pytest -q tests/unit/test_delivery_documentation_integration.py
```

Collection failed with `ModuleNotFoundError: No module named 'yaml'` and
`1 error in 0.58s`. This was not a feature RED. Subsequent commands used the
existing repository virtual environment; nothing was installed.

### Initial RED

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py --tb=short
25 failed, 5 passed in 2.51s
```

Expected failures included:

- Completed-task feedback: `feedback requires a previously accepted delivery slice task`.
- Controlled no-impact with no review: `assert True is (None is True)`.
- Repair after task acceptance entered the implementation contract:
  `invalid delivery result fields`.
- Documentation crash tests did not reach journal/publication boundaries:
  `DID NOT RAISE ... ProcessLost`.
- Inner verification repair returned `build_blocked` requiring an implementation
  pointer instead of running the documentation author/reviewer chain.

### Initial GREEN

Same command after the initial adapter/gate changes:

```text
30 passed in 12.63s
```

### Additional lifecycle RED/GREEN

The same command after adding focused lifecycle, external-spec, report
preservation and downstream budget cases produced:

```text
1 failed, 39 passed in 16.89s
```

`test_pending_docs_rejects_changed_failure_evidence` returned
`delivery_documentation_repair_limit` instead of requiring reconciliation for
changed failure evidence. The adapter now compares the structured feedback
before replay. Focused check including the updated finalization fixture:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py tests/unit/test_delivery_finalization.py --tb=short
52 passed in 18.87s
```

### Git-backed recovery RED/GREEN

Initializing a real Git candidate in the existing crash cases exposed the
changed-file recomputation problem:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py -k build_restart --tb=short
3 failed, 1 passed, 36 deselected in 2.32s
```

Receipt, publication and progress restart all failed with
`delivery_reconciliation_required: documentation inputs changed`. Persisting the
original changed-file inventory in the existing operation fixed these cases:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py --tb=short
40 passed in 17.07s
```

### One surrounding regression batch

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_*.py tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py tests/unit/test_documentation_gate.py tests/unit/test_docs_verifier.py tests/unit/test_runnability_*.py tests/unit/test_llm_provider.py tests/unit/test_claude_delivery_scope.py --tb=short
2 failed, 761 passed in 85.93s (0:01:25)
```

Both failures were existing Ralph outer-loop test doubles missing the added
optional `require_independent_review` argument:

- `TestOuterLoopConvergence.test_documentation_gate_receives_delivery_slice_changed_files`
- `TestOuterLoopConvergence.test_documentation_gate_includes_docs_committed_after_task_progress`

Each raised `TypeError: ...fake_gate() got an unexpected keyword argument
'require_independent_review'`. Both narrowly affected fixture signatures were
updated; their behavior and assertions are unchanged.

### Receipt-backed replay RED

Self-review found that revalidating the full product fingerprint in the adapter
would reject the writer's own documentation changes after reconstruction. Added
a real receipt/Git/runner replay test before adjusting the validation boundary:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py -k runnability_receipt --tb=short
1 failed, 40 deselected in 0.72s
```

Observed `documentation_runnability_evidence_invalid: candidate_fingerprint
mismatch` instead of resuming real independent review and reaching the bounded
repair limit for this intentionally incomplete README. The adapter now checks
the immutable receipt against its captured candidate fingerprint while still
checking the current stack/contract. Task 1 owns initial candidate validation
and replay source/candidate guards, as the supplied context requires.

### Final amended-file verification

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_integration.py tests/unit/test_delivery_documentation.py tests/unit/test_delivery_finalization.py tests/unit/test_ralph_outer.py tests/unit/test_documentation_gate.py tests/unit/test_runnability_evidence.py --tb=short
438 passed in 69.72s (0:01:09)
```

This includes all 41 documentation integration cases, both corrected outer-loop
fixtures, the real documentation runner, finalization and receipt/gate coverage.
The unaffected surrounding files retain their passing evidence from the single
batch above. No further full surrounding batch was run. `git diff --check`
also passed with no output before staging.

## Changed files

- `src/harness/ralph.py`
- `src/harness/documentation_gate.py`
- `tests/unit/test_delivery_documentation_integration.py`
- `tests/unit/test_delivery_finalization.py`
- `tests/unit/test_ralph_outer.py`
- This implementation report.

The main agent's plan and convergence/design edits were left untouched and
are not part of the implementation commit.

## Self-review and remaining boundary

Self-review checked operation advancement, unknown kind handling, unresolved
state retention, empty-journal ordering, report-publication ordering, provider
marker spoofing, source-repair targeting, exact report preservation, runnability
authority, and cumulative token accounting. It found and resolved the original
changed-file replay mismatch and the overstrict receipt replay check described
above. Ralph is an existing large module; edits are confined to its current
adapter, gate and completion boundary rather than restructuring it.

This implements Task 2 only. Native entry/prose and the later bundle milestones
remain outstanding phase-4 work; deferred element-identity functionality remains
inactive. Main-agent-owned convergence records describe that boundary. No
independent review was dispatched by this worker; the main agent will arrange
the requested read-only review after this report and checkpoint commit.

## Fix round 1: reproduction-only policy boundary (2026-09-13)

Status: NEEDS_CONTEXT. Task 2 is not complete. This round intentionally stops
after RED, per the main agent's instruction, pending explicit authorization for
the narrow treatment of the two controller-owned canonical report paths.
No production code was changed and no commit was created in this round.

### Approved correction and proposed durable sequence

Read the updated task-2 brief at HEAD `29ff3834`. The user approved a
post-authoring/pre-review runnability checkpoint in the same documentation
operation and attempt ceiling. Before implementation, proposed to the main
agent an immutable original authoring context plus per-attempt checkpoint
intent/completion in the documentation journal, with the reviewer bound to the
refreshed receipt and post-authoring candidate. Unknown checkpoint completion
would block replay; final receipt reuse would validate actual current candidate,
contract, resolved stack, receipt integrity and latest/currentness. No changed
hashes or report edits after review were proposed.

Inspection exposed a second boundary: `product_evidence_fingerprint` includes
both canonical in-worktree documentation reports. Neither the inventory nor
the runnability execution path excludes them. Their publication changes the
actual product fingerprint after the proposed pre-review checkpoint. In
particular, the reviewer report embeds the receipt digest while the receipt
embeds the product fingerprint, which includes the report. This is a content
self-reference, not a Git commit mismatch (`candidate_commit` is already
informational in the existing runnability receipt validator).

The main agent confirmed this finding and instructed this round to remain
reproduction-only. A publication overlay or report-path identity exception
would be an additional policy beyond the approved checkpoint; none has been
implemented. README and CHANGELOG remain part of actual product identity.

### Consuming RED evidence

Added `tests/unit/test_delivery_documentation_checkpoint.py` with an enabled
candidate-owned runnability contract, resolved browser/Postgres stacks, real
runnability execution owner and immutable receipt generation/validation, real
Git checkpoint commits, real documentation author/reviewer runner, and the real
Ralph inner/post-verification chain. External author/reviewer and sandbox
execution are scripted; remote push is a no-op. The post-verify observer only
records the real returned failures and returns the unchanged result.

Command (existing repository virtual environment, designated worktree):

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py --tb=short
2 failed in 2.12s
```

1. `test_real_inner_loop_converges_with_post_authoring_runnability` fails its
   convergence assertion. The real post-verify chain returns
   `docs-runnability-evidence-stale`, then the next feedback returns
   `build_blocked` with `accepted documentation received new failure evidence`.
   This reproduces the reviewed pre-authoring receipt mismatch: final
   verification replaces the evidence digest after documentation review.
2. `test_report_publication_preserves_post_authoring_receipt_candidate` fails
   the diagnostic assertion that the post-authoring candidate survives report
   publication. The real documentation runner succeeds, but the actual product
   fingerprints differ:

   ```text
   post-authoring: 8b045a1875d6cca317c35828849eafb4727df9457527f2b03d35a9ff4d446f5c
   post-publication: 262aa0549b3edddd7a340b0541d289076655995fdd1c50349bf09ea4c38150cb
   ```

   This separately demonstrates that a refresh before review alone cannot
   supply a receipt for the exact final in-worktree report-bearing candidate.
   The assertion is deliberately RED pending the explicitly approved policy;
   it is not an assertion that current identity semantics promise equality.

The initial single-test reproduction also failed as expected (`1 failed in
1.27s`), but its inherited Git mock produced checkpoint warnings. The final
two-test reproduction uses real GitOps checkpoint commits and a Python project
manifest and has no warnings. No GREEN claim, xfail, regression batch, live
provider run, install, migration, push or commit was made in this round.

### Files and next required decision

Only the new reproduction test module and this report were changed by the
worker. The main agent's uncommitted plan edit was preserved. Production
implementation, durable checkpoint schema, failure/recovery regression coverage
and final relevant regression batch remain pending. The main agent is obtaining
authorization for a narrow treatment of the exact canonical report pair before
resuming implementation; no broad inventory redesign is authorized.

## Fix round 1 resumed: approved exact-report policy and evidence checkpoint

The user separately approved excluding only the resolved canonical
`documentation-impact-report.md` and `docs-verification-report.md` paths from
the runnability product fingerprint. This resolves the policy blocker above;
ordinary product inventory and README/CHANGELOG/source/other-spec coverage stay
unchanged. Implementation resumed from `29ff3834` in the same worktree.

### Implemented correction

- Added `runnability_product_fingerprint(worktree, spec_dir)` alongside existing
  runnability evidence validation. It reuses the current inventory mechanics with
  exactly two resolved paths, rejects symlinked specs/reports and report
  directories, and leaves ordinary product inventory unchanged. External specs
  do not exclude any unrelated candidate path. Existing incompatible receipts
  are not migrated or re-signed.
- Passed the resolved spec into the existing runnability execution owner and
  producer. The documentation runner and Ralph's actual-content validation use
  the same scoped fingerprint. Land's runnability-only comparison resolves the
  spec inside the actual landing candidate; its ordinary coverage/publication
  fingerprints are unchanged. Commit identity remains informational under the
  existing validator.
- Documentation journal schema 2 preserves the original authoring evidence and
  records up to three explicit per-author checkpoint transitions. Each transition
  has durable intent, candidate identity, before/after evidence snapshots, new
  input fingerprint, completion/failure status and an error where applicable.
  The strict validator requires each runnable review to follow its matching
  completed checkpoint. Earlier unreleased journal schemas fail closed.
- After each successful author, the same runner calls a narrow Ralph callback
  before deterministic and independent review. Ralph invokes its existing
  runnability owner, records the actual result, and returns the validated current
  receipt. The runner guards candidate/source bytes and its journal around that
  transition, durably saves completion, then binds the reviewer assignment and
  report to the refreshed evidence. There is no second operation pointer or
  controller and no report-digest patching after review.
- Pending/unknown or failed checkpoint completion cannot be retried implicitly.
  Completed checkpoint, reviewer, publication and Ralph progress crashes resume
  the same durable operation without repeating the journey or counting role
  tokens twice. Missing checkpoint callbacks cannot publish runnable docs.
- Final post-verification reuses only an applied documentation operation's
  independently reviewed, completely published checkpoint. Read-only proof checks
  the strict journal, actual source/candidate, exact canonical report bytes,
  current receipt/latest selector, current stack and current contract. Invalid
  state returns a failure without generating a replacement receipt. Standard
  verification still executes on the final candidate.
- The same three-author-attempt ceiling, finite budget and cumulative role
  accounting remain in force. No-runnability execution keeps its prior route.

### Focused evidence, including failed iterations

All commands below used the existing repository virtual environment from the
designated worktree. The prior two real consuming RED failures are recorded in
the reproduction-only section above.

New exact-path/safety tests initially failed because the scoped helper did not
yet exist:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py --tb=short
11 failed in 1.53s
```

The first implementation run exercised the now-converging real loop:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py tests/unit/test_delivery_documentation.py --tb=short
1 failed, 77 passed in 13.49s
```

Only its token expectation failed: actual total `15` versus expected `14`.
The two roles account for 14 tokens; the real standard verification adds one.
The fixture now asserts 15 rather than discarding that actual verification cost.

Expanded checkpoint/integration run:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py tests/unit/test_delivery_documentation_integration.py --tb=short
1 failed, 70 passed in 38.21s
```

The old synthetic receipt-only recovery case had no enabled runnable contract
or resolved stack execution configuration. It correctly could not refresh that
receipt after authoring. The test now uses the real enabled runnability fixture
and proves recovery after the writer receipt, before the new checkpoint, succeeds
with two role calls and exactly two journeys (initial and checkpoint).

After adding all modes/provider facades and remaining budget/corruption cases,
the same focused command produced:

```text
3 failed, 82 passed in 52.39s
```

These three failures were test editing errors: assertions belonging to the
repair-attempt test were initially placed in the parameterized budget test,
causing `NameError: name 'attempts' is not defined`. The block was moved back;
no production behavior was changed for those failures. Narrow repair/budget and
new archived-candidate Land checks then passed:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py -k 'repaired_authoring or finite_budget' tests/unit/test_land.py -k 'repaired_authoring or finite_budget or excludes_only_resolved' --tb=short
9 passed, 160 deselected in 6.42s
```

Self-review added a consuming RED for omission of the checkpoint callback:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py -k without_author_checkpoint --tb=short
1 failed, 44 deselected in 0.85s
```

Observed `BuildResult(exit_code=0, status='done', token_usage=14, ...
runnability_reviewed=False)`: the direct helper could publish runnable docs with
no callback. It now blocks with `documentation_runnability_checkpoint_missing`
before independent review; the strict journal also rejects a runnable review
without the matching completed checkpoint.

Final focused GREEN before the surrounding batch:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_documentation_checkpoint.py tests/unit/test_delivery_documentation_integration.py --tb=short
86 passed in 53.13s
```

This covers both neutral provider facades across all three modes; exact-path
identity and unsafe paths; real-loop convergence and final receipt reuse;
writer/intent/external-completion/checkpoint/review/publication/progress crashes;
failed/cancelled refresh; candidate, evidence and journal mutation; final source,
README, other-spec, report, contract, stack and latest-selector rejection; strict
checkpoint corruption; finite budget and three-attempt repair/replay behavior.

### Single surrounding regression batch

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest -q tests/unit/test_delivery_*.py tests/unit/test_ralph_inner.py tests/unit/test_ralph_outer.py tests/unit/test_documentation_gate.py tests/unit/test_docs_verifier.py tests/unit/test_runnability_*.py tests/unit/test_llm_provider.py tests/unit/test_claude_delivery_scope.py tests/unit/test_land.py tests/unit/test_product_inventory.py tests/unit/test_candidate_evidence_excerpt.py --tb=short
942 passed in 142.89s (0:02:22)
```

This was the single surrounding batch for the approved fix round. It passed
without failures or warnings. `git diff --check` also passed with no output.
Implementation status: DONE for the approved correction, pending the main
agent's independent scoped re-review; no claim of broader phase-4 completion.

### Changed files and self-review

Code: `candidate_evidence.py`, `delivery_documentation.py`,
`delivery_documentation_contract.py`, `ralph.py`, `runnability_evidence.py`,
`runnability_runner.py`, and the runnability-only comparison in `land.py`.
Tests: new `test_delivery_documentation_checkpoint.py`, the directly affected
receipt recovery case in `test_delivery_documentation_integration.py`, and
four Land candidate comparison cases in `test_land.py`. This report is included.

Self-review checked the exact two-path boundary, producer/consumer consistency,
durable intent/completion ordering, original evidence retention and review input
rebinding, final receipt/currentness/report integrity, operation and budget
reuse, and rejection of incompatible records. Ordinary inventory has no changes.
No independent reviewer or subagent was dispatched. The main agent's plan and
convergence records remain outside this worker's commit. Later phase-4/native
entry/prose/bundle milestones and deferred identity functionality remain outside
this checkpoint; no live providers, installs, migration, push or defaults were
used or changed.
