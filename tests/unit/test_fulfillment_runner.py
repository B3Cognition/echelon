"""Tests for fulfillment verification prompt orchestration."""

from __future__ import annotations

import os
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from harness.fulfillment_runner import FulfillmentRunner
from kernel.fulfillment import read_fulfillment_metadata


def _write_verify_skill(root):
    skill_dir = root / ".claude" / "skills" / "speckit-echelon-verify-spec"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.md").write_text(
        "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
        encoding="utf-8",
    )


def _write_spec_inputs(spec_dir, *, tasks: str = "# Tasks\n") -> None:
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
    (spec_dir / "plan.md").write_text("# Plan\n", encoding="utf-8")
    (spec_dir / "tasks.md").write_text(tasks, encoding="utf-8")


def _write_matching_audit(root, spec_id: str = "spec-001") -> None:
    run_dir = root / "runs" / f"verify-spec-{spec_id}-20260615"
    run_dir.mkdir(parents=True)
    (run_dir / "requirement-audit.md").write_text(
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | FR | spec.md | Build one thing | Test one thing |\n",
        encoding="utf-8",
    )


def _write_matching_report(report) -> None:
    report.write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
        encoding="utf-8",
    )


@pytest.mark.unit
class TestFulfillmentRunner:
    def test_refresh_builds_verify_spec_prompt_and_runs_provider(self, tmp_path):
        _write_verify_skill(tmp_path)
        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 0

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert result.used_cache is False
        provider.exec_prompt.assert_called_once()
        worktree_path, prompt = provider.exec_prompt.call_args.args
        assert worktree_path == str(tmp_path)
        assert "You are COMMANDER" in prompt
        assert "verify spec-001" in prompt

    def test_refresh_returns_127_when_verify_spec_skill_missing(self, tmp_path):
        provider = MagicMock()
        provider.cli = "claude"

        result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 127
        assert result.status == "missing_skill"
        assert result.used_cache is False
        provider.exec_prompt.assert_not_called()

    def test_refresh_stamps_latest_fulfillment_report_on_success(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"

        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text("# Fulfillment\n", encoding="utf-8")
            return 0

        provider.exec_prompt.side_effect = write_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert result.scope == "full"
        assert result.reason == "full verify-spec completed"
        assert result.report_path == str(report)
        assert isinstance(result.cache_key, str)
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"
        assert metadata["verify_scope"] == "full"
        assert isinstance(metadata["spec_input_hash"], str)
        assert isinstance(metadata["verify_cache_key"], str)

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

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_fails_when_report_drops_canonical_inventory_row(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("- FR-001\n- FR-002\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"
        run_dir = tmp_path / "runs" / "verify-spec-spec-001-20260616"
        run_dir.mkdir(parents=True)
        (run_dir / "canonical-requirements.json").write_text(
            '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
            encoding="utf-8",
        )
        (run_dir / "requirement-audit.md").write_text(
            "| ID | Category |\n"
            "| --- | --- |\n"
            "| FR-001 | functional |\n",
            encoding="utf-8",
        )

        provider = MagicMock()
        provider.cli = "claude"

        def write_report_missing_inventory_row(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "|---|---|---|---|---|\n"
                "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_report_missing_inventory_row

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_rejects_large_audit_scope_drop_without_scope_change(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"

        previous = tmp_path / "runs" / "verify-spec-spec-001-previous"
        current = tmp_path / "runs" / "verify-spec-spec-001-current"
        previous.mkdir(parents=True)
        current.mkdir(parents=True)
        previous_rows = "\n".join(
            f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 101)
        )
        current_rows = "\n".join(
            f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 61)
        )
        (previous / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"{previous_rows}\n",
            encoding="utf-8",
        )
        (current / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"{current_rows}\n",
            encoding="utf-8",
        )
        os.utime(spec_dir / "spec.md", (50, 50))
        os.utime(previous / "requirement-audit.md", (100, 100))
        os.utime(current / "requirement-audit.md", (200, 200))

        provider = MagicMock()
        provider.cli = "claude"

        def write_matching_current_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                + "\n".join(
                    f"| FR-{index:03d} | IMPLEMENTED | src/a.py | high | ok |"
                    for index in range(1, 61)
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_matching_current_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 2
        assert result.status == "failed"
        assert read_fulfillment_metadata(report) == {}

    def test_refresh_allows_large_audit_scope_drop_after_spec_change(self, tmp_path):
        skill_dir = tmp_path / ".claude" / "skills" / "speckit-echelon-verify-spec"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.md").write_text(
            "---\nname: echelon.verify-spec\n---\nverify $ARGUMENTS\n",
            encoding="utf-8",
        )
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Changed Spec\n", encoding="utf-8")
        report = spec_dir / "fulfillment-report.md"

        previous = tmp_path / "runs" / "verify-spec-spec-001-previous"
        current = tmp_path / "runs" / "verify-spec-spec-001-current"
        previous.mkdir(parents=True)
        current.mkdir(parents=True)
        (previous / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            + "\n".join(
                f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 101)
            )
            + "\n",
            encoding="utf-8",
        )
        (current / "requirement-audit.md").write_text(
            "| ID | Category | Source | Requirement | Acceptance Signal |\n"
            "| --- | --- | --- | --- | --- |\n"
            + "\n".join(
                f"| FR-{index:03d} | FR | spec.md | R | A |" for index in range(1, 61)
            )
            + "\n",
            encoding="utf-8",
        )
        os.utime(previous / "requirement-audit.md", (100, 100))
        os.utime(spec_dir / "spec.md", (150, 150))
        os.utime(current / "requirement-audit.md", (200, 200))

        provider = MagicMock()
        provider.cli = "claude"

        def write_matching_current_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                + "\n".join(
                    f"| FR-{index:03d} | IMPLEMENTED | src/a.py | high | ok |"
                    for index in range(1, 61)
                )
                + "\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_matching_current_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.exit_code == 0
        assert result.status == "refreshed"
        assert read_fulfillment_metadata(report)["verified_commit"] == "abc123"

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

        assert result.exit_code == 0
        assert result.status == "refreshed"
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert f"verify spec-001 spec_dir={spec_dir}" in prompt
        metadata = read_fulfillment_metadata(report)
        assert metadata["spec_id"] == "spec-001"
        assert metadata["verified_commit"] == "abc123"

    def test_refresh_uses_cached_full_report_when_commit_and_spec_hash_match(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "cached"
        assert second.scope == "full"
        assert second.reason == "full verify-spec cache hit"
        assert second.report_path == str(report)
        assert isinstance(second.cache_key, str)
        assert second.exit_code == 0
        assert second.used_cache is True
        provider.exec_prompt.assert_called_once()

    def test_refresh_invalidates_cache_when_tasks_change(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            (spec_dir / "tasks.md").write_text("# Tasks\n- [ ] T001\n", encoding="utf-8")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert second.used_cache is False
        assert provider.exec_prompt.call_count == 2

    def test_refresh_invalidates_cache_when_commit_changes(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch(
            "harness.fulfillment_runner._current_git_commit",
            side_effect=["abc123", "def456", "def456"],
        ):
            first = runner.refresh(str(tmp_path), "spec-001")
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert provider.exec_prompt.call_count == 2

    def test_refresh_does_not_use_cache_without_metadata(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        _write_matching_report(report)
        provider = MagicMock()
        provider.cli = "claude"
        provider.exec_prompt.return_value = 0

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            result = FulfillmentRunner(provider).refresh(str(tmp_path), "spec-001")

        assert result.status == "refreshed"
        provider.exec_prompt.assert_called_once()

    def test_refresh_does_not_use_cache_when_artifact_validation_fails(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        _write_matching_audit(tmp_path)
        report = spec_dir / "fulfillment-report.md"
        provider = MagicMock()
        provider.cli = "claude"

        def write_report(_worktree_path: str, _prompt: str) -> int:
            _write_matching_report(report)
            return 0

        provider.exec_prompt.side_effect = write_report
        runner = FulfillmentRunner(provider)

        with patch("harness.fulfillment_runner._current_git_commit", return_value="abc123"):
            first = runner.refresh(str(tmp_path), "spec-001")
            report.write_text(
                report.read_text(encoding="utf-8")
                + "| FR-999 | IMPLEMENTED | src/b.py | high | invented row |\n",
                encoding="utf-8",
            )
            second = runner.refresh(str(tmp_path), "spec-001")

        assert first.status == "refreshed"
        assert second.status == "refreshed"
        assert provider.exec_prompt.call_count == 2

    def test_scoped_refresh_passes_impacted_ids_and_merges_report(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(
            spec_dir,
            tasks=(
                "- [x] T-001 complexity=standard phase=base req=FR-001 depends=none\n"
                "- [x] T-002 complexity=standard phase=base req=FR-002 depends=T-001\n"
            ),
        )
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: base123\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n"
            "| FR-002 | PARTIAL | src/b.swift | medium | replace |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        def write_scoped_report(_worktree_path: str, _prompt: str) -> int:
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_scoped_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=["T-002"],
            )

        assert result.status == "refreshed"
        assert result.scope == "scoped"
        assert result.reason == "scoped verify-spec completed"
        _worktree_path, prompt = provider.exec_prompt.call_args.args
        assert "verify spec-001" in prompt
        assert "scope=scoped" in prompt
        assert "scoped_ids=FR-001,FR-002" in prompt
        text = report.read_text(encoding="utf-8")
        assert "verify_scope: scoped" in text
        assert "base_full_verify_commit: base123" in text
        assert "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |" in text
        assert "| FR-002 | IMPLEMENTED | src/b.swift | high | fixed |" in text

    def test_scoped_refresh_skips_provider_when_no_impacted_ids(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: head456\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert result.status == "cached"
        assert result.scope == "scoped"
        assert result.reason == "scoped verify-spec skipped; no impacted requirements"
        provider.exec_prompt.assert_not_called()

    def test_scoped_refresh_falls_back_to_full_when_report_is_stale(self, tmp_path):
        _write_verify_skill(tmp_path)
        spec_dir = tmp_path / "specs" / "spec-001-demo"
        _write_spec_inputs(spec_dir)
        report = spec_dir / "fulfillment-report.md"
        report.write_text(
            "---\nverify_scope: full\nverified_commit: old123\n---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| FR-001 | IMPLEMENTED | src/a.swift | high | keep |\n",
            encoding="utf-8",
        )
        provider = MagicMock()
        provider.cli = "claude"

        def write_full_report(_worktree_path: str, prompt: str) -> int:
            assert "scope=scoped" not in prompt
            report.write_text(
                "| ID | Status | Evidence | Confidence | Notes |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| FR-001 | IMPLEMENTED | src/a.swift | high | refreshed |\n",
                encoding="utf-8",
            )
            return 0

        provider.exec_prompt.side_effect = write_full_report

        with patch("harness.fulfillment_runner._current_git_commit", return_value="head456"):
            result = FulfillmentRunner(provider).refresh(
                str(tmp_path),
                "spec-001",
                scope="scoped",
                completed_task_ids=[],
            )

        assert result.status == "refreshed"
        assert result.scope == "full"
        assert result.reason == "full verify-spec completed"
        metadata = read_fulfillment_metadata(report)
        assert metadata["verified_commit"] == "head456"
        assert metadata["verify_scope"] == "full"
