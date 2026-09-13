# Task 1 implementation report

Status: DONE. Independent original-BASE review remains the controller's next step.

## Scope and implementation

Original BASE: `b6f0fb8dd7cdd943a629c3132c7258b51c13b20d`.

Implementation commit: `b70dfa9c6a42f9a421d111b2808bf60d4a4da26f`
(`feat: derive captured RE graph contributions through shared transforms`).
Its tree is `96ac1f1bbfb23ad7ffbe61c503e10045788fbd4f`.

Implemented the inactive supplied-value RE contribution API and exact DTOs in
`src/echelon/spec_graph_re.py`, retaining native `ReArtifactDescriptor`,
`TopologyArtifactReceipt`, and graph class identities. The public boundary checks
exact records, tuples, bytes, strings, positive non-bool generations, scope,
canonical paths, component-wise ownership, matching source observations,
SHA-256 bytes, duplicates, preceding Artifact records, and stored-source IDs.
It raises a fixed bounded SpecGraphError outside exception handlers and does not
catch process-control BaseExceptions. It validates all supplied observations,
even extra source and Artifact observations it will not emit.

The return contains replaced/contributed nodes, edges, and topology receipt
inputs only. Existing Artifact properties are detached through a narrow shared
JSON property copier, including Mapping proxies and nested tuple/list shapes.
The existing identity `_copy_tree` remains a compatibility wrapper around that
same implementation and retains accepted scalar shapes, finite-float/UTF-8/key
rules, and ValueError behavior. Source/decision/topology records are freshly
constructed on every call; no input DTO or native record is returned by alias.

Live `_add_re_topology` delegates small pure transformations at its original
interleaving points. Selection, context exclusion, registry loading, descriptor
lookup, early returns, per-artifact annotation/title reads, source grouping,
workspace acquisition, topology loading, physical source-path validation,
receipt reads, and incremental mutations remain owned by the legacy helper.
Legacy observations are not routed through strict DTO validation. Artifact
replacement remains shallow and uses the original graph lookup key.

Files in implementation commit:

- `src/echelon/spec_graph_re.py`
- `src/echelon/spec_graph_values.py`
- `src/echelon/spec_graph.py`
- `src/echelon/spec_graph_identity.py`
- `tests/unit/test_spec_graph_re.py`
- `docs/element-identity-storage.md`

No registry, model, source capture/selection, memory planner/collector, identity
storage, runtime, controller, provider, state, CLI, prose, stopped smoke, global
installation, or main-branch changes were made. No subagents were dispatched.
The controller's plan and progress ledger remain unstaged and excluded.

## Requirements correction received during implementation

The controller identified that native source roots can be exactly `.`. The
blanket non-dot path rule in the first brief incorrectly rejected a valid
monorepo root. The amended requirement permits `.` only for workspace/semantic
source root paths and topology source root paths, using the existing pure
`normalize_source_root_path`. Artifact/receipt paths remain strict non-dot.
RE source-ID policy remains unchanged: source ID `.` is rejected. Topology
ownership uses the actual `source_storage_key`; it was not mocked to invent a
storage-key variant that the RE source policy cannot admit.

The native test proves semantic index generation 2 and topology **index**
generation 9 are preserved while the actual topology source receipt generation
is 3. No per-source receipt generation is substituted for index generation.

## Exact execution environment

Every pytest command below ran from:

`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`

Every command used the parent environment executable:

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`

The worktree has no `.venv`. Import-order subprocesses use the pytest
interpreter with `PYTHONPATH=src`; they import and assert identities only, with
no live action. No broad/full-unit suite was run. All command outputs below
were inspected in full; failure descriptions retain the decisive actual lines.

## Complete test chronology

1. Required first RED, before any production edit:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_captured_re_retains_actual_workspace_decision_after_file_change -q
```

Exit 1; `1 failed in 0.23s`. The test created the exact bytes
`b"intro\n\n ## Captured decision\n"`, physically validated its descriptor with
`validate_re_artifact_descriptor`, then ran actual `_add_re_topology`. Its full
Artifact properties, workspace Decision record (`Captured decision`), exact two
edges, and empty inputs assertions all passed. Only the subsequent import
failed: `ModuleNotFoundError: No module named 'echelon.spec_graph_re'`.
Selection/index/catalog acquisition were deterministic fixtures; title reading
and descriptor physical validation were real. Controller notified before
production changes.

2. Initial GREEN after implementing shared transformations and the new API:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_captured_re_retains_actual_workspace_decision_after_file_change -q
```

Exit 0; `1 passed in 0.21s`. The file is overwritten and removed after capture;
the new contribution retains original title/hash and complete expected records.

3. First root-source fixture attempt:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest 'tests/unit/test_spec_graph_re.py::test_native_registry_and_legacy_source_root_match_captured_values[.]' -q
```

