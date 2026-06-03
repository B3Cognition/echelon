"""Tests for Python-owned spec run history updates."""

from __future__ import annotations

import json

import pytest

from harness.run_history import append_implementation_run


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
