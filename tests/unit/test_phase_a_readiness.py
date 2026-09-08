"""Deterministic Phase A build-input validation."""
from __future__ import annotations

from pathlib import Path

from harness.phase_a_readiness import (
    REQUIRED_PHASE_A_BUILD_INPUTS,
    coverage_contract_error,
    validate_phase_a_readiness,
)


def _write_required(spec_dir: Path) -> None:
    spec_dir.mkdir(parents=True)
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        content = (
            '{\n'
            '  "status": "pass",\n'
            '  "findings": [],\n'
            '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
            '}\n'
            if name == "plan-conformance.json"
            else f"# {name}\n"
        )
        (spec_dir / name).write_text(content, encoding="utf-8")


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


def test_ready_state_rejects_ambiguous_coverage_case_type_cardinality(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "spec.md").write_text("- **FR-001**: Animate collection.\n")
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-001 | UT-001; E2E-001/E2E-002 | unit/e2e | planned | planned | tests | implement |\n"
    )

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert not result.ready
    assert result.blockers == [
        "coverage-map.md invalid: coverage test type/case cardinality must be one or match case count"
    ]


def test_coverage_contract_error_returns_repairable_reason(tmp_path: Path) -> None:
    spec_dir = tmp_path / "001-demo"
    spec_dir.mkdir()
    (spec_dir / "spec.md").write_text("- **FR-001**: Animate collection.\n")
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-001 | UT-001; E2E-001/E2E-002 | unit/e2e | planned | planned | tests | implement |\n"
    )

    assert coverage_contract_error(spec_dir) == (
        "coverage test type/case cardinality must be one or match case count"
    )


def test_readiness_rejects_symbolic_case_without_rewriting_spec(tmp_path: Path) -> None:
    spec_dir = tmp_path / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "spec.md").write_text("- **FR-001**: Collect one item.\n")
    coverage = (
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-001 | C-HTTP-001..N | contract | automated | automated | tests | implement |\n"
    )
    path = spec_dir / "coverage-map.md"
    path.write_text(coverage)

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert not result.ready
    assert "C-HTTP-001..N" in result.blockers[0]
    assert "enumerate each case" in result.blockers[0]
    assert path.read_text() == coverage


def test_ready_state_rejects_task_owned_case_missing_from_coverage_map(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "spec.md").write_text("- **FR-001**: Animate collection.\n")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001 depends=none\n"
        "  **Named Test Ownership:** `UT-GEST-001`, `UT-GEST-006`.\n"
    )
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement ID | Test Case ID | Test Type | Automation Status | Coverage Type | Evidence | Gap / Action |\n"
        "|---|---|---|---|---|---|---|\n"
        "| FR-001 | UT-GEST-001 | unit | automated | direct | tests | none |\n"
    )

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert result.ready is False
    assert result.blockers == [
        "coverage-map.md invalid: task-owned test cases are absent from "
        "coverage-map.md: UT-GEST-006"
    ]