Exit 1; `1 failed in 0.22s`. Fixture failure before native assertions:
`ModuleNotFoundError: No module named 'test_spec_graph'`. Corrected fixture imports
to `tests.unit.test_spec_graph` and `tests.unit.test_topology_registry`.

4. Second root-source fixture attempt, same exact command as step 3:

Exit 1; `1 failed in 0.25s`. Native registry correctly rejected the fixture:
`harness.re_registry.ReRegistryError: artifact catalog paths are not sorted`.
Sorted the fixture's native source manifest descriptors by path. This was a
fixture correction, not the intended RED and not a registry implementation change.

5. Decisive root-source RED, same exact command as step 3:

Exit 1; `1 failed in 0.24s`. Native descriptors, typed registry catalogs,
workspace config, actual topology receipt/index loading, and the real legacy
helper succeeded first. Exact source root properties, real workspace/source
titles, topology receipt edge, and uncataloged-path exclusion assertions passed.
The new public call then raised
`echelon.spec_graph.SpecGraphError: invalid captured RE graph contribution` for
the valid `.` source root. Controller notified before amending public path rules.

6. Root-source GREEN after using pure source-root normalization:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_native_registry_and_legacy_source_root_match_captured_values -q
```

Exit 0; `2 passed in 0.24s`. Both `.` and `sources/api` match all actual legacy
records, exact edges, and topology inputs. Native topology index/source
generation distinction is asserted before the captured call.

7. Expanded focused captured module:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py -q
```

Exit 0; `94 passed in 0.31s`. This included independent complete mixed records
and deterministic rendered bytes, multiple sources/decisions/nondecisions,
mining observations, all four lifecycle values, Mapping/list/tuple/scalar
detachment, labels, title variants, empty/missing cases, strict-value rejection,
damaged attributes/containers, bounded exception chains, and process control.
Some parametrized tests iterate several damaged values within each pytest case.

8. Legacy/API observation expansion and a self-review regression:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_legacy_replacement_keeps_lookup_key_and_shallow_properties tests/unit/test_spec_graph_re.py::test_native_capture_has_no_ambient_access_during_contribution tests/unit/test_spec_graph_re.py::test_legacy_acquisition_order_keeps_earlier_partial_mutations tests/unit/test_spec_graph_re.py::test_legacy_early_returns_do_not_acquire_source_registries tests/unit/test_spec_graph_re.py::test_import_orders_preserve_native_model_identities -q
```

Exit 1; `1 failed, 10 passed in 0.48s`. The new legacy lookup-key test exposed an
extraction defect: expected `artifact:demo:re/workspace/odd.bin`, got
`duck-typed-other-id`. The helper had used the node's damaged id rather than
the legacy lookup key. Fixed by explicitly passing the original artifact ID.
The ten other cases passed, including native tripwires, both import orders,
early returns, and later-source partial mutations/read order.

9. Scoped lookup-key fix GREEN:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_legacy_replacement_keeps_lookup_key_and_shallow_properties tests/unit/test_spec_graph_re.py::test_complete_mixed_records_order_and_detached_json_properties -q
```

Exit 0; `5 passed in 0.23s`. Lookup-key/mining semantics and legacy shallow
property aliasing are restored; captured independent ownership remains intact.

10. Additional legacy read-order self-review RED:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_legacy_decision_key_errors_precede_actual_title_read -q
```

Exit 1; `1 failed in 0.25s`. A damaged duck-typed descriptor path raises from
`removeprefix`. The extraction performed a title read before that error;
`assert reads == []` failed with one read. Split out pure `_decision_id` and
called it at the original pre-title position for workspace and source decisions.

11. Scoped decision-key ordering GREEN:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_legacy_decision_key_errors_precede_actual_title_read tests/unit/test_spec_graph_re.py::test_legacy_acquisition_order_keeps_earlier_partial_mutations tests/unit/test_spec_graph_re.py::test_complete_mixed_records_order_and_detached_json_properties -q
```

Exit 0; `7 passed in 0.23s`. Decision-key errors precede reads and retain earlier
artifact mutation; later semantic conflict and later receipt failure retain
earlier source contributions in the exact acquired/mutated sequence.

