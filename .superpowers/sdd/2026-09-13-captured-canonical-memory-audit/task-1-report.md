# Task 1 implementer report

Status: DONE. No unresolved implementation or native-compatibility concern.

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Review base: `1cfbb98532d75a820b5469d35d97e9ac4c9e5e15`.
Implementation commit: `36f15ddf3fa256926300e8135ad253dc1397fc98`
(`feat(memory): audit captured canonical sources through read-only storage`).
Exact staged implementation tree tested and committed:
`a56f5865efc87afacaaf9bbc5e27d1b09291dc20`.

## Implementation

- Added only the opt-in `audit_captured_spec_memory` entry point in the new
  captured audit module. Full selected-tree validation precedes adapter/config
  acquisition; source hashes, main/support snapshots and the reconciliation table
  derive from detached exact bytes mapped to canonical logical paths. Absolute
  project paths are not resolved or used to reread sources.
- Shared native snapshot metadata construction while retaining both legacy disk
  loaders' read ordering and their existing `artifact_hash` calls.
- Extracted native report classification/assembly and already-parsed extras
  classification without duplicating or redesigning native policy. The native
  factory/reconciliation monkeypatch seams and bounded extras read ordering remain
  intact. Cleanup still calls the same native planner. An optional private support
  tuple avoids disk support loading for captured calls.
- Actual acquisition uses the native adapter/miner, run ID `audit`, existing
  read-only collection entry, native expected-ID response parser and unchanged
  complete wing scanner. A get-only private wrapper deep-copies each backend
  response before another read. Expected ID membership and in-wing row equality
  with the full scan are required. Extras use that already-acquired scan.
- Invalid request/source exceptions are bounded outside the exception handler.
  Ordinary adapter/storage failures and operational SystemExit return unavailable;
  ordinary planner/reconciliation failures return native fail reports. Keyboard
  interrupts propagate. No creating access, disk fallback or live runtime hook.
- Documented the observed interval, physical/logical mapping, provenance limits,
  complete scan budget, native policy and remaining publication/lifecycle owners.

Changed implementation/test/document paths (and no others):

1. `src/echelon/mempalace_captured_audit.py`
2. `src/echelon/mempalace_audit.py`
3. `src/echelon/mempalace_requirements.py`
4. `tests/unit/test_mempalace_captured_audit.py`
5. `docs/element-identity-storage.md`

This report is a separately authorized administrative artifact. Root-owned
plan/brief/progress files were excluded from staging and commits. The existing
dirty progress file remained dirty. No subagents, reviewers, installation,
provider/backend integration, actual global memory opening, capacity benchmark,
full unit suite or runtime activation was performed.

## Test evidence and actual chronology

All pytest commands below used the stated worktree and the absolute executable.
Each entry records an actual execution, including unsuccessful fixture diagnostics.

### First RED, before production edits

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py::test_captured_audit_reads_candidate_tree_and_actual_collection -q
```

Result: exit 1, `1 failed in 0.60s`.
Failure: `ModuleNotFoundError: No module named 'echelon.mempalace_captured_audit'`.
Before that missing API call, real sealed transaction/source inspection/projection
and native adapter/miner planning succeeded with two candidate rows. The existing
disk audit returned fail with zero present rows. Only the writer/collection
storage boundary was simulated, with a fixture-local palace path lookup. Root was
notified of this genuine absent-API RED before production editing. There were no
fixture corrections before this first RED.

### Failed first GREEN attempts and corrected fixture

After implementation, the same exact command ran twice:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py::test_captured_audit_reads_candidate_tree_and_actual_collection -q
```

Results in order: exit 1, `1 failed in 0.62s`; exit 1, `1 failed in 0.61s`.
The second invocation followed adding report details to the assertion message.
Both reached the new API but received native fail instead of the expected pass.

Diagnostic command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py::test_captured_audit_reads_candidate_tree_and_actual_collection -q --showlocals
```

Result: exit 1, `1 failed in 0.62s`. Investigation identified a fixture mistake:
the initial spec directory was `specs/demo`. Scope validation and native loading
accept that selection, but inherited reconciliation requires a three-digit-prefixed
canonical slug. Both rows therefore correctly appeared non-canonical. Changed only
the new fixture to `specs/001-demo`; preserved the inherited production policy.
Root was notified and agreed. This directory rule is independent of element-ID
width; the real requirement label remains exactly `FR-1000000`.

GREEN command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py::test_captured_audit_reads_candidate_tree_and_actual_collection -q
```

Result: exit 0, `1 passed in 0.59s`.

The final first-test fixture additionally verifies that matching old rows pass
the native disk audit with two present rows before installing candidate rows and
observing its failure. This makes the source-change causal control local to that
test, rather than relying only on the later unchanged-source parity tests. That
addition was included in subsequent focused and covering executions below; it
does not retroactively change the initial RED or fixture-correction history.

