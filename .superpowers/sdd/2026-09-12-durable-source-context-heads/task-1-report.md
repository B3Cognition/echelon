# Task 1 implementation report: durable accepted source-context heads

Base: `cf5252c5582de05025bb629f8c3d88b639eb73a3`.
Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Implementation checkpoint: `f8911aef` (`feat(identity): retain source contexts in publication journal`).
The later self-review amendment is described separately below; the eleven-module
result applies to the checkpoint, not automatically to the amended code.

## Implemented

- Added schema 5 with only source contexts, source publication plans, the unique
  source sequence index, partial numeric accepted-head index, and partial
  spec/operation registration index. Preserved exact schema 4 as `SCHEMA_V4`;
  marker format and SQLite user_version remain 1.
- Added keyword-only registration/current-head APIs and connection-owned source
  helpers. Registration records the prescribed globally owned operation/digest,
  shares the existing pending/child-ownership guard, returns its original receipt
  on exact retries, and never resets an accepted context or allocates element IDs.
- Added exact frozen/slotted `PublicationSourceClaim` and a trailing optional
  request field. Version-1 source-less bytes, defaults, operation order, child
  codecs and receipt shapes remain unchanged. Version 2 closes the source claim
  wire and binds canonical retained original bytes to the enclosing marker hash.
- Used the existing baseline codec, source fingerprint and final projector
  directly. No captured-value fabrication, independent encoding/projection,
  current-file reconstruction, publisher edits, or source codec edits.
- Bound first preparation to the exact accepted predecessor identity, original
  manifest and registered selection; persisted the next unbounded decimal
  sequence and derived final manifest atomically with parent/child claims.
- Kept journal apply as the only lifecycle/reference/occurrence writer. Source
  pointer CAS, source acceptance digest, all existing child effects, and the
  closed version-2 application receipt commit together. The receipt has no
  circular hash. Release retains its original shape and pending guard semantics.
- Kept original registration/prepare/apply/release receipts retryable after later
  accepted heads and reopen. Same bytes with an old predecessor cannot authorize
  a new publication. Equal-content/no-op acceptance advances once.
- Implemented independent pointer versus indexed highest accepted-row checks,
  exact registration/parent association checks, bounded immediate-predecessor
  validation, and complete source-chain audit. Pointer clearing/rewind, highest
  deletion, wrong context, premature acceptance and contradictory local hashes
  fail without fallback or repair. Missing context checks are conservative and
  spec-bounded when orphan registration digests cannot recover a context name.
- Routed full audits through schema 5, including materialized history capture,
  administration, explicit upgrade, backup and restore. The history wire itself
  contains no new source/publication rows. Backup now audits before claiming its
  destination; corruption cannot produce a completed backup through that API.
- Adjusted internal namespace validation to recognize exact frozen schemas for
  old-schema audit. Ordinary public open and transaction validation still require
  the current schema. Frozen schema-4 journal audit explicitly disables source
  table access and rejects source-bearing requests; missing-table errors are not
  swallowed. Binding audits remain enabled for schemas 3/4/5.
- Documented the API, receipts, CAS, recovery, version compatibility, integrity
  limits, and remaining managed-run/dependency/semantic/graph owners.

## Test evidence and actual TDD observations

All commands below use
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from the worktree.
The sole standalone Python codec inspection used `PYTHONPATH=src`.

1. Required first RED, before any production edit:
   `pytest tests/unit/test_element_identity_source_store.py -q`.
   `1 failed in 0.21s`, exclusively at
   `AttributeError: 'IdentityStore' object has no attribute 'register_source_context'`.
   Real transaction sealing, source capture/factory and store initialization had
   succeeded; the binary/CRLF `FR-1000000` bytes had been asserted. Root was
   notified before production changes. Registration GREEN: `1 passed in 0.22s`.
2. Version-2 RED: the source-only closed-wire/receipt test failed importing missing
   `PublicationSourceClaim` (`1 failed, 1 passed in 0.23s`). GREEN after journal
   composition: `2 passed in 0.47s`.
