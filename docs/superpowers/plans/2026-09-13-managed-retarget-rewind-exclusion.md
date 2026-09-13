# Managed retarget and rewind exclusion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent existing retarget and rewind owners from mutating identity-managed sources, graph, memory, state or Git until their authenticated managed transition protocol is integrated.

**Architecture:** Extend the reviewed negative ownership query to support a real selected spec without a run selector, reuse authority-presence checks, and place negative admission at each existing mutation owner before its first effect. Preserve legacy execution and existing lock/error/recovery ownership. This does not implement managed retarget or managed rewind.

**Tech Stack:** Existing IdentityStore query-only transactions, native lifecycle locks, native retarget/rewind coordinators, temporary Git repositories and existing fixture helpers.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no main mutation, global installation, stopped-smoke edits or live activation.
- IDs travel through interfaces as strings.
- Existing graph keys remain valid.
- Historical evidence is retained, not relabeled as proof of the new content.
- Identity failures cannot become quality debt or banzai waivers.
- Agents propose content and edits; they do not allocate IDs, mutate the ledger, or certify publication.
- Preserve existing native legacy behavior, lock ordering, exception families and recovery protocols outside the explicit negative admission.
- Negative ownership observation is not an enrollment lease, full history audit, positive managed authority or no-witness reconstruction after all ownership evidence is removed.

---

### Task 1: exclude managed ownership from native retarget and rewind effects

**Files:** Modify `src/harness/element_identity_store.py`, `src/harness/element_identity_legacy_guard.py`, `src/echelon/spec_retarget.py`, `src/echelon/spec_retarget_recovery.py`, `src/echelon/rewind.py`, `src/echelon/cli.py`, and `docs/element-identity-storage.md`; create `tests/unit/test_managed_retarget_rewind_exclusion.py`. Existing test modules remain unchanged. No new controller, schema, source/run transition, journal/publication protocol, state admission, prose, graph/miner or other production changes without root escalation. Root owns plan/brief/progress; no subagents.

**Store interface:** Retain `IdentityStore.require_unmanaged_execution(*, spec_id: str | None, run_ids: tuple[str, ...]) -> None`. Extend only the empty exact-tuple case: `run_ids=()` is permitted when spec_id is valid and non-None. Both spec_id=None and run_ids=() still reject before a transaction. Preserve all existing strict element types, duplicate rules, query-only single transaction, indexed retained matching-owner and global orphan-registration checks, bounded no-chain error and BaseException behavior. No fabricated run selector, new schema, full child-history scan, all-spec scan or allowance based on decoded ownership payload validity. Matching row presence remains enough to refuse.

**New guard interface**, in the existing focused guard module:

```python
def require_legacy_identity_spec(*, project_root: Path, spec_id: str) -> None:
    # Validate the real exact spec identifier, then observe only existing authority.
    # No initialization or live source/state inference.
```

Use the existing text validator for spec_id before authority access. Share a private authority-presence/open helper with require_legacy_identity_execution: lstat `.echelon` before its identity child, truly absent parent/child permits legacy, present symlink/non-directory parent refuses, present leaf is passed to existing IdentityStore.open which refuses damaged/missing parts. Preserve existing execution guard order and monkeypatch seams. The new guard calls the reviewed query with spec_id and empty run tuple; matching managed spec or global orphan refuses, unrelated valid legacy spec proceeds. All ordinary errors raise `IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` outside the handler with no cause/context; existing constant is `identity authority does not permit legacy execution`. Other BaseException propagation stays native. Do not resolve filesystem aliases or derive a spec ID from Markdown.

**Retarget owners:** Keep preview-only `prepare_spec_retarget(confirm=False)` behavior unchanged. In each of `_apply_retarget`, `_adopt_prepared_retarget`, `_resume_existing_retarget`, after existing spec/Phase-A/baseline-run leases and the existing under-lock preflight revalidation, guard the exact selected canonical spec independently from original runtime state, and guard the actual baseline run directory with freshly read native state. Resume additionally guards the actual resolved active replacement run and its freshly read state before either rebuilding/finalizing early return or callback/invalidation. Use the already resolved native spec/run identities; do not replace original state fields to hide a second witness. A small private local helper may share this composition and error translation:

