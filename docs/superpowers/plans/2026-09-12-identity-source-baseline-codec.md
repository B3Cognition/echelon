# Initial publication source baseline codec implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Preserve exact original publication and selected dependency bytes in a deterministic recovery value before any target is promoted.

**Architecture:** Encode and decode the already reviewed immutable `PublicationSourcesSnapshot` with a closed version-1 string-tree JSON format. Accept only a complete initial observation where every current target equals its original preimage. This is a pure recovery codec, not a publisher, source-selection authority, semantic verdict or new journal.

**Tech Stack:** Existing source/publication snapshot dataclasses and pure validators, strict JSON, canonical base64 and SHA-256, real sealed publication fixtures.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- A crash between artifact promotion, ledger publication, and graph projection must be recoverable without duplicate allocation or false completion.
- No live publication/controller/provider/producer activation, memory writes, source selection, namespace enrollment or database schema changes in this task.

---

### Task 1: losslessly retain the complete initial source observation

**Files:** Create `src/harness/squad_source_baseline_codec.py` and `tests/unit/test_squad_source_baseline_codec.py`; document in `docs/element-identity-storage.md`. Leave existing publication/pin/lock, snapshot, journal, provider and state-owner code unchanged. Do not add a parallel publisher, CLI, persistence owner, artifact grammar or generic filesystem abstraction.

**Interfaces:**

```python
def encode_initial_publication_sources(snapshot: PublicationSourcesSnapshot) -> str: ...
def decode_initial_publication_sources(payload: str) -> PublicationSourcesSnapshot: ...
```

Use existing exact dataclasses from `harness.squad_source_snapshot`, `harness.squad_publication_snapshot`, and `PublicationMarker` from `harness.squad_publication`. The returned snapshot contains immutable tuples/dataclasses/bytes, detached from mutable caller objects. Both functions are pure: no files, SQLite, provider, clock, randomness or network. Raise bounded `PublicationError("manifest_invalid")` for malformed inputs, including modified/missing frozen attributes, subclasses where exact dataclass types are required, invalid Unicode, deep/malformed JSON and invalid base64. Do not leak full untrusted payloads in diagnostics.

Read existing `_marker_from`, `_validate_image`, `_source_path`, `_source_selection` and `harness.element_identity_json.strict_json`. Reuse these pure policies for their own formats; do not call the filesystem-dependent `_validate_manifest` or recreate its source/namespace authorization. No new third-party dependency.

**Initial observation requirement:** Require exact `PublicationSourcesSnapshot`, `PublicationSnapshot`, marker/operation/image/tree/path/file/directory dataclass types and exact tuples for their sequences. `promoted_prefix` must be exact integer zero. Independently require every operation's `current` descriptor to equal its `preimage`, with actual `current_bytes` matching that descriptor; a prefix of zero alone is not proof of original bytes. Validate each postimage descriptor and exact postimage bytes too. Missing images require `sha256 is None`, `mode is None`, and bytes `None`; files require lowercase SHA-256, exact integer mode in the existing range, and exact bytes (including empty) whose actual SHA matches. Keep binary, hidden-file, CRLF, empty/missing and permission distinctions. Write operations require a file postimage; delete requires missing. Targets are strictly sorted, unique canonical project-relative paths with no component overlap, matching the sealed snapshot's ordering. Empty operation tuples and exact no-op images remain valid.

Selected tree/file paths must equal `_source_selection`'s canonical sorted non-overlapping selection, with no duplicate or ancestor/descendant overlap across selections. Within each existing tree: directories and files are independently path-sorted and unique; the root directory appears exactly once, all members are under that root by path components, and every non-root member's parent directory exists in the directory set. File and directory names cannot collide, and a file cannot be an ancestor of another entry. Directory modes obey the existing mode policy. Missing trees have exact Boolean `exists=False` and no members; existing trees have exact Boolean `exists=True`, including empty roots. Selected external files may be missing and must use exact descriptors/bytes. Whenever an operation target is represented by a selected file or lies below a selected tree, its current/preimage must agree with the selected observation: an absent selected-tree file means missing, not an invented empty file. A target equal to a known directory (including parents implied by present selected files/trees) or descending through a known regular file is inconsistent and must reject; a target equal to a selected regular file is valid only when descriptors and bytes agree. Do not infer existing parent directories merely from a missing selected path. Operations outside the selected sources remain fully retained; selections are not a write-scope grant. Prefix siblings such as `spec` and `specs` remain independent.

**Exact wire format:** Canonical JSON uses `json.dumps(..., ensure_ascii=True, sort_keys=True, separators=(",", ":"))`, no trailing newline, and contains strings, null, arrays and objects only. IDs/path strings retain exact Unicode code points after valid UTF-8 validation. No integer/Boolean wire scalar or implicit coercion. Decode with strict_json, exact closed key sets and exact scalar types; after reconstruction require encoding to equal the original payload so alternate JSON whitespace, escaped forms, ordering, base64 or decimal padding are rejected rather than silently canonicalized.

Root keys: `version` equal `"1"`, `publication`, `trees`, `files`.

`publication` keys: `marker`, `operations`. Marker keys are `schema_version` equal `"1"`, `transaction_id`, `manifest_sha256`, carrying the existing marker's validated values. There is no stored promoted_prefix: zero is implicit in this initial-only format.

Each operation has exactly `action`, `target`, `preimage`, `postimage`. Each image has exactly `kind`, `sha256`, `mode`, `content_base64`: missing uses kind `"missing"` and three null fields; file uses kind `"file"`, actual lowercase hash, canonical decimal mode string, and canonical ASCII base64 of exact bytes (`""` for empty). Reconstruct operation `current` and `current_bytes` from its retained preimage, never from the live target. There are no stage filenames or guessed original bytes.

