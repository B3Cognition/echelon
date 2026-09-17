# Managed context authentication implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Check an explicitly managed run's retained record against actual durable genesis and return its coherent accepted source context, without enabling any execution path.

**Architecture:** Add one opt-in read-only IdentityStore entry point that composes the existing managed-record validator, managed genesis reader and accepted-source reader under the existing single transaction owner. Independent caller-selected spec/run IDs are checked against the supplied record and durable genesis. No new schema, record format, source selection, classifier or transaction owner is needed.

**Tech Stack:** Existing SQLite IdentityStore, pure managed state record validator, managed/source store helpers, real registration/publication and query-only tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- No live enrollment or provider activation, schema change, implicit initialize/upgrade/import, lifecycle/publication write, graph/memory effect or semantic certification.
- Existing IdentityStore remains the database transaction owner. No state or publication locks are acquired under its transaction; no provider call or source filesystem capture occurs there.
- This check is required only for callers that already selected managed execution. It never returns a legacy fallback, classifies absent metadata as legacy, or claims to detect erased metadata without an independent runtime selection.

---

### Task 1: authenticate explicit managed context on one read-only transaction

**Files:** Modify `src/harness/element_identity_store.py` to add exactly the public entry below, and `src/harness/element_identity_managed_store.py` for a focused composition helper if needed. Create `tests/unit/test_element_identity_managed_context.py`. Document in `docs/element-identity-storage.md`. Do not alter schema, managed request codec, state writer/namespace, controller/executor/provider/CLI/startup production, source publication algorithm or role prose. Root owns plan/ledger. Source/managed tests can be consulted for real setup helpers, not copied wholesale or broadly rewritten.

**Interface:**

```python
def check_managed_context(self, *, spec_id: str, run_id: str,
                          record: object) -> dict:
    """Check explicit genesis ownership and observe its current source, read-only."""
```

Return a detached exact dict with exactly two keys, `managed_identity` and `source_context`. `managed_identity` is the existing exact ten-string genesis record. `source_context` is the existing full source receipt (version, namespace, spec/context/registration/operation identifiers, sequence and manifest payload/hash). No invented wire version or persisted receipt, renamed source fields, copying of current head values into genesis, source bytes or inode claim. The accepted head can be the initial sequence`0` or a later accepted publication; immutable genesis remains bound to the original source registration/hash.

Validate `spec_id` and `run_id` with the existing exact-string lifecycle text validator. Validate/detach `record` with `validate_managed_identity_record`; it must match those independently supplied spec/run identifiers exactly. Present malformed, missing/None, false, partial, unknown fields and every valid-but-different namespace/epoch/spec/run/context/path/operation/original source claim reject. Do not derive trusted selection from the untrusted record, stringify inputs, normalize published labels or fill missing values.

Use one existing `self._transaction()` with `PRAGMA query_only=ON`. Read actual retained genesis through `element_identity_managed_store.read`; absent genesis is an error, never a None/legacy return. Require full exact record equality. Read its context through the existing `element_identity_source_store.read` on the SAME connection, validate namespace/spec/context/registration association against the matched genesis, and return detached records. Reuse their existing integrity checks, including damaged source heads and orphan managed operations; do not duplicate source parsing, audit algorithms, schema validation or SQL ownership logic. The extra bounded current-source read performed inside existing genesis validation is acceptable; changing the existing managed reader's API just to remove it is not needed. A coherent single transaction matters; do not call the two public methods in separate transactions.

The public entry point normalizes ordinary input/helper/storage exceptions to `IdentityStoreError` with a short fixed message, no untrusted text or retained exception cause/context. Preserve BaseException. Raising after the handler is the existing new pure-validator pattern. Unknown damaged authority, missing files, changed handle namespace and unsupported old schemas reject through existing owners without initialize/upgrade/repair. No scans of entities, revisions, reservations, bindings or issue history are added; all managed/source reads retain their indexed scope. This is a read-only authority association check, not a full audit or proof that arbitrary child history is undamaged.

This method reads supplied record values, not state files. Callers must obtain/validate state before entering it, and must use independent selected spec/run IDs. It acquires no state lock, calls no state initializer/writer and performs no publication capture. It observes source metadata from the registry, not current files. Its returned head is a snapshot, not a reservation or guarantee of freshness after return; future publication must still CAS against that exact head and authenticate actual captured bytes. A pending publication does not invalidate coherent read-only observation: prepared retains the old head, applied retains the newly accepted head, released retains the same accepted head. No release, recovery or completion is certified by this method.

