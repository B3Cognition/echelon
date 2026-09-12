from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import get_type_hints

import pytest


pytestmark = pytest.mark.unit


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SOURCE = (
    "- **FR-1000000**: Preserve source_metric at 1 unit.\n"
    "- **NFR-2000000**: Respond within 1 second.\n"
    "- **AC-3000000**: Given a request, when processed, then the metric is visible.\n"
    "- **ERROR-4000000**: If processing fails, return E300.\n"
)


def projection(source: str = SOURCE, *, term: str = "source_metric", source_sha: str | None = None) -> str:
    digest = _sha(source) if source_sha is None else source_sha
    return f"""# SOURCE: spec.md
# SOURCE_SHA256: {digest}
ARTIFACT: SPEC
TITLE: Snapshot validation

REQ: FR-1000000
GIVEN: a request includes {term}
WHEN: the system processes the request
THEN: the system MUST preserve {term}
OUTPUT: preserved {term}
CONSTRAINT: {term} = 1 unit
EXAMPLE: AC-3000000

REQ: NFR-2000000
GIVEN: a request is made
WHEN: the system responds
THEN: the system MUST respond within 1 second
OUTPUT: a response
EXAMPLE: AC-3000000

AC: AC-3000000
GIVEN: a request includes {term}
WHEN: the system processes the request
THEN: the result exposes {term}

ERROR: ERROR-4000000
WHEN: processing fails
THEN: the system returns an error
ERROR_CODE: E300
"""


def inventory(locator: str = "https://example.test/AC-3000000") -> str:
    return json.dumps({
        "schema_version": 1,
        "sources": [{"id": "U-1000000", "locator": locator, "kind": "web",
                     "status": "read", "disposition": "relevant",
                     "discovered_from": "prompt", "discovery_method": "seed"}],
        "frontier": {"disposition": "complete", "unvisited_relevant_sources": [],
                     "expanded_seed_locators": [locator]},
    })


def seeded_store(tmp_path, source: str = SOURCE):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_lifecycle import ElementAdopt
    from harness.element_identity_store import IdentityStore

    rows = parse_identity_artifact(path="spec.md", role="requirements", text=source).declarations
    store = IdentityStore.initialize(tmp_path)
    store.import_identities(spec_id="demo", operation_id="import", definitions=tuple(
        (row.element_id, row.caption) for row in rows))
    store.apply_lifecycle(spec_id="demo", operation_id="adopt", changes=tuple(
        ElementAdopt(row.element_id, row.caption, row.content) for row in rows))
    return store


def check(store, *, artifacts, projection_sources=(), evidence_inventories=(), scope=None, changes=()):
    from harness.element_identity_candidate import IdentityEditScope

    return store.check_identity_candidate(
        spec_id="demo", artifacts=artifacts,
        scope=scope or IdentityEditScope((), ()), changes=changes,
        projection_sources=projection_sources, evidence_inventories=evidence_inventories,
    )


def codes(result):
    return {item.code for item in result.diagnostics}


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


def test_public_descriptor_annotations_and_exact_type_validation(tmp_path):
    from harness.element_identity_bundle import EvidenceInventoryContext, LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_store import IdentityStore, IdentityStoreError

    hints = get_type_hints(LexiconProjectionSource)
    assert hints == {"projection_path": str, "source_path": str, "glossary_path": str | None}
    assert get_type_hints(EvidenceInventoryContext) == {
        "path": str, "required_seed_locators": tuple[str, ...]}
    wrapper_hints = get_type_hints(IdentityStore.check_identity_candidate)
    assert wrapper_hints["projection_sources"] == Sequence[LexiconProjectionSource]
    assert wrapper_hints["evidence_inventories"] == Sequence[EvidenceInventoryContext]
    store = seeded_store(tmp_path)
    artifacts = (CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),)
    for keyword, value in (
        ("projection_sources", "not-a-sequence"),
        ("projection_sources", [object()]),
        ("evidence_inventories", b"not-a-sequence"),
        ("evidence_inventories", [object()]),
    ):
        with pytest.raises(IdentityStoreError):
            check(store, artifacts=artifacts, **{keyword: value})
    with pytest.raises(IdentityStoreError, match="required_seed_locators"):
        check(store, artifacts=artifacts, evidence_inventories=(
            EvidenceInventoryContext("evidence.json", "seed"),))
    for seeds in (("",), ("  ",), (1,)):
        with pytest.raises(IdentityStoreError, match="seed"):
            check(store, artifacts=artifacts, evidence_inventories=(
                EvidenceInventoryContext("evidence.json", seeds),))
    for bad_path in ("/absolute", "../parent", "a\\b", "a/./b"):
        with pytest.raises(IdentityStoreError, match="path"):
            check(store, artifacts=artifacts, projection_sources=(
                LexiconProjectionSource(bad_path, "spec.md"),))


