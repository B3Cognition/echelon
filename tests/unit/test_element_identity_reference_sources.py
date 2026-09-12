"""Exact proposed reference claims against caller-supplied postimages."""

import hashlib
from collections.abc import Sequence
from dataclasses import replace

import pytest


pytestmark = pytest.mark.unit


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artifact(path, role, text, *, before=None):
    from harness.element_identity_candidate import CandidateArtifact

    return CandidateArtifact(path, role, before, text)


def _claim(path, text, anchor, target, relation="reference", revision=None):
    from harness.element_identity_bindings import ReferenceClaim

    return ReferenceClaim(path, _digest(text), anchor, target, revision, relation)


def test_existing_target_does_not_authenticate_a_wrong_source_anchor(tmp_path):
    from harness.element_identity_store import IdentityStore
    from harness.element_identity_lifecycle import ElementCreate
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact

    store = IdentityStore.initialize(tmp_path)
    label, = store.reserve(spec_id="demo", kind="FR", operation_id="reserve", count=1)
    store.apply_lifecycle(spec_id="demo", operation_id="create", changes=(
        ElementCreate(label, "Scene", "Scene body.", "reserve"),
    ))
    text = "Before " + label
    claim = ReferenceClaim("evidence.md", hashlib.sha256(text.encode()).hexdigest(),
                           "span:0:9", label, "1", "evidence")
    assert store.validate_projected_bindings(spec_id="demo", claims=(claim,)) is None

    from harness.element_identity_reference_sources import validate_reference_claim_sources
    result = validate_reference_claim_sources(
        (CandidateArtifact("evidence.md", "evidence", text, text),), (claim,),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]


@pytest.mark.parametrize("label", [
    "U-000001", "A-000001", "FR-000001", "NFR-000001", "AC-000001",
    "T-000001", "ISS-000001", "T-S01a", "AC-001a", "AC-1000000",
    "FR-" + "9" * 5000,
], ids=["unknown", "assumption", "functional", "nonfunctional", "criterion",
        "task", "issue", "legacy", "composite", "seven-digit", "five-thousand-digit"])
def test_exact_reference_spans_support_all_identity_spellings(label):
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = f"See {label}."
    claim = _claim("references.md", text, f"span:4:{4 + len(label)}", label)
    assert validate_reference_claim_sources(
        (_artifact("references.md", "references", text),), (claim,)
    ) == ()


def test_repeated_labels_multiple_sources_and_historical_revisions_are_source_compatible():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    first = "FR-000001 then FR-000001"
    second = "Evidence for AC-1000000"
    claims = (
        _claim("references.md", first, "span:0:9", "FR-000001", revision=None),
        _claim("references.md", first, "span:15:24", "FR-000001", revision="7"),
        _claim("references.md", first, "span:0:9", "FR-000001", revision="999"),
        _claim("evidence.md", second, "span:13:23", "AC-1000000", "evidence", "3"),
    )
    artifacts = (
        _artifact("references.md", "references", first),
        _artifact("evidence.md", "evidence", second),
    )
    assert validate_reference_claim_sources(artifacts, claims) == ()


def test_all_four_relations_and_markdown_contexts_match_real_parser_outputs():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    references = "See FR-000001."
    evidence = "Observed AC-000001."
    tasks = (
        "- [ ] T-000001 complexity=standard phase=core "
        "req=FR-000001 depends=T-000002\n  **Title:** Task.\n"
    )
    claims = (
        _claim("references.md", references, "span:4:13", "FR-000001"),
        _claim("evidence.md", evidence, "span:9:18", "AC-000001", "evidence"),
        _claim("tasks.md", tasks, f"span:{tasks.index('FR-000001')}:{tasks.index('FR-000001') + 9}",
               "FR-000001", "requires"),
        _claim("tasks.md", tasks, f"span:{tasks.index('T-000002')}:{tasks.index('T-000002') + 8}",
               "T-000002", "depends"),
    )
    artifacts = (
        _artifact("references.md", "references", references),
        _artifact("evidence.md", "evidence", evidence),
        _artifact("tasks.md", "tasks", tasks),
    )
    assert validate_reference_claim_sources(artifacts, claims) == ()


def test_lexicon_dependency_uses_exact_source_span():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = (
        "ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-000001\n"
        "GIVEN: a player\nWHEN: play begins\nTHEN: movement works\n"
        "DEPENDS: FR-000002\n"
    )
    start = text.index("FR-000002")
    claim = _claim("requirements.lexicon", text, f"span:{start}:{start + 9}",
                   "FR-000002", "depends")
    assert validate_reference_claim_sources(
        (_artifact("requirements.lexicon", "lexicon", text),), (claim,)
    ) == ()


