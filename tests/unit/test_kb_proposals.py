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
    accepted_kb_target_paths,
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
        "agent": "echelon.mirror",
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


def _write_traceable_artifact(project: Path, run_id: str = "squad-001") -> None:
    artifact = project / "runs" / run_id / "reasoning-journal.jsonl"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text('{"id":"RJ-001","claim":"traceable"}\n', encoding="utf-8")


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


def test_publish_kb_reports_copies_usage_summary(tmp_path: Path) -> None:
    project = tmp_path
    run_dir = project / "runs" / "squad-001"
    run_dir.mkdir(parents=True)
    usage_text = "schema_version: 1\nrun_id: squad-001\n"
    (run_dir / "kb-usage.yaml").write_text(usage_text, encoding="utf-8")
    spec_dir = project / "specs" / "001-feature"

    published = publish_kb_reports(project, "squad-001", spec_dir)

    assert published == spec_dir / "kb"
    assert (spec_dir / "kb" / "kb-usage-summary.yaml").read_text(encoding="utf-8") == usage_text


def test_publish_kb_reports_returns_none_without_source_reports(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-feature"

    published = publish_kb_reports(tmp_path, "squad-001", spec_dir)

    assert published is None
    assert not (spec_dir / "kb").exists()


def test_accepted_kb_target_paths_returns_only_accepted_known_files(tmp_path: Path) -> None:
    target = tmp_path / "knowledge-base" / "sage-decisions.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("entries: []\n", encoding="utf-8")
    report = tmp_path / "runs" / "squad-001" / "kb-apply-report.yaml"
    report.parent.mkdir(parents=True)
    report.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "run_id": "squad-001",
                "outcomes": [
                    {"outcome": "accepted", "targets": ["knowledge-base/sage-decisions.yaml"]},
                    {"outcome": "rejected", "targets": ["knowledge-base/patterns.yaml"]},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert accepted_kb_target_paths(tmp_path, "squad-001") == (target,)


def test_accepted_kb_target_paths_rejects_unknown_accepted_file(tmp_path: Path) -> None:
    report = tmp_path / "runs" / "squad-001" / "kb-apply-report.yaml"
    report.parent.mkdir(parents=True)
    report.write_text(
        yaml.safe_dump(
            {
                "run_id": "squad-001",
                "outcomes": [{"outcome": "accepted", "targets": ["README.md"]}],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown target"):
        accepted_kb_target_paths(tmp_path, "squad-001")


def test_publish_kb_reports_failure_is_non_blocking(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    run_dir = project / "runs" / "squad-001"
    run_dir.mkdir(parents=True)
    (run_dir / "kb-apply-report.yaml").write_text("status: degraded\n", encoding="utf-8")
    spec_dir = project / "specs" / "001-feature"
    destination = spec_dir / "kb" / "kb-apply-report.yaml"
    original_write_text = Path.write_text

    def fail_publication(path: Path, *args, **kwargs):
        if path == destination:
            raise RuntimeError("publication failed unexpectedly")
        return original_write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_publication)

    assert publish_kb_reports(project, "squad-001", spec_dir) is None


def test_valid_pattern_proposal_passes() -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
    )

    assert result.ok is True
    assert result.issues == []


def test_validate_with_project_root_rejects_missing_source_artifact(tmp_path: Path) -> None:
    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        project_root=tmp_path,
    )

    assert result.ok is False
    assert any(issue.path == "source_artifacts[0]" for issue in result.issues)


def test_validate_with_project_root_accepts_traceable_source_artifact(tmp_path: Path) -> None:
    _write_traceable_artifact(tmp_path)

    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        _base_proposal(),
        expected_run_id="squad-001",
        project_root=tmp_path,
    )

    assert result.ok is True


def test_validate_with_project_root_rejects_missing_evidence_locator(tmp_path: Path) -> None:
    _write_traceable_artifact(tmp_path)
    proposal = _base_proposal(
        evidence_refs=[
            {
                "artifact": "runs/squad-001/reasoning-journal.jsonl",
                "locator": "RJ-999",
                "claim": "Not present in artifact.",
            }
        ]
    )

    result = validate_proposal_document(
        "kb-prop-0001.yaml",
        proposal,
        project_root=tmp_path,
    )

    assert result.ok is False
    assert any(issue.path == "evidence_refs[0].locator" for issue in result.issues)


def test_rejects_fictitious_agent_identity() -> None:
    proposal = _base_proposal(agent="echelon.invented")

    result = validate_proposal_document("bad-agent.yaml", proposal)

    assert result.ok is False
    assert any(issue.path == "agent" for issue in result.issues)


def test_rejects_legacy_hyphenated_agent_identity() -> None:
    result = validate_proposal_document(
        "bad-agent.yaml",
        _base_proposal(agent="echelon-mirror"),
    )

    assert result.ok is False
    assert any(issue.path == "agent" for issue in result.issues)


@pytest.mark.parametrize("value", [[["journal.jsonl"]], [None], [1]])
def test_rejects_non_string_source_artifacts(value) -> None:
    proposal = _base_proposal(source_artifacts=value)

    result = validate_proposal_document("bad-provenance.yaml", proposal)

    assert result.ok is False
    assert any(issue.path == "source_artifacts[0]" for issue in result.issues)


@pytest.mark.parametrize(
    "value",
    [
        ["not-a-mapping"],
        [{"artifact": "journal.jsonl", "locator": "RJ-001"}],
        [{"artifact": "journal.jsonl", "locator": 1, "claim": "supported"}],
    ],
)
def test_rejects_invalid_evidence_references(value) -> None:
    proposal = _base_proposal(evidence_refs=value)

    result = validate_proposal_document("bad-evidence.yaml", proposal)

    assert result.ok is False
    assert any(issue.path.startswith("evidence_refs[0]") for issue in result.issues)


def test_rejects_evidence_reference_not_declared_as_source_artifact() -> None:
    proposal = _base_proposal(
        source_artifacts=["runs/squad-001/other.jsonl"],
        evidence_refs=[
            {
                "artifact": "runs/squad-001/reasoning-journal.jsonl",
                "locator": "RJ-001",
                "claim": "WHY3 passed.",
            }
        ],
    )

    result = validate_proposal_document("bad-evidence.yaml", proposal)

    assert result.ok is False
    assert any(issue.path == "evidence_refs[0].artifact" for issue in result.issues)


def test_rejects_reserved_payload_provenance_fields() -> None:
    proposal = _base_proposal(
        payload={
            **_base_proposal()["payload"],
            "operation_id": "forged/run",
            "run_id": "forged-run",
            "source": "echelon.invented",
            "created_at": "1999-01-01T00:00:00Z",
        }
    )

    result = validate_proposal_document("bad-payload.yaml", proposal)

    assert result.ok is False
    assert {issue.path for issue in result.issues} >= {
        "payload.operation_id",
        "payload.run_id",
        "payload.source",
        "payload.created_at",
    }


@pytest.mark.parametrize("agent", ["mirror", "echelon."])
def test_rejects_unknown_agent_identity(agent: str) -> None:
    proposal = _base_proposal(agent=agent)

    result = validate_proposal_document("bad-agent.yaml", proposal)

    assert result.ok is False
    assert any(issue.path == "agent" for issue in result.issues)


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
    _write_traceable_artifact(project)
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
    assert data["entries"][0]["id"] == "pat-" + hashlib.sha256(
        b"squad-001/kb-prop-0001"
    ).hexdigest()[:12]
    assert data["entries"][0]["run_id"] == "squad-001"
    assert data["entries"][0]["project_fingerprint"] != "auto"


def test_apply_sage_entry_defaults_correctness_and_passes_canonical_schema(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "sage-decisions.yaml"
    target.write_text("schema_version: 2\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    proposal = _base_proposal(
        proposal_id="kb-prop-sage-0001",
        proposal_type="sage_decision",
        agent="echelon.sage",
        targets=["knowledge-base/sage-decisions.yaml"],
        payload={
            "artifact": "spec.md",
            "challenge_type": "missing_evidence",
            "challenge_summary": "Evidence is incomplete.",
            "outcome": "blocked",
            "resolution": "Obtain evidence.",
        },
    )
    (proposal_dir / "sage.yaml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "applied"
    entry = yaml.safe_load(target.read_text(encoding="utf-8"))["entries"][0]
    assert entry["was_correct"] is True


def test_apply_rejects_new_sage_entry_that_fails_canonical_validation(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "sage-decisions.yaml"
    original = "schema_version: 2\nappend_only: true\nentries: []\n"
    target.write_text(original, encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    proposal = _base_proposal(
        proposal_type="sage_decision",
        agent="echelon.sage",
        targets=["knowledge-base/sage-decisions.yaml"],
        payload={
            "artifact": "spec.md",
            "challenge_type": "invalid",
            "challenge_summary": "Evidence is incomplete.",
            "outcome": "blocked",
            "resolution": "Obtain evidence.",
            "was_correct": True,
        },
    )
    (proposal_dir / "invalid-sage.yaml").write_text(yaml.safe_dump(proposal), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.rejected_count == 1
    assert target.read_text(encoding="utf-8") == original


def test_load_proposals_rejects_later_duplicate_proposal_id(tmp_path: Path) -> None:
    proposal_dir = tmp_path / "kb-proposals"
    proposal_dir.mkdir()
    (proposal_dir / "first.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    (proposal_dir / "second.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    loaded = load_proposals(proposal_dir, expected_run_id="squad-001")

    assert loaded[0].validation.ok is True
    assert loaded[1].validation.ok is False
    assert any(
        issue.path == "proposal_id" and "duplicate" in issue.message
        for issue in loaded[1].validation.issues
    )


def test_apply_mixed_run_is_degraded_when_one_proposal_is_rejected(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text("schema_version: 1\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "accepted.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    (proposal_dir / "rejected.yaml").write_text("schema_version: [", encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 1
    assert report.rejected_count == 1
    assert report.status == "degraded"


def test_apply_invalid_and_valid_mixed_run_continues(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
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
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    (kb / "patterns.yaml").write_text(
        "schema_version: 1\nappend_only: true\nentries:\n"
        "  - operation_id: squad-001/kb-prop-0001\n"
        "    run_id: squad-001\n"
        "    source: echelon-mirror\n"
        "    created_at: '2026-07-17T12:00:00Z'\n"
        "    confidence: 0.8\n"
        "    id: pat-existing001\n"
        "    name: Existing constraint pattern\n"
        "    domain: planning\n"
        "    description: Existing entry used to test duplicate operation skipping.\n"
        "    tags: [planning]\n"
        "    status: active\n"
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
    _write_traceable_artifact(project)
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


def test_apply_rejects_preexisting_target_schema_debt_without_mutating(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    original = "schema_version: 1\nentries:\n  - legacy: true\n"
    target.write_text(original, encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "legacy.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.rejected_count == 1
    assert "existing target schema debt" in (report.outcomes[0].reason or "")
    assert target.read_text(encoding="utf-8") == original


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
    _write_traceable_artifact(project)
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


def test_apply_atomic_target_write_failure_preserves_original(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    target.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "write-failure.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    original_replace = kb_proposals.os.replace

    def fail_replace(source: Path, destination: Path):
        if destination == target:
            raise OSError("target is read-only")
        return original_replace(source, destination)

    monkeypatch.setattr(kb_proposals.os, "replace", fail_replace)

    report = apply_proposals(project, "squad-001")

    assert report.rejected_count == 1
    assert "target is read-only" in (report.outcomes[0].reason or "")
    assert target.read_text(encoding="utf-8") == original
    assert (project / "runs" / "squad-001" / "kb-apply-report.yaml").exists()


def test_apply_writes_durable_mutation_journal_before_canonical_write(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    target.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "accepted.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    original_replace = kb_proposals.os.replace
    observed = {"journal_exists_before_target_write": False}

    def observe_target_replace(source: Path, destination: Path):
        if destination == target:
            observed["journal_exists_before_target_write"] = (
                project / "runs" / "squad-001" / "kb-mutation-journal.jsonl"
            ).exists()
        return original_replace(source, destination)

    monkeypatch.setattr(kb_proposals.os, "replace", observe_target_replace)

    report = apply_proposals(project, "squad-001")

    assert report.accepted_count == 1
    assert observed["journal_exists_before_target_write"] is True
    journal = project / "runs" / "squad-001" / "kb-mutation-journal.jsonl"
    assert "squad-001/kb-prop-0001" in journal.read_text(encoding="utf-8")


def test_apply_lock_contention_rejects_without_mutating_target(tmp_path: Path) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    original = "schema_version: 1\nentries: []\n"
    target.write_text(original, encoding="utf-8")
    target.with_name(f"{target.name}.lock").write_text("another writer", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "contended.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.rejected_count == 1
    assert "target lock unavailable" in (report.outcomes[0].reason or "")
    assert target.read_text(encoding="utf-8") == original


def test_report_write_failure_rolls_back_canonical_mutation(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    target.write_text("schema_version: 1\nappend_only: true\nentries: []\n", encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "report-failure.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    original = target.read_text(encoding="utf-8")
    original_replace = kb_proposals.os.replace
    calls = {"report_writes": 0}

    def fail_final_report_replace(source: Path, destination: Path):
        if destination == project / "runs" / "squad-001" / "kb-apply-report.yaml":
            calls["report_writes"] += 1
            if calls["report_writes"] > 1:
                raise OSError("report filesystem is unavailable")
        return original_replace(source, destination)

    monkeypatch.setattr(kb_proposals.os, "replace", fail_final_report_replace)

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.accepted_count == 0
    assert report.rejected_count == 1
    assert "report filesystem is unavailable" in (report.report_error or "")
    assert target.read_text(encoding="utf-8") == original


def test_report_preflight_failure_skips_canonical_mutation(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path
    _write_traceable_artifact(project)
    kb = project / "knowledge-base"
    kb.mkdir()
    target = kb / "patterns.yaml"
    original = "schema_version: 1\nappend_only: true\nentries: []\n"
    target.write_text(original, encoding="utf-8")
    proposal_dir = project / "runs" / "squad-001" / "kb-proposals"
    proposal_dir.mkdir(parents=True)
    (proposal_dir / "preflight-failure.yaml").write_text(yaml.safe_dump(_base_proposal()), encoding="utf-8")
    original_replace = kb_proposals.os.replace

    def fail_report_replace(source: Path, destination: Path):
        if destination == project / "runs" / "squad-001" / "kb-apply-report.yaml":
            raise OSError("report filesystem is unavailable")
        return original_replace(source, destination)

    monkeypatch.setattr(kb_proposals.os, "replace", fail_report_replace)

    report = apply_proposals(project, "squad-001")

    assert report.status == "degraded"
    assert report.accepted_count == 0
    assert "report filesystem is unavailable" in (report.report_error or "")
    assert target.read_text(encoding="utf-8") == original


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
