# Task 1 report: managed retarget/rewind exclusion

Status: DONE. All identified fixture failures resolved; no unresolved implementation findings.

Base: `5591bc696d8c3d9ef27667961760c593a8954bd7`.
Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.
Implementation commit: `d57c3c59f372f732bce784d7ed66787e8aef0024`.
Staged seven-module covering tree: `46f9bedca263e566ea7b1cea3d3d9b517b88e7fa`.
Amended staged tree: `8e456289d9908655d91290d6f82409fdfae04067`.

## Implementation

- Extended only the empty exact run tuple in `IdentityStore.require_unmanaged_execution`: valid non-None spec selection permits `()`. No selector at all still refuses before transaction. Query text, indexes, single query-only transaction, duplicate/type rules, retained matching-row/orphan refusal and no-chain/process-control behavior remain intact.
- Added `require_legacy_identity_spec`, validating the exact identifier before I/O. Both guards share existing-authority presence/open logic, retaining execution's managed-key, filesystem-presence, original-claim-validation, then open order. No authority initialization, Markdown lookup or fabricated run selector.
- Added selected-spec plus freshly read original baseline admission after native leases/preflight in fresh apply and prepared adoption. Resume also checks actual active replacement state before callback, invalidation, or rebuilding/finalizing return. Rejection stays outside mutation failure recording.
- Added recovery admission after native checkpoint/revision/runtime checks and before captured-receipt reconciliation. Actual retained baseline run is independently queried, with strict optional JSON-object reads only after real ancestor-directory and regular-leaf validation. No `SquadStateStore` constructor is used for that optional read, because it would create staging/lock infrastructure. Missing baseline state/run stays missing and only its persisted run ID is queried. Ordinary failures become the bounded recovery error outside their handler; process-control exceptions propagate.
- Added CLI rewind admission after fresh locked state, independently selecting canonical spec and original run claims for both confirm and nominal preview. Preserved the early read-only failed-gate preflight. Added only managed-identity-validator `StateAdvanceError` translation at both existing loads; unrelated native errors remain unchanged.
- Added standalone confirmed rewind checks for selected-directory name and checkpoint spec, before same-head success and all mutation boundaries. Library preview remains native.
- Documented exact owner boundaries, native cold-load bookkeeping, retained compatibility, absence-query limitations and remaining managed transition/all-writer/graph-mining/rollout integration.

## Files

Implementation/new tests/docs only:

1. `src/harness/element_identity_store.py`
2. `src/harness/element_identity_legacy_guard.py`
3. `src/echelon/spec_retarget.py`
4. `src/echelon/spec_retarget_recovery.py`
5. `src/echelon/rewind.py`
6. `src/echelon/cli.py`
7. `docs/element-identity-storage.md`
8. `tests/unit/test_managed_retarget_rewind_exclusion.py`
9. `tests/unit/test_cli_spec_retarget.py`: root-authorized 12-line fixture-only amendment in three named test bodies; no assertion or mock changes.

All other pre-existing tests are unchanged. Root-owned plan, brief and progress changes are excluded from the implementation index. This report is separately authorized and will be committed separately.

## Native fixture history and rulings

The first RED uses the actual retarget CLI fixture, real Git repository, native selectors/preflight and leases. Enrollment uses actual source-tree capture, source-context registration and managed registration. Genesis requires an empty selected tree: the helper temporarily retains the fixture's run-shadow contents separately, captures/enrolls the genuinely empty actual selected tree, then materializes the original native fixture bytes as deliberate post-genesis source state. This proves retained negative ownership refusal; it does not assert accepted-source freshness or valid positive managed retarget. Genesis validation was never weakened.

Root was notified of each initial fixture correction and actual RED/GREEN. Root confirmed the post-genesis fixture interpretation. Root also ruled:

