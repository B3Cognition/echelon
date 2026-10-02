"""Shadow verification-path evidence for formal obligations."""

import pytest

from understanding.requirement_projection import project_requirements
from understanding.verification_paths import assess_verification_paths


@pytest.mark.unit
def test_linked_criterion_preserves_setup_action_and_expected_observation() -> None:
    projections = project_requirements(
        "- **FR-001**: The page MUST show one canvas.\n"
        "- **AC-001**: Given successful initialization, when the visitor opens "
        "the page, then exactly one primary canvas is visible, verifying FR-001.\n"
    )

    paths = assess_verification_paths(projections)

    assert paths["FR-001"] == {
        "mode": "shadow",
        "semantic_alignment": "not_assessed",
        "linked_acceptance_criteria": [
            {
                "requirement_id": "AC-001",
                "source_location": {"line_start": 2, "line_end": 2},
                "given": "successful initialization",
                "when": "the visitor opens the page",
                "then": "exactly one primary canvas is visible",
                "review_flags": [],
            }
        ],
        "review_flags": [],
    }


@pytest.mark.unit
def test_unlinked_obligation_reports_missing_verification_path() -> None:
    projections = project_requirements(
        "- **FR-001**: The page MUST show one canvas.\n"
        "- **AC-001**: Given a page, when it opens, then a canvas is visible, "
        "verifying FR-999.\n"
    )

    paths = assess_verification_paths(projections)

    assert paths["FR-001"]["linked_acceptance_criteria"] == []
    assert paths["FR-001"]["review_flags"] == [
        "no_linked_acceptance_criterion"
    ]


@pytest.mark.unit
def test_vague_outcome_is_flagged_without_claiming_a_verdict() -> None:
    projections = project_requirements(
        "- **NFR-001**: The interface MUST be usable.\n"
        "- **AC-001**: Given an open page, when a visitor uses it, "
        "then the interface is good, verifying NFR-001.\n"
    )

    path = assess_verification_paths(projections)["NFR-001"]

    assert path["semantic_alignment"] == "not_assessed"
    assert path["linked_acceptance_criteria"][0]["then"] == "the interface is good"
    assert path["linked_acceptance_criteria"][0]["review_flags"] == [
        "subjective_expected_outcome:good"
    ]


@pytest.mark.unit
def test_inspection_criterion_is_not_flagged_only_for_lacking_gwt() -> None:
    projections = project_requirements(
        "- **FR-001**: The delivered project MUST use TypeScript.\n"
        "- **AC-001**: Inspection of the source confirms TypeScript, "
        "verifying FR-001.\n"
    )

    path = assess_verification_paths(projections)["FR-001"]

    assert path["linked_acceptance_criteria"][0]["then"] == (
        "Inspection of the source confirms TypeScript"
    )
    assert path["linked_acceptance_criteria"][0]["review_flags"] == []


@pytest.mark.unit
def test_req_lexicon_criterion_uses_its_explicit_scenario_fields() -> None:
    projections = project_requirements(
        "REQ: FR-001\n"
        "THEN: the page MUST show one canvas\n\n"
        "REQ: AC-001\n"
        "GIVEN: successful initialization\n"
        "WHEN: the visitor opens the page\n"
        "THEN: exactly one primary canvas is visible\n"
        "DEPENDS: FR-001\n"
    )

    criterion = assess_verification_paths(projections)["FR-001"][
        "linked_acceptance_criteria"
    ][0]

    assert criterion["given"] == "successful initialization"
    assert criterion["when"] == "the visitor opens the page"
    assert criterion["then"] == "exactly one primary canvas is visible"
    assert criterion["review_flags"] == []
