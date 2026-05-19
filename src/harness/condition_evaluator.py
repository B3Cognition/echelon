"""ConditionEvaluator — evaluates workflow/definition.yaml transition conditions."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from harness.squad_provider import SquadAgentResult


class ConditionEvaluator:
    """Evaluates condition strings from definition.yaml transitions against state.json.

    Returns True/False for known conditions, None for unrecognised ones.
    None triggers COMMANDER judgment dispatch.
    """

    def evaluate(
        self,
        condition: str,
        state: dict,
        result: "Optional[SquadAgentResult]" = None,
    ) -> Optional[bool]:
        condition = condition.strip()

        if condition == "always":
            return True

        # Compound: split AND before OR (AND binds tighter)
        if re.search(r"\bAND\b", condition):
            parts = re.split(r"\bAND\b", condition)
            sub = [self.evaluate(p.strip(), state, result) for p in parts]
            if None in sub:
                return None
            return all(sub)

        if re.search(r"\bOR\b", condition):
            parts = re.split(r"\bOR\b", condition)
            sub = [self.evaluate(p.strip(), state, result) for p in parts]
            if all(s is None for s in sub):
                return None
            if None in sub:
                return None  # conservative: unknown sub-condition → COMMANDER
            return any(sub)

        # verdict = X — checks result.verdict
        m = re.fullmatch(r"verdict\s*=\s*(\S+)", condition)
        if m:
            if result is None:
                return False
            return result.verdict == m.group(1)

        # field in [v1, v2, ...]
        m = re.fullmatch(r"([\w.\-]+)\s+in\s+\[([^\]]+)\]", condition)
        if m:
            field, values_str = m.group(1), m.group(2)
            values = [v.strip() for v in values_str.split(",")]
            return str(self._get(state, field, "")) in values

        # field >= value  /  field <= value  /  field > value  /  field < value
        # (both operands are field names — look them up in state)
        m = re.fullmatch(r"([\w.\-]+)\s*(>=|<=|>|<)\s*([\w.\-]+)", condition)
        if m:
            left_field, op, right_field = m.group(1), m.group(2), m.group(3)
            left_val = self._get(state, left_field)
            right_val = self._get(state, right_field)
            if left_val is None or right_val is None:
                return False
            try:
                fv, ref = float(left_val), float(right_val)
            except (TypeError, ValueError):
                return None
            return {
                ">=": fv >= ref,
                "<=": fv <= ref,
                ">": fv > ref,
                "<": fv < ref,
            }[op]

        # field = value  (string/dash-notation field names like "why3-verdict")
        m = re.fullmatch(r"([\w.\-]+)\s*=\s*(.+)", condition)
        if m:
            field, expected = m.group(1).strip(), m.group(2).strip()
            return str(self._get(state, field, "")) == expected

        # bare boolean field  e.g. "convergence_detected", "quality_gates.pass"
        if re.fullmatch(r"[\w.\-]+", condition):
            val = self._get(state, condition)
            if val is not None:
                return bool(val)

        return None  # unrecognised → COMMANDER judgment

    def _get(self, state: dict, field: str, default=None):
        """Read a dotted-path field from state dict.

        Special derived fields:
          quality_gates.pass  — latest quality_scores entry's pass flag
          quality_gates.fail  — negation of quality_gates.pass
          CRITICAL_issues     — True when quality_scores[-1].pass is False
          no_CRITICAL_issues  — negation of CRITICAL_issues
        """
        # Derived: quality_gates.pass / quality_gates.fail
        # Prefer quality_scores[-1].pass when available (agents write here).
        # Fall back to direct state["quality_gates"]["pass"] traversal so
        # tests and interactive COMMANDER writes remain compatible.
        if field == "quality_gates.pass":
            scores = state.get("quality_scores") or []
            if scores:
                return bool(scores[-1].get("pass"))
            # fall through to normal dotted-path

        if field == "quality_gates.fail":
            scores = state.get("quality_scores") or []
            if scores:
                return not bool(scores[-1].get("pass"))
            # fall through to normal dotted-path

        # Derived: CRITICAL_issues / no_CRITICAL_issues
        # Agents write issues to journal entries (not state_updates), so derive
        # from quality_scores[-1].pass: fail → CRITICAL issues present.
        if field == "CRITICAL_issues":
            # Explicit issues_log takes priority when populated
            issues = state.get("issues_log") or []
            if issues:
                return any(
                    (i.get("severity") or "").upper() == "CRITICAL"
                    for i in issues
                )
            scores = state.get("quality_scores") or []
            if scores:
                return not bool(scores[-1].get("pass"))
            return default

        if field == "no_CRITICAL_issues":
            critical = self._get(state, "CRITICAL_issues")
            if critical is None:
                return default
            return not critical

        # Normal dotted-path traversal
        parts = field.split(".")
        val: object = state
        for p in parts:
            if not isinstance(val, dict):
                return default
            val = val.get(p)
            if val is None:
                return default
        return val
