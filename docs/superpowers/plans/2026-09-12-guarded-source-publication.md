# Guarded source publication implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Promote a sealed publication while checking retained complete selected sources under the existing descriptor-associated publication lock.

**Architecture:** Add an opt-in method on PreparedSquadPublication using the existing inspection scope and one shared promotion loop. A focused internal source-progress adapter compares observed source snapshots with original sources plus only the sealed progress; short controller callbacks can later prepare/finalize durable identity effects while the same publication owner remains held. Default publish remains compatible; no controller activates this method in this phase.

**Tech Stack:** Existing descriptor-safe publisher/inspection owners, source baseline codec, expected-source projection and selected-source fingerprint, POSIX file locks, immutable snapshots, real-process/fault tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- The canonical inputs still match the captured publication baseline.
- A pending publication blocks conflicting writes until reconciled.
- No live provider/controller activation, identity schema/head registration, graph/memory write, extra controller or lock. The existing publication owner remains the only promoter; source comparison is not semantic or namespace authority.

---

### Task 1: add opt-in descriptor-bound guarded source promotion

**Files:** Modify `src/harness/squad_publication.py` for the opt-in method/shared promotion loop/borrowed-root plumbing. Create `src/harness/squad_source_guard.py` for internal selected-source progress checks. Modify `src/harness/squad_source_projection.py` only to extract/share its existing pure selected-source transformation if needed, preserving its public initial guard and final-only API. Create `tests/unit/test_squad_source_guard.py`; document the opt-in boundary in `docs/element-identity-storage.md`. No controller, state, store, graph, memory, provider or prose changes. Root owns plan/ledger.

**Public interface on PreparedSquadPublication:**

```python
def publish_sources(
    self,
    initial: PublicationSourcesSnapshot,
    *,
    before_publish: Callable[[PublicationSourcesSnapshot], None] | None = None,
    after_publish: Callable[[PublicationSourcesSnapshot], None] | None = None,
    fault_hook: Callable[[int], None] | None = None,
) -> PublicationSourcesSnapshot: ...
```

The retained initial snapshot is validated first through the unchanged initial codec and final projection guard; no fabricated zero-prefix snapshot. Its source paths supply the exact selection. The controller must separately authenticate original capture, selection completeness, accepted namespace/context, scope and semantic review; a self-consistent caller snapshot is not authority. Removing a source from a caller-supplied self-consistent initial snapshot cannot be detected as an omitted dependency by this method alone. No fallback to legacy publish on validation or capability failure.

**One owner and shared loop:** Acquire `_project_inspection_scope` once, retaining its original project/root chain and expected-lock descriptor. Do not call public inspect/inspect_sources/publish/discard recursively under that lock. Capture current sealed operations and selected sources using existing private capture owners. Require exact original marker and all ordered operation action/target/preimage/postimage/postimage-byte bindings to match the newly verified seal. Initial original bytes stay retained even when current targets form a valid partial post-prefix. Preserve shared stage checks and the current legal global-prefix/no-op semantics.

Extract the existing publish promotion body into one private caller-owned helper shared by old publish and new publish_sources. Preserve old public signature, exception codes, fault-hook positions, durable retry of already-post targets, target order, stage verification, fsync, no-op/delete rules and final target check. Do not create a second promotion loop. New guarded calls must carry the borrowed retained project descriptor through target image reads, parent traversal/mutation and target-directory fsync. Narrow optional private helper arguments are allowed; default legacy callers retain their current behavior. A guarded helper must never reopen an unbound project pathname and assume it is the retained root. Never close the borrowed descriptor: duplicate only when an existing helper owns/closes its root fd. Preserve ancestor/symlink/regular-file checks and verify retained root/transaction bindings at each boundary. No root or ancestor drift is repaired.

**Source progress check:** The current sealed snapshot already authenticates a legal ordered target prefix. From the retained original source observations, apply exactly the sealed postimages for that prefix using the shared pure source transformation, retaining all other bytes, modes, paths, empty directories and absences. Compare the complete selected manifest to the actual freshly captured manifest; no whole-tree exemption, Markdown-only scan, target-only check, hash-from-current substitution or silent selection expansion. Exact explicit-file selections and all unbound hidden/binary tree members remain protected. For already-post no-op operations, original and proposed images are equal; they grant no extra membership changes.

The only additional intermediate shape allowed beyond a completed-operation prefix is a parent-directory creation prefix of the next not-yet-post **write** operation: original-absent directory ancestors of that one target, in a contiguous ancestor chain, each at existing PUBLICATION_DIRECTORY_MODE. This accounts for interruption after mkdir/chmod but before file replacement. It cannot grant files, siblings, directories for later operations, changed existing directory modes, or relaxed path-kind rules. A partial noncanonical mkdir mode, unaccounted temporary file, stage damage or unrelated source change fails closed; do not delete/repair those inputs. This method resumes authenticated operation/allowed-directory prefixes, not every arbitrary interrupted filesystem state. No successful completion may be returned for an unclassified state.

Capture and validate sources before promotion, after every fault-hook boundary/before each next operation, and after each operation/final hook. Short capture scopes may be refreshed to account for owned changes, while the original root/lock owner and sealed stage descriptors remain held. Existing inspection exit checks must still validate each capture before it is trusted. Sources observed during a callback retain their normal inspection pins until the callback returns and pass exit verification before proceeding. Do not exempt captured trees because a target lives inside them. Return a detached final snapshot only after the complete expected-final fingerprint, targets, source capture, original root and seal pass final validation. This provides checked observation boundaries under a cooperating publisher lock, not a claim to detect every transient external mutation that is restored between observations.

