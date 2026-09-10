from pathlib import Path
import hashlib
import json

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


@pytest.mark.unit
def test_spec_gate_parse_failure_does_not_mask_root_cause_with_source_id_noise(
    tmp_path: Path,
) -> None:
    """An invalid projection cannot establish a meaningful source-ID diff."""
    spec_dir = tmp_path / "specs" / "001-parse-root-cause"
    spec_dir.mkdir(parents=True)
    source = """# Feature Specification

## Functional Requirements

- **FR-001**: Preserve the visible scene.

## Acceptance Criteria

- **AC-001**: Given the scene, when rendered, then it remains visible.
"""
    (spec_dir / "spec.md").write_text(source, encoding="utf-8")
    (spec_dir / "requirements.lexicon.md").write_text(
        f"""# SOURCE: spec.md
# SOURCE_SHA256: {_hash_text(source)}
ARTIFACT: SPEC
TITLE: Parse root cause

REQ: FR-001
GIVEN: the scene is available
WHEN: it renders
THEN: the system MUST preserve the visible scene
OUTPUT: a visible scene
EXAMPLE: AC-001

AC: AC-001
GIVEN: the scene is available
WHEN: it renders
THEN: the visible scene is present
OUTPUT: visible_scene_count = 1 scene
""",
        encoding="utf-8",
    )

    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="specs/001-parse-root-cause",
        config={"lexicon_gate": {"enabled": True}},
        previous_attempts=0,
    )

    assert result.evaluation == "failed"
    report = json.loads((spec_dir / "spec-lexicon-report.json").read_text())
    codes = [finding["code"] for finding in report["findings"]]
    assert "parse-error" in codes
    assert not any(code.startswith("source-id-") for code in codes)


@pytest.mark.unit
def test_spec_gate_ignores_inherited_requirement_references_when_checking_source_ids(
    tmp_path: Path,
) -> None:
    """Only IDs declared by the current source belong in its projection."""
    spec_dir = tmp_path / "specs" / "001-inherited-references"
    spec_dir.mkdir(parents=True)
    source = """# Feature Specification

## Functional Requirements

- **FR-001**: Preserve the scene while retaining 003-base/FR-023 behavior. Constraint: `source_metric = 1 unit`.

## Acceptance Criteria

- **AC-001**: Given the scene, when rendered, then the preserved behavior remains visible.
"""
    (spec_dir / "spec.md").write_text(source, encoding="utf-8")
    (spec_dir / "requirements.lexicon.md").write_text(
        f"""# SOURCE: spec.md
# SOURCE_SHA256: {_hash_text(source)}
ARTIFACT: SPEC
TITLE: Inherited references

REQ: FR-001
GIVEN: the scene is available
WHEN: it renders
THEN: the system MUST preserve the visible scene
OUTPUT: the visible scene is preserved
CONSTRAINT: source_metric = 1 unit
EXAMPLE: AC-001

AC: AC-001
GIVEN: the scene is available
WHEN: it renders
THEN: the preserved behavior is visible
""",
        encoding="utf-8",
    )

    result = run_spec_lexicon_gate(
        project_root=tmp_path,
        spec_dir_ref="specs/001-inherited-references",
        config={"lexicon_gate": {"enabled": True}},
        previous_attempts=0,
    )

    assert result.evaluation == "passed"
    assert result.findings == 0
