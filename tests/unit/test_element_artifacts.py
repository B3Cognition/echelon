"""Source-preserving identity adapter contracts for Markdown artifacts."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from harness.element_artifacts import parse_identity_artifact


FIXTURES = Path("tests/fixtures/element_identity/discovery")
pytestmark = pytest.mark.unit


def test_opaque_issue_heading_is_diagnostic_not_empty_report():
    from harness.element_artifacts import parse_identity_artifact
    text = "### ISS-legacy: Collision\nBody\n"
    result = parse_identity_artifact(path="issues.md", role="issues", text=text)
    assert not result.declarations
    assert not result.references
    assert [d.code for d in result.diagnostics] == ["unsupported_declaration"]
    span = result.diagnostics[0].span
    assert text[span.start:span.end] == "ISS-legacy"


@pytest.mark.parametrize("family", ["AC", "FR", "NFR", "ISS", "U", "A", "T"])
@pytest.mark.parametrize("suffix", ["legacy", "old.name", "old-name", "a_b", "001.legacy", "001-legacy", "001é", "001*legacy", "001**legacy", "001`legacy", "001``legacy"])
@pytest.mark.parametrize("shape", ["### {id}: Caption", "- {id}: Caption", "- **{id}**: Caption", "- `{id}`: Caption", "- **{id}** Caption", "- `{id}` Caption"])
def test_unsupported_explicit_labels_keep_exact_span_without_shorter_reference(family, suffix, shape):
    label = f"{family}-{suffix}"
    text = "Résumé ⚡\r\n" + shape.format(id=label) + "\r\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert not result.declarations
    assert not result.references
    assert [d.code for d in result.diagnostics] == ["unsupported_declaration"]
    span = result.diagnostics[0].span
    assert (text[span.start:span.end], span.line) == (label, 2)


@pytest.mark.parametrize("wrapped", ["---\n{line}\n---\n", "```\n{line}\n```\n", "    {line}\n", "<!-- {line} -->\n", "> {line}\n"])
def test_unsupported_declarations_in_inactive_sources_are_ignored(wrapped):
    result = parse_identity_artifact(path="issues.md", role="issues", text=wrapped.format(line="### ISS-legacy: Caption"))
    assert not result.declarations and not result.references and not result.diagnostics


def test_unsupported_indented_heading_retains_ambiguous_boundary_and_plain_prose_is_reference():
    text = "  ### ISS-legacy: Caption\n- FR-001 is mentioned here\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [d.code for d in result.diagnostics] == ["ambiguous_block_boundary"]
    assert [r.target_id for r in result.references] == ["FR-001"]


def test_supported_numeric_composite_issue_heading_is_unchanged():
    result = parse_identity_artifact(path="issues.md", role="issues", text="### ISS-099legacy: Caption\nBody\n")
    assert [d.element_id for d in result.declarations] == ["ISS-099legacy"]
    assert not result.diagnostics


def _codes(result) -> set[str]:
    return {diagnostic.code for diagnostic in result.diagnostics}


def _assert_exact_slices(text: str, result) -> None:
    for declaration in result.declarations:
        assert text[declaration.span.start : declaration.span.end] == declaration.content
        assert text[declaration.label_span.start : declaration.label_span.end] == declaration.element_id
    for reference in result.references:
        assert text[reference.span.start : reference.span.end]


def test_question_declaration_and_evidence_reference_are_distinct():
    questions = parse_identity_artifact(
        path="unknowns.md",
        role="unknowns",
        text="### U-001: Keyboard focus ownership\n\n- Why: focus must return to the game.\n",
    )
    evidence = parse_identity_artifact(
        path="evidence-grades.md",
        role="evidence",
        text="| E3 | U-001 | activeElement | A | Focus ownership |\n",
    )
    assert [d.element_id for d in questions.declarations] == ["U-001"]
    assert questions.declarations[0].caption == "Keyboard focus ownership"
    assert not evidence.declarations
    assert [(r.target_id, r.relation) for r in evidence.references] == [
        ("U-001", "evidence")
    ]


def test_unknown_assumption_and_issue_authority_requires_level_three_headings():
    assumptions = parse_identity_artifact(
        path="assumptions.md", role="assumptions", text="### A-001: Browser support\n"
    )
    wrong_level = parse_identity_artifact(
        path="unknowns.md", role="unknowns", text="## U-001: Wrong level\n"
    )
    assert [declaration.element_id for declaration in assumptions.declarations] == ["A-001"]
    assert not wrong_level.declarations
    assert "unexpected_definition" in _codes(wrong_level)


def test_duplicate_declarations_are_not_collapsed():
    text = "- **AC-000001**: Move.\n- **AC-000001**: Stop.\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert len(result.declarations) == 2
    assert "duplicate_definition" in _codes(result)
    _assert_exact_slices(text, result)


def test_heading_and_bullet_blocks_preserve_crlf_unicode_and_boundaries():
    text = (
        "# Requirements\r\n\r\n"
        "### NFR-1000000: Réponse rapide ⚡\r\n"
        "- **Statement:** Preserve café.\r\n"
        "#### Detail\r\n"
        "Use FR-001a.\r\n"
        "### Notes\r\n"
        "NFR-1000000 is mentioned again.\r\n\r\n"
        "- **AC-000002b**: Observe Δ.\r\n"
        "  - nested FR-1000000\r\n"
        "\r\n"
        "  continuation AC-000002b\r\n"
        "Footer FR-999.\r\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [(item.element_id, item.kind, item.caption) for item in result.declarations] == [
        ("NFR-1000000", "NFR", "Réponse rapide ⚡"),
        ("AC-000002b", "AC", "Observe Δ."),
    ]
    assert result.declarations[0].content.endswith("Use FR-001a.\r\n")
    assert "### Notes" not in result.declarations[0].content
    assert result.declarations[1].content.endswith("  continuation AC-000002b\r\n")
    assert "Footer" not in result.declarations[1].content
    assert result.content_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert [ref.target_id for ref in result.references] == [
        "FR-001a",
        "NFR-1000000",
        "FR-1000000",
        "AC-000002b",
        "FR-999",
    ]
    assert result.declarations[0].span.line == 3
    assert result.declarations[0].label_span.line == 3
    _assert_exact_slices(text, result)


def test_issue_companion_is_owned_but_plain_same_level_heading_and_footer_are_not():
    text = (
        "### ISS-001: Focus is lost\n"
        "- **Severity:** HIGH\n\n"
        "### Resolution Guidance\n"
        "- **Action:** Restore U-004.\n\n"
        "### Reviewer Notes\n"
        "Do not swallow FR-999.\n\n"
        "## Certified Evidence Interpretation\n"
        "U-001 remains historic.\n"
    )
    result = parse_identity_artifact(path="issues.md", role="issues", text=text)
    assert [(d.element_id, d.disposition) for d in result.declarations] == [
        ("ISS-001", "occurrence")
    ]
    assert "### Resolution Guidance" in result.declarations[0].content
    assert "### Reviewer Notes" not in result.declarations[0].content
    assert "Certified Evidence" not in result.declarations[0].content
    assert "duplicate_occurrence" not in _codes(result)
    assert [(r.target_id, r.owner_id) for r in result.references] == [
        ("U-004", "ISS-001"),
        ("FR-999", None),
        ("U-001", None),
    ]


def test_projection_and_occurrence_duplicates_get_role_specific_diagnostics():
    issues = parse_identity_artifact(
        path="issues.md",
        role="issues",
        text="### ISS-001: One\n\n### ISS-001: Two\n",
    )
    assert [d.element_id for d in issues.declarations] == ["ISS-001", "ISS-001"]
    assert "duplicate_occurrence" in _codes(issues)


def test_wrong_role_declarations_are_diagnostics_but_summary_rows_are_references():
    text = (
        "### U-001: This is a declaration in the wrong artifact\n\n"
        "| Open question | U-002 | Who owns focus? |\n"
        "| Assumption | A-001 | Browser keyboard support |\n"
        "A sentence beginning with FR-009 is only prose.\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert not result.declarations
    assert "unexpected_definition" in _codes(result)
    assert [r.target_id for r in result.references] == [
        "U-001",
        "U-002",
        "A-001",
        "FR-009",
    ]


def test_inactive_markdown_regions_cannot_declare_or_reference_authority():
    text = (
        "---\n"
        "example: U-001\n"
        "---\n"
        "<!-- ### U-002: comment -->\n"
        "> ### U-003: quote\n"
        "> U-004\n"
        "    ### U-005: indented code\n"
        "~~~~markdown\n"
        "### U-006: tilde fence\n"
        "U-007\n"
        "~~~~\n"
        "````\n"
        "### U-008: backtick fence\n"
        "``` does not close a four-character fence\n"
        "````\n"
        "Inline `investigation/U-009.md` is active.\n"
        "### U-010: Real question\n"
    )
    result = parse_identity_artifact(path="unknowns.md", role="unknowns", text=text)
    assert [d.element_id for d in result.declarations] == ["U-010"]
    assert [r.target_id for r in result.references] == ["U-009"]
    assert not result.diagnostics


def test_list_owned_four_space_continuations_are_active_but_indented_code_is_not():
    text = (
        "- **FR-001**: Parent.\n"
        "    continuation AC-001\n"
        "        code example U-999\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [(reference.target_id, reference.owner_id) for reference in result.references] == [
        ("AC-001", "FR-001")
    ]


def test_list_content_columns_survive_paragraphs_and_nested_child_indentation():
    text = (
        "- **FR-001**: Parent.\n"
        "  continuation paragraph\n"
        "    more AC-001\n"
        "- **FR-002**: Second parent.\n"
        "    - **AC-002**: Four-space child.\n"
        "      continuation U-002\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [declaration.element_id for declaration in result.declarations] == [
        "FR-001",
        "FR-002",
        "AC-002",
    ]
    assert [(reference.target_id, reference.owner_id) for reference in result.references] == [
        ("AC-001", "FR-001"),
        ("U-002", "AC-002"),
    ]
    assert not result.diagnostics


def test_fence_delimiter_inside_html_comment_cannot_hide_later_active_source():
    text = "<!--\n```markdown\n-->\n### U-001: Actual question\n"
    result = parse_identity_artifact(path="unknowns.md", role="unknowns", text=text)
    assert [declaration.element_id for declaration in result.declarations] == ["U-001"]
    assert not result.references
    assert not result.diagnostics


@pytest.mark.parametrize("inactive_prefix", ["> ", "    "])
def test_comment_markers_in_inactive_containers_cannot_open_real_comments(
    inactive_prefix: str,
):
    text = f"{inactive_prefix}<!-- example\n\n### U-001: Actual question\n"
    result = parse_identity_artifact(path="unknowns.md", role="unknowns", text=text)
    assert [declaration.element_id for declaration in result.declarations] == ["U-001"]
    assert not result.references
    assert not result.diagnostics


def test_fenced_example_relative_to_list_content_cannot_declare_elements():
    text = (
        "- **FR-001**: Parent\n\n"
        "    ```markdown\n"
        "    - **AC-001**: Example only\n"
        "    ```\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [declaration.element_id for declaration in result.declarations] == ["FR-001"]
    assert not result.references
    assert not result.diagnostics


def test_inline_html_comments_hide_only_the_comment_not_active_source_around_it():
    text = (
        "### U-001: Active question <!-- U-999 -->\n"
        "Body U-002 <!-- U-003 --> remains active.\n"
    )
    result = parse_identity_artifact(path="unknowns.md", role="unknowns", text=text)
    assert [(d.element_id, d.caption) for d in result.declarations] == [
        ("U-001", "Active question")
    ]
    assert [reference.target_id for reference in result.references] == ["U-002"]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("<!-- U-001\n", "unterminated_comment"),
        ("```markdown\nU-001\n", "unterminated_fence"),
        ("---\nU-001: metadata\n", "unterminated_frontmatter"),
    ],
)
def test_unterminated_inactive_regions_are_diagnostics(text: str, code: str):
    result = parse_identity_artifact(path="notes.md", role="references", text=text)
    assert code in _codes(result)
    assert not result.references


def test_task_rows_reuse_canonical_metadata_and_own_subordinate_blocks():
    text = (
        "- [ ] T-000001 complexity=standard phase=core "
        "req=FR-001,AC-002 depends=T-000000 target=sources/app\n\n"
        "  **Title:** Implement café movement\n\n"
        "  **Description:** Uses FR-003.\n\n"
        "- [x] T-S02a [P] complexity=trivial phase=polish "
        "req=INFRA depends=none target=sources/app\n\n"
        "  **Title:** Polish keyboard focus\n"
    )
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=text)
    assert [(d.element_id, d.caption, d.kind) for d in result.declarations] == [
        ("T-000001", "Implement café movement", "T"),
        ("T-S02a", "Polish keyboard focus", "T"),
    ]
    assert [(r.target_id, r.relation, r.owner_id) for r in result.references] == [
        ("FR-001", "requires", "T-000001"),
        ("AC-002", "requires", "T-000001"),
        ("T-000000", "depends", "T-000001"),
        ("FR-003", "reference", "T-000001"),
    ]
    assert "INFRA" not in {r.target_id for r in result.references}
    _assert_exact_slices(text, result)


def test_task_metadata_ranges_are_single_relation_aware_intervals():
    forward = (
        "- [ ] T-001 complexity=standard phase=core "
        "req=FR-001..FR-003 depends=T-001..T-002\n"
        "  **Title:** Implement an interval\n"
    )
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=forward)
    assert [
        (item.target_id, item.range_end_id, item.relation)
        for item in result.references
    ] == [
        ("FR-001", "FR-003", "requires"),
        ("T-001", "T-002", "depends"),
    ]
    assert not result.diagnostics

    reversed_text = forward.replace("FR-001..FR-003", "FR-003..FR-001")
    reversed_result = parse_identity_artifact(
        path="tasks.md", role="tasks", text=reversed_text
    )
    assert [
        (item.target_id, item.range_end_id, item.relation)
        for item in reversed_result.references
    ] == [("T-001", "T-002", "depends")]
    assert "invalid_range" in _codes(reversed_result)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (
            "- [ ] T-001 complexity=huge phase=core req=FR-001 depends=none\n"
            "  **Title:** Bad metadata\n",
            "malformed_task",
        ),
        (
            "- [ ] T-001 complexity=standard phase=core req=FR-001 depends=none\n",
            "missing_task_title",
        ),
        (
            "- [ ] T-001 complexity=standard phase=core req=FR-001 depends=none\n"
            "  **Title:** One\n  **Title:** Two\n",
            "duplicate_task_title",
        ),
        (
            "- [ ] T-FOO complexity=standard phase=core req=FR-001 depends=none\n"
            "  **Title:** Unsupported task label\n",
            "malformed_task",
        ),
    ],
)
def test_task_like_rows_are_never_silently_omitted(text: str, code: str):
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=text)
    assert code in _codes(result)


def test_template_task_rows_remain_supported():
    text = Path("runtime/templates/tasks-template.md").read_text(encoding="utf-8")
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=text)
    assert [declaration.element_id for declaration in result.declarations] == [
        "T-001",
        "T-002",
    ]
    assert not result.diagnostics


def test_duplicate_canonical_task_rows_are_retained_before_diagnosis():
    row = (
        "- [ ] T-001 complexity=standard phase=core req=FR-001 depends=none\n"
        "  **Title:** Implement movement\n"
    )
    result = parse_identity_artifact(path="tasks.md", role="tasks", text=row + row)
    assert [declaration.element_id for declaration in result.declarations] == [
        "T-001",
        "T-001",
    ]
    assert "duplicate_definition" in _codes(result)


def test_ranges_are_retained_without_expansion_and_commas_stay_separate():
    giant = "9" * 5000
    text = (
        "U-001–U-005, U-010—U-011, U-020..U-021, U-030 - U-031, "
        f"FR-1–FR-{giant}, AC-001a, investigation/U-004.md\n"
    )
    result = parse_identity_artifact(path="investigation/report.md", role="investigation", text=text)
    assert [(r.target_id, r.range_end_id) for r in result.references] == [
        ("U-001", "U-005"),
        ("U-010", "U-011"),
        ("U-020", "U-021"),
        ("U-030", "U-031"),
        ("FR-1", f"FR-{giant}"),
        ("AC-001a", None),
        ("U-004", None),
    ]
    assert all(reference.relation == "evidence" for reference in result.references)


@pytest.mark.parametrize(
    "text",
    [
        "U-005–U-001\n",
        "U-001–A-005\n",
        "U-001a–U-005b\n",
        "U-001..\n",
    ],
)
def test_bad_ranges_are_diagnostic_and_not_split_into_independent_references(text: str):
    result = parse_identity_artifact(path="notes.md", role="references", text=text)
    assert "invalid_range" in _codes(result)
    assert not result.references


def test_ascii_hyphen_prose_delimiter_is_not_a_dangling_range():
    result = parse_identity_artifact(
        path="notes.md", role="references", text="FR-001 - implementation note\n"
    )
    assert [reference.target_id for reference in result.references] == ["FR-001"]
    assert "invalid_range" not in _codes(result)


def test_only_the_declaration_label_span_is_excluded_from_references():
    text = "- **FR-001**: FR-001 requires AC-001 and FR-001a, not FR-001abc?\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [d.element_id for d in result.declarations] == ["FR-001"]
    assert [r.target_id for r in result.references] == [
        "FR-001",
        "AC-001",
        "FR-001a",
        "FR-001abc",
    ]


def test_unsupported_unicode_suffix_cannot_create_a_shorter_reference():
    result = parse_identity_artifact(
        path="notes.md", role="references", text="FR-001é and FR-001a\n"
    )
    assert [reference.target_id for reference in result.references] == ["FR-001a"]


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("- **FR-001** Statement without a colon\n", "unsupported_declaration"),
        (
            "- **FR-001**: Parent requirement.\n"
            "  ### AC-001: Ambiguous nested heading.\n",
            "ambiguous_block_boundary",
        ),
    ],
)
def test_ambiguous_or_malformed_id_bearing_bullets_are_diagnostic(text: str, code: str):
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert code in _codes(result)


def test_valid_nested_bullet_declaration_has_innermost_reference_ownership():
    text = (
        "- **FR-001**: Parent requirement.\n"
        "  - **AC-001**: Nested criterion.\n"
        "    Uses U-001.\n"
    )
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [declaration.element_id for declaration in result.declarations] == [
        "FR-001",
        "AC-001",
    ]
    assert [(reference.target_id, reference.owner_id) for reference in result.references] == [
        ("U-001", "AC-001")
    ]
    assert not result.diagnostics


def test_nested_heading_reference_uses_innermost_declaration_owner():
    text = "## FR-001: Parent\n### AC-001: Child\nUse U-001.\n"
    result = parse_identity_artifact(path="spec.md", role="requirements", text=text)
    assert [declaration.element_id for declaration in result.declarations] == [
        "FR-001",
        "AC-001",
    ]
    assert [(reference.target_id, reference.owner_id) for reference in result.references] == [
        ("U-001", "AC-001")
    ]


def test_qualified_cross_spec_references_are_diagnostic_not_local_bare_ids():
    text = (
        "specs/002-other/spec.md#FR-001 and 002-other::FR-002 are cross-spec; "
        "investigation/U-001.md is local.\n"
    )
    result = parse_identity_artifact(path="notes.md", role="references", text=text)
    assert [reference.target_id for reference in result.references] == ["U-001"]
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_qualified_reference",
        "unsupported_qualified_reference",
    ]
    assert [text[d.span.start : d.span.end] for d in result.diagnostics] == [
        "specs/002-other/spec.md#FR-001",
        "002-other::FR-002",
    ]


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("### U-001 Question without colon\n", "U-001"),
        ("### U-001é: Unsupported suffix\n", "U-001é"),
    ],
)
def test_unsupported_explicit_headings_are_diagnostic_not_references(
    text: str, label: str
):
    result = parse_identity_artifact(path="unknowns.md", role="unknowns", text=text)
    assert not result.declarations
    assert not result.references
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "unsupported_declaration"
    ]
    diagnostic = result.diagnostics[0]
    assert text[diagnostic.span.start : diagnostic.span.end] == label


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"path": 1, "role": "references", "text": ""}, "path"),
        ({"path": "notes.md", "role": 1, "text": ""}, "role"),
        ({"path": "notes.md", "role": "references", "text": 1}, "text"),
        ({"path": "/notes.md", "role": "references", "text": ""}, "path"),
        ({"path": "a/../notes.md", "role": "references", "text": ""}, "path"),
        ({"path": "a\\notes.md", "role": "references", "text": ""}, "path"),
        ({"path": ".", "role": "references", "text": ""}, "path"),
        ({"path": "notes.md", "role": "REFERENCE", "text": ""}, "role"),
        ({"path": "notes.md", "role": "references", "text": "x\x00y"}, "NUL"),
        ({"path": "notes.md", "role": "references", "text": "\ud800"}, "UTF-8"),
    ],
)
def test_invalid_api_inputs_raise_value_error(kwargs, message: str):
    with pytest.raises(ValueError, match=message):
        parse_identity_artifact(**kwargs)


def test_result_and_nested_collections_are_immutable():
    result = parse_identity_artifact(
        path="unknowns.md", role="unknowns", text="### U-001: Question\n"
    )
    assert isinstance(result.declarations, tuple)
    assert isinstance(result.references, tuple)
    assert isinstance(result.diagnostics, tuple)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.role = "references"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.declarations[0].caption = "changed"


def test_discovery_fixture_preserves_historical_evidence_without_claiming_publication():
    before_text = (FIXTURES / "before/unknowns.md").read_text(encoding="utf-8")
    after_text = (FIXTURES / "after/unknowns.md").read_text(encoding="utf-8")
    evidence_text = (FIXTURES / "evidence-grades.md").read_text(encoding="utf-8")

    before = parse_identity_artifact(path="unknowns.md", role="unknowns", text=before_text)
    after = parse_identity_artifact(path="unknowns.md", role="unknowns", text=after_text)
    evidence = parse_identity_artifact(path="evidence-grades.md", role="evidence", text=evidence_text)

    assert [(d.element_id, d.caption) for d in before.declarations] == [
        ("U-001", "Visual style"),
        ("U-002", "Collision margin"),
        ("U-003", "DOM status"),
        ("U-004", "Focus ownership"),
        ("U-005", "Large-step collision"),
    ]
    assert [(d.element_id, d.caption) for d in after.declarations] == [
        ("U-001", "Map dimensions and speed"),
        ("U-002", "Graphics fallback"),
        ("U-003", "Focus conveyance"),
        ("U-004", "Initial placement"),
    ]
    assert [r.target_id for r in evidence.references] == [
        "U-003",
        "U-004",
        "U-001",
        "U-002",
        "U-005",
    ]
    assert not before.diagnostics and not after.diagnostics and not evidence.diagnostics
