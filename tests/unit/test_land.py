"""Tests for harness.land — idempotent spec completion."""
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from harness.land import (
    LandOptions,
    LandPrepareResult,
    _check_ready_before_land,
    _delete_harness_branches,
    _fulfillment_warning,
    _finish_landing,
    _land_status_warning,
    _run_land_verify,
    find_pr_url,
    land,
    resolve_land_repo,
)
from harness.deferred_scope import apply_defer
from harness.errors import GitOpsError


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
    m.get_default_branch.return_value = "main"
    m.merge_pr.return_value = merge_result
    m.delete_remote_branch.return_value = delete_result
    m.push_landed_default_branch.return_value = True
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
    def test_blocks_when_feature_branch_resolution_fails(
        self, tmp_path: Path
    ) -> None:
        gitops = _make_gitops()
        gitops.find_feature_branch.side_effect = GitOpsError(
            "mirror fetch failed",
            command="git fetch --all --prune",
        )

        with (
            patch("harness.land._banner") as banner,
            patch("harness.land._cleanup_worktrees") as cleanup,
            patch("harness.land._delete_harness_branches") as delete_branches,
        ):
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        cleanup.assert_not_called()
        delete_branches.assert_not_called()
        assert banner.call_args.args[0] == "LAND — BRANCH RESOLUTION BLOCKED"

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
        assert "echelon spec reopen 001" in warning

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

    def test_fulfillment_warning_rejects_unbacked_deferred_scope_row(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| NFR-008 | DEFERRED_SCOPE | defer:defer-001: reason |\n",
            encoding="utf-8",
        )

        warning = _fulfillment_warning("001", tmp_path)

        assert warning is not None
        assert "no active defer entry" in warning

    def test_fulfillment_warning_accepts_ledger_backed_deferred_scope_row(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text("NFR-008\n", encoding="utf-8")
        (spec_dir / "tasks.md").write_text(
            "- [ ] T-001 complexity=standard phase=build req=NFR-008 depends=none\n",
            encoding="utf-8",
        )
        apply_defer(spec_dir, ["NFR-008"], reason="owner decision")
        (spec_dir / "fulfillment-report.md").write_text(
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| NFR-008 | DEFERRED_SCOPE | defer:defer-001: owner decision |\n",
            encoding="utf-8",
        )

        assert _fulfillment_warning("001", tmp_path) is None

    def test_fulfillment_warning_rejects_scoped_report_for_landing(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "001-demo"
        spec_dir.mkdir(parents=True)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            "spec_id: '001'\n"
            "verified_commit: head456\n"
            "verify_scope: scoped\n"
            "base_full_verify_commit: base123\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n",
            encoding="utf-8",
        )

        with patch("harness.land._current_git_commit", return_value="head456"):
            warning = _fulfillment_warning("001", tmp_path)

        assert warning is not None
        assert "scoped fulfillment report" in warning
        assert "echelon spec verify 001" in warning

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
        assert "echelon spec reopen 042" in fields["next step"]

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

    def test_land_uses_feature_branch_readiness_when_current_checkout_is_stale(
        self, tmp_path: Path
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        _commit(repo, "README.md", "base\n", "base")
        _commit(
            repo,
            "specs/042-demo/spec.md",
            "# Demo\n\n**Status**: Planned\n",
            "stale spec on main",
        )
        _git(repo, "checkout", "-b", "042-demo")
        verified = _commit(
            repo,
            "src/app.py",
            "print('ok')\n",
            "implementation checkpoint",
        )
        (repo / "specs/042-demo/spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Demo\n\n**Status**: ready_to_land\n",
            encoding="utf-8",
        )
        (repo / "specs/042-demo/fulfillment-report.md").write_text(
            "---\n"
            f"verified_commit: {verified}\n"
            "verify_scope: full\n"
            "---\n"
            "| ID | Status | Evidence | Confidence | Notes |\n"
            "|---|---|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/app.py | high | ok |\n",
            encoding="utf-8",
        )
        _git(repo, "add", "specs/042-demo/spec.md", "specs/042-demo/fulfillment-report.md")
        _git(repo, "commit", "-m", "mark ready to land")
        _git(repo, "checkout", "main")

        gitops = _make_gitops(feature_branch="042-demo")
        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._verify_before_land", return_value=True),
            patch("harness.land._finish_landing", return_value=True) as finish_landing,
            patch("harness.land._banner") as banner,
        ):
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-demo")

            result = land("042", project_dir=repo, gitops=gitops)

        assert result is True
        prepare.assert_called_once()
        finish_landing.assert_called_once()
        assert not banner.called

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

    def test_blocks_when_branch_and_spec_evidence_are_missing(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        gitops = _make_gitops(feature_branch=None)
        result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is False
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
        with patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"):
            land("042", project_dir=tmp_path, gitops=gitops)
        gitops.delete_remote_branch.assert_called_once_with(
            "042-my-feature", project_dir=str(tmp_path)
        )

    def test_finish_landing_skips_remote_delete_without_origin(self, tmp_path: Path) -> None:
        gitops = _make_gitops()

        with (
            patch("harness.land._origin_remote_url", return_value=None),
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
        ):
            result = _finish_landing(
                "042",
                "042-my-feature",
                tmp_path,
                gitops,
                spec_project_dir=tmp_path,
            )

        assert result is True
        gitops.delete_remote_branch.assert_not_called()
        delete_local.assert_called_once_with("042-my-feature", str(tmp_path))
        cleanup_worktrees.assert_called_once()
        write_status.assert_not_called()

    def test_finish_landing_blocks_when_remote_head_is_feature_branch(
        self, tmp_path: Path
    ) -> None:
        gitops = _make_gitops()

        with (
            patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"),
            patch("harness.land._remote_head_branch", return_value="042-my-feature"),
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
            patch("harness.land._banner") as banner,
        ):
            result = _finish_landing(
                "042",
                "042-my-feature",
                tmp_path,
                gitops,
                spec_project_dir=tmp_path,
            )

        assert result is False
        gitops.delete_remote_branch.assert_not_called()
        delete_local.assert_not_called()
        cleanup_worktrees.assert_not_called()
        write_status.assert_not_called()
        assert banner.call_args.args[0] == "LAND — REMOTE DEFAULT BRANCH BLOCKED"
        fields = dict(banner.call_args.args[1])
        assert "042-my-feature" in fields["problem"]
        assert "change default branch to main" in fields["next step"]

    def test_finish_landing_blocks_on_real_remote_delete_failure(
        self, tmp_path: Path
    ) -> None:
        gitops = _make_gitops(delete_result=False)

        with (
            patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"),
            patch("harness.land._remote_head_branch", return_value="main"),
            patch("harness.land._delete_local_branch") as delete_local,
            patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
            patch("harness.land.write_status") as write_status,
            patch("harness.land._banner") as banner,
        ):
            result = _finish_landing(
                "042",
                "042-my-feature",
                tmp_path,
                gitops,
                spec_project_dir=tmp_path,
            )

        assert result is False
        gitops.delete_remote_branch.assert_called_once_with(
            "042-my-feature", project_dir=str(tmp_path)
        )
        delete_local.assert_not_called()
        cleanup_worktrees.assert_not_called()
        write_status.assert_not_called()
        assert banner.call_args.args[0] == "LAND — REMOTE BRANCH CLEANUP BLOCKED"

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
        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"),
        ):
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            result = land("042", project_dir=tmp_path, gitops=gitops)
        assert result is True
        gitops.merge_pr.assert_not_called()
        prepare.assert_called_once()
        gitops.push_landed_default_branch.assert_called_once_with(str(tmp_path), "main")
        gitops.delete_remote_branch.assert_called_once()

    def test_direct_land_blocks_if_default_push_fails(self, tmp_path: Path) -> None:
        gitops = _make_gitops()
        gitops.push_landed_default_branch.return_value = False

        with (
            patch("harness.land.prepare_feature_branch") as prepare,
            patch("harness.land._finish_landing") as finish_landing,
            patch("harness.land._banner") as banner,
            patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"),
        ):
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_branch_into_default.assert_called_once_with("042-my-feature", str(tmp_path))
        gitops.push_landed_default_branch.assert_called_once_with(str(tmp_path), "main")
        finish_landing.assert_not_called()
        assert banner.call_args.args[0] == "LAND — DEFAULT PUSH FAILED"

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
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        gitops = _make_gitops(feature_branch=None)

        with (
            patch("harness.land._cleanup_worktrees") as cleanup,
            patch("harness.land._delete_harness_branches") as delete_harness,
        ):
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        cleanup.assert_not_called()
        delete_harness.assert_not_called()

    def test_no_branch_blocks_unmerged_verified_commit(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        _git(tmp_path, "checkout", "-b", "verified-work")
        verified = _commit(tmp_path, "feature.txt", "work\n", "verified work")
        _git(tmp_path, "checkout", "main")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            f"---\nverified_commit: {verified}\n---\n"
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py |\n",
            encoding="utf-8",
        )

        with (
            patch("harness.land._cleanup_worktrees") as cleanup,
            patch("harness.land._delete_harness_branches") as delete_harness,
        ):
            result = land("042-my-feature", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is False
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"
        cleanup.assert_not_called()
        delete_harness.assert_not_called()

    def test_no_branch_finishes_when_verified_commit_is_on_main(
        self, tmp_path: Path
    ) -> None:
        from harness.fulfillment_runner import (
            _implementation_input_hash,
            _spec_input_hash,
        )

        _init_repo(tmp_path)
        verified = _commit(tmp_path, "README.md", "landed\n", "landed work")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        spec_hash = _spec_input_hash(spec_dir)
        implementation_hash = _implementation_input_hash(tmp_path)
        (spec_dir / "fulfillment-report.md").write_text(
            "---\n"
            f"verified_commit: {verified}\n"
            f"spec_input_hash: {spec_hash}\n"
            f"implementation_input_hash: {implementation_hash}\n"
            "---\n"
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py |\n",
            encoding="utf-8",
        )

        with (
            patch("harness.land._cleanup_worktrees") as cleanup,
            patch("harness.land._delete_harness_branches") as delete_harness,
        ):
            result = land("042-my-feature", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is True
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"
        cleanup.assert_called_once()
        assert [call.args[0] for call in delete_harness.call_args_list] == [
            "042-my-feature",
            "042",
        ]

    def test_no_branch_blocks_ready_spec_without_input_hashes(
        self, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        verified = _commit(tmp_path, "README.md", "landed\n", "landed work")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            f"---\nverified_commit: {verified}\n---\n"
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py |\n",
            encoding="utf-8",
        )

        result = land("042", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is False
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"

    def test_no_branch_blocks_fulfillment_gaps_on_main(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        verified = _commit(tmp_path, "README.md", "landed\n", "landed work")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            f"---\nverified_commit: {verified}\n---\n"
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| FR-001 | PARTIAL | src/a.py |\n",
            encoding="utf-8",
        )

        result = land("042", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is False
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"

    def test_no_branch_blocks_changed_spec_input_hash(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        verified = _commit(tmp_path, "README.md", "landed\n", "landed work")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Amended spec\n",
            encoding="utf-8",
        )
        (spec_dir / "fulfillment-report.md").write_text(
            f"---\nverified_commit: {verified}\nspec_input_hash: stale\n---\n"
            "| ID | Status | Evidence |\n|---|---|---|\n"
            "| FR-001 | IMPLEMENTED | src/a.py |\n",
            encoding="utf-8",
        )

        result = land("042", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is False
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "ready_to_land"

    def test_numeric_selector_uses_canonical_identity_for_branch_lookup(
        self, tmp_path: Path
    ) -> None:
        spec_dir = tmp_path / "specs" / "906-cli-output-styling"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: ready_to_land\n---\n# Spec\n",
            encoding="utf-8",
        )
        gitops = _make_gitops("906-cli-output-styling")

        with patch("harness.land._check_ready_before_land", return_value=False):
            result = land("906", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.find_feature_branch.assert_called_once_with(
            "906-cli-output-styling"
        )

    def test_no_branch_keeps_legacy_landed_spec_idempotent(
        self, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "landed\n", "landed work")
        spec_dir = tmp_path / "specs" / "042-my-feature"
        spec_dir.mkdir(parents=True)
        (spec_dir / "spec.md").write_text(
            "---\nstatus: landed\n---\n# Spec\n",
            encoding="utf-8",
        )

        result = land("042-my-feature", project_dir=tmp_path, gitops=_make_gitops(None))

        assert result is True
        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"

    def test_lands_latest_legacy_harness_branch_when_feature_branch_is_missing(
        self, tmp_path: Path
    ) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        _git(tmp_path, "branch", "harness/042/default/iter-0")
        _git(tmp_path, "checkout", "harness/042/default/iter-0")
        _commit(tmp_path, "feature.txt", "verified work\n", "legacy implementation")
        _git(tmp_path, "branch", "harness/042/default/iter-3")
        _git(tmp_path, "checkout", "main")
        gitops = _make_gitops(feature_branch=None)

        with (
            patch("harness.land._check_ready_before_land", return_value=True),
            patch("harness.land._verify_before_land", return_value=True),
            patch("harness.land._clean_generated_drift_before_direct_merge", return_value=True),
            patch("harness.land._finish_landing", return_value=True),
        ):
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is True
        gitops.merge_branch_into_default.assert_called_once_with(
            "harness/042/default/iter-3", str(tmp_path)
        )

    def test_slug_lands_numeric_legacy_harness_branch(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        _git(tmp_path, "checkout", "-b", "harness/906/default/iter-3")
        _commit(tmp_path, "feature.txt", "verified work\n", "legacy implementation")
        _git(tmp_path, "checkout", "main")
        gitops = _make_gitops(feature_branch=None)

        with (
            patch("harness.land._check_ready_before_land", return_value=True),
            patch("harness.land._verify_before_land", return_value=True),
            patch("harness.land._clean_generated_drift_before_direct_merge", return_value=True),
            patch("harness.land._finish_landing", return_value=True),
        ):
            result = land(
                "906-cli-output-styling",
                project_dir=tmp_path,
                gitops=gitops,
            )

        assert result is True
        gitops.merge_branch_into_default.assert_called_once_with(
            "harness/906/default/iter-3", str(tmp_path)
        )

    def test_blocks_ambiguous_legacy_harness_branch_selection(self, tmp_path: Path) -> None:
        _init_repo(tmp_path)
        _commit(tmp_path, "README.md", "base\n", "base")
        _git(tmp_path, "branch", "harness/042/default/iter-3")
        _git(tmp_path, "branch", "harness/042/conservative/iter-3")
        gitops = _make_gitops(feature_branch=None)

        with patch("harness.land._banner") as banner:
            result = land("042", project_dir=tmp_path, gitops=gitops)

        assert result is False
        gitops.merge_branch_into_default.assert_not_called()
        assert banner.call_args.args[0] == "LAND — BRANCH RESOLUTION BLOCKED"

    def test_cleans_up_worktrees(self, tmp_path: Path) -> None:
        worktree_dir = tmp_path / "runs" / "build-test" / "worktrees" / "default" / "iter-0"
        worktree_dir.mkdir(parents=True)
        _write_state(tmp_path / "runs" / "build-test" / "state", "042", "default", None)
        unrelated = (
            tmp_path
            / "runs"
            / "build-other"
            / "worktrees"
            / "default"
            / "iter-0"
        )
        unrelated.mkdir(parents=True)
        _write_state(
            tmp_path / "runs" / "build-other" / "state",
            "043-other",
            "default",
            None,
        )
        gitops = _make_gitops()
        with patch("harness.land.prepare_feature_branch") as prepare:
            prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
            land("042", project_dir=tmp_path, gitops=gitops)
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)

    @patch("harness.land.subprocess.run")
    def test_deletes_harness_branches(self, mock_run: MagicMock, tmp_path: Path) -> None:
        list_result = MagicMock(
            returncode=0,
            stdout="  harness/042/strategy1/iter-1\n  harness/042/strategy1/iter-2\n",
        )
        delete_result = MagicMock(returncode=0, stdout="")
        mock_run.side_effect = [list_result, delete_result, delete_result]

        _delete_harness_branches("042", tmp_path)

        # Verify git branch --list was called
        list_call = mock_run.call_args_list[0]
        assert list_call[0][0] == ["git", "branch", "--list", "harness/042/*"]
        # Verify safe git branch -d was called for each branch.
        assert mock_run.call_count == 3
        deleted_branches = [c[0][0][3] for c in mock_run.call_args_list[1:]]
        assert all(c[0][0][2] == "-d" for c in mock_run.call_args_list[1:])
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
        assert fields["next step"] == "re-run after checks/branch protection clear: echelon delivery land 042"

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
        clean_result = MagicMock(returncode=0, stdout="")
        no_origin_result = MagicMock(returncode=1, stdout="")
        list_result = MagicMock(returncode=0, stdout="  harness/042/codegen/iter-0\n  harness/042/codegen/iter-1\n")
        delete_result = MagicMock(returncode=0, stdout="")
        with patch("harness.land.subprocess.run") as mock_run:
            # 7 calls: dirty probe, two origin probes, local branch delete, --list, then 2x -D.
            mock_run.side_effect = [
                clean_result,
                no_origin_result,
                no_origin_result,
                delete_result,
                list_result,
                delete_result,
                delete_result,
            ]
            with (
                patch("harness.land._default_branch_already_contains_feature", return_value=False),
                patch("harness.land.prepare_feature_branch") as prepare,
                patch("harness.land._post_land_topology_reconciliation"),
            ):
                prepare.return_value = LandPrepareResult(status="prepared", branch="042-my-feature")
                land("042", project_dir=tmp_path, gitops=gitops)
        dirty_call = mock_run.call_args_list[0]
        assert dirty_call[0][0] == ["git", "diff", "--name-only", "HEAD", "--"]
        origin_call = mock_run.call_args_list[1]
        assert origin_call[0][0] == ["git", "remote", "get-url", "origin"]
        cleanup_origin_call = mock_run.call_args_list[2]
        assert cleanup_origin_call[0][0] == ["git", "remote", "get-url", "origin"]
        # Fourth call: git branch -d <feature-branch> (safe local cleanup)
        local_delete_call = mock_run.call_args_list[3]
        assert local_delete_call[0][0] == ["git", "branch", "-d", "042-my-feature"]
        # Fifth call: git branch --list harness/042/*
        list_call = mock_run.call_args_list[4]
        assert list_call[0][0] == ["git", "branch", "--list", "harness/042/*"]
        # Remaining calls: git branch -D <harness-branch>
        delete_calls = mock_run.call_args_list[5:]
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
def test_workspace_target_land_uses_workspace_spec_readiness_not_target_branch_ref(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    _init_repo(workspace)
    target = workspace / "sources" / "prosaic"
    _init_repo(target)

    spec = workspace / "specs" / "001-demo" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        "---\n"
        "status: In Progress\n"
        "targets:\n"
        "- sources/prosaic\n"
        "---\n"
        "# Spec\n\n"
        "**Status**: In Progress\n",
        encoding="utf-8",
    )
    _git(workspace, "add", "specs/001-demo/spec.md")
    _git(workspace, "commit", "-m", "spec in progress")
    _git(workspace, "branch", "001-demo")
    spec.write_text(
        "---\n"
        "status: ready_to_land\n"
        "targets:\n"
        "- sources/prosaic\n"
        "---\n"
        "# Spec\n\n"
        "**Status**: ready_to_land\n",
        encoding="utf-8",
    )

    gitops = _make_gitops(feature_branch="001-demo")

    with (
        patch("harness.land._fulfillment_warning", return_value=None),
        patch("harness.land._default_branch_already_contains_feature", return_value=True),
        patch("harness.land._checkout_default_for_landing_cleanup", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
        patch("harness.land._banner") as banner,
    ):
        result = land("001", project_dir=workspace, gitops=gitops)

    assert result is True
    assert all(call.args[0] != "LAND — SPEC NOT READY" for call in banner.call_args_list)


@pytest.mark.unit
def test_polyrepo_land_uses_target_harness_pr_state_and_cleans_its_worktree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    harness_root = workspace / "runs" / "targets" / "api"
    target_root = workspace / "sources" / "api"
    target_root.mkdir(parents=True)

    spec_dir = workspace / "specs" / "042-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\n"
        "status: ready_to_land\n"
        "targets:\n"
        "- sources/api\n"
        "---\n"
        "# Demo\n",
        encoding="utf-8",
    )

    state_dir = harness_root / "runs" / "build-target" / "state"
    pr_url = "https://github.com/example/api/pull/42"
    _write_state(state_dir, "042-demo", "default", pr_url)
    worktree = harness_root / "runs" / "build-target" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)

    gitops = _make_gitops(feature_branch="042-demo")
    gitops.destroy_worktree.side_effect = (
        lambda path, *, keep_branch: path.rmdir()
    )

    result = land(
        "042",
        project_dir=workspace,
        harness_root=harness_root,
        gitops=gitops,
        options=LandOptions(allow_fulfillment_gaps=True),
    )

    assert result is True
    gitops.merge_pr.assert_called_once_with(pr_url)
    gitops.merge_branch_into_default.assert_not_called()
    gitops.destroy_worktree.assert_called_once_with(worktree, keep_branch=True)
    assert not worktree.exists()


@pytest.mark.unit
def test_polyrepo_branchless_cleanup_uses_target_harness_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    harness_root = workspace / "runs" / "targets" / "api"
    target_root = workspace / "sources" / "api"
    _init_repo(target_root)
    verified_commit = _commit(target_root, "README.md", "# API\n", "initial")

    spec_dir = workspace / "specs" / "043-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\n"
        "status: landed\n"
        "targets:\n"
        "- sources/api\n"
        "---\n"
        "# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        f"verified_commit: {verified_commit}\n"
        "verify_scope: full\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | README.md | high | ok |\n",
        encoding="utf-8",
    )

    state_dir = harness_root / "runs" / "build-target" / "state"
    _write_state(state_dir, "043-demo", "default", None)
    worktree = harness_root / "runs" / "build-target" / "worktrees" / "default" / "iter-0"
    worktree.mkdir(parents=True)

    gitops = _make_gitops(feature_branch=None)
    gitops.destroy_worktree.side_effect = (
        lambda path, *, keep_branch: path.rmdir()
    )

    result = land(
        "043",
        project_dir=workspace,
        harness_root=harness_root,
        gitops=gitops,
    )

    assert result is True
    gitops.merge_pr.assert_not_called()
    gitops.merge_branch_into_default.assert_not_called()
    gitops.destroy_worktree.assert_called_once_with(worktree, keep_branch=True)
    assert not worktree.exists()


@pytest.mark.unit
def test_workspace_target_fulfillment_freshness_uses_target_repo_ref(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    _init_repo(workspace)
    target = workspace / "sources" / "prosaic"
    _init_repo(target)

    old_target_commit = _commit(target, "src/app.ts", "export const ok = true;\n", "impl")
    _git(target, "checkout", "-b", "001-demo")
    _commit(target, "README.md", "# Prosaic\n", "docs")

    spec_dir = workspace / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\n"
        "status: ready_to_land\n"
        "targets:\n"
        "- sources/prosaic\n"
        "---\n"
        "# Spec\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        f"verified_commit: {old_target_commit}\n"
        "verify_scope: full\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | src/app.ts | high | ok |\n",
        encoding="utf-8",
    )

    warning = _fulfillment_warning(
        "001",
        workspace,
        commit_project_dir=target,
        commit_ref="001-demo",
    )

    assert warning is None
    with patch("harness.land._banner") as banner:
        assert _check_ready_before_land(
            "001",
            workspace,
            LandOptions(),
            fulfillment_project_dir=target,
            fulfillment_ref="001-demo",
        )
    assert all(
        call.args[0] != "LAND — FULFILLMENT GAPS BLOCKED"
        for call in banner.call_args_list
    )


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
def test_finish_landing_runs_one_topology_hook_after_checkout_and_status(
    tmp_path: Path,
) -> None:
    from harness.land import _finish_landing
    from harness.spec_frontmatter import read_frontmatter

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Spec\n",
        encoding="utf-8",
    )
    gitops = _make_gitops()

    def assert_post_land(spec_id: str, workspace_root: Path, target_root: Path) -> None:
        assert spec_id == "001-demo"
        assert workspace_root == tmp_path
        assert target_root == tmp_path
        assert read_frontmatter(spec_dir)["status"] == "landed"
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

    with (
        patch("harness.land._origin_remote_url", return_value=None),
        patch("harness.land._delete_local_branch"),
        patch("harness.land._cleanup_worktrees"),
        patch("harness.land._delete_harness_branches"),
        patch(
            "harness.land._post_land_topology_reconciliation",
            side_effect=assert_post_land,
        ) as post_land,
    ):
        assert _finish_landing(
            "001-demo",
            "001-feature",
            tmp_path,
            gitops,
            spec_project_dir=tmp_path,
        )

    post_land.assert_called_once_with("001-demo", tmp_path, tmp_path)


@pytest.mark.unit
def test_branchless_idempotent_land_runs_same_post_land_topology_hook(
    tmp_path: Path,
) -> None:
    from harness.land import _finish_branchless_landing

    spec_dir = tmp_path / "specs/001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: landed\n---\n# Spec\n",
        encoding="utf-8",
    )
    gitops = _make_gitops(feature_branch=None)
    order: list[str] = []
    gitops.ensure_on_default_branch.side_effect = lambda path: order.append("checkout")

    with patch(
        "harness.land._post_land_topology_reconciliation",
        side_effect=lambda *args: order.append("topology"),
    ) as post_land:
        assert _finish_branchless_landing(
            "001-demo",
            wrapper_project_dir=tmp_path,
            project_dir=tmp_path,
            spec_dir=spec_dir,
            gitops=gitops,
            options=LandOptions(),
        )

    assert order == ["checkout", "topology"]
    post_land.assert_called_once_with("001-demo", tmp_path, tmp_path)


@pytest.mark.unit
def test_branchless_spec_not_found_reports_orchestration_root(tmp_path: Path) -> None:
    from harness.land import _finish_branchless_landing

    wrapper_project_dir = tmp_path / "workspace"
    wrapper_project_dir.mkdir()
    gitops = _make_gitops(feature_branch=None)

    with (
        patch("harness.land._banner") as banner,
        patch("harness.land.write_status") as write_status,
    ):
        result = _finish_branchless_landing(
            "042",
            wrapper_project_dir=wrapper_project_dir,
            project_dir=wrapper_project_dir,
            spec_dir=None,
            gitops=gitops,
            options=LandOptions(),
        )

    assert result is False
    write_status.assert_not_called()
    fields = dict(banner.call_args.args[1])
    assert fields["problem"] == (
        "spec directory for 042 was not found from orchestration root "
        f"{wrapper_project_dir.resolve()}"
    )
    assert "spec status is (missing), not ready_to_land or landed" not in str(
        banner.call_args
    )


@pytest.mark.unit
def test_branchless_missing_status_retains_status_diagnostic(tmp_path: Path) -> None:
    from harness.land import _finish_branchless_landing

    wrapper_project_dir = tmp_path / "workspace"
    spec_dir = wrapper_project_dir / "specs" / "042-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\ntitle: Demo\n---\n# Demo\n",
        encoding="utf-8",
    )
    gitops = _make_gitops(feature_branch=None)

    with (
        patch("harness.land._banner") as banner,
        patch("harness.land.write_status") as write_status,
    ):
        result = _finish_branchless_landing(
            "042",
            wrapper_project_dir=wrapper_project_dir,
            project_dir=wrapper_project_dir,
            spec_dir=spec_dir,
            gitops=gitops,
            options=LandOptions(),
        )

    assert result is False
    write_status.assert_not_called()
    fields = dict(banner.call_args.args[1])
    assert fields["problem"] == (
        "spec status is (missing), not ready_to_land or landed"
    )


@pytest.mark.unit
def test_post_land_topology_failure_is_nonfatal_with_source_refresh_guidance(
    tmp_path: Path,
    caplog,
) -> None:
    from harness.land import _post_land_topology_reconciliation
    from harness.topology_promotion import TopologyPromotionResult

    source = tmp_path / "sources/api"
    source.mkdir(parents=True)
    _init_repo(source)
    head = _commit(source, "src/app.py", "pass\n", "landed")
    with (
        patch(
            "harness.topology_promotion.reconcile_landed_topology",
            return_value=TopologyPromotionResult(
                status="stale",
                source_id="api",
                message="expected generation 1, found 2",
            ),
        ),
        patch(
            "echelon.topology_audit.audit_topology",
            return_value=SimpleNamespace(status="stale"),
        ),
    ):
        _post_land_topology_reconciliation("001-demo", tmp_path, source)

    assert "topology: stale" in caplog.text
    assert "next: echelon re refresh --source api" in caplog.text


@pytest.mark.unit
def test_post_land_reports_topology_and_semantic_re_independently(
    tmp_path: Path,
    caplog,
) -> None:
    from harness.land import _post_land_topology_reconciliation
    from harness.topology_promotion import TopologyPromotionResult

    source = tmp_path / "sources/api"
    caplog.set_level("INFO")
    source.mkdir(parents=True)
    _init_repo(source)
    _commit(source, "src/app.py", "pass\n", "landed")
    with (
        patch(
            "harness.topology_promotion.reconcile_landed_topology",
            return_value=TopologyPromotionResult(
                status="current",
                source_id="api",
                message="published",
            ),
        ),
        patch(
            "echelon.topology_audit.audit_topology",
            return_value=SimpleNamespace(status="stale"),
        ),
        patch(
            "harness.land._landed_semantic_re_status",
            return_value="current",
            create=True,
        ),
    ):
        _post_land_topology_reconciliation("001-demo", tmp_path, source)

    assert "topology: stale" in caplog.text
    assert "semantic RE: current" in caplog.text
    assert caplog.text.count("next: echelon re refresh --source api") == 1


@pytest.mark.unit
@pytest.mark.parametrize("audit_status", ("degraded", "invalid", "unavailable"))
def test_post_land_maps_unusable_topology_audit_status_to_unavailable(
    tmp_path: Path,
    caplog,
    audit_status: str,
) -> None:
    from harness.land import _post_land_topology_reconciliation
    from harness.topology_promotion import TopologyPromotionResult

    source = tmp_path / "sources/api"
    source.mkdir(parents=True)
    _init_repo(source)
    _commit(source, "src/app.py", "pass\n", "landed")
    with (
        patch(
            "harness.topology_promotion.reconcile_landed_topology",
            return_value=TopologyPromotionResult(
                status="current",
                source_id="api",
                message="published",
            ),
        ),
        patch(
            "echelon.topology_audit.audit_topology",
            return_value=SimpleNamespace(status=audit_status),
        ),
        patch(
            "harness.land._landed_semantic_re_status",
            return_value="current",
        ),
    ):
        _post_land_topology_reconciliation("001-demo", tmp_path, source)

    assert "topology: unavailable" in caplog.text
    if audit_status != "unavailable":
        assert f"topology: {audit_status}" not in caplog.text
    assert "next: echelon re refresh --source api" in caplog.text


@pytest.mark.unit
def test_land_refuses_different_active_authoring_branch_without_git_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "-b", "002-authoring", "main")

    current = repo / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-b", encoding="utf-8")
    run_dir = repo / "runs" / "run-b"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        '{"run_id":"run-b","spec_id":"002-authoring",'
        '"feature_branch":"002-authoring",'
        '"spec_dir":"runs/run-b/specs/002-authoring"}',
        encoding="utf-8",
    )
    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"

    with (
        patch("harness.land._check_ready_before_land", return_value=True),
        patch("harness.land._verify_before_land", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
        patch("harness.land._banner") as banner,
    ):
        result = land("001", project_dir=repo, gitops=gitops)

    assert result is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-authoring"
    assert current.read_text(encoding="utf-8") == "run-b"
    gitops.merge_pr.assert_not_called()
    gitops.merge_branch_into_default.assert_not_called()
    assert banner.call_args.args[0] == "LAND — ACTIVE AUTHORING SPEC"


@pytest.mark.unit
def test_land_refuses_active_authoring_branch_for_relative_single_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "-b", "002-authoring", "main")

    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Demo\n",
        encoding="utf-8",
    )

    current = repo / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-b", encoding="utf-8")
    run_dir = repo / "runs" / "run-b"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        '{"run_id":"run-b","spec_id":"002-authoring",'
        '"feature_branch":"002-authoring",'
        '"spec_dir":"runs/run-b/specs/002-authoring"}',
        encoding="utf-8",
    )
    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    monkeypatch.chdir(tmp_path)

    with (
        patch("harness.land._check_ready_before_land", return_value=True),
        patch(
            "harness.land._prepare_for_land",
            return_value=LandPrepareResult(status="prepared", branch="001-feature"),
        ) as prepare,
        patch("harness.land._verify_before_land", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
        patch("harness.land._banner") as banner,
    ):
        result = land("001", project_dir=Path("repo"), gitops=gitops)

    assert result is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-authoring"
    assert current.read_text(encoding="utf-8") == "run-b"
    prepare.assert_not_called()
    gitops.merge_pr.assert_not_called()
    gitops.merge_branch_into_default.assert_not_called()
    assert banner.call_args.args[0] == "LAND — ACTIVE AUTHORING SPEC"


@pytest.mark.unit
def test_land_refuses_active_authoring_branch_for_relative_no_spec_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "-b", "002-authoring", "main")

    current = repo / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-b", encoding="utf-8")
    run_dir = repo / "runs" / "run-b"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        '{"run_id":"run-b","spec_id":"002-authoring",'
        '"feature_branch":"002-authoring",'
        '"spec_dir":"runs/run-b/specs/002-authoring"}',
        encoding="utf-8",
    )
    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    monkeypatch.chdir(tmp_path)

    with (
        patch("harness.land._check_ready_before_land", return_value=True),
        patch(
            "harness.land._prepare_for_land",
            return_value=LandPrepareResult(status="prepared", branch="001-feature"),
        ) as prepare,
        patch("harness.land._verify_before_land", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
        patch("harness.land._banner") as banner,
    ):
        result = land("001", project_dir=Path("repo"), gitops=gitops)

    assert result is False
    assert _git(repo, "branch", "--show-current").stdout.strip() == "002-authoring"
    assert current.read_text(encoding="utf-8") == "run-b"
    prepare.assert_not_called()
    gitops.merge_pr.assert_not_called()
    gitops.merge_branch_into_default.assert_not_called()
    assert banner.call_args.args[0] == "LAND — ACTIVE AUTHORING SPEC"


@pytest.mark.unit
def test_land_prefers_converged_current_build_iter_over_higher_failed_iter(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "wrapper"
    target = wrapper / "sources" / "prosaic"
    _init_repo(wrapper)
    _init_repo(target)
    _commit(target, "README.md", "base\n", "base")
    _git(target, "checkout", "-b", "harness/911/default/iter-1")
    verified_commit = _commit(target, "feature.txt", "verified\n", "verified work")
    _git(target, "checkout", "main")
    _git(target, "branch", "harness/911/default/iter-4")

    spec_dir = wrapper / "specs" / "911-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\ntargets:\n- sources/prosaic\n---\n# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        f"---\nverified_commit: {verified_commit}\n---\n",
        encoding="utf-8",
    )
    marker = wrapper / "runs" / ".current-build-911"
    marker.parent.mkdir(parents=True)
    marker.write_text("build-911", encoding="utf-8")
    state_dir = wrapper / "runs" / "build-911" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "spec_id": "911-demo",
                "strategy_id": "default",
                "outer_iter": 1,
                "status": "converged",
            }
        ),
        encoding="utf-8",
    )

    gitops = _make_gitops(feature_branch=None)
    with (
        patch("harness.land._check_ready_before_land", return_value=True),
        patch(
            "harness.land._prepare_for_land",
            return_value=LandPrepareResult(status="prepared", branch="harness/911/default/iter-1"),
        ),
        patch("harness.land._verify_before_land", return_value=True),
        patch("harness.land._clean_generated_drift_before_direct_merge", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
    ):
        assert land("911", project_dir=wrapper, gitops=gitops, harness_root=wrapper)

    gitops.merge_branch_into_default.assert_called_once_with(
        "harness/911/default/iter-1", str(target.resolve())
    )


@pytest.mark.unit
def test_land_blocks_when_current_build_branch_misses_verified_commit(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "wrapper"
    target = wrapper / "sources" / "prosaic"
    _init_repo(wrapper)
    _init_repo(target)
    _commit(target, "README.md", "base\n", "base")
    _git(target, "branch", "harness/911/default/iter-1")
    _git(target, "branch", "harness/911/default/iter-4")
    _git(target, "checkout", "-b", "unrelated")
    verified_commit = _commit(target, "other.txt", "unrelated\n", "unrelated work")
    _git(target, "checkout", "main")

    spec_dir = wrapper / "specs" / "911-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\ntargets:\n- sources/prosaic\n---\n# Demo\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        f"---\nverified_commit: {verified_commit}\n---\n",
        encoding="utf-8",
    )
    marker = wrapper / "runs" / ".current-build-911"
    marker.parent.mkdir(parents=True)
    marker.write_text("build-911", encoding="utf-8")
    state_dir = wrapper / "runs" / "build-911" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "default.json").write_text(
        json.dumps(
            {
                "spec_id": "911-demo",
                "strategy_id": "default",
                "outer_iter": 1,
                "status": "converged",
            }
        ),
        encoding="utf-8",
    )

    gitops = _make_gitops(feature_branch=None)
    with patch("harness.land._banner") as banner:
        result = land("911", project_dir=wrapper, gitops=gitops, harness_root=wrapper)

    assert result is False
    assert banner.call_args.args[0] == "LAND — BRANCH RESOLUTION BLOCKED"
    assert not any(
        call.args[0] in {"harness/911/default/iter-1", "harness/911/default/iter-4"}
        for call in gitops.merge_branch_into_default.call_args_list
    )


