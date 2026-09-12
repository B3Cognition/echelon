# Expected publication source manifest implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Derive the exact selected-source metadata expected after all sealed operations complete, preserving unrelated source membership, bytes and modes.

**Architecture:** A pure projection validates the retained initial capture, applies sealed file postimages to detached selected source observations, and uses the source-manifest factory. Existing directories keep their observed modes; genuinely new directories use the existing publisher's explicit creation mode. This is an expected final state, not an observed or authenticated completed publication.

**Tech Stack:** Existing immutable source/publication snapshots, initial codec, selected-source manifest factory, pathlib component comparisons, real POSIX publisher tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- The canonical inputs still match the captured publication baseline.
- No live provider/controller activation, accepted-source persistence, schema change, graph/memory write, extra lock or new publication owner. Projection grants no acceptance, freshness or semantic authority.

---

### Task 1: derive the exact expected final selected-source fingerprint

**Files:** Create `src/harness/squad_source_projection.py` and `tests/unit/test_squad_source_projection.py`; modify `src/harness/squad_publication.py` only to name and share its existing new-directory mode; document the inactive projection in `docs/element-identity-storage.md`. No capture/codec/factory/parser/store/controller changes. Root owns plan/ledger.

**Interface:**

```python
def project_publication_source_manifest(
    initial: PublicationSourcesSnapshot,
) -> SourceManifestSnapshot: ...
```

Use `encode_initial_publication_sources(initial)` as the first guard, discard its output, and preserve its PublicationError. Do not fabricate a zero-prefix current snapshot or re-encode/decode a copy. The factory `snapshot_source_manifest(trees=..., files=...)` supplies the output's exact canonical format and digest; do not duplicate JSON/hash/validation logic. All outputs are detached metadata; initial bytes/objects remain unchanged. No I/O, parser, database, clock, network, provider or randomness.

**Existing publisher mode, not new policy:** `_open_parent_directory(..., create=True)` currently calls `os.fchmod(next_fd, 0o755)` only after its own successful mkdir/open. Introduce module constant `PUBLICATION_DIRECTORY_MODE = 0o755` beside existing publication constants and use it in that one fchmod call and in the pure projection. Preserve every existing race/error/fsync/descriptor/lock behavior. This does not re-chmod existing directories, including the FileExistsError path. A successful final capture with a different newly required directory mode will differ from the expectation and cannot pass a future comparison; do not silently accept an arbitrary mode or pretend all crash/interference states are now recoverable.

**Projection rules:** Start from each selected tree's immutable directory and file observations. Apply every sealed operation affecting that selection by component-relative path, never raw string prefixes. Write sets the target to its exact postimage descriptor and postimage bytes, including empty/binary/CRLF and mode-only/no-op writes. Delete removes only the exact file; it never removes directories. A missing-target no-op delete creates nothing. For a write beneath a selected tree, add only missing directory ancestors down to and including that selected root, with PUBLICATION_DIRECTORY_MODE; keep every existing directory object/mode. A missing selected tree becomes present only if a write beneath it creates its root. Unchanged empty trees/directories/hidden files stay present. Rebuild sorted exact tuples of existing ProjectDirectorySnapshot/ProjectFileSnapshot/ProjectTreeSnapshot objects, retaining complete membership.

For explicitly selected files, replace image/content only for an exact operation target; otherwise preserve the supplied image and None-versus-empty distinction. Operations outside all selected sources do not expand selection or add unrelated metadata. However, writes that would make the selected shape impossible must fail: a write at or above a selected tree root would leave a file where tree capture expects directories; a write strictly above or below an explicitly selected file would leave a regular-file ancestor or turn the selected file location into a directory. Reject those cases with bounded `PublicationError("manifest_invalid")`, even when the before selections are absent. Missing no-op deletes at those relationships need not fail because they create nothing. Initial validation already rejects existing directory targets and existing regular-file ancestors; retain its behavior. Do not infer new source roots, typed roles or writable authority.

Do not mutate metadata dictionaries obtained from other code or initial dataclasses. Local detached maps/tuple construction are sufficient. Normalize unexpected structural errors to PublicationError("manifest_invalid") from None without catching BaseException; keep the first initial guard outside that normalizer. No new reference/candidate diagnostic codes, decoder, partial-prefix projection, accepted-head API or current-filesystem fallback. This task is final-state projection only: it does not authenticate a supplied seal, classify partial mkdir states, prevent races or provide same-owner publication recovery.

