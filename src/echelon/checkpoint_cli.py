"""Spec-scoped checkpoint CLI."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from harness.phase_checkpoints import (
    accept_checkpoint_baseline,
    commit_manual_checkpoint,
    load_checkpoint_ledger,
)
from harness.spec_frontmatter import find_spec_dir


_USAGE = (
    "Usage:\n"
    "  echelon spec checkpoint list [--spec <id>]\n"
    "  echelon spec checkpoint accept --phase <phase-id> [--spec <id>] [--run-id <id>]\n"
    "  echelon spec checkpoint commit --phase <phase-id> [--spec <id>] "
    "[--run-id <id>] [--message <msg>]\n"
    "\nCompatibility alias: echelon checkpoint ...\n"
)


def _find_spec_dir(project_root: Path, spec: str) -> Path | None:
    return find_spec_dir(spec, project_root)


def _active_run_dir(project_root: Path) -> Path | None:
    for base_dir in (project_root / "runs", project_root / "squad"):
        current_file = base_dir / ".current"
        if current_file.exists():
            run_id = current_file.read_text(encoding="utf-8").strip()
            run_dir = base_dir / run_id
            if run_id and run_dir.exists():
                return run_dir

    candidates: list[Path] = []
    for base_name in ("runs", "squad"):
        base_dir = project_root / base_name
        if not base_dir.exists():
            continue
        candidates.extend(
            path
            for path in base_dir.iterdir()
            if path.is_dir() and not path.name.startswith(".") and (path / "state.json").exists()
        )
    return sorted(candidates, key=lambda path: path.name, reverse=True)[0] if candidates else None


def _canonical_spec_dir_from_ref(project_root: Path, ref: str) -> Path | None:
    if not ref:
        return None
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = project_root / candidate

    if candidate.is_dir():
        return candidate

    parts = candidate.parts
    if "specs" in parts:
        idx = parts.index("specs")
        suffix = Path(*parts[idx:])
        project_candidate = project_root / suffix
        if project_candidate.is_dir():
            return project_candidate

    return None


def _active_spec_dir(project_root: Path) -> Path | None:
    run_dir = _active_run_dir(project_root)
    if run_dir is None:
        return None
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    for key in ("spec_dir", "published_spec_dir"):
        spec_dir = _canonical_spec_dir_from_ref(project_root, str(state.get(key) or "").strip())
        if spec_dir is not None:
            return spec_dir

    spec_id = str(state.get("spec_id") or "").strip()
    return _find_spec_dir(project_root, spec_id) if spec_id else None


def _active_spec_dir_matching(project_root: Path, spec: str) -> Path | None:
    run_dir = _active_run_dir(project_root)
    if run_dir is None:
        return None
    state_path = run_dir / "state.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    state_spec_id = str(state.get("spec_id") or "").strip()
    if state_spec_id and (state_spec_id == spec or state_spec_id.startswith(f"{spec}-")):
        for key in ("spec_dir", "published_spec_dir"):
            spec_dir = _canonical_spec_dir_from_ref(project_root, str(state.get(key) or "").strip())
            if spec_dir is not None:
                return spec_dir

    return None


def _arg_value(args: list[str], name: str) -> str:
    if name not in args:
        return ""
    idx = args.index(name)
    if idx + 1 >= len(args):
        return ""
    return args[idx + 1]


def run_checkpoint_command(args: list[str], *, project_root: Path) -> None:
    subcommand = args[0] if args else "list"
    if subcommand in {"-h", "--help", "help"}:
        print(_USAGE)
        raise SystemExit(0)
    if subcommand not in {"list", "accept", "commit"}:
        print(_USAGE, file=sys.stderr)
        raise SystemExit(1)

    spec = _arg_value(args, "--spec")
    spec_dir = (
        _active_spec_dir_matching(project_root, spec) or _find_spec_dir(project_root, spec)
        if spec
        else _active_spec_dir(project_root)
    )
    if spec_dir is None and not spec:
        print(
            "No active spec resolved.\n\n"
            "Use:\n"
            "  echelon spec checkpoint list --spec 001",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if spec_dir is None:
        print(f"No spec directory found for {spec!r}.", file=sys.stderr)
        raise SystemExit(1)

    if subcommand == "accept":
        phase = _arg_value(args, "--phase")
        if not phase:
            print("Usage: echelon spec checkpoint accept --phase <phase-id> [--spec <id>]", file=sys.stderr)
            raise SystemExit(1)
        checkpoint = accept_checkpoint_baseline(
            project_root=project_root,
            spec_dir=spec_dir,
            phase=phase,
            run_id=_arg_value(args, "--run-id"),
        )
        print(f"Accepted checkpoint baseline {checkpoint.id} at {checkpoint.commit[:7]}")
        return

    if subcommand == "commit":
        phase = _arg_value(args, "--phase")
        message = _arg_value(args, "--message") or "docs: accept manual Phase A checkpoint"
        if not phase:
            print("Usage: echelon spec checkpoint commit --phase <phase-id> [--spec <id>]", file=sys.stderr)
            raise SystemExit(1)
        checkpoint = commit_manual_checkpoint(
            project_root=project_root,
            spec_dir=spec_dir,
            phase=phase,
            run_id=_arg_value(args, "--run-id"),
            message=message,
        )
        print(f"Committed checkpoint {checkpoint.id} at {checkpoint.commit[:7]}")
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