- Keep pre-lease `_failed_gate_rewind_authority`, which is read-only; admission precedes the under-lock evaluation and every consuming/effect path. Native invalid preflight may reject first.
- Translate only `StateAdvanceError.validator == 'managed_identity'` at the two native CLI loads. Distinguish cold native staging/state.lock creation from prohibited business effects.
- Preserve native optional-baseline ancestor checks before leaf reads; no constructor/staging/lock creation there.
- Committed recovery probes with non-recovered history return `None` before `_require_recovery_revision`. Preserve that harmless native path and test actual recovered history separately.
- Ruling 40 narrowly authorizes real baseline `state.json` fixture materialization in the three existing synthetic `_apply_retarget` test bodies, preserving all assertions/mocks and the new fresh-read requirement. Only the new module plus CLI-retarget module are rerun after this amendment.

## Test attempts and fixture corrections

All commands below ran in the worktree above with the local absolute executable; no global installation, provider/backend, live mutation, stopped smoke, full-unit run or capacity benchmark was invoked.

Common executable: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`.

1. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py::test_managed_retarget_rejects_before_first_durable_effect -q`
   - Exit 4; collection error, `ModuleNotFoundError: No module named 'test_cli_spec_retarget'`, 1 error in 0.07s.
   - Fixture import corrected to the repository package `tests.unit.test_cli_spec_retarget`.
2. Same exact command.
   - Exit 1; 1 failed in 0.46s. Actual managed registration refused a nonempty selected tree with `IdentityStoreError: invalid managed identity authority or request`.
   - Inspected `_source`/`register` in `element_identity_managed_store.py` and native genesis fixture. Corrected fixture to real empty-tree genesis followed by deliberate source materialization, as described above.
3. Same exact command: actual first RED.
   - Exit 1; 1 failed in 0.64s. Native `_apply_retarget` reached `append_prepared_revision_from_preview`; the sole effect-boundary tripwire recorded entry and raised `Failed: managed retarget reached its first durable effect`.
   - This was before production edits, with valid registration and native preflight/leases. Failure was not dirt, malformed registration or self-deadlock.
4. Same exact command: first GREEN.
   - Exit 0; 1 passed in 0.66s. No tripwire entry; canonical/run bytes, identity SQL, pointer, Git HEAD/refs/index/object inventory unchanged.
5. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -q`
   - Exit 0; 99 passed in 27.54s. Initial store/spec-guard and complete retarget branch matrix.
6. Same module command after adding recovery/rewind tests.
   - Exit 1; 22 failed, 188 passed in 61.88s.
   - All failures were `DID NOT RAISE RetargetRecoveryError` for the 11 captured-prepared-history witnesses crossed with `verified_committed_retarget_recovery` and `resume_committed_retarget_recovery`. Native probes return `None` before revision admission for non-recovered history. No effect tripwire was entered. The actual committed-recovery fixture/control passed.
   - Corrected matrix to call `_require_recovery_revision` and `recover_retarget_checkpoint`; explicitly asserted the two native non-recovered no-ops and tested both committed entry points using the real recovered commit fixture. No production changes for these failures.
7. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -k 'recovery or busy_native or failed_gate' -q`
   - Exit 1; 2 failed, 30 passed, 175 deselected in 11.11s.
   - New failed-gate tests passed their intended assertions, then raised `NameError: name 'prepare_rewind' is not defined` because a patch had moved standalone preview assertions to their end. Moved those lines back to their standalone test. No production changes.
8. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -k 'recovery or busy_native or failed_gate or standalone' -q`
   - Exit 0; 36 passed, 171 deselected in 12.18s.
9. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -k 'standalone or cli_uses or keeps_legacy_cli or optional_baseline or native_preview_noop or unrelated_authority_retains' -q`
   - Exit 0; 87 passed, 128 deselected in 29.75s.
   - Includes cold-state bookkeeping bounds, metadata-only malformed CLI refusal, selected/claimed/physical/declared witnesses, unrelated-authority native same-head preview completion, optional read I/O/process-control handling and both standalone spec witnesses.
