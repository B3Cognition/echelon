"""Controller-owned proportional Phase 1 quality repair accounting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from harness.proportional_quality import (
    AUTOMATIC_REPAIR_LIMIT,
    EXTENSION_REPAIR_LIMIT,
    QualityCandidateIntegrityError,
    QualityCandidateManifest,
    capture_quality_candidate,
    initialize_repair_state,
    rank_quality_candidates,
    record_what_outcome,
    restore_quality_candidate,
    validate_repair_state,
)


def _repair_state(**overrides: object) -> dict[str, object]:
    state = initialize_repair_state({"spec_authoring_mode": "proportional"})
    assert state is not None
    return {**state, **overrides}


def test_new_proportional_run_starts_with_controller_owned_limits() -> None:
    repair = initialize_repair_state({"spec_authoring_mode": "proportional"})

    assert repair == {
        "schema_version": 1,
        "authoring_mode": "proportional",
        "automatic_limit": AUTOMATIC_REPAIR_LIMIT,
        "automatic_consumed": 0,
        "extension_limit": EXTENSION_REPAIR_LIMIT,
        "extension_authorized": 0,
        "extension_consumed": 0,
        "migration_basis": "fresh",
        "baseline_candidate_id": None,
        "candidate_ids": [],
    }


def test_perfectionist_run_never_creates_proportional_repair_state() -> None:
    state = {"spec_authoring_mode": "perfectionist", "iteration": 4}

    assert initialize_repair_state(state) is None
    assert "phase1_quality_repair" not in state


def test_existing_valid_state_round_trips_detached_on_resume() -> None:
    existing = _repair_state(automatic_consumed=2, extension_authorized=1)

    restored = initialize_repair_state(
        {
            "spec_authoring_mode": "proportional",
            "phase1_quality_repair": existing,
        }
    )

    assert restored == existing
    assert restored is not existing
    restored["automatic_consumed"] = 1
    assert existing["automatic_consumed"] == 2


def _certified_why2_score(
    tmp_path: Path,
    *,
    iteration: int,
    passed: bool,
) -> dict[str, object]:
    report_path = tmp_path / f"phase1-why2-iter-{iteration}.json"
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "phase": "phase1-why2",
                "iteration": iteration,
                "spec": {"path": "specs/001/spec.md", "sha256": "a" * 64},
                "pass": passed,
            }
        ),
        encoding="utf-8",
    )
    digest = hashlib.sha256(report_path.read_bytes()).hexdigest()
    return {
        "pass": passed,
        "pass_id": f"WHY2-iter-{iteration}",
        "source": "harness:understanding",
        "evidence": str(report_path),
        "evidence_digest": digest,
        "overall": 0.9,
        "structure": 0.9,
        "readability": 0.9,
        "cognitive": 0.9,
        "semantic": 0.9,
        "testability": 0.9,
        "behavioral": 0.9,
        "depth": 0.9,
    }


def test_legacy_history_counts_completed_certified_why2_assessments(
    tmp_path: Path,
) -> None:
    repair = initialize_repair_state(
        {
            "quality_scores": [
                _certified_why2_score(tmp_path, iteration=0, passed=False),
                _certified_why2_score(tmp_path, iteration=1, passed=True),
                _certified_why2_score(tmp_path, iteration=2, passed=False),
                _certified_why2_score(tmp_path, iteration=3, passed=True),
                {"source": "agent", "pass_id": "WHY2-iter-99", "pass": True},
            ],
            "iteration": 0,
        }
    )

    assert repair is not None
    assert repair["automatic_consumed"] == 3
    assert repair["migration_basis"] == "why2_history"


@pytest.mark.parametrize(
    "mutate_score",
    [
        lambda score: score.pop("evidence_digest"),
        lambda score: score.update(evidence_digest="f" * 64),
        lambda score: score.update(pass_id="WHY2-iter-9"),
        lambda score: score.update(source="harness:forged"),
    ],
)
def test_partial_or_forged_why2_history_falls_back_to_global_iteration(
    tmp_path: Path,
    mutate_score,
) -> None:
    score = _certified_why2_score(tmp_path, iteration=0, passed=False)
    mutate_score(score)

    repair = initialize_repair_state(
        {"quality_scores": [score], "iteration": 2}
    )

    assert repair is not None
    assert repair["automatic_consumed"] == 2
    assert repair["migration_basis"] == "iteration_fallback"


def test_history_free_legacy_run_uses_capped_global_iteration() -> None:
    repair = initialize_repair_state({"iteration": 9})

    assert repair is not None
    assert repair["automatic_consumed"] == 3
    assert repair["migration_basis"] == "iteration_fallback"


def test_changed_valid_automatic_what_consumes_only_automatic_budget() -> None:
    original = _repair_state()

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=True,
        extension_active=False,
    )

    assert outcome.outcome == "consumed"
    assert outcome.repair_state["automatic_consumed"] == 1
    assert outcome.repair_state["extension_consumed"] == 0
    assert original["automatic_consumed"] == 0


def test_changed_valid_extension_what_consumes_only_extension_budget() -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=True,
        extension_active=True,
    )

    assert outcome.outcome == "consumed"
    assert outcome.repair_state["automatic_consumed"] == 0
    assert outcome.repair_state["extension_consumed"] == 1


def test_unchanged_valid_automatic_what_reports_no_progress_without_consuming() -> None:
    original = _repair_state()

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="a" * 64,
        valid_completion=True,
        extension_active=False,
    )

    assert outcome.outcome == "no_artifact_progress"
    assert outcome.repair_state["automatic_consumed"] == 0
    assert outcome.repair_state["extension_consumed"] == 0


def test_unchanged_valid_authorized_extension_consumes_extension_once() -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="a" * 64,
        valid_completion=True,
        extension_active=True,
    )

    assert outcome.outcome == "no_artifact_progress"
    assert outcome.repair_state["extension_consumed"] == 1


@pytest.mark.parametrize("valid_completion,extension_active", [(False, False), (False, True)])
def test_operational_what_outcome_never_consumes_budget(
    valid_completion: bool,
    extension_active: bool,
) -> None:
    original = _repair_state(extension_authorized=1)

    outcome = record_what_outcome(
        original,
        baseline_sha256="a" * 64,
        current_sha256="b" * 64,
        valid_completion=valid_completion,
        extension_active=extension_active,
    )

    assert outcome.outcome == "not_consumed"
    assert outcome.repair_state == original


@pytest.mark.parametrize(
    "override",
    [
        {"automatic_limit": 2},
        {"extension_limit": 2},
        {"automatic_consumed": -1},
        {"automatic_consumed": 4},
        {"extension_consumed": 2},
        {"authoring_mode": "perfectionist"},
        {"agent_override": True},
    ],
)
def test_invalid_or_agent_authored_repair_state_fails_closed(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        validate_repair_state(_repair_state(**override))


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("automatic_limit", True),
        ("automatic_limit", 3.0),
        ("extension_limit", True),
        ("extension_limit", 1.0),
        ("automatic_consumed", True),
        ("automatic_consumed", 0.0),
        ("extension_authorized", True),
        ("extension_authorized", 0.0),
        ("extension_consumed", True),
        ("extension_consumed", 0.0),
    ],
)
def test_repair_state_rejects_boolean_and_equal_valued_float_numbers(
    field: str,
    malformed: object,
) -> None:
    with pytest.raises(ValueError):
        validate_repair_state(_repair_state(**{field: malformed}))


def test_persisted_repair_key_cannot_be_replaced_with_agent_authored_null() -> None:
    with pytest.raises(ValueError):
        initialize_repair_state(
            {
                "spec_authoring_mode": "proportional",
                "phase1_quality_repair": None,
            }
        )


def _candidate(
    candidate_id: str,
    *,
    failed: int,
    margin: float,
    overall: float,
    statements: int,
    assessment: int,
    reasons: tuple[str, ...] = (),
) -> QualityCandidateManifest:
    return QualityCandidateManifest(
        schema_version=1,
        candidate_id=candidate_id,
        checkpoint_commit="a" * 40,
        owned_artifact_digests=(("spec.md", "b" * 64),),
        run_artifact_root="/run",
        understanding_evidence="/run/evidence/understanding.json",
        understanding_evidence_digest="c" * 64,
        normalized_gates=(("overall", overall, 0.8, overall >= 0.8),),
        sage_finding_routes=(),
        failed_gate_count=failed,
        worst_gate_margin=margin,
        overall_score=overall,
        formal_statement_count=statements,
        byte_count=100,
        repair_number=assessment,
        assessment_index=assessment,
        eligibility_reasons=reasons,
    )


def test_candidate_ranking_uses_the_complete_lexicographic_policy() -> None:
    candidates = (
        _candidate("later", failed=1, margin=-0.1, overall=0.7, statements=8, assessment=5),
        _candidate("more-statements", failed=1, margin=-0.1, overall=0.7, statements=9, assessment=1),
        _candidate("lower-overall", failed=1, margin=-0.1, overall=0.6, statements=1, assessment=0),
        _candidate("worse-margin", failed=1, margin=-0.2, overall=0.99, statements=1, assessment=0),
        _candidate("more-failures", failed=2, margin=0.0, overall=1.0, statements=1, assessment=0),
        _candidate("best", failed=0, margin=0.0, overall=0.8, statements=10, assessment=9),
        _candidate(
            "hard-blocked",
            failed=0,
            margin=1.0,
            overall=1.0,
            statements=1,
            assessment=0,
            reasons=("critical_sage_issue",),
        ),
    )

    ranked = rank_quality_candidates(candidates)

    assert tuple(item.candidate_id for item in ranked) == (
        "best",
        "later",
        "more-statements",
        "lower-overall",
        "worse-margin",
        "more-failures",
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _candidate_repo(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    spec_dir = repo / "runs" / "run-1" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    artifact_root = repo / "runs" / "run-1"
    evidence = artifact_root / "evidence" / "understanding" / "phase1-why2-iter-0.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "completed",
                "phase": "phase1-why2",
                "iteration": 0,
                "spec": {
                    "path": "runs/run-1/specs/001-demo/spec.md",
                    "sha256": hashlib.sha256(b"# Candidate zero\n").hexdigest(),
                },
                "thresholds": {"overall": 0.8},
                "scores": {"overall": 0.7},
                "gates": {
                    "overall": {
                        "score": 0.7,
                        "threshold": 0.8,
                        "pass": False,
                        "numeric_pass": False,
                        "pass_basis": "numeric_threshold",
                    }
                },
                "pass": False,
                "requirement_count": 2,
            }
        ) + "\n",
        encoding="utf-8",
    )
    for name, content in {
        "spec.md": "# Candidate zero\n",
        "requirements-overview.md": "# Overview zero\n",
        "quality-gates.md": "# Gates zero\n",
        "issues.md": "# Issues zero\n",
    }.items():
        (spec_dir / name).write_text(content, encoding="utf-8")
    (repo / "controller-state.json").write_text('{"iteration": 7}\n', encoding="utf-8")
    (repo / "README.md").write_text("original\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    return repo, spec_dir, artifact_root, evidence


def test_capture_persists_manifest_after_unique_checkpoint_and_updates_repair_state(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    repair = _repair_state()

    manifest = capture_quality_candidate(
        project_root=repo,
        spec_dir=spec_dir,
        run_artifact_root=artifact_root,
        run_id="run-1",
        spec_id="001-demo",
        candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={
            "overall": {"score": 0.7, "threshold": 0.8, "pass": False},
        },
        sage_finding_routes=({"issue_id": "SAGE-1", "route": "phase1-what"},),
        formal_statement_count=2,
        repair_number=0,
        assessment_index=0,
        eligibility_reasons=(),
        repair_state=repair,
    )

    persisted = json.loads(
        (artifact_root / "quality-candidates" / "quality-candidate-0.json").read_text()
    )
    assert persisted["checkpoint_commit"] == _git(repo, "rev-parse", "HEAD")
    assert persisted["owned_artifact_digests"] == dict(manifest.owned_artifact_digests)
    assert persisted["understanding_evidence_digest"] == hashlib.sha256(evidence.read_bytes()).hexdigest()
    assert repair["baseline_candidate_id"] == "quality-candidate-0"
    assert repair["candidate_ids"] == ["quality-candidate-0"]
    assert "Echelon-Phase: phase1-quality-candidate-0" in _git(repo, "log", "-1", "--format=%B")


def test_pre_candidate_repair_state_migrates_once_and_candidate_membership_is_strict() -> None:
    legacy = _repair_state()
    legacy.pop("baseline_candidate_id")
    legacy.pop("candidate_ids")

    migrated = validate_repair_state(legacy)

    assert migrated["baseline_candidate_id"] is None
    assert migrated["candidate_ids"] == []
    with pytest.raises(ValueError):
        validate_repair_state({**migrated, "baseline_candidate_id": "missing"})
    with pytest.raises(ValueError):
        validate_repair_state({**migrated, "candidate_ids": ["one", "one"], "baseline_candidate_id": "one"})
    with pytest.raises(ValueError):
        validate_repair_state(
            {
                **migrated,
                "candidate_ids": ["quality-candidate-1", "quality-candidate-0"],
                "baseline_candidate_id": "quality-candidate-1",
            }
        )


def test_restore_candidate_reads_only_owned_commit_artifacts_and_reverifies_evidence(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    repair = _repair_state()
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=repair,
    )
    for name in ("spec.md", "requirements-overview.md", "quality-gates.md", "issues.md"):
        (spec_dir / name).write_text(f"changed {name}\n", encoding="utf-8")
    _git(repo, "add", str(spec_dir.relative_to(repo)))
    _git(repo, "commit", "-m", "candidate one")
    (repo / "README.md").write_text("unrelated dirty\n", encoding="utf-8")

    checkpoint = restore_quality_candidate(
        repo, spec_dir, candidate, run_id="run-1", spec_id="001-demo"
    )

    assert (spec_dir / "spec.md").read_text() == "# Candidate zero\n"
    assert (spec_dir / "requirements-overview.md").read_text() == "# Overview zero\n"
    assert (repo / "README.md").read_text() == "unrelated dirty\n"
    assert (repo / "controller-state.json").read_text() == '{"iteration": 7}\n'
    assert checkpoint.phase == "phase1-quality-candidate-restored"
    assert checkpoint.commit == _git(repo, "rev-parse", "HEAD")
    assert evidence.is_file()


@pytest.mark.parametrize("breakage", ["missing_commit", "path_escape", "digest", "evidence"])
def test_restore_candidate_fails_closed_on_manifest_integrity_breakage(
    tmp_path: Path, breakage: str
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    values = dict(candidate.__dict__)
    if breakage == "missing_commit":
        values["checkpoint_commit"] = "f" * 40
    elif breakage == "path_escape":
        values["owned_artifact_digests"] = (("../README.md", "b" * 64),)
    elif breakage == "digest":
        values["owned_artifact_digests"] = tuple(
            (name, "f" * 64 if name == "spec.md" else digest)
            for name, digest in candidate.owned_artifact_digests
        )
    else:
        evidence.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(QualityCandidateIntegrityError):
        restore_quality_candidate(
            repo, spec_dir, QualityCandidateManifest(**values), run_id="run-1", spec_id="001-demo"
        )


def test_restore_candidate_rejects_dirty_owned_path(tmp_path: Path) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    (spec_dir / "spec.md").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(QualityCandidateIntegrityError, match="dirty"):
        restore_quality_candidate(repo, spec_dir, candidate, run_id="run-1", spec_id="001-demo")


def test_capture_rejects_malformed_markdown_before_checkpoint_or_manifest(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    (spec_dir / "spec.md").write_bytes(b"\xff\xfe")
    head_before = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(QualityCandidateIntegrityError, match="malformed"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )

    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert not (artifact_root / "quality-candidates" / "quality-candidate-0.json").exists()


def test_capture_rejects_understanding_evidence_for_a_different_spec(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["spec"]["sha256"] = "f" * 64
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(QualityCandidateIntegrityError, match="different spec"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )


def test_restore_checkpoint_failure_rolls_back_candidate_files(tmp_path: Path) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    current = {}
    for name in ("spec.md", "requirements-overview.md", "quality-gates.md", "issues.md"):
        current[name] = f"current {name}\n"
        (spec_dir / name).write_text(current[name], encoding="utf-8")
    _git(repo, "add", str(spec_dir.relative_to(repo)))
    _git(repo, "commit", "-m", "current candidate")
    (repo / ".git" / "index.lock").write_text("locked\n", encoding="utf-8")

    try:
        with pytest.raises(QualityCandidateIntegrityError, match="checkpoint"):
            restore_quality_candidate(
                repo, spec_dir, candidate, run_id="run-1", spec_id="001-demo"
            )
    finally:
        (repo / ".git" / "index.lock").unlink()

    assert {
        name: (spec_dir / name).read_text(encoding="utf-8")
        for name in current
    } == current


def test_restore_rejects_commit_without_the_candidate_checkpoint_identity(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    forged = QualityCandidateManifest(
        **{
            **candidate.__dict__,
            "checkpoint_commit": _git(repo, "rev-parse", f"{candidate.checkpoint_commit}^"),
        }
    )

    with pytest.raises(QualityCandidateIntegrityError, match="identity"):
        restore_quality_candidate(repo, spec_dir, forged, run_id="run-1", spec_id="001-demo")


@pytest.mark.parametrize(
    "normalized_gates",
    [
        {"overall": {"score": 1.0, "threshold": 0.8, "pass": True}},
        {"overall": {"score": 0.7, "threshold": 0.1, "pass": True}},
        {"overall": {"score": 0.7, "threshold": 0.8, "pass": True}},
        {
            "overall": {"score": 0.7, "threshold": 0.8, "pass": False},
            "invented": {"score": 1.0, "threshold": 0.0, "pass": True},
        },
        {
            "overall": {
                "score": 0.7,
                "threshold": 0.8,
                "pass": False,
                "unbound_margin": 1.0,
            }
        },
    ],
)
def test_capture_rejects_caller_gate_data_that_conflicts_with_immutable_evidence(
    tmp_path: Path,
    normalized_gates: dict[str, dict[str, object]],
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    repair = _repair_state()
    head_before = _git(repo, "rev-parse", "HEAD")

    with pytest.raises(QualityCandidateIntegrityError, match="gate"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence, normalized_gates=normalized_gates,
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=repair,
        )

    assert repair == _repair_state()
    assert _git(repo, "rev-parse", "HEAD") == head_before
    assert not (artifact_root / "quality-candidates" / "quality-candidate-0.json").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [("score", float("nan")), ("score", float("inf")), ("threshold", float("-inf"))],
)
def test_capture_rejects_nonfinite_gate_evidence(
    tmp_path: Path, field: str, value: float
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report[field + "s"]["overall"] = value
    report["gates"]["overall"][field] = value
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(QualityCandidateIntegrityError, match="gate"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )


def test_capture_rejects_internally_contradictory_evidence_verdict(tmp_path: Path) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["gates"]["overall"]["pass"] = True
    report["pass"] = True
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(QualityCandidateIntegrityError, match="gate"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": True}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )


def test_capture_rejects_formal_count_that_improves_ranking_tiebreak(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)

    with pytest.raises(QualityCandidateIntegrityError, match="formal statement"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=0, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )


@pytest.mark.parametrize(
    ("candidate_id", "assessment_index", "existing_ids"),
    [
        ("quality-candidate-5", 0, []),
        ("quality-candidate-1", 0, ["quality-candidate-0"]),
    ],
)
def test_capture_rejects_falsified_candidate_sequence_or_assessment_order(
    tmp_path: Path,
    candidate_id: str,
    assessment_index: int,
    existing_ids: list[str],
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    repair = _repair_state(
        candidate_ids=existing_ids,
        baseline_candidate_id=(existing_ids[0] if existing_ids else None),
    )
    original = json.loads(json.dumps(repair))

    with pytest.raises(QualityCandidateIntegrityError, match="sequence|assessment"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id=candidate_id,
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=assessment_index, eligibility_reasons=(), repair_state=repair,
        )

    assert repair == original
    assert not (artifact_root / "quality-candidates" / f"{candidate_id}.json").exists()


def test_capture_rejects_symlink_candidate_artifact(tmp_path: Path) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    target = repo / "outside-spec.md"
    target.write_text("# Symlink target\n", encoding="utf-8")
    (spec_dir / "spec.md").unlink()
    (spec_dir / "spec.md").symlink_to(target)

    with pytest.raises(QualityCandidateIntegrityError, match="regular"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
        )


def test_capture_rejects_checkpoint_blob_changed_by_git_clean_filter(tmp_path: Path) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    _git(repo, "config", "filter.candidate-clean.clean", "sed s/Candidate/Committed/")
    _git(repo, "config", "filter.candidate-clean.smudge", "cat")
    attributes = repo / ".gitattributes"
    relative_spec = (spec_dir / "spec.md").relative_to(repo).as_posix()
    attributes.write_text(f"{relative_spec} filter=candidate-clean\n", encoding="utf-8")
    _git(repo, "add", ".gitattributes")
    _git(repo, "commit", "-m", "configure candidate clean filter")
    (spec_dir / "spec.md").write_text("# Candidate filtered\n", encoding="utf-8")
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["spec"]["sha256"] = hashlib.sha256(
        b"# Candidate filtered\n"
    ).hexdigest()
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")
    repair = _repair_state()
    original_repair = json.loads(json.dumps(repair))

    with pytest.raises(QualityCandidateIntegrityError, match="checkpoint.*digest"):
        capture_quality_candidate(
            project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
            run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
            understanding_evidence=evidence,
            normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
            sage_finding_routes=(), formal_statement_count=2, repair_number=0,
            assessment_index=0, eligibility_reasons=(), repair_state=repair,
        )

    assert not (artifact_root / "quality-candidates" / "quality-candidate-0.json").exists()
    assert repair == original_repair


def test_restore_rejects_understanding_reference_outside_recorded_run_root(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    outside = repo / "outside-evidence.json"
    outside.write_bytes(evidence.read_bytes())
    forged = QualityCandidateManifest(
        **{
            **candidate.__dict__,
            "understanding_evidence": str(outside),
            "understanding_evidence_digest": hashlib.sha256(outside.read_bytes()).hexdigest(),
        }
    )

    with pytest.raises(QualityCandidateIntegrityError, match="run artifact root"):
        restore_quality_candidate(repo, spec_dir, forged, run_id="run-1", spec_id="001-demo")


def test_restore_rejects_reconstructed_evidence_for_different_manifest_spec(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["spec"]["sha256"] = "f" * 64
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")
    forged = QualityCandidateManifest(
        **{
            **candidate.__dict__,
            "understanding_evidence_digest": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
    )

    with pytest.raises(QualityCandidateIntegrityError, match="different spec"):
        restore_quality_candidate(repo, spec_dir, forged, run_id="run-1", spec_id="001-demo")


def test_restore_rejects_reconstructed_malformed_understanding_report(
    tmp_path: Path,
) -> None:
    repo, spec_dir, artifact_root, evidence = _candidate_repo(tmp_path)
    candidate = capture_quality_candidate(
        project_root=repo, spec_dir=spec_dir, run_artifact_root=artifact_root,
        run_id="run-1", spec_id="001-demo", candidate_id="quality-candidate-0",
        understanding_evidence=evidence,
        normalized_gates={"overall": {"score": 0.7, "threshold": 0.8, "pass": False}},
        sage_finding_routes=(), formal_statement_count=2, repair_number=0,
        assessment_index=0, eligibility_reasons=(), repair_state=_repair_state(),
    )
    report = json.loads(evidence.read_text(encoding="utf-8"))
    report["spec"].pop("path")
    evidence.write_text(json.dumps(report) + "\n", encoding="utf-8")
    forged = QualityCandidateManifest(
        **{
            **candidate.__dict__,
            "understanding_evidence_digest": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }
    )

    with pytest.raises(QualityCandidateIntegrityError, match="malformed"):
        restore_quality_candidate(repo, spec_dir, forged, run_id="run-1", spec_id="001-demo")
