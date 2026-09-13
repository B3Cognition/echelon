# Task 1 report: managed projection write exclusion

## Status and commit

DONE. Implementation commit:
`aef09ba943d8db24ce448b73c58443bdb3e87e1a` (`feat: block legacy projection writes for managed ownership`).

The controller-supplied base was confirmed as both initial `HEAD` and merge-base:
`12486fceced03b16c60d045ea6f0ad5e312d9edf`.

## Implementation

- Added `IdentityStore.require_unmanaged_workspace()`: one existing read
  transaction, `PRAGMA query_only=ON`, then the exact bounded
  `managed_identity_specs` and forced `managed_identity_operations` partial-index
  observations. It performs no payload decoding, canonical enumeration, child
  history scan, mutation, migration, or new indexing. Ordinary exceptions become
  the exact bounded store error outside the handler; process-control exceptions
  propagate.
- Added `require_legacy_identity_workspace(project_root=...)` using the existing
  parent-first `.echelon` lstat and authority-open logic. The private no-selector
  path now invokes the workspace query; existing spec/run public paths retain
  their input and ordering semantics.
- Added `_require_legacy_workspace_projection(project_root)` in
  `workspace_graph.py`, translating only `IdentityStoreError` to the bounded
  `WorkspaceGraphError` outside the handler.
- Guarded the exact five rootful owners: `write_workspace_graph`,
  `write_workspace_graph_audit`, write-mode `refresh_workspace_graph`,
  `_graph_output_commit`, and eligible write-mode `spec_memory_audit`.
- Aggregate refresh checks after root resolution and before shared RE, discovery,
  per-spec work, composition, or final graph/audit writes. Read-only preview is
  unchanged.
- Graph output commit checks the selected `spec_dir.name` and independently the
  physical `spec_dir.resolve().name` before `OwnedOutputCommit`. Memory audit
  performs its native audit first, skips unavailable reports, resolves the native
  canonical selection, checks selected and actual report-output names, and leaves
  the native writer outside the admission handler.
- Rootless serializers and exact-byte primitives remain unchanged and trusted,
  including `write_spec_graph` and `write_workspace_graph_bytes`.
- Storage documentation records exact coverage, global versus selected-spec
  scope, absent-canonical ownership, no lease/atomic proof, low-level limits, and
  remaining positive integration.

## TDD evidence

### Authoritative RED

The first test initialized a real identity database, captured a genuine empty
run-local source tree, registered native source context and managed genesis,
confirmed the managed spec was absent from canonical `specs/`, snapshotted every
directory/file/symlink and the SQLite dump, and tripwired only the first upstream
`_refresh_re_memory` boundary.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_projection_write_exclusion.py::test_managed_workspace_refresh_rejects_before_upstream_refresh -q
```

Exit 1: `1 failed in 0.32s`. The real write refresh reached the expected missing
admission boundary and raised:

```text
AssertionError: managed workspace reached upstream RE refresh
```

The controller was notified immediately. No fixture correction was needed.

### First GREEN

After the query, guard/translator, and all five owner placements, the identical
command exited 0 with `1 passed in 0.31s`.

## Test coverage

The new task module exercises real authority and native records. Doubles are only
at required acquisition/computation or storage/effect seams.

- Actual managed rows, damaged payloads, registration-only orphans, empty
  authority, reservation, import, and source-only authority.
- One query-only transaction; exact two SQL statements; bounded `LIMIT 1` reads;
  partial-index plan; allowed-table-only reads; no child-history access or writes.
- Absent parent/child compatibility, malformed present parent/leaf refusal,
  bounded/no-chain ordinary failures, and `KeyboardInterrupt`, `GeneratorExit`,
  and `SystemExit` propagation.
- Native direct workspace graph/audit records, existing and absent output paths,
  and unchanged filesystem/SQL before render, prepare, temp, or replace.
- Aggregate refresh before RE/discovery/all per-spec/final effects in both
  absent-canonical and mixed managed/legacy workspaces; native read-only preview.
- Actual workspace build/audit/refresh CLI write routes and actual spec graph
  build/audit/refresh commit owner; no success output or state changes on refusal.
- Memory-audit selected and physical output witnesses, unavailable no-write, and
  native earlier audit error.
- Unrelated managed ownership with supported numeric legacy selector and native
  graph/report output bytes and keys; managed read-only graph/memory commands.
- Rootless low-level writer controls remain callable without fabricated roots.

The first full new-module iteration exited 1 with `8 failed, 27 passed in 1.84s`:
seven failures shared one missing `IdentityStoreError` test import, and one
positive assertion expected a nonexistent spec-graph `scope` key. The import was
restored and the literal native assertion corrected to `schema_version == 1`.
The next run exited 0 with `35 passed in 1.79s`; after adding the low-level
trusted-primitive control, it exited 0 with `36 passed in 1.88s`.

One initial multi-file `apply_patch` attempt failed before changing files because
an empty documentation hunk was invalid. The production patch was reapplied
without that empty hunk. No production code preceded the authoritative RED.

### Ruling 45 fixture correction

Static inspection found that the positive parameter of existing
`test_spec_memory_audit_write_respects_availability` claimed a canonical writable
output but did not create `specs/003-demo/spec.md`. Required native
`resolve_spec_dir` would reject that synthetic setup. No pre-correction failure
was executed or claimed. The controller authorized creating the real directory
and `spec.md` only for `status == "pass"`; all mocks/assertions remain, and the
unavailable source remains absent. No production compatibility bypass was added.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_spec_memory.py::test_spec_memory_audit_write_respects_availability -q
..                                                                       [100%]
2 passed in 0.25s
```

