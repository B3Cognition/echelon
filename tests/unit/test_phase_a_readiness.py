"""Deterministic Phase A build-input validation."""
from __future__ import annotations

from pathlib import Path

from harness.phase_a_readiness import (
    REQUIRED_PHASE_A_BUILD_INPUTS,
    validate_phase_a_readiness,
)


def _write_required(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")


def test_ready_state_requires_all_core_build_input_artifacts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "spec.md").unlink()

    result = validate_phase_a_readiness(
        {"status": "done", "completed_phases": ["phase1-constitution"]},
        [spec_dir],
    )

    assert not result.ready
    assert result.missing == {"spec.md": [spec_dir]}
    assert "spec.md absent" in result.blockers[0]


def test_ready_state_passes_when_core_build_inputs_exist(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)

    result = validate_phase_a_readiness(
        {"status": "done", "completed_phases": ["phase1-constitution"]},
        [spec_dir],
    )

    assert result.ready
    assert result.blockers == []
    assert result.ready_spec_dir == spec_dir


def test_blocked_state_is_never_ready_even_with_artifacts(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)

    result = validate_phase_a_readiness(
        {
            "status": "blocked",
            "blocked_reason": "missing_echelon_result",
            "completed_phases": ["phase1-constitution"],
        },
        [spec_dir],
    )

    assert not result.ready
    assert result.blockers == ["run status is blocked: missing_echelon_result"]
