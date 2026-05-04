#!/usr/bin/env python3
"""evaluate_transition.py — CLI wrapper for kernel/evaluator.py.

Usage:
    python evaluate_transition.py \
        --state <state_json_path> \
        --transitions <transitions_json> \
        [--config <config_yaml_path>] \
        [--last-outputs <json_string>]

Reads state.json and transitions JSON, calls evaluate_transitions_list,
outputs EvaluatorResult as JSON to stdout.

Exit codes:
    0 — guard_result == PASS
    1 — guard_result == FAIL or UNDEFINED
    2 — error (schema violation, file not found, etc.)

See contracts/evaluator-contract.md § Interface.
"""

import argparse
import json
import sys
from pathlib import Path

# Ensure kernel is importable
SCRIPT_DIR = Path(__file__).resolve().parent
EXT_DIR = SCRIPT_DIR.parent.parent
if str(EXT_DIR) not in sys.path:
    sys.path.insert(0, str(EXT_DIR))

from kernel.evaluator import PredicateNotDefined, evaluate_transitions_list
from kernel.state_loader import StateLoadError, load


def _load_config(config_path: str) -> dict:
    """Load echelon-config.yml or return minimal defaults."""
    if not config_path:
        return {
            "convergence": {
                "max_iterations": 5,
                "quality_delta_threshold": 0.02,
                "consecutive_passes_required": 2,
                "assess_defer_loop_limit": 2,
            },
            "quality_gates": {"spec": {"overall": 0.7}},
            "specialists": {"guardian_mode": "always_on"},
        }
    path = Path(config_path)
    if not path.exists():
        print(f"ERROR: config file not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        import yaml  # type: ignore
        with path.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if not isinstance(cfg, dict):
            print(f"ERROR: config must be a YAML dict", file=sys.stderr)
            sys.exit(2)
        return cfg
    except ImportError:
        print("WARNING: PyYAML not available — using minimal config defaults", file=sys.stderr)
        return {}
    except Exception as exc:
        print(f"ERROR loading config: {exc}", file=sys.stderr)
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CLI wrapper for evaluate_transitions. Outputs EvaluatorResult JSON."
    )
    parser.add_argument("--state", required=True, help="Path to state.json")
    parser.add_argument("--transitions", required=True, help="JSON array of transition objects")
    parser.add_argument("--config", default="", help="Path to echelon-config.yml (optional)")
    parser.add_argument("--last-outputs", default="{}", help="JSON string of last agent outputs (optional)")
    args = parser.parse_args()

    # Load state
    result = load(args.state, strict=False)
    if isinstance(result, StateLoadError):
        error_out = {
            "guard_result": "FAIL",
            "errors": [f"state_load_error: {result.code}: {result.message}"],
            "next_phase": None,
            "next_agent": None,
            "matched_transition_index": None,
            "actions": [],
            "trace": [],
        }
        print(json.dumps(error_out))
        return 2
    state = result

    # Load config
    config = _load_config(args.config)

    # Parse transitions
    try:
        transitions = json.loads(args.transitions)
        if not isinstance(transitions, list):
            raise ValueError("transitions must be a JSON array")
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR parsing transitions: {exc}", file=sys.stderr)
        return 2

    # Parse last_outputs
    try:
        last_outputs = json.loads(args.last_outputs)
        if not isinstance(last_outputs, dict):
            last_outputs = {}
    except json.JSONDecodeError:
        last_outputs = {}

    # Evaluate
    try:
        eval_result = evaluate_transitions_list(transitions, state, config, last_outputs)
    except PredicateNotDefined as exc:
        error_out = {
            "guard_result": "FAIL",
            "errors": [f"predicate_not_defined: {exc.predicate_name}"],
            "next_phase": None,
            "next_agent": None,
            "matched_transition_index": None,
            "actions": [],
            "trace": [],
        }
        print(json.dumps(error_out))
        return 2

    # Output result
    print(json.dumps(eval_result, indent=2))

    # Exit code
    guard_result = eval_result.get("guard_result", "FAIL")
    if guard_result == "PASS":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
