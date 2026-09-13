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