def test_duplicate_descriptor_primary_paths_are_rejected_before_authority(tmp_path):
    from harness.element_identity_bundle import EvidenceInventoryContext, LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_store import IdentityStoreError

    store = seeded_store(tmp_path)
    artifacts = (CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),)
    with pytest.raises(IdentityStoreError, match="duplicate projection"):
        check(store, artifacts=artifacts, projection_sources=(
            LexiconProjectionSource("p.lexicon", "spec.md"),
            LexiconProjectionSource("p.lexicon", "spec.md"),
        ))
    with pytest.raises(IdentityStoreError, match="duplicate evidence"):
        check(store, artifacts=artifacts, evidence_inventories=(
            EvidenceInventoryContext("evidence.json"), EvidenceInventoryContext("evidence.json")))


def test_corresponding_roles_require_explicit_descriptors(tmp_path):
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), projection()),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(), inventory()),
    ))
    assert codes(result) == {"projection_binding_missing", "inventory_binding_missing"}


@pytest.mark.parametrize(
    ("descriptor", "artifacts", "offending"),
    [
        ("missing-projection", (), "missing.lexicon"),
        ("wrong-projection-role", (("projection.lexicon", "references"),), "projection.lexicon"),
        ("missing-source", (("projection.lexicon", "lexicon_projection"),), "spec.md"),
        ("wrong-source-role", (("projection.lexicon", "lexicon_projection"), ("spec.md", "references")), "spec.md"),
        ("missing-glossary", (("projection.lexicon", "lexicon_projection"), ("spec.md", "requirements")), "glossary.md"),
        ("wrong-glossary-role", (("projection.lexicon", "lexicon_projection"), ("spec.md", "requirements"),
                                 ("glossary.md", "references")), "glossary.md"),
    ],
)
def test_projection_descriptor_associations_must_match_captured_paths_and_roles(
        tmp_path, descriptor, artifacts, offending):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    rows = []
    for path, role in artifacts:
        text = projection() if role == "lexicon_projection" else SOURCE if role == "requirements" else "text\n"
        rows.append(CandidateArtifact(path, role, text, text))
    if not any(row.path == "spec.md" for row in rows):
        rows.append(CandidateArtifact("source-copy.md", "requirements", SOURCE, SOURCE))
    glossary = "glossary.md" if "glossary" in descriptor else None
    result = check(store, artifacts=tuple(rows), projection_sources=(
        LexiconProjectionSource("missing.lexicon" if descriptor == "missing-projection" else "projection.lexicon",
                                "spec.md", glossary),))
    assert any(item.code == "supplemental_binding_mismatch" and item.path == offending
               for item in result.diagnostics)


def test_present_projection_requires_corresponding_source_image(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, None),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), projection()),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),))
    assert any(item.code == "supplemental_binding_mismatch" and "after" in item.detail
               for item in result.diagnostics)


