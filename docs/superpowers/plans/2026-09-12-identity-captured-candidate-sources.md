# Captured candidate source assembly implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Assemble typed candidate before/after text from a validated retained initial publication/source snapshot, with explicit physical-to-logical source bindings and physical write scope.

**Architecture:** A pure adapter joins controller-supplied source bindings to the existing snapshot and sealed operations. It reuses the initial-source codec's strict validation, creates existing CandidateArtifact values without reading current files, and reports unauthorized or non-text proposed writes. This connects capture to typed preflight without replacing capture, parsing, source authentication or completion ownership.

**Tech Stack:** Immutable publication/source dataclasses, existing canonical path validation and initial-source codec, CandidateArtifact/CandidateDiagnostic, real sealed transactions and identity candidate fixtures.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- The canonical inputs still match the captured publication baseline.
- No live provider, producer, controller, graph, memory, database or publication activation in this task. An internally valid supplied snapshot is not an authenticated accepted baseline.

---

### Task 1: join retained original and proposed bytes into typed candidates

**Files:** Create `src/harness/element_identity_candidate_sources.py` and `tests/unit/test_element_identity_candidate_sources.py`; document the pure adapter in `docs/element-identity-storage.md`. Do not modify existing codec, capture, publisher, parser, scope checker, authority or source-claim validator. Root owns plan/ledger.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class CandidateSourceBinding:
    source_path: str
    artifact_path: str
    role: str

@dataclass(frozen=True, slots=True)
class CapturedCandidateSources:
    artifacts: tuple[CandidateArtifact, ...]
    diagnostics: tuple[CandidateDiagnostic, ...]