def test_unicode_crlf_spans_are_code_points_while_hashes_use_original_utf8_bytes():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "Résumé ⚡\r\nSee FR-000001\r\n"
    claim = _claim("résumé.md", text, "span:14:23", "FR-000001")
    assert claim.source_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert validate_reference_claim_sources(
        (_artifact("résumé.md", "references", text),), (claim,)
    ) == ()


def test_missing_after_image_never_falls_back_to_before_or_other_paths():
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001"
    claims = (
        _claim("before-only.md", text, "span:0:9", "FR-000001"),
        _claim("not-supplied.md", text, "span:0:9", "FR-000001"),
    )
    result = validate_reference_claim_sources(
        (CandidateArtifact("before-only.md", "references", text, None),), claims
    )
    assert [(item.code, item.path, item.detail) for item in result] == [
        ("reference_source_missing", "before-only.md", "claim requires a present supplied after image"),
        ("reference_source_missing", "not-supplied.md", "claim requires a present supplied after image"),
    ]


def test_empty_present_source_is_distinct_from_absence_and_has_its_own_hash():
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    empty_claim = _claim("empty.md", "", "span:0:0", "FR-000001")
    missing_claim = _claim("missing.md", "", "span:0:0", "FR-000001")
    result = validate_reference_claim_sources(
        (CandidateArtifact("empty.md", "references", None, ""),
         CandidateArtifact("missing.md", "references", "", None)),
        (empty_claim, missing_claim),
    )
    assert [(item.code, item.path) for item in result] == [
        ("reference_source_binding_mismatch", "empty.md"),
        ("reference_source_missing", "missing.md"),
    ]


def test_hash_mismatch_uses_after_image_and_does_not_hide_an_exact_binding():
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    before = "FR-000001"
    after = "FR-000002"
    claim = _claim("source.md", before, "span:0:9", "FR-000002")
    result = validate_reference_claim_sources(
        (CandidateArtifact("source.md", "references", before, after),), (claim,)
    )
    assert [(item.code, item.detail) for item in result] == [
        ("reference_source_hash_mismatch", "claim source hash does not match supplied after image"),
    ]


@pytest.mark.parametrize("anchor", [
    "span:1:10", "span:0:8", "span:00:09", "span:-1:9",
    "span:" + "9" * 5000 + ":10", "FR-000001", "not-a-span",
])
def test_anchor_spelling_is_never_coerced_or_parsed(anchor):
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001"
    result = validate_reference_claim_sources(
        (_artifact("source.md", "references", text),),
        (_claim("source.md", text, anchor, "FR-000001"),),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]


@pytest.mark.parametrize(("target", "relation"), [
    ("FR-000002", "reference"), ("FR-000001", "depends"),
    ("FR-000001", "requires"), ("FR-000001", "evidence"),
])
def test_target_and_relation_must_match_the_complete_parser_triple(target, relation):
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001"
    result = validate_reference_claim_sources(
        (_artifact("source.md", "references", text),),
        (_claim("source.md", text, "span:0:9", target, relation),),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]


@pytest.mark.parametrize(("role", "text", "anchor"), [
    ("requirements", "- **FR-000001**: A declaration.\n", "span:4:13"),
    ("references", "```\nFR-000001\n```\n", "span:4:13"),
    ("references", "    FR-000001\n", "span:4:13"),
    ("references", "<!-- FR-000001 -->\n", "span:5:14"),
])
def test_declarations_and_parser_masked_source_do_not_create_reference_facts(role, text, anchor):
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    result = validate_reference_claim_sources(
        (_artifact("source.md", role, text),),
        (_claim("source.md", text, anchor, "FR-000001"),),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]


@pytest.mark.parametrize(("text", "parser_code"), [
    ("scope::FR-000001", "unsupported_qualified_reference"),
    ("FR-000001.other", "unsupported_reference"),
])
def test_unsupported_whole_tokens_preserve_parser_diagnostics_and_never_leak_prefixes(text, parser_code):
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    start = text.index("FR-000001")
    result = validate_reference_claim_sources(
        (_artifact("source.md", "references", text),),
        (_claim("source.md", text, f"span:{start}:{start + 9}", "FR-000001"),),
    )
    assert [(item.code, item.element_id) for item in result] == [
        (parser_code, None),
        ("reference_source_binding_mismatch", "FR-000001"),
    ]
    assert result[0].detail.startswith("after span:")


