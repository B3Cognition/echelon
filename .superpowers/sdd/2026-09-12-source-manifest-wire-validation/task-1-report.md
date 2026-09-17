# Task 1 implementer report: source-manifest wire validation

## What I implemented

- Added `harness.squad_source_manifest_codec` with the required public
  `decode_source_manifest` and `validate_source_manifest` functions.
- Decoding accepts only the existing canonical ASCII version-1 metadata wire,
  validates every closed object/array/scalar shape, canonical path, mode, image,
  tree layout and complete sorted/non-overlapping selection, then returns a fresh
  existing `SourceManifestSnapshot` with the unchanged payload and computed
  lowercase unprefixed SHA-256.
- Validation requires the exact existing frozen snapshot class, delegates payload
  validation to the decoder, validates the supplied digest with the publisher's
  existing SHA-256 validator and returns the detached decoded snapshot.
- Both public functions bound ordinary malformed input and reused-validator
  failures to `PublicationError("manifest_invalid")` from no context while
  preserving `BaseException` propagation.
- Extracted the initial baseline codec's existing membership/hierarchy rules into
  `_validate_tree_layout` and left its dataclass, byte/hash, mode and returned-value
  validation order and behavior intact.
- Documented the codec as an inactive representation boundary and explicitly
  documented that self-consistent changed metadata is not authenticated source
  provenance, an accepted head, a publication receipt or activation.

No store, schema, source-head, context registration, capture, source-manifest
factory, publisher, controller, provider or graph code was changed.

## Tests and results

- New codec test module: `90 passed in 0.22s` on its complete focused green run.
- Existing baseline codec after shared extraction: `36 passed in 0.21s`.
- Required final covering run, executed once:

  `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_manifest_codec.py tests/unit/test_squad_source_manifest.py tests/unit/test_squad_source_baseline_codec.py tests/unit/test_squad_source_projection.py tests/unit/test_squad_source_guard.py`

  Result: `240 passed in 1.88s`, exit 0, output pristine.
- Final focused check after making the valid prefix-sibling fixture also represent
  a present empty selected tree: `1 passed in 0.18s`, exit 0.
- `git diff --check`: exit 0 with no output.

Coverage includes the required real capture/factory round trip; literal payloads
and digests including empty selection; rich CRLF/binary/wide-ID/Unicode/mode/
absence/empty-directory captures; exact closed shapes; duplicate, numeric,
noncanonical and malformed JSON; hash/mode/path violations; sorted/unique/layout/
overlap violations; exact snapshot and damaged-field validation; bounded Unicode,
deep-JSON and reused-validator failures; explicit `BaseException` propagation;
self-consistent changed-hash acceptance without an authentication claim; and a
post-capture purity tripwire across filesystem, SQLite, network, clock and random
access surfaces.

## TDD evidence

### RED

Before any production edit, I added the exact required real regression and ran:

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_manifest_codec.py::test_real_manifest_round_trip_preserves_exact_existing_wire`

The real `inspect_sources` capture completed, the assertion preserved
`b"FR-1000000\r\n\x00\xff"`, and the existing `snapshot_source_manifest` factory
completed. The test then failed at the required import with:

`ModuleNotFoundError: No module named 'harness.squad_source_manifest_codec'`

Result: `1 failed in 0.17s`, exit 1. This was the expected missing-feature failure,
not a setup, capture or factory failure. I notified the root controller before
making production edits.

### GREEN

After implementation, the new test module passed 90/90, the extracted baseline
module passed 36/36, and the exact final five-module run passed 240/240 as recorded
above.

## Files changed

- `src/harness/squad_source_manifest_codec.py` (new)
- `tests/unit/test_squad_source_manifest_codec.py` (new)
- `src/harness/squad_source_baseline_codec.py`
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-source-manifest-wire-validation/task-1-report.md`

## Self-review findings

- Re-read the task brief line by line against the implementation and tests.
- Confirmed the new decoder reuses `_object`, `_array`, `_text`, `_path`,
  `_decode_mode`, `_source_selection`, `_validate_tree_layout` and the publisher's
  `_validate_sha256`; it never calls the byte-bearing baseline `_decode_image`.
- Compared the extracted tree-layout block with the original diff: all sorted,
  unique, absent-tree, root, containment, explicit-parent, collision and
  regular-file-ancestor checks are unchanged, and `_tree_value` still performs all
  exact snapshot/image/content validation before calling it.
- Confirmed canonical re-encoding uses the existing factory's `ensure_ascii=True`,
  `sort_keys=True` and compact separators and compares byte-for-byte before hashing.
- Confirmed outputs contain no source bytes, publication snapshot, accepted-head
  receipt or live wiring, and the existing simple `SourceManifestSnapshot`
  constructor remains untouched.
- Reworded the validator docstring during self-review to avoid implying that shape
  validation authenticates provenance.

## Issues or concerns

None for the implementation. An unrelated untracked root-owned plan file appeared
at `docs/superpowers/plans/2026-09-12-durable-source-context-heads.md`; it was not
read, modified or included in this task's commit.
