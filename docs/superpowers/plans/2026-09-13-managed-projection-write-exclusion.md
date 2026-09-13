# Managed projection write exclusion implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refuse legacy spec graph/report commands and rootful workspace graph writes when retained managed ownership would otherwise bypass the integrated negative boundaries.

**Architecture:** Add an explicit any-managed-workspace absence query and guard, reuse selected-spec admission at existing CLI output ownership, and guard aggregate refresh before its first upstream mutation. Keep diagnostic reads, native output serializers and unrelated legacy behavior unchanged. This is not positive managed projection or a complete arbitrary-file writer sandbox.

**Tech Stack:** Existing IdentityStore query-only transactions, native spec/workspace graphs and Typer command ownership, temporary filesystem/SQLite/Git fixtures.

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

### Task 1: exclude managed ownership from named projection output owners

**Fixture amendment (Ruling 45):** Permit a real canonical directory/spec.md setup only for the writable `status == "pass"` parameter of `tests/unit/test_cli_spec_memory.py::test_spec_memory_audit_write_respects_availability`. That synthetic fixture returns a pass report without any source file; native audit would already require a real spec, and new selected-spec admission cannot trust the mocked report as a substitute for selection. Preserve all mocks/assertions, leave unavailable case's source absent, and retain mandatory production resolve/admission. No production fallback or admission stub. Include this narrow existing-test amendment in the initial eight-module covering tree; document the statically inspected fixture conflict (no executed pre-correction failure) and actual focused correction results. Other existing-test edits require the narrow authorization below.

**Error-ordering amendment (Ruling 46):** In `tests/unit/test_workspace_graph_audit.py::test_write_workspace_audit_rejects_earlier_symlinked_ancestor`, update only the expected exception/message to `WorkspaceGraphError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` and necessary imports. Preserve the actual symlink fixture, temporary-file tripwire and unchanged external-byte assertions. The malformed `.echelon` parent is rejected by required identity admission before native output-path preparation; retain that ordering and no-write guarantee. No production change is authorized by this amendment. The initial eight-module cover is already 264 passed/1 failed; run the amended workspace_graph_audit module only and record its exact amended tree, not another unchanged eight-module cover.

**Files:** Modify `src/harness/element_identity_store.py`, `src/harness/element_identity_legacy_guard.py`, `src/echelon/cli_app.py`, `src/echelon/workspace_graph.py`, `src/echelon/workspace_graph_audit.py`, `src/echelon/workspace_graph_refresh.py`, and `docs/element-identity-storage.md`; create `tests/unit/test_managed_projection_write_exclusion.py`. Existing tests unchanged except the exact Ruling45 and Ruling46 amendments above. No schema, graph wire/key, renderer, managed publisher, source/run transition, counter, RE writer, provider or prose changes. Root owns plan/brief/ledger; no worker children. Start only after previous memory/evidence phase is reviewed complete.

**New query interface:** `IdentityStore.require_unmanaged_workspace(self) -> None`. In one existing transaction set `PRAGMA query_only=ON`, then refuse if either (a) any row exists in managed_identity_specs, or (b) any operations row with method='managed_identity' exists. Use bounded SELECT 1 ... LIMIT 1 observations, with the existing managed_identity_operations partial index for (b). A row's presence is enough; do not decode payloads or enumerate canonical specs. This catches damaged retained ownership and registration-only orphans; no managed canonical directory is required. Existing source contexts, imported IDs or allocations without managed enrollment do not by themselves block legacy workspace projection. No full history scan, migration, new index or mutation. Ordinary failures become `IdentityStoreError("invalid unmanaged workspace authority or request")` raised outside handlers without cause/context; other BaseException values propagate.

```python
def require_unmanaged_workspace(self) -> None:
    try:
        with self._transaction() as connection:
            connection.execute("PRAGMA query_only=ON")
            if connection.execute("SELECT 1 FROM managed_identity_specs LIMIT 1").fetchone() is not None:
                raise ValueError("managed workspace ownership is retained")
            if connection.execute(
                "SELECT 1 FROM operations INDEXED BY managed_identity_operations "
                "WHERE method='managed_identity' LIMIT 1"
            ).fetchone() is not None:
                raise ValueError("managed registration is retained")
        return None
    except Exception:
        pass
    raise IdentityStoreError("invalid unmanaged workspace authority or request")
```

