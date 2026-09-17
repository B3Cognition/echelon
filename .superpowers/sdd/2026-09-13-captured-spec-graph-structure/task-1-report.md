# Task 1 implementer report

Status: DONE. Implementation commit: `f429a965ad25a693d5e480798882f2c26b1468ec`
(`refactor(graph): share captured spec-local structure`).

## Scope and implementation

Base: `b3ea04fe9efcc8377f9db231a6bf0ef79a1c5db5`.
All commands below ran in
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
The parent checkout's absolute pytest executable was used throughout; no
worktree virtual environment, installs, live providers, smoke, capacity, full-unit
suite, activation, or postcommit repeated suite was used.

Scoped implementation files:

- `src/echelon/spec_graph_structure.py`: frozen/slotted local value carrier,
  validated supplied-tree boundary, logical path mapping, shared pure local
  transformation helpers and registry selection.
- `src/echelon/spec_graph.py`: existing reader helper signatures delegate to the
  shared transformations. Graph models, wire, external observations and their call
  order remain owned by this module.
- `tests/unit/test_spec_graph_structure.py`: 107 cases, including physical capture,
  complete independent expected records, real legacy comparison, detached ownership,
  parser/error contracts, import identity, ambient tripwires and real publication.
- `docs/element-identity-storage.md`: supplied-tree contract and explicit limitations.

The task brief and this report are retained separately as scoped task records.
Root-owned `progress.md` and `docs/superpowers/plans/2026-09-13-captured-spec-graph-structure.md`
were dirty and excluded from every implementer commit.

The local builder uses the existing manifest factory to validate exact snapshot
types, nested bytes/hashes/modes/membership/layout, without treating its digest as
acceptance. It uses component-wise physical-root stripping and canonical
`specs/{spec_id}` paths. It preserves UTF-8 replacement for requirement inventory,
strict task/consumed JSON/ledger decoding, absent-versus-empty behavior, original
requirement precedence, task order/status, INFRA/UNMAPPED interpretation, input-unit
aggregation, deferral status, amendment controls and original verified provenance.
The public boundary raises a bounded error after leaving exception handlers;
SystemExit and KeyboardInterrupt propagate. Results own their records and mutable
nested property containers. Missing/empty valid trees yield only a Spec node.

## Actual test chronology

### 1. Required actual RED, before all production edits

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_captured_structure_retains_real_spec_after_file_change -q
```

The test created a physical `specs/demo/spec.md`, and the real existing reader
successfully returned the complete asserted canonical record:
`("FR-1000000", "spec", "spec.md", 3, "- FR-1000000: Keep question identity.")`.
The real `inspect_project_tree` context then captured the tree and successfully
asserted its original bytes. After changing the physical file, execution reached
the absent module import. Relevant actual output:

```text
>       module = importlib.import_module("echelon.spec_graph_structure")
E   ModuleNotFoundError: No module named 'echelon.spec_graph_structure'
FAILED tests/unit/test_spec_graph_structure.py::test_captured_structure_retains_real_spec_after_file_change
1 failed in 0.18s
```

Exit 1, expected missing-module failure; neither parsing nor capture failed or
skipped. Root was notified of this exact RED before production edits.

### 2. Named GREEN after shared transformation extraction

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_captured_structure_retains_real_spec_after_file_change -q
.                                                                        [100%]
1 passed in 0.20s
```

Exit 0. The captured requirement remained FR-1000000 after the physical source
changed. Root was notified.

### 3–5. Independent rich fixture expectation corrections

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_rich_structure_has_complete_independent_records_and_rendered_bytes tests/unit/test_spec_graph_structure.py::test_physical_roots_do_not_change_any_records_or_bytes -q
1 failed, 1 passed in 0.24s
```

The complete input assertion exposed an incorrect hand-authored expectation:
`deferred-scope.json` is not in the existing artifact registry. The parser still
emits its Deferral records, but the policy does not emit an Artifact/Input for it.
Inspection confirmed this; only that expected artifact row was removed.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_rich_structure_has_complete_independent_records_and_rendered_bytes -q
1 failed in 0.22s
```

Inputs and nodes then matched completely. The remaining edge order assertion
showed the existing canonical ordering places numeric `FR-1000000` before legacy
`FR-016b`. The independent expected requirement order was corrected accordingly;
production was unchanged by either fixture correction.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_rich_structure_has_complete_independent_records_and_rendered_bytes -q
.                                                                        [100%]
1 passed in 0.21s
```

### 6. First expanded focused checkpoint

Added pure missing/empty, lifecycle, statuses, malformed files, UTF-8, directory
presence, unsafe components, subclasses/damaged snapshots, property ownership and
process-control exception cases.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py -q
........................................................................ [ 75%]
........................                                                 [100%]
96 passed in 0.26s
```

Exit 0; root received the result and fixture correction explanation.

### 7–8. Real legacy and publication composition checkpoint

