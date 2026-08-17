"""Behavioral contracts for canonical requirement projection."""

from pathlib import Path

import pytest

from understanding.requirement_projection import project_requirements
from understanding.service import (
    DEFAULT_QUALITY_GATES,
    analyze_spec_bundle,
    parse_requirements,
)


PROPORTIONAL_HELLO_WORLD_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/understanding/proportional-hello-world-first-candidate.md"
)


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
def test_retained_hello_world_candidate_has_consistent_explainable_quality_evidence() -> None:
    """The retained live candidate cannot regain contradictory role evidence."""
    spec_text = PROPORTIONAL_HELLO_WORLD_FIXTURE.read_text(encoding="utf-8")
    projections = project_requirements(spec_text)

    assert [projection.requirement_id for projection in projections] == [
        "AC-001",
        "AC-002",
        "AC-003",
        "AC-004",
        "FR-001",
        "FR-002",
        "FR-003",
        "FR-004",
        "FR-005",
        "FR-006",
        "FR-007",
        "FR-008",
        "FR-009",
    ]
    assert all(
        "User Story:" not in projection.normative_text
        and "Priority:" not in projection.normative_text
        for projection in projections
    )
    assert projections[0].normative_text == (
        "Given exactly 1 delivered script and an available Python runtime, "
        "when the Invoker directly performs 1 Program invocation, then exactly "
        "1 delivered artifact runs as a script through that Python runtime."
    )
    assert projections[0].traceability_references == ("FR-001",)
    assert projections[1].normative_text == (
        "Given the script required by FR-001 and observable execution-output "
        "channels, when 1 Program invocation succeeds, then the Standard output "
        "Greeting Output count equals 1, its visible content equals "
        "`Hello, World!`, and application output on every other channel equals 0."
    )
    assert projections[1].traceability_references == (
        "FR-001",
        "FR-002",
        "FR-003",
        "FR-004",
    )
    assert projections[2].normative_text == (
        "Given closed user input and monitored file, network, and retained-state "
        "boundaries, when 1 Program invocation runs to completion, then user-input "
        "read operations equal 0, file writes equal 0, network calls equal 0, and "
        "retained execution-state items after termination equal 0."
    )
    assert projections[2].traceability_references == (
        "FR-005",
        "FR-006",
        "FR-007",
        "FR-008",
    )

    bundle = analyze_spec_bundle(
        PROPORTIONAL_HELLO_WORLD_FIXTURE,
        thresholds=DEFAULT_QUALITY_GATES,
        enhanced=True,
        use_nlp=False,
    )

    assert bundle.thresholds == {
        "overall": 0.75,
        "structure": 0.75,
        "testability": 0.75,
        "semantic": 0.65,
        "cognitive": 0.65,
        "readability": 0.55,
        "depth": 0.40,
        "behavioral": 0.55,
    }
    assert bundle.scores == {
        "overall": 0.6978472499999999,
        "structure": 0.7269,
        "testability": 0.7356,
        "semantic": 0.5126,
        "cognitive": 0.7578,
        "readability": 0.6996,
        "depth": 0.7448,
        "behavioral": 0.7157,
    }
    assert {
        name for name, gate in bundle.gates.items() if not gate["pass"]
    } == {"overall", "structure", "testability", "semantic"}

    for evidence in bundle.per_requirement:
        shared = evidence["shared_roles"]
        semantic = evidence["semantic_roles"]
        for singular, plural in (
            ("actor", "actors"),
            ("action", "actions"),
            ("object", "objects"),
        ):
            assert bool(shared[singular]) is bool(semantic[plural])


@pytest.mark.unit
def test_projection_strips_only_standalone_trailing_verification_metadata() -> None:
    spec = """# Requirements

- **AC-001**: The caller MUST observe output, verifying FR-001, FR-002, and FR-003.
- **FR-001**: The verifier MUST finish verifying FR-002.
- **FR-002**: The verifier MUST emit status, verifying FR-001 remains current.
- **FR-003**: The verifier MUST compare status by verifying FR-001 against output.
"""

    projections = project_requirements(spec)

    assert projections[0].normative_text == "The caller MUST observe output."
    assert projections[0].traceability_references == (
        "FR-001",
        "FR-002",
        "FR-003",
    )
    assert projections[1].normative_text == (
        "The verifier MUST finish verifying FR-002."
    )
    assert projections[1].traceability_references == ("FR-002",)
    assert projections[2].normative_text == (
        "The verifier MUST emit status, verifying FR-001 remains current."
    )
    assert projections[2].traceability_references == ("FR-001",)
    assert projections[3].normative_text == (
        "The verifier MUST compare status by verifying FR-001 against output."
    )
    assert projections[3].traceability_references == ("FR-001",)


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


@pytest.mark.unit
def test_heading_projection_rejects_generic_requirement_prefixes() -> None:
    spec = """### ADR-001: Decision
- **Statement**: This must not become a requirement.

### A-001: Note
- **Statement**: This must not become a requirement.

### FR-001: Requirement
- **Statement**: The command MUST write a message.

### NFR-001: Performance
- **Statement**: The command MUST finish within 200 ms.
"""

    assert [projection.requirement_id for projection in project_requirements(spec)] == [
        "FR-001",
        "NFR-001",
    ]
