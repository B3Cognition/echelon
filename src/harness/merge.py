"""Auto-merge logic with precondition checks.

Per T046 / FR-MERGE-001 / FR-MERGE-002:
- Preconditions: verify passed, converged, mode not guided, N=1 strategy
- N>1 disables auto-merge
- Branch protection failure handled gracefully
"""

from __future__ import annotations

import logging
from typing import Any

from harness.loop_result import LoopResult
from harness.run_intent import RunIntent

logger = logging.getLogger(__name__)


def attempt_auto_merge(
    loop_result: LoopResult,
    intent: RunIntent,
    gitops: Any,
) -> bool:
    """Attempt auto-merge if all preconditions are met.

    Per FR-MERGE-001, all four preconditions must pass:
    1. Verify passed (final_verify.passed = True)
    2. Status = converged
    3. Mode is banzai or semi (never guided)
    4. N=1 strategy (FR-MERGE-002)

    Args:
        loop_result: Result from the ralph-loop.
        intent: Original RunIntent.
        gitops: GitOpsManager instance.

    Returns:
        True if merge succeeded, False otherwise.
    """
    # Check N > 1
    if len(intent.strategies) > 1:
        logger.info(
            "Auto-merge disabled: N=%d strategies active. "
            "Compare PRs and merge manually.",
            len(intent.strategies),
        )
        return False

    # Check mode
    if intent.mode == "guided":
        logger.info("Auto-merge skipped: mode=guided requires human review")
        return False

    # Check status
    if loop_result.status != "converged":
        logger.info(
            "Auto-merge skipped: status=%s (not converged)",
            loop_result.status,
        )
        return False

    # Check verify passed
    if loop_result.final_verify is None or not loop_result.final_verify.passed:
        logger.info("Auto-merge skipped: verify not passed")
        return False

    # Check auto_merge flag
    if not intent.auto_merge:
        logger.info("Auto-merge not requested (auto_merge=false)")
        return False

    # Check PR URL
    if not loop_result.pr_url:
        logger.info("Auto-merge skipped: no PR URL available")
        return False

    # All preconditions met -- attempt merge
    try:
        success = gitops.merge_pr(loop_result.pr_url)
        if success:
            logger.info("Auto-merge succeeded: %s", loop_result.pr_url)
        else:
            logger.warning(
                "Auto-merge failed (branch protection?): %s",
                loop_result.pr_url,
            )
        return success
    except Exception as e:
        logger.warning("Auto-merge error: %s", e)
        return False
