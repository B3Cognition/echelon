# Managed spec memory and evidence exclusion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude retained identity-managed specs from six direct legacy memory/evidence mutation owners until their managed publication protocol is integrated.

**Architecture:** Reuse the reviewed selected-spec negative authority guard before adapter acquisition, cleanup, source publication and successful retarget-memory receipts. Keep native read-only audits and unrelated legacy commands unchanged. This closes named bypasses, not the whole writer perimeter or enrollment race.

**Tech Stack:** Existing IdentityStore and legacy guard, native canonical/evidence loaders, MemPalace adapters/miners, temporary local collection doubles and real on-disk identity registration.

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

### Task 1: exclude managed specs from direct legacy memory and evidence effects

**Files:** Modify `src/echelon/mempalace_requirements.py`, `src/echelon/mempalace_audit.py`, `src/echelon/mempalace_spec_evidence.py`, `src/echelon/mempalace_retarget.py`, and `docs/element-identity-storage.md`; create `tests/unit/test_managed_spec_memory_exclusion.py`. Existing tests remain unchanged. No store/guard/schema/controller/provider/prose/graph/RE-writer or publication protocol changes. Root owns plan/brief/progress; no worker subagents.

**Consumes:** `harness.element_identity_legacy_guard.require_legacy_identity_spec(*, project_root: Path, spec_id: str) -> None`, `LEGACY_IDENTITY_EXECUTION_BLOCKED = "identity authority does not permit legacy execution"`, and `IdentityStoreError`. Existing guard validates exact string IDs, observes only existing authority, rejects retained matching spec rows and orphan genesis, and bounds ordinary errors outside handlers. No authority initialization, managed registration, runtime inference, fake run ID or document-derived counter is permitted in production.

**Shared translation:** Add a small private helper in `mempalace_requirements.py`, reused by audit/evidence owners (which already depend on that module):

```python
def _require_legacy_spec_memory(
    project_root: Path, *, spec_id: str, resolved_spec_id: str | None = None,
) -> None:
    try:
        require_legacy_identity_spec(project_root=project_root, spec_id=spec_id)
        if resolved_spec_id is not None and resolved_spec_id != spec_id:
            require_legacy_identity_spec(project_root=project_root, spec_id=resolved_spec_id)
        return None
    except IdentityStoreError:
        pass
    raise SpecMemoryError(LEGACY_IDENTITY_EXECUTION_BLOCKED)
```

The optional second selector is only a second actual directory identity already selected/resolved by that owner, not an alias search or normalized replacement of the first witness. Keep both when they differ. Adapter `run_id` values such as `manual`, `cleanup`, or `retarget-finalize` are native provenance labels, not actual runtime ownership witnesses; never query them as managed runs or scan current run state. Exceptions raised by the real guard are bounded; preserve its other BaseException propagation. Retarget owners use a local corresponding translation to `RetargetMemoryError` directly from the shared identity guard, outside any existing failure/receipt handler. Retarget identity failure has `receipt is None`, not pass/fail/not_applicable authority.

**Exact six owners and placements:**

1. `mine_spec_requirements`: keep native selector resolution and canonical snapshot loading first. Before the adapter-construction try, guard actual selected `spec_dir.name` and independently `snapshot.spec_id` (physical canonical identity). No adapter acquisition, mine, support mine, report downgrade or memory mutation on rejection.
2. `cleanup_stale_spec_memory`: after native resolve/snapshot, before adapter creation, guard selected name and snapshot spec ID. No planning/get/delete/report receipt on rejection.
3. `mine_spec_evidence_memory`: preserve native evidence snapshot loading/landed policy and spec resolution, then guard selected directory name and independently `spec_dir.resolve().name` before adapter-construction try and before cleanup. Keep native zero-evidence behavior only for legacy selection; zero rows is not managed admission. No unavailable/partial downgrade of identity failure.
4. `publish_spec_evidence_package`: preserve native root/spec resolution, landed validation and verify-evidence source selection. Before `evidence_dir.mkdir` and every copy/hash/manifest write, guard selected name and actual resolved spec-directory name. No evidence directory creation or overwritten manifest on rejection. Keep source selection and legacy report wire unchanged. `publish_all_spec_evidence_packages` stays its existing per-spec iteration/reporting owner: the guarded leaf reports a bounded SpecMemoryError through its existing failure aggregation; other valid legacy specs may still publish. No all-or-nothing batch transaction, global managed scan or top-level success for a rejected package.
5. `purge_retarget_spec_memory`: after existing `_require_spec_id` validation, guard its exact checked ID before `_configured_mempalace_wing`, the not_applicable receipt, adapter acquisition, scans or delete. Raise bounded `RetargetMemoryError` outside its handler with no cause/context or receipt. Native malformed selector validation still precedes admission.
6. `refresh_retarget_spec_memory`: preserve native canonical resolved-path/spec validation. Guard that actual resolved `spec_id` and, if the input selected directory has a different nonempty name, its actual `spec_dir.name` before config/not_applicable receipt, adapter creation, mine/cleanup/audit and durable report-set recovery/publication. Do not infer a selector from an arbitrary ancestor or replace the existing canonical-path validation. Keep all existing report transaction/receipt/recovery logic unchanged.