**Required first real regression:**

```python
def test_projected_manifest_matches_real_write_delete_and_new_directories(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs").chmod(0o750)
    (project / "specs/old.md").write_bytes(b"old")
    (project / "specs/.keep").write_bytes(b"\x00\xff")
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"FR-1000000\r\nnew")
    stage.chmod(0o640)
    write = Path("specs/nested/new.md")
    delete = Path("specs/old.md")
    transaction.add_write(write, stage, owned_paths={write})
    transaction.add_delete(delete, owned_paths={delete})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert initial.trees[0].directories[0].mode == 0o750
        assert {item.path: item.content for item in initial.trees[0].files} == {
            "specs/.keep": b"\x00\xff", "specs/old.md": b"old"}
    from harness.squad_source_projection import project_publication_source_manifest
    expected = project_publication_source_manifest(initial)
    prepared.publish()
    with prepared.inspect_sources(tree_paths=("specs",)) as final:
        actual = snapshot_source_manifest(trees=final.trees, files=final.files)
        assert {item.path: item.mode for item in final.trees[0].directories} == {
            "specs": 0o750, "specs/nested": 0o755}
        assert {item.path: item.content for item in final.trees[0].files} == {
            "specs/.keep": b"\x00\xff", "specs/nested/new.md": b"FR-1000000\r\nnew"}
    assert actual == expected
```

Use the established secure-POSIX capability check for real capture fixtures only; do not use a module-wide autouse skip that also suppresses platform-independent pure tests. Real capture must succeed before new-module import gives RED; notify root before production edits. Root verified add_delete(target, *, owned_paths) and the current write/capture interfaces. Independent final source assertions keep the two factory paths from becoming the sole oracle.

- [ ] Add first real regression, obtain actual RED before production, implement minimal shared-mode projection, verify GREEN.
- [ ] Verify complete independent expected payload for one small fixture, plus empty selection, unchanged selection, absent and empty trees/files, existing nondefault directory modes, new nested roots, binary/hidden/CRLF/wide/legacy bytes, deletions retaining empty directories, exact explicit-file writes/deletes and source boundaries/prefix siblings. Real publication must substantiate new-directory mode and selected absence behavior.
- [ ] Verify structurally impossible selection/write relationships fail without publication or source mutation, alongside valid component-prefix siblings and missing no-op-delete controls. Verify all operations outside selection leave the selected fingerprint unchanged, without claiming their scope was validated by this projection.
- [ ] Retain an actual initial capture across an interrupted two-target publication; projection from that original remains stable and matches the eventual actual final capture after retry. Passing actual partial or final captures to the initial guard still fails when they are noninitial. No partial-prefix recovery claim.
- [ ] Verify existing source changes outside sealed targets differ from expected final fingerprint: hidden addition, empty-directory deletion, file bytes/mode and directory mode. Use real post-publication recapture; do not claim this pure function prevented the change.
- [ ] Cover input noninitial/structural rejection through existing guard, frozen output, unchanged original bytes/objects, and explicit no-I/O tripwires after real setup (builtins/io/Path, os.open/listdir/scandir/stat, SQLite/network/time/random). Do not repeat the whole initial-codec malformed matrix.
- [ ] Run once final covering modules: new tests/unit/test_squad_source_projection.py, tests/unit/test_squad_source_manifest.py, tests/unit/test_squad_source_baseline_codec.py, tests/unit/test_squad_publication.py. No full/million/live/provider/postcommit repeats. Self-review exact shared rules and source membership; document limitations, git diff --check, commit task files and full actual report. Root independently reviews.

## Remaining integration

Expected and observed fingerprints must later be bound to authenticated namespace/context, durable accepted-source history, candidate scope/review and the exact sealed publication. The existing publication/completion owner must perform fresh comparison and promotion with descriptor/lock continuity and preserve a recoverable intent if any comparison/effect fails. Run-local versus published/retarget source association, managed producer enforcement, graph/memory currentness and bounded repair remain outstanding. This plan selects none of those APIs or schemas.
