"""F3 — task complexity → norepinephrine (current agent).

complexity = clamp(archetype_base[archetype] + agent_bump.get(agent, 0), 0, 1)
delta = (complexity - 0.5) * multiplier

If delta == 0, no emission. Otherwise HormoneUpdate(agent, "norepinephrine", delta).
"""
from __future__ import annotations

from hormone_calc.config import DynamicsConfig
from hormone_calc.observable import ObservableState
from hormone_calc.output import HormoneUpdate, Trigger


class TaskComplexityTrigger:
    def __init__(self, config: DynamicsConfig):
        self.cfg = config.task_complexity

    def detect(self, obs: ObservableState) -> list[Trigger]:
        base = self.cfg.archetype_base.get(obs.archetype, 0.0)
        bump = self.cfg.agent_bump.get(obs.agent, 0.0)
        complexity = max(0.0, min(1.0, base + bump))

        delta = (complexity - 0.5) * self.cfg.multiplier
        # Round to 10 decimal places to avoid floating-point precision artifacts
        delta = round(delta, 10)
        if delta == 0.0:
            return []
        return [HormoneUpdate(agent=obs.agent, hormone="norepinephrine", delta=delta)]