def test_intervals_are_diagnosed_and_neither_endpoint_is_eligible():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001..FR-000003"
    claim = _claim("source.md", text, "span:0:9", "FR-000001")
    result = validate_reference_claim_sources(
        (_artifact("source.md", "references", text),), (claim,)
    )
    assert [(item.code, item.element_id, item.detail) for item in result] == [
        ("reference_source_binding_mismatch", "FR-000001",
         "claim requires an exact parsed span, target and relation match"),
        ("unsupported_reference_range", "FR-000001",
         "interval references are unsupported"),
    ]


def test_supported_inline_code_uses_the_inner_label_span():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "`FR-000001`"
    assert validate_reference_claim_sources(
        (_artifact("source.md", "references", text),),
        (_claim("source.md", text, "span:1:10", "FR-000001"),),
    ) == ()


def test_empty_investigation_filename_does_not_invent_a_zero_width_reference():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    result = validate_reference_claim_sources(
        (_artifact("investigations/FR-000001.md", "investigation", ""),),
        (_claim("investigations/FR-000001.md", "", "span:0:0", "FR-000001", "evidence"),),
    )
    assert [item.code for item in result] == ["reference_source_binding_mismatch"]


def test_unsupported_claimed_role_is_a_source_diagnostic_without_guessed_parsing():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001"
    result = validate_reference_claim_sources(
        (_artifact("source.md", "custom", text),),
        (_claim("source.md", text, "span:0:9", "FR-000001"),),
    )
    assert [(item.code, item.detail) for item in result] == [
        ("unsupported_role", "claim source role is unsupported"),
    ]


def test_glossary_and_evidence_inventory_are_deliberately_empty_fact_images():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    artifacts = (
        _artifact("glossary.md", "glossary", "FR-000001"),
        _artifact("inventory.md", "evidence_inventory", "FR-000002"),
    )
    claims = (
        _claim("glossary.md", "FR-000001", "span:0:9", "FR-000001"),
        _claim("inventory.md", "FR-000002", "span:0:9", "FR-000002"),
    )
    result = validate_reference_claim_sources(artifacts, claims)
    assert [(item.code, item.path) for item in result] == [
        ("reference_source_binding_mismatch", "glossary.md"),
        ("reference_source_binding_mismatch", "inventory.md"),
    ]


class _RecursiveSequence(Sequence):
    def __len__(self):
        raise RecursionError("UNTRUSTED_SENTINEL_" + "x" * 10_000)

    def __getitem__(self, index):
        raise RecursionError("UNTRUSTED_SENTINEL_" + "x" * 10_000)


def test_request_containers_are_strict_sequences_and_errors_are_bounded():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    artifact = _artifact("source.md", "references", "FR-000001")
    claim = _claim("source.md", "FR-000001", "span:0:9", "FR-000001")
    invalid = (
        ("artifacts", (artifact,), (claim,)),
        (b"artifacts", (artifact,), (claim,)),
        ((item for item in (artifact,)), (claim,), (claim,)),
        ((artifact,), "claims", (claim,)),
        ((artifact,), b"claims", (claim,)),
        ((artifact,), (item for item in (claim,)), (claim,)),
        (_RecursiveSequence(), (claim,), (claim,)),
    )
    for artifacts, claims, _ in invalid:
        with pytest.raises(ValueError) as captured:
            validate_reference_claim_sources(artifacts, claims)
        assert str(captured.value) == "invalid reference source validation request"


def test_bounded_request_error_suppresses_untrusted_traceback_context():
    import traceback

    from harness.element_identity_reference_sources import validate_reference_claim_sources

    with pytest.raises(ValueError) as captured:
        validate_reference_claim_sources(_RecursiveSequence(), ())
    rendered = "".join(traceback.format_exception(captured.value))
    assert "UNTRUSTED_SENTINEL_" not in rendered
    assert len(rendered) < 1_000


