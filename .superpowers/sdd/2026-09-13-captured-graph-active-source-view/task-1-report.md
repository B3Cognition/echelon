# Task 1 report: explicit run-local graph source view

## Status

DONE. The scoped code, tests, and storage documentation are committed as
`0e2f7d37 feat: add captured run-local graph source view`. The exact staged tree
tested before that commit was `b15dc1c7ca2265d279b3ebe9b7e646c18a43daef`;
`0e2f7d37^{tree}` is the same tree. The controller-owned dirty `progress.md` was
never staged or included.

## Implementation

- Extended the existing keyword-only `build_captured_identity_graph` interface
  with `spec_source_path: str | None = None` while retaining the return type and
  every existing argument.
- Kept the existing scope, exact projected-source type checks, nested snapshot
  validation, and complete manifest recomputation/equality check before selector
  consumption.
- Reused `_source_path` for exact built-in string, UTF-8, and normalized
  project-relative validation. The only accepted values are the exact canonical
  `specs/<spec_id>` path or `runs/<one component>/specs/<spec_id>`.
- Selects exactly one original physical tree. There is no canonical/other-run/
  parent fallback. The original tree is passed directly to
  `build_spec_graph_structure`, which remains the owner of relative parsing and
  canonical graph paths.
- For run-local selection only, constructs one private component-aware byte-table
  view: removes entries beneath the canonical and selected physical roots, then
  maps every selected file to `specs/<spec_id>/<relative path>`. This prevents
  stale canonical blending while retaining unrelated RE/dependency bytes.
- Does not mutate or return a rebased manifest and adds no public carrier,
  parser, authority, alias map, runtime state, producer, provider, CLI, schema,
  codec, journal, memory writer, publisher, or completion behavior.
- Updated `docs/element-identity-storage.md` with exact selector grammar,
  logical/physical distinction, no-fallback and unchanged-wire behavior, and the
  intentionally missing runtime/promotion/completion integration.

## Tests and TDD evidence

### RED (production still at BASE)

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_active_view.py::test_run_local_view_matches_canonical_graph_and_retains_history -q
```

The real fixture completed identity reservation, Movement revision 1, exact
parsed evidence binding to revision 1, revision 2, two physical tree capture,
separate canonical comparison capture, native planning, independent identity/
history assertions, and expected graph assembly before reaching the new call.
Relevant output:

```text
FAILED tests/unit/test_spec_graph_active_view.py::test_run_local_view_matches_canonical_graph_and_retains_history
TypeError: build_captured_identity_graph() got an unexpected keyword argument 'spec_source_path'
1 failed in 0.68s
```

This was the expected genuine feature RED, not an absent-module, stub-validator,
or live-audit failure. Root was notified before the production edit. No fixture
correction was needed for this RED.

### First GREEN

The identical command after the minimal production edit produced:

```text
.                                                                        [100%]
1 passed in 0.65s
```

Root was notified immediately.

### Exact subsequent focused chronology

1. After adding the first portable selector/ownership groups, running the whole
   new module produced `2 failed, 21 passed in 0.72s`. Both failures occurred in
   identity history projection after otherwise valid graph construction: the
   value fixtures introduced `FR-000001`/`FR-000002` graph requirements but used
   the pre-existing explicitly empty history fixture. This was a genuine fixture
   omission, not treated as feature RED.
2. The first diagnostic Python here-document (`PYTHONPATH=src .../.venv/bin/python
   - <<'PY'`) itself failed with `NameError: name '_memory' is not defined`
   because wildcard import correctly omits underscore-prefixed test helpers. The
   diagnostic was corrected to import the test module by name.
3. The corrected diagnostic invoked private `_build` only to expose the bounded
   errors and showed `SpecGraphError: invalid identity history projection input`
   for both failing cases. The fixtures were corrected by supplying the existing
   imported-history helper with exactly the graph requirement labels; production
   code was unchanged for this correction.
4. Re-running the whole new module produced `23 passed in 0.67s`.
5. After adding all-domain/RE parity, graph-self, raw validation, coherence,
   purity, exception and guarded-publication coverage, the module produced
   `37 passed in 0.76s`.
6. After adding explicit missing-versus-empty manifest and nested evidence-byte
   coverage, the module produced `1 failed, 37 passed in 0.79s`. The assertion
   assumed a tuple index even though the existing manifest owner sorts tree paths.
   This was recorded as a fixture assertion error and corrected to select the
   tree by exact path; production was unchanged.
7. Re-running the module produced `38 passed in 0.78s`.
8. Self-review then replaced a defensive indexed layout expression with an
   explicit four-component check and made the detachment fixture mutate the
   selected tree by exact path. The once-only covering suite below is the fresh
   verification of that final working/staged tree.

### Once-only covering verification

Command (run once after the final code/test/doc edit and before the scoped commit):

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_active_view.py tests/unit/test_spec_graph_captured.py tests/unit/test_spec_graph_structure.py tests/unit/test_identity_graph_publication_composition.py tests/unit/test_squad_source_projection_images.py -q
```

