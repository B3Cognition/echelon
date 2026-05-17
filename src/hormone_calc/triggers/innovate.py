"""T-INNOVATE-SUMMON — fires on_innovate_summon when MAVERICK is dispatched."""
from __future__ import annotations

from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall, Trigger


class InnovateTrigger:
    def detect(self, obs: ObservableState) -> list[Trigger]:
        if obs.agent == "MAVERICK":
            return [HandlerCall(name="on_innovate_summon", args=())]
        return []
