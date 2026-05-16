"""F1 — budget pressure → adrenaline (current agent).

Band lookup: find the smallest band.upto > ratio; that band's delta applies.
At ratio >= 0.95 (critical band), additionally emit a BroadcastAdrenaline.

Bands and critical_broadcast value come from DynamicsConfig (config-driven).
"""
from __future__ import annotations

from hormone_calc.config import DynamicsConfig
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate, BroadcastAdrenaline, Trigger


class BudgetPressureTrigger:
    def __init__(self, config: DynamicsConfig):
        self.cfg = config.budget_pressure

    def detect(self, obs: ObservableState) -> list[Trigger]:
        ratio = obs.token_ratio
        delta = self._lookup_band_delta(ratio)
        triggers: list[Trigger] = []
        if delta > 0:
            triggers.append(HormoneUpdate(
                agent=obs.agent, hormone="adrenaline", delta=delta,
            ))
        # Critical broadcast: ratio in the highest band (>= 0.95 in defaults)
        critical_threshold = self._critical_threshold()
        if ratio >= critical_threshold and self.cfg.critical_broadcast > 0:
            triggers.append(BroadcastAdrenaline(delta=self.cfg.critical_broadcast))
        return triggers

    def _lookup_band_delta(self, ratio: float) -> float:
        """Find the band whose [previous_upto, upto) contains ratio."""
        for band in self.cfg.bands:
            if ratio < band.upto:
                return band.delta
        # Ratio >= all upto values → use the last band's delta (catches ratio==1.00)
        return self.cfg.bands[-1].delta if self.cfg.bands else 0.0

    def _critical_threshold(self) -> float:
        """The lower bound of the last (critical) band."""
        if len(self.cfg.bands) < 2:
            return 1.0  # no critical band defined
        return self.cfg.bands[-2].upto
