"""Unit tests for deterministic, read-only spec-retarget eligibility."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess

import pytest

from echelon.spec_retarget import RetargetEvidence, classify_retarget, collect_retarget_evidence


def eligible_evidence(tmp_path: Path) -> RetargetEvidence:
    return RetargetEvidence(
        spec_id="001-demo",
        run_id="squad-base",
        run_dir=tmp_path / "runs/squad-base",
        spec_dir=tmp_path / "specs/001-demo",
        feature_branch="001-demo",
        current_branch="001-demo",
        active_run_id="squad-base",
        canonical_targets=("services/api",),
        state_targets=("services/api",),
        replacement_targets=("apps/web",),
        lifecycle_status="planned",
        phase_b_history=(),
        delivery_state_paths=(),
        completed_task_ids=(),
        post_phase_a_artifacts=(),
        selected_spec_dirty_paths=(),
        original_user_message="Build account search",
        autonomy_mode="semi",
        product_inputs_recoverable=True,
        published_re_recoverable=True,
    )


@pytest.mark.unit
def test_classifier_accepts_ready_phase_a_without_using_artifact_stage(tmp_path: Path) -> None:
    result = classify_retarget(eligible_evidence(tmp_path))

    assert result.eligible is True
    assert result.reason_codes == ()


@pytest.mark.unit
def test_classifier_rejects_any_delivery_evidence(tmp_path: Path) -> None:
    evidence = replace(
        eligible_evidence(tmp_path),
        phase_b_history=("run-history.json:r-2",),
        delivery_state_paths=("runs/build-001/state.json",),
    )

    result = classify_retarget(evidence)

    assert result.eligible is False
    assert "retarget_delivery_already_started" in result.reason_codes
    assert result.next_command == "echelon spec run 'Build account search' --target apps/web"


@pytest.mark.unit
def test_classifier_rejects_active_pointer_or_target_drift(tmp_path: Path) -> None:
    evidence = replace(
        eligible_evidence(tmp_path),
        active_run_id="squad-other",
        state_targets=("apps/web",),
    )

    result = classify_retarget(evidence)

    assert set(result.reason_codes) == {
        "retarget_active_spec_mismatch",
        "retarget_target_contract_mismatch",
    }
    assert result.next_command == "echelon spec switch 001-demo"


def _git(project_root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project_root, check=True, capture_output=True)


@pytest.mark.unit
def test_collect_evidence_reads_exact_spec_delivery_markers_without_writing(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "001-demo")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: planned\n---\n# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "targets.yml").write_text("targets:\n  - services/api\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(
        "- [x] T-001 target=services/api\n",
        encoding="utf-8",
    )
    (spec_dir / "run-history.json").write_text(
        json.dumps({"runs": [{"run_id": "build-1", "phase": "B"}]}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs/squad-base"
    run_dir.mkdir(parents=True)
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "squad-base",
                "spec_id": "001-demo",
                "feature_branch": "001-demo",
                "spec_dir": "specs/001-demo",
                "targets": ["services/api"],
                "original_user_message": "Build account search",
                "autonomy_mode": "semi",
                "product_inputs": {"recoverable": True},
                "published_re_context": {"status": "attached"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "runs/.current").write_text("squad-base\n", encoding="utf-8")
    state_dir = tmp_path / "runs/build-001/state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        json.dumps({"spec_id": "001-demo"}), encoding="utf-8"
    )
    before = {
        path: path.read_bytes()
        for path in (spec_dir / "spec.md", spec_dir / "targets.yml", run_dir / "state.json")
    }

    evidence = collect_retarget_evidence(tmp_path, "001-demo")

    assert evidence.canonical_targets == ("services/api",)
    assert evidence.state_targets == ("services/api",)
    assert evidence.phase_b_history == ("run-history.json:build-1",)
    assert evidence.delivery_state_paths == ("runs/build-001/state/default.json",)
    assert evidence.completed_task_ids == ("T-001",)
    assert evidence.product_inputs_recoverable is True
    assert evidence.published_re_recoverable is True
    assert {path: path.read_bytes() for path in before} == before
