# Task 1 report: captured identity graph assembly

Status: DONE.

Base: `60f5f8bb483cf37521fb5267f8ae3edf56e81808`.
Workdir for every command below:
`/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Pytest executable for every test run:
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`.
No worktree `.venv`, full-unit/capacity/live/provider/stopped-smoke/global-install
or main-branch action was used. No subagents or reviewers were dispatched.

## Implementation

- Added `src/echelon/spec_graph_captured.py` (171 lines): the values-only frozen,
  slotted `CapturedGraphMemory` grouping and `build_captured_identity_graph`.
- Added `tests/unit/test_spec_graph_captured.py` (846 lines): real acquisition
  and legacy comparisons, independent complete expected wire records, explicit
  domain/source consistency, malformed values, ownership and purity contracts.
- Documented the inactive boundary and remaining integration in
  `docs/element-identity-storage.md`.
- Added this report. The task brief was already tracked in BASE. Root-owned
  plan/progress files were not staged or committed by the implementer.

The assembler validates scope and exact outer types, recomputes the existing
manifest over all images, requires the selected canonical spec root, and builds
one present-byte table. Explicit policy paths, native memory sources, selected
RE descriptors and topology receipt contents must agree with that table.
Semantic receipt paths are presence dependencies only. It composes local,
policy, canonical-spec, spec-evidence, published-re, RE annotation and retained
identity projection in the specified order. Existing owners retain native
parsing, audit, drawer, scope, endpoint, RE/source and history semantics.

The full assembler rejects an explicitly selected RE descriptor that lacks its
preceding Artifact node; the lower-level RE builder was not changed and its
missing-node behavior has a direct compatibility test. Policy overlap retains
the existing local role. Native memory overrides and duplicate-edge validation
remain native. Matching drawer keys across domains retain replacement behavior
when edges differ; duplicate identical edges still fail through the graph model.

The root graph file participates in image-manifest validation but cannot be a
policy/memory input and does not affect derived graph bytes. The explicit
generator version is retained without package-version discovery. Existing
identity projection detaches records and nested properties, and the existing
renderer validates the final graph before return. Ordinary exceptions are
caught and a bounded `SpecGraphError` is raised after the handler, leaving no
source-bearing cause/context. Process-control `BaseException`s propagate.

No existing production file changed. No production caller was added.

## TDD and complete execution chronology

All production code was absent during run 1. The parent was notified of the
successful missing-module RED before production code was added. The first
implementation then passed run 2. Subsequent tests strengthened that same
implementation; there were no production amendments after its first GREEN.

1. Required first RED:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py::test_captured_assembly_retains_projected_source_and_old_evidence -q
   ModuleNotFoundError: No module named 'echelon.spec_graph_captured'
   1 failed in 0.69s
   ```

   The failure occurred at the deferred import, after the real IdentityStore
   reserve/create/evidence/revision/history, sealed publication inspection,
   source-image projection, native canonical planner, local/memory graph
   composition and real identity projection all completed. Assertions confirmed
   `FR-000001`, stable requirement key, current revision `2`, original revision
   content, the old evidence `ASSESSES_REVISION` edge to revision `1`, and
   `target_revision_matches_current is False`. No fixture failure preceded this
   RED. The audit was a supplied deterministic observation, not a collection
   audit.

2. First GREEN, same exact command:

   ```text
   1 passed in 0.67s
   ```

   After acquisition the physical spec and actual identity store were advanced.
   The graph still rendered exactly like the retained projected bytes/history.

3. Independent complete canonical-only and three-domain expected wire cases:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py -q -k 'complete_'
   3 passed, 1 deselected in 0.24s
   ```

4. Newly added boundary/source-table/domain/policy/error cases:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py -q -k 'boundary or validation or policy or nested or selected_missing or graph_bytes or process_control'
   101 passed, 4 deselected in 0.33s
   ```

5. First native comparison/unavailable-observation/guarded-publication batch:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py -q -k 'partial_unavailable or duplicate_cross or full_render or guarded_source'
   3 failed, 3 passed, 105 deselected in 0.78s
   ```

   Failures were test-fixture errors, not bypassed assertions:

   - The exception-origin unavailable audit was incorrectly given a non-null
     wing, nonzero counters and two errors. The existing memory owner correctly
     rejected it. Inspection of `_audit_report` established the actual exception
     contract: null wing, zero counters, unavailable status and one error.
   - Both full legacy comparisons (`.` and `sources/api`) omitted an explicitly
     linked but uncataloged `re/sources/api/contracts.md` from the supplied
     policy selection. The legacy policy owner includes that linked artifact,
     independently of typed descriptor admission. Every other graph record was
     equal. The fixture now supplies that literal policy path without treating
     it as a typed descriptor or a mined RE source.

   The systematic-debugging skill was read before correcting the fixtures.

