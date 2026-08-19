"""Spec-scoped checkpoint CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

from harness.phase_checkpoints import (
    accept_checkpoint_baseline,
    commit_manual_checkpoint,
    load_checkpoint_ledger,
)
from echelon.checkpoint_coverage import (
    CheckpointCoverageError,
    compute_spec_checkpoint_coverage,
)
from echelon.spec_lifecycle import (
    SpecRunAmbiguous,
    SpecRunNotFound,
    resolve_active_spec_run,
    resolve_spec_run,
)


_USAGE = (
    "Usage:\n"
    "  echelon spec checkpoint list [--spec <run-or-spec-id>] [--strict]\n"
    "  echelon spec checkpoint accept --phase <phase-id> [--spec <id>] [--run-id <id>]\n"
    "  echelon spec checkpoint commit --phase <phase-id> [--spec <id>] "
    "[--run-id <id>] [--message <msg>]\n"
    "  echelon spec checkpoint migrate [--spec <run-or-spec-id>] [--confirm]\n"
)


def _parse_checkpoint_args(
    args: list[str],
    subcommand: str,
) -> dict[str, str | bool]:
    value_options = {
        "list": frozenset({"--spec"}),
        "accept": frozenset({"--phase", "--spec", "--run-id"}),
        "commit": frozenset({"--phase", "--spec", "--run-id", "--message"}),
        "migrate": frozenset({"--spec"}),
    }[subcommand]
    flag_options = {
        "list": frozenset({"--strict"}),
        "migrate": frozenset({"--confirm"}),
    }.get(subcommand, frozenset())
    parsed: dict[str, str | bool] = {}
    index = 1
    while index < len(args):
        option = args[index]
        if option in parsed:
            raise ValueError("duplicate checkpoint option")
        if option in flag_options:
            parsed[option] = True
            index += 1
            continue
        if (
            option not in value_options
            or index + 1 >= len(args)
            or args[index + 1].startswith("--")
        ):
            raise ValueError("invalid checkpoint option")
        parsed[option] = args[index + 1]
        index += 2
    return parsed


def _format_checkpoint_created_at(value: str) -> str:
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _manual_boundary_completion_id(state: dict[str, object], phase: str) -> str:
    if state.get("checkpoint_policy_version") != 2:
        return ""
    outcomes = state.get("phase_completion_outcomes")
    if type(outcomes) is not list:
        raise RuntimeError("versioned checkpoint outcomes are invalid")
    for outcome in reversed(outcomes):
        if (
            type(outcome) is dict
            and outcome.get("phase") == phase
            and outcome.get("outcome") == "executed"
            and isinstance(outcome.get("completion_id"), str)
        ):
            return str(outcome["completion_id"])
    raise RuntimeError(f"phase {phase!r} has no executed completion to checkpoint")


def _render_coverage(rows: tuple[object, ...]) -> None:
    print("\nCOVERAGE\n")
    if not rows:
        print("(none)")
        return
    print("COMPLETION                       PHASE                 STATUS              REWIND")
    for row in rows:
        completion_id = getattr(row, "completion_id") or "-"
        print(
            f"{completion_id:<32} "
            f"{getattr(row, 'phase'):<21} "
            f"{getattr(row, 'status'):<19} "
            f"{getattr(row, 'rewind')}"
        )


def run_checkpoint_command(args: list[str], *, project_root: Path) -> None:
    subcommand = args[0] if args else "list"
    if subcommand in {"-h", "--help", "help"}:
        print(_USAGE)
        raise SystemExit(0)
    if subcommand not in {"list", "accept", "commit", "migrate"}:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(1)

    try:
        options = _parse_checkpoint_args(args, subcommand)
    except ValueError:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(1)
    strict = options.get("--strict") is True
    spec = str(options.get("--spec") or "")
    try:
        run = (
            resolve_spec_run(project_root, spec)
            if spec
            else resolve_active_spec_run(project_root)
        )
    except SpecRunAmbiguous as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    except SpecRunNotFound as exc:
        if spec:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        print(
            "No active spec resolved.\n\n"
            "Use:\n"
            "  echelon spec checkpoint list --spec 001",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    spec_dir = run.spec_dir
    try:
        state = json.loads((run.run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read checkpoint run state: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if type(state) is not dict:
        print("Checkpoint run state must be a JSON object.", file=sys.stderr)
        raise SystemExit(1)

    if subcommand == "migrate":
        from echelon.checkpoint_migration import (
            LegacyCheckpointMigrationError,
            apply_legacy_checkpoint_migration,
            prepare_legacy_checkpoint_migration,
        )

        try:
            plan = prepare_legacy_checkpoint_migration(project_root, run)
            print(f"LEGACY CHECKPOINT MIGRATION - run {run.run_dir_name}\n")
            if plan.files:
                print("FILE                         ACTION")
                for item in plan.files:
                    print(f"{item.name:<28} {item.disposition}")
            else:
                print("(no allowlisted staging artifacts)")
            if plan.ignored:
                print("\nIgnored: " + ", ".join(plan.ignored))
            if options.get("--confirm") is not True:
                print(
                    "\nConfirm with:\n  "
                    "echelon spec checkpoint migrate "
                    f"--spec {run.run_dir_name} --confirm"
                )
                return
            checkpoint = apply_legacy_checkpoint_migration(project_root, plan)
        except LegacyCheckpointMigrationError as exc:
            print(f"Cannot migrate legacy checkpoints: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"Migration checkpoint {checkpoint.commit[:7]} recorded.")
        return

    if subcommand == "accept":
        phase = str(options.get("--phase") or "")
        if not phase:
            print("Usage: echelon spec checkpoint accept --phase <phase-id> [--spec <id>]", file=sys.stderr)
            raise SystemExit(1)
        checkpoint = accept_checkpoint_baseline(
            project_root=project_root,
            spec_dir=spec_dir,
            phase=phase,
            run_id=str(options.get("--run-id") or run.run_id),
            boundary_completion_id=_manual_boundary_completion_id(
                state,
                phase,
            ),
        )
        print(f"Accepted checkpoint baseline {checkpoint.id} at {checkpoint.commit[:7]}")
        return

    if subcommand == "commit":
        phase = str(options.get("--phase") or "")
        message = str(
            options.get("--message") or "docs: accept manual Phase A checkpoint"
        )
        if not phase:
            print("Usage: echelon spec checkpoint commit --phase <phase-id> [--spec <id>]", file=sys.stderr)
            raise SystemExit(1)
        checkpoint = commit_manual_checkpoint(
            project_root=project_root,
            spec_dir=spec_dir,
            phase=phase,
            run_id=str(options.get("--run-id") or run.run_id),
            message=message,
            boundary_completion_id=_manual_boundary_completion_id(
                state,
                phase,
            ),
        )
        print(f"Committed checkpoint {checkpoint.id} at {checkpoint.commit[:7]}")
        return

    ledger = load_checkpoint_ledger(spec_dir)
    print(f"CHECKPOINTS - spec {ledger.spec_id}\n")
    if not ledger.checkpoints:
        print("(none)")
    else:
        print(
            "Order: oldest -> newest (ledger order); "
            "phase-only rewind selects the last matching row\n"
        )
        print(
            "ID                       PHASE                 COMMIT      "
            "CREATED UTC          LATEST  SOURCE"
        )
        latest_by_phase = {
            checkpoint.phase: index
            for index, checkpoint in enumerate(ledger.checkpoints)
        }
        for index, checkpoint in enumerate(ledger.checkpoints):
            print(
                f"{checkpoint.id:<24} "
                f"{checkpoint.phase:<21} "
                f"{checkpoint.commit[:7]:<11} "
                f"{_format_checkpoint_created_at(checkpoint.created_at):<20} "
                f"{'yes' if latest_by_phase[checkpoint.phase] == index else '-':<7} "
                f"{checkpoint.source}"
            )
    from harness.phase_graph import load_workspace_phase_graph

    try:
        graph, _ = load_workspace_phase_graph(project_root)
        coverage = compute_spec_checkpoint_coverage(graph, state, ledger)
    except (CheckpointCoverageError, FileNotFoundError) as exc:
        print(f"Could not compute checkpoint coverage: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    _render_coverage(coverage)
    if strict and any(row.status == "missing" for row in coverage):
        raise SystemExit(2)