def test_exact_types_duplicates_canonical_paths_and_damaged_fields_are_rejected():
    from harness.element_identity_bindings import ReferenceClaim
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    class ArtifactSubclass(CandidateArtifact):
        pass

    class ClaimSubclass(ReferenceClaim):
        pass

    text = "FR-000001"
    artifact = _artifact("source.md", "references", text)
    claim = _claim("source.md", text, "span:0:9", "FR-000001")
    bad_path = replace(artifact, path="a/../source.md")
    no_images = replace(artifact, before_text=None, after_text=None)
    damaged_artifact = _artifact("damaged.md", "references", text)
    object.__setattr__(damaged_artifact, "role", [])
    missing_field = _artifact("missing-field.md", "references", text)
    object.__delattr__(missing_field, "path")
    damaged_claim = _claim("source.md", text, "span:0:9", "FR-000001")
    object.__setattr__(damaged_claim, "relation", [])
    actions = (
        lambda: validate_reference_claim_sources((artifact, artifact), (claim,)),
        lambda: validate_reference_claim_sources((bad_path,), ()),
        lambda: validate_reference_claim_sources((no_images,), ()),
        lambda: validate_reference_claim_sources((ArtifactSubclass(
            "source.md", "references", None, text),), (claim,)),
        lambda: validate_reference_claim_sources((artifact,), (claim, claim)),
        lambda: validate_reference_claim_sources((artifact,), (ClaimSubclass(
            claim.source_path, claim.source_sha256, claim.source_anchor,
            claim.target_id, claim.target_revision, claim.relation),)),
        lambda: validate_reference_claim_sources((damaged_artifact,), ()),
        lambda: validate_reference_claim_sources((missing_field,), ()),
        lambda: validate_reference_claim_sources((artifact,), (damaged_claim,)),
    )
    for action in actions:
        with pytest.raises(ValueError, match="^invalid reference source validation request$"):
            action()


@pytest.mark.parametrize("field", ["path", "role", "text"])
def test_unencodable_artifact_fields_are_rejected_even_when_unclaimed(field):
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    surrogate = "\ud800"
    values = {"path": "source.md", "role": "references", "text": "clean"}
    values[field] = surrogate
    artifact = CandidateArtifact(values["path"], values["role"], None, values["text"])
    with pytest.raises(ValueError, match="^invalid reference source validation request$"):
        validate_reference_claim_sources((artifact,), ())


def test_empty_requests_and_unclaimed_parser_problems_have_no_semantic_diagnostics():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    assert validate_reference_claim_sources((), ()) == ()
    assert validate_reference_claim_sources(
        (_artifact("bad.md", "references", "scope::FR-000001"),), ()
    ) == ()


def test_results_are_sorted_deduplicated_and_inputs_are_not_mutated():
    from harness.element_identity_reference_sources import validate_reference_claim_sources

    a_text = "FR-000001.other"
    b_text = "FR-000002"
    artifacts = [
        _artifact("b.md", "references", b_text),
        _artifact("a.md", "references", a_text),
    ]
    claims = [
        _claim("b.md", b_text, "span:1:9", "FR-000002", revision="2"),
        _claim("a.md", a_text, "span:0:9", "FR-000001", revision="1"),
        _claim("b.md", b_text, "span:1:9", "FR-000002", revision="1"),
    ]
    before_artifacts, before_claims = list(artifacts), list(claims)
    result = validate_reference_claim_sources(artifacts, claims)
    assert [(item.path, item.element_id, item.code) for item in result] == [
        ("a.md", None, "unsupported_reference"),
        ("a.md", "FR-000001", "reference_source_binding_mismatch"),
        ("b.md", "FR-000002", "reference_source_binding_mismatch"),
    ]
    assert artifacts == before_artifacts and claims == before_claims


def test_validation_performs_no_io_clock_or_network_access(monkeypatch):
    import builtins
    import socket
    import sqlite3
    import time

    from harness.element_identity_reference_sources import validate_reference_claim_sources

    text = "FR-000001"
    artifact = _artifact("source.md", "references", text)
    claim = _claim("source.md", text, "span:0:9", "FR-000001")

    def forbidden(*args, **kwargs):
        raise AssertionError("external access is forbidden")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    assert validate_reference_claim_sources((artifact,), (claim,)) == ()


def test_shared_parser_preserves_absent_empty_and_candidate_import_semantics():
    from harness.element_identity_candidate import CandidateArtifact
    from harness.element_identity_candidate_store import _parse_image as store_parse
    from harness.element_identity_reference_sources import _parse_image as source_parse

    artifact = CandidateArtifact("source.md", "references", None, "")
    absent = source_parse(artifact, None)
    empty = store_parse(artifact, "")
    assert store_parse is source_parse
    assert absent == empty
    assert absent.path == "source.md" and absent.role == "references"
    assert absent.content_sha256 == hashlib.sha256(b"").hexdigest()
    assert absent.declarations == absent.references == absent.diagnostics == ()