3. Backup integrity RED: 17 damaged-authority cases had already passed their
   read/audit checks but backup did not raise. Run: `17 failed, 34 passed in 4.00s`.
   Added the full pre-destination audit. GREEN: `51 passed in 3.53s`.
4. Altered parent-helper request RED: `-k 'frozen_schema4 or altered_parent'`
   returned `1 failed, 4 passed, 75 deselected in 0.76s`; source-plan validation
   accepted a different recovery payload supplied by its caller. Bound helper
   arguments to the exact retained parent. GREEN subset: `3 passed, 77 deselected
   in 0.54s`.
5. Other development checkpoints: 63 source tests passed in 5.91s; 76 passed in
   6.84s; 79 passed in 7.33s. Focused existing publication/admin/binding modules:
   `254 passed in 23.62s`. These passing cases are verification, not observed REDs.
   A mixed-fixture setup error initially mismatched issue occurrence text with
   its historical issue revision; correcting that test fixture is not claimed
   as a production regression or TDD evidence.

## Eleven-module checkpoint run (once)

Command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_publication.py tests/unit/test_element_identity_store.py tests/unit/test_element_identity_lifecycle.py tests/unit/test_element_identity_bindings.py tests/unit/test_element_identity_transaction_composition.py tests/unit/test_element_identity_binding_preview.py tests/unit/test_element_identity_snapshot.py tests/unit/test_element_identity_admin.py tests/unit/test_element_identity_request_codec.py tests/integration/test_element_identity_store.py -q -s
```

Result on the implementation subsequently committed as `f8911aef`:
`668 passed in 74.12s (0:01:14)`, exit 0, no warnings/failures.

The existing million-record test ran exactly once:

```text
CAPACITY records=1000000 import_seconds=14.496 open_seconds=0.000731 allocation_seconds=0.016208 database_bytes=168914944
```

This means one million imported element IDs, in existing 10,000-row batches.
It does not mean one million source heads or assessed revisions. The synthetic
5,000-digit source sequence test exercises decimal parsing/increment and numeric
index ordering; it does not claim thousands of physically accepted publications.

## Self-review amendment after the checkpoint

Self-review found that deleting both a publication parent and its ordinary
operation while retaining its source row could hit the old journal's missing
record branch and return `None`. It also found that the connection-owned source
acceptance helper checked only the source receipt fields, not the complete
supplied application and source-less request bypass.

Added actual RED tests for all three parent states and four acceptance-input
contradictions. Command:
`pytest tests/unit/test_element_identity_source_store.py -q -k 'missing_parent_and_operation or acceptance_helper'`.
Result: `7 failed, 80 deselected in 0.77s`, each from an expected error not being
raised. These tests exercised real SQLite rows and transactions.

Amended the missing-parent branch with an exact indexed source-plan lookup,
guarded by explicit source-schema support. Amended acceptance to authenticate
the exact retained parent request and require its prepared state and complete
canonical application receipt before writes. It reuses the journal's read-only
receipt validator; the three child writers and parent receipt owner remain in
the journal.

Covering amendment command:

```text
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_publication.py -q
```

Result: `203 passed in 17.23s`, exit 0, no warnings/failures. This includes all 87
source tests and the existing journal tests, including frozen schema-4 tests in
the source module. The eleven-module/capacity suite was not repeated after this
amendment. The earlier 668-test result is not represented as a run on amended code.

### Final bounded-read clarification and amendment

Root clarified that the planned no-history-scan rule includes existing identity
child-effect scans when reading a current source head. The original source read
called the full journal loader; switching only its `effects` flag would still
call the unconditional historical `_absent_rows` checks. No common guard or
`_ApplicationStore` behavior was weakened.

Added a real all-seven-family mixed-head test which denies any SQLite read of
historical identity child tables, and also checks indexed parent/claim/source-head
query plans. Observed RED:
`pytest tests/unit/test_element_identity_source_store.py -q -k 'mixed_source_head_read or structural_parent'`
returned `1 failed, 4 passed, 87 deselected in 0.92s`, with
`access to reservations.operation_id is prohibited` from the journal's old
`_absent_rows` path. The four passing cases are structural damage controls, not REDs.

Current source reads now use indexed source/registration/parent and child-claim
ownership, existing pure journal request/plan/preparation validators, exact closed
application envelope and preparation binding, state/completion/hash checks, and
source plan/immediate-predecessor validation. They do not call the journal history
loader or read historical identity child tables. Explicit journal read/retry/full
audit still reconstructs and validates all child effects. Recomputed local hashes
cannot hide a wrong preparation, operation envelope, completion digest or plan
shape on the current source read. Missing/damaged source-parent rejection remains
covered by the preceding amendment tests.

Final amended-code run of the same source/publication command above:
`208 passed in 17.89s`, exit 0, no warnings/failures (92 source tests and 116 existing
publication tests). No other production changes followed that run. Only final
documentation/report edits followed. This is the final amended-code evidence;
the 668-test/capacity checkpoint and intermediate 203-test run are separately
identified above and were not repeated on unchanged code.

## Coverage and ownership review

The source tests cover detached exact receipts; global registration/child ID
ownership and pending exclusion; all seven ID families with lifecycle/reference/
occurrence/source effects in one application; retained old revision evidence;
same/different specs and explicitly empty contexts; selection omission and
substitution; stale equal-content predecessors; three accepted heads and exact
old retries; direct SQLite damage including locally recomputed hashes; backup,
restore and full snapshot audit; genuine frozen schema-4 prepared/applied/released
journals with all three child methods; no source-table access during schema-4
audit; and strict old-schema public open/write rejection.

Real SQL authorizer failures cover source-plan insertion, a child insert, pointer
CAS, acceptance digest, parent application receipt and COMMIT. Each pre-commit
failure preserves the exact SQL dump, original head, absent child effects and
pending state. An isolated connection wrapper separately reports an exception
after actual COMMIT: reopen and exact retry recover one coherent committed
receipt. This is explicitly an uncertain outcome, not rollback. Two real spawned
processes compete from one predecessor; one accepts, one rejects, with one sequence.

Real publisher callback tests retain an interrupted actual filesystem prefix,
reload the original baseline from the stored version-2 request, retry to exact
final bytes/head, and release explicitly. They include binary/CRLF/wide-ID data,
hidden files, empty directories, absent selections, writes/deletion/no-op, modes
and nested parents. Dependency drift never reaches prepare; after-callback
failure leaves applied pending state and stage/recovery material. Pure codec and
ordinary SQLite tests are not POSIX-skipped; only real capture/promotion tests use
the secure-POSIX fixture. Store/helper tests prohibit file opens and transaction/
PRAGMA ownership. EXPLAIN checks verify required source-head/context/parent and
spec-registration indexes without temporary sorting.

## Files changed

- `src/harness/element_identity_source_store.py` (new)
- `src/harness/element_identity_publication.py`
- `src/harness/element_identity_publication_store.py`
- `src/harness/element_identity_schema.py`
- `src/harness/element_identity_store.py`
- `src/harness/element_identity_snapshot.py`
- `tests/unit/test_element_identity_source_store.py` (new)
- `tests/unit/test_element_identity_admin.py` (current schema/count expectations)
- `tests/unit/test_element_identity_bindings.py` (latest-schema case labels)
- `docs/element-identity-storage.md`
- This task report.

## Limits and remaining work

Source contexts are explicit trusted observation scopes. They do not authenticate
the run's intended context/namespace, dependency completeness, source relocation,
semantic review, graph completion or future dependency refresh. Whole-database
coherent substitution is outside local consistency detection. No controller,
provider, graph, CLI, source codec, projector, guard, publisher, or memory
implementation was changed or activated. No install, main merge, live/provider
tests, stopped-smoke operation, broad full-unit suite, or postcommit test repeat
was performed. Root owns the plan/ledger and independent review.

`git diff --check` passed during self-review, including after the final amended-code
test run. The final staged task range is also checked before committing. Source ownership is kept
in one focused module; the existing publication/store modules remain substantial
and were extended without unrelated restructuring.
