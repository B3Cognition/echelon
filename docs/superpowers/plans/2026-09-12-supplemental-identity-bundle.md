# Supplemental identity bundle implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend the inactive general candidate checker to explicitly associated derived Lexicon, glossary and JSON source-inventory snapshots without treating them as new identity definitions.

**Architecture:** Add immutable controller-supplied source/context descriptors and a pure supplemental validation module. Integrate it into the existing one-transaction general checker, using reviewed text validators and existing typed Lexicon projection facts. Keep discovery's narrower API unchanged and retain all authoritative definition, scope, lifecycle and reference checks.

**Tech Stack:** Python dataclasses, existing pure artifact validators and identity store, pytest; no dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-durable-element-identities-design.md`

## Global Constraints

- Work only in the existing delivery-controller-contract worktree; no global installation, main mutation, or stopped-smoke edits.
- Keep existing human-readable IDs and graph keys stable. Record identity revisions, lifecycle events, and reference provenance beside them.
- A content hash is a revision/integrity binding, not the entity identity.
- Typed adapters distinguish definitions from references in supported Markdown, task rows, Lexicon, and investigation artifacts.
- Keep failed candidates as diagnostics; do not update canonical artifacts, graphs, or memory from rejected candidates.
- No new parser grammar, JSON schema, database schema, allocation, semantic approval, publisher or live activation in this task.
- Detected damaged authority continues to raise IdentityStoreError. All caller collections are snapshotted before the same one query-only transaction; no nested public store calls.

---

### Task 1: explicit supplemental source associations and scoped snapshots

**Files:** Create `src/harness/element_identity_bundle.py` and `tests/unit/test_supplemental_identity_bundle.py`; modify `src/harness/element_identity_candidate.py`, `src/harness/element_identity_candidate_store.py`, the thin general wrapper in `src/harness/element_identity_store.py`, and `docs/element-identity-candidates.md`. Update former general-wrapper unsupported-projection tests to assert its new explicit association requirement; preserve narrow discovery restrictions. Reuse the reviewed snapshot APIs from `harness.spec_lexicon_gate` and `harness.evidence_inventory` without altering their rules. If integration needs a parser, schema or representation change, report before implementing it.

**Dependencies:** Implement only after `2026-09-12-artifact-validation-snapshots.md` passes independent review. The preceding definition checker includes the reviewed distinction between an absent image (`None`) and a present empty document (`""`); inspect and preserve its current `_parse_image` behavior.

**New public descriptors**, exported from `harness.element_identity_bundle`:

```python
@dataclass(frozen=True, slots=True)
class LexiconProjectionSource:
    projection_path: str
    source_path: str
    glossary_path: str | None = None

@dataclass(frozen=True, slots=True)
class EvidenceInventoryContext:
    path: str
    required_seed_locators: tuple[str, ...] = ()