6. Diagnostic standalone fixture run (not a pytest verification run):

   ```python
   # Invoked with:
   # PYTHONPATH=src /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python - <<'PY'
   import tempfile
   from pathlib import Path
   import pytest
   from tests.unit.test_spec_graph_captured import test_full_render_matches_real_legacy_native_acquisition
   with tempfile.TemporaryDirectory() as directory, pytest.MonkeyPatch.context() as patch:
       try:
           test_full_render_matches_real_legacy_native_acquisition(Path(directory), patch, '.')
       except AssertionError as error:
           tb = error.__traceback__
           while tb.tb_next:
               tb = tb.tb_next
           values = tb.tb_frame.f_locals
           actual = values['result'].to_dict()
           expected = values['expected'].to_dict()
           for key in actual:
               if actual[key] != expected[key]:
                   if isinstance(actual[key], list):
                       print(key, 'actual only', [v for v in actual[key] if v not in expected[key]])
                       print(key, 'expected only', [v for v in expected[key] if v not in actual[key]])
                   else:
                       print(key, actual[key], expected[key])
   # PY
   ```

   This first diagnostic exited 1 before the comparison: the temporary path
   used `/var`, and the real identity authority correctly rejected its symlinked
   ancestor (`IdentityStoreError: symlinked identity state is forbidden: /var`).
   Pytest's actual fixture already uses the resolved `/private/var` path.

7. The same diagnostic command was run with exactly one change:
   `Path(directory).resolve()` replaced `Path(directory)`. It exited 0 and
   reported only the omitted policy Artifact/input and resulting source-set
   digest difference:

   ```text
   source_set_digest sha256:bc8294f5fa0d272eba99648642520ab93bfcda9f227498e9a18c0c29a402c67c sha256:27a5f5fe37c4033f3ee0404cd1d53b599db9a4944443acac0477d210b0e35b6f
   inputs actual only []
   inputs expected only: re/sources/api/contracts.md, role reverse_engineering,
     required False, hash sha256:a9726c4d5ac5d63c861b074ad18f8192352efd0b721f33009d3f49b910b17784
   nodes actual only []
   nodes expected only: Artifact artifact:demo:re/sources/api/contracts.md,
     role reverse-engineering, same hash, mining_status not-mined-by-policy
   ```

   The short diagnostic summary above retains every differing field; the two
   list lines in raw output were Python dictionary representations.

8. Named scoped verification after the two fixture corrections:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py -q -k 'partial_unavailable or full_render'
   4 passed, 107 deselected in 0.76s
   ```

9. Newly added native-acquisition ownership/purity/sanitization/import tests:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py -q -k 'detached or pure_assembly or source_bearing or import_orders'
   7 passed, 111 deselected in 0.89s
   ```

   Import tests launch fresh Python processes with `PYTHONPATH=src` and the
   current parent interpreter; both import orders retain native model identities.

10. Final preparation added explicit prepared-publication/lock entry-point
    guards, unused-RE-observation validation, an independently valid but
    byte-conflicting memory observation, lower-level missing-node compatibility,
    and the documentation. The actual physical native comparison cases now
    explicitly request the existing secure-POSIX fixture; pure cases have no
    POSIX skip. These changes are included in the covering run below.

11. Once-only covering verification:

    ```text
    /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_spec_graph_captured.py tests/unit/test_spec_graph.py tests/unit/test_spec_graph_structure.py tests/unit/test_spec_graph_memory.py tests/unit/test_spec_graph_re.py tests/unit/test_spec_graph_identity.py tests/unit/test_squad_source_projection_images.py tests/unit/test_squad_source_manifest.py -q
    712 passed in 9.15s
    ```

    Exit 0, no warnings, errors or skips. No earlier unchanged passing batch was
    repeated except as part of this required covering run. No postcommit repeat.