**Callbacks:** Validate non-None callbacks are callable before any promotion. Invoke before_publish once per invocation only after first current-seal/source-progress validation; revalidate after it before mutation. Invoke after_publish once per invocation only after full postimage/source validation, still under the same lock, with the actual final snapshot; revalidate after it before successful return. Exact retries may invoke both again, so future owner effects must be independently idempotent. They are trusted short controller hooks: no providers, lock recursion, broad filesystem writes or long work. Callback exceptions propagate unchanged (including authority failures); this is not an untrusted-input normalization boundary. Before-callback failure promotes nothing; after-callback failure may leave all files published but never reports success. Fault hooks retain their existing bounded publish_io behavior. The method neither prepares/releases identity journals itself nor discards recovery materials; caller-owned pending intents remain the future completion owner's duty.

Malformed supplied snapshot/selection/callback shape uses PublicationError("manifest_invalid"); source/seal association or progress mismatch uses target_drift or existing stage errors as appropriate. Preserve BaseException propagation/resource cleanup and don't catch errors into a success return. No new wire format or durable sidecar file.

**Required first real regression:**

```python
def test_changed_unbound_evidence_blocks_before_any_promotion(tmp_path):
    from pathlib import Path
    from harness.squad_publication import PublicationError, SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    target = project / "specs/unknowns.md"
    target.write_bytes(b"# Unknowns\n## U-001: Existing\nBody\n")
    evidence = project / "specs/evidence.md"
    evidence.write_bytes(b"U-001: retained evidence\n")
    transaction = SquadPublicationTransaction.begin(project, squad, "3" * 32)
    stage = transaction.build_path("unknowns.md")
    stage.write_bytes(b"# Unknowns\n## U-001: Existing\nRevised body\n")
    relative = Path("specs/unknowns.md")
    transaction.add_write(relative, stage, owned_paths={relative})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert next(f.content for f in initial.trees[0].files if f.path.endswith("evidence.md")) == b"U-001: retained evidence\n"
    evidence.write_bytes(b"changed dependency\n")
    before_calls = []
    with pytest.raises(PublicationError, match="^target_drift$"):
        prepared.publish_sources(initial, before_publish=before_calls.append)
    assert before_calls == []
    assert target.read_bytes() == b"# Unknowns\n## U-001: Existing\nBody\n"
    assert evidence.read_bytes() == b"changed dependency\n"
```

Use the established secure-POSIX capability check only for tests with real capture/mutation. The actual first capture must succeed before the missing method raises the RED AttributeError instead of expected PublicationError; notify root before production edits. No mocked successful snapshots or fake callback receipts.

- [ ] Obtain first actual RED, implement minimal opt-in/shared-owner path and run focused GREEN.
- [ ] Exercise real writes/deletes/empty/no-op/mode-only/shared-stage operations, complete hidden/binary dependencies, explicit external files and absences, nested new directories/restrictive umask, unchanged existing modes, and immutable returned original/final snapshots. Compare final actual manifest independently to public expected-final projection and assert concrete bytes/modes/member sets.
- [ ] Reject source content/mode/membership/directory changes, observed-capture selection mismatches against initial, marker/operation/stage mismatches, malformed inputs and impossible projected path kinds before first promotion where observable. Reject fresh drift introduced by before callback/fault hooks and after callback/final hook; no success, no discarded stage or repaired dependency. Assert exact side effects/remaining prefix after failures. Synthetic internal-capture damage is not a proof that supplied initial selection completeness is authenticated.
- [ ] Real interrupted two-target publication using fault hook, close/reload prepared object, preserve original source bytes, retry from legal prefix to exact final result, then exact successful retry. Exercise intermediate newly created directory prefixes of next write and reject unrelated/later-operation/sibling/non0755 directory additions. Explicitly distinguish manually constructed interruption states from actual injected publisher faults in report.
- [ ] Prove one existing publication lock acquisition and descriptor association with real separate-process exclusion, no nested lock, and bounded lock-order violation controls. Reuse established spawn/event worker patterns; no repeated/high-count race loop. Inject original root swap/transient root acquisition replacement and target-ancestor/stage replacement at named boundaries; guarded mutations must not follow a substituted root. Verify borrowed descriptors remain open for owner and owned resources close on callback/fault/capture failures.
- [ ] Callback ordering/once-per-invocation, failure propagation, retry repetition, and source revalidation must be checked against real publication state; no provider/store/graph effects added. Verify legacy publish remains compatible through its existing tests rather than duplicating them.
- [ ] Self-review the sole promotion loop, root-descriptor plumbing, full selected-source comparison and precise partial-state allowance. Run once final covering modules: new tests/unit/test_squad_source_guard.py, tests/unit/test_squad_source_projection.py, tests/unit/test_squad_source_manifest.py, tests/unit/test_squad_publication_sources.py, tests/unit/test_squad_publication_inspection.py, tests/unit/test_squad_publication.py. No full/million/live/provider/postcommit repeats. Document limitations, actual diffcheck, commit task files and full report. Root supplies independent review.

## Remaining integration

Callbacks do not authenticate managed runs, source heads, identity claims, semantic review, graph results or completion state. Those require a closed versioned bundle and durable identity intent under existing SquadController completion ownership, plus explicit producer scoping and feature snapshots. Unclassified filesystem damage must remain blocked with recovery material retained. No new live activation, retarget policy or accepted-head schema is selected by this plan.
