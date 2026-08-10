"""Prompt contract tests for verify-spec reconciliation."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VERIFY_COMMAND = ROOT / "prosaic" / "commands" / "echelon.verify-spec.md"
VERIFY_INIT = ROOT / "runtime" / "workflow" / "phases" / "verify-spec-1-init.md"
VERIFY_RECONCILE = (
    ROOT / "runtime" / "workflow" / "phases" / "verify-spec-6-reconcile.md"
)
WORKFLOW = ROOT / "runtime" / "workflow" / "definition.yaml"


def test_verify_spec_command_documents_reconcile_exception() -> None:
    text = VERIFY_COMMAND.read_text(encoding="utf-8")

    assert "--reconcile" in text
    assert "--dry-run" in text
    assert "source code is always read-only" in text
    assert "tasks.md" in text
    assert "harness task-progress helpers" in text


def test_verify_spec_init_parses_reconcile_flags() -> None:
    text = VERIFY_INIT.read_text(encoding="utf-8")

    assert "--reconcile" in text
    assert "--dry-run" in text
    assert "reconcile" in text
    assert "dry_run" in text


def test_verify_spec_workflow_has_optional_reconcile_phase() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "verify-spec-6-reconcile" in text
    assert "condition: reconcile = true" in text
    assert "task-requirement-map.candidates.json" in text
    assert "task-requirement-map-applied.md" in text
    assert "progress-reconciliation-plan.md" in text


def test_reconcile_phase_requires_harness_apply_command() -> None:
    text = VERIFY_RECONCILE.read_text(encoding="utf-8")

    assert "write-task-requirement-mapping-candidates" in text
    assert "write-progress-reconciliation-candidates" in text
    assert "apply-progress-reconciliation" in text
    assert "progress-reconciliation-candidates.json" in text
    assert "progress-reconciliation-plan.md" in text
    assert "progress-reconciliation-applied.md" in text


def test_reconcile_phase_candidate_commands_stamp_state() -> None:
    text = VERIFY_RECONCILE.read_text(encoding="utf-8")

    assert "If `{verify_run_dir}/state.json` is missing, hard stop with BLOCKED" in text
    assert (
        '  "{verify_run_dir}/task-requirement-map.candidates.json" \\\n'
        '  "{verify_run_dir}/state.json"'
    ) in text
    assert "task_requirement_mapping_candidates: ready" in text
    assert (
        '  "{verify_run_dir}/progress-reconciliation-candidates.json" \\\n'
        '  "{verify_run_dir}/state.json"'
    ) in text
    assert "progress_reconciliation_candidates: ready" in text


def test_reconcile_phase_apply_commands_stamp_state() -> None:
    text = VERIFY_RECONCILE.read_text(encoding="utf-8")

    assert (
        '  "{verify_run_dir}" \\\n'
        '  "{verify_run_dir}/state.json"'
    ) in text
    assert "task_requirement_mapping: applied" in text
    assert "progress_reconciliation: applied" in text
    assert "dry_run" in text
    assert "safe/applied counts" in text


def test_reconcile_phase_maps_unmapped_task_requirements_before_done_updates() -> None:
    text = VERIFY_RECONCILE.read_text(encoding="utf-8")

    assert "task-requirement-map.candidates.json" in text
    assert "write-task-requirement-mapping-candidates" in text
    assert "apply-task-requirement-mapping" in text
    assert "req=UNMAPPED" in text
    assert "Run task requirement mapping before progress reconciliation" in text


def test_reconcile_phase_forbids_direct_tasks_editing() -> None:
    text = VERIFY_RECONCILE.read_text(encoding="utf-8")

    assert "NEVER edit task checkboxes" in text
    assert "python -m harness mark-task-progress" in text
    assert "ALWAYS use the deterministic harness command" in text
    assert "Do not hand-write\n`task-requirement-map.candidates.json`" in text
    assert "Do not hand-write\n`progress-reconciliation-candidates.json`" in text
