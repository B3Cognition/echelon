"""Run skill orchestration entry point.

Per T043: wires RunIntent parsing -> StrategyCoordinator -> terminal output.
Acquires lock, runs GC, launches coordinator, prints results.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from harness.config import load_config
from harness.coordinator import StrategyCoordinator
from harness.gc import run_gc
from harness.merge import attempt_auto_merge
from harness.run_intent import parse_intent
from harness.state import StateStore

logger = logging.getLogger(__name__)


def run(
    user_message: str,
    provider: Any,
    gitops: Any,
    base_dir: str = ".",
) -> None:
    """Execute /speckit-harness-run skill.

    Args:
        user_message: Natural-language run request.
        provider: SandboxProvider instance.
        gitops: GitOpsManager instance.
        base_dir: Base directory for harness state.
    """
    # 1. Parse intent
    intent = parse_intent(user_message)
    logger.info("Parsed run intent: spec=%s, mode=%s, strategies=%s",
                intent.spec_id, intent.mode, intent.strategies)

    # 2. Load config
    config = load_config()

    # 3. Ensure project is on the default branch before any git operations.
    # echelon.run/bugfix may leave the working directory on a feature branch.
    # Stash any local changes and switch back so mirror worktrees can be
    # created cleanly.
    try:
        gitops.ensure_on_default_branch(base_dir)
    except Exception as e:
        logger.warning("ensure_on_default_branch failed (continuing): %s", e)

    # 4. Create coordinator
    coordinator = StrategyCoordinator(
        provider=provider,
        gitops=gitops,
        config=config,
        base_dir=base_dir,
    )

    # 5. Run GC before starting
    try:
        run_gc(config, base_dir=base_dir)
    except Exception as e:
        logger.warning("GC failed (continuing): %s", e)

    # 6. Launch coordinator
    results = coordinator.start(intent)

    # 7. Print results
    result_map = dict(zip(intent.strategies, results))
    comparison = coordinator.compare_results(result_map)

    print("\n--- RESULTS ---", file=sys.stderr)
    for sid, info in comparison.get("strategies", {}).items():
        status_str = "CONVERGED" if info["converged"] else info["status"].upper()
        print(f"  {sid}: {status_str} | "
              f"iterations: {info['outer_iterations']} outer, {info['inner_iterations']} inner | "
              f"tokens: {info['tokens_used']}",
              file=sys.stderr)
        if info.get("pr_url"):
            print(f"    PR: {info['pr_url']}", file=sys.stderr)

    summary = comparison.get("summary", {})
    print(f"\n  Total: {summary.get('converged', 0)} converged, "
          f"{summary.get('failed', 0)} failed, "
          f"{summary.get('total_tokens', 0)} tokens",
          file=sys.stderr)

    # 8. Auto-merge if applicable
    if intent.auto_merge and len(results) == 1:
        merged = attempt_auto_merge(results[0], intent, gitops)
        if merged:
            print("  Auto-merged successfully!", file=sys.stderr)