12. Offline composition fixture attempt:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_structure_memory_re_and_retained_history_preserve_offline_evidence -q
```

Exit 1; `1 failed in 0.77s`. The actual native RE planner rejected incomplete
fixture metadata with `ValueError: invalid reverse-engineering mining input`.
Added its required `canonical=True` and `scope="reverse-engineering"` metadata.
No planner/memory implementation was changed or mocked.

13. Second offline composition attempt, same exact command as step 12:

Exit 1; `1 failed in 0.75s`. All native planning/composition/projection ran;
the test incorrectly expected identity `unassessed` on an RE Artifact's
`STORED_AS`. Existing projection adds this only to identity-bearing requirement
edges here. Corrected the expectation: requirement `VERIFIED_BY`/`STORED_AS`
are unassessed, RE Artifact `STORED_AS` preserves its original properties.
No identity projection code behavior was changed.

14. Offline composition GREEN, same exact command as step 12:

Exit 0; `1 passed in 0.71s`. Actual local structure, native canonical and RE
memory plans, captured memory, captured RE, and actual retained-history
projection compose offline. Complete deterministic graph container serialization,
source/memory digests, stable req/task/decision/source keys, original historical
revision/claim edges, preceding memory annotations, unchanged RE storage edge,
and unassessed requirement evidence/storage edges are checked.

15. Once-only required covering run, after adding final exact-record-subclass,
extra-observation/workspace ownership/stored-nondecision cases and documentation:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_structure.py tests/unit/test_spec_graph_memory.py tests/unit/test_spec_graph_identity.py tests/unit/test_spec_graph_audit.py tests/unit/test_re_artifacts.py tests/unit/test_topology_registry.py -q
```

Exit 0; `681 passed in 8.50s`. Output was pristine, without warnings or skipped
cases. The eight modules were not repeated after this run. No broad/full-unit,
capacity, live-provider, stopped-smoke, or installation checks were run.

## Tested tree and post-covering accounting

Before step 15, the six implementation files were staged and `git write-tree`
returned `96ac1f1bbfb23ad7ffbe61c503e10045788fbd4f`. The working source/test/docs
content was identical to that staged scope. Root-owned unstaged differences
were the plan, progress ledger, and amended brief; none affects test execution.
`git diff --check` and `git diff --cached --check` completed with exit 0 and no
diagnostics. The implementation commit has that exact tree, confirmed by
`git rev-parse HEAD^{tree}` after commit.

After covering: **no code, test, or product documentation changes**. The only
package additions are this report and the controller-amended exact task brief.
The controller explicitly requested including that brief after covering so the
reviewed requirements travel with the package. They are requirements/report-only
changes and do not require or claim a repeated test run. The controller's plan
and progress ledger are excluded from both implementation and report commits.

## Native versus fixture acquisition boundaries

- First RED: physical native descriptor validation and real title reading;
  only linked-path selection, semantic index, and descriptor acquisition are
  fixtures. All graph transformations/assertions are real.
- `_native_fixture`: real files and hashes; real `validate_re_artifact_descriptor`,
  typed `load_published_index`/`canonical_re_artifact_descriptors`; real workspace
  configuration discovery and physical source validation; real topology index,
  receipt and provider artifact parsing/hash/path validation through existing
  registry fixture files. Fixture helper functions only create deterministic
  registry/config/provider-shaped input files. They do not replace registry or
  graph production functions. Providers themselves are not executed.
- Native legacy comparisons use actual `_linked_re_artifacts` over attached
  context; the selected uncataloged filename bait is ignored. Source selection
  is demonstrated for that offline fixture only, not authenticated globally.
- Legacy order/error tests deliberately fixture selection/index/catalog and
  workspace acquisition, retaining legacy duck-typed records. Canonical path
  validation, title reading, receipt reading, and all graph transformations run
  for real; observation wrappers record exact ordering. The later receipt error
  is a deliberate read failure. These prove incremental behavior, not native
  registry acceptance of malformed index objects.
- Pure complete-record/rejection tests use directly supplied DTO/native records
  and arbitrary receipt bytes. Receipt payloads are intentionally not parsed by
  the captured boundary. They prove coherent supplied values, not provenance.
- Native tripwire test completes all imports, file/registry acquisition and
  real legacy construction before blocking file/stat/resolve/enumeration,
  environment/process/clock/random/network/database, memory, registry, identity,
  capture and writer entry points. The contribution still matches all native
  legacy records. It invokes none of the blocked operations; database/identity
  entry points are blocked before any lock could be acquired.
- Offline composition creates a real local IdentityStore fixture and captures
  retained history before graph construction. Spec-local trees are valid
  detached fixture snapshots. Native pure canonical/RE memory planners run;
  audits are supplied deterministic observations. No real memory collection,
  fresh storage audit, provider invocation, graph write, or publication occurs.

## Self-review and remaining limits