Output (recorded once):

```text
........................................................................ [ 24%]
........................................................................ [ 49%]
........................................................................ [ 74%]
........................................................................ [ 99%]
..                                                                       [100%]
290 passed in 9.05s
```

No unchanged post-commit test rerun was performed.

## Coverage completed

- Real first RED/GREEN with two immutable physical tree captures, separate
  canonical comparison, stable requirement key, current revision 2, retained
  evidence-to-revision-1 edge, full rendered equality, hidden binary and empty
  directory, and unchanged retained physical sources.
- Portable `None`, explicit canonical, valid run-local, absent exact tree,
  wrong-spec/layout/depth/root and every specified malformed/non-string/string-
  subclass selector case without a filesystem skip.
- Distinct missing/empty physical observations and manifests, native empty
  canonical logical output, stale requirement/policy/memory exclusion and
  explicit rejection when stale logical sources are requested.
- No blending; exact active policy, nested evidence and memory byte ownership;
  old content rejection; physical run-local policy/memory spelling rejection;
  canonical-prefix sibling isolation; native canonical planned-row names.
- Full native local/canonical/evidence/published-RE parity with canonical
  Artifact, Requirement and drawer identities plus preserved SourceRoot,
  Decision, topology and RE records.
- Selected graph self-file manifest sensitivity with derived graph-byte
  invariance.
- Validation before filtering for ignored canonical and other-run bytes, hash,
  mode, layout, hidden binary and stale/mismatched manifests; separately
  recomputed coherent inactive observations demonstrate coherence rather than
  authority.
- Input/manifest/memory/history immutability, post-call nested mutation
  detachment, and tripwires against Path/built-in IO, filesystem inspection,
  SQLite/store, provider, memory-adapter, planner and audit acquisition.
- Bounded ordinary error text with no cause/context and propagation of a
  process-control `KeyboardInterrupt`.
- Real sealed run-local update with canonical and active roots selected,
  projected active logical graph, callback-free `publish_sources`, final physical
  manifest equality, final graph equality and unchanged canonical bytes.

## Files changed

- `src/echelon/spec_graph_captured.py`
- `tests/unit/test_spec_graph_active_view.py` (new)
- `docs/element-identity-storage.md`
- This report only in the administrative follow-up commit.

## Self-review

Completeness: checked every brief checklist item and the explicit interface/path
contract. Existing graph keys, canonical policy/memory/planned-row names, RE
identities and default callers remain unchanged. IDs continue to cross interfaces
as strings.

Quality: the change remains inside the existing assembler and reuses the existing
path validator, manifest owner and native structure builder. Component tuples,
not string prefixes, own ancestry. No parsing or public source representation was
duplicated. The private remap is local to one call and one byte table.

Discipline: only the authorized production module, new focused test module and
focused storage documentation are in the scoped commit. There is no live
activation or adjacent refactor. The controller-owned dirty progress file was
excluded.

Testing: tests assert complete rendered graph equality for the principal,
all-domain and publication cases, use real identity/publication components where
required, and use value fixtures for portable boundary cases. Mutation review
confirms selector layout, fallback, ancestry, stale blending, byte matching,
manifest validation, self-file exclusion, detachment, IO purity and exception
normalization each have a failing behavioral test if removed or reversed. Final
covering output is pristine.

## Issues or concerns

No implementation concern. The deliberate limitation is material: this pure
adapter does not authenticate run ownership, dependency completeness, semantic
approval, graph admission, publication or completion. Runtime selection,
canonical promotion/mirroring, managed transitions and recovery ordering remain
future owner integration and were not broadened into this task.
