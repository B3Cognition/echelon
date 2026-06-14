"""Tests for fulfillment verification prompt orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from harness.fulfillment_runner import FulfillmentRunner
from kernel.fulfillment import read_fulfillment_metadata


@pytest.mark.unit
class TestFulfillmentRunner:
    def test_refresh_builds_verify_spec_prompt_and_runs_provider(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 0

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 0
        provider.exec_prompt.assert_called_once()
        worktree_path, prompt = provider.exec_prompt.call_args.args
        assert worktree_path == str(tmp_path)
        assert "You are COMMANDER" in prompt
        assert "verify spec-001" in prompt

    def test_refresh_returns_127_when_verify_spec_skill_missing(self, tmp_path):
        provider = MagicMock()
        provider.cli = "claude"

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 127
        provider.exec_prompt.assert_not_called()

    def test_refresh_stamps_latest_fulfillment_report_on_success(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 0
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"

    def test_refresh_rejects_report_with_ids_not_in_requirement_audit(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        report = spec_dir / "fulfillment-report.md"
        run_dir = tmp_path / "runs" / "verify-spec-spec-001-20260614"
        run_dir.mkdir(parents=True)
        (run_dir / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | FR | spec.md | Build one thing | Test one thing |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"

        def write_mismatched_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
                "| FR-999 | IMPLEMENTED | src/b.py | high | invented row |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_mismatched_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result == 2
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_uses_orchestration_spec_dir_for_polyrepo_runs(self, tmp_path):
        worktree = tmp_path / "runs" / "build-1" / "worktrees" / "default" / "iter-0"
        skill_dir = worktree / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        orchestration_root = tmp_path / "polyrepo"
        spec_dir = orchestration_root / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(
                str(worktree),
                "spec-001",
                orchestration_root=orchestration_root,
            )

        assert result == 0
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert f"verify spec-001 spec_dir={spec_dir}" in prompt
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"
