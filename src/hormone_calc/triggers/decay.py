"""T-DECAY — always-on. Fires decay_hormones for the current agent."""
from __future__ import annotations

from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall, Trigger


class DecayTrigger:
    def detect(self, obs: ObservableState) -> list[Trigger]:
        return [HandlerCall(name="decay_hormones", args=(obs.agent,))]