@pytest.mark.unit
@pytest.mark.parametrize("converged_states", ([], ["default", "conservative"]))
def test_current_build_harness_branch_requires_exactly_one_converged_strategy(
    tmp_path: Path,
    converged_states: list[str],
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    spec_dir = repo / "specs" / "911-demo"
    spec_dir.mkdir(parents=True)
    (repo / "runs").mkdir(exist_ok=True)
    (repo / "runs" / ".current-build-911").write_text("build-911", encoding="utf-8")
    state_dir = repo / "runs" / "build-911" / "state"
    state_dir.mkdir(parents=True)
    for strategy in converged_states:
        (state_dir / f"{strategy}.json").write_text(
            json.dumps(
                {
                    "spec_id": "911-demo",
                    "strategy_id": strategy,
                    "outer_iter": 1,
                    "status": "converged",
                }
            ),
            encoding="utf-8",
        )
    if not converged_states:
        (state_dir / "default.json").write_text(
            json.dumps({"spec_id": "911-demo", "status": "failed"}),
            encoding="utf-8",
        )

    gitops = _make_gitops(feature_branch=None)
    with patch("harness.land._banner") as banner:
        result = land("911", project_dir=repo, gitops=gitops, harness_root=repo)

    assert result is False
    assert banner.call_args.args[0] == "LAND — BRANCH RESOLUTION BLOCKED"


@pytest.mark.unit
def test_polyrepo_land_does_not_compare_wrapper_and_target_branch_names(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "wrapper"
    target = wrapper / "sources" / "prosaic"
    _init_repo(wrapper)
    _init_repo(target)
    _commit(target, "README.md", "base\n", "base")

    spec_dir = wrapper / "specs" / "911-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\ntargets:\n- sources/prosaic\n---\n# Demo\n",
        encoding="utf-8",
    )
    current = wrapper / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-a", encoding="utf-8")
    run_dir = wrapper / "runs" / "run-a"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "spec_id": "911-demo",
                "feature_branch": "911-demo",
                "spec_dir": "runs/run-a/specs/911-demo",
                "published_spec_dir": "specs/911-demo",
            }
        ),
        encoding="utf-8",
    )

    gitops = _make_gitops(feature_branch="harness/911/default/iter-1")
    with (
        patch("harness.land._check_ready_before_land", return_value=True),
        patch(
            "harness.land._prepare_for_land",
            return_value=LandPrepareResult(status="prepared", branch="harness/911/default/iter-1"),
        ) as prepare,
        patch("harness.land._verify_before_land", return_value=True),
        patch("harness.land._clean_generated_drift_before_direct_merge", return_value=True),
        patch("harness.land._finish_landing", return_value=True),
        patch("harness.land._banner") as banner,
    ):
        assert land("911", project_dir=wrapper, gitops=gitops, harness_root=wrapper)

    prepare.assert_called_once()
    assert all(call.args[0] != "LAND — ACTIVE AUTHORING SPEC" for call in banner.call_args_list)


