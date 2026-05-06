"""Run skill orchestration entry point.

Per T043: wires RunIntent parsing -> StrategyCoordinator -> terminal output.
Acquires lock, runs GC, launches coordinator, prints results.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict

from harness.config import load_config
from harness.coordinator import StrategyCoordinator
from harness.gc import run_gc
from harness.run_intent import parse_intent
from harness.state import StateStore

logger = logging.getLogger(__name__)


def _count_tasks(spec_id: str, base_dir: str) -> int:
    """Return count of T-NNN task headings in tasks.md, or 0 if unreadable."""
    try:
        from harness.spec_frontmatter import find_spec_dir
        spec_dir = find_spec_dir(spec_id, Path(base_dir).resolve())
        if spec_dir is None:
            return 0
        tasks_md = spec_dir / "tasks.md"
        if not tasks_md.exists():
            return 0
        text = tasks_md.read_text(encoding="utf-8", errors="replace")
        return len(re.findall(r"^#{1,4}\s+T-\d+", text, re.MULTILINE))
    except Exception:
        return 0


def _print_delivery_summary(
    intent: Any,
    result_map: Dict[str, Any],
    comparison: Dict[str, Any],
    base_dir: str,
    config: Any = None,
) -> None:
    """Print a structured delivery summary to stderr."""
    sep = "=" * 60
    print(f"\n{sep}", file=sys.stderr)
    print("  DELIVERY SUMMARY", file=sys.stderr)
    print(sep, file=sys.stderr)

    # -- Spec / target --
    task_count = _count_tasks(intent.spec_id, base_dir)
    task_note = f"  ({task_count} tasks)" if task_count else ""
    print(f"  Spec:      {intent.spec_id}{task_note}", file=sys.stderr)
    target_repo = getattr(config, "target_repo", None) if config is not None else None
    if target_repo:
        print(f"  Target:    {target_repo}", file=sys.stderr)
    print(f"  Strategy:  {', '.join(intent.strategies)}  |  Mode: {intent.mode}",
          file=sys.stderr)

    # -- Per-strategy outcome --
    print("", file=sys.stderr)
    for sid, info in comparison.get("strategies", {}).items():
        result = result_map.get(sid)
        converged = info.get("converged", False)
        status_icon = "✓" if converged else "✗"
        status_str = "CONVERGED" if converged else info.get("status", "FAILED").upper()
        print(f"  {status_icon} [{sid}]  {status_str}", file=sys.stderr)

        # Branch / PR
        outer = info.get("outer_iterations", 0)
        inner = info.get("inner_iterations", 0)
        branch = f"harness/{intent.spec_id}/{sid}/iter-{max(outer - 1, 0)}"
        print(f"    Branch:     {branch}", file=sys.stderr)
        pr_url = info.get("pr_url")
        if pr_url:
            print(f"    PR:         {pr_url}", file=sys.stderr)
        else:
            print(f"    PR:         not created (gh/glab unavailable or pr_host unset)",
                  file=sys.stderr)

        # Iterations
        print(f"    Iterations: {outer} outer, {inner} inner retries", file=sys.stderr)

        # Termination reason when not clean convergence
        if result is not None:
            reason = getattr(result, "termination_reason", None)
            if reason and reason != "converged":
                print(f"    Stopped:    {reason}", file=sys.stderr)

        # Verification
        if result is not None:
            fv = getattr(result, "final_verify", None)
            if fv is not None:
                v_icon = "✓" if fv.passed else "✗"
                duration = f"  ({fv.duration_s:.1f}s)" if fv.duration_s else ""
                print(f"    Verify:     {v_icon} {'passed' if fv.passed else 'FAILED'}"
                      f"{duration}", file=sys.stderr)
                for failure in (fv.failures or []):
                    print(f"                ✗ [{failure.category.value}] {failure.error}",
                          file=sys.stderr)
            else:
                print(f"    Verify:     skipped (no sandbox / project type undetected)",
                      file=sys.stderr)

    # -- Totals --
    summary = comparison.get("summary", {})
    n_converged = summary.get("converged", 0)
    n_failed = summary.get("failed", 0)
    total_tokens = summary.get("total_tokens", 0)
    print("", file=sys.stderr)
    print(f"  Result:    {n_converged} converged, {n_failed} failed"
          + (f"  |  {total_tokens:,} tokens" if total_tokens else ""),
          file=sys.stderr)
    print(sep, file=sys.stderr)


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

    _print_delivery_summary(intent, result_map, comparison, base_dir, config)

    # 8. Auto-land if applicable
    converged = comparison.get("summary", {}).get("converged", 0) > 0
    if intent.auto_merge and converged:
        from harness.land import land
        try:
            landed = land(intent.spec_id, project_dir=Path(base_dir), gitops=gitops)
            if landed:
                print("  Auto-landed successfully!", file=sys.stderr)
            else:
                logger.warning("auto-land: land() returned False for spec %s", intent.spec_id)
        except Exception as e:
            logger.warning("auto-land: land() raised for spec %s: %s", intent.spec_id, e)
