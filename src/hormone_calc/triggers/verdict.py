"""A-category verdict-driven triggers.

T-GATE-PASS, T-GATE-FAIL, T-REWORK, T-LOW-CONFIDENCE per spec section 3A.
Verdict normalization sets are defined here as constants.
"""
from __future__ import annotations

from hormone_calc.observable import ObservableState
from hormone_calc.output import HandlerCall, Trigger


PASS_VERDICTS = frozenset({"PASS", "APPROVED", "DONE", "COMPLETE", "STABLE"})
FAIL_VERDICTS = frozenset({"FAIL", "CHANGES_REQUESTED", "REJECTED", "KILL", "INSTABILITY"})
SOFT_FAIL_VERDICTS = frozenset({"DONE_WITH_CONCERNS", "DEFER", "NEEDS_CONTEXT", "BLOCKED"})


class VerdictTrigger:
    def detect(self, obs: ObservableState) -> list[Trigger]:
        triggers: list[Trigger] = []
        verdict = (obs.result or {}).get("verdict", "")

        # T-GATE-PASS / T-GATE-FAIL
        if verdict in PASS_VERDICTS:
            triggers.append(HandlerCall(name="on_gate_pass", args=(obs.agent,)))
        elif verdict in FAIL_VERDICTS:
            triggers.append(HandlerCall(name="on_gate_fail", args=(obs.agent,)))

        # T-REWORK — same agent had non-PASS verdict prior + current also non-PASS
        if (verdict not in PASS_VERDICTS
                and obs.prior_verdict_for_agent is not None
                and obs.prior_verdict_for_agent not in PASS_VERDICTS):
            triggers.append(HandlerCall(name="on_rework", args=(obs.agent,)))

        # T-LOW-CONFIDENCE — explicit low confidence OR soft-fail verdict
        confidence = ((obs.result or {}).get("data") or {}).get("confidence")
        if (
            (isinstance(confidence, (int, float)) and confidence < 0.5)
            or verdict in SOFT_FAIL_VERDICTS
        ):
            triggers.append(HandlerCall(name="on_low_confidence", args=(obs.agent,)))

        return triggers
