# Task 1 implementation report: captured candidate sources

## Status

DONE. Implemented the bounded, inactive, pure adapter that joins an existing
validated initial `PublicationSourcesSnapshot` to explicitly mapped immutable
`CandidateArtifact` values while independently checking exact physical operation
write/classification scope.

## What was implemented

- Added frozen slotted `CandidateSourceBinding` and `CapturedCandidateSources`
  values and the requested `assemble_candidate_sources` interface.
- Preserved `encode_initial_publication_sources(snapshot)` as the sole initial
  snapshot/image guard, outside the scoped-input normalization boundary, so an
  invalid snapshot retains its exact bounded `PublicationError`.
- Snapshotted and strictly revalidated all three caller sequences, exact binding
  types and damaged fields, canonical physical/logical paths, exact supported
  roles, uniqueness, opaque-write subset/disjointness, and bounded traceback
  suppression without interpolating caller payloads.
- Indexed sealed operations, selected external files, selected trees,
  directories and regular files. Resolution is component-wise and distinguishes
  absent selections/members from present empty files, exact directories from
  files, file ancestors from children, and prefix siblings from tree members.
- Preserved exact original and sealed proposed bytes as text without BOM, CRLF,
  whitespace or Unicode normalization. Invalid typed baselines raise a bounded
  request error; invalid typed proposals produce a physical-path diagnostic and
  omit only that artifact. Unbound binary/hidden selected sources stay untouched.
- Checked every sealed operation, including creation, deletion, missing-target
  no-op delete, no-op write and mode-only write, for exact writable permission
  and explicit typed/opaque classification. Opaque content is never decoded.
- Sorted artifacts by logical artifact path and deduplicated/sorted diagnostics
  with the existing candidate ordering. Returned only owned immutable tuples.
- Documented the adapter's physical/logical namespace split, validation and byte
  rules, operation policy, diagnostic handling, inactivity and remaining durable
  controller responsibilities.

## TDD evidence

### RED — required real capture before production edit

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py::test_sealed_original_and_proposed_bytes_supply_candidate_images
```

Relevant output:

```text
E       ModuleNotFoundError: No module named 'harness.element_identity_candidate_sources'
1 failed in 0.17s
```

The test used the real `SquadPublicationTransaction.begin`, staged write,
`add_write`, `seal`, and `inspect_sources` APIs. Assertions proved that the real
capture exposed the exact original and proposed bytes before the post-capture
import reached the expected missing-production-module failure. Root was notified
of this actual RED before the production module was added.

### GREEN — minimal adapter

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py::test_sealed_original_and_proposed_bytes_supply_candidate_images
```

Output:

```text
.                                                                        [100%]
1 passed in 0.16s
```

### Focused iteration

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py
```

Final focused output before covering verification:

```text
....................................                                     [100%]
36 passed in 0.43s
```

## Final covering verification (run once)

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py tests/unit/test_squad_source_baseline_codec.py tests/unit/test_squad_publication_sources.py tests/unit/test_discovery_identity_candidate.py tests/unit/test_element_identity_reference_sources.py
```

Output:

```text
........................................................................ [ 19%]
........................................................................ [ 39%]
........................................................................ [ 59%]
........................................................................ [ 79%]
........................................................................ [ 98%]
....                                                                     [100%]
364 passed in 7.18s
```

No full, million-scale, live-provider, installation, controller smoke, or
post-commit suite was run.

## Real versus synthetic fault provenance

- Real filesystem/publication APIs produced all sealed and selected-source
  snapshots. The required first regression and operation cases did not mock
  publisher or source bytes.
- The partial-publication test used the real two-target publisher and real retry.
  Its deterministic `fault_hook` raised `RuntimeError("synthetic interruption")`
  at promotion position 1; the resulting partial filesystem state, inspection,
  existing initial-codec rejection, and successful retry were real.
- The I/O-purity test captured a real snapshot first, then installed synthetic
  tripwires on built-in/io/Path opens, relevant `os` calls, SQLite, socket, clock
  and randomness entry points only during detached assembly. It also compared an
  independent byte inventory and canonical retained encoding before/after.
- The real store smoke initialized a fixture-local `IdentityStore`, explicitly
  imported/adopted sanitized before definitions, assembled a real sealed after
  image and unchanged evidence, and executed the existing discovery and reference
  validators. Registry and canonical source contents were asserted unchanged.

## Files changed

