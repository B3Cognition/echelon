from pathlib import Path
import hashlib

import pytest

from harness.spec_lexicon_gate import run_spec_lexicon_gate


@pytest.mark.unit
@pytest.mark.parametrize(
    "config",
    [
        {"lexicon_gate": {"enabled": False}},
        {
            "lexicon_gate": {
                "enabled": True,
                "artifacts": {"spec": {"enabled": False}},
            }
        },
    ],
)
def test_disabled_spec_gate_is_pending_without_certificate_metadata(
    tmp_path: Path,
    config: dict[str, object],
) -> None:
    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="",
        config=config,
        previous_attempts=7,
    )

    assert result.evaluation == "pending"
    assert result.passed is None
    assert result.attempts == 0
    assert result.findings is None
    assert result.report_path is None
    assert result.state_updates() == {
        "lexicon_evaluation": "pending",
        "lexicon_attempts": 0,
    }


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.unit
def test_spec_gate_uses_markdown_glossary_heading_terms_with_qualifiers(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-model-tier"
    spec_dir.mkdir(parents=True)
    source = """# Feature Specification

## Functional Requirements

- **FR-001**: Preserve model_tier.

## Acceptance Criteria

- **AC-001**: Given model_tier exists, when inspected, then it is preserved.
"""
    (spec_dir / "spec.md").write_text(source, encoding="utf-8")
    (spec_dir / "glossary.md").write_text(
        """# Domain Glossary

## Terms

### `model_tier` (candidate neutral key under this feature)
- **Definition:** The requested neutral key.
""",
        encoding="utf-8",
    )
    (spec_dir / "requirements.lexicon.md").write_text(
        f"""# SOURCE: spec.md
# SOURCE_SHA256: {_hash_text(source)}
ARTIFACT: SPEC
TITLE: Model tier preservation

REQ: FR-001
GIVEN: an artifact declares model_tier
WHEN: the system runs inspect
THEN: the system MUST preserve model_tier
OUTPUT: preserved model_tier
DEPENDS: none
EXAMPLE: AC-001

AC: AC-001
GIVEN: an artifact declares model_tier
WHEN: the system runs inspect
THEN: model_tier is preserved
""",
        encoding="utf-8",
    )

    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="specs/001-model-tier",
        config={"lexicon_gate": {"enabled": True}},
        previous_attempts=2,
    )

    assert result.evaluation == "passed"
    assert result.passed is True
    assert result.attempts == 0
    assert result.findings == 0


def test_spec_gate_accepts_source_local_constraint_identifiers(
    tmp_path: Path,
) -> None:
    """Derived constraints may retain source-local measurement identifiers."""
    spec_dir = tmp_path / "specs" / "001-local-constraint"
    spec_dir.mkdir(parents=True)
    source = """# Feature Specification

## Functional Requirements

- **FR-001**: The view must present exactly one view. Constraint: view_count = 1.

## Acceptance Criteria

- **AC-001**: The Page Viewer sees exactly one view. Verifies: FR-001.
"""
    (spec_dir / "spec.md").write_text(source, encoding="utf-8")
    (spec_dir / "glossary.md").write_text("", encoding="utf-8")
    (spec_dir / "requirements.lexicon.md").write_text(
        f"""# SOURCE: spec.md
# SOURCE_SHA256: {_hash_text(source)}
ARTIFACT: SPEC
TITLE: Single view

REQ: FR-001
GIVEN: the application is available
WHEN: the Page Viewer opens the view
THEN: the view SHALL present exactly one view
OUTPUT: one rendered view
CONSTRAINT: view_count = 1
EXAMPLE: AC-001

AC: AC-001
GIVEN: the application is available
WHEN: the Page Viewer opens the view
THEN: the view presents exactly one view
CONSTRAINT: view_count = 1
""",
        encoding="utf-8",
    )

    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="specs/001-local-constraint",
        config={"lexicon_gate": {"enabled": True}},
        previous_attempts=0,
    )

    assert result.evaluation == "passed"
    assert result.findings == 0
