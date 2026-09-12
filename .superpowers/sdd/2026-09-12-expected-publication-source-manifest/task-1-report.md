# Task 1 report: expected final publication source manifest

## Result

Implemented the inactive pure projection
`project_publication_source_manifest(initial)` for the exact final selected-source
fingerprint after all sealed publication operations succeed.

- The existing initial-baseline encoder is invoked first and its
  `PublicationError` is preserved.
- Selected trees retain complete immutable directory/file membership. Exact writes
  replace files with their sealed descriptor and bytes, exact deletes remove only
  files, and missing deletes create nothing.
- Writes beneath selected trees create only missing selected-root/descendant
  directory entries. Existing directory objects/modes are retained.
- The publisher's already-observed `0755` new-parent mode is now named
  `PUBLICATION_DIRECTORY_MODE` and shared by its one existing `fchmod` site and the
  projection. No race, descriptor, error, fsync, lock, or existing-directory
  behavior changed.
- Exact selected-file writes/deletes are projected without expanding selection.
  Component-prefix siblings and unrelated operations stay outside the selected
  fingerprint.
- Writes that would make a selected tree/file shape impossible fail with bounded
  `PublicationError("manifest_invalid")`.
- The existing source-manifest factory remains the sole canonical payload/digest
  implementation.
- Documented the helper as inactive final-state projection and recorded the future
  guarded-comparison, durable-authority, and recovery limitations.

## TDD evidence and chronology

### Required first real RED (before production edits)

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_projection.py::test_projected_manifest_matches_real_write_delete_and_new_directories
```

Actual result (exit 1):

```text
F                                                                        [100%]
E       ModuleNotFoundError: No module named 'harness.squad_source_projection'
1 failed in 0.18s
```

The real transaction, sealed-operation capture, existing-directory-mode assertion,
and independent initial file assertions all succeeded before the import. The failure
was therefore the expected missing-feature failure, not a setup or capability error.
Root was notified of this exact result before any production edit.

### Minimal GREEN

After adding the projection and shared publisher mode, the same command produced:

```text
.                                                                        [100%]
1 passed in 0.17s
```

### Expanded RED/repair chronology

The first expanded focused run produced 17 passes and four failures. Three failures
were test-construction errors caught before acceptance: one hand-written digest was
incorrect, one synthetic operation tuple was not in the baseline guard's required
sorted order, and one control combined ancestor-related operations that the sealed
operation contract itself forbids. The digest was independently corrected, targets
were sorted, and the delete controls were separated into individually valid sealed
snapshots.

The fourth failure was the intended additional production RED:

```text
E       RecursionError: untrusted projection structure
4 failed, 17 passed in 0.30s
```

This showed that an unexpected structural error after the initial guard was not yet
normalized. The projection now preserves `PublicationError` and normalizes other
`Exception` failures to `PublicationError("manifest_invalid") from None`, without
catching `BaseException`. The initial guard remains before this normalizer.

Expanded focused GREEN:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_projection.py
.....................                                                    [100%]
21 passed in 0.26s
```

After tightening the no-op write and delete-retains-newly-empty-directory evidence,
the final focused iteration of the same command produced:

```text
.....................                                                    [100%]
21 passed in 0.25s
```

## Final required verification

The exact required four-module set was run once:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_projection.py tests/unit/test_squad_source_manifest.py tests/unit/test_squad_source_baseline_codec.py tests/unit/test_squad_publication.py
```

Actual pristine output (exit 0):

```text
........................................................................ [ 40%]
........................................................................ [ 80%]
...................................                                      [100%]
179 passed in 1.46s
```

No full-suite, million-scale, live, provider, post-commit, stopped-smoke, activation,
or installation run was performed.

## Evidence classification

### Actual filesystem/publication evidence

- Required real write/delete publication matched the projected final manifest;
  independent assertions proved preserved binary hidden content, deleted old content,
  CRLF postimage bytes, existing `0750` root mode, and newly created `0755` directory.
- Real writes made a missing selected nested tree and exact missing selected file
  present; an untouched missing tree and missing no-op delete remained absent.
- A retained original two-target capture projected identically before and after a
  forced one-target interruption, then matched the eventual real final recapture
  after retry. Fresh partial and final captures were rejected by the initial guard.
- Five independent real post-publication mutations (hidden-file addition,
  empty-directory deletion, file-byte change, file-mode change, and directory-mode
  change) each produced a recaptured fingerprint different from the expectation.
  These tests demonstrate detection by comparison only; the pure projection does not
  prevent interference.
- The established publisher test in the required `test_squad_publication.py` module
  independently exercises canonical new-parent modes under a restrictive umask.

### Synthetic pure evidence

- One complete payload and digest are hand-literal expectations, independent of the
  projection's factory call.
- Empty and unchanged selections, absent/present empty trees, missing/present empty
  files, existing nondefault directory modes, nested new directories, hidden/binary,
  CRLF, wide legacy bytes, mode-only and exact no-op writes, and deletion retaining
  an empty directory are covered.
- Exact selected-file writes/deletes, unselected operations, component-prefix
  siblings, missing relationship deletes, and every impossible write relationship
  are covered with component-relative cases.
- Noninitial and malformed initial snapshots are rejected through the existing guard;
  output freezing and unchanged original dataclass/bytes identity are checked.

### Static/tripwire evidence

- After real setup/capture, tripwires forbid builtins and `io` open, `Path` open/stat,
  `os.open/listdir/scandir/stat`, SQLite, socket, wall/monotonic clock, randomness,
  and secret bytes. Two projections remain equal without triggering any tripwire.
- Diff inspection confirms only the named new-parent `fchmod` call changed in the
  publisher and no capture, codec, factory, parser, store, or controller code changed.

## Files changed

- `src/harness/squad_source_projection.py` (new)
- `tests/unit/test_squad_source_projection.py` (new)
- `src/harness/squad_publication.py`
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-expected-publication-source-manifest/task-1-report.md`

The concurrently present untracked
`docs/superpowers/plans/2026-09-12-guarded-source-publication.md` is outside this
task and was not modified or staged.

## Self-review

- Re-read the brief and inspected the exact task diff after verification.
- Confirmed every path relationship uses components, not raw string prefixes.
- Confirmed output tree/file tuple order and complete unchanged membership are
  retained, while local dicts are detached and never written back to input values.
- Confirmed missing tree roots are created in the projection only by descendant
  writes, and all new selected directories share the publisher's named mode.
- Confirmed exact selected-file replacement preserves the missing `None` versus
  present empty `bytes` distinction.
- Confirmed no reference/candidate diagnostics, decoder, partial-prefix, accepted
  head, recovery, current-filesystem fallback, or activation API was added.
- Confirmed the projection module remains focused (127 lines) and the larger test
  file reflects the brief's intentionally broad contract matrix.
- No unresolved correctness concern found.

## Diff check

Command run before report creation:

```text
git diff --check
```

Actual result: exit 0 with no output.

After explicitly staging only the five task files above (and excluding the root-owned
untracked plan), the final check including this report was:

```text
git diff --cached --check
```

Actual result: exit 0 with no output. `git status --short` listed exactly the staged
task files plus the excluded untracked root-owned plan.

## Concerns

None. The helper remains deliberately inactive. Authentication, guarded fresh
comparison, durable accepted-source history, candidate scope/review binding,
partial-recovery ownership, and completion integration remain future work exactly as
documented.