```python
try:
    require_legacy_identity_spec(project_root=root, spec_id=selected_spec_id)
    require_legacy_identity_execution(project_root=root, run_dir=run_dir, state=state)
    return
except IdentityStoreError:
    pass
raise RetargetEligibilityError(LEGACY_IDENTITY_EXECUTION_BLOCKED)
```

Place rejection before append_prepared_revision, checkpoint creation/callback, replacement bootstrap, memory purge, graph/artifact invalidation, state/failure recording, active pointer changes and provider dispatch. Keep it outside mutation failure handlers so rejection itself cannot write a failed revision or state. Matching ownership in physical run name, original declared run, original claimed spec, or separately selected spec must refuse even if managed_identity metadata was removed. Presence of managed_identity with any value also refuses even without ledger. Unrelated initialized authority permits the unchanged native legacy path. Preserve busy-lease precedence and lock release. This instant observation does not prevent concurrent enrollment after admission.

**Retarget recovery:** `_require_recovery_revision` is not purely read-only: its captured-receipt reconciliation can advance history. Insert negative admission after its existing checkpoint/revision/runtime identity checks but before `raw_graph` reconciliation or any advance. Guard the exact checkpoint spec and the validated replacement_state at its actual retained run path. Also guard the revision's actual baseline run path using its existing state when present; if state.json is truly absent, an empty state is only a negative-query carrier for that actual persisted run ID, never reconstructed managed authority. Validate a present optional baseline state with the existing regular-file/read semantics, without creating run directories or changing state. A dangling symlink, nonregular or unreadable/malformed present state cannot be treated as absent. Reuse a private helper if needed; do not duplicate recovery revision parsing or change the existing accepted dict contract (the annotated Mapping already validates exact dict). Translate ordinary admission/optional-state-read errors to `RetargetRecoveryError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` outside their handler. Preserve BaseException and keep this gate before recovery's mutation/failure-recording try block. This also protects `verified_committed_retarget_recovery` and resume paths that call `_require_recovery_revision`; do not add another recovery writer.

**Rewind:** In public `_cmd_rewind`, after existing leases and fresh locked SquadStateStore.load, call both the selected-spec and original-run execution guards before failed-gate authority, retarget recovery verification, prepare_rewind, ledger trimming, cleanup, state CAS or any completion banner. Preserve earlier read-only syntax/checkpoint validation and busy-lease precedence. Guard this command regardless of --confirm: its native same-head path can return applied=True and proceed to state effects even for a nominal preview. Do not fix or otherwise alter that unrelated legacy behavior in this task. Translate admission failure to the existing handled RewindError constant, so CLI exits unsuccessfully and prints no completion.

Also protect standalone `rewind.prepare_rewind(confirm=True)` using the real resolved spec directory name and independently checkpoint.spec_id before its same-head success return, backup creation, recovery-owned dirty-file discard or Git reset. Keep confirm=False native library behavior unchanged; it performs no effects itself. No current-run guessing or filesystem scan in this lower-level API. This library check cannot detect a declaration that is not provided and has no retained ledger witness; the CLI's actual-state guard handles that context. Preserve native earlier validation and nonmanaged retry/no-op behavior.

**First RED:** Build a genuine temporary retarget CLI workspace using the existing native fixture pattern in test_cli_spec_retarget, initialize and enroll the real selected spec/baseline run through actual source-context/managed APIs, and put the returned managed record into its actual state. Use native `_build_retarget_preview`/prepare path and real leases. Install only an effect-boundary tripwire on `append_prepared_revision_from_preview`; it must record entry and fail if reached. Snapshot canonical/run files, identity SQL, current pointer, Git HEAD/refs/index/object inventory after enrollment and before invocation. Name `test_managed_retarget_rejects_before_first_durable_effect`:

```python
with pytest.raises(RetargetEligibilityError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
    prepare_spec_retarget(root, "001-demo", ("apps/web",), confirm=True)
assert effects == []
assert after_snapshot == before_snapshot
```

