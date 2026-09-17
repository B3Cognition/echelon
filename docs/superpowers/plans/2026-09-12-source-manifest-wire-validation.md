# Source manifest wire validation implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Validate the existing metadata-only source fingerprint when it is loaded from retained storage, without reconstructing nonexistent source bytes or claiming authentication.

**Architecture:** A pure strict decoder validates the existing closed version1 metadata wire and returns the existing immutable snapshot type. Factor only the baseline codec's current tree-layout checks into one private shared helper so actual-byte capture validation and metadata decoding enforce the same membership rules. No persistence or managed-source API is introduced here.

**Tech Stack:** Existing SourceManifestSnapshot, strict_json, canonical ASCII JSON/SHA-256, shared path/mode/selection/layout validators, real source capture plus pure malformed-wire tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- The canonical inputs still match the captured publication baseline.
- No live controller/provider activation, schema or persisted-source-head change, publication effect, graph/memory write or accepted-source authority. Structurally valid metadata is a retained claim, not proof of its source bytes or owner.

---

### Task 1: decode and validate the existing selected-source metadata wire

**Files:** Create `src/harness/squad_source_manifest_codec.py` and `tests/unit/test_squad_source_manifest_codec.py`. Modify `src/harness/squad_source_baseline_codec.py` only for the shared tree-layout extraction. Document in `docs/element-identity-storage.md`. No capture, source-manifest factory, projection, source guard, publisher, parser, store, controller, state, provider or graph changes. Root owns plan/ledger.

**Public interfaces:**

```python
def decode_source_manifest(payload: str) -> SourceManifestSnapshot: ...

def validate_source_manifest(
    snapshot: SourceManifestSnapshot,
) -> SourceManifestSnapshot: ...
```

`decode_source_manifest` accepts only the exact canonical ASCII payload already emitted by `snapshot_source_manifest`, validates its complete closed shape, and returns a fresh existing SourceManifestSnapshot containing the unchanged payload and computed lowercase unprefixed SHA-256. It does not return source bytes, a PublicationSnapshot or an accepted-head receipt. `validate_source_manifest` requires the exact existing frozen snapshot class with intact exact-string fields, delegates to the decoder and requires the supplied digest to equal the decoded digest; return the validated detached snapshot. Reject subclasses, missing/deleted fields and malformed strings. Do not make the otherwise intentionally simple SourceManifestSnapshot constructor perform validation.

**Closed existing wire:** Root keys exactly version/trees/files, version the string1. Arrays are exact JSON arrays. Each tree keys path/exists/directories/files; exists only strings true/false. Directory keys path/mode, canonical path and canonical decimal mode string. Tree file/explicit file keys path/image. Image keys kind/sha256/mode only; file kind uses lowercase64hex SHA and existing canonical mode format/range; missing kind requires both null and is permitted only for explicit selected files, never tree file entries. No numeric/Boolean scalar, content_base64, unknown key, duplicate JSON key, alternate version, coerced type or file/directory/source selection alias. Retain empty selected trees, empty directories, missing explicit files, sorted membership and sorted separate trees/files arrays exactly as the factory. Re-encoding through the existing canonical json.dumps arguments must equal the original payload exactly; reject alternate whitespace/newline/key order/escaping and non-ASCII literal encoding. Path strings decoded from canonical ASCII escapes must still be valid UTF-8 canonical paths.

**Reuse and layout factoring:** Reuse baseline codec `_object`, `_array`, `_text`, `_path`, `_decode_mode`, and `_source_selection`, plus the publisher's existing `_validate_sha256`. Do not call `_decode_image`: it correctly requires real bytes and content_base64, neither of which exist in this format. Do not fabricate empty bytes/hash values to trick actual-byte validators, or wrap observations in fake initial publications.

Extract the baseline codec's existing membership/layout validation into:

```python
def _validate_tree_layout(
    root: str,
    exists: bool,
    directory_paths: list[str],
    file_paths: list[str],
) -> None: ...
```