## Tested tree and amendment accounting

Before run 11 the module, tests and documentation were staged explicitly.
`git diff --cached --check` passed with no output. `git write-tree` returned:

```text
5ea945dced266fce4c68cb87406c54bca5d4013a
```

That staged tree, based on BASE above, contains exactly the three executable/
documentation changes tested by run 11. Root's concurrent `progress.md` edits
were unstaged and were excluded. No production, test or documentation changes
were made after run 11. This report is the sole post-verification addition.
The final commit therefore differs from the tested tree only by this report;
no further test execution is warranted for this report-only addition.

An earlier `git diff --check` also had no output. Its combined inspection command
ended with `git diff --no-index /dev/null src/echelon/spec_graph_captured.py`,
whose exit 1 means a new-file diff existed, not a failed check.

## Evidence boundaries and self-review

- First RED/GREEN uses actual identity authority lifecycle operations, retained
  history, publication sealing/inspection and projected final images; native
  planning and all graph transformations are real. It does not publish those
  operations. The supplied audit is deterministic and does not contact storage.
- Full legacy comparisons use actual files, typed semantic catalogs,
  workspace configuration, linked artifact policy, topology indexes/receipts,
  real source capture and a real imported IdentityStore snapshot. Native memory
  planners execute through deterministic external adapter fixtures. Audit
  acquisition is supplied, not authenticated or refreshed. Every rendered
  record, field and digest is compared after the same identity projection;
  in-memory receipt tuples are compared too. Later physical spec/descriptor
  drift does not change the retained graph. Imported history stays imported,
  with no revisions manufactured and legacy verification/memory assessments
  remaining unassessed.
- Independent pure expected fixtures enumerate complete canonical-only and
  three-domain records, source/workspace decisions and topology. Expected
  source/audit/wire digests use explicit test payloads and ordinary SHA-256/JSON,
  not the production builders or receipt/digest helpers as an oracle. Native
  seven-field row types are used as supplied observations in these fixtures;
  their actual acquisition/planning is tested separately above.
- The guarded publication fixture performs only a non-graph source write via
  actual `publish_sources`. Final source capture equals the projected manifest,
  and derivation from those actual final bytes renders identically. It explicitly
  verifies that no graph file was written. This is not graph sealing, joint
  identity/source publication, or an atomic source-plus-graph transaction.
- The purity fixture acquires real native rows and real identity history first,
  then blocks file/stat/resolve/enumeration, environment, process, clock, random,
  socket, SQLite, identity methods, memory acquisition/planning, registry reads,
  capture, graph writers and publication/lock entry points during assembly.
  It compares the full graph and actual fixture file bytes before/after.
- Ownership tests mutate supplied image/descriptors/source/audit/row/history
  records, later-output records and nested properties, and retained lower-level
  contribution properties. Earlier rendered bytes remain unchanged; the
  assembler leaves retained lower-level contributions unchanged during calls.
- Malformed exact/subclass/slot/recursive values, stale manifests, hidden/binary
  hash contradictions, missing versus empty files, scope/selection conflicts,
  duplicate policy/domain/observation/row keys, optional-domain emptiness and
  graph self-input all have bounded-error tests. Explicitly selected descriptors
  are never silently dropped. Unused RE observations still go through the real
  public RE validator.
- Self-review found no required production amendment. The implementation reuses
  existing transformations and does not duplicate parsing, snapshot codecs,
  authority, native planning, graph schema or audit normalization. The broad
  test module is intentionally one file to match the specified scope; no
  test-only functionality was added to production owners.

## Remaining limitations

No live caller is activated. Complete dependency selection, authentic memory/
registry acquisition, authentic selection of the retained identity ledger,
semantic review/authorization, graph operation sealing, durable joint identity/
source publication, run enrollment/transitions, producer allocation, runtime/
manual/CLI enforcement, and bounded repair remain required. Coherent supplied
values produce a derived view, not publication authority. Source root directories
and receipt contents are not authenticated by the presence table. The root
graph-file input exclusion does not exempt later publication from sealing or
source guarding. The controller owns the independent original-BASE review after
this task reports DONE.
