# Task 1 implementer report

Status: DONE. Base: `e637706429a3b0a3b3180736c2a44cc0ce54920a`.
Workspace: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Branch: `fix/delivery-controller-contract`.

## Implementation

- Added the exact seven-field frozen/slotted `ManagedIdentityRequest`, strict
  canonical ASCII version-1 codec, canonical UUID/path/hash validation, exact type
  and mutated/deleted-field revalidation. Existing strict JSON, request canonical
  serializer, lifecycle text and source-path validators are reused. Ordinary
  failures are bounded with suppressed untrusted exception context; BaseException
  is preserved. The codec does no I/O.
- Added immutable, explicit, inactive registration/read methods. Registration is
  one ordinary globally owned operation plus one registry row in the store-owned
  transaction. Namespace is checked, not substituted. Exact original retries are
  resolved before fresh-enrollment checks, including after source advancement,
  seven-family materialization, revisions, pending publication and reopen.
- First enrollment fully audits existing authority in the same transaction before
  inserting any new operation. It rejects retained non-source operations and all
  identity child history for that spec, including empty imports, abandoned
  reservations, terminal entities, publications and removed legacy entity rows.
  Other specs' valid history and existing source registrations remain permitted.
- The retained original source context operation and independently retained
  original manifest SHA bind genesis. Its selected spec tree must exist and have
  exactly its original root directory and no files; other dependency trees/files
  and valid original root modes remain supported. Existing connection-owned
  source helpers validate immutable registration separately from current source
  state. The source helper module was not changed.
- Current reads validate indexed registry, operation and source associations,
  detect missing rows with orphan registration operations, and do not scan
  identity child history. Full audit checks every registry row and orphan
  operation. Original source rewriting plus recomputed local source hashes still
  contradicts the independent genesis hash.
- Froze schema 5 and added only the schema-6 registry table and partial operation
  index. Marker/user_version remain 1. Explicit old-schema audit routing remains
  lifecycle 2+, bindings 3+, journal 4+, source 5+, managed 6 only. Snapshot,
  administrative audit, backup-before-claim, upgrade and restore route managed
  audit explicitly. Materialized identity-history wire/digest is unchanged.
- Updated current-schema expectations and storage documentation. No production
  source/journal/lifecycle/common-guard/provider/controller/state/CLI/graph/memory
  files were modified. No runtime was enrolled or activated.

## TDD and verification evidence

All commands below ran in the workspace above. The exact pytest executable was
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` (shown as `$PYTEST`
below only to make repeated commands readable; no replacement environment variable
was required). Tests use this checkout's configured `src` import path.

### First actual regression before production

Command: `$PYTEST -q tests/unit/test_element_identity_managed.py`.

The initial fixture setup attempt reported `1 error in 0.16s` because the
project's secure-POSIX fixture was module-local to source tests. Added the same
capability-scoped fixture to this test module; it is used only for real filesystem
capture cases, not the pure codec or ordinary SQLite tests.

The actual RED then completed genuine secure POSIX capture, produced the real
manifest, initialized the authority, registered the source context and asserted
sequence `"0"`. Only then it failed at:

```text
register = store.register_managed_identity
AttributeError: 'IdentityStore' object has no attribute 'register_managed_identity'
1 failed in 0.26s
```

The missing production module was deliberately imported after the missing-method
line so it could not prevent the real setup. No source manifest was fabricated to
reach this failure. Root was notified before any production edits.

Initial GREEN with the same command: `1 passed in 0.25s`, pristine output.

### Focused development checks

- Managed module expanded: `1 failed, 80 passed in 2.13s`; the new administrative
  count assertion found omitted `managed_identity_specs` count routing. Added the
  count and reran: `81 passed in 2.09s`, pristine.
- Real source/history/process/corruption expansion initially gave `1 failed, 113
  passed in 4.80s`: the test's revision incorrectly changed its immutable subject.
  Corrected test setup to retain `AC title`; no lifecycle production edit.
- Frozen-5 fixture expansion gave `4 failed, 114 passed in 5.36s` because the test
  helper import omitted its `tests.unit` package. Corrected fixture import; command
  `$PYTEST -q tests/unit/test_element_identity_managed.py -k frozen` returned
  `46 passed, 72 deselected in 2.00s`, pristine. This selection also includes frozen
  malformed-field tests.
- `$PYTEST -q tests/unit/test_element_identity_admin.py tests/unit/test_element_identity_source_store.py`
  returned `5 failed, 123 passed in 12.84s`: only old current-schema `5` expectations
  and the new zero registry count differed. Updated those closed current-schema
  expectations; old frozen fixtures were not reinterpreted.
- `$PYTEST -q tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_admin.py tests/unit/test_element_identity_source_store.py`
  returned `249 passed in 18.84s`, pristine.
- Added successful schema-6 backup/restore/current-upgrade preservation coverage:
  `$PYTEST -q tests/unit/test_element_identity_managed.py::test_current_backup_restore_and_upgrade_preserve_genesis`
  returned `1 passed in 0.33s`, pristine.

### Single final ten-module covering run — original code point

The staged Git tree was `e0f5e8dc1f5bbf510a96586476a6b842c131598f` when the
following command ran. This is the **pre-amendment** code point, not a claim that
the later fresh-only amendment received a repeated ten-module run.

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_managed.py tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_publication.py tests/unit/test_element_identity_store.py tests/unit/test_element_identity_lifecycle.py tests/unit/test_element_identity_bindings.py tests/unit/test_element_identity_snapshot.py tests/unit/test_element_identity_admin.py tests/unit/test_element_identity_request_codec.py tests/integration/test_element_identity_store.py --deselect=tests/integration/test_element_identity_store.py::test_million_identity_capacity_uses_indexed_lookup_and_counter
759 passed, 1 deselected in 63.29s (0:01:03)
```