- `src/harness/element_identity_candidate_sources.py` (new)
- `tests/unit/test_element_identity_candidate_sources.py` (new)
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-identity-captured-candidate-sources/task-1-report.md` (new)

## Self-review

### Executed review evidence

- The original failure was observed before production code and the same real
  regression passed after the minimal implementation.
- The focused module passed 36 tests; the exact five-module covering command
  passed all 364 tests with no warnings or stray output.
- `git diff --check` was clean before covering verification and was repeated after
  the final report was written.

### Static review findings

- Re-read the 89-line task brief and inspected the complete task diff against each
  stated interface, validation, resolution, byte, diagnostic, operation-scope,
  purity and inactivity requirement.
- Confirmed the new production module imports no parser, store, provider,
  filesystem or managed-controller integration and modifies no existing codec,
  capture, publisher, parser, scope, authority or reference-validator module.
- Confirmed physical diagnostic paths never reuse mapped logical artifact paths,
  opaque operations produce no artifacts, and operation diagnostics are collected
  independently of successful typed artifact decoding.
- Confirmed no derivation of spec roots, filename roles, labels, identities,
  references, grants, namespace or semantic verdicts was introduced.
- Mutation check: tests fail for missing initial guard, wrong current/postimage
  selection, textual rather than component path matching, missing exact operation
  permission/classification, decoding opaque/unbound binary sources, normalization
  of exact text, wrong diagnostic namespace/order, coercive input handling, I/O,
  snapshot mutation, store mutation, or acceptance of partial/completed captures.

No self-review defect remained after focused iteration.

## Concerns and limitations

No correctness concern within the assigned adapter scope. By design this is only
detached assembly: it does not authenticate selection completeness, accepted
source heads, namespaces, roles, semantic edit scope or publication authority.
Managed registration/schema/provider integration, durable intent/recovery,
semantic review, and publication/ledger/graph/memory completion remain explicitly
outside this task. A later caller must retain the complete physical snapshot and
reject any returned diagnostics before treating the artifact tuple as successful.

## Round 1/5 review fix report

Fix base: `57b0d2cf9955df1017496c8431b96f918cef9af7`.

### Changes

- Broadened only the caller-controlled `_normalize` boundary to catch ordinary
  `Exception` failures. Any custom `Sequence` snapshot/validation failure now
  becomes the constant `ValueError("invalid captured candidate source request")`
  with `from None`. `BaseException` cancellation/exit signals are not caught.
- Kept `encode_initial_publication_sources(snapshot)` before and outside that
  boundary, so initial snapshot `PublicationError` remains unchanged.
- Preserved the original real-store smoke with unchanged evidence and added a
  separate real sealed evidence write with distinct valid before/after contents.
  The reference source validator accepts the actual assembled after-image hash
  and rejects the actual retained before-image hash.

### TDD RED — unbounded custom Sequence failure

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py::test_custom_sequence_runtime_failure_has_bounded_suppressed_traceback
```

Relevant output:

```text
E       RuntimeError: UNTRUSTED-RUNTIME-UNTRUSTED-RUNTIME-...
tests/unit/test_element_identity_candidate_sources.py:385: RuntimeError
1 failed in 0.20s
```

This was an actual production RED: a custom ordinary `Sequence.__len__` raised a
caller-controlled `RuntimeError`, and the full repeated message escaped into the
formatted pytest traceback. The real initial snapshot had already validated.

### TDD GREEN — bounded normalization

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py::test_custom_sequence_runtime_failure_has_bounded_suppressed_traceback
```

Output:

```text
.                                                                        [100%]
1 passed in 0.18s
```

The regression formats the raised `ValueError` traceback and proves the untrusted
message is absent and the explicit cause is `None`.

### Covering verification after amended code

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_candidate_sources.py
```

Output:

```text
......................................                                   [100%]
38 passed in 0.43s
```

Per the fix instructions, the five-module/full/million/live/provider/install and
post-commit suites were not repeated.

### Fault and fixture provenance

- The unbounded-message RED used a synthetic custom caller `Sequence`, while its
  `PublicationSourcesSnapshot` came from a real sealed publication inspection.
- The changed-evidence composition coverage uses a real staged write, seal and
  `inspect_sources` capture. Its `before_text` is the actual physical preimage and
  its `after_text` is the distinct sealed stage content. Both hashes are computed
  from those assembled strings; no unrelated synthetic stale digest is used.
- The unchanged-evidence store/reference smoke remains present and unchanged,
  preserving its separate retained-evidence coverage.

### Round 1 self-review

Executed review: the dedicated RuntimeError test demonstrated RED then GREEN, and
the complete new test module passed 38/38 with pristine output. Static review:
re-read the amended 91-line brief and inspected the fix diff from `57b0d2cf`; the
new broad catch is confined to `_normalize`, cannot intercept initial snapshot
validation, and does not catch `BaseException`. The added reference test proves
before and after hashes differ before checking clean after-hash composition and
the exact stale-before diagnostic. No existing codec, publisher, capture, parser,
scope, store, authority, or reference-validator module was changed. The unrelated
untracked selected-source-manifest plan remains untouched. Reviewer minors about
docstring wording and deleted-slot/valid-empty coverage remain deferred to final
triage as directed, not silently expanded into this fix loop.
