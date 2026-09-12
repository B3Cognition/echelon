# Task 1 report: detached projected publication source images

## Status

DONE. The approved durable-identity graph-input prerequisite is implemented on
`fix/delivery-controller-contract` without activating a caller, graph, runtime,
capture, source-selection, or publication-policy path.

## Implementation and files

- `src/harness/squad_source_projection.py`
  - Added the exact frozen, slotted `ProjectedPublicationSources` DTO with
    `trees`, `files`, and `manifest` fields.
  - Added `project_publication_source_images(initial)`. It runs the existing
    `encode_initial_publication_sources` guard, then returns the exact final
    selected source images after all sealed operations.
  - Extracted one `_project_selected_sources` transformation shared by the new
    public API and the existing private prefix transformer. There is no copied
    projection loop or second transformation policy.
  - Preserved `project_publication_source_manifest(initial)` and
    `_transform_selected_sources(initial, prefix, *, new_directories=())`; each
    still returns the same `SourceManifestSnapshot` result expected by existing
    callers and guard recovery.
  - Reconstructs every returned tree, directory, tree-file, selected-path, and
    image-descriptor record. Retained immutable strings and bytes are preserved
    exactly, while later forced damage to caller-held frozen records cannot alter
    the projection.
  - Creates and validates the manifest once from the exact returned tree/file
    tuples through `snapshot_source_manifest`.
- `tests/unit/test_squad_source_projection_images.py`
  - Added real guarded publication RED/GREEN coverage; independently specified
    complete tree/file/image records and literal manifest payload/hash; rich pure
    mixed-operation coverage; missing/empty distinctions; canonical new parents;
    prefix siblings and outside-operation controls; deep detachment/frozen-value
    checks; malformed initial guard parity; baseline-codec rejection of the DTO;
    no-I/O/process/environment/authority tripwires; and real interrupted/reloaded
    prefix plus partial-parent compatibility.
  - Pure tests have no POSIX skip. Only the two tests that perform real secure
    publication use the existing secure-capability fixture.
- `docs/element-identity-storage.md`
  - Documented the new value carrier, exact manifest agreement, deep detachment,
    retained legacy guard contract, and explicit lack of capture or acceptance
    authority.
- `.superpowers/sdd/2026-09-13-projected-source-images/task-1-brief.md`
  - Requirements brief retained verbatim and force-added because `.superpowers/`
    is ignored.
- `.superpowers/sdd/2026-09-13-projected-source-images/task-1-report.md`
  - This report; force-added for the same reason.

The root-owned `.superpowers/sdd/2026-09-13-projected-source-images/progress.md`
was already dirty during the task and was excluded from every stage and commit.

## Actual RED

Working directory:
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_squad_source_projection_images.py::test_projected_images_match_real_guarded_publication -q
```

Output summary: exit 1, `1 failed in 0.17s`. The real transaction begin, staged
write, seal, successful initial selected-tree capture, exact `b"\x00\xff"`
assertion, and existing current manifest projection all completed first. The test
then failed at the intended call with:

```text
AttributeError: module 'harness.squad_source_projection' has no attribute 'project_publication_source_images'
```

The root was notified of this exact RED before any production edit.

Why this RED was valid: it exercised the real secure publication path and failed
only because the requested public API did not yet exist, rather than from setup,
capture, sealing, or current projection behavior.

## GREEN and focused iterations

After the minimal shared extraction, the same command from the same working
directory exited 0 with `1 passed in 0.18s`.

Expanded focused command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_squad_source_projection_images.py -q
```

The first expanded run produced `6 passed, 1 failed in 0.25s`. This was a test
fixture correction, not a production defect: mode `0o1000` is valid under the
existing `0..0o7777` publication mode contract. The malformed-mode case was
corrected to `0o10000`. The next run exited 0 with `7 passed in 0.24s`.

Self-review then strengthened detachment assertions from representative records
to every retained tree, directory, file/path, input image, and operation postimage
relationship. The exact same focused command was rerun and exited 0 with
`7 passed in 0.24s`.

## Named covering result

The required six-module covering set was run exactly once after focused GREEN,
from the same working directory:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_squad_source_projection_images.py tests/unit/test_squad_source_projection.py tests/unit/test_squad_source_guard.py tests/unit/test_squad_source_manifest.py tests/unit/test_squad_publication_sources.py tests/unit/test_element_identity_source_store.py -q
```

Result: exit 0, `369 passed in 20.73s`. There were no failures, errors, warnings,
or skips. No broad unit, capacity, live, provider, global-install, or unchanged
post-commit suite was run.

## Self-review

- One transformation policy: confirmed the new DTO and both legacy manifest
  surfaces delegate to `_project_selected_sources`; there is one operation/tree/
  selected-file loop.
- Public compatibility: the legacy public manifest projector delegates to the new
  projection's `.manifest`; all existing source projection tests passed.
- Private compatibility: the private signature is unchanged. Real interrupted
  prefix and canonical partial-parent observations matched its manifest; the
  complete existing guard module passed.
- Exactness: rich independent expectations cover all output records, modes,
  hidden/binary/empty bytes, deletes, mode-only/no-op writes, missing and empty
  selected files/trees, nondefault modes, multilevel parents, and literal canonical
  payload/hash. Recomputed output manifest equals the returned manifest.
- Detachment: all retained nested records and all descriptors are fresh. Forced
  mutation of original nested records and operation descriptors after projection
  leaves the independently retained expected output unchanged.
- Validation: wrong top-level types, nonzero prefix, subclasses, damaged frozen
  images, invalid hashes/content/modes/layout, and impossible target ancestry retain
  bounded `PublicationError("manifest_invalid")`. The DTO cannot impersonate an
  initial physical capture through the baseline codec.
- Side effects: scoped tripwires cover file/stat/listing/write, process,
  environment, randomness, clock, socket, SQLite, inspection, and publication-lock
  access. Projection completed without invoking them.
- Diff scope: production changes are limited to the one allowed module. Tests and
  the requested documentation are the only other implementation files.

No code correction was needed after the named covering run. There are no later
implementation amendments.

## Provenance

- Required original BASE and branch starting HEAD:
  `e531f7f6d3306d58ca7304d96af8974b27d57a58`.
- Verified merge-base before edits:
  `e531f7f6d3306d58ca7304d96af8974b27d57a58`.
- Implementation stage contained exactly:
  `docs/element-identity-storage.md`,
  `src/harness/squad_source_projection.py`, and
  `tests/unit/test_squad_source_projection_images.py`.
- Exact verified implementation staged tree:
  `49345ce49d120b399367041411c3140c799c1d8e`.
- Implementation commit:
  `d5183dcd8c3d6c23d98d14ea6670c1d2bcfb0e90`; its committed tree is exactly
  `49345ce49d120b399367041411c3140c799c1d8e`.
- A documentation-only follow-up force-adds the unchanged task brief and this
  report. Its commit identifier is intentionally reported in the parent handoff,
  because a commit cannot contain its own hash.

## Concerns and limitations

No scoped implementation concern remains. This output supplies only the already
selected projected bytes and metadata. It is not a complete graph builder or
physical capture and does not prove source-selection completeness, logical source
mapping, semantic acceptance, graph sealing, publication freshness, receipt
authentication, runtime activation, or repair completion. Those remain with the
future trusted graph/completion owners described by the brief.