@pytest.mark.unit
def test_land_discards_generated_verify_drift_before_direct_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _commit(repo, "docs/perf/perf-metrics.json", '{"metrics": {}}\n', "base metrics")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    main_commit = _commit(repo, "main.txt", "main\n", "main")

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.delete_remote_branch.return_value = True
    gitops.push_landed_default_branch.return_value = True

    def verify_writes_generated_metrics(
        spec_id: str,
        project_dir: Path,
        gitops_arg: MagicMock,
        options: LandOptions,
    ) -> bool:
        assert spec_id == "001"
        (project_dir / "docs/perf/perf-metrics.json").write_text(
            '{"metrics": {"rerun": true}}\n',
            encoding="utf-8",
        )
        return True

    def direct_merge(branch: str, project_dir: str) -> bool:
        target = Path(project_dir)
        assert _git(target, "diff", "--name-only", "HEAD", "--").stdout.strip() == ""
        assert (
            _git(target, "merge-base", "--is-ancestor", main_commit, branch, check=False).returncode
            == 0
        )
        _git(target, "checkout", "main")
        _git(target, "merge", "--no-ff", branch, "-m", "land feature")
        return True

    gitops.merge_branch_into_default.side_effect = direct_merge

    with (
        patch("harness.land._verify_before_land", side_effect=verify_writes_generated_metrics),
        patch("harness.land._delete_local_branch"),
    ):
        result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is True
    gitops.merge_branch_into_default.assert_called_once_with("001-feature", str(repo))
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"