10. Once-only seven-module cover:
    `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_cli_spec_retarget.py tests/unit/test_spec_retarget.py tests/unit/test_spec_retarget_recovery.py tests/unit/test_cli_rewind.py tests/unit/test_rewind.py -q`
    - Exit 1; 8 failed, 441 passed in 83.70s. Staged tested tree: `46f9bedca263e566ea7b1cea3d3d9b517b88e7fa`.
    - All failures were existing synthetic `_apply_retarget` fixtures in `test_cli_spec_retarget.py`, which mocked leases, preflight and effects but created no baseline `state.json`. The newly required fresh state read raised `RetargetEligibilityError` from `FileNotFoundError` before their intended effect assertions. Failing tests: `test_apply_retarget_holds_locks_revalidates_and_orders_destructive_effects`; all six `test_destructive_failure_marks_failed_and_keeps_recovery_visible` cases (`purge`, `persist`, `artifacts`, `graphs`, `context`, `rebuilding`); and `test_bootstrap_failure_after_checkpoint_records_failure_and_recovery`.
    - Inspected those exact fixture bodies and `_baseline_state`/`_read_json_object`; there is no actual state read fixture or existing read seam supplied by them. Root was notified of the conflict with the no-existing-test-edits constraint. Requested only real legacy baseline state materialization in the three existing test bodies (eight cases), retaining all assertions and mocks. No production waiver or missing-state fallback was proposed.
11. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_cli_spec_retarget.py -q`
    - Exit 0; 280 passed in 70.44s. Amended staged tree: `8e456289d9908655d91290d6f82409fdfae04067`.
    - The only post-cover implementation-tree change is adding a real baseline directory and ordinary legacy JSON state in those three authorized fixture setups (12 added lines). There is no post-cover production or new-test change.

Before the cover, added final missing-baseline-directory/ancestor/declared/claimed tests, damaged CLI authority, exact string/tuple subclass checks and indexed-query SQL equality. These final cases are included in the covering tree, not retroactively attributed to earlier scoped runs.

## Diagnostic and review checks

- `git status --short` / `git rev-parse HEAD`: initial HEAD exactly matched BASE; only root-owned progress was dirty initially.
- Initial filename inventory command `pwd && rg --files -g AGENTS.md -g CLAUDE.md -g task-1-brief.md -g '!node_modules' -g '!vendor' . /Users/michalbachorik/work 2>/dev/null` was overbroad and returned a truncated list of filenames. No unrelated file contents were read or changed; subsequent repository work stayed in the authorized worktree. Applicable root `AGENTS.md` and `CLAUDE.md` were fully read; there were no deeper matching instruction files under src/tests/docs.
- Read scoped brief, native store/guard/retarget/recovery/rewind/CLI implementations and native fixtures with `cat`, `sed` and `rg`. Read the TDD skill, its `writing-good-tests.md` reference and verification skill. No whole plan was read and no subagents were created.
- A reconnaissance search using nonexistent `tests/unit/test_squad_human_input*` encountered zsh's `no matches found`; switched to `rg --files tests/unit` then the actual human-input/decision test paths. This was a read-only discovery correction, not a test execution failure.
- `git diff --check`: clean before staging.
- Confirmed all seven exact covering paths with `ls tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_cli_spec_retarget.py tests/unit/test_spec_retarget.py tests/unit/test_spec_retarget_recovery.py tests/unit/test_cli_rewind.py tests/unit/test_rewind.py`.
- `git add src/harness/element_identity_store.py src/harness/element_identity_legacy_guard.py src/echelon/spec_retarget.py src/echelon/spec_retarget_recovery.py src/echelon/rewind.py src/echelon/cli.py docs/element-identity-storage.md tests/unit/test_managed_retarget_rewind_exclusion.py` staged only the 8 named files.
- `git diff --cached --check`: clean. `git write-tree`: `46f9bedca263e566ea7b1cea3d3d9b517b88e7fa`. Staged stat: 8 files, 938 insertions, 24 deletions.

## Self-review

- Checked each production gate against its first durable effect and failure handler: history append, checkpoint/callback/bootstrap, resume return/invalidation, recovery receipt advancement, rewind backup/discard/reset, ledger/state/claim/pointer publication and completion output.
- Verified independent selected spec, physical run, raw declared run and raw claimed spec witnesses without replacing runtime fields. Real selector stripping is deliberately exercised by whitespace claims.
- Guard/query failures are bounded outside handlers; no matching-payload decode can waive retained ownership. No all-spec/child-history scan or namespace/schema mutation was added. Shared authority observation preserves old monkeypatch seams/order and BaseException behavior.
- Rejection snapshots cover retained source/run/stage/graph/history files, SQLite dump, pointer, Git HEAD/refs/index/objects. CLI cold reads explicitly allow only native empty `state.lock` and staging/runtime directory bookkeeping; recovery optional reads create nothing.
- Every retarget branch has the same independent ownership matrix; managed negative mode checks cover guided/semi/banzai. Rewind crosses ordinary/retarget checkpoint, same/moving head, confirm/preview, three modes and retained/removed/malformed declaration. Native lease contention is exercised from a real separate process with bounded pipe startup/release, followed by actual lease reacquisition after release.
- Real captured recovery demonstrates the historical hidden advancement in the unmanaged control; denied recovery cannot advance or recreate a missing baseline. A real native recovered Git commit is verified before enrollment and both committed entry points refuse afterward.
- No existing assertions/mocks, unrelated tests, root administrative files, journal schemas, authority producers or unrelated native same-head behavior were changed. The three authorized related fixtures now supply their real baseline state input.

## Remaining limitations

This is bounded negative admission at the named native owners. It is not an enrollment/concurrency lease, full-history audit, positive managed runtime admission, managed retarget/rewind transition, replacement managed-run binding, durable identity-history rewind, or complete direct writer perimeter. Declared metadata plus durable witnesses being lost cannot be repaired by Markdown inference. Standalone rewind lacks actual runtime context beyond its selected/checkpoint spec witnesses; CLI supplies original state. Native source registration genesis retained in tests does not certify the later fixture source contents. Pending identity/source publication, completion/recovery integration, direct graph/memory/checkpoint writers, graph-mining integration and final offline/rollout authorization remain separate.

## Post-cover amendments

Root-authorized fixture-only amendment: 12 added lines in the three named existing `test_cli_spec_retarget.py` fixture setups, preserving their assertions/mocks. `git add tests/unit/test_cli_spec_retarget.py`, `git diff --cached --check` (clean), and `git write-tree` recorded amended tree `8e456289d9908655d91290d6f82409fdfae04067`. The named two-module scoped run above verifies this amended tree. The seven-module cover is not repeated. Report-only writing is excluded from the implementation tree and does not claim another test run.

After the passing scoped run, `git diff --cached --name-only` showed exactly the nine authorized implementation/test/doc files, and `git diff --name-only --` with those exact paths returned no unstaged differences. `git write-tree` remained `8e456289d9908655d91290d6f82409fdfae04067`. `git diff --cached --check` was clean. `git commit -m 'fix(identity): exclude managed retarget and rewind effects'` created `d57c3c59f372f732bce784d7ed66787e8aef0024` (9 files, 950 insertions, 24 deletions); `git rev-parse HEAD HEAD^{tree}` verified its tree equals the amended tested tree. No production/test/doc amendment or unchanged test rerun followed that commit. This report is the only follow-up commit content.

## Review fix round 1/5 — baseline-only CLI recovery admission

Reviewed HEAD: `0d0f7cece8ca1be782db418085e5ca932f65507c`.
Fix status: DONE. The Important baseline-only CLI finding is fixed; no unresolved fix findings.
Fix implementation commit: `72af5b164eea4fa38b73afb930949b83d36a3cbb`.
Fix staged tested tree: `9d72db31394a0065c491778110c4487579cdbf98`.

### Confirmed Important finding and approved contract

Root confirmed that the original composition let a non-recovered committed-recovery probe return `None` without examining retained baseline ownership. CLI could then create a backup/reset/discard files or trim the checkpoint ledger before later recovery admission rejected a managed baseline. This was a plan-composition defect; the initial report's successful checks did not establish this baseline-only CLI boundary.

Ruling 41 approved extracting the existing nonmutating checkpoint/history/runtime validation and identity-admission prefix into one inspector returning `(spec_dir, revision)`, exposing `require_legacy_retarget_recovery(...) -> None` as a wrapper, and invoking it before CLI probes/resume/dirty planning/rewind effects. Captured receipt reconciliation must stay at the existing later owner. The worker read the amended brief first and reproduced the exact native effect-boundary failure before production edits.

### Fix implementation and self-review

- `_inspect_legacy_retarget_recovery` now contains the former exact identity-validation/admission prefix, with no duplicate parser or mutation option. Its return value is used by the original `_require_recovery_revision`, which retains the raw-graph reconciliation and history-advance logic.
- Public `require_legacy_retarget_recovery` invokes only that inspector and returns `None`. It cannot reconcile receipts, reconstruct baseline state, initialize staging/locks, or publish anything.
- CLI's retarget branch calls the wrapper under its existing leases/fresh state checks before committed-recovery probing/resume, recovery dirty-path planning, library rewind and ledger effects. The bounded identity `RewindError` is raised outside the handler, with no cause or context. Other native recovery errors keep their existing chained diagnostic style; BaseException propagation is unchanged.
- The non-recovered standalone committed probes still return `None` without calling the inspector. Their behavior was not broadened or used as an early recovery writer.
- Added a genuine completed-retarget baseline-only regression plus independent retained baseline physical/declared/claimed ownership, missing state/run, malformed and dangling-symlink cases. These cross confirmed/nominal preview and same-head dirty/moving-head/clean native library no-op setups. Snapshot assertions retain Git HEAD/refs/index/objects, source/run/history/ledger/state/pointer/SQL bytes, allowing only existing CLI empty state-lock bookkeeping. Tests reacquire the actual current replacement run's execution lease after rejection; missing baselines remain missing.
- The clean no-op setup uses native prepared revision, checkpoint commit and replacement bootstrap under real leases, stopping before invalidation. It proves the underlying library returns `Already at checkpoint.`; CLI identity admission precedes even the later native dirty-plan validation. It is not represented as a completed invalidation/recovery transaction.
- A native captured-receipt control proves the new wrapper leaves history `prepared` and snapshots unchanged, while the existing later `_require_recovery_revision` advances that same fixture to `failed`. Public wrapper tests also preserve bounded optional-read failures and process-control propagation.
- Storage documentation now identifies the shared inspector, public early wrapper and CLI baseline-only boundary explicitly.
- No full recovery invocation, new mutation flag, synthetic selector, authority initialization, history relabeling, journal schema, all-writer perimeter expansion or banzai waiver was introduced.

### Authorized related fixture correction

Before starting the fix cover, inspection found three existing synthetic CLI retarget tests with checkpoint/runtime but no history. A named diagnostic confirmed all three fail at the newly required native identity inspector, not at an effect. Root read their full bodies and authorized Ruling 43: supply actual native prepared-revision/recovery-projection setup and bind runtime/checkpoint to its returned revision ID, preserving all existing effects and assertions. Ruling 42 belongs to root's separately drafted memory plan and is outside this task.

Only `_seed_retarget_recovery_identity` and its three fixture call sites were added in `tests/unit/test_cli_rewind.py`: `test_retarget_checkpoint_routes_before_generic_cleanup_with_prereset_state`, `test_retarget_checkpoint_resumes_committed_recovery_before_git_reset`, and `test_unconfirmed_committed_recovery_is_read_only`. Existing effect mocks and assertions are unchanged. No admission mock or missing-history production fallback was added.

### Exact fix test/diagnostic attempts

Every command ran in `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract` using the existing absolute executable. Independent test processes used separate pytest temporary repositories. No seven-module rerun, full-unit/bare pytest, install, provider/backend dispatch, stopped smoke, live mutation or capacity benchmark occurred.

1. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py::test_cli_rewind_rejects_baseline_only_metadata_before_first_effect -q`
   - Actual first RED, first attempt: exit 1; 1 failed in 1.97s. Native `prepare_spec_retarget(..., confirm=True)` completed successfully, only retained baseline `managed_identity=False` was added, and confirmed `_cmd_rewind` reached the `create_backup_ref` effect tripwire (`Failed: baseline-only managed rewind reached its first effect`). Selected/current ownership remained legacy. No production edits preceded this observation.
