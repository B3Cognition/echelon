"""Tests for Phase A KB proposal validation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest
import yaml

import echelon.kb_proposals as kb_proposals
from echelon.kb_proposals import (
    _project_fingerprint,
    apply_proposals,
    load_proposals,
    publish_kb_reports,
    validate_proposal_document,
)


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


def test_publish_kb_reports_copies_apply_report_to_spec_dir(tmp_path: Path) -> None:
    project = tmp_path
    run_dir = project / "runs" / "squad-001"
    run_dir.mkdir(parents=True)
    (run_dir / "kb-apply-report.yaml").write_text(
        "schema_version: 1\nrun_id: squad-001\nstatus: degraded\n",
        encoding="utf-8",
    )
    spec_dir = project / "specs" / "001-feature"
    spec_dir.mkdir(parents=True)

    published = publish_kb_reports(project, "squad-001", spec_dir)

    assert published == spec_dir / "kb"
    assert (spec_dir / "kb" / "kb-apply-report.yaml").exists()


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
    (kb / "patterns.yaml").write_text(
        "schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8"
    )
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
    (kb / "patterns.yaml").write_text(
        "schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8"
    )
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
        "schema_version: 1\nappend_only: true\nentries:\n"
        "  - operation_id: squad-001/kb-prop-0001\n"
        "    run_id: squad-001\n"
        "    source: speckit-echelon-mirror\n"
        "    created_at: '2026-07-17T12:00:00Z'\n"
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


def test_apply_rejects_invalid_result_without_writing(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    original = "schema_version: 1\nappend_only: true\nentries: []\n"
    target.write_text(original, encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    proposal = _base_proposal()
    proposal["payload"]["scope"] = "invalid"
    (proposal_dir / "bad-result.yaml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.rejected_count == 1
    assert "resulting target schema invalid" in (report.outcomes[0].reason or "")
    assert target.read_text(encoding="utf-8") == original


def test_apply_preserves_preexisting_target_schema_debt_and_appends(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    original = "schema_version: 1\nentries:\n  - legacy: true\n"
    target.write_text(original, encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "legacy.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 1
    assert "existing target schema debt" in (report.outcomes[0].reason or "")
    updated = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert len(updated["entries"]) == 2
    assert updated["entries"][1]["operation_id"] == "squad-001/kb-prop-0001"


def test_project_fingerprint_is_stable_independent_of_cwd(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()

    monkeypatch.chdir(project)
    first = _project_fingerprint(project)
    monkeypatch.chdir(other_cwd)
    second = _project_fingerprint(project)

    assert first == second
    assert len(first) == 12
    assert first == first.lower()


def test_apply_malformed_target_continues_to_valid_proposal(tmp_path: Path) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: [", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "bad-target.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    valid_kb = project / "knowledge-base" / "pitfalls.yaml"
    valid_kb.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    valid = _base_proposal(
        proposal_id="kb-prop-0002",
        proposal_type="pitfall",
        targets=["knowledge-base/pitfalls.yaml"],
        payload={
            "name": "Avoid unclear constraints",
            "domain": "planning",
            "trigger": "constraint omitted",
            "impact": "rework",
            "avoidance": "state constraints first",
            "tags": ["planning"],
            "status": "active",
            "project_fingerprint": "auto",
            "scope": "local_only",
        },
    )
    (proposal_dir / "good-target.yaml").write_text(yaml.safe_dump(valid), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.rejected_count == 1
    assert report.accepted_count == 1
    assert (valid_kb.exists())


def test_apply_target_write_failure_is_reported_and_report_is_written(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    target.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "write-failure.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    original_write_text = Path.write_text

    def fail_target_write(path: Path, *args, **kwargs):
        if path == target:
            raise OSError("target is read-only")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_target_write)

    report = apply_proposals(project, "squad-001")

    assert report.rejected_count == 1
    assert "target is read-only" in (report.outcomes[0].reason or "")
    assert (project / "runs" / "squad-001" / "kb-apply-report.yaml").exists()


def test_report_write_failure_returns_degraded_report(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    target.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "report-failure.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    report_path = project / "runs" / "squad-001" / "kb-apply-report.yaml"
    original_write_text = Path.write_text

    def fail_report_write(path: Path, *args, **kwargs):
        if path == report_path:
            raise OSError("report filesystem is unavailable")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_report_write)

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.accepted_count == 1
    assert "report filesystem is unavailable" in (report.report_error or "")


def test_project_fingerprint_prefers_git_origin(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    origin = "https://example.test/echelon/project.git"
    subprocess.run(["git", "-C", str(project), "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(project), "remote", "add", "origin", origin],
        check=True,
        capture_output=True,
    )

    expected = hashlib.sha256(origin.encode("utf-8")).hexdigest()[:12]

    assert _project_fingerprint(project) == expected


def test_apply_missing_yaml_returns_degraded_report(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    real_import = __import__

    def fail_yaml_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("PyYAML unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_yaml_import)

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert "PyYAML unavailable" in (report.report_error or "")


def test_apply_loader_failure_returns_degraded_report(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)

    def fail_loader(*args, **kwargs):
        raise OSError("proposal directory cannot be enumerated")

    monkeypatch.setattr(kb_proposals, "load_proposals", fail_loader)

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.rejected_count == 1
    assert "proposal directory cannot be enumerated" in (report.outcomes[0].reason or "")
    assert (project / "runs" / "squad-001" / "kb-apply-report.yaml").exists()
