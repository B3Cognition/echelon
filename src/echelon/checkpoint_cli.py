"""Spec-scoped checkpoint CLI."""

from __future__ import annotations

from pathlib import Path

from harness.phase_checkpoints import load_checkpoint_ledger


def _find_spec_dir(project_root: Path, spec: str) -> Path | None:
    specs_dir = project_root / "specs"
    if not specs_dir.exists():
        return None
    matches = sorted(
        path for path in specs_dir.iterdir() if path.is_dir() and path.name.startswith(spec)
    )
    return matches[0] if matches else None


def _arg_value(args: list[str], name: str) -> str:
    if name not in args:
        return ""
    idx = args.index(name)
    if idx + 1 >= len(args):
        return ""
    return args[idx + 1]


def run_checkpoint_command(args: list[str], *, project_root: Path) -> None:
    subcommand = args[0] if args else "list"
    if subcommand not in {"list", "show"}:
        print("Usage: echelon checkpoint list [--spec <id>]")
        return

    spec = _arg_value(args, "--spec")
    if not spec:
        print(
            "No active spec resolved.\n\n"
            "Use:\n"
            "  echelon checkpoint list --spec 001\n"
            "  echelon phase list"
        )
        return

    spec_dir = _find_spec_dir(project_root, spec)
    if spec_dir is None:
        print(f"No spec directory found for {spec!r}.")
        return

    ledger = load_checkpoint_ledger(spec_dir)
    print(f"CHECKPOINTS - spec {ledger.spec_id}\n")
    if not ledger.checkpoints:
        print("(none)")
        return

    print("ID                       PHASE                 COMMIT      SOURCE")
    for checkpoint in ledger.checkpoints:
        print(
            f"{checkpoint.id:<24} "
            f"{checkpoint.phase:<21} "
            f"{checkpoint.commit[:7]:<11} "
            f"{checkpoint.source}"
        )