The actual initial RED must reach that forbidden effect, not fail due to a dirty enrollment fixture, malformed managed registration or lock self-deadlock. Keep identity/run runtime fixture files out of selected-spec dirty checks; follow actual existing native enrollment/source-manifest APIs. No actual backend/provider or destructive operation outside the temporary test repository.

- [ ] Read scoped native implementations and existing tests; add the first test and run before production edits with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_retarget_rewind_exclusion.py::test_managed_retarget_rejects_before_first_durable_effect -q` from this worktree. Notify root of actual RED/fixture corrections.
- [ ] Implement the query extension and guard extraction/new API, then all named owner placements; rerun first test to GREEN. Use apply_patch. Preserve root administrative files and unrelated worker changes.
- [ ] Test store spec-only queries against actual managed/unmanaged and damaged matching/orphan rows, unopened/missing/damaged authority, exact invalid identifiers/tuple rules, SQL state equality, query-only transaction count and indexed access without child history. Reuse existing comprehensive guard matrix rather than duplicating it; add scoped new-spec guard exact input/error/no-chain/process-control tests and confirm old execution behavior unchanged.
- [ ] Exercise each actual retarget mutation branch: fresh apply, prepared checkpoint adoption, active invalidation resume, and rebuilding/finalizing return. Use real existing revision/checkpoint fixtures and selector/lease code, not fake previews or fake guards. Matrix managed record present/removed/malformed, real retained selected spec versus baseline/active physical or declared run ownership, invalid authority, unrelated valid legacy authority, and guided/semi/banzai native modes. Rejection must precede every first effect/callback and leave SQL, history, state, stages, pointer, source/graph bytes and Git unchanged. Prove leases released and busy precedence with existing bounded native patterns; no long sleeps or lease reacquisition within the same thread.
- [ ] Exercise recovery admission with actual authenticated native revision/checkpoint/runtime fixtures, including captured receipts that would advance history inside `_require_recovery_revision`, already committed recovery, missing baseline state, present malformed/symlink baseline state and metadata-only baseline ownership with absent ledger. Assert no history advancement, reconstruction, directory creation, failure-state write, purge/refresh, graph mutation, recovery commit or pointer publication. Legacy compatible recovery remains covered by unchanged native suites; do not turn these tests into a second recovery implementation.
- [ ] Exercise `_cmd_rewind` with real state/checkpoint selection and native leases for ordinary and retarget checkpoints, same-head and moving-head cases, --confirm and nominal preview, all native autonomy modes and removed/malformed metadata. Assert unsuccessful CLI exit/constant/no completion output and no Git/source/state/ledger/pointer/failed-claim consumption. Use tripwires only at effect boundaries, not on the guarded owner itself. Test standalone confirmed prepare_rewind with a real Git repository and actual managed registration, including selected-directory versus checkpoint spec witnesses and no-op; native unmanaged preview/confirm controls remain unchanged. No actual external reset or mutation.
- [ ] Document exact guarded entry points, retained legacy compatibility and remaining positive managed transition/all-writer/graph-mining integration. Do not claim a complete writer perimeter, managed rewind/retarget support or concurrency lease.
- [ ] Self-review and run once the exact covering set: `tests/unit/test_managed_retarget_rewind_exclusion.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_cli_spec_retarget.py tests/unit/test_spec_retarget.py tests/unit/test_spec_retarget_recovery.py tests/unit/test_cli_rewind.py tests/unit/test_rewind.py -q` with the absolute pytest executable above. Confirm paths first. No full-unit/bare pytest, install, provider/backend, capacity benchmark or unchanged postcommit rerun. Later changes get named scoped checks with exact separately identified trees.
- [ ] Commit only scoped production/new tests/storage docs. Write the full report to the controller-authorized report path with all RED/GREEN/failure/fixture corrections, exact commands/results, implementation commit and staged tested tree, post-cover changes and limitations. Report-only commit is fine; root owns original-BASE independent review. No worker subagents.

## Remaining integration

This plan adds negative admission at the named native source-transition owners. It does not activate managed producers or publication, authorize rewind of durable identity history, bind a replacement managed run, guard every direct graph/memory/checkpoint writer, or change banzai policy. Those integrations and the final offline review/full-unit gate remain required before the explicit rollout checkpoint.