@pytest.mark.unit
def test_land_blocks_unknown_verify_drift_before_direct_merge(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main")

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"

    def verify_writes_source_file(
        spec_id: str,
        project_dir: Path,
        gitops_arg: MagicMock,
        options: LandOptions,
    ) -> bool:
        (project_dir / "feature.txt").write_text("changed after verify\n", encoding="utf-8")
        return True

    with (
        patch("harness.land._verify_before_land", side_effect=verify_writes_source_file),
        patch("harness.land._banner") as banner,
    ):
        result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is False
    gitops.merge_branch_into_default.assert_not_called()
    assert banner.call_args.args[0] == "LAND — DIRTY WORKTREE"
    assert _git(repo, "branch", "--show-current").stdout.strip() == "001-feature"


@pytest.mark.unit
def test_land_finishes_cleanup_when_default_already_contains_feature(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "001-feature", "-m", "land feature")
    _git(repo, "checkout", "001-feature")

    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Spec\n",
        encoding="utf-8",
    )
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        f"verified_commit: {head}\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | feature.txt | high | ok |\n",
        encoding="utf-8",
    )

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.delete_remote_branch.return_value = True

    with (
        patch("harness.land._origin_remote_url", return_value=None),
        patch("harness.land._cleanup_worktrees") as cleanup_worktrees,
        patch("harness.land._delete_harness_branches") as delete_harness_branches,
    ):
        result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is True
    gitops.delete_remote_branch.assert_not_called()
    gitops.ensure_on_default_branch.assert_called_once_with(str(repo))
    cleanup_worktrees.assert_called_once()
    delete_harness_branches.assert_called_once()
    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert _git(repo, "branch", "--list", "001-feature").stdout.strip() == ""


