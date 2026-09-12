# Task 1 implementation report

Base: `7f1b0218ddbef020c499314ef23783a976aad599`.
Root's task-only Ruling 23 clarification was read in full at `cf6440ef1fc16fab47d9a1fe1074881dba90c3b2`; the review base remains unchanged.
Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`.

## Implementation

- Added opt-in `PreparedSquadPublication.publish_sources` with retained original codec/final projection validation, exact current seal association, complete selected-source progress comparison, and trusted before/after callbacks.
- Extracted the existing publisher body into `_promote`, the sole promotion loop shared by legacy `publish` and guarded publication. Legacy lock ownership, operation order, hook positions, already-post durability, write/delete/no-op rules, stage verification and final target checks remain in place.
- Added optional borrowed project-descriptor plumbing for target images, parent traversal/mutation and target-directory fsync. Helpers duplicate borrowed roots when they own their descriptor and never close the original owner descriptor. Existing target ancestors are pinned for the whole guarded invocation; newly created/first traversed parents join that owner before temporary traversal descriptors close. No missing-entry or old membership pins are carried across authorized changes. Root/seal/target ancestor bindings are verified at observation and mutation boundaries.
- Added the private pure `_transform_selected_sources` extraction under the unchanged public initial guard/final-only projector. No fabricated initial snapshot, new wire format or durable sidecar is involved.
- Added exact canonical parent-prefix acceptance only for the next unfinished write. The complete manifest must equal one enumerated prefix; later parents, siblings, unknown temporary files, file additions and noncanonical modes remain blocked and retained.
- Added guarded-only stage-mode checks before callbacks, including already-post retries. Existing inspection intentionally reports desired sealed modes; its API and legacy behavior remain unchanged.
- Fixed cleanup of a newly opened directory on mkdir durability failure and registration order for duplicated parent pins when the following duplicate fails.
- Documented the opt-in boundary and deferred completion/identity authority in `docs/element-identity-storage.md`.

## Commands and actual TDD chronology

All pytest commands used `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from the worktree above. No standalone Python, installations, whole suite, capacity suite, live/provider commands or postcommit test repetition were run.

1. **Required first RED, before any production edit:**
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py::test_changed_unbound_evidence_blocks_before_any_promotion`
   Output: `1 failed in 0.17s`; real `inspect_sources(tree_paths=("specs",))` completed and the original evidence-byte assertion passed, then line 38 raised `AttributeError: 'PreparedSquadPublication' object has no attribute 'publish_sources'` instead of the expected `PublicationError("target_drift")`. Root was notified before production edits.
2. **Minimal implementation GREEN:**
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py`
   Output: `1 passed in 0.19s`.
3. Expanded real-state tests after the minimal implementation:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py`
   Output: `37 passed in 0.72s`. These additional tests were GREEN on their first run; this is not claimed as individual RED evidence for each case.
4. Focused legacy compatibility check:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_publication.py::test_postimage_verification_failure_retains_stage`
   Output: `1 failed in 0.35s`, because the existing `_target_image` wrapper received unexpected `project_fd=None`. Optional root kwargs are now omitted on the legacy call path. Same command afterward: `1 passed in 0.30s`.
5. Named boundary/process/resource checks:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k 'mkdir_fsync or replacements or single_retained or inversion'`
   Output: `2 failed, 7 passed, 37 deselected in 0.58s`. A real mkdir followed by injected directory-fsync failure leaked the newly opened directory descriptor; a root swap during callback was rejected as `stage_corrupt` by short capture pins before the root owner could report `target_drift`. Added descriptor cleanup and checked the original owner before short-scope exit verification. Same command afterward: `9 passed, 37 deselected in 0.50s`.
6. Association, omitted-selection limitation, and capture-failure checks:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k 'mismatch or omitted or capture_failure or empty_operation'`
   Output: `16 passed, 46 deselected in 0.31s`.
7. Stage-mode regression RED:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k stage_mode_damage`
   Output: `2 failed, 62 deselected in 0.28s`. Before publication, the callback had already run before write rejected stage mode; after publication an already-post retry incorrectly returned success. Guarded owner verification now compares retained stage mode with each sealed write mode. Same command afterward: `2 passed, 62 deselected in 0.20s`.
8. Parent-pin descriptor exhaustion:
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k parent_pin_descriptor`
   Initial injection hit regular-file verification instead of parent-pin duplication (`1 passed, 64 deselected in 0.21s`), so it did not prove the intended failure. The injection was narrowed to the named parent helper. Corrected RED: `1 failed, 64 deselected in 0.22s`, with an unclosed first duplicate after the second duplication failed. Immediate resource registration fixed it. GREEN: `1 passed, 64 deselected in 0.19s`.

9. **Ruling 23 target-ancestor lifetime RED, before strengthening production:**
   `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k identical_target_ancestor`
   Output: `2 failed, 69 deselected in 0.27s`; both existing target ancestors and publisher-created parents were actually renamed and replaced with a different-inode tree containing identical bytes/modes at fault position 1. Both incorrectly returned success. Root was notified before the strengthening edit. Existing target ancestors now join the original owner before capture; parent traversal registers new/first traversed parents on that same owner before closing temporary descriptors.