Added real pre-memory full-local-record comparison, original memory helper
continuation, final task artifact override assertion, sealed source projection and
publication/final-capture comparison, strict ambient tripwires and fresh-process
imports in both orders. Import subprocesses used the active parent Python and
explicit `PYTHONPATH=src`.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py -q
1 failed, 100 passed in 0.54s
```

The complete pre-memory records and final task overrides already matched.
Only the additional hand-authored external receipt-set assertion failed:
the real fulfillment fixture also produces the existing `spec-evidence` receipt.
Inspection of the real evidence-domain owner confirmed this behavior. The expected
receipt set was corrected to `canonical-spec` plus `spec-evidence`, and the
evidence adapter/audit were explicitly given deterministic fixtures at the same
external boundary as the canonical adapter. Core graph transformations and source
parsers remain real; the observing wrapper retains records and calls the original
canonical memory helper.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_legacy_graph_local_boundary_matches_complete_fragment -q
.                                                                        [100%]
1 passed in 0.24s
```

### 9. Final expanded focused checkpoint before covering

Self-review restored the legacy order of extracting canonical rows before source
path resolution, avoiding a new resolution when no spec-origin rows exist. The
shared module reused existing `_input_role` and `_scope_node_id`, and consumed the
public registry accessor rather than duplicating policy. Added real legacy helper
exception and external artifact role-override cases. Documentation was then added.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py -q
........................................................................ [ 67%]
...................................                                      [100%]
107 passed in 0.52s
```

Exit 0; root received the checkpoint before the covering command.

### 10. Once-only required covering command and full output

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_audit.py tests/unit/test_graph_traversal.py tests/unit/test_identity_graph_traversal.py tests/unit/test_spec_graph_identity.py tests/unit/test_graph_source_parsers.py tests/unit/test_canonical_requirements.py -q
........................................................................ [ 23%]
........................................................................ [ 46%]
........................................................................ [ 69%]
........................................................................ [ 92%]
......................                                                   [100%]
310 passed in 8.30s
```

Exit 0. Output pristine, no warnings/skips/errors. Existing full-graph
memory/RE/topology tests were unchanged and included in this covering set.
`git diff --check` also exited 0 with no output.

The exact scoped covering tree, reconstructed in an isolated temporary Git index
from these recorded blobs, is `615f2ed57d20c18cba168b38d103406de8757791`.
It is BASE plus precisely the four implementation files below, excluding root's
dirty plan/ledger. Reconstructing its tree did not modify the working files or the
real Git index and did not run another test suite.

| Covered file | Git blob |
| --- | --- |
| `src/echelon/spec_graph.py` | `0e3666c823a8594c6a06ac2b52951b3e2e593618` |
| `src/echelon/spec_graph_structure.py` | `917fce8656448b04d985a0d64712b2309ff79817` |
| `tests/unit/test_spec_graph_structure.py` | `cba8f017ecd814dcd991476daf9c404d688c28a8` |
| `docs/element-identity-storage.md` | `81efb1935ab019914d4134180456eff090e934f2` |

### 11. Exact post-covering amendment and scoped verification

Self-review found that forced input damage in the ownership test targeted the
first sorted file, `.hidden.bin`, which is intentionally ignored. Root was
notified and agreed to a test-only amendment and its named verification. The
assertion now selects graph-bearing `specs/demo/spec.md`, damages its bytes/hash,
changes its physical path, then clears the input tree's files. The separately
retained expected fragment must still match. No production or doc file changed.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_structure.py::test_outputs_own_records_and_all_nested_mutable_properties -q
.                                                                        [100%]
1 passed in 0.22s
```

Exit 0. `git diff --check` again exited 0 with no output. The amended test blob is
`665bcb050041e7db7dabecaf88f624c9f025351e`; the other three blobs above are unchanged.
The final scoped implementation tree is
`6b9e37438169abff9f96b9d27a9c2a7e9e1693ae`, committed as `f429a965`.
There were no additional implementation amendments or test runs after that commit.
The subsequent brief/report commit changes only task records; it does not change
the tested implementation tree's source/test/doc blobs.

## Self-review and limits

- Reviewed the original-BASE scoped diff and both modules. Existing graph model
  definitions and identity stay in `echelon.spec_graph`; fresh imports in both
  orders pass. Shared construction loops exist once, and physical readers remain
  in the legacy wrappers. The large legacy module was not relocated wholesale.
- Real pre-memory comparison covers every local input/node/edge, with original
  external continuation and separately asserted final task-role overrides. No
  external roles were changed to force equality and no local records were omitted.
- Independent rich expectations cover all graph fields and exact hashes/roles/
  required flags, source line/text/category, mixed ID widths and legacy IDs,
  source precedence, wide task source-row order, unresolved/INFRA behavior,
  multiple input units, both deferral statuses, numeric/empty/nonnumeric amendment
  directories, all five controls, and original verified provenance. Additional
  tables cover lifecycle and status variations.
- Tripwires run after imports/fixture creation and reject file reads/writes,
  resolution/stat/enumeration, processes, environment, time/random/network/DB and
  memory/topology/full-graph authority calls. The captured builder makes none.
- The sealed publication test changes a requirement and task/reference, retains
  hidden binary content, adds an amendment control, publishes only sources and
  compares projected/final actual fragment bytes. There is no graph writer.
- The carrier is distinct from capture and full graph types and is not itself a
  validator. Existing graph records are detached; input damage and other-result
  nested property mutation do not alter the retained expected result.
- Approved limits remain: this is deterministic spec-local structure only.
  Complete captured memory/RE/topology and evidence-domain inputs, source-selection
  and logical-mapping ownership, identity overlay, sealing, managed producers,
  runtime, semantic acceptance, completion and bounded repair remain required
  before activation. No new runtime protocol is selected or external observation
  fabricated. No additional correctness concerns identified.
