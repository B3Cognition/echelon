"""C-category dispatch-chain triggers.

T-PROPAGATE-DOWNSTREAM, T-CORTISOL-CONTAGION, T-PEER-ACCEPT, T-PEER-REJECT
per spec section 3C. All skip when upstream_agent is None.

GATE_AGENTS: agents whose verdict is about the upstream's artifact rather
than their own work. Their PASS/FAIL drives peer_accept/peer_reject.
"""
from __future__ import annotations

from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall, Trigger
from hormone_calc.triggers.verdict import PASS_VERDICTS, FAIL_VERDICTS


GATE_AGENTS = frozenset({
    "SAGE", "CHECKPOINT", "GATEKEEPER", "SPEC_GUARD",
    "CODE_REVIEWER", "TEST_GUARDIAN", "VALIDATOR",
    "GUARDIAN", "MONITOR", "INTEGRATOR",
})

CORTISOL_CONTAGION_THRESHOLD = 0.8


class DispatchChainTrigger:
    def detect(self, obs: ObservableState) -> list[Trigger]:
        upstream = obs.upstream_agent
        if upstream is None:
            return []

        triggers: list[Trigger] = []

        # T-PROPAGATE-DOWNSTREAM — always when upstream present
        triggers.append(HandlerCall(
            name="propagate_downstream", args=(upstream, obs.agent),
        ))

        # T-CORTISOL-CONTAGION — when upstream cortisol > threshold
        upstream_cortisol = (
            obs.state.get("endocrine_state", {})
            .get("agents", {})
            .get(upstream, {})
            .get("hormones", {})
            .get("cortisol")
        )
        if (isinstance(upstream_cortisol, (int, float))
                and upstream_cortisol > CORTISOL_CONTAGION_THRESHOLD):
            triggers.append(HandlerCall(
                name="propagate_cortisol_contagion", args=(upstream, obs.agent),
            ))

        # T-PEER-ACCEPT / T-PEER-REJECT — only for gate agents
        if obs.agent in GATE_AGENTS:
            verdict = (obs.result or {}).get("verdict", "")
            if verdict in PASS_VERDICTS:
                triggers.append(HandlerCall(
                    name="on_peer_accept", args=(upstream, obs.agent),
                ))
            elif verdict in FAIL_VERDICTS:
                triggers.append(HandlerCall(
                    name="on_peer_reject", args=(upstream, obs.agent),
                ))

        return triggers