Read the scoped production diff against BASE and the full new implementation;
checked shared copier behavior, exact record identities, source/descriptor/path
ownership, sorted ordering, contribution-only output, nested ownership, source
index generation fields, bounded errors and process-control propagation.
Two extraction defects were caught before covering and corrected with explicit
RED/GREEN tests: lookup-key preservation and decision-key/read ordering.
Two native root fixture problems and two offline composition fixture expectation/
metadata problems are explicitly retained in the chronology above.

The test module is substantial because the brief requires value, native fixture,
legacy order, ownership, purity, and composition contracts in one scoped file.
No unrelated restructuring or generic graph/validation framework was added.
The existing large `spec_graph.py` only delegates the selected transformations.

No known implementation blocker remains. Complete authenticated dependency
discovery and joint capture, memory planning/audit acquisition against exact
images, full graph composition/sealing, managed source/runtime/producer/semantic/
completion enforcement, and bounded repair still require integration. A coherent
supplied descriptor, source tuple, or receipt hash is not accepted registry
provenance, and preceding stored IDs do not prove current storage. The new entry
point has no live caller. Controller performs independent original-BASE review.

## Fix round 1: preserve legacy path-component ordering

FIX_BASE: `7cfaf0a8033430a78b25443f282c3b830193410d`.
Fresh review found one Important ordering defect: sorting descriptor strings
does not match legacy sorting of Path objects. For example, string order puts
`re/workspace/a-b.md` before `re/workspace/a/decision.md`; legacy path-component
order puts the directory `a` first. This changed contributed node order,
decision-edge order and serialization. The existing passing cases had not used
names that distinguish those orderings. The controller confirmed the original
ordering requirement; no policy/brief amendment was needed.

Fix commit: `7cf1b3139a032f6f9491f99bba8af006e142f649`
(`fix: preserve legacy component order in captured RE graph`).
Tested tree: `6ff30cedf21c51efa40a9b3387e5aa3081e35d7e`.

The production change is one line: the artifact sort key now constructs a
`PurePosixPath`, matching the legacy component ordering without filesystem
access. No legacy helper, validation, source selection, registry or model code
changed. The only other executable change is a two-case parametrized regression
in `tests/unit/test_spec_graph_re.py`.

The regression creates and physically validates native descriptors and exact
bytes, then calls actual `_add_re_topology` before the captured entry point.
It independently specifies complete ordered legacy nodes, captured contributed
nodes, edges, and rendered contribution bytes. Both workspace and source cases
use `a/decision.md` and `a-b.md`. The source case additionally includes the
nondecision `a/summary.md`, checking its `DESCRIBED_BY` edge between the two
decision relationships. Selection, semantic index and descriptor acquisition
are deterministic fixtures; physical descriptor validation, workspace source
configuration/discovery, source-path validation, absent-topology loading, title
reads and graph transformations remain real. No provider or memory acquisition
occurs. Expected ordering is explicitly declared, not derived by the production
sort function.

All commands ran from
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`:

1. Focused RED before changing production:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py::test_captured_path_component_order_matches_actual_legacy_relationships -q
```

Exit 1; `2 failed in 0.28s`. No fixture failures preceded this RED. Native
physical descriptor checks and every independent actual-legacy ordered-node/
edge assertion passed first. Captured workspace edge 0 incorrectly targeted
`decision:workspace:a-b.md` instead of `decision:workspace:a/decision.md`;
captured source edge 1 incorrectly targeted `decision:api:a-b.md` instead of
`decision:api:a/decision.md`. Controller notified before the one-line fix.

2. Focused GREEN, same exact command as step 1:

Exit 0; `2 passed in 0.22s`. Complete ordered nodes, all relationships, and
rendered bytes now match the independent expectations in both cases.

3. Once-only requested amended covering modules:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_re.py tests/unit/test_spec_graph.py -q
```

Exit 0; `144 passed in 1.13s`, pristine output. Neither the previous eight-module
covering run nor broader unit suites were repeated. No live/global/main actions
or subagents were used.

Before the two-module covering run, staging the two changed executable files
and `git write-tree` yielded `6ff30cedf21c51efa40a9b3387e5aa3081e35d7e`.
`git diff --cached --check` passed without diagnostics. The fix commit has that
same tree, confirmed after commit. Root-owned unstaged plan/progress differences
were excluded. There were no code/test amendments after covering; this report
appendix is the only later change and is committed separately without a test
repeat.

Self-review: verified the single production-line diff and the independent
workspace/source expected sequences, including the interleaved nondecision
source relationship. The pure path sort changes only deterministic ordering;
it adds no observation or physical-path normalization. No known fix blocker
remains. The original inactive integration limits above remain unchanged.
Fresh scoped controller re-review follows this DONE report.
