"""Deterministic helpers for squad quality score routing."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any


QUALITY_GATE_SCORE_KEYS = (
    "overall",
    "structure",
    "testability",
    "semantic",
    "cognitive",
    "readability",
    "depth",
    "behavioral",
)

FAIL_VERDICTS = {"FAIL", "FAILED", "BLOCKED", "REJECTED", "CHANGES_REQUESTED", "KILL"}
PASS_VERDICTS = {
    "PASS",
    "DONE",
    "COMPLETE",
    "APPROVED",
    "VERIFIED",
    "COMPLIANT",
    "ALIGNED",
}


def resolve_quality_gate_thresholds(
    project_root: Path | None,
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve numeric quality gates through the project config cascade."""
    resolved: dict[str, float] = {
        key: float(value)
        for key, value in (defaults or {}).items()
        if key in QUALITY_GATE_SCORE_KEYS and isinstance(value, (int, float))
    }

    if project_root is not None:
        try:
            from harness.config import get_full_resolved_config

            payload = get_full_resolved_config(project_root)
            gates = payload.get("quality_gates")
            if isinstance(gates, dict):
                resolved.update(
                    {
                        key: float(value)
                        for key, value in gates.items()
                        if key in QUALITY_GATE_SCORE_KEYS
                        and isinstance(value, (int, float))
                    }
                )
        except Exception:
            pass

    return resolved


def render_quality_gate_context(gates: dict[str, Any]) -> str:
    """Render the authoritative gate block injected into agent prompts."""
    lines = [
        "## Resolved Quality Gates",
        "These values come from the resolved Echelon project configuration and are authoritative.",
        "Never substitute thresholds copied from agent or phase files.",
    ]
    for key in QUALITY_GATE_SCORE_KEYS:
        value = gates.get(key)
        if isinstance(value, (int, float)):
            lines.append(f"- {key}: >= {value:g}")
    return "\n".join(lines) + "\n\n"


def explicit_quality_pass(score: object) -> bool | None:
    """Return the explicit boolean pass flag, or None when absent/invalid."""
    if not isinstance(score, dict):
        return None
    value = score.get("pass")
    return value if isinstance(value, bool) else None


def derive_quality_pass_from_thresholds(
    score: dict[str, Any],
    gates: dict[str, Any] | None,
) -> bool | None:
    """Derive pass/fail from numeric quality gate thresholds.

    Supports both the runtime config shape (`quality_gates.overall`) and the
    kernel-evaluator shape (`quality_gates.spec.overall`).
    """
    if not isinstance(score, dict) or not isinstance(gates, dict):
        return None
    gate_values = gates.get("spec") if isinstance(gates.get("spec"), dict) else gates
    comparable = [
        (key, gate_values.get(key))
        for key in QUALITY_GATE_SCORE_KEYS
        if isinstance(gate_values.get(key), (int, float))
    ]
    if not comparable:
        return None
    for key, threshold in comparable:
        value = score.get(key)
        if not isinstance(value, (int, float)) or value < threshold:
            return False
    return True


def derive_quality_pass_from_verdict(verdict: str | None) -> bool | None:
    """Map routing verdicts to a quality pass flag when scores cannot."""
    verdict_upper = (verdict or "").upper()
    if verdict_upper in FAIL_VERDICTS:
        return False
    if verdict_upper in PASS_VERDICTS:
        return True
    return None


def normalize_why_quality_scores(
    quality_scores: object,
    *,
    verdict: str | None,
    gates: dict[str, Any] | None,
) -> object:
    """Return a copy with non-boolean WHY pass flags made deterministic.

    If an agent accidentally writes an iteration marker into `pass`, preserve it
    as `pass_id` and replace `pass` with a boolean derived from thresholds or
    verdict. Non-list/non-dict shapes are left untouched for schema validation.
    """
    if not isinstance(quality_scores, list):
        return quality_scores
    normalized = deepcopy(quality_scores)
    for score in normalized:
        if not isinstance(score, dict):
            continue
        if isinstance(score.get("pass"), bool):
            continue
        original = score.get("pass")
        if original is not None and "pass_id" not in score:
            score["pass_id"] = original
        derived = derive_quality_pass_from_thresholds(score, gates)
        if derived is None:
            derived = derive_quality_pass_from_verdict(verdict)
        if derived is not None:
            score["pass"] = derived
    return normalized


def validate_quality_scores_shape(quality_scores: object) -> str | None:
    """Return an error string when a quality_scores update is unsafe."""
    if not isinstance(quality_scores, list):
        return "quality_scores must be a list"
    for idx, score in enumerate(quality_scores):
        if not isinstance(score, dict):
            return f"quality_scores[{idx}] must be an object"
        if "pass" in score and not isinstance(score["pass"], bool):
            return f"quality_scores[{idx}].pass must be a boolean"
    return None
