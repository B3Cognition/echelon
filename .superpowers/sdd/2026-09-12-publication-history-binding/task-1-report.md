# Task 1 report: complete proposed-history publication binding

Status: DONE. No known unresolved implementation defect from implementer self-review.
Independent original-BASE review belongs to root and has not been performed by this implementer.

## Scope and implementation

Worked only in `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`,
branch `fix/delivery-controller-contract`, starting at
`6879b17c583f38c0b83a8b94d3408d7df2be66ec`.
Read the task-1 brief, applicable AGENTS/CLAUDE guidance and TDD/verification skills,
including the good-tests reference. No other plan workspace was read. No agents or
reviewers were spawned. All file edits used apply_patch.

The optional exact `proposed_history_sha256` field follows `sources`. Existing
v1/v2 request encodings remain unchanged when it is absent. Version 3 has two
closed shapes, with mandatory non-null exact lowercase history SHA and optional
complete source claim. Existing child operation order, canonical encoding,
detachment and marker validation are retained. Duplicate JSON keys, unknown keys,
null source/history wire values, malformed hashes and damaged frozen records reject.

The preview's row overlay is extracted as a private pure function over a detached
snapshot, decoded children and the existing planned rows. Public preview retains
its pending and new-child guards. New preparation checks complete proposed history
inside the existing write transaction before any parent/claim/source insert.
Prepared application validates retained ownership/plan first, checks current
complete history before child writers, applies through the existing sole writers,
accepts sources and updates the parent, then captures actual materialized history
before commit. Any mismatch rolls back the existing composed transaction.

Application v3 metadata is derived from the retained request by one pure shared
helper. The receipt retains complete operation and publication entries, its exact
history claim, and existing source receipt when present. Source `_parent` uses
that metadata for its closed envelope; `_bound_row` relies on its already-validated
parent envelope and checks exact source receipt and application hash. `accept`
continues to reuse journal receipt reconstruction and retained request equality.
There is no new capture in `_load`, `_application`, source/managed reads or the
common allocator/child guard. Exact prior retries bypass fresh complete-history
comparison and retain original receipts after later identity and source history.

Files in the implementation commit:

- `src/harness/element_identity_publication.py`: optional field, strict v3 codec and pure receipt metadata.
- `src/harness/element_identity_publication_store.py`: three transactional history checks and retained application metadata.
- `src/harness/element_identity_snapshot_preview.py`: shared pure overlay extraction; no public pending bypass.
- `src/harness/element_identity_source_store.py`: v3 closed-envelope/history association checks.
- `tests/unit/test_element_identity_publication_history.py`: 60 focused cases including parameter variants.
- `docs/element-identity-storage.md`: exact behavior, compatibility, cost, rollout and non-authentication limitations.

`element_identity_snapshot.py`, schema/admin/state/controller/executor/provider/CLI/startup,
graph and memory production code were not changed. No global installation, main
checkout, stopped-smoke workspace, producer or live/runtime integration was mutated.
Root's dirty `progress.md` was never staged or committed by this implementer.

## Actual RED and complete command chronology

All pytest commands below ran from the worktree above with
`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`. No standalone Python
was needed. There were no full unit, capacity, controller or live suite runs.

1. Added exactly the brief's first regression before production changes.
   Command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py`.
   Actual output:

   ```text
   FAILED tests/unit/test_element_identity_publication_history.py::test_history_bound_publication_retains_exact_snapshot
   TypeError: PublicationIntentRequest.__init__() got an unexpected keyword argument 'proposed_history_sha256'
   tests/unit/test_element_identity_publication_history.py:11: TypeError
   1 failed in 0.23s
   ```

   Real initialization, reservation, canonical child encoding and existing preview
   all succeeded before the constructor TypeError. This was the missing feature,
   not a setup/import failure. Root was notified with this exact RED before any
   production edit. The `a * 64` seal hash is a journal-only test claim, not physical
   publication proof.

2. Implemented the four production-file changes described above. Ran the same
   command: `1 passed in 0.26s`. This was the first GREEN. No production code was
   changed after this run; subsequent changes were tests and documentation.

3. Added literal wire/receipt expectations, malformed/damaged values, all three
   child methods, exact CRLF/Unicode detachment, wide labels, stale legitimate
   entity/reference/occurrence history, irrelevant changes, ownership guards,
   pre-application corruption, post-effect rollback and SQL/commit fault coverage.
   Same module command: `40 passed in 3.96s`.

4. Added rehashed request/receipt corruption variants and real guarded-source
   recovery, graph comparison, retained retry, bounded reads and backup/restore.
   Same module command: `1 failed, 56 passed in 6.17s`.
   The test reached restore after all preceding integration assertions passed,
   then failed with `IdentityStoreError: workspace must be an existing directory`.
   This was a test setup error: the restore destination had not been created.

5. Added the missing destination `mkdir` in the test only.
   Command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py::test_real_guarded_source_recovery_graph_retry_backup_and_bounded_reads`.
   Output: `1 passed in 0.78s`.