def assemble_candidate_sources(
    snapshot: PublicationSourcesSnapshot,
    bindings: Sequence[CandidateSourceBinding],
    *,
    writable_paths: Sequence[str],
    opaque_write_paths: Sequence[str] = (),
) -> CapturedCandidateSources: ...
```

`source_path`, writable_paths and opaque_write_paths use the snapshot's canonical project-relative POSIX paths. `artifact_path` uses the existing canonical relative CandidateArtifact/ReferenceClaim path policy. Mapping is explicit: do not derive a spec root, strip prefixes heuristically, normalize labels or infer roles from filenames. Each binding has one unique source_path and one unique artifact_path. Role must be an exact string in IDENTITY_SUPPORTED_ROLES. The caller owns namespace, role associations, source selection completeness and the artifact/element semantic edit scope; this helper checks only the supplied mapping and physical write scope. It does not interpret IDs or grants, parse artifacts, allocate, resolve references or make a semantic verdict.

**Input validation and original-image guard:** Snapshot is required even for empty bindings. Call existing `encode_initial_publication_sources(snapshot)` to enforce its exact structural, image-byte/hash/mode, initial preimage and selection/target consistency contract; discard the returned encoding. Do not reimplement this validator, manufacture an initial snapshot from current postimages, or perform an encode/decode round trip. Preserve PublicationError on invalid snapshots rather than converting authority/source damage to a candidate-repair diagnostic. No codec performance claim is made; this is not an allocation hot path.

Snapshot all three ordinary Sequence inputs to tuples, reject strings/bytes/generators, exact binding instances only, and revalidate damaged/deleted frozen fields. Validate source/writable/opaque paths with `_source_path` and artifact paths with `_validate_input(..., role="references", text="")`, including UTF-8. Require canonical unique paths within each sequence; no coercion. Opaque paths must be a subset of writable_paths and disjoint from all binding source paths. Malformed binding/scope input raises bounded ValueError without payload interpolation, including Unicode/attribute/type/recursion failures and PublicationError from a scope path validator. Use `raise ValueError(<constant>) from None` at normalization boundaries: check formatted traceback suppression of an oversized untrusted exception message, not merely str(error). Keep that normalization boundary separate from snapshot validation: invalid snapshot PublicationError must not be converted. Preserve caller values. Empty sequences are allowed when the snapshot is valid.

**Resolve original sources:** Build indexes from every selected regular file/external file, selected directory, selected tree root, and operation. A bound source is captured if it has an operation, an explicit selected file observation, or lies component-wise at/below a selected tree root. Missing members of a completely selected tree mean absent; textual prefix siblings are not captured. Exact existing directories, known regular-file ancestors, and uncaptured bound paths raise bounded ValueError (controller source-binding defect), not a provider repair finding. Infer existing ancestor directories only from actual selected directories/present files and present operation preimages; do not infer them from absent paths. Existing codec validation remains responsible for shared operation/selection consistency. No filesystem fallback.

For each binding, take before bytes from operation.current_bytes when that source has an operation; otherwise use the selected source (None when captured absent). Take after bytes from operation.postimage_bytes for an operation, otherwise exactly before. Present empty bytes decode to ""; None remains None. If both are absent, emit no CandidateArtifact: this models an optional absent source without fabricating an empty document. The explicit binding still accounts for a missing-target no-op delete operation. An absent selected tree root is absent, not an invented existing directory. Never infer post-promotion directory modes or produce a complete post-tree claim.

Before bytes for a typed binding must decode as exact UTF-8 and pass the existing text validator (including no NUL). If not, raise bounded ValueError: the claimed typed baseline cannot be interpreted and must not be sent to an agent as a repair of authenticated history. A non-text proposed after image is a candidate failure: add `CandidateDiagnostic("candidate_source_not_text", source_path, None, "typed proposed source must contain valid UTF-8 text without NUL")` and omit that artifact, retaining other diagnostics/artifacts. Do not normalize CRLF, whitespace, BOM or Unicode. An unchanged typed binary source consequently fails as an invalid before image. Unbound unchanged binary/hidden files remain in the caller's retained snapshot and are not decoded, silently relabeled as typed facts or dropped from physical-source authority.

**Physical proposed-write policy:** Inspect EVERY sealed operation, including no-op writes/deletes and mode-only changes. A target absent from writable_paths emits `CandidateDiagnostic("artifact_out_of_scope", target, None, "sealed operation target is not explicitly writable")`. A target absent from both binding source paths and opaque_write_paths emits `CandidateDiagnostic("publication_target_unbound", target, None, "sealed operation target has no explicit typed or opaque binding")`. Both diagnostics may apply. Opaque writes are explicitly authorized non-typed paths; they are not parsed, do not produce CandidateArtifact values and cannot overlap a typed binding. This permission is not discovered from content and does not establish that a caller chose the correct role. Unbound unchanged selected files are not operations and need no opaque-write permission. Scope matching is exact path equality, not parent-directory grants or textual prefix matching.

All adapter diagnostic paths are project-relative physical source paths, explicitly distinct from returned CandidateArtifact paths. Sort/deduplicate diagnostics with the existing candidate ordering `(path or "", element_id or "", code, detail)` and sort artifacts by artifact_path. Return exact immutable tuples in the frozen result. Do not mutate snapshot/bindings/scopes or suppress physical write diagnostics when another artifact decodes successfully. Callers must reject any diagnostics before accepting the artifact tuple as successful assembly.

**Required first real regression before production edits:**

```python
def test_sealed_original_and_proposed_bytes_supply_candidate_images(tmp_path):
    from pathlib import Path
    from harness.squad_publication import SquadPublicationTransaction
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    target = Path("specs/demo/unknowns.md")
    (project / target).parent.mkdir(parents=True)
    before = b"### U-001: Lighting\r\nOriginal.\r\n"
    after = b"### U-001: Lighting\r\nRevised.\r\n"
    (project / target).write_bytes(before)
    transaction = SquadPublicationTransaction.begin(project, squad, "1" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(after)
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs/demo",), file_paths=()) as snapshot:
        assert snapshot.publication.operations[0].current_bytes == before
        assert snapshot.publication.operations[0].postimage_bytes == after
    from harness.element_identity_candidate_sources import CandidateSourceBinding, assemble_candidate_sources
    result = assemble_candidate_sources(snapshot,
        (CandidateSourceBinding(target.as_posix(), "unknowns.md", "unknowns"),),
        writable_paths=(target.as_posix(),))
    assert not result.diagnostics
    artifact, = result.artifacts
    assert (artifact.path, artifact.role, artifact.before_text, artifact.after_text) == (
        "unknowns.md", "unknowns", before.decode(), after.decode())
    assert (project / target).read_bytes() == before
```

Use the secure-POSIX skip fixture already established in test_squad_publication_sources.py. Real capture must succeed before reaching the new missing-module RED; no mocked publisher or source bytes. Notify root with actual RED before production changes.

- [ ] Write and run the required real regression, retain RED, implement the minimal pure join using the existing initial codec, and verify GREEN.
- [ ] Test exact physical/logical mappings and all supported roles without re-parsing role semantics; complete selected nested/hidden sources, explicit external files, operations outside selected trees, absent tree/member/external versus empty, creation/deletion/no-op, unchanged dependencies and CRLF/multibyte/BOM preservation. Explicitly distinguish prefix siblings, existing directory paths, regular-file ancestors and uncaptured bindings. No unbounded ID parsing is introduced; retain wide/legacy IDs byte-for-byte in fixtures.
- [ ] Test every operation requires exact write permission and explicit typed/opaque classification, including mode-only and no-op writes and deletes. Binary opaque operations succeed only with their explicit permission; typed proposed invalid UTF-8/NUL produces diagnostics; malformed typed before bytes raise. Unchanged unbound binary/hidden files are retained in the caller snapshot and do not fail text assembly.
- [ ] Test strict type/Sequence/unique source-and-artifact paths, damaged frozen fields, invalid/unknown roles, path canonicalization/Unicode, opaque/writable subset/disjointness, sorted diagnostics and artifacts, empty inputs, no mutation and frozen tuple ownership. Reuse codec error behavior for noninitial or inconsistent snapshots without repeating its whole malformed-wire matrix.
- [ ] Integrate a real store with sanitized before/after smoke fixtures: import/adopt before definitions explicitly, capture a real sealed candidate plus retained evidence, assemble images, feed existing check_discovery_candidate, and assert subject_changed/definition_removed with unchanged registry and canonical files. The store is test setup, not an import in the adapter. Compose a positive exact after-image reference through validate_reference_claim_sources and a stale before-hash rejection, without claiming semantic approval. Review clarification: keep the unchanged-evidence smoke fixture, and add a separate real sealed evidence write with distinct valid before/after text; accept the actual proposed after hash and reject the actual retained before hash. An unrelated synthetic hash or equal before/after text does not prove this relationship. New coverage for already-correct assembly need not invent a failing production RED.
- [ ] Show retained assembly still uses original before bytes after a real two-target partial-publication fault and successful retry; freshly captured post/partial snapshots reject via existing initial guard. This proves detached assembly only, not accepted-baseline/seal authority or full crash recovery. After real setup, interdict builtins/io/Path opens, os.open/listdir/scandir/stat and relevant SQLite/network/time/random calls while assembling; no I/O, including Path.open bypass, must occur. Input snapshot remains byte-for-byte identical under independent inventory assertions.
- [ ] Run once final covering modules: new tests/unit/test_element_identity_candidate_sources.py, tests/unit/test_squad_source_baseline_codec.py, tests/unit/test_squad_publication_sources.py, tests/unit/test_discovery_identity_candidate.py, tests/unit/test_element_identity_reference_sources.py. No full/million/live/provider/postcommit repeats. Document boundaries, self-review against scope and exact before images, git diff --check, commit task files and full actual report. Root owns independent review.

## Remaining integration

Review clarification for input normalization: ordinary Exception failures raised during the caller-controlled Sequence snapshot/validation boundary must become the constant ValueError from None, including custom __len__/__getitem__ RuntimeError messages. Do not catch BaseException cancellation/exit signals or broaden this boundary around initial snapshot validation. Invalid snapshots must still retain PublicationError. Keep this change confined to caller-input normalization.

Authenticated complete source selection, durable accepted-source heads, immutable managed-spec/run contracts, semantic review and publication/ledger/graph completion are still required. The assembly helper must not be activated alone or called an authorization service. Later callers bind physical/logical role mappings and scopes to their accepted controller contract, combine all diagnostics with existing structural/target checks and semantic review, and retain the full physical snapshot independently of typed artifacts.
