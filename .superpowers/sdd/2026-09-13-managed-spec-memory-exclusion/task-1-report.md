# Task 1 implementation report

## Status

DONE

Base: `e19944195e4bb5d556ea98934dfe6638537217f3`

Implementation commit: `5bb18aa8d66f3877424a034d49ad58efb05231f4`
(`fix: block managed specs from legacy memory effects`)

## Implemented

- Added the private `_require_legacy_spec_memory(project_root, *, spec_id,
  resolved_spec_id=None)` translation in `mempalace_requirements.py`. It calls
  the reviewed selected-spec guard for both actual witnesses when they differ,
  translates only `IdentityStoreError` to the exact bounded `SpecMemoryError`,
  and leaves process-control `BaseException` propagation intact.
- Added the corresponding private `RetargetMemoryError` translation in
  `mempalace_retarget.py`. Identity rejection is raised before existing handlers
  and carries `receipt is None`, with no cause or context.
- Guarded exactly the six requested mutation owners at their specified points:
  `mine_spec_requirements`, `cleanup_stale_spec_memory`,
  `mine_spec_evidence_memory`, `publish_spec_evidence_package`,
  `purge_retarget_spec_memory`, and `refresh_retarget_spec_memory`.
- Preserved native selector/snapshot/landed/source/canonical-path validation
  ordering. The changes do not query adapter provenance `run_id` labels, scan
  runtime state, initialize or modify the identity store, or alter report and
  batch transaction behavior.
- Added one new test module covering retained selected ownership for all six
  owners, exact bounded errors and unchanged filesystem/type/symlink/SQL state,
  malformed matching ownership, orphan genesis, present damaged authority,
  missing and unrelated authority, zero evidence, actual string/path/numeric
  selectors, both symlink witnesses, publication preimage preservation and
  mixed-batch partial behavior, retarget configured/no-config ordering, native
  error precedence, process-control propagation, and legacy positive controls.
- Documented the exact boundary and its limitations, including per-spec batch
  semantics, alias witnesses, provenance labels, read-only audits, no global RE
  blockade, and remaining direct graph/CLI/low-level/positive-managed work.

No store, guard, schema, controller, provider, prose, graph, RE writer,
publication protocol, adapter factory, planning API, captured audit API, generic
miner, or low-level collection owner was changed.

## TDD evidence and command log

### Required first RED

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_spec_memory_exclusion.py::test_managed_evidence_mining_rejects_before_adapter_acquisition -q
```

Preimplementation result: exit 1 in the command invocation; pytest reported
`1 failed in 0.27s`.

Relevant failure:

```text
Failed: DID NOT RAISE <class 'echelon.mempalace_requirements.SpecMemoryError'>
```

The real native evidence fixture, `IdentityStore.initialize`, source-tree
capture, source registration, and empty managed genesis for `003-demo` all
completed. The call reached the `create_spec_evidence_memory_adapter` tripwire.
Its `AssertionError` was caught by the preimplementation legacy acquisition
handler and converted to an `unavailable` report, so the required bounded
`SpecMemoryError` was absent. This is the expected RED reason and confirms the
test reached the requested acquisition boundary.

Fixture correction: none. The retained ownership fixture and canonical evidence
workspace were valid on the first attempt; the existing canonical fixture was
not rewritten and genesis remained empty.

Root was notified immediately after this RED and accepted the boundary evidence.

### Required first GREEN

Same command after the scoped production placement:

```text
.                                                                        [100%]
1 passed in 0.26s
```

Exit 0. Root was notified immediately after GREEN.

### New-module development run

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_spec_memory_exclusion.py -q
```

Result: exit 0, `20 passed in 1.71s`.

### Named scoped additions

After adding the explicit provenance-label/unrelated-authority control and the
native publication-source precedence case, only their named tests were run:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_spec_memory_exclusion.py::test_unrelated_authority_preserves_legacy_requirement_alias_mining tests/unit/test_managed_spec_memory_exclusion.py::test_publication_source_selection_error_precedes_managed_admission -q
```

Result: exit 0, `2 passed in 0.35s`.

Exact tree for that scoped run was the then-working tree containing only the
same six eventual implementation paths plus the new untracked test; the only
subsequent changes were the documented wording correction at the beginning of
`docs/element-identity-storage.md` and a test-name-only correction. No production
behavior changed after this scoped run.

### Staging and pre-cover checks

Commands/results:

- `git diff --check -- <six authorized paths>`: exit 0, no output.
- Explicit existence check for all seven required test modules: exit 0,
  `seven test module paths confirmed`.
- `git diff --cached --check`: exit 0, no output.
- Explicitly staged only the six implementation paths listed below.
- `git write-tree`: `1922f886f214c3318ddc605b8854c4cd8e4f8872`.

The root-owned dirty progress file and unrelated untracked projection plan were
not staged or tested as part of this implementation tree.

### Exact one-time seven-module covering run

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_spec_memory_exclusion.py tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_mempalace_retarget.py tests/unit/test_mempalace_captured_audit.py tests/unit/test_mempalace_captured_artifact_audit.py -q
```

