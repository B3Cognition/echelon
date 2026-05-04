"""evaluator.py — Typed transition evaluator for Echelon COMMANDER.

Implements evaluate_transitions() per contracts/evaluator-contract.md.

Supports 16-predicate inventory (predicates 15 and 16 raise PredicateNotDefined
until canonical definitions are added — ADR-001 caveat).

Supports AND/OR combinators, nesting depth <= 1.
First-match-wins.
Pure function — no I/O, no journal writes, no state mutations.
Budget: <= 500ms per call (FR-STATE-003).

Routing boundary: On encountering a `preflight: true` node,
evaluate_transitions returns guard_result: SKIPPED_PREFLIGHT_NODE immediately
(T011/T018 PLAN2 clarification).
"""

from __future__ import annotations

import re
import time
from typing import Any, Literal

from kernel.accessors import (
    get_autonomy_mode,
    get_checkpoint_approved,
    get_config_assess_defer_limit,
    get_config_consecutive_passes,
    get_config_guardian_mode,
    get_config_max_iterations,
    get_config_quality_delta_threshold,
    get_config_quality_gates,
    get_critical_issues,
    get_defer_count,
    get_iteration,
    get_last_outputs_verdict,
    get_last_quality_scores,
    get_mode,
    get_quality_scores_window,
)


# ---------------------------------------------------------------------------
# TypedDicts
# ---------------------------------------------------------------------------


class EvaluatorTraceEntry(dict):
    """Trace entry for a single predicate evaluation."""
    # Keys: sub_term (str), fields_read (list[str]), observed_values (dict), result (str)


class EvaluatorResult(dict):
    """Return type of evaluate_transitions.
    Keys: next_phase, next_agent, matched_transition_index, actions, guard_result, trace, errors
    """


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PredicateNotDefined(Exception):
    """Raised when a predicate's canonical definition has not yet been added."""
    def __init__(self, predicate_name: str) -> None:
        self.predicate_name = predicate_name
        super().__init__(
            f"PredicateNotDefined: '{predicate_name}' has no canonical definition yet "
            f"(ADR-001 caveat — add definition before using in production)"
        )


class UnknownPredicate(Exception):
    """Raised at schema-load time for predicates not in the 16-predicate inventory."""
    def __init__(self, predicate_text: str) -> None:
        self.predicate_text = predicate_text
        super().__init__(f"UnknownPredicate: '{predicate_text}' is not in the predicate inventory")


# ---------------------------------------------------------------------------
# Predicate evaluators (one per predicate in the inventory)
# ---------------------------------------------------------------------------


