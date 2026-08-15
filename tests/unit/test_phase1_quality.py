from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import harness.phase1_quality as quality_module
from harness.phase1_quality import (
    build_legacy_phase1_quality_certificate,
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


def _write_passing_sage_issues(spec_path: Path) -> Path:
    issues_path = spec_path.parent / "issues.md"
    issues_path.write_text(
        """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 0
- **Verdict:** PASS

## Issues

No issues found.
""",
        encoding="utf-8",
    )
    return issues_path


def _ordinary_assessment(project_root: Path, issues_path: Path) -> object:
    return quality_module.AuthoritativeQualityAssessment(
        numeric_pass=True,
        provider_verdict="PASS",
        sage_verdict="PASS",
        authoritative_issues=(),
        exact_routes=(),
        ordinary_pass=True,
        proportional_failure=False,
        hard_blockers=(),
        sage_evidence=quality_module.load_authoritative_sage_evidence_snapshot(
            issues_path,
            project_root=project_root,
        ),
    )


def _legacy_certificate(
    state: dict[str, object],
    *,
    project_root: Path,
) -> dict[str, object]:
    spec_path = project_root / str(state["spec_dir"]) / "spec.md"
    evidence = state["understanding_evidence"]
    assert isinstance(evidence, dict)
    report_path = Path(str(evidence["path"]))
    return {
        "schema_version": 1,
        "status": "passed",
        "source_path": spec_path.relative_to(project_root).as_posix(),
        "source_sha256": _sha256(spec_path),
        "understanding_evidence": report_path.relative_to(
            project_root
        ).as_posix(),
        "understanding_evidence_sha256": str(evidence["digest"]),
        "sage_phase": "phase1-why2",
    }


def test_phase1_quality_certificate_is_bound_to_current_spec_and_evidence(
    tmp_path: Path,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)

    certificate = _legacy_certificate(state, project_root=tmp_path)

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


def test_legacy_builder_preserves_perfectionist_certificate_shape(
    tmp_path: Path,
) -> None:
    state, _spec_path, _report_path = _quality_state(tmp_path)

    assert build_legacy_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    ) == _legacy_certificate(state, project_root=tmp_path)


def test_phase1_quality_certificate_rejects_tampered_understanding_evidence(
    tmp_path: Path,
) -> None:
    state, _spec_path, report_path = _quality_state(tmp_path)
    certificate = _legacy_certificate(state, project_root=tmp_path)
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
    certificate = _legacy_certificate(state, project_root=tmp_path)
    state["spec_quality_certificate"] = certificate
    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_schema_v2_certificate_binds_authoritative_sage_pass(
    tmp_path: Path,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)
    issues_path = _write_passing_sage_issues(spec_path)

    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
        authoritative_sage_assessment=_ordinary_assessment(
            tmp_path,
            issues_path,
        ),
    )

    assert certificate is not None
    assert certificate["schema_version"] == 2
    assert certificate["sage_evidence"] == "specs/001-demo/issues.md"
    assert certificate["sage_evidence_sha256"] == _sha256(issues_path)
    assert certificate["sage_verdict"] == "PASS"
    state["spec_quality_certificate"] = certificate
    assert has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_schema_v2_certificate_restart_currentness_rejects_sage_fail(
    tmp_path: Path,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)
    issues_path = _write_passing_sage_issues(spec_path)
    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
        authoritative_sage_assessment=_ordinary_assessment(
            tmp_path,
            issues_path,
        ),
    )
    assert certificate is not None
    state["spec_quality_certificate"] = certificate

    issues_path.write_text(
        """# Issues — WHY2

## Summary
- **CRITICAL:** 0
- **HIGH:** 0
- **MEDIUM:** 0
- **LOW:** 1
- **Verdict:** FAIL

## Issues

### ISS-QUALITY: Residual issue
- **Severity:** LOW
- **Type:** incompleteness
- **Description:** A required case remains incomplete.
- **Affected artifact:** spec.md
- **Affected section:** Requirements
- **Evidence:** The authoritative SAGE assessment records the gap.
- **Recommendation:** Complete the requirement.
- **Responsible agent:** WHAT
- **Action Required:** Amend the specification.
""",
        encoding="utf-8",
    )

    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_schema_v2_currentness_rejects_parse_hash_evidence_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)
    issues_path = _write_passing_sage_issues(spec_path)
    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
        authoritative_sage_assessment=_ordinary_assessment(
            tmp_path,
            issues_path,
        ),
    )
    assert certificate is not None
    state["spec_quality_certificate"] = certificate
    certified_bytes = issues_path.read_bytes()
    issues_path.write_bytes(certified_bytes + b"\n<!-- parsed snapshot -->\n")
    replacement = issues_path.with_suffix(".replacement.md")
    replacement.write_bytes(certified_bytes)
    real_read_bytes = Path.read_bytes
    issues_reads = 0

    def swap_before_digest(path: Path) -> bytes:
        nonlocal issues_reads
        if path == issues_path:
            issues_reads += 1
            if issues_reads == 2:
                replacement.replace(issues_path)
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", swap_before_digest)

    assert not has_current_phase1_quality_certificate(
        state,
        project_root=tmp_path,
    )


def test_schema_v2_certificate_restart_currentness_rejects_unsafe_sage_path(
    tmp_path: Path,
) -> None:
    state, spec_path, _report_path = _quality_state(tmp_path)
    issues_path = _write_passing_sage_issues(spec_path)
    certificate = build_phase1_quality_certificate(
        state,
        project_root=tmp_path,
        authoritative_sage_assessment=_ordinary_assessment(
            tmp_path,
            issues_path,
        ),
    )
    assert certificate is not None
    state["spec_quality_certificate"] = {
        **certificate,
        "sage_evidence": "../issues.md",
    }

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
