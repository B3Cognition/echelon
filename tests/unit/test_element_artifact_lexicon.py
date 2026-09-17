"""Validated, source-preserving Lexicon identity projection contracts."""

from __future__ import annotations

import pytest

from harness.element_artifacts import parse_identity_artifact


VALID = (
    "ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-000001\n"
    "GIVEN: an active player\nWHEN: movement is requested\n"
    "THEN: the game MUST move the player\n"
    "DEPENDS: FR-000000\nEXAMPLE: AC-1000000\n\n"
    "AC: AC-1000000\nGIVEN: an active player\n"
    "WHEN: movement is requested\nTHEN: the player position changes\n"
)


def _codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def test_derived_lexicon_is_not_an_independent_definition():
    text = (
        "ARTIFACT: SPEC\nTITLE: Game\n\nREQ: FR-000001\n"
        "GIVEN: an active player\nWHEN: movement is requested\n"
        "THEN: the game MUST move the player\n\n"
        "AC: AC-1000000\nGIVEN: an active player\n"
        "WHEN: movement is requested\nTHEN: the player position changes\n"
    )
    result = parse_identity_artifact(
        path="requirements.lexicon.md", role="lexicon_projection", text=text
    )
    assert [(d.element_id, d.disposition) for d in result.declarations] == [
        ("FR-000001", "projection"),
        ("AC-1000000", "projection"),
    ]
    assert not result.diagnostics


def test_valid_lexicon_uses_whole_document_grammar_and_preserves_every_block():
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon", text=VALID)
    assert [(d.element_id, d.kind, d.caption) for d in result.declarations] == [
        ("FR-000001", "FR", "the game MUST move the player"),
        ("AC-1000000", "AC", "the player position changes"),
    ]
    assert result.declarations[0].content == (
        "REQ: FR-000001\n"
        "GIVEN: an active player\n"
        "WHEN: movement is requested\n"
        "THEN: the game MUST move the player\n"
        "DEPENDS: FR-000000\n"
        "EXAMPLE: AC-1000000\n\n"
    )
    assert result.declarations[1].content.endswith("THEN: the player position changes\n")
    assert [(r.target_id, r.relation, r.owner_id) for r in result.references] == [
        ("FR-000000", "depends", "FR-000001"),
        ("AC-1000000", "reference", "FR-000001"),
    ]
    for declaration in result.declarations:
        assert VALID[declaration.span.start : declaration.span.end] == declaration.content
        assert VALID[declaration.label_span.start : declaration.label_span.end] == declaration.element_id


def test_lexicon_crlf_unicode_offsets_are_exact():
    text = VALID.replace("Game", "Café Δ").replace("\n", "\r\n")
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon", text=text)
    assert not result.diagnostics
    for declaration in result.declarations:
        assert text[declaration.span.start : declaration.span.end] == declaration.content
        assert declaration.span.line in {4, 11}


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "ARTIFACT: SPEC\nTITLE: Broken\n\nREQ: FR-001\n"
            "GIVEN: a condition\nWHEN: an event\n",
            "invalid_lexicon",
        ),
        (
            VALID.replace("REQ: FR-000001", "REQ: AC-000001"),
            "unsupported_lexicon_id",
        ),
        (
            VALID.replace("AC: AC-1000000", "AC: FR-1000000"),
            "unsupported_lexicon_id",
        ),
        (
            VALID + "\nRULE: FR-009\nIF: a condition\nTHEN: a result\n",
            "unexpected_definition",
        ),
    ],
)
def test_invalid_or_wrong_family_lexicon_constructs_are_diagnostic(text: str, code: str):
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon", text=text)
    assert code in _codes(result)


def test_unsupported_legacy_lexicon_labels_do_not_disappear():
    text = VALID.replace("REQ: FR-000001", "REQ: REQ-000001")
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon", text=text)
    assert [declaration.element_id for declaration in result.declarations] == ["AC-1000000"]
    assert "unsupported_lexicon_id" in _codes(result)


