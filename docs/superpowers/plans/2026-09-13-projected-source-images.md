# Projected source images implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Expose the exact complete projected source bytes already computed by the publisher, together with their existing manifest fingerprint, for later captured graph construction.

**Architecture:** Return detached existing source-image records from the existing pure transformation before it discards bytes into a metadata manifest. Both the public manifest projection and the guarded publisher's private prefix projection keep using that single transformation and unchanged metadata semantics.

**Tech Stack:** Frozen Python source snapshot records, existing canonical source-manifest factory, sealed-operation projection and offline real-POSIX publication tests.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- IDs travel through interfaces as strings.
- Historical evidence is retained, not relabeled as proof of the new content.
- No new allocation, lifecycle, graph, memory, provider, state or publication writer is activated.
- Preserve existing sealed-operation ordering, selected-source membership, new-directory modes, canonical manifest bytes, prefix-progress rules and sole publication/lock ownership.
- Projected bytes are a prediction from a validated supplied initial snapshot, not a fresh capture, original recovery baseline, semantic judgment, accepted-source receipt or proof of source selection completeness.

---

### Task 1: expose detached projected images through the existing transformer

**Files:** Modify only `src/harness/squad_source_projection.py` in production. Create `tests/unit/test_squad_source_projection_images.py`; existing source projection/guard tests may gain focused compatibility assertions. Document in `docs/element-identity-storage.md`. Do not change capture, guard or promotion algorithms, snapshot/manifest wire formats, codecs, schema/identity/state/controller/provider/CLI/graph/memory production or prose. Root owns plan/ledger.

**Public interface in squad_source_projection.py:**

```python
@dataclass(frozen=True, slots=True)
class ProjectedPublicationSources:
    trees: tuple[ProjectTreeSnapshot, ...]
    files: tuple[ProjectPathSnapshot, ...]
    manifest: SourceManifestSnapshot

def project_publication_source_images(
    initial: PublicationSourcesSnapshot,
) -> ProjectedPublicationSources:
    ...
```

Use existing ProjectDirectorySnapshot/ProjectFileSnapshot/ProjectTreeSnapshot/ProjectPathSnapshot/PublicationImageDescriptor and SourceManifestSnapshot types. This new DTO deliberately has no publication marker/promoted-prefix fields and is not a PublicationSourcesSnapshot; do not fabricate an initial or final physical capture by replacing its publication header. It is a value carrier, not an acceptance validator for caller-constructed instances.

The new public function validates the original initial snapshot through existing `encode_initial_publication_sources`, just as the current manifest projector does; noninitial prefixes, wrong types/damaged frozen values, invalid byte/hash/mode/layout and target conflicts continue to reject under existing PublicationError rules. Reuse the existing transformation's complete operation/tree/selected-file logic. Extract a narrow private transformation returning the new DTO if needed. Keep `_transform_selected_sources(initial, prefix, *, new_directories=()) -> SourceManifestSnapshot` with its existing signature and meaning because squad_source_guard consumes it for interrupted prefixes and next-write parent progress. It may delegate to the shared image transformer and return `.manifest`. Keep `project_publication_source_manifest(initial)` public signature and byte-identical result, preferably returning the new public projection's `.manifest`. No copied second projection loop, per-file policy fork or new partial-prefix public API.

Return the exact final selected tree/file images after all sealed operations: unchanged hidden/binary/empty files, write/delete/mode-only/no-op changes, all surviving directory modes and complete membership, canonical-mode newly required parents, and missing/empty tree and selected-file distinctions. Operations outside selected sources retain existing behavior; this helper does not expand selection or claim it was complete. Preserve component-wise path rules and the existing rejection of impossible file/ancestor/tree-root operations.

Construct fresh nested record objects for the result, including retained unchanged directory/file/path records and PublicationImageDescriptor records, while preserving immutable bytes/strings exactly. No result may depend on later `object.__setattr__` damage to a caller-held frozen input record. The manifest is generated/validated once from those exact output tuples through the existing snapshot_source_manifest factory; `snapshot_source_manifest(trees=result.trees, files=result.files) == result.manifest` and `result.manifest == project_publication_source_manifest(initial)` must hold. Keep canonical sorting unchanged, no new integer/padding interpretation, serialization format or content decoding.

The transformation uses no filesystem, stat, process, environment, clock, randomness, socket, provider, identity database, locks or writes. It does not reread canonical/staged paths. Do not add a temporary tree, savepoint, copy database, writer callback or physical freshness claim. Pure cases must not inherit a blanket POSIX skip; only real secure-publication tests use the existing capability guard.

