# Selected source manifest implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Produce a deterministic content-and-membership fingerprint of complete selected source observations, independent of publication operation IDs or promotion progress.

**Architecture:** A small pure factory reuses the existing initial-source codec's pure tree/image/path/selection validators, projects validated observations to a closed canonical metadata manifest, and hashes the exact ASCII payload. Original bytes remain separately retained in the caller's snapshot; this fingerprint will support later durable accepted-source comparison but is not itself acceptance or authentication.

**Tech Stack:** Existing ProjectTreeSnapshot/ProjectPathSnapshot, pure codec helpers, frozen result dataclass, canonical ASCII string-tree JSON and SHA-256, real joint source capture.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- The canonical inputs still match the captured publication baseline.
- No live producer/provider/controller activation, schema change, accepted-source persistence, graph/memory write or publication effect. A supplied source observation and its hash are not authenticated accepted-source authority.

---

### Task 1: fingerprint complete selected source observations

**Files:** Create `src/harness/squad_source_manifest.py` and `tests/unit/test_squad_source_manifest.py`; document the inactive factory in `docs/element-identity-storage.md`. Do not modify capture, initial codec, candidate assembly, parser, store, graph or publisher. Root owns plan/ledger.

**Interface:**

```python
@dataclass(frozen=True, slots=True)
class SourceManifestSnapshot:
    payload: str
    sha256: str

def snapshot_source_manifest(
    *,
    trees: tuple[ProjectTreeSnapshot, ...],
    files: tuple[ProjectPathSnapshot, ...],
) -> SourceManifestSnapshot: ...
```

These are precisely the existing immutable source-observation tuples, e.g. `snapshot.trees` and `snapshot.files` from joint capture. The factory intentionally does not take a PublicationSnapshot or inspect operations, marker, transaction ID or promoted prefix. It fingerprints the selected sources observed at that point, whether before, during or after publication. A partial capture can therefore have a valid, different manifest; this does not make it an initial or completed publication. Callers still require the separate initial guard wherever original before bytes are required. Sources outside the explicit selection are outside this fingerprint; do not claim full project coverage.

**Validation reuse:** Require exact tuple containers, exact existing dataclasses and their current strict closed-field/image/membership/path rules. Use `squad_source_baseline_codec._tree_value` to validate each tree, `_encode_image` for each explicit file image/actual bytes, `_path` for file paths and `_source_selection` for cross-selection canonical uniqueness and component non-overlap. Each of these helpers is pure and already reviewed; do not copy their logic or call filesystem manifest validation. Require the tuple order to equal the existing helper's sorted canonical selection output. Existing strict tree validation handles sorted complete directories/files, root occurrence, parents, modes, file/directory conflicts, absent trees and actual byte/hash equality; missing external files retain None, present empty bytes remain a file. Every source file's bytes must be validated before they are omitted from the metadata. The tuple inputs are not broadened to ordinary mutable Sequence interfaces.

Invalid inputs raise the existing bounded `PublicationError("manifest_invalid")`, including damaged/deleted frozen attributes and Unicode/type/key/recursion errors. Suppress underlying untrusted exception context when normalizing unexpected structural failures (`from None`); do not include source content in exception text or rendered chained tracebacks. No I/O, namespace lookup, parser, SQLite, provider, clock or randomness. Inputs and retained bytes must remain unchanged.

**Exact closed wire projection:** The factory emits `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` with no newline. Every scalar is a string or null; JSON numeric/Boolean scalars never appear. Root keys are exactly `version`, `trees`, `files`, with version `"1"`. Trees/files preserve canonical sorted input order.

- Each tree has exactly `path`, `exists`, `directories`, `files`. Exists is `"true"` or `"false"`.
- Each directory has exactly `path`, `mode`, with canonical decimal mode string using the existing codec mode range/format.
- Each tree file and explicit selected file has exactly `path`, `image`.
- Each image has exactly `kind`, `sha256`, `mode`. For a regular file, kind is `"file"`, SHA is the actual byte digest and mode the canonical decimal string. For missing selected files, kind is `"missing"` and both other fields are null. Tree files must be regular files.
- No `content_base64`, original text/bytes, publication fields, namespace, role, binding, semantic flags, timestamps or source-root inference appears in the manifest.

