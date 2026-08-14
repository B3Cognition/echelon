"""Behavioral contracts for canonical requirement projection."""

import pytest

from understanding.requirement_projection import project_requirements


SPEC = """# Requirements

## Command behavior
- **FR-001**: The command prints Hello, world! to standard output. Constraint: Exit status is zero. Verified by: AC-001, FR-001.

### NFR-001: Completion time
- **Statement**: The greeting command must write the configured message to standard output.
- **Constraints**: Completion time <= 200 ms.
- **Verified by**: AC-002, FR-001.

ARTIFACT: SPEC

REQ: FR-002
GIVEN: a configured greeting
WHEN: the greeting command runs
THEN: the greeting command MUST write the configured message
OUTPUT: the configured message is available on standard output
CONSTRAINT: output_length <= 128 bytes
DEPENDS: FR-001, FR-002
"""


@pytest.mark.unit
def test_projection_separates_normative_text_constraints_and_traceability() -> None:
    """Dropping recognized metadata must not make it part of quality prose."""
    projections = project_requirements(SPEC)

    req = projections[0]
    assert req.requirement_id == "FR-001"
    assert req.normative_text == "The command prints Hello, world! to standard output."
    assert req.constraints == ("Exit status is zero.",)
    assert req.traceability_references == ("AC-001",)
    assert req.source_location.line_start == 4
    assert req.source_location.line_end == 4
    assert "Exit status" not in req.normative_text
    assert "AC-001" not in req.normative_text


@pytest.mark.unit
def test_projection_handles_statement_sections_and_folded_lexicon_fields() -> None:
    """Conventional and Lexicon forms retain their usable evidence separately."""
    projections = project_requirements(SPEC)

    nfr = projections[1]
    assert nfr.requirement_id == "NFR-001"
    assert nfr.normative_text == (
        "The greeting command must write the configured message to standard output."
    )
    assert nfr.constraints == ("Completion time <= 200 ms.",)
    assert nfr.traceability_references == ("AC-002", "FR-001")
    assert nfr.source_location.line_start == 6
    assert nfr.source_location.line_end == 9

    lexicon = projections[2]
    assert lexicon.requirement_id == "FR-002"
    assert lexicon.normative_text == (
        "Given a configured greeting, when the greeting command runs, "
        "the greeting command MUST write the configured message. "
        "the configured message is available on standard output."
    )
    assert lexicon.constraints == ("output_length <= 128 bytes",)
    assert lexicon.traceability_references == ("FR-001",)
    assert lexicon.source_location.line_start == 13
    assert lexicon.source_location.line_end == 19
    assert "<=" not in lexicon.normative_text