@pytest.mark.unit
def test_land_clears_active_authoring_pointer_for_landed_spec(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature")
    _git(repo, "checkout", "main")
    _git(repo, "merge", "--no-ff", "001-feature", "-m", "land feature")

    spec_dir = repo / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "---\nstatus: ready_to_land\n---\n# Spec\n",
        encoding="utf-8",
    )
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    (spec_dir / "fulfillment-report.md").write_text(
        "---\n"
        f"verified_commit: {head}\n"
        "---\n"
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | feature.txt | high | ok |\n",
        encoding="utf-8",
    )
    current = repo / "runs" / ".current"
    current.parent.mkdir(parents=True)
    current.write_text("run-a\n", encoding="utf-8")
    run_dir = repo / "runs" / "run-a"
    run_dir.mkdir()
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "spec_id": "001-demo",
                "feature_branch": "001-feature",
                "spec_dir": "runs/run-a/specs/001-demo",
                "published_spec_dir": "specs/001-demo",
            }
        ),
        encoding="utf-8",
    )

    gitops = MagicMock()
    gitops.find_feature_branch.return_value = "001-feature"
    gitops.get_default_branch.return_value = "main"
    gitops.delete_remote_branch.return_value = True

    with (
        patch("harness.land._origin_remote_url", return_value=None),
        patch("harness.land._cleanup_worktrees"),
        patch("harness.land._delete_harness_branches"),
    ):
        result = land("001", project_dir=repo, gitops=gitops, options=LandOptions())

    assert result is True
    assert not current.exists()


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

    with patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"):
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
def test_prepare_feature_branch_skips_push_without_origin(tmp_path: Path) -> None:
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

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(),
    )

    assert result.status == "prepared"
    assert result.pushed is False
    gitops.push_prepared_branch.assert_not_called()


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
    gitops.push_prepared_branch.assert_not_called()
    assert result.pushed is False
    assert result.autoresolved_files == [".gitignore"]
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert (repo / ".gitignore").read_text(encoding="utf-8").splitlines() == [
        "*.pyc",
        ".env",
        ".cache",
    ]


