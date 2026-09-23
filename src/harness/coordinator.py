"""Temporary test bridge while callers move to the single controller."""

from typing import Any, Mapping

from harness.delivery_controller import DeliveryController
from harness.delivery_results import DeliveryResult


class StrategyCoordinator(DeliveryController):
    """Compatibility adapter with no fan-out or strategy selection."""

    def __init__(
        self,
        *args: Any,
        fresh_branch_bases: Mapping[str, str] | None = None,
        fresh_completed_task_ids: Mapping[str, tuple[str, ...]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            *args,
            fresh_branch_base=(fresh_branch_bases or {}).get("default"),
            fresh_completed_task_ids=(fresh_completed_task_ids or {}).get(
                "default", ()
            ),
            **kwargs,
        )

    def start(self, intent: Any) -> list[DeliveryResult]:
        return [self.run(intent)]

    def status(self) -> dict[str, object]:
        state = self.state()
        return {
            "active_loops": int(
                state.get("status") in {"running", "blocked", "initialized"}
            ),
            "strategies": {"default": state} if state else {},
        }

    def compare_results(
        self, results: Mapping[str, DeliveryResult]
    ) -> dict[str, object]:
        result = results.get("default")
        if result is None:
            return {"strategies": {}, "summary": {"converged": 0, "failed": 0, "total_tokens": 0}}
        state = self.state()
        return {
            "strategies": {
                "default": {
                    "status": result.status,
                    "termination_reason": result.termination_reason,
                    "outer_iterations": result.outer_iterations,
                    "inner_iterations": result.inner_iterations,
                    "tokens_used": result.tokens_used,
                    "pr_url": result.pr_url,
                    "branch": result.branch,
                    "converged": result.status == "converged",
                    **state,
                }
            },
            "summary": {
                "converged": int(result.status == "converged"),
                "failed": int(result.status != "converged"),
                "total_tokens": result.tokens_used,
            },
        }


__all__ = ["DeliveryController", "StrategyCoordinator"]
