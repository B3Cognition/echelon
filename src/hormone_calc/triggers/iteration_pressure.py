"""F2 — iteration count → adrenaline (current agent).

Band lookup based on iteration/max_squad_iterations ratio. Max defaults to 10
if not present in state.thresholds.max_squad_iterations (matches the
banzai-mode config).
"""
from __future__ import annotations

from hormone_calc.config import DynamicsConfig
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate, Trigger


class IterationPressureTrigger:
    def __init__(self, config: DynamicsConfig):
        self.cfg = config.iteration_pressure

    def detect(self, obs: ObservableState) -> list[Trigger]:
        max_iter = (
            obs.state.get("thresholds", {})
            .get("max_squad_iterations")
            or 10
        )
        if max_iter <= 0:
            return []
        ratio = obs.iteration / max_iter

        delta = 0.0
        for band in self.cfg.bands:
            if ratio < band.upto:
                delta = band.delta
                break
        else:
            # ratio >= all upto values
            delta = self.cfg.bands[-1].delta if self.cfg.bands else 0.0

        if delta > 0:
            return [HormoneUpdate(
                agent=obs.agent, hormone="adrenaline", delta=delta,
            )]
        return []
