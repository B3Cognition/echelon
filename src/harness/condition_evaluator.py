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
        """Read a dotted-path field from state dict."""
        parts = field.split(".")
        val: object = state
        for p in parts:
            if not isinstance(val, dict):
                return default
            val = val.get(p)
            if val is None:
                return default
        return val