**New guard interface:** `require_legacy_identity_workspace(*, project_root: Path) -> None` in the existing legacy guard module. Reuse its private `.echelon` parent-first lstat and existing-authority open observation. No selector fabrication, Markdown scan, namespace initialization or current-run inference. The private helper's previously unused no-spec/no-run selection can explicitly invoke the new workspace query; the existing spec/run public entry points must retain their exact input and order semantics. Workspace public wrapper catches ordinary Exception and raises `IdentityStoreError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` outside the handler, preserving other BaseException propagation. Keep all existing absent-parent/child compatibility and malformed-present parent/leaf refusal. Existing spec guard still calls require_unmanaged_execution(spec_id=..., run_ids=()), not the global query. Existing legacy runs/spec commands remain usable beside an unrelated managed spec; only aggregate workspace projection is global.

**Workspace exception translator:** Add private `_require_legacy_workspace_projection(project_root: Path) -> None` in workspace_graph.py, calling the new workspace guard and translating only IdentityStoreError to `WorkspaceGraphError(LEGACY_IDENTITY_EXECUTION_BLOCKED)` outside the handler. workspace_graph_audit and workspace_graph_refresh already depend on workspace_graph, so reuse that helper without a dependency cycle. Do not fold identity refusal into an outcome, graph status, partial report or backend unavailable result.

**Exact aggregate owners:**

1. `write_workspace_graph(graph, project_root)`: guard before output-path creation, rendering or byte publication. Actual root argument supplies authority; no graph property supplies permission.
2. `write_workspace_graph_audit(report, project_root)`: same guard before parent creation, rendering/temp file/replace.
3. `refresh_workspace_graph(project_root, write=True)`: after existing root resolution, before `_refresh_re_memory`, canonical discovery, per-spec refresh, output commits or final graph/audit writes. Put it outside per-domain exception-to-outcome handlers. Write=False remains native read-only preview with no ownership gate. Repeated negative checks at later direct writers are observations, not a lease or atomic cross-domain proof. Existing CLI workspace build/audit/refresh already catch WorkspaceGraphError; verify real handled failure/no successful output, without adding a parallel CLI guard.

**Spec output owners:** The prior phase provides `_require_legacy_spec_memory(project_root, *, spec_id, resolved_spec_id=None)` in mempalace_requirements and the original selected-spec identity guard. Reuse the private bounded SpecMemoryError helper, not a new allocator/admission path.

4. `_graph_output_commit(spec_dir, ...)` in cli_app.py: before constructing OwnedOutputCommit, guard actual selected `spec_dir.name` and independently actual `spec_dir.resolve().name` against `Path.cwd()`. Existing graph build/audit/refresh --write commands already route through this owner and catch RuntimeError/SpecMemoryError. Keep native read-only build/audit computation and errors before this gate; no changes to graph bytes or Git commit ownership.
5. `spec_memory_audit(..., write=True)` in cli_app.py: after native audit returns a report eligible for writing (`status != "unavailable"`), but before write_audit_reports, resolve the actual selected spec using the existing resolve_spec_dir and guard its name plus actual output `Path(report.spec_dir).resolve().name`. Put only the admission inside the existing SpecMemoryError handler; preserve the native write helper/error behavior itself. Write=False and unavailable/no-write paths remain native diagnostics. Mining/refresh reports are already behind guarded leaf owners from the previous phase; do not add duplicate paths there.

Native `write_spec_graph(graph, spec_dir)`, spec audit/report serializers and generic exact-byte/export output helpers lack a project-root admission contract. Leave them unchanged; they remain low-level trusted-caller output primitives, not a managed publication API. Do not invent roots by arbitrary ancestor walking, alter their signatures, or claim this task guards arbitrary Python/file access or every CLI --output destination. Standalone RE mining is not globally blocked. Positive captured identity projection, candidate publication and remaining source/checkpoint/runtime writers remain separate integration requirements.

**First RED:** Create a genuine empty run-local source tree for a managed spec absent from canonical `specs/` discovery, initialize IdentityStore and register actual source context/genesis using existing native helpers. No malformed state or fake authority. Invoke the real rootful refresh_workspace_graph(write=True) and tripwire only its first upstream effect boundary `_refresh_re_memory`; this is not the guarded aggregate owner. Snapshot all directories/files/symlinks and SQLite dump before invocation. Name the test `test_managed_workspace_refresh_rejects_before_upstream_refresh`:

