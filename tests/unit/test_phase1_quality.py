from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness.phase1_quality import (
    build_phase1_quality_certificate,
    has_current_phase1_quality_certificate,
    has_current_phase1_quality_prerequisite,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _quality_state(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    spec_path = spec_dir / "spec.md"
    spec_path.write_text("# Demo\n\n- **FR-001**: The system SHALL work.\n")

    evidence_dir = tmp_path / "runs" / "run-1" / "evidence" / "understanding"
    evidence_dir.mkdir(parents=True)
    report_path = evidence_dir / "phase1-why2-iter-0.json"
    report = {
        "schema_version": 1,
        "status": "completed",
        "phase": "phase1-why2",
        "iteration": 0,
        "spec": {
            "path": "specs/001-demo/spec.md",
            "sha256": _sha256(spec_path),
        },
        "thresholds": {},
        "scores": {},
        "gates": {},
        "pass": True,
        "requirement_count": 1,
        "per_requirement": [],
        "entity_analysis": {},
        "behavioral_analysis": {},
        "diagrams": {"enabled": False, "status": "skipped", "outputs": []},
        "findings": [],
        "generated_at": "2026-07-25T00:00:00+00:00",
    }
    report_path.write_text(json.dumps(report, sort_keys=True))
    report_digest = _sha256(report_path)
    state: dict[str, object] = {
        "spec_dir": "specs/001-demo",
        "completed_phases": ["phase1-understanding", "phase1-why2"],
        "understanding_evidence": {
            "phase": "phase1-why2",
            "iteration": 0,
            "status": "completed",
            "path": str(report_path),
            "digest": report_digest,
            "pass": True,
            "failing_gates": [],
            "error": None,
        },
        "quality_scores": [
            {
                "pass": True,
                "pass_id": "WHY2-iter-0",
                "source": "harness:understanding",
                "evidence": str(report_path),
                "evidence_digest": report_digest,
            }
        ],
    }
    return state, spec_path, report_path


def test_phase1_quality_certificate_is_bound_to_current_spec_and_evidence(
    tmp_path: Path,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)

    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )

    assert certificate is not None
    state["spec_quality_certificate"] = certificate
    assert has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )

    spec_path.write_text("# Amended\n\n- **FR-001**: The system SHALL work.\n")

    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_phase1_quality_certificate_rejects_tampered_understanding_evidence(
    tmp_path: Path,
) -> None:
    state, _spec_path, report_path = _quality_state(tmp_path)
    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )
    assert certificate is not None
    state["spec_quality_certificate"] = certificate

    report_path.write_text("{}")

    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_phase1_quality_certificate_requires_passing_why2_completion(
    tmp_path: Path,
) -> None:
    state, _spec_path, _report_path = _quality_state(tmp_path)
    state["completed_phases"] = ["phase1-understanding"]
    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )

    assert certificate is not None
    state["spec_quality_certificate"] = certificate
    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


@pytest.mark.parametrize(
    ("passing_certificate", "current_debt", "expected"),
    [
        (True, False, True),
        (False, True, True),
        (True, True, True),
        (False, False, False),
    ],
)
def test_phase1_quality_prerequisite_is_the_explicit_certificate_or_debt_union(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    passing_certificate: bool,
    current_debt: bool,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        "harness.phase1_quality.has_current_phase1_quality_certificate",
        lambda *_args, **_kwargs: passing_certificate,
    )
    monkeypatch.setattr(
        "harness.phase1_quality.has_current_quality_debt_authorization",
        lambda *_args, **_kwargs: current_debt,
    )

    assert has_current_phase1_quality_prerequisite(
        {},
        project_root=tmp_path,
    ) is expected
