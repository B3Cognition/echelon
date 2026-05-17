"""B-category quality-driven triggers.

T-QUALITY-IMPROVE / T-QUALITY-REGRESS per spec section 3B.
Threshold: delta >= 0.05 in either direction.
"""
from __future__ import annotations

from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall, Trigger


QUALITY_DELTA_THRESHOLD = 0.05


class QualityTrigger:
    def detect(self, obs: ObservableState) -> list[Trigger]:
        series = obs.quality_score_series
        if len(series) < 2:
            return []

        delta = series[-1] - series[-2]
        if delta >= QUALITY_DELTA_THRESHOLD:
            return [HandlerCall(name="on_quality_improvement", args=())]
        elif delta <= -QUALITY_DELTA_THRESHOLD:
            return [HandlerCall(name="on_quality_regression", args=())]
        return []
