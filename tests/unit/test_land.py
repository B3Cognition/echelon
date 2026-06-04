"""Tests for harness.land — idempotent spec completion."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.land import (
    LandOptions,
    LandPrepareResult,
    _fulfillment_warning,
    _land_status_warning,
    _run_land_verify,
    find_pr_url,
    land,
    resolve_land_repo,
)


def _write_state(state_dir: Path, spec_id: str, strategy: str, pr_url: str | None) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{strategy}.json").write_text(
        json.dumps({"spec_id": spec_id, "pr_url": pr_url}), encoding="utf-8"
    )


def _make_gitops(
    feature_branch: str | None = "042-my-feature",
    merge_result: bool = True,
    delete_result: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.find_feature_branch.return_value = feature_branch
    m.merge_pr.return_value = merge_result
    m.delete_remote_branch.return_value = delete_result
    return m


@pytest.mark.unit
class TestLandOptions:
    def test_default_land_options_are_autonomous_merge(self) -> None:
        options = LandOptions()
        assert options.autoresolve is True
        assert options.prepare_only is False
        assert options.continue_existing is False
        assert options.strategy == "merge"
        assert options.allow_fulfillment_gaps is False

    def test_prepare_result_records_conflict_state(self) -> None:
        result = LandPrepareResult(
            status="blocked",
            branch="001-feature",
            prepared_commit=None,
            pushed=False,
            conflicted_files=["src/app.py"],
            autoresolved_files=[".gitignore"],
            message="semantic conflicts remain",
        )
        assert result.status == "blocked"
        assert result.conflicted_files == ["src/app.py"]


@pytest.mark.unit
class TestFindPrUrl:
    def test_returns_url_from_state_file(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", "https://github.com/o/r/pull/7")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/7"

    def test_returns_none_when_spec_dir_missing(self, tmp_path: Path) -> None:
        assert find_pr_url("042", tmp_path) is None

    def test_returns_none_when_all_files_lack_pr_url(self, tmp_path: Path) -> None:
        _write_state(tmp_path, "042", "default", None)
        assert find_pr_url("042", tmp_path) is None

    def test_returns_first_sorted_file_when_multiple_have_pr_url(self, tmp_path: Path) -> None:
        (tmp_path / "a-state.json").write_text(
            '{"spec_id": "spec-042", "pr_url": "https://github.com/org/repo/pull/1"}'
        )
        (tmp_path / "b-state.json").write_text(
            '{"spec_id": "spec-042", "pr_url": "https://github.com/org/repo/pull/2"}'
        )
        assert find_pr_url("spec-042", tmp_path) == "https://github.com/org/repo/pull/1"

    def test_skips_corrupt_json(self, tmp_path: Path) -> None:
        (tmp_path / "bad.json").write_text("{not json}", encoding="utf-8")
        _write_state(tmp_path, "042", "good", "https://github.com/o/r/pull/9")
        assert find_pr_url("042", tmp_path) == "https://github.com/o/r/pull/9"


@pytest.mark.unit
class TestResolveLandRepo:
    def test_uses_single_spec_target_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "rbf-opta-points"
        target.mkdir()
        spec_dir = tmp_path / "specs" / "001-opta-points-perf-fix"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\n"
            "targets:\n"
            "  - rbf-opta-points\n"
            "status: ready_to_land\n"
            "---\n"
            "# Spec\n",
            encoding="utf-8",
        )

        assert resolve_land_repo(tmp_path, spec_dir) == target.resolve()

    def test_no_targets_uses_project_dir(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("# Spec\n", encoding="utf-8")

        assert resolve_land_repo(tmp_path, spec_dir) == tmp_path.resolve()


@pytest.mark.unit
class TestLand:
    def test_fulfillment_warning_reports_missing_gap(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )

        warning = _fulfillment_warning("001", tmp_path, strict=False)

        assert warning is not None
        assert "MISSING" in warning
        assert "echelon reopen 001" in warning

    def test_fulfillment_warning_strict_treats_unverified_as_blocking(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | UNVERIFIED | src/a.py | medium | no test |\n",
            encoding="utf-8",
        )

        assert _fulfillment_warning("001", tmp_path, strict=False) is None
        assert _fulfillment_warning("001", tmp_path, strict=True) is not None

    def test_land_blocks_fulfillment_gaps_before_merge(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | DEVIATED | src/a.py | high | wrong behavior |\n",
            encoding="utf-8",
        )
        gitops = _make_gitops()

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            finish_landing.return_value = True

            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        prepare.assert_not_called()
        finish_landing.assert_not_called()
        assert banner.call_args.args[0] == "LAND — FULFILLMENT GAPS BLOCKED"
        fields = dict(banner.call_args.args[1])
        assert "DEVIATED" in fields["problem"]
        assert "echelon reopen 042" in fields["next step"]

    def test_land_blocks_when_spec_not_ready_to_land(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: In Progress\n---\n# Spec\n",
            encoding="utf-8",
        )
        gitops = _make_gitops()

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
            patch("harness.land._banner") as banner,
        ):
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        prepare.assert_not_called()
        finish_landing.assert_not_called()
        assert banner.call_args.args[0] == "LAND — SPEC NOT READY"
        fields = dict(banner.call_args.args[1])
        assert "ready_to_land" in fields["problem"]

    def test_land_status_warning_accepts_ready_to_land(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )

        assert _land_status_warning("042", tmp_path) is None

    def test_land_prepare_uses_spec_target_repo(self, tmp_path: Path) -> None:
        target = tmp_path / "rbf-opta-points"
        target.mkdir()
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\n"
            "targets:\n"
            "  - rbf-opta-points\n"
            "status: ready_to_land\n"
            "---\n"
            "# Spec\n",
            encoding="utf-8",
        )
        gitops = _make_gitops()

        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")

            result = land(
                "042",
                project_dir=tmp_path,
                gitops=gitops,
                options=LandOptions(prepare_only=True),
            )

        assert result is True
        assert prepare.call_args.kwargs["project_dir"] == target.resolve()

    def test_land_allows_fulfillment_gaps_with_explicit_override(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | MISSING | none | high | absent |\n",
            encoding="utf-8",
        )
        gitops = _make_gitops()

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            finish_landing.return_value = True

            result = land(
                "042",
                project_dir=tmp_path,
                gitops=gitops,
                options=LandOptions(allow_fulfillment_gaps=True),
            )

        assert result is True
        prepare.assert_called_once()
        assert banner.call_args.args[0] == "LAND — FULFILLMENT GAPS WARNING"

    def test_fulfillment_warning_reports_stale_verified_commit(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        first = _commit(repo, "README.md", "base\n", "base")
        _commit(repo, "later.txt", "later\n", "later")

        spec_dir = repo / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "verified_commit: " + first + "\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        warning = _fulfillment_warning("042", repo, strict=False)

        assert warning is not None
        assert "stale" in warning
        assert first in warning

    def test_fulfillment_warning_reports_missing_report_for_spec(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )

        warning = _fulfillment_warning("042", tmp_path, strict=False)

        assert warning is not None
        assert "no fulfillment report" in warning

    def test_returns_true_when_feature_branch_not_found(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()

    def test_merges_pr_when_feature_branch_and_pr_url_exist(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")

    def test_deletes_remote_branch_after_merge(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()
        land("042", project_dir=tmp_path, gitops=gitops)
        gitops.delete_remote_branch.assert_called_once_with(
            "042-my-feature", project_dir=str(tmp_path)
        )

    def test_returns_false_when_merge_blocked(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops(merge_result=False)
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(
                status="blocked",
                branch="042-my-feature",
                conflicted_files=["src/app.swift"],
            )
            result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is False
        gitops.delete_remote_branch.assert_not_called()

    def test_skips_merge_when_no_pr_url(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        prepare.assert_called_once()
        gitops.delete_remote_branch.assert_called_once()

    def test_calls_ensure_on_default_branch(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            land("042", project_dir=tmp_path, gitops=gitops)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

    def test_writes_landed_status_to_spec_frontmatter(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets: []\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )
        gitops = _make_gitops()
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            land("042", project_dir=tmp_path, gitops=gitops)
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_is_idempotent_when_branch_already_deleted(self, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True

    def test_cleans_up_worktrees(self, tmp_path: Path) -> None:
        worktree_dir = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
        worktree_dir.mkdir(parents=True)
        gitops = _make_gitops()
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            land("042", project_dir=tmp_path, gitops=gitops)
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)

    @patch("harness.land.subprocess.run")
    def test_deletes_harness_branches(self, mock_run: MagicMock, tmp_path: Path) -> None:
        gitops = _make_gitops(feature_branch=None)
        list_result = MagicMock(
            returncode=0,
            stdout="  harness/042/strategy1/iter-1\n  harness/042/strategy1/iter-2\n",
        )
        delete_result = MagicMock(returncode=0, stdout="")
        mock_run.side_effect = [list_result, delete_result, delete_result]

        result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is True
        # Verify git branch --list was called
        list_call = mock_run.call_args_list[0]
        assert list_call[0][0] == ["git", "branch", "--list", "harness/042/*"]
        # Verify git branch -D was called for each branch
        assert mock_run.call_count == 3
        deleted_branches = [c[0][0][3] for c in mock_run.call_args_list[1:]]
        assert "harness/042/strategy1/iter-1" in deleted_branches
        assert "harness/042/strategy1/iter-2" in deleted_branches

    def test_accepts_explicit_state_dir(self, tmp_path: Path) -> None:
        custom_state = tmp_path / "custom-state"
        _write_state(custom_state, "042", "default", "https://github.com/o/r/pull/9")
        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops, state_dir=custom_state)
        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/9")

    def test_prepare_only_prepares_without_landing_cleanup(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("---\ntargets: []\n---\n# Spec\n", encoding="utf-8")

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._delete_harness_branches") as delete_harness,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(
                status="prepared",
                branch="042-my-feature",
                prepared_commit="abc123",
            )

            result = land(
                "042",
                project_dir=tmp_path,
                gitops=gitops,
                options=LandOptions(prepare_only=True),
            )

        assert result is True
        prepare.assert_called_once()
        gitops.merge_branch_into_default.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()
        delete_local.assert_not_called()
        delete_harness.assert_not_called()
        cleanup_worktrees.assert_not_called()
        gitops.ensure_on_default_branch.assert_not_called()
        write_status.assert_not_called()
        banner.assert_called_once()
        assert banner.call_args.args[0] == "LAND — PREPARED"

    def test_prepare_only_does_not_merge_existing_pr(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops()

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
        ):
            prepare.return_value = LandPrepareResult(
                status="prepared",
                branch="042-my-feature",
                prepared_commit="abc123",
            )
            result = land(
                "042",
                project_dir=tmp_path,
                gitops=gitops,
                options=LandOptions(prepare_only=True),
            )

        assert result is True
        prepare.assert_called_once()
        gitops.merge_pr.assert_not_called()
        gitops.merge_branch_into_default.assert_not_called()
        finish_landing.assert_not_called()

    def test_pr_merge_failure_does_not_bypass_pr_with_direct_merge(
        self, tmp_path: Path
    ) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops(merge_result=False)

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(
                status="prepared",
                branch="042-my-feature",
                prepared_commit="abc123",
            )
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")
        prepare.assert_called_once()
        gitops.merge_branch_into_default.assert_not_called()
        finish_landing.assert_not_called()
        banner.assert_called_once()
        assert banner.call_args.args[0] == "LAND — ACTION NEEDED"
        fields = dict(banner.call_args.args[1])
        assert fields["next step"] == "re-run after checks/branch protection clear: echelon land 042"

    def test_returns_false_when_preparation_blocks_on_semantic_conflict(
        self, tmp_path: Path
    ) -> None:
        gitops = _make_gitops()

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._delete_harness_branches") as delete_harness,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(
                status="blocked",
                branch="042-my-feature",
                conflicted_files=["src/app.swift"],
                message="merge conflicts remain",
            )

            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_branch_into_default.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()
        delete_local.assert_not_called()
        delete_harness.assert_not_called()
        cleanup_worktrees.assert_not_called()
        gitops.ensure_on_default_branch.assert_not_called()
        write_status.assert_not_called()
        banner.assert_called_once()
        assert banner.call_args.args[0] == "LAND — FEATURE BRANCH NEEDS CONFLICT RESOLUTION"

    def test_verify_failure_blocks_before_direct_merge(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops._config = MagicMock(
            verify_command=f"{shlex.quote(sys.executable)} -c \"import sys; print('verify failed'); sys.exit(7)\""
        )

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._delete_harness_branches") as delete_harness,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(
                status="prepared",
                branch="042-my-feature",
                prepared_commit="abc123",
            )

            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_branch_into_default.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()
        delete_local.assert_not_called()
        delete_harness.assert_not_called()
        cleanup_worktrees.assert_not_called()
        gitops.ensure_on_default_branch.assert_not_called()
        write_status.assert_not_called()
        banner.assert_called_once()
        assert banner.call_args.args[0] == "LAND — VERIFY FAILED"
        fields = dict(banner.call_args.args[1])
        assert "verify failed" in fields["output"]

    def test_verify_failure_blocks_before_pr_merge(self, tmp_path: Path) -> None:
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")
        gitops = _make_gitops(merge_result=True)
        gitops._config = MagicMock(
            verify_command=f"{shlex.quote(sys.executable)} -c \"import sys; sys.exit(2)\""
        )

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(
                status="prepared",
                branch="042-my-feature",
                prepared_commit="abc123",
            )

            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_pr.assert_not_called()
        prepare.assert_not_called()
        gitops.merge_branch_into_default.assert_not_called()
        gitops.delete_remote_branch.assert_not_called()
        banner.assert_called_once()
        assert banner.call_args.args[0] == "LAND — VERIFY FAILED"


@pytest.mark.unit
class TestLandVerify:
    def test_no_verify_command_is_success(self, tmp_path: Path) -> None:
        passed, output = _run_land_verify(tmp_path, _make_gitops())
        assert passed is True
        assert "no verify_command" in output

    def test_verify_command_success_captures_output(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops._config = MagicMock(
            verify_command=f"{shlex.quote(sys.executable)} -c \"print('verify ok')\""
        )

        passed, output = _run_land_verify(tmp_path, gitops)

        assert passed is True
        assert output == "verify ok"

    def test_verify_command_failure_captures_trimmed_output(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops._config = MagicMock(
            verify_command=(
                f"{shlex.quote(sys.executable)} -c "
                "\"import sys; print('x' * 2500); sys.exit(1)\""
            )
        )

        passed, output = _run_land_verify(tmp_path, gitops)

        assert passed is False
        assert len(output) == 2000
        assert output == "x" * 2000

    def test_malformed_verify_command_fails_closed(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops._config = MagicMock(verify_command="'unterminated")

        passed, output = _run_land_verify(tmp_path, gitops)

        assert passed is False
        assert "invalid verify_command" in output

    def test_verify_command_uses_bounded_tempfile_capture(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops._config = MagicMock(verify_command="verify-tool")

        with patch("harness.land.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess(["verify-tool"], 0)

            passed, output = _run_land_verify(tmp_path, gitops)

        assert passed is True
        assert output == ""
        kwargs = run.call_args.kwargs
        assert "capture_output" not in kwargs
        assert "text" not in kwargs
        assert kwargs["stdout"] is not subprocess.PIPE
        assert kwargs["stderr"] is not subprocess.PIPE


@pytest.mark.unit
class TestDeleteHarnessBranches:
    """Tests for _delete_harness_branches via land() integration."""

    def test_deletes_legacy_harness_branches(self, tmp_path: Path) -> None:
        """Simulate two harness/* branches existing for spec 042."""
        gitops = _make_gitops()
        list_result = MagicMock(returncode=0, stdout="  harness/042/codegen/iter-0\n  harness/042/codegen/iter-1\n")
        delete_result = MagicMock(returncode=0, stdout="")
        with patch("harness.land.subprocess.run") as mock_run:
            # 4 calls: _delete_local_branch, then --list, then 2x -D for harness branches
            mock_run.side_effect = [delete_result, list_result, delete_result, delete_result]
            with patch("harness.land.prepare_feature_branch") as prepare:
                prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
                land("042", project_dir=tmp_path, gitops=gitops)
        # First call: git branch -d <feature-branch> (safe local cleanup)
        local_delete_call = mock_run.call_args_list[0]
        assert local_delete_call[0][0] == ["git", "branch", "-d", "042-my-feature"]
        # Second call: git branch --list harness/042/*
        list_call = mock_run.call_args_list[1]
        assert list_call[0][0] == ["git", "branch", "--list", "harness/042/*"]
        # Remaining calls: git branch -D <harness-branch>
        delete_calls = mock_run.call_args_list[2:]
        deleted_branches = [c[0][0][3] for c in delete_calls]
        assert "harness/042/codegen/iter-0" in deleted_branches
        assert "harness/042/codegen/iter-1" in deleted_branches

    def test_no_error_when_no_harness_branches(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        empty_result = MagicMock(returncode=0, stdout="")
        with patch("harness.land.subprocess.run") as mock_run:
            mock_run.return_value = empty_result
            with patch("harness.land.prepare_feature_branch") as prepare:
                prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
                result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test User")


def _commit(path: Path, rel: str, text: str, message: str) -> str:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(path, "add", rel)
    _git(path, "commit", "-m", message)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


@pytest.mark.unit
def test_land_prepares_feature_branch_before_direct_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    main_commit = _commit(repo, "main.txt", "main\n", "main")

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.delete_remote_branch.return_value = True

    def direct_merge(branch: str, project_dir: str) -> bool:
        target = Path(project_dir)
        assert (
            _git(target, "merge-base", "--is-ancestor", main_commit, branch, check=False).returncode
            == 0
        )
        _git(target, "checkout", "main")
        _git(target, "merge", "--no-ff", branch, "-m", "land feature")
        return True

    gitops.merge_branch_into_default.side_effect = direct_merge

    with patch("harness.land._delete_local_branch"):
        result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is True
    gitops.merge_branch_into_default.assert_called_once_with("001-feature", str(repo))
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert (repo / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    assert (
        _git(repo, "merge-base", "--is-ancestor", main_commit, "001-feature", check=False).returncode
        == 0
    )


@pytest.mark.unit
def test_prepare_feature_branch_merges_default_and_pushes(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main work")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    gitops.push_prepared_branch.return_value = None

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    assert result.branch == "001-feature"
    gitops.push_prepared_branch.assert_called_once_with(
        str(repo), "001-feature", force_with_lease=False
    )
    assert result.pushed is True
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"
    assert (
        _git(repo, "merge-base", "--is-ancestor", "main", "001-feature", check=False).returncode
        == 0
    )


@pytest.mark.unit
def test_prepare_feature_branch_blocks_unsupported_strategy_without_checkout(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _git(repo, "checkout", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(strategy="rebase"),
    )

    assert result.status == "blocked"
    assert result.branch == "001-feature"
    assert "unsupported" in result.message
    assert "rebase" in result.message
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    gitops.get_default_branch.assert_not_called()


@pytest.mark.unit
def test_prepare_feature_branch_blocks_dirty_tracked_worktree_without_checkout(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _git(repo, "checkout", "main")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "blocked"
    assert result.branch == "001-feature"
    assert "tracked changes" in result.message
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    gitops.get_default_branch.assert_not_called()


@pytest.mark.unit
def test_prepare_feature_branch_reports_merge_conflicts(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "README.md", "feature\n", "feature work")
    _git(repo, "checkout", "main")
    _commit(repo, "README.md", "main\n", "main work")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "blocked"
    assert result.branch == "001-feature"
    assert result.conflicted_files == ["README.md"]
    assert "conflicts" in result.message
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"


@pytest.mark.unit
def test_prepare_feature_branch_autoresolves_gitignore_union(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", "*.pyc\n.env\n", "feature gitignore")
    _git(repo, "checkout", "main")
    _commit(repo, ".gitignore", ".env\n.cache\n", "main gitignore")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    gitops.push_prepared_branch.return_value = None

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    assert result.branch == "001-feature"
    gitops.push_prepared_branch.assert_called_once_with(
        str(repo), "001-feature", force_with_lease=False
    )
    assert result.pushed is True
    assert result.autoresolved_files == [".gitignore"]
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert (repo / ".gitignore").read_text(encoding="utf-8").splitlines() == [
        "*.pyc",
        ".env",
        ".cache",
    ]


@pytest.mark.unit
def test_prepare_feature_branch_respects_no_autoresolve_for_gitignore(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", "*.pyc\n.env\n", "feature gitignore")
    _git(repo, "checkout", "main")
    _commit(repo, ".gitignore", ".env\n.cache\n", "main gitignore")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(autoresolve=False),
    )

    assert result.status == "blocked"
    assert result.conflicted_files == [".gitignore"]
    assert result.autoresolved_files == []
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ".gitignore"


@pytest.mark.unit
def test_prepare_feature_branch_does_not_autoresolve_modified_gitignore(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, ".gitignore", ".env\n", "base gitignore")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", ".env\n.build/\n", "feature gitignore")
    _git(repo, "checkout", "main")
    _commit(repo, ".gitignore", ".env\n.cache/\n", "main gitignore")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "blocked"
    assert result.conflicted_files == [".gitignore"]
    assert result.autoresolved_files == []
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ".gitignore"


@pytest.mark.unit
def test_prepare_feature_branch_blocks_on_source_conflict(tmp_path: Path) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/app.swift", "let value = 1\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "src/app.swift", "let value = 2\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "src/app.swift", "let value = 3\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "blocked"
    assert result.conflicted_files == ["src/app.swift"]
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == "src/app.swift"


@pytest.mark.unit
def test_prepare_feature_branch_continue_commits_resolved_merge_and_pushes(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/app.swift", "let value = 1\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "src/app.swift", "let value = 2\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "src/app.swift", "let value = 3\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    (repo / "src/app.swift").write_text("let value = 4\n", encoding="utf-8")
    _git(repo, "add", "src/app.swift")
    gitops.reset_mock()

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(continue_existing=True),
    )

    assert result.status == "prepared"
    assert result.branch == "001-feature"
    assert result.pushed is True
    assert result.prepared_commit == _git(repo, "rev-parse", "HEAD").stdout.strip()
    gitops.push_prepared_branch.assert_called_once_with(
        str(repo), "001-feature", force_with_lease=False
    )
    gitops.get_default_branch.assert_not_called()
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode != 0


@pytest.mark.unit
def test_prepare_feature_branch_continue_blocks_when_conflicts_remain(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "src/app.swift", "let value = 1\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "src/app.swift", "let value = 2\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "src/app.swift", "let value = 3\n", "main")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )
    gitops.reset_mock()

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(continue_existing=True),
    )

    assert result.status == "blocked"
    assert result.branch == "001-feature"
    assert result.conflicted_files == ["src/app.swift"]
    assert "conflicts" in result.message
    gitops.push_prepared_branch.assert_not_called()
    gitops.get_default_branch.assert_not_called()
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == "src/app.swift"


@pytest.mark.unit
def test_prepare_feature_branch_continue_blocks_without_merge_in_progress(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")

    gitops = MagicMock()

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(continue_existing=True),
    )

    assert result.status == "blocked"
    assert result.branch == "001-feature"
    assert "no merge in progress" in result.message
    gitops.push_prepared_branch.assert_not_called()
    assert _git(repo, "rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode != 0


@pytest.mark.unit
class TestLandIntegration:
    """Integration tests using real tmp dirs and real git repos."""

    def test_writes_status_and_cleans_worktrees_in_real_filesystem(self, tmp_path: Path) -> None:
        """Full filesystem integration: state file, spec.md, worktree dir all created."""
        import subprocess as sp

        # Set up a minimal git repo so _delete_harness_branches can run
        sp.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], check=True, capture_output=True)
        (tmp_path / "README.md").write_text("hi")
        sp.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
        sp.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
        verified_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()

        # State file with PR URL
        state_dir = tmp_path / "runs" / "build-test" / "state"
        _write_state(state_dir, "042", "default", "https://github.com/o/r/pull/7")

        # Spec dir
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\ntargets: []\nstatus: ready_to_land\n---\n# Body\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            f"verified_commit: {verified_commit}\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        # Worktree dir
        worktree_dir = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
        worktree_dir.mkdir(parents=True)

        gitops = _make_gitops()
        result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is True
        gitops.merge_pr.assert_called_once_with("https://github.com/o/r/pull/7")
        gitops.delete_remote_branch.assert_called_once()
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"