def test_projection_runs_complete_validator_and_exact_typed_authority_match(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    stale = projection(source_sha="0" * 64).replace("NFR-2000000", "NFR-2000001")
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", stale, stale),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),))
    assert "invalid_lexicon_projection" in codes(result)
    assert "projection_authority_mismatch" in codes(result)
    details = [item.detail for item in result.diagnostics if item.code == "invalid_lexicon_projection"]
    assert any("source-hash-mismatch" in detail and "line:" in detail and "before" in detail for detail in details)
    assert any("source-id-missing" in detail for detail in details)


def test_projection_preserves_mixed_legacy_six_and_seven_digit_labels(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    source = (
        "- **FR-001legacy**: Preserve the scene.\n"
        "- **NFR-123456**: Respond promptly.\n"
        "- **AC-1234567**: Given a scene, when rendered, then it remains visible.\n"
        "- **ERROR-7654321**: If rendering fails, return E765.\n"
    )
    derived = f"""# SOURCE: spec.md
# SOURCE_SHA256: {_sha(source)}
ARTIFACT: SPEC
TITLE: Mixed labels

REQ: FR-001legacy
GIVEN: a scene is available
WHEN: it renders
THEN: the system MUST preserve the scene
OUTPUT: a preserved scene
EXAMPLE: AC-1234567

REQ: NFR-123456
GIVEN: a scene is available
WHEN: it renders
THEN: the system MUST respond promptly
OUTPUT: a prompt response
EXAMPLE: AC-1234567

AC: AC-1234567
GIVEN: a scene is available
WHEN: it renders
THEN: the scene remains visible

ERROR: ERROR-7654321
WHEN: rendering fails
THEN: the system returns an error
ERROR_CODE: E765
"""
    store = seeded_store(tmp_path, source)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", source, source),
        CandidateArtifact("projection.lexicon", "lexicon_projection", derived, derived),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),))
    assert result.diagnostics == ()


def test_optional_glossary_uses_exact_image_and_never_implicit_filename(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    governed = projection(term="governed_metric")
    no_descriptor = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("glossary.md", "glossary", "governed_metric\n", "governed_metric\n"),
        CandidateArtifact("projection.lexicon", "lexicon_projection", governed, governed),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),))
    assert any("unresolved-term" in item.detail for item in no_descriptor.diagnostics)
    from harness.element_identity_candidate import IdentityEditScope
    explicit = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("glossary.md", "glossary", None, "governed_metric\n"),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), governed),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md", "glossary.md"),),
       scope=IdentityEditScope(("glossary.md",), (), ("glossary.md",)))
    assert not any(item.code == "invalid_lexicon_projection" for item in explicit.diagnostics)


def test_projection_scope_is_owned_by_projection_not_source(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    before = projection()
    changed_block = before.replace("the result exposes source_metric", "the result visibly exposes source_metric")
    artifacts = (
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", before, changed_block),
    )
    descriptor = (LexiconProjectionSource("projection.lexicon", "spec.md"),)
    wrong_artifact = check(store, artifacts=artifacts, projection_sources=descriptor,
                           scope=IdentityEditScope(("spec.md",), ("AC-3000000",)))
    assert "artifact_out_of_scope" in codes(wrong_artifact)
    wrong_element = check(store, artifacts=artifacts, projection_sources=descriptor,
                          scope=IdentityEditScope(("projection.lexicon",), ()))
    assert "element_out_of_scope" in codes(wrong_element)
    allowed = check(store, artifacts=artifacts, projection_sources=descriptor,
                    scope=IdentityEditScope(("projection.lexicon",), ("AC-3000000",)))
    assert allowed.diagnostics == ()


def test_projection_metadata_change_requires_unowned_text_permission(tmp_path):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    before = projection()
    after = before.replace("TITLE: Snapshot validation", "TITLE: Reviewed snapshot")
    artifacts = (CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
                 CandidateArtifact("projection.lexicon", "lexicon_projection", before, after))
    descriptor = (LexiconProjectionSource("projection.lexicon", "spec.md"),)
    denied = check(store, artifacts=artifacts, projection_sources=descriptor,
                   scope=IdentityEditScope(("projection.lexicon",), ()))
    assert "unowned_text_changed" in codes(denied)
    allowed = check(store, artifacts=artifacts, projection_sources=descriptor,
                    scope=IdentityEditScope(("projection.lexicon",), (), ("projection.lexicon",)))
    assert allowed.diagnostics == ()


def test_source_revision_requires_refreshed_projection_and_exact_scopes(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope
    from harness.element_identity_lifecycle import ElementRevision

    store = seeded_store(tmp_path)
    revised_source = SOURCE.replace("source_metric", "revised_metric")
    old_rows = {row.element_id: row for row in parse_identity_artifact(
        path="spec.md", role="requirements", text=SOURCE).declarations}
    new_rows = {row.element_id: row for row in parse_identity_artifact(
        path="spec.md", role="requirements", text=revised_source).declarations}
    change = (ElementRevision("FR-1000000", "1", old_rows["FR-1000000"].caption,
                              new_rows["FR-1000000"].content),)
    descriptor = (LexiconProjectionSource("projection.lexicon", "spec.md"),)
    stale = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, revised_source),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), projection()),
    ), projection_sources=descriptor,
       scope=IdentityEditScope(("spec.md",), ("FR-1000000",)), changes=change)
    assert any(item.code == "invalid_lexicon_projection" and "after" in item.detail
               and "source-hash-mismatch" in item.detail for item in stale.diagnostics)

    refreshed = projection(revised_source, term="revised_metric")
    valid = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, revised_source),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), refreshed),
    ), projection_sources=descriptor,
       scope=IdentityEditScope(
           ("spec.md", "projection.lexicon"),
           ("FR-1000000", "AC-3000000"),
           ("projection.lexicon",),
       ), changes=change)
    assert valid.diagnostics == ()


