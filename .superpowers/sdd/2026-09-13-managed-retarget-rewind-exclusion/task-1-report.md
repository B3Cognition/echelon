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