The validated codec tree/image values have exactly this shape after removing only their image `content_base64` fields. Modify only those fresh projection dictionaries, never caller objects. `SourceManifestSnapshot.sha256` is lowercase SHA-256 of payload encoded as ASCII, without a `sha256:` prefix. The result is a detached frozen slotted value containing only two strings. Do not add a decoder, source-change classifier, storage, registration API or additional manifest format in this task; those are not required to compute a fingerprint from captured observations.

**Required first real regression before production edits:**

```python
def test_real_selected_sources_have_independent_closed_manifest(tmp_path):
    import hashlib
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs").chmod(0o750)
    (project / "specs/notes.md").write_bytes(b"hello")
    (project / "specs/notes.md").chmod(0o640)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"later")
    target = Path("specs/notes.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",), file_paths=("absent",)) as sources:
        assert sources.trees[0].files[0].content == b"hello"
    from harness.squad_source_manifest import snapshot_source_manifest
    manifest = snapshot_source_manifest(trees=sources.trees, files=sources.files)
    expected = ('{"files":[{"image":{"kind":"missing","mode":null,"sha256":null},"path":"absent"}],'
        '"trees":[{"directories":[{"mode":"488","path":"specs"}],"exists":"true",'
        '"files":[{"image":{"kind":"file","mode":"416",'
        '"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"},'
        '"path":"specs/notes.md"}],"path":"specs"}],"version":"1"}')
    assert manifest.payload == expected
    assert manifest.sha256 == hashlib.sha256(expected.encode("ascii")).hexdigest()
```

Use the established secure-POSIX skip fixture for real capture cases. Capture must succeed before the missing new module is the RED. Root verified the current capture/dataclass/helper interfaces and manual golden shape; do not mock capture or use factory output as its own expected manifest.

- [ ] Add required real regression, retain and notify root of actual missing-module RED before production edits, implement minimal shared-validator projection, verify GREEN.
- [ ] Independently assert the exact closed golden wire and empty selection wire; absence versus empty, empty directories/trees, nested and hidden/binary files, non-ASCII paths with canonical ASCII escaping, CRLF and wide/legacy ID bytes represented only through their exact content hash, and no byte/base64 leakage into payload. Empty both selection tuples is valid.
- [ ] Show determinism across repeated real captures/new transaction IDs with unchanged sources. Independently change content, file mode, directory mode, hidden membership, file absence/presence, empty-directory presence and selection coverage; each relevant source change must change payload/digest. Mode and selected-root differences count even when bytes match. Use actual captures for filesystem changes; do not claim fingerprint equality authenticates sources outside selection.
- [ ] Show a real two-target interrupted publication yields distinct initial/partial/final selected-source manifests and retry preserves the final fingerprint. The initial byte-retention codec still separately rejects noninitial captures; do not alter its guard. Existing source snapshots remain unchanged after factory calls.
- [ ] Test exact container/dataclass types, damaged fields, malformed paths, unsorted/duplicate/overlapping selections including interleaved prefix-sibling ancestry, tree membership and byte/hash mismatch failures through reused validators. Include valid prefix siblings and a no-I/O tripwire after real setup covering builtins/io/Path opens, os.open/listdir/scandir/stat, SQLite/network/time/random entry points. Check bounded exception rendering and frozen detached output; no duplicated exhaustive codec matrix is required.
- [ ] Run once final covering modules: new tests/unit/test_squad_source_manifest.py, tests/unit/test_squad_source_baseline_codec.py, tests/unit/test_squad_publication_sources.py, tests/unit/test_element_identity_candidate_sources.py. No full/million/live/provider/postcommit repeats. Document observed fingerprint versus source selection completeness/accepted authority, self-review pure helper reuse and exact wire, git diff --check, commit task files and actual report. Root independently reviews.

## Remaining integration

This factory does not persist an accepted-source head, register a managed spec/run, authenticate the source owner or make a compare-and-swap acceptance decision. Later controller integration must store the accepted manifest with the appropriate namespace/context and publication receipt, compare a fresh complete captured source set against it, and coordinate source/ledger/graph completion under the existing owner. The original bytes required for crash recovery remain in the existing retained source baseline, not in this metadata fingerprint.