Only the named mutation owners receive admission. Leave `audit_spec_memory`, `audit_spec_evidence_memory`, both captured audit APIs, adapter factories/planning APIs, `mine_re_memory` and generic direct collection/miner helpers unchanged. Read-only audits remain available for diagnosis and captured composition; passing those audits does not admit legacy writes. These selected-spec guards do not see metadata-only managed declarations if all durable spec ownership witnesses are absent, do not pin enrollment, and do not cover an upstream command's earlier independent effects. Document those limits explicitly.

**First RED:** Use real temporary native evidence workspace content from `tests.unit.test_mempalace_spec_evidence.write_evidence_workspace` and actual IdentityStore initialization/source capture/source registration/managed genesis for spec `003-demo` in a separate empty run-local tree. The existing canonical fixture may remain unchanged: this test proves retained spec ownership, not accepted-source equality. Do not enroll a nonempty genesis or rewrite the genesis contract. Use the real selector/snapshot/landed path. Tripwire only at `create_spec_evidence_memory_adapter`, which is the earliest backend acquisition boundary; no fake guard or fake owner. Snapshot every local path/type/file/symlink and identity SQL after setup. Name the test `test_managed_evidence_mining_rejects_before_adapter_acquisition`:

```python
with pytest.raises(SpecMemoryError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
    mine_spec_evidence_memory(root, "003-demo", run_id="manual")
assert effects == []
assert snapshot(root) == before
```

The failing preimplementation attempt must reach the adapter tripwire, not fail because enrollment, lifecycle, selector or fixture setup is invalid. No external palace/backend access: real adapter/miner behavior is allowed only with test-local storage.

- [ ] Read scoped owners, native test fixtures and shared guard contracts. Add first test and run before production edits with `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_spec_memory_exclusion.py::test_managed_evidence_mining_rejects_before_adapter_acquisition -q` from the existing worktree. Notify root of actual RED and any fixture correction.
- [ ] Implement shared translation plus six placements with apply_patch; rerun the exact first test to GREEN. Keep native read ordering and errors before the specified gate, all ordinary rejection raised outside handlers, no chaining or successful receipt/downgrade.
- [ ] Exercise every named owner with actual retained selected-spec registration, no runtime metadata, malformed matching ownership payload, orphan genesis and present damaged authority; use real store/guard and selectors. Reuse existing guard fixtures/matrix selectively rather than repeat all storage tests. Include truly absent authority (no initialization), valid unrelated authority, configured/no-config retarget cases, zero-evidence cases and actual name/path/numeric selectors. Alias tests must independently catch managed selected name and managed physical canonical target for native supported symlink selectors, without changing unrelated legacy alias behavior. Verify exact bounded exception type/message/cause/context/receipt and unchanged local files/directories/SQL. Effects must be observable tripwires on acquisition/mutation boundaries, never patched guards or owners.
- [ ] Prove direct evidence publication refuses before mkdir/copy/manifest even with an existing package; mixed managed/legacy `publish_all_spec_evidence_packages` returns native partial/failure counts with no managed mutation while a real legacy package is published. Use genuine native verify-source discovery fixtures; no mocked selection.
- [ ] Include native legacy positive controls for real requirement/evidence mining and stale cleanup using local collection doubles at the storage seam, actual adapter/planner/miner wherever practical; preserve old keys/rows/statuses. Include native retarget no-config not_applicable controls and unchanged scoped retarget suites for full report transaction behavior. Managed no-config still refuses before receipt. Test unrelated malformed selector/landed/source errors retain native precedence. No identity error is folded into partial/unavailable/pass/not_applicable.
- [ ] Test translation's ordinary failure and process-control behavior at the direct shared guard seam, plus at least one real malformed-authority rejection; KeyboardInterrupt, GeneratorExit and SystemExit remain the underlying guard's native propagation, not report conversion. Do not broaden production catch types to satisfy test doubles that violate the consumed contract.
- [ ] Document exact six owners, no global RE blockade, native per-spec batch partial semantics, alias witnesses, provenance run labels versus runtime ownership, and remaining direct graph/CLI/low-level writer and positive managed publication integration. No complete perimeter or live success claim.
- [ ] Self-review and run once these exact seven modules with the absolute pytest executable: `tests/unit/test_managed_spec_memory_exclusion.py tests/unit/test_mempalace_requirements.py tests/unit/test_mempalace_audit.py tests/unit/test_mempalace_spec_evidence.py tests/unit/test_mempalace_retarget.py tests/unit/test_mempalace_captured_audit.py tests/unit/test_mempalace_captured_artifact_audit.py -q`. Confirm paths first. No full-unit/bare pytest, capacity benchmark, global install, provider/backend or unchanged postcommit rerun. Any later amendment gets named scoped tests and a separately recorded tested tree.
- [ ] Commit only scoped production/new tests/storage docs; full report at controller-authorized path records all test attempts, exact commands/results, fixture corrections, tested staged tree, implementation commit, post-cover changes and limitations. Report-only commit allowed. Root owns independent original-BASE review; no worker subagents or root administrative staging.

## Remaining integration

This is negative admission for six direct spec memory/evidence owners, not managed mining/publication, a captured multi-domain storage/config/catalog observation, aggregate graph ownership, positive runtime/producer/semantic/bounded-repair integration or complete writer coverage. All remain required before final offline full-unit/review and the explicit rollout checkpoint.