**First actual regression before production:** Define a capability-scoped secure-POSIX fixture locally for the real-capture tests. In `test_check_managed_context_uses_actual_genesis_and_initial_source`, create `runs/first/specs/demo` as an empty real tree, seal an empty `SquadPublicationTransaction`, jointly inspect that tree, call `snapshot_source_manifest`, initialize actual IdentityStore, register context`first-source` using operation`source-registration`, register actual managed genesis for spec`demo`/run`first` using operation`managed-registration`, then invoke the missing public entry. The real capture and registrations must succeed first; the expected RED is AttributeError for `check_managed_context`, not a fixture or import error. Minimal assertion tail:

```python
observed = authority.check_managed_context(spec_id="demo", run_id="first", record=genesis)
assert observed == {"managed_identity": genesis, "source_context": initial_source}
assert observed["managed_identity"] is not genesis
```

- [ ] Run the exact first test with the existing worktree pytest executable and notify root of actual RED before production. Keep pure input tests platform-independent; only real publication capture requires the capability fixture.
- [ ] Implement the small composition on the existing transaction/read helpers, no new transaction owner. Make the first test GREEN. Add closed-input tests and independently specified result shape, exact preserved values, detached nested manifest/result mutations, bounded exception/context and BaseException propagation.
- [ ] Exercise independently selected wrong spec/run, valid other-workspace/epoch records, forged original operation/path/source claim, missing genesis, orphan operation, damaged retained managed row, malformed record and valid legacy imported-but-unmanaged spec. Each rejects without new operations, enrollment, counter movement or source changes. Actual state-store initialization/load followed by this check demonstrates structurally valid caller metadata alone is insufficient; keep state reads outside the database transaction.
- [ ] Use real source-aware publication to check initial/prepared/applied/released observations, immutable original genesis after head advancement, exact old record accepted after later history and no state/source/identity side effects from checking. Preserve the existing journal semantics; accepted head observation is not release/completion. Test two contexts/specs so changing the supplied context cannot read another accepted source.
- [ ] Prove one query-only transaction via existing connection instrumentation around real store operations; a helper attempts an actual SQL write under this call and it must reject with unchanged database rows. A probe that switches the source after the check returns proves old returned data is detached and future calls see the new head, without claiming an after-return freshness guarantee. Do not create a public test hook.
- [ ] Reuse actual authorizer/index-plan testing patterns to prohibit identity child/history table reads while checking an established context containing mixed-family history. Named managed/source lookup plans remain indexed. Do not run a million-record test or full audit as a routine check.
- [ ] Verify actual missing database/marker, corrupt current authority and changed namespace on an existing handle fail without creating or repairing files. A frozen supported-old schema test may reuse the existing independent frozen-schema fixtures through a focused helper; open/check must not upgrade it. Do not classify total metadata deletion as legacy or add filesystem discovery heuristics. No source filesystem/stat reads beyond the existing authority access; source tree content can differ physically and the check still only reports the retained accepted snapshot, documented explicitly.
- [ ] Run the final covering set once: `tests/unit/test_element_identity_managed_context.py`, `tests/unit/test_element_identity_managed.py`, `tests/unit/test_element_identity_state.py`, `tests/unit/test_element_identity_source_store.py`, and `tests/unit/test_element_identity_publication.py`. No full-unit/controller/capacity/live-provider/install run. Report exact final code point; later fixes need covering evidence without relabeling the earlier suite.
- [ ] Self-review spec/run/namespace comparison, single transaction, copied records, original-versus-current source association and honest layer limits; document, diffcheck and commit only scoped code/tests/docs/report. Root supplies independent full original-base review after DONE.

## Remaining integration

Startup/dispatch/completion owners must still make the managed-versus-legacy selection independently of mutable provider output, detect removed metadata against durable authority, check current physical source scope and invoke the authenticated check before using its claims. Subsequent-run transitions, isolation, producer reservations, semantic assessment, coordinated source/identity/graph completion and bounded repair remain unimplemented integrations. No existing runtime caller invokes this method in this phase.