Exit code 0; output pristine, no skips/warnings/errors. The sole deselected test
was inspected at `tests/integration/test_element_identity_store.py:165`; it creates
one million imported identities and measures allocation/lookup behavior. It was
not rerun. This task does **not** claim a schema-6 million-capacity measurement.
No broad full-unit, live/provider, install or postcommit tests were run.

### Post-covering self-review amendment — actual RED and affected GREEN

Self-review found that `import_identities(definitions=())` retains an ordinary
import operation without child rows. A nonnumeric legacy import whose rows were
removed also retains an import operation which the preexisting full audit accepts.
Fresh enrollment must still reject these specs. Root explicitly agreed that the
fresh-only requirement covers this edge.

Before the production amendment:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_managed.py::test_first_enrollment_rejects_retained_import_operation_without_entity_rows
FAILED ...[empty-import] — DID NOT RAISE IdentityStoreError
FAILED ...[removed-legacy-rows] — DID NOT RAISE IdentityStoreError
2 failed in 0.37s
```

Added a first-enrollment-only retained non-source operation check immediately
after full audit and before operation insertion, preserving exact retry ordering
and existing import/common-guard behavior. Updated documentation and the two
regression cases. Only the affected managed module was rerun:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_managed.py
124 passed in 6.05s
```

Exit code 0; output pristine. Final implementation/test/document staged tree,
before adding this report: `b80d75f62e6e617f90bfb707486a7c6d4e99d816`.
`git diff --check` and `git diff --cached --check` both exited 0 with no output.
The complete amendment diff was self-reviewed; no subsequent production changes.

## Coverage and self-review

The 124 managed tests cover independent closed wire/receipt expectations; exact
types and malformed Unicode/depth/duplicate/type/UUID/path/hash cases; pure codec
I/O prohibition; bounded ordinary failures and BaseException; detached reads;
history-wire stability; first-enrollment prerequisites and exact SQL-dump
preservation; arbitrary other-spec history and dependency metadata; global
spec/run/operation ownership and permanent publication child claims; real source
file advancement plus seven-family materialization/revision/pending exact retry;
operation insert, registry insert and before-COMMIT SQLite denial rollback;
separately labeled after-actual-COMMIT uncertainty; two real spawned processes
with one genesis winner; raw SQL corruption with recomputed request/operation/
original-source hashes; query/audit/snapshot/backup/restore rejection without
repair or successful destination creation; positive backup/restore/upgrade;
EXPLAIN indexed lookup checks and authorizer-prohibited identity child-history
access (including after source advancement); independent frozen-5 DDL with
registered/advanced sources and prepared/applied/released version-2 journals;
old5 unsupported-operation rejection without managed-table access.

Confirmed original namespace and genesis versus current-head semantics, exact
retry ordering, no half-insert audit, source association checks, immutable rows,
source/publication receipt stability and frozen audit routing. Request and store
modules remain focused (73 and 134 lines). Existing `IdentityStore` is large;
changes there are confined to request entry points and additive audit/schema
routing/counts. No subagents or reviewers were spawned; independent review is
root-owned.

## Changed files

- `src/harness/element_identity_managed.py` (new)
- `src/harness/element_identity_managed_store.py` (new)
- `src/harness/element_identity_schema.py`
- `src/harness/element_identity_store.py`
- `src/harness/element_identity_snapshot.py`
- `tests/unit/test_element_identity_managed.py` (new)
- `tests/unit/test_element_identity_admin.py`
- `tests/unit/test_element_identity_source_store.py`
- `tests/unit/test_element_identity_bindings.py`
- `docs/element-identity-storage.md`
- `.superpowers/sdd/2026-09-12-managed-identity-registration/task-1-report.md` (this report)

## Concerns, limits and handoff

No unresolved correctness concern from self-review. This is local consistency
detection, not protection from coherently substituting an entire older database.
The genesis record is immutable first-run metadata, not an active-run pointer.
It does not authenticate complete dependency selection or semantic proposals,
enforce metadata presence/removal/downgrade in runtime consumers, enroll existing
workspaces, bind later manual/retarget/replay runs, define provider proposal or
graph staging formats, or activate controller/provider enforcement. Those remain
later integration work; historical enrollment requires explicit reconciliation.

Implementation/test/document files are committed as `0daa82c`
(`feat(identity): retain inactive managed genesis registration`). This report is
committed separately: its ignored `.superpowers` location required explicit
force-add after the ordinary add was rejected. No tests were rerun postcommit.
Root-owned `progress.md` remains modified and outside this commit; root-owned
following-integration observations are also untouched. The implementation can be
clean while the whole shared worktree is not. No main, global installation,
provider runtime or stopped-game workspace was modified.