6. Added request-only rehash cases and a second real guarded v3 source publication
   to prove original retries survive both identity and source-head advancement.
   Command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py::test_real_guarded_source_recovery_graph_retry_backup_and_bounded_reads tests/unit/test_element_identity_publication_history.py::test_rehashed_history_or_closed_receipt_damage_rejects_association`.
   Output: `1 failed, 18 passed in 2.51s`.
   The real-workflow fixture omitted the existing-directory prerequisite for
   `runs/second`; `SquadPublicationTransaction.begin` raised `PublicationError:
   manifest_invalid`, caused by `FileNotFoundError` for that directory. All 18
   rehashed association cases passed. No production change was made.

7. Added `runs/second.mkdir()` in the test.
   Command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py::test_real_guarded_source_recovery_graph_retry_backup_and_bounded_reads`.
   Output: `1 passed in 1.06s`.

8. Added an SQL authorizer regression proving stale bound preparation attempts
   zero INSERT/UPDATE/DELETE operations before rejecting its history mismatch.
   Command: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py::test_stale_prepare_checks_history_before_attempting_any_insert`.
   Output: `1 passed in 0.34s`.

9. Completed documentation and self-review, then ran the requested complete
   covering modules exactly once on final implementation/test code:

   ```text
   /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_element_identity_publication_history.py tests/unit/test_element_identity_publication.py tests/unit/test_element_identity_source_store.py tests/unit/test_element_identity_snapshot_preview.py tests/unit/test_element_identity_snapshot.py tests/unit/test_element_identity_managed_context.py tests/unit/test_element_identity_request_codec.py tests/unit/test_spec_graph_identity.py
   576 passed in 42.31s
   ```

   Exit code 0, no failures or skips reported. In particular, real secure-POSIX
   publication exercised on this host rather than skipping. No unchanged
   postcommit test rerun was performed. Only this report was added after coverage.

## Evidence and self-review

Reviewed the entire original-BASE production/documentation diff and complete new
test file, then staged only the six scoped task files. `git diff --check` and
`git diff --cached --check` both exited 0 with no output.

- Compatibility: four independently assembled canonical request and complete
  empty-receipt expectations cover v1, v2 and both v3 source variants. Expected
  plan bytes are the literal `{"lineage":[],"revisions":[]}`; preparation/release
  shapes are exact. Existing covering modules protect old child codec/receipt
  behavior, migration fixtures, projection and history ordering.
- Freshness and ordering: legitimate unrelated revision/reference/occurrence
  writes leave the exact child proposal valid and source head unchanged, but stale
  prepare rejects with unchanged complete SQL dump. Fresh hashes succeed. Unused
  reservations and another spec's real create preserve the proposal hash. A
  dedicated authorizer proves no write is even attempted before rejection.
- Prepared ownership: ordinary reservation/child writes and public preview reject
  pending state. An explicit raw-SQL, internally consistent fault adds a reference
  with its operation, binding receipt and hashes. Full audit and prepared read
  still observe the retained intent; apply rejects before either child writer and
  leaves the pending record intact. This is injected corruption, not an allowed
  concurrent writer.
- Rollback: an injected faulty child writer produces extra internally consistent
  reference history after precheck. The actual post-application comparison rejects;
  a full before/after SQL dump shows rollback of all child effects, source pointer,
  source application hash and parent receipt/state. Normal retry succeeds. SQL
  authorizers separately fail source-plan insert, child insert, source-head update,
  parent receipt update and actual COMMIT. A commit wrapper that commits first and
  then raises demonstrates uncertainty/reopen retaining one original receipt.
- Real integrations in tests: actual source inspection, seal, registration,
  physical-prefix interruption, reloaded original baseline and guarded recovery
  agree with the stored source manifest/application hash. A second real guarded
  source publication advances the head. Original request, prepare/apply/release
  results survive later identity/source history, restart, full audit and real
  backup/restore. No live producer or runtime caller was enabled.
- Graph boundary: actual existing projection/rendering from proposed and applied
  complete history yields equal output, stable entity keys, and old evidence edges
  targeting revision 1 rather than the new revision. The graph was not added to
  the physical publication and this test claims equality, not graph/source
  authentication.
- Retained associations: request-only, receipt-only and repaired-preparation
  history mismatches reject despite recalculated local hashes. Both source and
  sourceless v3 envelopes reject missing/null/extra history, old version, null
  source and duplicate keys. Source head reads additionally enforce exact source
  receipt/application hashes.
- No-scan/recursion: capture is called only by the new history-check helper and
  the post-effect apply branch. Full capture's audit can reenter journal `_load`
  and source validation, but neither path captures. `_application` only derives
  metadata from the retained request. The source/managed read test denies reads
  to all identity-history tables and still succeeds after two v3 source heads;
  EXPLAIN shows indexed SEARCH without SCAN/TEMP B-TREE for head, parent and claims.
  Explicit capture tripwires protect exact retries and ordinary allocation. No
  new transaction/savepoint/copy/callback boundary was introduced.

Self-review corrections were test fixture directory prerequisites and stronger
request-only/source-head/pre-insert evidence, as chronologized above. No production
correctness or scope amendment was identified. No schema/graph/source-capture owner
expansion was necessary.

## Staged and commit provenance

Implementation commit: `554f83c94176115fc98040dde883ee9e62b42dd0`
(`Bind publication intents to complete proposed identity history`).

- Parent: original BASE `6879b17c583f38c0b83a8b94d3408d7df2be66ec`.
- Staged tree immediately before commit: `4425f8caaf6ebe870bc150abcbf7c8f83dd26f65`.
- Actual committed tree: `4425f8caaf6ebe870bc150abcbf7c8f83dd26f65`, verified using
  `git log -1 --format='%H%n%T%n%P'`.
- Six files, 617 insertions and 17 deletions. `git show --format= --name-only HEAD`
  showed exactly the six implementation files listed above.
- Only unstaged change after that commit was root-owned
  `.superpowers/sdd/2026-09-12-publication-history-binding/progress.md`.

This report is committed separately after the implementation commit so its full
commit/tree provenance can be recorded without a self-referential hash. The
report-only commit adds this explicit scratch path; it changes no tested code.
No later implementation amendment or postcommit test repeat occurred in this task.
Future fix rounds must append their exact edits and named covering evidence here.

## Concerns and honest limitations

No known unresolved task defect. Full-history capture remains deliberately costly:
one capture for a new bound prepare and two for a still-prepared bound apply, each
with the existing global authority audit. It is not a per-ID scan or throughput
claim. Old binaries cannot interpret v3 and matching-code rollout is required.

The digest checks materialized-history equality, not graph derivation, complete
physical source selection, semantic correctness, trusted runtime selection,
historical adoption or graph artifact bytes. A coherent malicious rewrite of all
authority rows is outside these association checks. Source-backed fault tests use
declared empty selections where physical source proof is irrelevant; the separate
real guarded-source test supplies actual physical capture/seal/recovery evidence.

Captured-source graph construction, all producer proposals/reservations, managed
runtime selection, semantic authorization, coordinated completion/recovery,
lifecycle-aware memory and bounded repair remain separate integration work.
All producer/runtime/live integrations remain OFF. Root supplies the fresh
independent review against the full original BASE after this task is returned.
