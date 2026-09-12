# Task 1 implementation report: selected source observation manifest

## Status

DONE. The requested inactive, pure selected-source observation fingerprint is
implemented, documented, and covered without activating a controller, store,
provider, publisher, accepted-source head, or schema.

## Implementation

- Added frozen, slotted `SourceManifestSnapshot(payload, sha256)`.
- Added keyword-only `snapshot_source_manifest(*, trees, files)` for the exact
  immutable source-observation tuples.
- Reused the reviewed baseline codec helpers `_tree_value`, `_encode_image`,
  `_path`, and `_source_selection`; no validation logic or filesystem manifest
  walk was copied.
- Validated every retained byte image before removing only `content_base64` from
  fresh projection dictionaries.
- Emitted the exact closed version-1 canonical ASCII JSON projection and its
  lowercase unprefixed SHA-256.
- Normalized structural, Unicode, key, type, value, overflow, and recursion
  failures to bounded `PublicationError("manifest_invalid")` with underlying
  contexts suppressed.
- Documented observation scope, exact metadata wire, initial-codec separation,
  lack of accepted authority, and remaining durable integration.

## TDD chronology and evidence

### Required real RED before production edits

Only the required real regression and secure-POSIX skip fixture existed at this
point. The test created and sealed a real publication, successfully completed
`inspect_sources(tree_paths=("specs",), file_paths=("absent",))`, and asserted the
captured tree retained `b"hello"` before importing the missing module.

Command:

```text
PYTHONPATH=src /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_manifest.py::test_real_selected_sources_have_independent_closed_manifest
```

Relevant output:

```text
E       ModuleNotFoundError: No module named 'harness.squad_source_manifest'
1 failed in 0.17s
```

This was the expected missing-feature failure after actual capture, not a capture,
fixture, or assertion failure. The root was notified of this exact RED before any
production file was created.

### Initial GREEN

After the minimal shared-validator projection was implemented, the same command
produced:

```text
1 passed in 0.17s
```

### Expanded focused coverage

The first expanded run executed 18 tests. Seventeen passed; the empty-wire test
contained an incorrectly transcribed independently expected digest:

```text
17 passed, 1 failed in 0.30s
```

An independent standard-library calculation confirmed the literal should be
`2947fe0a303cc99f6074aecd8f6f39b741128c3644acb76c193be41394b05f07`.
Only that test expectation changed. The focused file then produced:

```text
18 passed in 0.27s
```

### Self-review RED/GREEN for suppressed Unicode context

Self-review found that a reused validator's already-bounded `PublicationError`
could retain an underlying `UnicodeEncodeError` context. A focused regression was
added before changing the production catch boundary.

Command:

```text
PYTHONPATH=src /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_manifest.py::test_unicode_validation_context_is_suppressed
```

RED:

```text
E       AssertionError: assert False is True
1 failed in 0.20s
```

The production boundary was then changed to re-raise the single bounded code
`from None`. The same test passed, followed by the expanded focused file:

```text
1 passed in 0.16s
19 passed in 0.26s
```

After adding the explicit present-empty-tree and recursive scalar-type assertions,
the final focused iteration was:

```text
19 passed in 0.28s
```

## Coverage evidence

Actual real filesystem/publication execution covers:

- the exact independent golden wire after successful selected-source capture;
- missing versus empty files, a wholly empty selected tree, nested empty
  directories, hidden/binary files, CRLF, non-ASCII paths, and wide legacy bytes;
- repeated captures through different real transaction IDs;
- independent content, file-mode, directory-mode, hidden-membership,
  absence/presence, empty-directory, selected-root, and selection-coverage
  changes;
- unchanged fingerprint after a real unselected-file change, proving only the
  explicit scope is observed and making no completeness/authentication claim;
- a real two-target interrupted promotion with distinct initial/partial/final
  manifests, stable final retry, and the separate initial codec continuing to
  reject noninitial captures;
- real capture followed by a pure-call tripwire blocking builtins, `io`, `Path`,
  `os.open/listdir/scandir/stat`, SQLite, socket, time, and random entry points.

Executed synthetic counterfactual inputs cover exact tuple/dataclass enforcement,
deleted fields, malformed Unicode and relative paths, noncanonical order,
duplicates, cross-kind overlaps, interleaved prefix-sibling ancestry, valid prefix
siblings, malformed tree membership, content type, and image byte/hash mismatch.
The recursion normalization counterfactual deliberately injects a dependency
`RecursionError` containing untrusted text and verifies it is absent from rendered
traceback output. These are executed invalid-input tests, not claims about a live
provider or durable authority.

## Final requested covering run

Run exactly once after focused iteration:

```text
PYTHONPATH=src /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_manifest.py tests/unit/test_squad_source_baseline_codec.py tests/unit/test_squad_publication_sources.py tests/unit/test_element_identity_candidate_sources.py
```

Output:

```text
249 passed in 1.42s
```

No whole-suite, million-scale, live, provider, postcommit, global-install, main, or
stopped-smoke run was performed.

## Files changed

- `src/harness/squad_source_manifest.py`
- `tests/unit/test_squad_source_manifest.py`
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-selected-source-manifest/task-1-report.md`

## Self-review

- Completeness: checked every Task 1 checklist item against implementation,
  executed tests, and documentation. No decoder, storage, registration,
  classifier, source-root inference, or activation was added.
- Exact wire: verified the literal golden and empty payloads, root/member shapes,
  all-string-or-null scalar leaves, ASCII escaping, and absence of bytes/base64.
- Reuse and purity: the production module imports only standard-library hashing,
  JSON/dataclass support, existing snapshot types, publication error, and the four
  required pure validators. The only dictionary mutation removes
  `content_base64` from newly returned projection dictionaries, never caller data.
- Detached output: source inputs remain unchanged across factory calls; later
  deliberate synthetic input mutation does not affect returned strings. The
  output is the exact frozen, slotted dataclass.
- Mutation review: removing byte validation, mode/path projection, canonical order
  enforcement, content removal, ASCII encoding, digesting, tuple/type enforcement,
  or exception suppression would fail at least one focused test.
- `git diff --check` is recorded immediately before commit after staging the exact
  task files.

## Concerns

None. This is intentionally an observation fingerprint only. Selection
completeness, accepted authority, durable comparison, publication receipt binding,
and source/ledger/graph coordination remain explicit future integration work.