**First actual RED before production:** Build a real sealed publication with a write into a selected tree and capture its actual initial source snapshot using existing APIs, then call the missing function through the existing module. Required setup follows existing test_squad_source_projection.py:

```python
import harness.squad_source_projection as projection
from pathlib import Path
from harness.squad_publication import SquadPublicationTransaction

def test_projected_images_match_real_guarded_publication(tmp_path, secure_posix):
    project = tmp_path.resolve()
    squad = project / "runs/spec-test"
    squad.mkdir(parents=True)
    (project / "specs").mkdir()
    (project / "specs/.keep").write_bytes(b"\x00\xff")
    transaction = SquadPublicationTransaction.begin(project, squad, "2" * 32)
    stage = transaction.build_path("after.md")
    stage.write_bytes(b"FR-1000000\r\nnew")
    target = Path("specs/nested/new.md")
    transaction.add_write(target, stage, owned_paths={target})
    prepared = transaction.seal()
    with prepared.inspect_sources(tree_paths=("specs",)) as initial:
        assert initial.trees[0].files[0].content == b"\x00\xff"
    expected_manifest = projection.project_publication_source_manifest(initial)
    result = projection.project_publication_source_images(initial)
    assert result.manifest == expected_manifest
    final = prepared.publish_sources(initial)
    assert result.trees == final.trees
    assert result.files == final.files
```

Define secure_posix using the existing capability-check fixture pattern. Real begin/stage/seal/initial capture and current manifest projection must succeed before AttributeError for the missing new function. Notify root of actual RED before production. Expand the test with independently constructed complete expected nested records/modes/bytes/manifest; shared-transform equality alone is insufficient.

- [ ] Write/run the actual first regression using `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest` from this worktree. Standalone Python requires PYTHONPATH=src. Notify root of the exact RED before production, then implement the smallest shared extraction and obtain GREEN.
- [ ] Add independent complete expected trees, directories, files, image descriptors, bytes and manifest payload/hash for mixed write/delete/mode-only/no-op operations, untouched hidden/binary/empty files, preserved nondefault directory/file modes, selected missing/empty files and missing/empty trees, multi-level new parents and sibling/component-prefix cases. Verify all outputs, not counts or any-one-file modes.
- [ ] Verify all nested output records are detached from initial records and frozen; explicitly damage original unchanged directory/file/image/path records after result creation and assert result remains equal to the independently retained expectation. Original inputs are unchanged by normal projection. This is detachment testing, not a guarantee against arbitrary mutation of the returned object itself.
- [ ] Test malformed original images, hashes, modes, types/subclasses, nonzero prefix and impossible target/ancestor layouts against existing rejection behavior; preserve the original manifest projector's outputs and error classes/codes. Passing the new DTO to the original-baseline codec must reject rather than impersonate a physical initial capture.
- [ ] Exercise real guarded publication and interrupted-prefix recovery with the original snapshot retained: exact projected final tuples/manifest equal the actual final capture after restart/reload, including mode-only and new parents. Private prefix `_transform_selected_sources` must still match actual intermediate source observations and existing allowed partial-parent behavior; no guard relaxation.
- [ ] Run all pure cases with scoped no-I/O/no-process/no-authority tripwires after fixture creation/import; no blanket POSIX skip. Real byte equality is not source-selection, semantic, graph or receipt authentication.
- [ ] Run once the covering modules under tests/unit: `test_squad_source_projection_images.py`, `test_squad_source_projection.py`, `test_squad_source_guard.py`, `test_squad_source_manifest.py`, `test_squad_publication_sources.py`, `test_element_identity_source_store.py`. Existing source-store tests protect expected manifest/application ownership compatibility. No full-unit/capacity/live/provider/global install or unchanged postcommit repeat. Later amendments get named focused coverage and exact chronology.
- [ ] Self-review one projection policy, legacy public/private result compatibility, exact nested detachment/manifest agreement and no physical side effects; document/diff-check/commit scoped files and full report. Root supplies fresh original-BASE review after DONE.

## Remaining integration

This supplies projected selected bytes, not a complete captured graph builder. A trusted graph owner still needs complete source selection, logical source mapping, additional policy/memory/RE/topology inputs and graph sealing, followed by managed producer/runtime/semantic/completion and bounded repair integration. No live caller is switched here.
