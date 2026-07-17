"""Tests for Phase A KB proposal validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from echelon.kb_proposals import load_proposals, validate_proposal_document


def _base_proposal(**overrides):
    data = {
        "schema_version": 1,
        "proposal_id": "kb-prop-0001",
        "proposal_type": "pattern",
        "run_id": "squad-001",
        "agent": "speckit-echelon-mirror",
        "created_at": "2026-07-17T12:00:00Z",
        "targets": ["knowledge-base/patterns.yaml"],
        "confidence": 0.72,
        "source_artifacts": ["runs/squad-001/reasoning-journal.jsonl"],
        "evidence_refs": [
            {
                "artifact": "runs/squad-001/reasoning-journal.jsonl",
                "locator": "RJ-001",
                "claim": "WHY3 passed after constraint was added.",
            }
        ],
        "payload": {
            "name": "Architecture constraint before estimates",
            "domain": "planning",
            "description": "Apply explicit architecture constraints before estimates.",
            "tags": ["planning"],
            "status": "active",
            "project_fingerprint": "auto",
            "scope": "local_only",
        },
    }
    data.update(overrides)
    return data


def test_valid_pattern_proposal_passes() -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
    )

    assert result.ok is True
    assert result.issues == []


def test_rejects_scalar_target_contract() -> None:
    data = _base_proposal(target="knowledge-base/patterns.yaml")
    data.pop("targets")

    result = validate_proposal_document("bad.yaml", data)

    assert result.ok is False
    assert any(issue.path == "targets" for issue in result.issues)


def test_rejects_wrong_target_for_type() -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(targets=["knowledge-base/sage-decisions.yaml"]),
    )

    assert result.ok is False
    assert any(issue.path == "targets[0]" for issue in result.issues)


def test_operation_identity_is_run_id_plus_proposal_id() -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
    )

    assert result.operation_id == "squad-001/kb-prop-0001"


def test_load_proposals_reports_yaml_parse_failure(tmp_path: Path) -> None:
    proposal_dir = tmp_path / "kb-proposals"
    proposal_dir.mkdir()
    (proposal_dir / "bad.yaml").write_text("schema_version: [", encoding="utf-8")

    loaded = load_proposals(proposal_dir)

    assert len(loaded) == 1
    assert loaded[0].validation.ok is False
    assert loaded[0].data is None


@pytest.mark.parametrize("proposal_type", [["pattern"], {"type": "pattern"}])
def test_rejects_unhashable_proposal_type_without_raising(proposal_type) -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(proposal_type=proposal_type),
    )

    assert result.ok is False
    assert any(issue.path == "proposal_type" for issue in result.issues)


@pytest.mark.parametrize(
    "target",
    [["knowledge-base/patterns.yaml"], {"target": "knowledge-base/patterns.yaml"}],
)
def test_rejects_unhashable_target_without_raising(target) -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(targets=[target]),
    )

    assert result.ok is False
    assert any(issue.path == "targets[0]" for issue in result.issues)


@pytest.mark.parametrize("created_at", ["not-a-timestamp", "2026-99-99T99:99:99Z"])
def test_rejects_invalid_created_at(created_at: str) -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(created_at=created_at),
    )

    assert result.ok is False
    assert any(issue.path == "created_at" for issue in result.issues)


def test_rejects_boolean_confidence() -> None:
    result = validate_proposal_document(
        "bad.yaml",
        _base_proposal(confidence=True),
    )

    assert result.ok is False
    assert any(issue.path == "confidence" for issue in result.issues)
