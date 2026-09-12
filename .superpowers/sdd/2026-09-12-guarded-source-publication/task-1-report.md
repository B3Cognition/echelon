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

## Fix round 1 — first-captured target ancestor ownership

FIX_BASE / original review HEAD: `1227855d17ec89c25ae64d7eac910ed14f67dbb1`.
The independent review found one Important issue at `src/harness/squad_publication.py:2261`: a canonical new target parent first discovered by a checked capture retained only short-scope directory pins, so its identical-content/mode replacement between capture exit and mutation traversal could be adopted and published into. This enforces the existing Ruling 23; no plan or authority changes were made.

**Real regression RED before production edits:**

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py::test_first_captured_parent_stays_bound_before_mutation_traversal`

Output: `1 failed in 0.23s`, exit 1. Failure: `Failed: DID NOT RAISE <class 'harness.squad_publication.PublicationError'>`. The real fault hook creates `specs/a` at `0755` at position 0. A real source-tree capture records that directory and inode A. Immediately before the shared loop's target-image read, the test renames A and creates an identical empty `0755` directory at the same path with inode B. Before the fix the publisher returned success. Root was notified of this RED before production changed. The capture wrapper returns the unchanged real snapshot; the test does not fabricate a successful observation.

**Narrow fix:** `_capture_inspection` accepts an optional private `target_paths` owner supplied only by guarded publication. For each target's `paths.current` capture, it identifies only the newly traversed ancestor directory/entry associations and duplicates those descriptors into the original owner before the temporary capture closes. Each duplicate is registered for cleanup immediately. Source-only directory bindings, missing-entry pins, regular-file pins and membership pins are not copied. Normal capture exit verification still runs; original owner verification now detects the replacement before mutation. Public inspectors and legacy publication omit this optional owner and preserve their behavior.

**Focused GREEN:** the exact RED command above then produced `1 passed in 0.17s`, exit 0. Assertions establish that inode A stays retained, inode B differs, both directories stay empty, no target is published, and stage recovery material remains. A further real control replaces an unrelated read-only source directory with identical contents/mode between operation boundaries and confirms successful exact final publication; this prevents blanket lifetime retention of all source directories.

**One covering run for the amended code:**

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py tests/unit/test_squad_publication_inspection.py tests/unit/test_squad_publication_sources.py`

Output: `297 passed in 2.60s`, exit 0, no warnings. This was the only three-module covering run in the fix round. No whole suite, capacity, live/provider, installation, or postcommit test repetition occurred; no subagents were dispatched.

**Self-review:** read the complete amended production/test diff. The copied slice starts immediately before each target-current traversal and ends immediately afterward, excluding stage ancestors and subsequently captured source-only directories. Existing parent entry and child descriptors are duplicated, never reopened from an unbound root, and each successful duplicate is immediately registered on the original owner for exceptional cleanup. Missing and file pins stay in the short scope, so normal target writes and canonical parent creation remain possible. Existing descriptor cleanup, callback, process-lock and inspection tests are covered by the 297-test run. `git diff --check` before the covering run produced no output and exit 0; `git diff --cached --check` also completed with no output and exit 0 before commit. Source dependency completeness and cross-invocation inode authority remain explicit caller limitations. No unresolved correctness concern is known; root owns fresh scoped re-review.

Changed files in this fix: `src/harness/squad_publication.py`, `tests/unit/test_squad_source_guard.py`, and this report. Root plans/ledgers and the untracked next-phase source-manifest wire-validation plan remain untouched.

## Fix round 2 — bounded ownership of distinct target ancestor associations

FIX_BASE: `dc4a4964bf186ae5984f03f79ad61563a7cf3ebb`.
The fresh scoped review marked the original lifetime finding addressed, but found one new Important issue in the handoff: every checked capture duplicated all target ancestors into the invocation owner again, producing quadratic long-lived descriptor growth with operation count. No operation cap or new policy was authorized or added.

**Actual bounded regression RED before production edits:**

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py::test_repeated_captures_publish_eight_targets_under_bounded_descriptor_limit`

Output: `1 failed in 0.37s`, exit 1. An isolated spawned child with `RLIMIT_NOFILE=256` attempted eight valid shared-stage writes under one existing parent and returned `('PublicationError', 'target_drift')` instead of the expected actual final source receipt. Preparation and initial source capture were real; no filesystem drift was injected. Only the child sets its soft descriptor limit; parent/session limits remain untouched. Root received the actual RED result before production changed.

**Narrow implementation:** `_InspectionPaths.retain_directory` indexes retained target associations by the parent device/inode and entry name. A known entry must have the same child identity and still pass its original descriptor/entry verification; it returns the original retained child descriptor without allocating another pair. A new entry duplicates parent and child once, immediately registers each duplicate for cleanup, and retains that original pair. The method never overwrites a prior association. Initial target traversal now uses temporary traversal descriptors and the same distinct-association owner; capture handoffs and mutation traversal also call it. No missing-entry, regular-file or membership pins gain invocation lifetime. Public inspectors and legacy publication do not invoke the new retention path.

The old partial-parent-pin exhaustion test was updated to inject failure during the second descriptor duplication in the new shared retention helper. It still asserts cleanup of the first successful duplicate and no promoted targets. This is a change of fault-injection location after the ownership operation moved, not a weakening of its behavior assertion.

**Focused GREEN:** the exact bounded regression command above produced `1 passed in 0.33s`, exit 0. The child returned the actual final file paths, bytes and modes for all eight targets; parent-side checks independently confirmed all eight published contents and retained stage material. This is a bounded resource-limit test, not an unlimited-capacity claim.

**Substitution/cleanup checks:**

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py -k 'parent_pin_descriptor or identical_target_ancestor or first_captured_parent'`

Output: `4 passed, 70 deselected in 0.25s`, exit 0. Existing and publisher-created target-ancestor substitutions, the first-captured-parent boundary regression and partial duplicate cleanup remain enforced.

**One covering run:**

`/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest -q tests/unit/test_squad_source_guard.py tests/unit/test_squad_publication_inspection.py tests/unit/test_squad_publication_sources.py`

Output: `298 passed in 2.70s`, exit 0, no warnings. No broad, capacity, live/provider, installation or postcommit test repeats were run; no subagents were dispatched. The isolated OS child is the explicitly authorized location for the bounded resource-limit regression.

**Self-review:** reviewed the complete amended source/test diff and traced all three ownership entry points through the shared retention helper. Long-lived target descriptors are now proportional to distinct retained parent/name associations, rather than number of capture passes; short captured files/directories still consume resources proportional to the current capture, and no universal capacity guarantee is claimed. Existing bindings are verified, compared and reused without replacement, so deduplication cannot silently adopt a new child at the same original parent/name. Every new duplicate is registered before the next allocation; BaseException cleanup remains caller-owned. Root/stage owners, sole promotion loop, callback order and public inspection defaults remain unchanged. `git diff --check` before the covering run returned no output and exit 0. Final staged diff checking is completed before commit. No unresolved correctness concern is known; fresh scoped re-review remains root-owned.

Changed files: `src/harness/squad_publication.py`, `tests/unit/test_squad_source_guard.py`, and this report. Root plans/ledgers and the untracked next-phase codec plan remain untouched.