This private helper consumes paths already validated with `_path` and exactly validated existence; it preserves the current sorted/unique directory and file checks, absent-tree emptiness, present-root occurrence, component-contained membership, explicit parent directories, file/directory collisions and regular-file-ancestor rejection. `_tree_value` continues to validate every exact dataclass, mode and actual byte/hash image before calling it; returned dictionaries/observations/directory sets remain byte-for-byte/shape compatible. The decoder applies path/mode/image validation before the same layout helper. Do not duplicate these hierarchy rules or weaken the initial codec/factory. Pure shared extraction only; no other initial-baseline behavior change.

Both new public functions normalize ordinary validation/structural/Unicode/JSON/type/recursion errors to the existing bounded PublicationError("manifest_invalid") from None, including a PublicationError raised by a reused helper with an underlying untrusted context. Preserve BaseException propagation. No filesystem, SQLite, parser, network, provider, clock or randomness. Existing input strings/snapshots stay unchanged. A caller can supply a self-consistent changed file hash; without original bytes/accepted authority the decoder must not claim to detect that as forged provenance.

**Required first regression before production:**

```python
def test_real_manifest_round_trip_preserves_exact_existing_wire(tmp_path, secure_posix):
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_source_manifest import snapshot_source_manifest
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/notes.md").write_bytes(b"FR-1000000\r\n\x00\xff")
    prepared = SquadPublicationTransaction.begin(project, squad, "4" * 32).seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as sources:
        assert sources.trees[0].files[0].content == b"FR-1000000\r\n\x00\xff"
    observed = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    from harness.squad_source_manifest_codec import decode_source_manifest, validate_source_manifest
    assert decode_source_manifest(observed.payload) == observed
    assert validate_source_manifest(observed) == observed
```

Root verified empty sealed operations and existing capture/factory signatures. Scope the secure-POSIX fixture to real capture cases only, not platform-independent wire tests. Actual capture/factory must succeed before missing new module causes RED; notify root before production edits.

- [ ] Add first real regression and report actual missing-module RED before production edits. Implement strict metadata decoder and pure shared-layout extraction, verify GREEN.
- [ ] Check complete independent literal payload/digest (including empty selection) without deriving expectations from decoder output; rich actual captures preserve hidden/binary/CRLF/wide-ID hashes, Unicode paths, modes, absences, empty directories and selection scope. Decoder emits no original content or new wire format.
- [ ] Parameterize malformed exact closed shapes/scalars, duplicate keys, noncanonical JSON/ASCII/escapes, bad hash/mode/path, sorting/duplicates, source component overlap including interleaved prefix sibling, tree membership/parents/root/collisions/absent trees, tree missing-file images and invalid extra content fields. Include valid component siblings and canonical non-ASCII paths. No duplicated exhaustive actual-byte codec matrix.
- [ ] Validate supplied digest mismatch, wrong exact snapshot types, deleted/damaged frozen fields and untrusted/deep JSON bounded rendered errors. Include actual malformed Unicode context and explicit BaseException propagation control; no synthetic RED claimed for already-correct code.
- [ ] Demonstrate the explicit unauthenticated boundary: change one valid file SHA in the metadata and recompute canonical payload; decoder accepts this different self-consistent claim but it is not equal to the observed source fingerprint. Do not call this accepted baseline or actual-source tamper detection.
- [ ] Tripwire pure decode/validate after real setup across builtins/io/Path, os.open/listdir/scandir/stat, SQLite/network/time/random; input snapshots remain unchanged and output detached. Pure synthetic cases must run without POSIX fixture.
- [ ] Run once final covering modules: new tests/unit/test_squad_source_manifest_codec.py, tests/unit/test_squad_source_manifest.py, tests/unit/test_squad_source_baseline_codec.py, tests/unit/test_squad_source_projection.py, tests/unit/test_squad_source_guard.py. Self-review exact shared extraction and error/wire boundaries, document limitations, actual git diff --check, commit task files/full report. No full/million/live/provider/postcommit repeats. Root independently reviews.

## Remaining integration

Durable accepted-source heads still need explicit namespace/spec/run/source context, idempotent compare-and-swap ownership and publication receipt binding. Metadata validation cannot establish those. Future managed registration must not silently accept existing relabeled histories, and partial integration must not activate any producer. Closed completion recovery, graph/memory acceptance, all producers and bounded repair remain required.