```

Add these optional keyword parameters to the existing general `IdentityStore.check_identity_candidate`, retaining its other parameters and exact result type:

```python
projection_sources: Sequence[LexiconProjectionSource] = ()
evidence_inventories: Sequence[EvidenceInventoryContext] = ()
```

Preserve `check_discovery_candidate` and its strict scope/role contract exactly. Do not add a new public checker, arbitrary caller-selected policy or publication-success flag. The general role set adds `lexicon_projection`, `glossary` and `evidence_inventory`; ISS occurrence authorization remains unsupported. New descriptors are structural controller assertions, not persisted binding receipts or evidence of semantic approval.

Validate/snapshot exact descriptor types, both outer sequences and each seed-locator sequence before opening authority. Wrong types, malformed canonical POSIX paths, duplicate descriptor primary paths and non-string/blank seed locators raise IdentityStoreError through the existing public boundary. Preserve exact locator strings; do not normalize them. Structural association defects are candidate diagnostics: missing descriptor for a corresponding role, descriptor path missing from the captured bundle, wrong role at a referenced path, absent source image for a present projection image, or unused/mismatched descriptor. Use `projection_binding_missing`, `inventory_binding_missing` and `supplemental_binding_mismatch` with offending path and useful detail. No missing descriptor silently grants empty required-seed coverage.

Every projection descriptor must name a captured `lexicon_projection` artifact and a captured authoritative `requirements` source. An optional glossary path must name a captured `glossary` artifact. A declared glossary may be absent in one image; then pass None to the text validator for that image. With no glossary descriptor, use no glossary; never find one by filename or read it from disk. Multiple explicitly associated projections of one source are allowed representations, not duplicate authoritative definitions. At most one source descriptor is permitted per projection path. Do not silently choose among multiple authoritative source definitions.

For each present before/after projection image, call `validate_spec_lexicon_texts` with the corresponding exact source/glossary images and the source basename, with `artifact_type="SPEC"`. Missing source or non-requirement source is a blocking association diagnostic, not a fallback. Convert every complete validation finding into `invalid_lexicon_projection` with original code/message/line and before/after image in detail; keep existing parser diagnostics too. Preserve whole grammar/validity, source metadata/hash, all existing source-ID checks including ERROR-family checks, governed terms and glossary rules. Do not replace this with an ID-set-only approximation.

Additionally compare the managed FR/NFR/AC projection declarations to the typed declarations of its named source image using exact labels. Any mismatch is `projection_authority_mismatch`. This closes differences between the legacy source-contract extractor and managed typed ownership; it does not register ERROR or other families as new identities. The source artifact independently passes ordinary registry baseline/lifecycle validation. A projection's block content must not be compared to the authoritative registry content, and its declarations must not enter the authoritative definition/ordinal maps. Native `lexicon` declarations remain authoritative and still conflict with a duplicate Markdown source.

Keep derived declaration spans in the existing scope checker. Rewriting a derived block requires its exact element ID and artifact permission; granting permission for a source file does not authorize its projection file. Header/source-hash/glossary changes outside declaration spans require the existing `unowned_text_paths` permission. Projection introduction/removal can be scoped without inventing a second lifecycle event when the authoritative source identity is already preserved/created/retired correctly. Preserve ordinary source ancestor/descendant checks and None-versus-empty behavior.

Glossary and inventory roles have no managed declarations or implicit element references. Represent their exact present text as an empty typed fact set with its actual UTF-8 SHA256; absence remains the existing empty fact image. Their entire changed text therefore requires artifact plus unowned-text permission. For every present inventory image, run `validate_evidence_inventory_text` with the exact declared seed snapshot. Return `invalid_evidence_inventory` with original structural/seed error detail. A present empty JSON file is invalid; an absent image is not parsed. Never scan source IDs, glossary terms or URLs for managed labels.

Projection references still use the shared exact-label/current-or-projected target resolution and reference-claim logic, including inactive dependency and unsupported-range diagnostics. Reference claims retain the projection's own path/hash/span, never its source's path/hash or an inferred current assessment. Changed projection content cannot inherit old projection evidence. Structural source equivalence does not prove semantic faithfulness; later publication review must include changed derived wording even when the authoritative revision is unchanged.

- [ ] Write this real-storage projection test before implementation. It imports/adopts only the source's typed declarations, then submits unchanged source/projection with the explicit descriptor:

```python
def test_projection_does_not_duplicate_authoritative_definitions(tmp_path):
    from contextlib import closing
    import hashlib
    import sqlite3
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    source = ("- **FR-001**: Preserve the visible scene.\n"
              "- **AC-001**: Given the scene, when rendered, then it remains visible.\n")
    source_sha = hashlib.sha256(source.encode("utf-8")).hexdigest()
    derived = f"""# SOURCE: spec.md
# SOURCE_SHA256: {source_sha}
ARTIFACT: SPEC
TITLE: Visible scene

REQ: FR-001
GIVEN: the scene is available
WHEN: it renders
THEN: the system MUST preserve the visible scene
OUTPUT: a visible scene
EXAMPLE: AC-001

AC: AC-001
GIVEN: the scene is available
WHEN: it renders
THEN: the visible scene is preserved
"""
    rows = parse_identity_artifact(path="spec.md", role="requirements", text=source).declarations
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple(
        (row.element_id, row.caption) for row in rows))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(
        ElementAdopt(row.element_id, row.caption, row.content) for row in rows))

    def logical_state():
        with closing(sqlite3.connect(tmp_path / ".echelon/identity/registry.sqlite3")) as connection:
            return tuple(connection.iterdump())

    original = logical_state()
    result = store.check_identity_candidate(
        spec_id="demo",
        artifacts=(CandidateArtifact("spec.md", "requirements", source, source),
                   CandidateArtifact("requirements.lexicon.md", "lexicon_projection", derived, derived)),
        scope=IdentityEditScope((), ()),
        projection_sources=(LexiconProjectionSource("requirements.lexicon.md", "spec.md"),),
    )
    assert result.diagnostics == ()
    assert logical_state() == original
    assert store.lookup(spec_id="demo", element_id="FR-001")["content"] == rows[0].content
```

- [ ] Run `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m pytest tests/unit/test_supplemental_identity_bundle.py -q`; retain behavioral RED before implementing APIs/integration. Imports inside the collected test make the expected missing API a behavioral failure rather than a collection failure.
- [ ] Add source/projection regressions before their behavior: missing/wrong/duplicate descriptors; missing corresponding source image; wrong source role; stale source hash; exact-label mismatch; changed source with stale derived output; valid scoped source revision plus refreshed projection; changed derived block outside element scope; changed projection file outside artifact scope; header metadata outside unowned scope; introduced/removed projection; absent versus present-empty images; optional glossary absence and changed governed terms; existing native Lexicon/Markdown duplicate rejection.
- [ ] Add real mixed-family/legacy/six- and seven-digit cases. Preserve the full original discovery smoke, authoritatively bound source content, complete SQL logical prestate and unchanged original evidence receipts. Changed projection content with the same source revision must have unassessed new-source claims rather than inherited assessment.
- [ ] Add inventory/glossary regressions before their behavior: valid exact captured JSON; all existing source/frontier/required-seed errors through the shared validator; missing context descriptor; source IDs and URLs shaped like U/AC labels do not become definitions/references; no reads of declared paths; strict descriptor/seed snapshots under the one query-only transaction; present empty versus absent inventory; artifact/unowned scope enforcement.
- [ ] Implement pure descriptor normalization and supplemental checks in the focused new module. Extend existing general policy/parse boundary and authoritative-map disposition filtering without copying the candidate algorithm or creating another publication owner. Keep tuple snapshots and exact public type annotations resolvable.
- [ ] Run new bundle tests plus `tests/unit/test_definition_identity_candidate.py`, `tests/unit/test_discovery_identity_candidate.py`, `tests/unit/test_element_artifacts.py`, `tests/unit/test_element_artifact_lexicon.py`, `tests/unit/test_element_identity_lifecycle.py`, `tests/unit/test_element_identity_bindings.py`, `tests/unit/test_artifact_validation_snapshots.py` and `tests/unit/test_spec_lexicon_gate.py`.
- [ ] Update role/association documentation and explicit remaining boundaries. Self-review, run `git diff --check`, commit only task files, retain complete RED/GREEN commands/output and review gaps in the ignored task report.

## Following work

Issue occurrence authorization, interval/qualified reference resolution, historical import/audit tools, canonical/staged authentication, semantic review, durable publication intents/receipts, graph/memory lifecycle consumers, managed producers and bounded repair remain required. The general checker remains inactive and cannot authenticate completeness or authorize publication on its own.