@pytest.mark.unit
def test_prepare_feature_branch_autoresolves_specify_runtime_removal(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _commit(
        repo,
        ".specify/memory/constitution.md",
        "# Constitution\n\n[PROJECT_NAME]\n",
        "track legacy spec-kit constitution",
    )
    _commit(repo, ".specify/templates/spec-template.md", "# Template\n", "track templates")

    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", "__pycache__/\n.pytest_cache/\n", "feature gitignore")
    _commit(
        repo,
        ".specify/memory/constitution.md",
        "# Constitution\n\nReal project rules.\n",
        "feature constitution update",
    )

    _git(repo, "checkout", "main")
    _git(repo, "rm", "-r", ".specify")
    (repo / ".gitignore").write_text("/.specify/\n/runs/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore spec-kit runtime state")

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
    assert ".gitignore" in result.autoresolved_files
    assert ".specify/memory/constitution.md" in result.autoresolved_files
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert _git(repo, "ls-files", ".specify").stdout.strip() == ""
    assert "/.specify/" in (repo / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in (repo / ".gitignore").read_text(encoding="utf-8")
    gitops.push_prepared_branch.assert_not_called()


@pytest.mark.unit
def test_prepare_feature_branch_continue_autoresolves_specify_runtime_removal(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _commit(
        repo,
        ".specify/memory/constitution.md",
        "# Constitution\n\n[PROJECT_NAME]\n",
        "track legacy spec-kit constitution",
    )

    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, ".gitignore", "__pycache__/\n", "feature gitignore")
    _commit(
        repo,
        ".specify/memory/constitution.md",
        "# Constitution\n\nReal project rules.\n",
        "feature constitution update",
    )

    _git(repo, "checkout", "main")
    _git(repo, "rm", "-r", ".specify")
    (repo / ".gitignore").write_text("/.specify/\n/runs/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-m", "ignore spec-kit runtime state")

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"
    gitops.push_prepared_branch.return_value = None

    blocked = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(autoresolve=False),
    )
    assert blocked.status == "blocked"
    assert blocked.conflicted_files == [".gitignore", ".specify/memory/constitution.md"]

    with patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"):
        result = prepare_feature_branch(
            spec_id="001",
            feature_branch="001-feature",
            project_dir=repo,
            gitops=gitops,
            options=LandOptions(continue_existing=True),
        )

    assert result.status == "prepared"
    assert ".gitignore" in result.autoresolved_files
    assert ".specify/memory/constitution.md" in result.autoresolved_files
    assert _git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip() == ""
    assert _git(repo, "ls-files", ".specify").stdout.strip() == ""


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

    with patch("harness.land._origin_remote_url", return_value="git@github.com:org/repo.git"):
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
def test_prepare_feature_branch_continue_recovers_after_push_only_failure(
    tmp_path: Path,
) -> None:
    from harness.land import LandOptions, prepare_feature_branch

    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit(repo, "README.md", "base\n", "base")
    _commit(repo, "docs/perf/perf-metrics.json", '{"metrics": {}}\n', "base metrics")
    _git(repo, "checkout", "-b", "001-feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _git(repo, "checkout", "main")
    _commit(repo, "main.txt", "main\n", "main work")
    _git(repo, "checkout", "001-feature")
    _git(repo, "merge", "--no-ff", "main", "-m", "Merge main into 001-feature")
    (repo / "docs/perf/perf-metrics.json").write_text(
        '{"metrics": {"rerun": true}}\n',
        encoding="utf-8",
    )

    gitops = MagicMock()
    gitops.get_default_branch.return_value = "main"

    result = prepare_feature_branch(
        spec_id="001",
        feature_branch="001-feature",
        project_dir=repo,
        gitops=gitops,
        options=LandOptions(continue_existing=True),
    )

    assert result.status == "prepared"
    assert result.branch == "001-feature"
    assert result.pushed is False
    assert result.message == "feature branch is already prepared"
    gitops.push_prepared_branch.assert_not_called()
    assert _git(repo, "diff", "--name-only", "HEAD", "--").stdout.strip() == ""
    assert (
        _git(repo, "merge-base", "--is-ancestor", "main", "001-feature", check=False).returncode
        == 0
    )


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
        gitops.delete_remote_branch.assert_not_called()
        gitops.destroy_worktree.assert_called_once_with(worktree_dir, keep_branch=True)
        gitops.ensure_on_default_branch.assert_called_once_with(str(tmp_path))

        from harness.spec_frontmatter import read_frontmatter
        assert read_frontmatter(spec_dir)["status"] == "landed"