2. Same exact command after the Ruling 41 production extraction/placement.
   - First GREEN: exit 0; 1 passed in 1.79s. No effect entry; native snapshots unchanged except allowed read bookkeeping.
3. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_rewind.py -k 'retarget_checkpoint or unconfirmed_committed_recovery' -q --tb=short`
   - Exit 1; 3 failed, 31 deselected in 1.28s. All three synthetic fixtures raised `retarget recovery revision is unavailable`. Scope conflict escalated before editing existing tests; root authorized only the native fixture binding described above.
4. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -k 'baseline_only or admission_wrapper' -q --tb=short`
   - Exit 1; 16 failed, 37 passed, 228 deselected in 68.99s. Every failure was the new clean-noop fixture: restoring the whole canonical spec to checkpoint bytes reverted history to `prepared` while retaining rebuilding runtime, so the native dirty-path planner rejected `retarget recovery controller history drifted` during setup. Same-head dirty/moving baseline cases and wrapper controls passed. No prohibited effect was reached and no production correction was made for these fixture failures.
   - Replaced this setup with the genuine prepared-checkpoint plus replacement bootstrap state under native leases, stopping before invalidation instead of rewriting history. The lower-level native library clean same-head result is checked before adding baseline ownership; CLI admission is tested before later planner validation. Root was informed of the failure and accepted this fixture-only correction; first RED provenance remains the completed-retarget case in attempt 1.
5. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_rewind.py -k 'retarget_checkpoint or unconfirmed_committed_recovery' -q --tb=short`
   - Exit 0; 3 passed, 31 deselected in 0.53s after the narrowly authorized existing-fixture binding.
6. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py -k 'baseline_only and clean-noop' -q --tb=short`
   - Exit 0; 16 passed, 265 deselected in 18.29s after the native clean-noop fixture correction.
7. `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_cli_rewind.py tests/unit/test_spec_retarget_recovery.py -q`
   - Exit 0; 332 passed in 138.50s. Exact staged tested tree: `9d72db31394a0065c491778110c4487579cdbf98`.

### Fix tree and scope accounting

`git rev-parse HEAD` confirmed reviewed HEAD `0d0f7cece8ca1be782db418085e5ca932f65507c`. Read-only scoped implementation/test inspection and `git diff --check` were completed. Confirmed the three exact test paths with `ls`. `git add src/echelon/spec_retarget_recovery.py src/echelon/cli.py docs/element-identity-storage.md tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_cli_rewind.py` staged only those five files. `git diff --cached --check` was clean; `git write-tree` returned `9d72db31394a0065c491778110c4487579cdbf98`. Staged stat: 5 files, 251 insertions, 7 deletions.

Root-owned plan/brief/progress and the untracked next memory-plan draft were excluded. This appended fix report is separate from the implementation tested tree. No post-cover implementation amendments were made. The wider perimeter limitations documented above remain unchanged; they are not a deferral of the specific baseline-only CLI finding addressed here.

After the passing fix cover, `git diff --cached --name-only` contained exactly the five scoped files, and `git diff --name-only --` with those paths returned no unstaged changes. `git write-tree` still returned `9d72db31394a0065c491778110c4487579cdbf98`; `git diff --cached --check` was clean. `git commit -m 'fix(identity): admit retained baseline before CLI rewind effects'` created `72af5b164eea4fa38b73afb930949b83d36a3cbb` (5 files, 251 insertions, 7 deletions). `git rev-parse HEAD HEAD^{tree}` verified the implementation commit has the exact tested tree. The only follow-up content is this report append; no unchanged postcommit test rerun was performed.
