"""GitOpsManager — all git operations for the harness two-repo model.

Per contracts/gitops-interface.md:
- Mirror operations: clone_mirror, fetch_mirror
- Worktree operations: create_worktree, destroy_worktree
- Commit operations: commit (with [skip ci] support, FR-CI-001)
- Push operations: push (--force-with-lease, rebase retry, FR-REPO-005b)
- PR operations: create_draft_pr, update_pr, promote_pr_ready, merge_pr
- Safety: validate_not_self_targeting (FR-INIT-001), never-push-default (FR-REPO-004)
- Degraded mode: branch-push-only when gh/glab absent

Per ADR-001: Uses git CLI via subprocess.
Per ADR-006: Uses gh/glab CLI for PR operations.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Optional

from harness.config import HarnessConfig
from harness.errors import GitOpsError, GitOpsEscalation, SelfTargetError
from harness.paths import build_dir as _build_dir_fn, mirror_path as _mirror_path_fn, runs_dir as _runs_dir_fn

logger = logging.getLogger(__name__)

# Command timeout for git operations (seconds)
GIT_CMD_TIMEOUT = 120


def _run_git(
    args: list,
    cwd: Optional[str] = None,
    timeout: int = GIT_CMD_TIMEOUT,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command with timeout.

    Raises:
        GitOpsError: If the git command fails.
    """
    cmd = ["git"] + args
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as e:
        raise GitOpsError(
            f"Git command timed out after {timeout}s: {' '.join(cmd)}",
            command=" ".join(cmd),
        )
    except subprocess.CalledProcessError as e:
        raise GitOpsError(
            f"Git command failed: {' '.join(cmd)}: {e.stderr.strip()}",
            command=" ".join(cmd),
        )


def _check_tool_available(tool: str) -> bool:
    """Check if a CLI tool is available on PATH."""
    return shutil.which(tool) is not None