def test_every_grammar_valid_unsupported_req_or_ac_label_is_diagnostic():
    text = (
        "ARTIFACT: SPEC\nTITLE: Unsupported labels\n\n"
        "REQ: FR-FOO\nGIVEN: a condition\nWHEN: an event\n"
        "THEN: the system MUST act\n\n"
        "AC: AC-WORD\nGIVEN: a condition\nWHEN: an event\n"
        "THEN: an outcome is visible\n"
    )
    result = parse_identity_artifact(
        path="requirements.lexicon.md", role="lexicon", text=text
    )
    assert not result.declarations
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_lexicon_id",
        "unsupported_lexicon_id",
    ]
    assert [text[item.span.start : item.span.end] for item in result.diagnostics] == [
        "FR-FOO",
        "AC-WORD",
    ]


@pytest.mark.parametrize("role", ["lexicon", "lexicon_projection"])
def test_diagnosed_header_labels_do_not_hide_real_body_references(role):
    text = (
        "ARTIFACT: SPEC\r\nTITLE: Café ⚡\r\n\r\n"
        "REQ: AC-000001\r\nGIVEN: a condition\r\nWHEN: an event\r\n"
        "THEN: See AC-000001 and FR-FOO\r\n\r\n"
        "RULE: FR-009\r\nIF: a condition\r\n"
        "THEN: See T-000001 and AC-WORD\r\n"
    )
    result = parse_identity_artifact(
        path="requirements.lexicon.md", role=role, text=text
    )
    assert not result.declarations
    assert [
        (item.code, item.span.start, item.span.end, item.span.line,
         text[item.span.start:item.span.end])
        for item in result.diagnostics
    ] == [
        ("unsupported_lexicon_id", 38, 47, 4, "AC-000001"),
        ("unsupported_reference", 109, 115, 7, "FR-FOO"),
        ("unexpected_definition", 125, 131, 9, "FR-009"),
        ("unsupported_reference", 173, 180, 11, "AC-WORD"),
    ]
    assert [
        (item.target_id, item.relation, item.span.start, item.span.end,
         item.span.line, text[item.span.start:item.span.end])
        for item in result.references
    ] == [
        ("AC-000001", "reference", 95, 104, 7, "AC-000001"),
        ("T-000001", "reference", 160, 168, 11, "T-000001"),
    ]


def test_valid_indented_lexicon_blocks_preserve_declarations_and_boundaries():
    text = (
        "ARTIFACT: SPEC\nTITLE: Indented\n\n"
        "  REQ: FR-001\n  GIVEN: a condition\n  WHEN: an event\n"
        "  THEN: the system MUST act\n\n"
        "  AC: AC-001\n  GIVEN: a condition\n  WHEN: an event\n"
        "  THEN: the result is visible\n"
    )
    result = parse_identity_artifact(
        path="requirements.lexicon.md", role="lexicon", text=text
    )
    assert [
        (declaration.element_id, declaration.caption)
        for declaration in result.declarations
    ] == [
        ("FR-001", "the system MUST act"),
        ("AC-001", "the result is visible"),
    ]
    assert result.declarations[0].content.startswith("  REQ: FR-001\n")
    assert result.declarations[0].content.endswith("\n\n")
    assert result.declarations[1].content.startswith("  AC: AC-001\n")
    assert not result.references
    assert not result.diagnostics


def test_lexicon_definition_duplicates_are_retained_in_source_order():
    duplicate = VALID + (
        "\nREQ: FR-000001\nGIVEN: another player\nWHEN: movement repeats\n"
        "THEN: the game MUST move again\n"
    )
    result = parse_identity_artifact(path="requirements.lexicon.md", role="lexicon", text=duplicate)
    assert [d.element_id for d in result.declarations] == [
        "FR-000001",
        "AC-1000000",
        "FR-000001",
    ]
    assert "duplicate_definition" in _codes(result)


def test_lexicon_projection_duplicates_get_projection_diagnostic():
    duplicate = VALID + (
        "\nAC: AC-1000000\nGIVEN: another player\nWHEN: movement repeats\n"
        "THEN: another position changes\n"
    )
    result = parse_identity_artifact(
        path="requirements.lexicon.md", role="lexicon_projection", text=duplicate
    )
    assert [d.element_id for d in result.declarations] == [
        "FR-000001",
        "AC-1000000",
        "AC-1000000",
    ]
    assert "duplicate_projection" in _codes(result)


def test_quoted_lexicon_example_is_not_heuristically_parsed_for_reference_role():
    text = "> REQ: FR-001\n> THEN: a service MUST act\n"
    result = parse_identity_artifact(path="notes.md", role="references", text=text)
    assert not result.declarations
    assert not result.references
    assert not result.diagnostics
