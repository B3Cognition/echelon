"""Run skill orchestration entry point.

Per T043: wires RunIntent parsing -> StrategyCoordinator -> terminal output.
Acquires lock, runs GC, launches coordinator, prints results.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict

from harness.config import load_config
from harness.coordinator import StrategyCoordinator
from harness.gc import run_gc
from harness.paths import make_build_id, current_build_marker, runs_dir
from harness.run_intent import parse_intent

logger = logging.getLogger(__name__)


def _count_tasks(spec_id: str, base_dir: str) -> int:
    """Return count of canonical task rows in tasks.md, or 0 if absent."""
    try:
        from harness.task_validation import count_tasks_for_spec
        return count_tasks_for_spec(spec_id, Path(base_dir))
    except FileNotFoundError:
        return 0


def _print_delivery_summary(
    intent: Any,
    result_map: Dict[str, Any],
    comparison: Dict[str, Any],
    base_dir: str,
    config: Any = None,
) -> None:
    """Print a structured delivery summary to stderr."""
    from echelon.ui import banner as _banner

    task_count = _count_tasks(intent.spec_id, base_dir)
    task_note = f"  ({task_count} tasks)" if task_count else ""
    target_repo = getattr(config, "target_repo", None) if config is not None else None

    fields: list[tuple[str, str]] = [("spec", f"{intent.spec_id}{task_note}")]
    if target_repo:
        fields.append(("target", target_repo))
    fields.append(("strategies", f"{', '.join(intent.strategies)}  |  mode: {intent.mode}"))

    for sid, info in comparison.get("strategies", {}).items():
        result = result_map.get(sid)
        converged = info.get("converged", False)
        status_icon = "✓" if converged else "✗"
        status_str = "CONVERGED" if converged else info.get("status", "FAILED").upper()
        outer = info.get("outer_iterations", 0)
        inner = info.get("inner_iterations", 0)
        branch = info.get("branch") or f"harness/{intent.spec_id}/{sid}/iter-{max(outer - 1, 0)}"
        pr_url = info.get("pr_url")

        lines = [
            f"{status_icon} {status_str}",
            f"branch: {branch}",
            f"PR: {pr_url}" if pr_url else "PR: not created (gh/glab unavailable or pr_host unset)",
            f"iterations: {outer} outer, {inner} inner retries",
        ]
        if result is not None:
            reason = getattr(result, "termination_reason", None)
            if reason and reason != "converged":
                lines.append(f"stopped: {reason}")
            fv = getattr(result, "final_verify", None)
            if fv is not None:
                v_icon = "✓" if fv.passed else "✗"
                duration = f"  ({fv.duration_s:.1f}s)" if fv.duration_s else ""
                lines.append(f"verify: {v_icon} {'passed' if fv.passed else 'FAILED'}{duration}")
                for failure in (fv.failures or []):
                    lines.append(f"        ✗ [{failure.category.value}] {failure.error}")
            else:
                lines.append("verify: skipped (no sandbox / project type undetected)")

        fields.append((sid, "\n".join(lines)))

    summary = comparison.get("summary", {})
    n_converged = summary.get("converged", 0)
    n_failed = summary.get("failed", 0)
    total_tokens = summary.get("total_tokens", 0)
    result_str = f"{n_converged} converged, {n_failed} failed"
    if total_tokens:
        result_str += f"  ·  {total_tokens:,} tokens"
    fields.append(("result", result_str))

    _banner("DELIVERY SUMMARY", fields, file=sys.stderr)


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

    # 4. Generate build ID and write .current-build marker
    base_path = Path(base_dir).resolve()
    build_id = make_build_id()
    rd = runs_dir(base_path)
    rd.mkdir(parents=True, exist_ok=True)
    current_build_marker(base_path, intent.spec_id).write_text(build_id)
    logger.info("Build ID: %s", build_id)

    # 5. Create coordinator
    coordinator = StrategyCoordinator(
        provider=provider,
        gitops=gitops,
        config=config,
        base_dir=base_dir,
        build_id=build_id,
    )

    # 6. Run GC before starting
    try:
        run_gc(config, base_dir=base_dir)
    except Exception as e:
        logger.warning("GC failed (continuing): %s", e)

    # 7. Launch coordinator
    results = coordinator.start(intent)

    # 8. Print results
    result_map = dict(zip(intent.strategies, results))
    comparison = coordinator.compare_results(result_map)

    _print_delivery_summary(intent, result_map, comparison, base_dir, config)

    # 9. Auto-land if applicable
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