def _eval_always(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 1: always — constant true."""
    return True, [], {}


def _eval_quality_gates_pass(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 2: quality_gates.pass — numeric branch."""
    fields_read = ["quality_scores[-1]", "config.quality_gates"]
    last = get_last_quality_scores(state)
    gates = get_config_quality_gates(config)
    observed: dict[str, Any] = {"last_scores": last, "gates": gates}

    if last is None or gates is None:
        return False, fields_read, observed

    # Check each gate dimension
    spec_gates = gates.get("spec", {}) if isinstance(gates, dict) else {}
    for dim, threshold in spec_gates.items():
        if isinstance(threshold, (int, float)):
            score = last.get(dim)
            if score is None or score < threshold:
                observed["failed_dim"] = dim
                observed["score"] = score
                observed["threshold"] = threshold
                return False, fields_read, observed

    return True, fields_read, observed


def _eval_quality_gates_fail(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 3: quality_gates.fail — negation of quality_gates.pass."""
    passed, fields_read, observed = _eval_quality_gates_pass(state, config, last_outputs, args)
    return not passed, fields_read, observed


def _eval_convergence_detected(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 4: convergence_detected — delta check over window."""
    delta_threshold = get_config_quality_delta_threshold(config)
    consec_passes = get_config_consecutive_passes(config)
    fields_read = [
        "quality_scores[-N:]", "config.convergence.quality_delta_threshold",
        "config.convergence.consecutive_passes_required"
    ]
    observed: dict[str, Any] = {
        "delta_threshold": delta_threshold,
        "consecutive_passes_required": consec_passes,
    }

    if delta_threshold is None or consec_passes is None:
        return False, fields_read, observed

    window_size = consec_passes + 1
    window = get_quality_scores_window(state, window_size)
    observed["window_size"] = window_size
    observed["window_length"] = len(window) if window else 0

    if not window or len(window) < 2:
        return False, fields_read, observed

    # Check if last consec_passes deltas are all < delta_threshold
    overalls = [entry.get("overall", 0.0) for entry in window if isinstance(entry, dict)]
    if len(overalls) < 2:
        return False, fields_read, observed

    deltas = [abs(overalls[i] - overalls[i - 1]) for i in range(1, len(overalls))]
    observed["deltas"] = deltas

    # All recent deltas must be below threshold
    if all(d < delta_threshold for d in deltas[-(consec_passes):]):
        return True, fields_read, observed

    return False, fields_read, observed


def _eval_critical_issues(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 5: CRITICAL_issues — any unresolved CRITICAL issues."""
    fields_read = ["issues_log[*].severity", "issues_log[*].resolved"]
    critical = get_critical_issues(state)
    observed: dict[str, Any] = {"critical_count": len(critical)}
    return len(critical) > 0, fields_read, observed


def _eval_no_critical_issues(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 6: no_CRITICAL_issues — negation of CRITICAL_issues."""
    result, fields_read, observed = _eval_critical_issues(state, config, last_outputs, args)
    return not result, fields_read, observed


def _eval_iteration_lt_max(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 7: iteration < max_iterations."""
    fields_read = ["iteration", "config.convergence.max_iterations"]
    iteration = get_iteration(state)
    max_iter = get_config_max_iterations(config)
    observed: dict[str, Any] = {"iteration": iteration, "max_iterations": max_iter}
    if iteration is None or max_iter is None:
        return False, fields_read, observed
    return iteration < max_iter, fields_read, observed


def _eval_iteration_gte_max(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 8: iteration >= max_iterations."""
    result, fields_read, observed = _eval_iteration_lt_max(state, config, last_outputs, args)
    return not result, fields_read, observed


def _eval_verdict_eq(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 9: verdict = <value>."""
    expected = args.get("value", "")
    fields_read = ["last_outputs.verdict"]
    verdict = get_last_outputs_verdict(last_outputs)
    observed: dict[str, Any] = {"verdict": verdict, "expected": expected}
    if verdict is None:
        return False, fields_read, observed
    return verdict == expected, fields_read, observed


def _eval_defer_count_gte_limit(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 10: defer_count >= assess_defer_loop_limit."""
    fields_read = ["defer_count", "config.convergence.assess_defer_loop_limit"]
    defer = get_defer_count(state)
    limit = get_config_assess_defer_limit(config)
    observed: dict[str, Any] = {"defer_count": defer, "limit": limit}
    if defer is None or limit is None:
        return False, fields_read, observed
    return defer >= limit, fields_read, observed


def _eval_autonomy_in(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 11: autonomy in [guided, semi, banzai]."""
    allowed = args.get("values", ["guided", "semi", "banzai"])
    fields_read = ["autonomy_mode"]
    mode = get_autonomy_mode(state)
    observed: dict[str, Any] = {"autonomy_mode": mode, "allowed": allowed}
    if mode is None:
        return False, fields_read, observed
    return mode in allowed, fields_read, observed


def _eval_human_approved(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 12: human_approved."""
    checkpoint = args.get("checkpoint", "")
    fields_read = [f"checkpoint_responses[{checkpoint!r}].approved"]
    approved = get_checkpoint_approved(state, checkpoint)
    observed: dict[str, Any] = {"checkpoint": checkpoint, "approved": approved}
    if approved is None:
        return False, fields_read, observed
    return bool(approved), fields_read, observed


def _eval_mode_eq(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 13: mode = <value>."""
    expected = args.get("value", "brownfield")
    fields_read = ["mode"]
    mode = get_mode(state)
    observed: dict[str, Any] = {"mode": mode, "expected": expected}
    if mode is None:
        return False, fields_read, observed
    return mode == expected, fields_read, observed


def _eval_guardian_mode_eq(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 14: guardian_mode = always_on."""
    expected = args.get("value", "always_on")
    fields_read = ["config.specialists.guardian_mode", "config.guardian_mode"]
    gmode = get_config_guardian_mode(config)
    observed: dict[str, Any] = {"guardian_mode": gmode, "expected": expected}
    if gmode is None:
        return False, fields_read, observed
    return gmode == expected, fields_read, observed


def _eval_stagnation_detected(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 15: stagnation_detected — NOT YET DEFINED (ADR-001 caveat)."""
    raise PredicateNotDefined("stagnation_detected")


def _eval_unknown_territory(
    state: dict, config: dict, last_outputs: dict, args: dict
) -> tuple[bool, list[str], dict[str, Any]]:
    """Predicate 16: unknown_territory — NOT YET DEFINED (ADR-001 caveat)."""
    raise PredicateNotDefined("unknown_territory")


# ---------------------------------------------------------------------------
# Predicate registry
# ---------------------------------------------------------------------------

# Pattern → (handler, arg_extractor)
_PREDICATE_HANDLERS: dict = {
    "always": _eval_always,
    "quality_gates.pass": _eval_quality_gates_pass,
    "quality_gates.fail": _eval_quality_gates_fail,
    "convergence_detected": _eval_convergence_detected,
    "CRITICAL_issues": _eval_critical_issues,
    "no_CRITICAL_issues": _eval_no_critical_issues,
    "iteration < max_iterations": _eval_iteration_lt_max,
    "iteration >= max_iterations": _eval_iteration_gte_max,
    "defer_count >= assess_defer_loop_limit": _eval_defer_count_gte_limit,
    "human_approved": _eval_human_approved,
    "stagnation_detected": _eval_stagnation_detected,
    "unknown_territory": _eval_unknown_territory,
}

# Regex patterns for parameterized predicates
_VERDICT_RE = re.compile(r'^verdict\s*=\s*(\S+)$')
_AUTONOMY_RE = re.compile(r'^autonomy\s+in\s+\[(.+)\]$')
_MODE_RE = re.compile(r'^mode\s*=\s*(\S+)$')
_GUARDIAN_MODE_RE = re.compile(r'^guardian_mode\s*=\s*(\S+)$')


def _parse_predicate(
    condition: str,
    state: dict,
    config: dict,
    last_outputs: dict,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Parse and evaluate a single atomic predicate string.

    Returns (bool_result, fields_read, observed_values).
    Raises PredicateNotDefined for predicates 15/16.
    Raises UnknownPredicate for unknown conditions.
    """
    cond = condition.strip()

    # Direct match
    if cond in _PREDICATE_HANDLERS:
        return _PREDICATE_HANDLERS[cond](state, config, last_outputs, {})

    # Parameterized: verdict = <value>
    m = _VERDICT_RE.match(cond)
    if m:
        return _eval_verdict_eq(state, config, last_outputs, {"value": m.group(1)})

    # Parameterized: autonomy in [a, b, c]
    m = _AUTONOMY_RE.match(cond)
    if m:
        values = [v.strip() for v in m.group(1).split(",")]
        return _eval_autonomy_in(state, config, last_outputs, {"values": values})

    # Parameterized: mode = <value>
    m = _MODE_RE.match(cond)
    if m:
        return _eval_mode_eq(state, config, last_outputs, {"value": m.group(1)})

    # Parameterized: guardian_mode = <value>
    m = _GUARDIAN_MODE_RE.match(cond)
    if m:
        return _eval_guardian_mode_eq(state, config, last_outputs, {"value": m.group(1)})

    raise UnknownPredicate(cond)


# ---------------------------------------------------------------------------
# Combinator evaluator (AND / OR, depth <= 1)
# ---------------------------------------------------------------------------


def _eval_combinator(
    combinator: str,
    sub_conditions: list[str],
    state: dict,
    config: dict,
    last_outputs: dict,
) -> tuple[bool, list[EvaluatorTraceEntry]]:
    """Evaluate AND/OR combinator over sub_conditions (depth <= 1)."""
    trace_entries: list[EvaluatorTraceEntry] = []
    results: list[bool] = []

    for sub_cond in sub_conditions:
        sub_cond = sub_cond.strip()
        try:
            bool_result, fields_read, observed = _parse_predicate(sub_cond, state, config, last_outputs)
            result_str: str = "true" if bool_result else "false"
        except Exception:
            bool_result = False
            fields_read = []
            observed = {}
            result_str = "undefined"

        entry: EvaluatorTraceEntry = EvaluatorTraceEntry(
            sub_term=sub_cond,
            fields_read=fields_read,
            observed_values=observed,
            result=result_str,
        )
        trace_entries.append(entry)
        results.append(bool_result)

    if combinator == "AND":
        return all(results), trace_entries
    elif combinator == "OR":
        return any(results), trace_entries
    else:
        return False, trace_entries


# ---------------------------------------------------------------------------
# Condition string parser
# ---------------------------------------------------------------------------

_AND_RE = re.compile(r'\bAND\b', re.IGNORECASE)
_OR_RE = re.compile(r'\bOR\b', re.IGNORECASE)


def _eval_condition(
    condition: str,
    state: dict,
    config: dict,
    last_outputs: dict,
) -> tuple[bool, list[EvaluatorTraceEntry]]:
    """Evaluate a condition string (atomic or AND/OR combinator, depth <= 1)."""
    cond = condition.strip()

    # Check for AND combinator (higher precedence than OR per depth-1 contract)
    if _AND_RE.search(cond):
        parts = _AND_RE.split(cond)
        combined, trace = _eval_combinator("AND", parts, state, config, last_outputs)
        return combined, trace

    if _OR_RE.search(cond):
        parts = _OR_RE.split(cond)
        combined, trace = _eval_combinator("OR", parts, state, config, last_outputs)
        return combined, trace

    # Atomic predicate
    try:
        bool_result, fields_read, observed = _parse_predicate(cond, state, config, last_outputs)
        result_str = "true" if bool_result else "false"
    except (PredicateNotDefined, UnknownPredicate):
        raise
    except Exception:
        bool_result = False
        fields_read = []
        observed = {}
        result_str = "undefined"

    entry: EvaluatorTraceEntry = EvaluatorTraceEntry(
        sub_term=cond,
        fields_read=fields_read,
        observed_values=observed,
        result=result_str,
    )
    return bool_result, [entry]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_transitions(
    phase_id: str,
    state: dict,
    config: dict,
    last_outputs: dict,
    definition: dict | None = None,
) -> EvaluatorResult:
    """Evaluate outgoing transitions for a phase node.

    Args:
        phase_id:    Node id from definition.yaml (e.g., 'phase1-what').
        state:       Schema-validated state.json dict.
        config:      echelon-config.yml dict.
        last_outputs: Last agent's echelon_result dict.
        definition:  Parsed definition.yaml dict (optional). When None,
                     the caller must supply transitions via a different means.
                     This parameter is accepted for forward-compatibility but
                     the primary path is for callers to look up the node first
                     and pass the transitions list.

    Returns:
        EvaluatorResult dict.
    """
    _t_start = time.monotonic()

    # --- Preflight node routing boundary (T011/T018 PLAN2 clarification) ---
    if definition is not None:
        phases = definition.get("phases", [])
        # Handle both list and dict forms
        if isinstance(phases, list):
            node = next((p for p in phases if isinstance(p, dict) and p.get("id") == phase_id), None)
        elif isinstance(phases, dict):
            node = phases.get(phase_id)
        else:
            node = None

        if node is not None and node.get("preflight", False):
            return EvaluatorResult(
                next_phase=None,
                next_agent=None,
                matched_transition_index=None,
                actions=[],
                guard_result="SKIPPED_PREFLIGHT_NODE",
                trace=[],
                errors=[f"preflight_node_skipped: {phase_id} is a preflight node — route via preflight.run_preflight()"],
            )

    # --- Resolve transitions from definition ---
    transitions: list[dict] = []
    if definition is not None:
        phases = definition.get("phases", [])
        if isinstance(phases, list):
            node = next((p for p in phases if isinstance(p, dict) and p.get("id") == phase_id), None)
        elif isinstance(phases, dict):
            node = phases.get(phase_id)
        else:
            node = None

        if node is not None:
            transitions = node.get("transitions", [])

    all_trace: list[EvaluatorTraceEntry] = []
    errors: list[str] = []

    # --- Evaluate transitions (first-match-wins) ---
    for idx, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        condition = str(transition.get("condition", "always")).strip()
        _t_before = time.monotonic()

        try:
            matched, trace_entries = _eval_condition(condition, state, config, last_outputs)
        except PredicateNotDefined as exc:
            raise  # loud failure per contract
        except UnknownPredicate as exc:
            errors.append(f"unknown_predicate: {exc.predicate_text}")
            all_trace.append(EvaluatorTraceEntry(
                sub_term=condition,
                fields_read=[],
                observed_values={},
                result="undefined",
            ))
            continue
        except Exception as exc:
            errors.append(f"predicate_error: {condition}: {exc}")
            all_trace.append(EvaluatorTraceEntry(
                sub_term=condition,
                fields_read=[],
                observed_values={},
                result="undefined",
            ))
            continue

        all_trace.extend(trace_entries)

        if matched:
            return EvaluatorResult(
                next_phase=transition.get("to"),
                next_agent=transition.get("agent"),
                matched_transition_index=idx,
                actions=transition.get("actions", []),
                guard_result="PASS",
                trace=all_trace,
                errors=errors,
            )

    # --- No transition matched ---
    errors.append("no_transition_matched")
    return EvaluatorResult(
        next_phase=None,
        next_agent=None,
        matched_transition_index=None,
        actions=[],
        guard_result="FAIL",
        trace=all_trace,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Convenience: evaluate a raw transitions list (without full definition.yaml)
# ---------------------------------------------------------------------------


def evaluate_transitions_list(
    transitions: list[dict],
    state: dict,
    config: dict,
    last_outputs: dict,
) -> EvaluatorResult:
    """Evaluate a transitions list directly (no definition.yaml lookup needed).

    This is the primary API for COMMANDER's inline usage and for tests.
    """
    all_trace: list[EvaluatorTraceEntry] = []
    errors: list[str] = []

    for idx, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        condition = str(transition.get("condition", "always")).strip()

        try:
            matched, trace_entries = _eval_condition(condition, state, config, last_outputs)
        except PredicateNotDefined:
            raise
        except UnknownPredicate as exc:
            errors.append(f"unknown_predicate: {exc.predicate_text}")
            all_trace.append(EvaluatorTraceEntry(
                sub_term=condition, fields_read=[], observed_values={}, result="undefined"
            ))
            continue
        except Exception as exc:
            errors.append(f"predicate_error: {condition}: {exc}")
            all_trace.append(EvaluatorTraceEntry(
                sub_term=condition, fields_read=[], observed_values={}, result="undefined"
            ))
            continue

        all_trace.extend(trace_entries)

        if matched:
            return EvaluatorResult(
                next_phase=transition.get("to"),
                next_agent=transition.get("agent"),
                matched_transition_index=idx,
                actions=transition.get("actions", []),
                guard_result="PASS",
                trace=all_trace,
                errors=errors,
            )

    errors.append("no_transition_matched")
    return EvaluatorResult(
        next_phase=None,
        next_agent=None,
        matched_transition_index=None,
        actions=[],
        guard_result="FAIL",
        trace=all_trace,
        errors=errors,
    )
