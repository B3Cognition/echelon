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
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from harness.config import HarnessConfig
from harness.llm_provider import AICodingCliProvider
from harness.paths import build_dir as _build_dir_fn
from harness.delivery_results import ReviewResult
from harness.review_artifacts import (
    PublishedReviewBatch,
    ReviewArtifactError,
    ReviewArtifactPublisher,
    ReviewAllocation,
)

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
_REVIEW_AGENT_NAMES = (
    "echelon-debugger",
    "echelon-sentinel",
    "echelon-spec-guard",
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


@dataclass(frozen=True)
class _ReviewSkillResult:
    """Outcome of one review-planning skill invocation."""

    tokens_used: int
    queued: bool
    queued_task_ids: tuple[str, ...] = ()
    published_artifacts: tuple[Path, ...] = ()
    attempt_id: str | None = None
    reason: str = "review_staging_failed"


def _normalized_review_input(
    comments: List[ReviewComment],
    adjacent_line_threshold: int,
) -> str:
    """Return the complete, host-supplied comment payload for review triage."""
    payload = {
        "adjacent_line_threshold": adjacent_line_threshold,
        "comments": [
            {
                "comment_id": comment.comment_id,
                "reviewer": comment.reviewer,
                "body": comment.body,
                "path": comment.path,
                "line": comment.line,
                "timestamp": comment.created_at.isoformat(),
            }
            for comment in comments
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _load_review_agents(worktree: Path) -> dict[str, dict[str, object]]:
    """Load exactly the fixed read-only diagnostic agents from a worktree."""
    agents: dict[str, dict[str, object]] = {}
    for name in _REVIEW_AGENT_NAMES:
        prompt = _read_review_agent(worktree, name).strip()
        if not prompt:
            raise ReviewArtifactError(f"required review agent is empty: {name}")
        agents[name] = {
            "description": f"Read-only review triage: {name}",
            "prompt": prompt,
            "tools": ["Read"],
        }
    return agents


def _read_review_agent(worktree: Path, name: str) -> str:
    """Read one agent without allowing a symlink race to escape the worktree."""
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    fds: list[int] = []
    try:
        root_fd = _open_directory_chain(worktree, flags | directory | nofollow)
        fds.append(root_fd)
        claude_fd = os.open(".claude", flags | directory | nofollow, dir_fd=root_fd)
        fds.append(claude_fd)
        agents_fd = os.open("agents", flags | directory | nofollow, dir_fd=claude_fd)
        fds.append(agents_fd)
        agent_fd = os.open(f"{name}.md", flags | nofollow, dir_fd=agents_fd)
        fds.append(agent_fd)
        if not stat.S_ISREG(os.fstat(agent_fd).st_mode):
            raise ReviewArtifactError(f"required review agent is missing or unsafe: {name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(agent_fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewArtifactError(
            f"required review agent is missing or unsafe: {name}"
        ) from exc
    finally:
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                pass


def _open_directory_chain(path: Path, flags: int) -> int:
    """Open every directory component by descriptor, anchored at a trusted root."""
    raw = os.fspath(path)
    if os.path.isabs(raw):
        current_fd = os.open(os.path.sep, flags)
        components = Path(raw).parts[1:]
    else:
        current_fd = os.open(".", flags)
        components = Path(raw).parts
    try:
        for component in components:
            if component in {"", ".", ".."}:
                raise OSError("unsafe review-agent directory component")
            next_fd = os.open(component, flags, dir_fd=current_fd)
            try:
                if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                    raise OSError("review-agent component is not a directory")
            except Exception:
                os.close(next_fd)
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


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


def _find_review_spec_dir(base_dir: Path, spec_id: str) -> Path | None:
    matches = sorted(base_dir.glob(f"specs/{spec_id}-*"))
    return matches[0] if matches else None


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
        build_id: str = "",
        spec_dir: str | Path | None = None,
    ) -> None:
        self._gitops = gitops
        self._config = config
        self._rl = config.review_loop
        self._spec_id = spec_id
        self._strategy_id = strategy_id
        self._base_dir = Path(base_dir).resolve()
        self._spec_dir = (
            Path(spec_dir).resolve() if spec_dir is not None else None
        )
        self._pr_host = config.pr_host

        # Resolve LLM CLI binary — ECHELON_LLM env var takes precedence over config
        _cli = os.environ.get("ECHELON_LLM", config.llm.cli)
        self._llm_cli = _cli
        self._review_timeout_s = 1_200.0  # 20 min per review skill invocation

        # Persistent state: tracks which comment IDs we've already acted on
        self._state_file = (
            _build_dir_fn(self._base_dir, build_id) / "state"
            / f"{strategy_id}-review.json"
        )
        self._status_file = self._state_file.with_name(
            f"{strategy_id}-review-status.json"
        )
        self._seen_state_error = False
        try:
            self._seen_ids = self._load_seen_ids()
        except (OSError, ValueError):
            self._seen_ids = set()
            self._seen_state_error = True
        self.queued_task_ids: tuple[str, ...] = ()
        self.published_artifacts: tuple[Path, ...] = ()
        self._published_batch: PublishedReviewBatch | None = None
        self.pending_batch_attempt_id: str | None = None

    # === Public entry point ===

    def run_loop(
        self,
        pr_url: str,
        worktree_path: str,
        token_budget: Optional[int] = None,
    ) -> ReviewResult:
        """Poll for review comments, fix, push, re-request, repeat until merged.

        Each call performs one poll cycle. Returns:
          "review_fix_queued" — new echelon.review tasks written; coordinator
                                should re-run Phase 1 then call run_loop again.
          "completed"         — PR merged.
          "blocked"           — max iterations reached or unrecoverable error.
        """
        tokens_used = 0
        last_comment_time = self._load_last_comment_time()

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
                    return ReviewResult(
                        status="completed" if merged else "blocked",
                        termination_reason="converged" if merged else "blocker_escalation",
                        iterations=iteration + 1,
                        pr_url=pr_url,
                        tokens_used=tokens_used,
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
                self._save_last_comment_time(last_comment_time)

            invocation = self._invoke_review_skill(
                pr_url,
                comments,
                worktree_path=worktree_path,
            )
            tokens_used += invocation.tokens_used
            if not invocation.queued:
                if (
                    self._published_batch is not None
                    and self._published_batch.status == "no_blocking_comments"
                ):
                    continue
                return ReviewResult(
                    status="blocked",
                    termination_reason=invocation.reason,
                    iterations=iteration + 1,
                    pr_url=pr_url,
                    tokens_used=tokens_used,
                )

            # Signal coordinator to re-run Phase 1 with the new tasks
            return ReviewResult(
                status="review_fix_queued",
                termination_reason="review_fix_queued",
                iterations=iteration + 1,
                pr_url=pr_url,
                tokens_used=tokens_used,
            )

        logger.warning(
            "Review loop hit max_fix_iterations=%d for %s — escalating",
            self._rl.max_fix_iterations, pr_url,
        )
        return ReviewResult(
            status="blocked",
            termination_reason="blocker_escalation",
            iterations=self._rl.max_fix_iterations,
            pr_url=pr_url,
            tokens_used=tokens_used,
        )

    def _plan_and_publish_review(
        self,
        pr_url: str,
        comments: List[ReviewComment],
        *,
        worktree_path: str,
    ) -> _ReviewSkillResult:
        """Stage, validate, and publish review output before any PR mutation."""
        delivery_worktree = Path(worktree_path).resolve() if worktree_path else None
        spec_dir = self._spec_dir or _find_review_spec_dir(self._base_dir, self._spec_id)
        if (
            delivery_worktree is None
            or not delivery_worktree.is_dir()
            or spec_dir is None
            or not spec_dir.is_dir()
        ):
            return _ReviewSkillResult(tokens_used=0, queued=False)

        state_dir = self._state_file.parent
        if self._seen_state_error:
            return _ReviewSkillResult(
                tokens_used=0, queued=False, reason="review_staging_failed"
            )
        try:
            with ReviewArtifactPublisher(spec_dir, state_dir, self._strategy_id) as publisher:
                batch = publisher.recover_publication(self._seen_ids)
                self._published_batch = batch
                tokens_used = 0
                if batch is None:
                    self._published_batch = None
                    allocation = publisher.allocate(tuple(c.comment_id for c in comments))
                    invocation = self._invoke_staged_review_skill(
                        pr_url,
                        comments,
                        worktree_path=str(delivery_worktree),
                        spec_dir=spec_dir,
                        allocation=allocation,
                        publisher=publisher,
                    )
                    tokens_used = invocation.tokens_used
                    batch = self._published_batch
                    if batch is None:
                        return invocation

                if batch.status != "review_fix_queued":
                    for comment_id in batch.comment_ids:
                        self._seen_ids.add(comment_id)
                    self._save_seen_ids()
                    return _ReviewSkillResult(tokens_used=tokens_used, queued=False)

                self._record_pending_batch(batch)
                self.pending_batch_attempt_id = batch.attempt_id
                self.queued_task_ids = batch.task_ids
                self.published_artifacts = batch.artifact_paths
                return _ReviewSkillResult(
                    tokens_used=tokens_used,
                    queued=True,
                    queued_task_ids=batch.task_ids,
                    published_artifacts=batch.artifact_paths,
                    attempt_id=batch.attempt_id,
                    reason="review_fix_queued",
                )
        except (ReviewArtifactError, OSError, ValueError) as exc:
            logger.warning("Review artifact publication blocked: %s", exc)
            return _ReviewSkillResult(
                tokens_used=0,
                queued=False,
                reason="review_staging_failed",
            )

    def complete_published_batch(self, pr_url: str, attempt_id: str) -> bool:
        """Finish durable PR side effects, then consume an already-published batch."""
        spec_dir = self._spec_dir or _find_review_spec_dir(self._base_dir, self._spec_id)
        if spec_dir is None:
            return False
        try:
            with ReviewArtifactPublisher(
                spec_dir, self._state_file.parent, self._strategy_id
            ) as publisher:
                batch = publisher.recover_publication(set())
                pending = self._pending_batch_state(attempt_id)
                if batch is None:
                    return self._pending_effects_complete(pending)
                if batch.attempt_id != attempt_id:
                    return False
                if pending is None:
                    self._record_pending_batch(batch)
                    pending = self._pending_batch_state(attempt_id)
                if pending is None:
                    return False
                resolved = set(pending.get("resolved_comment_ids", []))
                if self._rl.resolve_threads:
                    for comment_id in batch.comment_ids:
                        if comment_id in resolved:
                            continue
                        if not self._resolve_thread(pr_url, comment_id):
                            return False
                        resolved.add(comment_id)
                        pending["resolved_comment_ids"] = sorted(resolved)
                        self._save_pending_batch(attempt_id, pending)
                if not pending.get("review_requested", False):
                    if not self._request_review(pr_url):
                        return False
                    pending["review_requested"] = True
                    self._save_pending_batch(attempt_id, pending)
                for comment_id in batch.comment_ids:
                    self._seen_ids.add(comment_id)
                self._save_seen_ids()
                publisher.mark_consumed(batch.attempt_id)
                return True
        except (ReviewArtifactError, OSError, ValueError) as exc:
            logger.warning("Review side effects remain pending: %s", exc)
            return False

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

    def _request_review(self, pr_url: str) -> bool:
        """Re-request review from config.review_loop.reviewers."""
        if not self._rl.reviewers:
            return True
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return False
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
            return True
        except Exception as e:
            logger.warning("Failed to request review on %s: %s", pr_url, e)
            return False

    def _resolve_thread(self, pr_url: str, comment_id: str) -> bool:
        """Mark a review thread as resolved after its fix is committed.

        Posts a "Resolved" reply to the comment thread (REST API).
        Attempts GraphQL thread resolution for GitHub; logs warning on failure
        since it requires the thread ID which must be fetched separately.
        """
        ref = _parse_pr_url(pr_url, self._pr_host)
        if ref is None:
            return False

        if ref.host == "github":
            return self._resolve_github_thread(ref, comment_id)
        return self._resolve_gitlab_thread(ref, comment_id)

    def _resolve_github_thread(self, ref: _PrRef, comment_id: str) -> bool:
        repo = f"{ref.owner}/{ref.repo}"

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
            return True
        except Exception as e:
            logger.warning(
                "GraphQL thread resolution failed for comment %s: %s — "
                "reply was posted but checkbox not checked",
                comment_id, e,
            )
            return False

    def _resolve_gitlab_thread(self, ref: _PrRef, comment_id: str) -> bool:
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
            return True
        except Exception as e:
            logger.warning(
                "Failed to resolve GitLab discussion for note %s: %s",
                comment_id, e,
            )
            return False

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
        *,
        worktree_path: str = "",
    ) -> _ReviewSkillResult:
        """Run a complete staged review attempt for the supplied host comments."""
        return self._plan_and_publish_review(
            pr_url,
            comments,
            worktree_path=worktree_path,
        )

    def _invoke_staged_review_skill(
        self,
        pr_url: str,
        comments: List[ReviewComment],
        *,
        worktree_path: str = "",
        spec_dir: Path | None = None,
        allocation: ReviewAllocation | None = None,
        publisher: ReviewArtifactPublisher | None = None,
    ) -> _ReviewSkillResult:
        """Invoke echelon.review via the configured AI coding CLI.

        Writes HARNESS_BUILD_STATUS_FILE, waits for skill completion,
        reads the status file to confirm review-fix tasks were queued.

        Returns the token estimate and whether canonical fix tasks were queued.
        """
        delivery_worktree = Path(worktree_path).resolve() if worktree_path else None
        if delivery_worktree is None or not delivery_worktree.is_dir():
            logger.error(
                "Cannot invoke echelon.review without a live delivery worktree"
            )
            return _ReviewSkillResult(tokens_used=0, queued=False)

        canonical_spec_dir = spec_dir or self._spec_dir or _find_review_spec_dir(
            self._base_dir, self._spec_id
        )
        if canonical_spec_dir is None or allocation is None or publisher is None:
            logger.error("Cannot invoke echelon.review without staged publication allocation")
            return _ReviewSkillResult(tokens_used=0, queued=False)
        try:
            review_agents = _load_review_agents(delivery_worktree)
        except (OSError, ReviewArtifactError) as exc:
            logger.warning("Cannot load review agents: %s", exc)
            return _ReviewSkillResult(tokens_used=0, queued=False)

        from harness.skill_loader import find_skill, resolve_llm_prompt
        args = f"{self._spec_id} pr_url={pr_url}"
        args += f" spec_dir={canonical_spec_dir}"
        args += f" worktree={delivery_worktree}"
        args += f" review_staging_dir={allocation.attempt_dir}"
        args += f" review_status_file={allocation.status_file}"
        args += " review_artifacts=" + json.dumps(list(allocation.artifact_names))
        args += " review_task_ids=" + json.dumps(list(allocation.task_ids))
        prompt_root = delivery_worktree
        if find_skill("echelon.review", delivery_worktree, self._llm_cli) is None:
            prompt_root = self._base_dir
        prompt = resolve_llm_prompt(
            build_command="echelon review",
            arguments=args,
            project_dir=prompt_root,
            cli=self._llm_cli,
        )
        prompt += (
            "\n\n## Harness Review Input\n\n```json\n"
            + _normalized_review_input(comments, self._rl.adjacent_line_threshold)
            + "\n```\n"
        )
        logger.info("Invoking echelon.review: spec=%s pr=%s", self._spec_id, pr_url)

        try:
            result = AICodingCliProvider(self._config).run_prompt_result(
                str(delivery_worktree),
                prompt,
                extra_env={"HARNESS_BUILD_STATUS_FILE": str(allocation.status_file)},
                timeout_ms=int(self._review_timeout_s * 1000),
                request_metadata={
                    "execution_profile": "review_triage_v1",
                    "prompt_metadata": {
                        "tool_read_roots": [str(delivery_worktree), str(canonical_spec_dir)],
                        "tool_write_paths": [
                            *(str(allocation.attempt_dir / name) for name in allocation.artifact_names),
                            str(allocation.attempt_dir / "tasks-append.md"),
                            str(allocation.status_file),
                        ],
                        "review_agents": review_agents,
                    },
                },
            )
        except Exception as exc:
            logger.warning("echelon.review provider failed: %s", exc)
            return _ReviewSkillResult(
                tokens_used=0, queued=False, reason="review_provider_failed"
            )
        if result.timed_out:
            logger.warning("echelon.review timed out after %ss", self._review_timeout_s)
            return _ReviewSkillResult(
                tokens_used=0, queued=False, reason="review_provider_failed"
            )

        tokens_used = max(1, len(result.stdout.encode("utf-8")) // 4)
        if result.exit_code != 0:
            logger.warning("echelon.review exited %d", result.exit_code)
            return _ReviewSkillResult(
                tokens_used=tokens_used, queued=False, reason="review_provider_failed"
            )

        try:
            batch = publisher.accept_manifest(allocation.status_file)
        except ReviewArtifactError as exc:
            logger.warning("echelon.review staged output is invalid: %s", exc)
            return _ReviewSkillResult(tokens_used=tokens_used, queued=False)
        self._published_batch = batch
        queued = batch.status == "review_fix_queued"
        return _ReviewSkillResult(
            tokens_used=tokens_used,
            queued=queued,
            queued_task_ids=batch.task_ids,
            published_artifacts=batch.artifact_paths,
            attempt_id=batch.attempt_id,
            reason="review_fix_queued" if queued else "review_no_blocking_comments",
        )

    # === Private: state persistence ===

    def _load_seen_ids(self) -> Set[str]:
        if self._state_file.exists():
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            seen_ids = data.get("seen_comment_ids", [])
            if not isinstance(seen_ids, list) or not all(
                isinstance(comment_id, str) for comment_id in seen_ids
            ):
                raise OSError("review seen-ID state is invalid")
            return set(seen_ids)
        return set()

    def _save_seen_ids(self) -> None:
        state = self._load_review_state()
        state["seen_comment_ids"] = sorted(self._seen_ids)
        self._write_review_state(state)

    def _load_last_comment_time(self) -> Optional[datetime]:
        value = self._load_review_state().get("last_blocking_comment_at")
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)

    def _save_last_comment_time(self, value: datetime) -> None:
        state = self._load_review_state()
        state["last_blocking_comment_at"] = value.astimezone(timezone.utc).isoformat()
        self._write_review_state(state)

    def _record_pending_batch(self, batch: PublishedReviewBatch) -> None:
        state = self._load_review_state()
        pending = state.setdefault("pending_batches", {})
        if not isinstance(pending, dict):
            raise OSError("review pending-batch state is invalid")
        pending.setdefault(
            batch.attempt_id,
            {
                "comment_ids": list(batch.comment_ids),
                "resolved_comment_ids": [],
                "review_requested": False,
            },
        )
        self._write_review_state(state)

    def _pending_batch_state(self, attempt_id: str) -> dict[str, object] | None:
        state = self._load_review_state()
        pending = state.get("pending_batches")
        if not isinstance(pending, dict):
            return None
        item = pending.get(attempt_id)
        return item if isinstance(item, dict) else None

    def _save_pending_batch(self, attempt_id: str, item: dict[str, object]) -> None:
        state = self._load_review_state()
        pending = state.setdefault("pending_batches", {})
        if not isinstance(pending, dict):
            raise OSError("review pending-batch state is invalid")
        pending[attempt_id] = item
        self._write_review_state(state)

    def _pending_effects_complete(self, item: dict[str, object] | None) -> bool:
        if item is None or item.get("review_requested") is not True:
            return False
        comment_ids = item.get("comment_ids")
        resolved = item.get("resolved_comment_ids")
        if not isinstance(comment_ids, list) or not isinstance(resolved, list):
            return False
        return (not self._rl.resolve_threads) or set(comment_ids).issubset(resolved)

    def _load_review_state(self) -> dict[str, object]:
        if not self._state_file.exists():
            return {}
        data = json.loads(self._state_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise OSError("review state is not an object")
        return data

    def _write_review_state(self, state: dict[str, object]) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(
            dir=self._state_file.parent, prefix=".review-state-", suffix=".tmp"
        )
        temp_path = Path(raw_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._state_file)
            directory_fd = os.open(self._state_file.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
