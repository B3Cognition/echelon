"""Tests for Python-owned spec run history updates."""

from __future__ import annotations

import json

import pytest

from harness.run_history import append_implementation_run, append_phase_a_run


@pytest.mark.unit
class TestRunHistory:
    def test_append_implementation_run_creates_authoritative_history(self, tmp_path):
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)

        append_implementation_run(
            spec_dir,
            run_id="run-1",
            spec_status="ready_to_land",
            verification_result="PASS",
        )

        data = json.loads((spec_dir / "run-history.json").read_text(encoding="utf-8"))
        assert data["authoritative_run"] == "run-1"
        assert data["runs"][0]["run_id"] == "run-1"
        assert data["runs"][0]["phase"] == "B"
        assert data["runs"][0]["status"] == "ready_to_land"
        assert data["runs"][0]["verification_result"] == "PASS"
        assert data["runs"][0]["spec_status"] == "ready_to_land"
        assert "timestamp" in data["runs"][0]

    def test_append_implementation_run_preserves_existing_runs(self, tmp_path):
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "run-history.json").write_text(
            json.dumps({"runs": [{"run_id": "phase-a", "phase": "A"}]}),
            encoding="utf-8",
        )

        append_implementation_run(
            spec_dir,
            run_id="run-2",
            spec_status="ready_to_land",
            verification_result="PASS",
        )

        data = json.loads((spec_dir / "run-history.json").read_text(encoding="utf-8"))
        assert [run["run_id"] for run in data["runs"]] == ["phase-a", "run-2"]
        assert data["authoritative_run"] == "run-2"

    def test_append_phase_a_run_records_done_once_per_run(self, tmp_path):
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)

        append_phase_a_run(
            spec_dir,
            run_id="squad-1",
            spec_status="planned",
            constitution_hash="abc123",
        )
        append_phase_a_run(
            spec_dir,
            run_id="squad-1",
            spec_status="planned",
            constitution_hash="def456",
        )

        data = json.loads((spec_dir / "run-history.json").read_text(encoding="utf-8"))
        assert len(data["runs"]) == 1
        assert data["runs"][0]["run_id"] == "squad-1"
        assert data["runs"][0]["phase"] == "A"
        assert data["runs"][0]["status"] == "done"
        assert data["runs"][0]["spec_status"] == "planned"
        assert data["runs"][0]["constitution_hash"] == "def456"

    def test_append_phase_a_run_records_complete_retarget_linkage(self, tmp_path):
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)

        append_phase_a_run(
            spec_dir,
            run_id="squad-replacement",
            spec_status="planned",
            constitution_hash="abc123",
            retarget_revision="retarget-1",
            supersedes_run_id="squad-base",
            baseline_checkpoint="retarget-preflight-retarget-1",
        )

        entry = json.loads((spec_dir / "run-history.json").read_text())["runs"][0]
        assert entry["retarget_revision"] == "retarget-1"
        assert entry["supersedes_run_id"] == "squad-base"
        assert entry["baseline_checkpoint"] == "retarget-preflight-retarget-1"