Each tree has exactly `path`, `exists`, `directories`, `files`; exists is string `"true"` or `"false"`. Each directory has exactly `path`, `mode` (canonical decimal mode string). Each tree file and selected external file has exactly `path`, `image`, where image uses the format above; a tree file must be present. Mode strings are canonical ASCII decimal in the existing bounded permission range, not octal, signs, padding, floats or Booleans. Conversion of this small bounded mode value does not impose a digit cap on identifiers or mutate Python's global integer settings.

The marker/hash and snapshot consistency are retained claims, not authentication. This snapshot lacks manifest stage filenames, so the codec cannot independently recompute the sealed manifest digest. A self-consistent altered payload can decode; the future completion owner must compare it to the intended authority, accepted baseline and authenticated sealed publication, then validate unchanged dependencies under the publication lock before promotion. Do not call decoding, hash equality, successful round-trip or a value created directly by a caller “authorized publication.” Selection completeness, artifact role/source associations, namespace/run binding, semantic evidence and complete versioned completion recovery remain later integration.

**Required first regression before production edits:** Use actual `SquadPublicationTransaction` and `PreparedSquadPublication.inspect_sources` following `tests/unit/test_squad_publication_sources.py`'s fixture conventions. Create a project-local spec tree with one CRLF Markdown file and a hidden binary file, plus an external empty file. Seal one write changing the Markdown, capture the tree and external file while every target remains at preimage, then import the absent new module and round-trip the observation:

```python
def real_prepared_write_fixture(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs/demo").mkdir(parents=True)
    (project / "specs/demo/spec.md").write_bytes(b"Original\r\n")
    (project / "specs/demo/.hidden").write_bytes(b"\x00\xff")
    (project / "constitution.md").write_bytes(b"")
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"Revised\r\n")
    target = Path("specs/demo/spec.md")
    transaction.add_write(target, stage, owned_paths={target})
    return transaction.seal()

def test_initial_source_baseline_round_trip_preserves_original_bytes(tmp_path):
    prepared = real_prepared_write_fixture(tmp_path)
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=("constitution.md",)) as observed:
        from harness.squad_source_baseline_codec import (
            encode_initial_publication_sources, decode_initial_publication_sources,
        )
        payload = encode_initial_publication_sources(observed)
        restored = decode_initial_publication_sources(payload)
        assert restored == observed
        assert restored.publication.operations[0].current_bytes == b"Original\r\n"
        assert restored.publication.operations[0].postimage_bytes == b"Revised\r\n"
        assert restored.trees[0].files[0].content == b"\x00\xff"
        assert restored.files[0].content == b""
```

Use the existing secure-POSIX test skip convention; never substitute mocked publication for this regression. The hidden file sorts before the Markdown file, making the explicit expected index deterministic. The initial failure must reach the new missing module after successfully preparing and capturing the real publication.

- [ ] Retain required actual RED, implement the minimal round-trip, verify GREEN.
- [ ] Assert complete exact wire shapes and bytes for multiple sorted operations, write/delete/no-op, all selected directories/files, nested and missing/empty trees, missing/empty external files, modes, hidden/binary/Unicode/CRLF data, overlap between target operations and selected sources, operations outside selected sources and prefix siblings. Expected serialized structures and original bytes must be independent literals, not projections of the codec under test.
- [ ] Execute a real multi-target partial publication with the existing fault hook. A fresh partially promoted inspect_sources observation must fail initial encoding. The earlier retained payload must still decode to its exact original bytes after partial and complete publication, regardless of live target contents; demonstrate immutable recovery value retention, not successful recovery/publication authorization. Include synthetic prefix-zero-but-current-postimage and no-op controls, explicitly distinguishing synthetic malformed values from actual publisher observations.
- [ ] Reject unknown/missing/extra/null/wrong-type fields, bad marker/version, deep/noncanonical/duplicate/numeric JSON, noncanonical or invalid base64, mismatched image hashes/modes/bytes, sortedness/duplicates/overlaps, invalid tree membership/parents/path escapes, missing-tree members, and snapshot/operation/selected-source inconsistencies. Test frozen attribute deletion and dataclass subclass rejection with bounded errors. Cover legitimate self-consistent altered data as unauthenticated decodable values, not a false cryptographic-authority claim.
- [ ] Verify encode/decode makes no filesystem/database changes or accesses using focused access interdiction after capturing the real fixture. Do not patch away the initial real capture. Verify repeated encoding is exact and all decoded dataclass sequences are tuples/bytes, with no mutable caller container sharing.
- [ ] Run once final covering modules: new `tests/unit/test_squad_source_baseline_codec.py`, `tests/unit/test_squad_publication_sources.py`, `tests/unit/test_squad_source_snapshot.py`, and `tests/unit/test_squad_publication.py`. All existing paths were verified by root. No full/million/live/provider/post-commit repeats.
- [ ] Document exact v1 representation, original-byte precondition and caller authentication limits; self-review closed shapes/source-tree consistency and unchanged lock/publisher ownership. Run git diff --check, commit only task files, retain actual commands/RED/GREEN/results and real-versus-synthetic provenance in the report. Root owns plan/ledger and independent review.

## Remaining integration

This codec supplies original bytes to an eventual complete recovery packet. It does not persist a managed-spec accepted baseline, select complete dependencies, assign artifact roles, bind lifecycle/reference/semantic requests, acquire locks or publish. Those must be integrated through the existing completion owner before any live managed producer is enabled.