## Exact eight-module cover and amended tree

All eight paths were confirmed present. The once-only exact command was:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_projection_write_exclusion.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_cli_graph.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_workspace_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_workspace_graph_refresh.py -q
```

Exit 1: `264 passed, 1 failed in 7.01s` (tool wall 7.24s). The only failure was
`test_write_workspace_audit_rejects_earlier_symlinked_ancestor`: its real
symlinked `.echelon` parent previously expected later output-path `OSError`, but
the required parent-first identity guard correctly returned bounded
`WorkspaceGraphError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` first. This boundary
conflict was raised before changing production or the test.

Ruling 46 retained production ordering and authorized changing only that expected
exception plus the necessary constant import. Its real symlink fixture,
temporary-file tripwire, and external-byte assertions are unchanged. Per ruling,
only the amended module was run:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_workspace_graph_audit.py -q
................................                                         [100%]
32 passed in 0.31s
```

The original cover therefore proves the unchanged 264 cases, and the complete
32-test amended audit module proves the final changed test tree. No duplicate
eight-module rerun, full-unit/bare pytest, install, backend/provider, smoke, or
capacity command was run.

## Command and failure log

All read-only discovery commands exited 0 unless noted:

1. `pwd` and `rg --files` confirmed the exact worktree and root guidance files.
2. Bounded `sed`/`wc -l` reads covered the complete brief, `AGENTS.md`,
   `CLAUDE.md`, TDD skill, good-tests reference, verification skill,
   using-superpowers subagent stop, and implementer prompt. An initially combined
   tool output was truncated, so dedicated complete reads preceded implementation.
3. `git status`, `git rev-parse HEAD`, and `git merge-base` confirmed the supplied
   base and only controller-owned initial progress edits.
4. Targeted `rg -n` and `sed` reads covered scoped store/guard/owners, schema/index,
   native source/enrollment fixtures, graph/audit records, CLI routes,
   selected-spec helper/resolver, commit owner, report writer, and documentation.
   Two broad outputs truncated and were followed by narrow complete reads.
5. Iterative tests and results are recorded verbatim above, including every
   failure and correction.
6. Self-review ran `git status --short`, `git diff --check`, scoped `git diff`, and
   a complete new-test read. Path confirmation for the eight required modules
   exited 0. Final unstaged and staged `git diff --check` both exited 0.
7. Exact-path staging, `git diff --cached --name-only`, cached stat, and status
   confirmed only the ten authorized paths were staged; controller administrative
   files stayed unstaged.
8. `git commit -m "feat: block legacy projection writes for managed ownership"`
   exited 0 and created `aef09ba9` with 10 files, 923 insertions, 7 deletions.
   `git rev-parse HEAD`, `git show --name-only`, and status confirmed the full
   commit and only controller-owned administrative edits remained.
9. The first ordinary exact-path `git add` for this report exited 1 because the
   `.superpowers` directory is ignored. No unrelated path was staged. The
   controller-authorized report path was then staged explicitly with `git add -f`
   for the report-only commit.

## Staged and tested implementation tree

```text
docs/element-identity-storage.md
src/echelon/cli_app.py
src/echelon/workspace_graph.py
src/echelon/workspace_graph_audit.py
src/echelon/workspace_graph_refresh.py
src/harness/element_identity_legacy_guard.py
src/harness/element_identity_store.py
tests/unit/test_cli_spec_memory.py
tests/unit/test_managed_projection_write_exclusion.py
tests/unit/test_workspace_graph_audit.py
```

Controller-owned and excluded from the implementation index/commit:

```text
.superpowers/sdd/2026-09-13-managed-projection-write-exclusion/progress.md
.superpowers/sdd/2026-09-13-managed-projection-write-exclusion/task-1-brief.md
docs/superpowers/plans/2026-09-13-managed-projection-write-exclusion.md
```

## Self-review

- All exact interfaces, queries, exception boundaries, five placements, read-only
  exceptions, selected/physical witnesses, and documentation requirements are
  present.
- Ordering is exact: workspace writers precede output construction/render;
  refresh precedes upstream effects outside per-domain handlers; graph commit
  precedes commit-owner construction; memory admission follows an eligible native
  audit and precedes report bytes while native writer errors remain native.
- Compatibility is preserved: existing spec/run guard calls the selected
  execution query; unrelated managed specs retain selected legacy writes; absent
  authority does not initialize; rootless primitives remain unchanged.
- Tests assert literal SQL, bytes, keys, errors, filesystem snapshots, and SQLite
  dumps. Tripwires prove effect ordering without replacing guarded owners.
- No schema, graph wire/key, renderer, publisher, source/run transition, counter,
  RE writer, provider, prose, install, backend, or capacity work was added. No
  child/helper/reviewer agent was dispatched.

No remaining task-scoped correctness concern was found. Root owns independent
original-base review.

## Remaining integration

These are negative boundaries for named legacy projection outputs only. They do
not implement managed graph/source acceptance, arbitrary low-level file-write
confinement, concurrent enrollment serialization, positive runtime/producers,
semantic repair, graph sealing, coordinated completion, backend/provider work,
or rollout authorization. Observations are not leases or atomic cross-domain
proofs. Rootless serializers remain trusted primitives, standalone RE mining is
not globally blocked, and no claim is made that every writer or CLI output is
guarded. Offline whole-branch review/full-unit verification and explicit rollout
authorization remain with the controller.