def test_changed_projection_cannot_inherit_old_projection_reference_assessment(tmp_path):
    from harness.element_artifacts import parse_identity_artifact
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    before = projection()
    parsed = parse_identity_artifact(
        path="projection.lexicon", role="lexicon_projection", text=before)
    reference = next(item for item in parsed.references if item.target_id == "AC-3000000")
    store.record_reference_claims(spec_id="demo", operation_id="claim", claims=(ReferenceClaim(
        "projection.lexicon", parsed.content_sha256,
        f"span:{reference.span.start}:{reference.span.end}",
        reference.target_id, "1", reference.relation),))
    original = tuple(store.reference_claims(
        spec_id="demo", source_path="projection.lexicon", source_sha256=parsed.content_sha256))
    descriptor = (LexiconProjectionSource("projection.lexicon", "spec.md"),)

    unchanged = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", before, before),
    ), projection_sources=descriptor)
    retained = next(item for item in unchanged.references
                    if item.start == reference.span.start and item.target_id == reference.target_id)
    assert retained.assessed_revisions == ("1",)
    assert retained.assessment_state == "current"

    after = before.replace(
        "the result exposes source_metric", "the result visibly exposes source_metric")
    changed = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", before, after),
    ), projection_sources=descriptor,
       scope=IdentityEditScope(("projection.lexicon",), ("AC-3000000",)))
    new_claim = next(item for item in changed.references
                     if item.start == reference.span.start and item.target_id == reference.target_id)
    assert changed.diagnostics == ()
    assert new_claim.source_sha256 == _sha(after)
    assert new_claim.assessed_revisions == ()
    assert new_claim.assessment_state == "unassessed"
    assert tuple(store.reference_claims(
        spec_id="demo", source_path="projection.lexicon",
        source_sha256=parsed.content_sha256)) == original


@pytest.mark.parametrize("before_present", [False, True])
def test_projection_can_be_introduced_or_removed_without_duplicate_lifecycle(tmp_path, before_present):
    from harness.element_identity_bundle import LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    derived = projection()
    before, after = (derived, None) if before_present else (None, derived)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", before, after),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),),
       scope=IdentityEditScope(("projection.lexicon",),
                               ("FR-1000000", "NFR-2000000", "AC-3000000"),
                               ("projection.lexicon",)))
    assert result.diagnostics == ()


def test_inventory_validates_exact_snapshot_without_inferred_identity_facts(tmp_path):
    from harness.element_identity_bundle import EvidenceInventoryContext
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    locator = "https://example.test/AC-3000000"
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(locator), inventory(locator)),
    ), evidence_inventories=(EvidenceInventoryContext("evidence.json", (locator,)),))
    assert result.diagnostics == ()
    assert result.references == ()


