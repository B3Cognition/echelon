"""Behavioral contracts for canonical requirement projection."""

import pytest

from understanding.requirement_projection import project_requirements
from understanding.service import parse_requirements


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


@pytest.mark.unit
def test_projection_preserves_general_lexicon_identifiers_for_compatibility() -> None:
    """Lexicon REQ identifiers are not limited to conventional FR prefixes."""
    spec = """ARTIFACT: SPEC

REQ: R1
THEN: the greeting command MUST write a message

REQ: TASK-07
THEN: the greeting command MUST write an audit record

REQ: REQ-001
THEN: the greeting command MUST write a status record

REQ: STORY-1
THEN: the greeting command MUST write a story result
"""

    projections = project_requirements(spec)

    assert [projection.requirement_id for projection in projections] == [
        "R1",
        "TASK-07",
        "REQ-001",
        "STORY-1",
    ]
    assert parse_requirements(spec)["count"] == 4


@pytest.mark.unit
def test_heading_projection_preserves_unknown_block_prose_and_original_text() -> None:
    """Unknown block lines are evidence, not metadata to silently discard."""
    spec = """### FR-001: Greeting
- **Statement**: The greeting command MUST write a configured message.
- **Implementation note**: The message includes the active locale.
- **Constraint**: output_length <= 128 bytes.
"""

    projection = project_requirements(spec)[0]

    assert projection.original_text == (
        "- **Statement**: The greeting command MUST write a configured message.\n"
        "- **Implementation note**: The message includes the active locale.\n"
        "- **Constraint**: output_length <= 128 bytes."
    )
    assert projection.normative_text == (
        "The greeting command MUST write a configured message. "
        "- **Implementation note**: The message includes the active locale."
    )
    assert projection.constraints == ("output_length <= 128 bytes.",)


@pytest.mark.unit
def test_projection_preserves_conventional_req_identifier_compatibility() -> None:
    spec = "- **REQ-001**: The greeting command MUST write a message.\n"

    assert parse_requirements(spec)["requirements"] == [
        {"id": "REQ-001", "text": "The greeting command MUST write a message."}
    ]


@pytest.mark.unit
def test_projection_excludes_technical_tokens_from_traceability() -> None:
    spec = (
        "- **FR-001**: The command MUST store SHA256, TLS1, and ISO-27001 "
        "alongside FR-002. Verified by: AC-001.\n"
    )

    projection = project_requirements(spec)[0]

    assert projection.traceability_references == ("FR-002", "AC-001")