Result: exit 0, `595 passed in 4.68s`, with no warnings or stray output.

The suite was run once against staged tree
`1922f886f214c3318ddc605b8854c4cd8e4f8872`. Commit
`5bb18aa8d66f3877424a034d49ad58efb05231f4` has the identical tree. There were
no post-cover implementation changes and no unchanged postcommit rerun.

No full-unit suite, capacity benchmark, install, provider/backend invocation,
actual palace service, main/smoke mutation, or live external operation was run.

### Report-only staging correction

An initial explicit `git add` of this report exited 1 because `.superpowers` is
ignored. Nothing was staged or committed by that attempt; Git reported only the
root-owned dirty progress file and unrelated untracked projection plan. The
controller-authorized report was then force-added by its exact path only. No
root ledger, plan, or other ignored content was added.

## Exact staged and tested tree

Tree: `1922f886f214c3318ddc605b8854c4cd8e4f8872`

```text
M  docs/element-identity-storage.md
M  src/echelon/mempalace_audit.py
M  src/echelon/mempalace_requirements.py
M  src/echelon/mempalace_retarget.py
M  src/echelon/mempalace_spec_evidence.py
A  tests/unit/test_managed_spec_memory_exclusion.py
```

Implementation diff versus the supplied base contains exactly those paths.

Excluded dirty/untracked administrative or unrelated paths observed before and
after the commit:

```text
 M .superpowers/sdd/2026-09-13-managed-spec-memory-exclusion/progress.md
?? docs/superpowers/plans/2026-09-13-managed-projection-write-exclusion.md
```

## Self-review

- Re-read each of the six placements against the brief. Native acquisition and
  validation remain before admission; every adapter, cleanup, delete, mkdir,
  copy/hash/manifest write, report recovery, and not-applicable receipt remains
  after admission.
- Confirmed only actual selected/resolved directory identities are checked.
  Adapter labels `manual`, `cleanup`, `retarget-purge`, and
  `retarget-finalize*` are not submitted as runtime ownership witnesses.
- Confirmed the shared translation catches only the consumed
  `IdentityStoreError`; `KeyboardInterrupt`, `GeneratorExit`, and `SystemExit`
  remain native. Tests assert exact message/type/cause/context and retarget
  `receipt is None`.
- Confirmed audits and generic/direct low-level APIs were not guarded, and mixed
  publication remains native partial aggregation rather than a transaction.
- Mutation review: removing any owner call reaches a named effect tripwire or
  changes preserved state; checking only one alias witness fails one of the two
  symlink cases; moving admission before native validation fails precedence
  cases; broadening the catch fails process-control cases; returning a receipt
  or downgrade fails exact error assertions.
- Test doubles are confined to backend acquisition/storage seams; the guard,
  owner, selector, snapshot, landed policy, verify-source discovery, identity
  store, source capture/registration, and managed genesis are real.
- `git diff --cached --check` and the exact covering run were clean before the
  implementation commit.

Self-review found and corrected one documentation inconsistency: the opening
storage overview previously said identity storage was not wired into evidence at
all. It now names the narrow negative exception without claiming positive
managed integration. A misleading positive-control test name was also narrowed;
neither correction changed production behavior.

## Limitations and concerns

No correctness concern within the requested six-owner boundary was found.

The delivered behavior is negative selected-spec admission only. It does not
observe metadata-only declarations after all durable ownership witnesses are
absent, pin enrollment, undo upstream independent effects, block direct graph or
CLI effects, cover low-level/generic/RE writers, or provide positive managed
mining/publication, managed producer/runtime selection, semantic authority,
complete joint capture, coordinated completion/recovery, or bounded repair.
Read-only audits remain diagnostic rather than admission. No live palace/backend
success claim is made.