@pytest.mark.parametrize("captured_role", [None, "references"])
def test_inventory_descriptor_must_name_a_captured_inventory_role(tmp_path, captured_role):
    from harness.element_identity_bundle import EvidenceInventoryContext
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    artifacts = [CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE)]
    if captured_role is not None:
        artifacts.append(CandidateArtifact("evidence.json", captured_role, inventory(), inventory()))
    result = check(store, artifacts=tuple(artifacts),
                   evidence_inventories=(EvidenceInventoryContext("evidence.json"),))
    assert any(item.code == "supplemental_binding_mismatch" and item.path == "evidence.json"
               for item in result.diagnostics)


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "not valid JSON"),
        ("[]", "root must be an object"),
        (json.dumps({"schema_version": 2}), "schema_version must equal 1"),
        (json.dumps({"schema_version": 1, "sources": []}), "sources must not be empty"),
        (inventory(), "missing declared source seed"),
    ],
)
def test_inventory_reports_shared_validator_errors(tmp_path, text, fragment):
    from harness.element_identity_bundle import EvidenceInventoryContext
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    seeds = ("missing",) if fragment.startswith("missing") else ()
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("evidence.json", "evidence_inventory", text, text),
    ), evidence_inventories=(EvidenceInventoryContext("evidence.json", seeds),))
    finding = next(item for item in result.diagnostics if item.code == "invalid_evidence_inventory")
    assert fragment in finding.detail


def test_absent_inventory_image_is_not_parsed_but_present_empty_is_invalid(tmp_path):
    from harness.element_identity_bundle import EvidenceInventoryContext
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    context = (EvidenceInventoryContext("evidence.json"),)
    absent = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(), None),
    ), evidence_inventories=context,
       scope=IdentityEditScope(("evidence.json",), (), ("evidence.json",)))
    assert absent.diagnostics == ()
    empty = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(), ""),
    ), evidence_inventories=context,
       scope=IdentityEditScope(("evidence.json",), (), ("evidence.json",)))
    assert any(item.code == "invalid_evidence_inventory" and "after" in item.detail
               for item in empty.diagnostics)


def test_inventory_whole_text_change_requires_artifact_and_unowned_scope(tmp_path):
    from harness.element_identity_bundle import EvidenceInventoryContext
    from harness.element_identity_candidate import CandidateArtifact, IdentityEditScope

    store = seeded_store(tmp_path)
    before = inventory()
    after = inventory("https://example.test/revised")
    artifacts = (CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
                 CandidateArtifact("evidence.json", "evidence_inventory", before, after))
    context = (EvidenceInventoryContext("evidence.json"),)
    denied = check(store, artifacts=artifacts, evidence_inventories=context)
    assert {"artifact_out_of_scope", "unowned_text_changed"} <= codes(denied)
    allowed = check(store, artifacts=artifacts, evidence_inventories=context,
                    scope=IdentityEditScope(("evidence.json",), (), ("evidence.json",)))
    assert allowed.diagnostics == ()


def test_supplemental_validation_never_reads_declared_paths(tmp_path, monkeypatch):
    from harness.element_identity_bundle import EvidenceInventoryContext, LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)

    def fail(*_args, **_kwargs):
        raise AssertionError("supplemental integration accessed the filesystem")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(Path, "read_bytes", fail)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), projection()),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(), inventory()),
    ), projection_sources=(LexiconProjectionSource("projection.lexicon", "spec.md"),),
       evidence_inventories=(EvidenceInventoryContext("evidence.json"),))
    assert result.diagnostics == ()


def test_descriptor_and_seed_sequences_are_snapshotted_before_one_query_only_transaction(tmp_path, monkeypatch):
    from harness.element_identity_bundle import EvidenceInventoryContext, LexiconProjectionSource
    from harness.element_identity_candidate import CandidateArtifact

    store = seeded_store(tmp_path)
    projections = [LexiconProjectionSource("projection.lexicon", "spec.md")]
    seeds = ["https://example.test/AC-3000000"]
    inventories = [EvidenceInventoryContext("evidence.json", seeds)]
    transaction = store._transaction
    entered = 0

    @contextmanager
    def read_transaction():
        nonlocal entered
        entered += 1
        projections.clear()
        inventories.clear()
        seeds.clear()
        with transaction() as connection:
            yield connection
            assert connection.execute("PRAGMA query_only").fetchone()[0] == 1

    monkeypatch.setattr(store, "_transaction", read_transaction)
    result = check(store, artifacts=(
        CandidateArtifact("spec.md", "requirements", SOURCE, SOURCE),
        CandidateArtifact("projection.lexicon", "lexicon_projection", projection(), projection()),
        CandidateArtifact("evidence.json", "evidence_inventory", inventory(), inventory()),
    ), projection_sources=projections, evidence_inventories=inventories)
    assert result.diagnostics == ()
    assert entered == 1
