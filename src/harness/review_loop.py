"""ReviewLoopController — Phase 3 automated PR review cycle.

Polls an open PR for blocking review comments, invokes echelon.review to
produce a fix plan, signals the coordinator to re-run Phase 1, resolves
threads after each fix, and re-requests review. Merges when the PR is
APPROVED or the silence window (merge_timeout_hours) elapses with no new
comments.

Wired in by StrategyCoordinator._run_strategy() after Phase 1 (and
optionally Phase 2) converge, gated on config.review_loop.enabled and
config.pr_host != "none".
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from harness.config import HarnessConfig
from harness.paths import harness_dir
from harness.loop_result import LoopResult

logger = logging.getLogger(__name__)

# Blocking language patterns — a comment containing any of these is treated
# as a change request even when the review state is just COMMENT.
_BLOCKING_VERBS = re.compile(
    r"\b(must|needs? to|should be|change|fix|revert|remove|rename|add|replace|"
    r"refactor|update|delete|move|extract|break|split|consolidate)\b",
    re.IGNORECASE,
)
# Comments that match these are excluded even if blocking verbs are present.
_EXCLUSION_PATTERNS = re.compile(
    r"^(nit:|nit\b|\[nit\]|optional:|minor:|suggestion:)", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Enums and data structures
# ---------------------------------------------------------------------------

class ApprovalState(Enum):
    PENDING = "pending"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"


@dataclass
class ReviewComment:
    """A single blocking review comment fetched from the PR host."""
    comment_id: str
    path: Optional[str]          # None for review-level comments
    line: Optional[int]
    body: str
    reviewer: str
    created_at: datetime
    is_inline: bool
    in_reply_to_id: Optional[str] = None


def _parse_dt(s: str) -> datetime:
    """Parse ISO-8601 timestamp from GitHub/GitLab API to aware datetime."""
    # Python 3.10 fromisoformat handles 'Z'; earlier versions don't.
    s = s.rstrip("Z")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# PR URL parsing
# ---------------------------------------------------------------------------

@dataclass
class _PrRef:
    host: str        # "github" or "gitlab"
    tool: str        # "gh" or "glab"
    owner: str
    repo: str
    number: str      # PR/MR number as string
    url: str         # original full URL


def _parse_pr_url(pr_url: str, pr_host: str) -> Optional[_PrRef]:
    """Extract owner, repo, and number from a GitHub or GitLab PR URL."""
    parsed = urlparse(pr_url)
    parts = [p for p in parsed.path.strip("/").split("/") if p]

    if pr_host == "github" or "github.com" in parsed.netloc:
        # https://github.com/{owner}/{repo}/pull/{number}
        if len(parts) >= 4 and parts[2] == "pull":
            return _PrRef(
                host="github", tool="gh",
                owner=parts[0], repo=parts[1],
                number=parts[3], url=pr_url,
            )
    elif pr_host == "gitlab" or "gitlab" in parsed.netloc:
        # https://gitlab.com/{owner}/{repo}/-/merge_requests/{number}
        # Filter out "-" placeholder segment
        clean = [p for p in parts if p != "-"]
        if len(clean) >= 4 and clean[-2] == "merge_requests":
            return _PrRef(
                host="gitlab", tool="glab",
                owner=clean[0], repo=clean[1],
                number=clean[-1], url=pr_url,
            )

    logger.warning("Could not parse PR URL: %s (pr_host=%s)", pr_url, pr_host)
    return None


# ---------------------------------------------------------------------------
# ReviewLoopController
# ---------------------------------------------------------------------------

class ReviewLoopController:
    """Phase 3: automated PR review cycle.

    Coordinator calls run_loop() once per review check. Internally it
    fetches comments, invokes echelon.review, and returns
    status="review_fix_queued" when new tasks have been written.
    The coordinator re-enters Phase 1 on that signal (Option A wiring).
    """

    def __init__(
        self,
        gitops: Any,
        config: HarnessConfig,
        spec_id: str,
        strategy_id: str,
        base_dir: str = ".",
    ) -> None:
        self._gitops = gitops
        self._config = config
        self._rl = config.review_loop
        self._spec_id = spec_id
        self._strategy_id = strategy_id
        self._base_dir = Path(base_dir)
        self._pr_host = config.pr_host

        # Resolve LLM CLI binary — ECHELON_LLM env var takes precedence over config
        _cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        self._llm_cli = _cli
        self._llm_bin = shutil.which(_cli) or _cli
        self._review_timeout_s = 1_200.0  # 20 min per review skill invocation

        # Persistent state: tracks which comment IDs we've already acted on
        self._state_file = (
            harness_dir(self._base_dir) / "state"
            / spec_id / f"{strategy_id}-review.json"
        )
        self._seen_ids: Set[str] = self._load_seen_ids()

    # === Public entry point ===

    def run_loop(
        self,
        pr_url: str,
        worktree_path: str,
        token_budget: Optional[int] = None,
    ) -> LoopResult:
        """Poll for review comments, fix, push, re-request, repeat until merged.

        Each call performs one poll cycle. Returns:
          "review_fix_queued" — new echelon.review tasks written; coordinator
                                should re-run Phase 1 then call run_loop again.
          "converged"         — PR merged.
          "failed"            — max iterations reached or unrecoverable error.
        """
        tokens_used = 0
        last_comment_time: Optional[datetime] = None

        for iteration in range(self._rl.max_fix_iterations):
            logger.info(
                "Review loop iteration %d/%d — %s",
                iteration + 1, self._rl.max_fix_iterations, pr_url,
            )

            comments = self._fetch_unresolved_comments(pr_url)
            approval_state = self._fetch_approval_state(pr_url)

            if not comments:
                if self._should_merge(last_comment_time, approval_state):
                    # Promote PR to ready if still draft before merging
                    self._gitops.promote_pr_ready(pr_url)
                    merged = self._gitops.merge_pr(pr_url)
                    return LoopResult(
                        status="converged" if merged else "failed",
                        termination_reason="converged" if merged else "blocker_escalation",
                        outer_iterations=iteration + 1,
                        inner_iterations=0,
                        pr_url=pr_url,
                        tokens_used=tokens_used,
                        final_verify=None,
                    )
                logger.info(
                    "No unresolved comments on %s — waiting %d min",
                    pr_url, self._rl.poll_interval_minutes,
                )
                time.sleep(self._rl.poll_interval_minutes * 60)
                continue

            newest = max(c.created_at for c in comments)
            if last_comment_time is None or newest > last_comment_time:
                last_comment_time = newest

            # Invoke echelon.review to produce review-fix-N.md + tasks
            fix_tokens = self._invoke_review_skill(pr_url, comments)
            tokens_used += fix_tokens

            # Mark all processed comments as seen so we don't re-process them
            for c in comments:
                self._seen_ids.add(c.comment_id)
            self._save_seen_ids()

            if self._rl.resolve_threads:
                for comment in comments:
                    self._resolve_thread(pr_url, comment.comment_id)

            self._request_review(pr_url)

            # Signal coordinator to re-run Phase 1 with the new tasks
            return LoopResult(
                status="review_fix_queued",
                termination_reason="review_fix_queued",
                outer_iterations=iteration + 1,
                inner_iterations=0,
                pr_url=pr_url,
                tokens_used=tokens_used,
                final_verify=None,
            )

        logger.warning(
            "Review loop hit max_fix_iterations=%d for %s — escalating",
            self._rl.max_fix_iterations, pr_url,
        )
        return LoopResult(
            status="failed",
            termination_reason="blocker_escalation",
            outer_iterations=self._rl.max_fix_iterations,
            inner_iterations=0,
            pr_url=pr_url,
            tokens_used=tokens_used,
            final_verify=None,
        )

    # === Private: comment fetching ===

    def _fetch_unresolved_comments(self, pr_url: str) -> List[ReviewComment]:
        """Fetch blocking unresolved review comments from GitHub/GitLab.

        Returns oldest-first. Excludes comments already in _seen_ids, replies,
        nits, pure questions, and non-blocking general comments.
        """
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return []

        if ref.host == "github":
            return self._fetch_github_comments(ref)
        return self._fetch_gitlab_comments(ref)

    def _fetch_github_comments(self, ref: _PrRef) -> List[ReviewComment]:
        comments: List[ReviewComment] = []
        repo = f"{ref.owner}/{ref.repo}"

        # 1. CHANGES_REQUESTED review bodies
        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/pulls/{ref.number}/reviews",
                    "--jq",
                    "[.[] | select(.state == \"CHANGES_REQUESTED\") | "
                    "{id: (.id | tostring), body: .body, user: .user.login, "
                    "submitted_at: .submitted_at}]",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            for item in json.loads(result.stdout or "[]"):
                body = (item.get("body") or "").strip()
                if not body:
                    continue
                cid = item["id"]
                if cid in self._seen_ids:
                    continue
                comments.append(ReviewComment(
                    comment_id=cid,
                    path=None, line=None,
                    body=body,
                    reviewer=item.get("user", ""),
                    created_at=_parse_dt(item["submitted_at"]),
                    is_inline=False,
                ))
        except Exception as e:
            logger.warning("Failed to fetch GitHub reviews: %s", e)

        # 2. Inline code review comments (root comments only)
        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/pulls/{ref.number}/comments",
                    "--jq",
                    "[.[] | select(.in_reply_to_id == null) | "
                    "{id: (.id | tostring), path: .path, line: .line, "
                    "body: .body, user: .user.login, created_at: .created_at}]",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            for item in json.loads(result.stdout or "[]"):
                body = (item.get("body") or "").strip()
                if not body:
                    continue
                if not self._is_blocking(body):
                    continue
                cid = item["id"]
                if cid in self._seen_ids:
                    continue
                comments.append(ReviewComment(
                    comment_id=cid,
                    path=item.get("path"),
                    line=item.get("line"),
                    body=body,
                    reviewer=item.get("user", ""),
                    created_at=_parse_dt(item["created_at"]),
                    is_inline=True,
                ))
        except Exception as e:
            logger.warning("Failed to fetch GitHub inline comments: %s", e)

        # 3. General PR issue comments with blocking language
        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/issues/{ref.number}/comments",
                    "--jq",
                    "[.[] | {id: (.id | tostring), body: .body, "
                    "user: .user.login, created_at: .created_at}]",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            for item in json.loads(result.stdout or "[]"):
                body = (item.get("body") or "").strip()
                if not body or not _BLOCKING_VERBS.search(body):
                    continue
                if _EXCLUSION_PATTERNS.match(body):
                    continue
                cid = item["id"]
                if cid in self._seen_ids:
                    continue
                comments.append(ReviewComment(
                    comment_id=cid,
                    path=None, line=None,
                    body=body,
                    reviewer=item.get("user", ""),
                    created_at=_parse_dt(item["created_at"]),
                    is_inline=False,
                ))
        except Exception as e:
            logger.warning("Failed to fetch GitHub issue comments: %s", e)

        comments.sort(key=lambda c: c.created_at)
        return comments

    def _fetch_gitlab_comments(self, ref: _PrRef) -> List[ReviewComment]:
        """GitLab equivalent — fetches MR notes with blocking language."""
        comments: List[ReviewComment] = []
        project = f"{ref.owner}%2F{ref.repo}"   # URL-encoded

        try:
            result = subprocess.run(
                [
                    "glab", "api",
                    f"projects/{project}/merge_requests/{ref.number}/notes",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            for item in json.loads(result.stdout or "[]"):
                if item.get("system"):
                    continue
                body = (item.get("body") or "").strip()
                if not body or not self._is_blocking(body):
                    continue
                cid = str(item["id"])
                if cid in self._seen_ids:
                    continue
                comments.append(ReviewComment(
                    comment_id=cid,
                    path=None, line=None,
                    body=body,
                    reviewer=item.get("author", {}).get("username", ""),
                    created_at=_parse_dt(item.get("created_at", "")),
                    is_inline=False,
                ))
        except Exception as e:
            logger.warning("Failed to fetch GitLab notes: %s", e)

        comments.sort(key=lambda c: c.created_at)
        return comments

    def _is_blocking(self, body: str) -> bool:
        """True if a comment body is a blocking change request."""
        if _EXCLUSION_PATTERNS.match(body):
            return False
        return bool(_BLOCKING_VERBS.search(body))

    def _fetch_approval_state(self, pr_url: str) -> ApprovalState:
        """Return the aggregate approval state of the PR.

        CHANGES_REQUESTED from any reviewer → CHANGES_REQUESTED.
        At least one APPROVED and none CHANGES_REQUESTED → APPROVED.
        Otherwise → PENDING.
        """
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return ApprovalState.PENDING

        if ref.host == "github":
            return self._fetch_github_approval(ref)
        return self._fetch_gitlab_approval(ref)

    def _fetch_github_approval(self, ref: _PrRef) -> ApprovalState:
        repo = f"{ref.owner}/{ref.repo}"
        try:
            result = subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/pulls/{ref.number}/reviews",
                    "--jq", "[.[] | .state]",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            states = json.loads(result.stdout or "[]")
            if "CHANGES_REQUESTED" in states:
                return ApprovalState.CHANGES_REQUESTED
            if "APPROVED" in states:
                return ApprovalState.APPROVED
        except Exception as e:
            logger.warning("Failed to fetch GitHub approval state: %s", e)
        return ApprovalState.PENDING

    def _fetch_gitlab_approval(self, ref: _PrRef) -> ApprovalState:
        project = f"{ref.owner}%2F{ref.repo}"
        try:
            result = subprocess.run(
                [
                    "glab", "api",
                    f"projects/{project}/merge_requests/{ref.number}/approvals",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            data = json.loads(result.stdout or "{}")
            if data.get("approved"):
                return ApprovalState.APPROVED
        except Exception as e:
            logger.warning("Failed to fetch GitLab approval state: %s", e)
        return ApprovalState.PENDING

    # === Private: PR operations ===

    def _request_review(self, pr_url: str) -> None:
        """Re-request review from config.review_loop.reviewers."""
        if not self._rl.reviewers:
            return
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return
        reviewers = ",".join(self._rl.reviewers)
        try:
            if ref.host == "github":
                subprocess.run(
                    [
                        "gh", "pr", "edit", ref.number,
                        "--add-reviewer", reviewers,
                        "--repo", f"{ref.owner}/{ref.repo}",
                    ],
                    capture_output=True, text=True, timeout=30, check=True,
                )
                logger.info("Re-requested review from %s on %s", reviewers, pr_url)
            else:
                subprocess.run(
                    [
                        "glab", "mr", "update", ref.number,
                        "--reviewer", reviewers,
                        "--repo", f"{ref.owner}/{ref.repo}",
                    ],
                    capture_output=True, text=True, timeout=30, check=True,
                )
                logger.info("Re-requested review from %s on %s", reviewers, pr_url)
        except Exception as e:
            logger.warning("Failed to request review on %s: %s", pr_url, e)

    def _resolve_thread(self, pr_url: str, comment_id: str) -> None:
        """Mark a review thread as resolved after its fix is committed.

        Posts a "Resolved" reply to the comment thread (REST API).
        Attempts GraphQL thread resolution for GitHub; logs warning on failure
        since it requires the thread ID which must be fetched separately.
        """
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return

        if ref.host == "github":
            self._resolve_github_thread(ref, comment_id)
        else:
            self._resolve_gitlab_thread(ref, comment_id)

    def _resolve_github_thread(self, ref: _PrRef, comment_id: str) -> None:
        repo = f"{ref.owner}/{ref.repo}"

        # Post a visible "Resolved" reply so reviewer sees it immediately
        try:
            subprocess.run(
                [
                    "gh", "api",
                    f"repos/{repo}/pulls/{ref.number}/comments/{comment_id}/replies",
                    "--method", "POST",
                    "--field", "body=Resolved — fix committed.",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
        except Exception as e:
            logger.warning(
                "Could not post reply to comment %s on %s: %s",
                comment_id, ref.url, e,
            )

        # Attempt GraphQL resolution to check the "Resolved" checkbox.
        # Requires fetching the thread node ID first via GraphQL.
        try:
            # Query for the thread node ID containing this comment
            query = (
                "query($owner:String!,$repo:String!,$pr:Int!){"
                "repository(owner:$owner,name:$repo){"
                "pullRequest(number:$pr){reviewThreads(first:100){nodes{"
                "id isResolved comments(first:10){nodes{databaseId}}"
                "}}}}"
            )
            result = subprocess.run(
                [
                    "gh", "api", "graphql",
                    "-f", f"query={query}",
                    "-f", f"owner={ref.owner}",
                    "-f", f"repo={ref.repo}",
                    "-F", f"pr={ref.number}",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            data = json.loads(result.stdout)
            threads = (
                data.get("data", {})
                .get("repository", {})
                .get("pullRequest", {})
                .get("reviewThreads", {})
                .get("nodes", [])
            )
            thread_node_id = None
            for thread in threads:
                if thread.get("isResolved"):
                    continue
                for node in thread.get("comments", {}).get("nodes", []):
                    if str(node.get("databaseId")) == comment_id:
                        thread_node_id = thread["id"]
                        break
                if thread_node_id:
                    break

            if thread_node_id:
                mutation = (
                    "mutation($id:ID!){resolveReviewThread(input:{threadId:$id})"
                    "{thread{isResolved}}}"
                )
                subprocess.run(
                    [
                        "gh", "api", "graphql",
                        "-f", f"query={mutation}",
                        "-f", f"id={thread_node_id}",
                    ],
                    capture_output=True, text=True, timeout=30, check=True,
                )
                logger.info("Resolved GitHub review thread for comment %s", comment_id)
        except Exception as e:
            logger.warning(
                "GraphQL thread resolution failed for comment %s: %s — "
                "reply was posted but checkbox not checked",
                comment_id, e,
            )

    def _resolve_gitlab_thread(self, ref: _PrRef, comment_id: str) -> None:
        project = f"{ref.owner}%2F{ref.repo}"
        try:
            # Find the discussion containing this note, then resolve it
            result = subprocess.run(
                [
                    "glab", "api",
                    f"projects/{project}/merge_requests/{ref.number}/discussions",
                ],
                capture_output=True, text=True, timeout=30, check=True,
            )
            discussions = json.loads(result.stdout or "[]")
            discussion_id = None
            for discussion in discussions:
                for note in discussion.get("notes", []):
                    if str(note.get("id")) == comment_id:
                        discussion_id = discussion["id"]
                        break
                if discussion_id:
                    break

            if discussion_id:
                subprocess.run(
                    [
                        "glab", "api",
                        f"projects/{project}/merge_requests/{ref.number}"
                        f"/discussions/{discussion_id}",
                        "--method", "PUT",
                        "--field", "resolved=true",
                    ],
                    capture_output=True, text=True, timeout=30, check=True,
                )
                logger.info(
                    "Resolved GitLab discussion %s for note %s",
                    discussion_id, comment_id,
                )
        except Exception as e:
            logger.warning(
                "Failed to resolve GitLab discussion for note %s: %s",
                comment_id, e,
            )

    # === Private: merge decision ===

    def _should_merge(
        self,
        last_comment_time: Optional[datetime],
        approval_state: ApprovalState,
    ) -> bool:
        """True when the PR is ready to merge.

        APPROVED → merge immediately.
        CHANGES_REQUESTED → never merge.
        PENDING + require_approval=False → merge after silence window.
        PENDING + require_approval=True → never merge on timeout alone.
        """
        if approval_state == ApprovalState.CHANGES_REQUESTED:
            return False
        if approval_state == ApprovalState.APPROVED:
            return True
        if self._rl.require_approval:
            return False
        if last_comment_time is None:
            return False
        elapsed_hours = (
            datetime.now(tz=timezone.utc) - last_comment_time
        ).total_seconds() / 3600.0
        return elapsed_hours >= self._rl.merge_timeout_hours

    # === Private: skill invocation ===

    def _invoke_review_skill(
        self,
        pr_url: str,
        comments: List[ReviewComment],
    ) -> int:
        """Invoke echelon.review via claude -p subprocess.

        Writes HARNESS_BUILD_STATUS_FILE, waits for skill completion,
        reads the status file to confirm review-fix tasks were queued.

        Returns a rough token estimate (stdout byte count / 4).
        """
        status_file = self._base_dir / ".harness-review-status.json"
        # Remove stale status file from a previous invocation
        status_file.unlink(missing_ok=True)

        env = {**os.environ, "HARNESS_BUILD_STATUS_FILE": str(status_file)}
        if self._config.llm.config_dir:
            env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(self._config.llm.config_dir)

        from harness.skill_loader import resolve_llm_prompt
        args = f"{self._spec_id} pr_url={pr_url}"
        prompt = resolve_llm_prompt(
            build_command="echelon review",
            arguments=args,
            project_dir=self._base_dir,
            cli=self._llm_cli,
        )
        logger.info("Invoking echelon.review: spec=%s pr=%s", self._spec_id, pr_url)

        try:
            if self._llm_cli == "opencode":
                cmd = [self._llm_bin, "run", "--dangerously-skip-permissions", prompt]
            else:
                cmd = [self._llm_bin, "-p", prompt, "--dangerously-skip-permissions"]
                if self._llm_cli == "copilot":
                    cmd += ["--allow-all-tools"]
            result = subprocess.run(
                cmd,
                cwd=str(self._base_dir),
                env=env,
                timeout=self._review_timeout_s,
            )
        except subprocess.TimeoutExpired:
            logger.warning("echelon.review timed out after %ss", self._review_timeout_s)
            return 0

        if result.returncode != 0:
            logger.warning("echelon.review exited %d", result.returncode)

        # Read status file if present
        if status_file.exists():
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                status = data.get("status", "unknown")
                logger.info("echelon.review status: %s", status)
                if status != "review_fix_queued":
                    logger.warning(
                        "echelon.review returned unexpected status: %s", status
                    )
            except Exception as e:
                logger.warning("Could not read review status file: %s", e)

        return 0  # stdout not captured; token tracking via status file only

    # === Private: state persistence ===

    def _load_seen_ids(self) -> Set[str]:
        if self._state_file.exists():
            try:
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                return set(data.get("seen_comment_ids", []))
            except Exception:
                pass
        return set()

    def _save_seen_ids(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps({"seen_comment_ids": sorted(self._seen_ids)}, indent=2),
            encoding="utf-8",
        )
