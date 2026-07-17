"""Tests for Phase A KB proposal validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from echelon.kb_proposals import apply_proposals, load_proposals, validate_proposal_document


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


def test_apply_valid_pattern_writes_canonical_entry(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: 1\nentries: []\n", encoding="utf-8")
    run = project / "runs" / "squad-001" / "kb-proposals"
    run.mkdir(parents=True)
    proposal = _base_proposal()
    (run / "kb-prop-0001.yaml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "applied"
    assert report.accepted_count == 1
    data = yaml.safe_load((kb / "patterns.yaml").read_text(encoding="utf-8"))
    assert data["entries"][0]["operation_id"] == "squad-001/kb-prop-0001"
    assert data["entries"][0]["run_id"] == "squad-001"
    assert data["entries"][0]["project_fingerprint"] != "auto"


def test_apply_invalid_and_valid_mixed_run_continues(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: 1\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "bad.yaml").write_text("schema_version: [", encoding="utf-8")
    (proposal_dir / "good.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 1
    assert report.rejected_count == 1
    assert (project / "runs" / "squad-001" / "kb-apply-report.yaml").exists()


def test_apply_duplicate_operation_is_skipped(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text(
        "schema_version: 1\nentries:\n"
        "  - operation_id: squad-001/kb-prop-0001\n"
        "    run_id: squad-001\n"
        "    source: speckit-echelon-mirror\n"
        "    created_at: 2026-07-17T12:00:00Z\n"
        "    confidence: 0.8\n"
        "    project_fingerprint: a1b2c3d4e5f6\n"
        "    scope: local_only\n",
        encoding="utf-8",
    )
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "kb-prop-0001.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 0
    assert report.skipped_duplicate_count == 1