class GitOpsManager:
    """All git operations for the harness two-repo model.

    Uses git CLI via subprocess (ADR-006).
    Uses gh/glab CLI for PR operations (ADR-006).
    """

    def __init__(self, config: HarnessConfig, base_dir: Optional[str] = None) -> None:
        """Initialize with harness config.

        Validates: git is available, gh/glab is available (warn if absent).

        Args:
            config: Harness configuration.
            base_dir: Base directory for mirror and worktrees. Defaults to cwd.
        """
        self._config = config
        self._base_dir = Path(base_dir) if base_dir else Path.cwd()
        self._mirror_path = _mirror_path_fn(self._base_dir)

        # Validate git is available
        if not _check_tool_available("git"):
            raise GitOpsError("git CLI is not available on PATH")

        # Check for gh/glab (warn if absent — degraded mode)
        self._has_gh = _check_tool_available("gh")
        self._has_glab = _check_tool_available("glab")
        self._pr_tool: Optional[str] = None

        if config.pr_host == "github" and self._has_gh:
            self._pr_tool = "gh"
        elif config.pr_host == "gitlab" and self._has_glab:
            self._pr_tool = "glab"
        elif config.pr_host != "none":
            if not self._has_gh and not self._has_glab:
                logger.warning(
                    "Neither gh nor glab CLI found. "
                    "PR operations will be unavailable (degraded mode). "
                    "Git push operations will still work."
                )

    @property
    def base_dir(self) -> Path:
        """Project root directory."""
        return self._base_dir

    @property
    def mirror_path(self) -> Path:
        """Path to the bare mirror repository."""
        return self._mirror_path

    # === Mirror Operations ===

    def clone_mirror(self, target_url: str) -> str:
        """Clone target repo as bare mirror.

        git clone --mirror <target_url> .specify/extensions/echelon/harness/mirror.git

        Returns:
            Path to the mirror directory.

        Raises:
            GitOpsError: If clone fails (auth, network, invalid URL).

        FR-REPO-002
        """
        self._mirror_path.parent.mkdir(parents=True, exist_ok=True)

        # Resolve local paths to absolute so git records a clean origin URL
        # (avoids trailing-dot artifacts from cloning with target_url=".")
        resolved_url = target_url
        candidate = Path(target_url)
        if not candidate.is_absolute():
            resolved = (self._base_dir / candidate).resolve()
            if resolved.exists():
                resolved_url = str(resolved)

        if self._mirror_path.exists():
            logger.info("Mirror already exists at %s, fetching instead", self._mirror_path)
            # Ensure origin URL is clean (fix up stale trailing-dot remotes)
            try:
                result = _run_git(
                    ["config", "--get", "remote.origin.url"],
                    cwd=str(self._mirror_path),
                    check=False,
                )
                if result.returncode == 0 and result.stdout.strip() != resolved_url:
                    _run_git(
                        ["remote", "set-url", "origin", resolved_url],
                        cwd=str(self._mirror_path),
                    )
                    logger.info("Updated mirror origin URL to %s", resolved_url)
            except Exception:
                pass
            self.fetch_mirror()
            return str(self._mirror_path)

        _run_git(
            ["clone", "--mirror", resolved_url, str(self._mirror_path)],
            cwd=str(self._base_dir),
        )
        logger.info("Cloned mirror from %s to %s", resolved_url, self._mirror_path)
        return str(self._mirror_path)

    def fetch_mirror(self) -> None:
        """Fetch all updates in the mirror.

        git -C mirror.git fetch --all --prune

        Raises:
            GitOpsError: On failure (network, auth).

        FR-REPO-002
        """
        if not self._mirror_path.exists():
            raise GitOpsError(
                f"Mirror does not exist at {self._mirror_path}. Run 'echelon harness init' to create it.",
                command="fetch_mirror",
            )
        try:
            _run_git(
                ["fetch", "--all", "--prune"],
                cwd=str(self._mirror_path),
            )
        except GitOpsError as e:
            if "refusing to fetch into branch" in str(e):
                # One or more branches are checked out in harness worktrees.
                # The mirror has stale data for those refs but that is acceptable —
                # those branches are actively in use and do not need to be updated.
                logger.warning(
                    "Mirror fetch skipped branch(es) locked in worktrees: %s", e
                )
            else:
                raise
        logger.info("Fetched mirror at %s", self._mirror_path)

    # === Worktree Operations ===

    def find_feature_branch(self, spec_id: str) -> Optional[str]:
        """Find the echelon feature branch for a spec.

        Tries two patterns against the mirror:
          1. Exact match of spec_id (handles full-slug IDs like '069-state-reader-role-assumption').
          2. Prefix match '{spec_id}-*' (handles numeric-only IDs like '069').

        Returns:
            Branch name or None if not found.
        """
        if not self._mirror_path.exists():
            logger.warning("Mirror does not exist — cannot search for feature branch")
            return None

        try:
            self.fetch_mirror()
        except GitOpsError as e:
            logger.warning("Could not fetch mirror while looking for feature branch: %s", e)

        def _list_branches(pattern: str) -> list[str]:
            try:
                result = _run_git(
                    ["branch", "--list", pattern],
                    cwd=str(self._mirror_path),
                )
                return [b.strip().lstrip("* ") for b in result.stdout.splitlines() if b.strip()]
            except GitOpsError as e:
                logger.warning("Could not list branches (pattern=%r) for spec %s: %s", pattern, spec_id, e)
                return []

        for pattern in (spec_id, f"{spec_id}-*"):
            branches = _list_branches(pattern)
            if branches:
                chosen = branches[0]
                logger.info("Found feature branch for spec %s: %s", spec_id, chosen)
                return chosen

        return None

    def create_worktree(
        self,
        spec_id: str,
        strategy_id: str,
        outer_iter: int,
        base_branch: Optional[str] = None,
        build_id: str = "",
    ) -> str:
        """Create ephemeral worktree from mirror.

        When base_branch is provided (the echelon feature branch, e.g.
        '001-weather-dashboard'): the worktree is checked out directly on that
        branch — no new harness/* branch is created. All implementation commits
        go to the feature branch itself, keeping the history on one branch until
        it is merged to main.

        When base_branch is None (legacy / no-echelon mode): a new branch named
        'harness/{spec_id}-{strategy_id}-iter-{outer_iter}' is created from the
        default branch HEAD (original behaviour).

        Returns:
            Absolute path to the worktree directory.

        FR-REPO-003a
        """
        if not self._mirror_path.exists():
            raise GitOpsError(
                f"Mirror does not exist at {self._mirror_path}. Run 'echelon harness init' to create it.",
                command="create_worktree",
            )

        # Worktree directory — same path regardless of branching mode.
        worktree_dir = (
            _build_dir_fn(self._base_dir, build_id) / "worktrees"
            / strategy_id / f"iter-{outer_iter}"
        )
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)

        # If a worktree already exists at this path (from a previous run), remove it
        # and prune stale registrations before creating a fresh one. Git does not
        # allow two worktrees checked out on the same branch, so this is required —
        # not just housekeeping. The committed state is in git (feature branch HEAD),
        # so nothing of value is lost by destroying the working directory.
        if worktree_dir.exists():
            try:
                _run_git(
                    ["worktree", "remove", "--force", str(worktree_dir)],
                    cwd=str(self._mirror_path),
                )
            except GitOpsError as e:
                logger.warning("Could not remove existing worktree at %s: %s", worktree_dir, e)
                # Directory may be an orphan (e.g., left after a branch switch with
                # committed submodule-like dirs). Force-remove from disk so the
                # subsequent `git worktree add` can create a fresh checkout.
                if worktree_dir.exists():
                    shutil.rmtree(str(worktree_dir))
                    logger.info("Force-removed orphan directory %s from disk", worktree_dir)
            _run_git(["worktree", "prune"], cwd=str(self._mirror_path))
            logger.info("Removed stale worktree at %s before recreating", worktree_dir)

        if base_branch:
            # Feature-branch mode: check out the existing echelon branch directly.
            # No new branch is created; harness commits land on the feature branch.
            branch_name = base_branch
            try:
                _run_git(
                    ["worktree", "add", str(worktree_dir), branch_name],
                    cwd=str(self._mirror_path),
                )
                logger.info(
                    "Created worktree at %s on feature branch %s",
                    worktree_dir, branch_name,
                )
            except GitOpsError as e:
                # Branch is already checked out in another working tree (typically
                # the main project directory when echelon.run left it on the feature
                # branch). Reuse that existing path rather than failing.
                match = re.search(
                    r"already used by worktree at '([^']+)'", str(e)
                )
                if match:
                    existing_path = match.group(1)
                    logger.warning(
                        "Branch %s already checked out at %s — reusing that path",
                        branch_name, existing_path,
                    )
                    # Add upstream remote to the existing path if not already present.
                    target_url = self._config.target_repo
                    if target_url == ".":
                        target_url = str(self._base_dir)
                    try:
                        _run_git(
                            ["remote", "add", "upstream", target_url],
                            cwd=existing_path,
                        )
                    except GitOpsError:
                        logger.warning(
                            "'upstream' remote may already exist at %s, updating URL", existing_path
                        )
                        try:
                            _run_git(
                                ["remote", "set-url", "upstream", target_url],
                                cwd=existing_path,
                            )
                        except GitOpsError as e:
                            logger.warning("Could not update upstream URL: %s", e)
                    return existing_path
                raise
        else:
            # Legacy mode: create a new harness/* branch from default branch HEAD.
            default_branch = self.get_default_branch()
            branch_name = f"harness/{spec_id}/{strategy_id}/iter-{outer_iter}"
            try:
                _run_git(
                    ["branch", branch_name, default_branch],
                    cwd=str(self._mirror_path),
                )
            except GitOpsError:
                logger.warning("Branch %s may already exist, continuing", branch_name)
            _run_git(
                ["worktree", "add", str(worktree_dir), branch_name],
                cwd=str(self._mirror_path),
            )
            logger.info(
                "Created worktree at %s on branch %s (base: %s)",
                worktree_dir, branch_name, default_branch,
            )

        # Add 'upstream' remote pointing to the real target repo.
        # The worktree's 'origin' inherits the mirror's remote, which may have
        # mirror=true (especially in single-repo mode). mirror=true blocks
        # `git push origin <branch>` with refspecs. 'upstream' is a clean remote
        # without mirror=true that we use for all pushes.
        target_url = self._config.target_repo
        is_local_target = target_url in (".", "") or Path(target_url).is_dir()
        if target_url == ".":
            # Resolve "." to an absolute path so the remote works from the worktree
            target_url = str(self._base_dir)
        try:
            _run_git(
                ["remote", "add", "upstream", target_url],
                cwd=str(worktree_dir),
            )
        except GitOpsError:
            # Remote may already exist if worktree was re-created; update URL to
            # ensure it points to the current target_repo (handles target_repo changes).
            logger.warning("'upstream' remote may already exist in worktree, updating URL")
            try:
                _run_git(
                    ["remote", "set-url", "upstream", target_url],
                    cwd=str(worktree_dir),
                )
            except GitOpsError as e:
                logger.warning("Could not update upstream URL: %s", e)

        if is_local_target:
            # Allow pushing into a checked-out branch (single-repo mode).
            # Without this, git rejects pushes to the project's own working copy.
            try:
                _run_git(
                    ["config", "receive.denyCurrentBranch", "updateInstead"],
                    cwd=target_url,
                )
                logger.info("Set receive.denyCurrentBranch=updateInstead on %s", target_url)
            except GitOpsError as e:
                logger.warning("Could not set receive.denyCurrentBranch on %s: %s", target_url, e)

        return str(worktree_dir)

    def destroy_worktree(
        self,
        worktree_path: str,
        keep_branch: bool = True,
    ) -> None:
        """Remove worktree. On failure: log warning, continue.

        Per FR-REPO-003b: final iteration worktree is kept.
        If keep_branch=True, branch is preserved on mirror for inspection.

        Args:
            worktree_path: Absolute path to the worktree.
            keep_branch: If True, preserve the branch on the mirror.
        """
        try:
            _run_git(
                ["worktree", "remove", "--force", worktree_path],
                cwd=str(self._mirror_path),
            )
            logger.info("Removed worktree at %s", worktree_path)
        except GitOpsError as e:
            logger.warning("Could not remove worktree at %s: %s", worktree_path, e)

        if not keep_branch:
            # Try to detect branch name from worktree path
            branch_name = self._branch_from_worktree_path(worktree_path)
            if branch_name:
                try:
                    _run_git(
                        ["branch", "-D", branch_name],
                        cwd=str(self._mirror_path),
                    )
                    logger.info("Deleted branch %s", branch_name)
                except GitOpsError as e:
                    logger.warning("Could not delete branch %s: %s", branch_name, e)

    # === Commit Operations ===

    def commit(
        self,
        worktree_path: str,
        message: str,
        skip_ci: bool = True,
    ) -> str:
        """Stage all changes and commit in the worktree.

        If skip_ci and config.ci_skip_enabled: prepend ci_skip_tag.

        Returns:
            Commit SHA.

        FR-CI-001
        """
        # Stage all changes
        _run_git(["add", "-A"], cwd=worktree_path)

        # Build commit message
        if skip_ci and self._config.ci_skip_enabled:
            message = f"{self._config.ci_skip_tag} {message}"

        _run_git(
            ["commit", "-m", message, "--allow-empty"],
            cwd=worktree_path,
        )

        # Get commit SHA
        result = _run_git(
            ["rev-parse", "HEAD"],
            cwd=worktree_path,
        )
        sha = result.stdout.strip()
        logger.info("Committed in %s: %s", worktree_path, sha[:12])
        return sha

    # === Push Operations ===

    def _ensure_not_default_branch_push(self, branch: str, command: str) -> None:
        default_branch = self.get_default_branch()
        if branch == default_branch or branch.endswith(f"/{default_branch}"):
            raise GitOpsError(
                f"Refusing to push to default branch '{default_branch}' (FR-REPO-004)",
                command=command,
            )

    def push(
        self,
        worktree_path: str,
        branch: str,
        force_with_lease: bool = True,
    ) -> None:
        """Push branch to target remote.

        Uses --force-with-lease (FR-REPO-005b).
        On non-fast-forward: rebase onto latest target branch, retry once.
        FR-REPO-004: NEVER pushes to default branch directly.

        Raises:
            GitOpsEscalation: On retry failure (needs human intervention).
            GitOpsError: On push to default branch.
        """
        self._ensure_not_default_branch_push(branch, "push")

        # Use 'upstream' remote (added by create_worktree). The mirror's 'origin'
        # may have mirror=true which blocks refspec pushes.
        remote = "upstream"

        push_args = ["push", remote, branch]
        if force_with_lease:
            push_args.insert(1, "--force-with-lease")

        try:
            _run_git(push_args, cwd=worktree_path)
            logger.info("Pushed branch %s to %s", branch, remote)
            return
        except GitOpsError as e:
            if "non-fast-forward" not in str(e) and "rejected" not in str(e):
                raise
            logger.warning("Push rejected (non-fast-forward), rebasing and retrying...")

        # Rebase onto the latest remote tip of the branch we're pushing to.
        # For feature branches this means rebasing onto the remote feature branch;
        # for harness/* branches (legacy mode) the behaviour is unchanged.
        try:
            _run_git(["fetch", remote], cwd=worktree_path)
            _run_git(
                ["rebase", f"{remote}/{branch}"],
                cwd=worktree_path,
            )
        except GitOpsError as e:
            raise GitOpsEscalation(
                f"Rebase failed after non-fast-forward push: {e}. "
                f"Human intervention required.",
                command="rebase",
            )

        # Retry push once with --force (tracking info is fresh after fetch+rebase,
        # but --force-with-lease can still reject with "stale info" in some git versions).
        retry_args = ["push", "--force", remote, branch]
        try:
            _run_git(retry_args, cwd=worktree_path)
            logger.info("Push succeeded after rebase on branch %s", branch)
        except GitOpsError as e:
            raise GitOpsEscalation(
                f"Push failed after rebase retry: {e}. "
                f"Human intervention required.",
                command="push --force (retry)",
            )

    def push_prepared_branch(
        self,
        project_dir: str,
        branch: str,
        *,
        force_with_lease: bool = False,
    ) -> None:
        """Push a prepared feature branch to origin.

        FR-REPO-004: NEVER pushes to default branch directly.
        """
        self._ensure_not_default_branch_push(branch, "push_prepared_branch")
        args = ["push", "origin", branch]
        if force_with_lease:
            args.insert(1, "--force-with-lease")
        _run_git(args, cwd=project_dir)
        logger.info("Pushed prepared branch %s to origin", branch)

    # === PR Operations ===

    def find_existing_pr(self, branch: str) -> Optional[str]:
        """Return the URL of an existing open PR for this branch, or None.

        Checks only with the configured PR tool (gh or glab). Returns None when
        the tool is unavailable or no open PR exists.
        """
        if not self._pr_tool:
            return None

        try:
            if self._pr_tool == "gh":
                result = subprocess.run(
                    ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "url", "--jq", ".[0].url"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                url = result.stdout.strip()
                return url if url else None
            else:  # glab
                result = subprocess.run(
                    ["glab", "mr", "list", "--source-branch", branch, "--state", "opened"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                # glab output: first line after header contains the MR URL
                for line in result.stdout.splitlines():
                    if "http" in line:
                        return line.strip().split()[-1]
                return None
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Could not check for existing PR on branch %s: %s", branch, e)
            return None

    def create_draft_pr(
        self,
        branch: str,
        spec_id: str,
        strategy_id: str,
        spec_name: str = "",
    ) -> str:
        """Create draft PR on target repo, or return the URL of an existing one.

        If a PR already exists for the branch (e.g., echelon.run created it),
        return its URL without creating a duplicate.

        Uses gh/glab CLI. Returns PR URL.
        Returns empty string + warning when gh/glab absent (degraded mode).

        FR-REPO-005a
        """
        if not self._pr_tool:
            logger.warning(
                "No PR tool available (gh/glab not found or pr_host not configured). "
                "Cannot create draft PR. Continuing in degraded mode."
            )
            return ""

        # Check if echelon (or a prior harness run) already opened a PR
        existing = self.find_existing_pr(branch)
        if existing:
            logger.info("PR already exists for branch %s: %s", branch, existing)
            return existing

        title_suffix = f" — {spec_name}" if spec_name else f"/{strategy_id}"
        title = f"harness: {spec_id}{title_suffix}"
        body = (
            f"Automated build via spec-kit harness.\n\n"
            f"Spec: {spec_id}{(' — ' + spec_name) if spec_name else ''}\n"
            f"Strategy: {strategy_id}"
        )

        try:
            if self._pr_tool == "gh":
                result = subprocess.run(
                    [
                        "gh", "pr", "create",
                        "--draft",
                        "--title", title,
                        "--body", body,
                        "--head", branch,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
            else:  # glab
                result = subprocess.run(
                    [
                        "glab", "mr", "create",
                        "--draft",
                        "--title", title,
                        "--description", body,
                        "--source-branch", branch,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )

            pr_url = result.stdout.strip()
            logger.info("Created draft PR: %s", pr_url)
            return pr_url

        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to create draft PR: %s", e)
            return ""

    def update_pr(self, pr_url: str, body: str) -> None:
        """Update PR description with latest iteration summary."""
        if not self._pr_tool or not pr_url:
            logger.warning("Cannot update PR: no tool or URL available")
            return

        try:
            if self._pr_tool == "gh":
                # Extract PR number from URL
                pr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["gh", "pr", "edit", pr_number, "--body", body],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            else:
                mr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["glab", "mr", "update", mr_number, "--description", body],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            logger.info("Updated PR %s", pr_url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to update PR %s: %s", pr_url, e)

    def promote_pr_ready(self, pr_url: str) -> None:
        """Flip PR from draft to ready-for-review.

        FR-REPO-005c
        """
        if not self._pr_tool or not pr_url:
            logger.warning("Cannot promote PR: no tool or URL available")
            return

        try:
            if self._pr_tool == "gh":
                pr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["gh", "pr", "ready", pr_number],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            else:
                mr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["glab", "mr", "update", mr_number, "--ready"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            logger.info("Promoted PR %s to ready", pr_url)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to promote PR %s: %s", pr_url, e)

    def merge_pr(self, pr_url: str) -> bool:
        """Attempt merge. Returns True if merged, False if blocked.

        FR-MERGE-001, FR-REPO-006
        """
        if not self._pr_tool or not pr_url:
            logger.warning("Cannot merge PR: no tool or URL available")
            return False

        try:
            if self._pr_tool == "gh":
                pr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["gh", "pr", "merge", pr_number, "--merge"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
            else:
                mr_number = pr_url.rstrip("/").split("/")[-1]
                subprocess.run(
                    ["glab", "mr", "merge", mr_number],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=True,
                )
            logger.info("Merged PR %s", pr_url)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.warning("Failed to merge PR %s (may be blocked by branch protection): %s", pr_url, e)
            return False

    def merge_branch_into_default(self, branch: str, project_dir: str) -> bool:
        """Merge branch directly into the default branch in project_dir.

        Used when no PR tool is available (gh/glab not configured). Switches to
        the default branch, merges with --no-ff, leaves the working directory on
        the default branch. Returns True on success, False on failure.
        """
        default = self._config.target_default_branch
        try:
            _run_git(["checkout", default], cwd=project_dir)
            _run_git(
                ["merge", "--no-ff", branch, "-m", f"Merge branch '{branch}' into {default}"],
                cwd=project_dir,
            )
            logger.info("Merged %s → %s in %s", branch, default, project_dir)
            return True
        except GitOpsError as e:
            logger.warning("Direct merge of %s into %s failed: %s", branch, default, e)
            return False

    def delete_remote_branch(
        self, branch_name: str, *, project_dir: str, remote: str = "origin"
    ) -> bool:
        """Delete branch_name from remote. Returns True if deleted or already gone, False on real error."""
        try:
            subprocess.run(
                ["git", "push", remote, "--delete", branch_name],
                capture_output=True,
                text=True,
                timeout=60,
                check=True,
                cwd=project_dir,
            )
            logger.info("Deleted remote branch %s/%s", remote, branch_name)
            return True
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").lower()
            if "remote ref does not exist" in stderr or "error: unable to delete" in stderr:
                # Branch was never pushed to this remote or was already deleted — not an error.
                logger.info("Remote branch %s/%s not found (already gone)", remote, branch_name)
                return True
            logger.warning(
                "Could not delete remote branch %s/%s: %s\n  stderr: %s",
                remote, branch_name, e, e.stderr.strip() if e.stderr else "(none)",
            )
            return False
        except subprocess.TimeoutExpired as e:
            logger.warning("Could not delete remote branch %s/%s: timed out", remote, branch_name)
            return False

    # === Query Operations ===

    def get_latest_worktree(
        self, spec_id: str, strategy_id: str, build_id: str = ""
    ) -> Optional[str]:
        """Return path to the most recently created worktree for this spec/strategy.

        When build_id is provided, looks in that specific build's worktrees.
        When build_id is empty, scans all builds under runs/ and returns the
        highest-mtime iter directory across all of them.

        Worktrees are created at:
            runs/{build_id}/worktrees/{strategy_id}/iter-{N}
        """
        rd = _runs_dir_fn(self._base_dir)
        if build_id:
            search_dirs = [_build_dir_fn(self._base_dir, build_id) / "worktrees" / strategy_id]
        else:
            search_dirs = [
                d / "worktrees" / strategy_id
                for d in sorted(rd.glob("build-*/"))
                if d.is_dir()
            ] if rd.exists() else []

        candidates = []
        for target in search_dirs:
            if target.exists():
                candidates.extend(p for p in target.iterdir() if p.is_dir())

        if not candidates:
            return None
        return str(max(candidates, key=lambda p: p.stat().st_mtime))

    def detect_language(self, worktree_path: str) -> Dict:
        """Fingerprint target repo: detect language, package manager, Playwright.

        Returns dict with language, package_manager, has_playwright,
        has_devcontainer, devcontainer_path.

        FR-INIT-002
        """
        from harness.fingerprint import fingerprint_repo, detect_playwright
        from harness.devcontainer import parse_devcontainer

        repo_path = Path(worktree_path)
        fp = fingerprint_repo(repo_path)

        devcontainer_path = repo_path / ".devcontainer" / "devcontainer.json"
        has_devcontainer = devcontainer_path.exists()

        return {
            "language": fp.language,
            "package_manager": fp.language,  # simplified mapping
            "has_playwright": fp.has_playwright,
            "has_devcontainer": has_devcontainer,
            "devcontainer_path": str(devcontainer_path) if has_devcontainer else None,
        }

    def ensure_on_default_branch(self, project_dir: Optional[str] = None) -> None:
        """Ensure the project working directory is on the default branch.

        If the working directory is on a feature branch (e.g. because
        echelon.run left it there), backup any uncommitted changes via
        ``git stash`` and switch to the default branch so harness can
        create clean worktrees from the mirror.

        Args:
            project_dir: Path to the project working directory. Defaults to
                self._base_dir.

        Raises:
            GitOpsError: If the branch switch itself fails after stashing.
        """
        cwd = project_dir or str(self._base_dir)
        default_branch = self._config.target_default_branch

        # Detect current branch
        try:
            result = _run_git(["branch", "--show-current"], cwd=cwd, check=False)
            current_branch = result.stdout.strip()
        except Exception:
            current_branch = ""

        if not current_branch or current_branch == default_branch:
            return  # Already on default branch or detached HEAD — nothing to do

        logger.warning(
            "Project working directory is on branch '%s', expected '%s'. "
            "Recovering — backing up any local changes and switching to '%s'.",
            current_branch, default_branch, default_branch,
        )

        # Check for uncommitted changes (staged or unstaged)
        dirty_result = _run_git(
            ["status", "--porcelain"],
            cwd=cwd,
            check=False,
        )
        is_dirty = bool(dirty_result.stdout.strip())

        if is_dirty:
            # Stash with a descriptive message so changes are recoverable
            import datetime as _dt
            timestamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            stash_msg = f"harness-auto-stash-{current_branch}-{timestamp}"
            try:
                _run_git(["stash", "push", "-m", stash_msg], cwd=cwd)
                logger.warning(
                    "Stashed uncommitted changes from '%s' as '%s'. "
                    "Recover with: git stash pop",
                    current_branch, stash_msg,
                )
            except GitOpsError as e:
                logger.warning("Stash failed (proceeding anyway): %s", e)

        _run_git(["checkout", default_branch], cwd=cwd)
        logger.info(
            "Switched project working directory from '%s' to '%s'",
            current_branch, default_branch,
        )

    def get_default_branch(self) -> str:
        """Return the default branch of the mirrored target repo.

        For remote mirrors, symbolic-ref HEAD reliably points to the remote's
        default branch. For local mirrors (target_repo="."), HEAD reflects the
        current checkout state, which may be a feature branch. In that case
        we prefer "main" or "master" if either exists in the mirror.
        """
        if not self._mirror_path.exists():
            return self._config.target_default_branch

        try:
            result = _run_git(
                ["symbolic-ref", "HEAD"],
                cwd=str(self._mirror_path),
            )
            ref = result.stdout.strip()
            if ref.startswith("refs/heads/"):
                head_branch = ref[len("refs/heads/"):]
            else:
                return ref

            # For local mirrors, HEAD may point to a feature branch.
            # Check for canonical branch names and prefer them.
            for canonical in ("main", "master"):
                if canonical == head_branch:
                    break  # HEAD already points to a canonical branch
                try:
                    _run_git(
                        ["rev-parse", "--verify", f"refs/heads/{canonical}"],
                        cwd=str(self._mirror_path),
                    )
                    logger.info(
                        "HEAD points to feature branch '%s'; using '%s' as default",
                        head_branch, canonical,
                    )
                    return canonical
                except GitOpsError:
                    pass

            return head_branch
        except GitOpsError:
            return self._config.target_default_branch

    def local_merge(self, push_branch: str, spec_id: str, spec_name: str = "") -> None:
        """Merge push_branch into the default branch in the mirror, then push upstream.

        Used in degraded mode when no PR tool (gh/glab) is available.

        Raises:
            GitOpsError: If checkout, merge, or push fails.
        """
        default_branch = self.get_default_branch()
        label = f"{spec_id} — {spec_name}" if spec_name else spec_id
        _run_git(["checkout", default_branch], cwd=str(self._mirror_path))
        _run_git(
            ["merge", "--no-ff", push_branch, "-m", f"merge: {label}"],
            cwd=str(self._mirror_path),
        )
        _run_git(["push", "upstream", default_branch], cwd=str(self._mirror_path))
        logger.info("Local merge: %s → %s", push_branch, default_branch)

    # === Safety ===

    def validate_not_self_targeting(
        self,
        target_url: str,
        harness_path: str,
    ) -> None:
        """Warn if a remote target URL matches the harness repo's own remote.

        Local paths (including CWD) are explicitly allowed — this supports
        the single-repo model where the harness is installed in the target repo
        itself (target_repo: ".").

        Raises:
            SelfTargetError: Only when a remote URL unambiguously matches the
                             harness repo's own origin remote.
        """
        # Local path targets are always allowed — single-repo model.
        if os.path.isdir(target_url):
            return

        # Remote URL check: warn if target remote == harness remote (likely a
        # misconfiguration when the user meant to use a local path instead).
        try:
            result = _run_git(
                ["config", "--get", "remote.origin.url"],
                cwd=harness_path,
                check=False,
            )
            if result.returncode == 0:
                harness_remote = result.stdout.strip()
                target_normalized = _normalize_git_url(target_url)
                harness_normalized = _normalize_git_url(harness_remote)
                if target_normalized and harness_normalized:
                    if target_normalized == harness_normalized:
                        raise SelfTargetError(
                            f"Target repo URL '{target_url}' matches harness repo "
                            f"remote '{harness_remote}'. Did you mean to use '.' as the target?"
                        )
        except GitOpsError:
            pass  # Not a git repo or no remote — can't be self-targeting

    # === Private helpers ===

    def _branch_from_worktree_path(self, worktree_path: str) -> Optional[str]:
        """Extract branch name from worktree path convention."""
        # Path: .specify/harness/worktrees/{spec_id}/{strategy_id}/iter-{N}
        parts = Path(worktree_path).parts
        try:
            wt_idx = parts.index("worktrees")
            spec_id = parts[wt_idx + 1]
            strategy_id = parts[wt_idx + 2]
            iter_part = parts[wt_idx + 3]
            return f"harness/{spec_id}-{strategy_id}-{iter_part}"
        except (ValueError, IndexError):
            return None


def _normalize_git_url(url: str) -> Optional[str]:
    """Normalize git URL for comparison.

    Handles: git@host:user/repo.git, https://host/user/repo.git, etc.
    Returns: host/user/repo (normalized) or None if can't parse.
    """
    url = url.strip()
    if not url:
        return None

    # Remove trailing .git
    if url.endswith(".git"):
        url = url[:-4]

    # SSH format: git@host:user/repo
    if url.startswith("git@"):
        url = url[4:]
        url = url.replace(":", "/", 1)
        return url.lower()

    # HTTPS format: https://host/user/repo
    for prefix in ("https://", "http://", "ssh://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
            # Remove auth if present (user@host)
            if "@" in url.split("/")[0]:
                url = url.split("@", 1)[1]
            return url.lower()

    # Local path — return resolved
    if os.path.isdir(url):
        return os.path.realpath(url)

    return url.lower()