### Expanded focused checks

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py -q
```

First expanded execution: exit 0, `103 passed in 0.95s`.
This included 48 full-report native/captured parity combinations, all supports,
physical selection, no source reread, validation and coherent complete acquisition.

After adding operational failure and graph composition coverage, the same command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py -q
```

Result: exit 1, `1 failed, 133 passed in 1.07s`.
The new graph test incorrectly expected presence `stale`. Existing native graph
semantics encode a stale row as presence `invalid`, with reconciliation status
`fail` and issue code `stale`. Corrected that test expectation and added the
explicit retained stale issue assertion. No graph or audit production change.

Scoped corrective check:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py::test_actual_audit_observation_is_preserved_in_graph_contribution -q
```

Result: exit 0, `3 passed in 0.57s`.

### Final covering run, exactly once

Confirmed all six requested module paths existed before running. Self-reviewed
the production extraction/new acquisition code and new tests, staged only the
five scoped files, and ran `git diff --cached --check` successfully. Recorded
`git write-tree` as `a56f5865efc87afacaaf9bbc5e27d1b09291dc20`.

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_mempalace_captured_audit.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_requirements.py tests/unit/test_context_reconciliation_captured.py tests/unit/test_spec_graph_memory.py tests/unit/test_mempalace_retarget.py -q
```

Result: exit 0, `583 passed in 2.30s`. Output was clean, with no warnings or skips.
The new module contributes 135 cases. No test path correction was needed.

Before committing, `git diff --cached --check` passed again, scoped unstaged diff
was empty, and `git write-tree` still matched the tested tree. The implementation
commit's `HEAD^{tree}` equals that exact value. No unchanged postcommit test rerun.

## Coverage and self-review

- Genuine native expected rows and parser content throughout, temporary config
  and palace location, fake read-only collection only at the storage boundary.
  Source preparation uses native publication inspection/projection or complete
  source inspection. Mutation/creating storage methods are tripwires.
- Full report parity for matching, missing, stale content and hashes, wing/room,
  path/scope/canonical flag/requirement identity/schema mismatches, support kind,
  all terminal lifecycle statuses, active duplicates, historical and ignored
  evidence extras, malformed expected responses and duplicate response IDs,
  probes false/true, and native empty planning. Kept inherited classification quirks.
- Canonical, run-local and staging physical trees produce canonical logical row
  keys and report paths; all thirteen direct support filenames count. Nested
  support and nonselected binary files do not become mined supports. Full original
  tree validation rejects damaged ignored hashes/content/modes/membership.
- Absent trees, present empty trees, and directories called spec.md are invalid;
  a present empty spec reaches native planning and still scans relevant extras.
- Removing source files plus disk loader, disk reconciliation, path resolution
  and byte-read tripwires does not affect captured results. Original tree data
  mutated by the adapter factory cannot alter the already detached source image.
- 1,003 total rows expose an active duplicate after the native 1,000-row window;
  native control passes, captured strict audit fails with the late duplicate,
  and a 1,002-row budget is unavailable. Exact/empty/512/513-row controls retain
  existing scanner page size, offsets, probes and no extra bounded query.
- Unsupported/truncated/excess/duplicate/malformed/wrong-wing pages and changed
  order/content/nested reused metadata are unavailable. Expected rows added,
  removed or changed between expected fetch and complete scan are unavailable,
  including nested metadata mutation. Unrequested valid and malformed expected
  IDs reject before scanning. Legitimate wrong-wing rows retain native fail.
- Exact budget/bool/spec shape checks and absolute Path validation run before
  adapter acquisition; ordinary validation exceptions have no cause/context or
  leaked nested source error. Required budget omission follows Python signature
  TypeError. A returned audit cannot replace the selected source tree.
- Ordinary errors/SystemExit/KeyboardInterrupt covered at adapter, main/support
  planning, read-only open, get, deep copy and reconciliation seams; real invalid
  UTF-8 native planning and missing configuration behavior also covered.
- Actual missing/stale/unavailable reports converted with GraphMemoryAudit origin
  `returned` retain native graph failure/presence/issue semantics, with no current
  identity revision or complete-graph/completion claim.

Self-review found only the two fixture expectation corrections documented above.
Native loader acquisition order, main-then-support planning order, module-level
factory/reconciliation seams, shared scanner and cleanup behavior were preserved.
No source/config authentication, storage lease, publication authority or runtime
activation is implied. Remaining integration belongs to the owners in the brief.

## Later amendments

None to the tested implementation tree. This report is added in a report-only
commit after the implementation commit, and is not represented as part of the
tested implementation tree. Any future review fixes require separately named
scoped checks and a further report amendment.