def test_ready_state_requires_all_mandatory_sentinel_outputs(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    for name in (
        "spec.md",
        "plan.md",
        "research.md",
        "data-model.md",
        "tasks.md",
        "constitution.md",
        "requirements-overview.md",
    ):
        (spec_dir / name).write_text(f"# {name}\n", encoding="utf-8")

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert not result.ready
    assert set(result.missing) == {
        "00-overview.md",
        "plan-conformance.md",
        "plan-conformance.json",
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    }


def test_ready_state_requires_final_overview_and_conformance_outputs(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    for name in ("00-overview.md", "plan-conformance.md", "plan-conformance.json"):
        (spec_dir / name).unlink(missing_ok=True)

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert not result.ready
    assert set(result.missing) == {
        "00-overview.md",
        "plan-conformance.md",
        "plan-conformance.json",
    }


def test_ready_state_rejects_invalid_plan_conformance_json(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "plan-conformance.json").write_text(
        '{"status": "maybe", "findings": [], "sources": []}\n',
        encoding="utf-8",
    )

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert not result.ready
    assert "plan-conformance.json invalid" in result.blockers[0]


def test_ready_state_accepts_minimal_valid_plan_conformance_json(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "plan-conformance.json").write_text(
        (
            '{\n'
            '  "status": "pass",\n'
            '  "findings": [],\n'
            '  "sources": ["spec.md", "requirements-overview.md", "plan.md", "tasks.md"]\n'
            '}\n'
        ),
        encoding="utf-8",
    )

    result = validate_phase_a_readiness({"status": "done"}, [spec_dir])

    assert result.ready


def test_ready_state_rejects_placeholder_constitution(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "constitution.md").write_text(
        "# Constitution\n\nProject: [PROJECT_NAME]\n",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {"status": "done", "completed_phases": ["phase1-constitution"]},
        [spec_dir],
    )

    assert not result.ready
    assert "constitution.md contains unresolved template markers" in result.blockers[0]


def test_ready_state_allows_sync_impact_report_placeholder_history(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "constitution.md").write_text(
        """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### I. Real Principle

Ready.
""",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {"status": "done", "completed_phases": ["phase1-constitution"]},
        [spec_dir],
    )

    assert result.ready


def test_ready_state_still_rejects_body_placeholder_after_sync_report(tmp_path: Path) -> None:
    spec_dir = tmp_path / "runs" / "run-1" / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "constitution.md").write_text(
        """<!--
Sync Impact Report
Modified principles:
  - [PRINCIPLE_1_NAME] -> I. Real Principle
-->

# Constitution

## Core Principles

### [PRINCIPLE_2_NAME]
""",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {"status": "done", "completed_phases": ["phase1-constitution"]},
        [spec_dir],
    )

    assert not result.ready
    assert "[PRINCIPLE_2_NAME]" in result.blockers[0]


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


def test_active_retarget_blocks_public_readiness(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_required(spec_dir)

    result = validate_phase_a_readiness(
        {
            "status": "done",
            "retarget": {
                "revision_id": "rt-1",
                "status": "finalizing",
                "replacement_targets": ["apps/web"],
            },
        },
        [spec_dir],
    )

    assert result.ready is False
    assert result.blockers == ["retarget revision rt-1 is finalizing"]


def test_controller_staging_can_validate_finalizing_retarget(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "targets.yml").write_text(
        "targets:\n  - apps/web\n", encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=REQ-1 depends=none "
        "target=apps/web\n",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {
            "status": "done",
            "implementation_targets": ["apps/web"],
            "retarget": {
                "revision_id": "rt-1",
                "status": "finalizing",
                "replacement_targets": ["apps/web"],
            },
        },
        [spec_dir],
        allow_pending_retarget_finalization=True,
    )

    assert result.ready is True


def test_finalizing_bypass_still_enforces_replacement_target_contract(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "targets.yml").write_text(
        "targets:\n  - services/api\n", encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=REQ-1 depends=none "
        "target=apps/web\n",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {
            "status": "done",
            "implementation_targets": ["apps/web"],
            "retarget": {
                "revision_id": "rt-1",
                "status": "finalizing",
                "replacement_targets": ["apps/web"],
            },
        },
        [spec_dir],
        allow_pending_retarget_finalization=True,
    )

    assert not result.ready
    assert any("replacement target" in blocker for blocker in result.blockers)


def test_completed_retarget_readiness_requires_authoritative_target_contract(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "targets.yml").write_text("targets:\n  - services/api\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=REQ-1 depends=none target=apps/web\n"
        "**Files:**\n"
        "- `sources/apps/ui.ts`\n"
        "- [ ] T-002 complexity=standard phase=build req=REQ-1 depends=none\n",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {
            "status": "done",
            "implementation_targets": ["apps/web"],
            "retarget": {
                "revision_id": "rt-1",
                "status": "complete",
                "replacement_targets": ["apps/web"],
            },
        },
        [spec_dir],
    )

    assert result.ready is False
    assert any("replacement target" in blocker for blocker in result.blockers)
    assert any("exactly one target" in blocker for blocker in result.blockers), result.blockers


def test_recovered_retarget_readiness_uses_restored_old_target_contract(
    tmp_path: Path,
) -> None:
    spec_dir = tmp_path / "specs" / "001-demo"
    _write_required(spec_dir)
    (spec_dir / "targets.yml").write_text(
        "targets:\n  - services/api\n", encoding="utf-8"
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=REQ-1 depends=none "
        "target=services/api\n",
        encoding="utf-8",
    )

    result = validate_phase_a_readiness(
        {
            "status": "done",
            "implementation_targets": ["services/api"],
            "retarget": {
                "revision_id": "rt-1",
                "status": "recovered",
                "old_targets": ["services/api"],
                "replacement_targets": ["apps/web"],
            },
        },
        [spec_dir],
    )

    assert result.ready is True
    assert result.blockers == []