10. Strengthening/cleanup/process GREEN:
    `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k 'identical_target_ancestor or parent_pin_descriptor or mkdir_fsync or single_retained'`
    Output: `5 passed, 66 deselected in 0.46s`.
11. **Single final covering run after final production refactor:**
    `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py tests/unit/test_squad_source_projection.py tests/unit/test_squad_source_manifest.py tests/unit/test_squad_publication_sources.py tests/unit/test_squad_publication_inspection.py tests/unit/test_squad_publication.py`
    Output: `438 passed in 3.85s`; process exit 0, no warnings. The guard module contains 71 cases. This is the only six-module covering run. The unchanged legacy module is the compatibility evidence rather than a duplicated legacy suite.

The final production refactor removed the now-unneeded per-operation resource scope after target ancestor resources moved into the single original owner. Tests and docs include absent selected-root creation, missing secure capability without fallback, and out-of-order target rejection; these were covered in the final run.

## Evidence classification and limits

**Real captures and filesystem effects:** all baseline and final snapshots in guarded tests come from actual descriptor-safe captures. Byte, mode, membership, directory, hidden/binary, explicit-file and absence mutations are real filesystem edits. Callback order/failure tests inspect actual targets and retained stage files. Original and returned snapshots remain detached and immutable. Independent public expected-final comparisons are paired with literal concrete byte/mode/member assertions so a shared transformation error cannot alone satisfy final expectations.

**Actual injected publisher faults:** the two-target fault-hook interruption occurs after the first actual replacement and before the second; it is followed by dropping the prepared object, reopening from the sealed marker, finishing from the original bytes, and an exact successful retry. The mkdir test interrupts the actual publisher after mkdir/fchmod during directory fsync and retries its canonical partial directory state. Stage and ancestor swaps occur at named real-copy boundaries. Syscall/read failures are injected in real operations; no mocked successful snapshots or fabricated callback receipts are used.

**Manually constructed interruption states:** canonical directory depths and a completed first target are constructed directly on disk, as are noncanonical directory, unrelated/later-parent/sibling and unknown temporary-file cases. These prove classification of those states, not that every state was produced by a real process crash. No claim is made about arbitrary interrupted states or transient changes restored between observations.

**Synthetic internal damage:** the selection-mismatch test alters the result of one private real tree capture to an alternate absent-tree selection. It tests full selected-manifest comparison, not authenticity or completeness of the caller's initial selection. A separate real test removes an explicit dependency from a self-consistent supplied initial selection, changes that omitted file, and confirms the method cannot detect the omitted dependency.

**Lock and descriptor proof:** one instrumented real lock owner records the borrowed root descriptor. The real separate spawned publisher first attempts nonblocking acquisition, reports being blocked, remains blocked during the final callback, and publishes only after the guarded owner exits. Public inspect/publish/discard methods are forbidden during this guarded invocation. The mutation parent helper receives that same root descriptor; the owner descriptor stays open through lock exit and is closed after owner teardown. Root swap before lock acquisition and a transient replacement while acquiring the root descriptor are rejected. Root, target-ancestor and stage replacements at named boundaries do not publish into substituted target paths. Ruling 23 tests further prove that identical-content/mode replacement of existing or publisher-created target ancestors between operations is rejected with exactly the first target published and the second untouched. Descriptor inventories cover callback, BaseException, fault, capture and directory-creation failures. Lock inversion controls use the established lock-order assertion and then prove a fresh successful publication. This invocation-local association cannot authenticate inode identity from a serialized original across recovery calls; non-target read-only source directories remain governed by short checked captures.

**Static review claims:** sole-loop ownership, unchanged public projector guard, absence of recursive lock calls, all guarded target read/parent/fsync call-site root forwarding, and absence of controller/store/graph/memory/provider writes are code/diff review conclusions. Tests bound specific real fault points; they are not exhaustive scheduler or crash proofs. The existing publisher module is large; the implementation keeps the shared ownership logic there as required and isolates source progress comparison in the new small module.

## Self-review and scope

Reviewed the implementation diff and the complete new guard/tests. Found and fixed the two descriptor cleanup paths, optional legacy keyword compatibility, stage-mode validation timing and root-error precedence described above. Ruling 23 was explicitly clarified with root before implementation rather than inferred. The final loop uses the original owner for target ancestors with no per-operation disposal and no global absence/membership exemptions. `git diff --check` was run during self-review and immediately before the final covering run with no output and exit 0.

Only the task's source modules, test module, documentation and this report are intended for commit. Root-owned plans/ledgers, including the next-phase source-manifest-wire-validation plan, remain untouched. No child agents or reviewers were dispatched; root owns independent review.

The original capture, selected dependency completeness, namespace/context, semantic acceptance, managed-run authority and durable identity intent remain caller obligations. Callbacks may repeat on exact retry and must be independently idempotent. After-callback failure can leave all target files published without successful return. Recovery material is retained. This task does not activate any live integration.
