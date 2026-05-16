#!/usr/bin/env python3
"""hormone-calc CLI entry point.

Subcommands:
  compute --agent X --dispatch-id Y --result-file Z [--state path]
          [--journal path] [--config path]
    → emits trigger list to stdout, one per line, space-separated args
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from hormone_calc.config import load as load_config
from hormone_calc.observable import build_from
from hormone_calc.output import serialize
from hormone_calc.upstream import derive_upstream

# Trigger module classes
from hormone_calc.triggers.decay import DecayTrigger
from hormone_calc.triggers.budget_pressure import BudgetPressureTrigger
from hormone_calc.triggers.iteration_pressure import IterationPressureTrigger
from hormone_calc.triggers.task_complexity import TaskComplexityTrigger
from hormone_calc.triggers.dispatch_chain import DispatchChainTrigger
from hormone_calc.triggers.verdict import VerdictTrigger
from hormone_calc.triggers.quality import QualityTrigger
from hormone_calc.triggers.innovate import InnovateTrigger


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="hormone-calc")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compute", help="Compute hormone triggers for a dispatch")
    c.add_argument("--agent", required=True)
    c.add_argument("--dispatch-id", required=True)
    c.add_argument("--result-file", required=True, type=Path)
    c.add_argument("--state", type=Path, default=Path(".specify/squad/state.json"))
    c.add_argument("--journal", type=Path, default=Path(".specify/squad/reasoning-journal.jsonl"))
    c.add_argument("--config", type=Path, default=None,
                   help="Override echelon-config.yml path (else uses default search)")

    return p.parse_args(argv)


def cmd_compute(args: argparse.Namespace) -> int:
    config = load_config(args.config)

    obs = build_from(
        agent=args.agent,
        dispatch_id=args.dispatch_id,
        result_path=args.result_file,
        state_path=args.state,
        journal_path=args.journal,
    )

    # Derive upstream now that we have the observable
    upstream = derive_upstream(obs)
    # Rebuild observable with upstream set (ObservableState is frozen)
    obs = replace(obs, upstream_agent=upstream)

    # Run triggers in spec section 3's prescribed order:
    # 1. Decay
    # 2. F-dynamics (budget, iteration, complexity)
    # 3. C-dispatch-chain
    # 4. A-verdict
    # 5. B-quality
    # 6. D-innovate
    detectors = [
        DecayTrigger(),
        BudgetPressureTrigger(config),
        IterationPressureTrigger(config),
        TaskComplexityTrigger(config),
        DispatchChainTrigger(),
        VerdictTrigger(),
        QualityTrigger(),
        InnovateTrigger(),
    ]
    all_triggers = []
    for d in detectors:
        all_triggers.extend(d.detect(obs))

    print(serialize(all_triggers))
    return 0


def main() -> None:
    args = _parse_args(sys.argv[1:])
    if args.cmd == "compute":
        sys.exit(cmd_compute(args))


if __name__ == "__main__":
    main()