```python
with pytest.raises(WorkspaceGraphError, match=LEGACY_IDENTITY_EXECUTION_BLOCKED):
    refresh_workspace_graph(root, write=True)
assert effects == []
assert snapshot(root) == before
```

Observe the tripwire reached before production edits; not a missing import or bad enrollment fixture. No real palace/backend/provider or external filesystem mutation.

- [ ] Read scoped owners/guard/store and relevant native fixtures. Add and run exact first RED using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_managed_projection_write_exclusion.py::test_managed_workspace_refresh_rejects_before_upstream_refresh -q` from this worktree. Notify root of actual result/corrections.
- [ ] Implement query/guard/translator and exact five owner placements with apply_patch; rerun first test to GREEN. Keep unrelated native code/semantics unchanged.
- [ ] Test query on actual managed rows, malformed matching payloads, registration-only orphan, valid allocation/import/source-only authority and empty authority. Assert one query-only transaction, SQL equality, bounded LIMIT observations and partial-index use for managed operations, with no child-history decode/scan. No new capacity benchmark. Test workspace guard absent parent/child versus malformed present parent/leaf and process-control/no-chain behavior, and confirm old spec/run entry behavior with unchanged existing guard suite.
- [ ] Exercise direct workspace graph and audit writers with actual native graph/report records and retained managed run-local ownership even when canonical directory is missing. Refuse before render/parent/temp/replace, leaving existing or absent output directory and source/SQL unchanged. Exercise aggregate refresh before upstream RE and all per-spec outputs, including managed and legacy members together. No caught per-domain partial success; actual CLI wrappers exit unsuccessfully. Use native local fixtures and tripwires at effect/storage seams, not patched guards or guarded owners.
- [ ] Exercise actual CLI graph build/audit/refresh --write routes before OwnedOutputCommit construction, and memory audit --write before report bytes; managed selected versus physical target witness, malformed authority and unrelated managed spec with actual legacy selection. Verify no source/graph/audit/Git/SQL changes and no completion output. Keep native supported alias behavior for unrelated legacy inputs; earlier native validation failure is safe. Read-only command/preview controls remain usable with managed ownership. Include native output-byte/key controls for unrelated legacy writes; mocks alone are not parity evidence.
- [ ] Test unavailable memory-audit no-write and native earlier selector/audit error paths without expanding production error handling. Exercise rootful workspace CLI catches with real guard failures, bounded constant and no successful summary. Preserve KeyboardInterrupt/GeneratorExit/SystemExit according to the consumed guard contract; no report conversion of those values in new helpers.
- [ ] Document exact owner coverage, workspace-global versus per-spec scope, absent-canonical ownership, no enrollment lease, low-level output primitives and remaining positive managed/source/runtime integration. No complete all-writer or live success claim.
- [ ] Self-review and run once exact eight-module cover with the absolute pytest executable: `tests/unit/test_managed_projection_write_exclusion.py tests/unit/test_element_identity_legacy_guard.py tests/unit/test_cli_graph.py tests/unit/test_cli_spec_memory.py tests/unit/test_cli_workspace_graph.py tests/unit/test_workspace_graph.py tests/unit/test_workspace_graph_audit.py tests/unit/test_workspace_graph_refresh.py -q`. Confirm paths first. No full-unit/bare pytest, backend/provider, install, capacity benchmark or unchanged postcommit rerun. Later amendment gets named scoped tests/exact amended tree.
- [ ] Commit only scoped code/new tests/storage docs. Full controller-authorized report includes every attempted command/result, actual RED/GREEN/fixture corrections, staged tested tree, implementation commit, post-cover changes and limitations. Report-only follow-up permitted; root owns administrative files and original-BASE review. No worker children.

## Remaining integration

These are negative boundaries for named legacy projection outputs, not managed graph/source acceptance, low-level arbitrary file-write confinement, concurrent enrollment serialization or positive runtime/producers/semantic repair/completion integration. Final offline whole-branch review/full-unit verification and explicit rollout authorization remain required.
