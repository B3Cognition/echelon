"""Thin parser and terminal presenter for ``echelon spec switch``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import TextIO

from echelon.spec_switch import (
    DirtySpecWorktreeError,
    SpecSwitchError,
    SpecSwitchOutcome,
    switch_spec,
)


SPEC_SWITCH_USAGE = (
    "Usage: echelon spec switch <spec-or-run-id> "
    "[--stash | --discard --confirm] [--restore-stash]"
)


class SpecSwitchCliError(ValueError):
    """Raised when command-line switch options are unsafe or malformed."""


@dataclass(frozen=True)
class SpecSwitchOptions:
    identity: str
    dirty_action: str
    confirm_discard: bool
    restore_stash: bool


def parse_spec_switch_args(args: list[str]) -> SpecSwitchOptions:
    """Parse the explicit, non-provider spec-switch option contract."""

    identity = ""
    stash = False
    discard = False
    confirm = False
    restore = False
    for arg in args:
        if arg == "--stash":
            stash = True
        elif arg == "--discard":
            discard = True
        elif arg == "--confirm":
            confirm = True
        elif arg == "--restore-stash":
            restore = True
        elif arg.startswith("-"):
            raise SpecSwitchCliError(f"unknown option: {arg}")
        elif not identity:
            identity = arg.strip()
        else:
            raise SpecSwitchCliError(f"unexpected argument: {arg}")

    if not identity:
        raise SpecSwitchCliError("spec switch requires a spec or run identity")
    if stash and discard:
        raise SpecSwitchCliError("--stash and --discard are mutually exclusive")
    if discard and not confirm:
        raise SpecSwitchCliError("--discard requires --confirm")
    if confirm and not discard:
        raise SpecSwitchCliError("--confirm requires --discard")
    return SpecSwitchOptions(
        identity=identity,
        dirty_action="stash" if stash else "discard" if discard else "refuse",
        confirm_discard=confirm,
        restore_stash=restore,
    )


def _print_dirty_paths(paths: tuple[str, ...], stream: TextIO) -> None:
    stream.write("Dirty worktree paths:\n")
    for path in paths:
        stream.write(f"  - {path}\n")


def _print_outcome(outcome: SpecSwitchOutcome, stream: TextIO) -> None:
    stream.write("Spec switch complete\n")
    stream.write(f"  source      {outcome.source.run_dir_name}\n")
    stream.write(f"  target      {outcome.target.run_dir_name}\n")
    stream.write(f"  branch      {outcome.target.feature_branch}\n")
    stream.write(
        f"  checkpoint  {outcome.target_checkpoint.checkpoint_id} "
        f"({outcome.target_checkpoint.commit[:7]})\n"
    )
    stream.write(f"  action      {outcome.action}\n")
    if outcome.stash_commit:
        stream.write(f"  stash       stored {outcome.stash_commit[:7]}\n")
    if outcome.restored_stash_commit:
        stream.write(
            f"  stash       restored {outcome.restored_stash_commit[:7]}\n"
        )
    stream.write("  next        echelon spec status\n")


def _run_switch(options: SpecSwitchOptions, project_root: Path) -> SpecSwitchOutcome:
    return switch_spec(
        project_root,
        options.identity,
        dirty_action=options.dirty_action,
        confirm_discard=options.confirm_discard,
        restore_stash=options.restore_stash,
    )


def _interactive_dirty_action(
    options: SpecSwitchOptions,
    error: DirtySpecWorktreeError,
    *,
    stdin: TextIO,
    stdout: TextIO,
) -> SpecSwitchOptions | None:
    _print_dirty_paths(error.paths, stdout)
    stdout.write("[s] Stash changes and switch\n")
    stdout.write("[d] Discard changes back to the checkpoint\n")
    stdout.write("[c] Cancel (default)\n")
    stdout.write("Choice [c]: ")
    choice = stdin.readline().strip().lower()
    if choice == "s":
        return SpecSwitchOptions(
            options.identity,
            "stash",
            False,
            options.restore_stash,
        )
    if choice == "d":
        stdout.write("Discard all Git-visible changes back to the checkpoint? [y/N] ")
        confirmed = stdin.readline().strip().lower() in {"y", "yes"}
        if confirmed:
            return SpecSwitchOptions(
                options.identity,
                "discard",
                True,
                options.restore_stash,
            )
    stdout.write("Spec switch cancelled.\n")
    return None


def run_spec_switch_command(
    args: list[str],
    *,
    project_root: Path,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run the deterministic switch command and return a process-style code."""

    if any(arg in {"-h", "--help"} for arg in args):
        stdout.write(SPEC_SWITCH_USAGE + "\n")
        return 0
    try:
        options = parse_spec_switch_args(args)
    except SpecSwitchCliError as exc:
        stderr.write(f"echelon spec switch: {exc}\n{SPEC_SWITCH_USAGE}\n")
        return 1

    root = Path(project_root).resolve()
    try:
        outcome = _run_switch(options, root)
    except DirtySpecWorktreeError as exc:
        interactive = stdin.isatty() and stdout.isatty()
        if options.dirty_action == "refuse" and interactive:
            selected = _interactive_dirty_action(
                options,
                exc,
                stdin=stdin,
                stdout=stdout,
            )
            if selected is None:
                return 1
            try:
                outcome = _run_switch(selected, root)
            except SpecSwitchError as retry_exc:
                stderr.write(f"echelon spec switch: {retry_exc}\n")
                return 1
        else:
            stderr.write(f"echelon spec switch: {exc}\n")
            _print_dirty_paths(exc.paths, stderr)
            stderr.write(
                f"Retry with: echelon spec switch {options.identity} --stash\n"
                f"Or discard: echelon spec switch {options.identity} "
                "--discard --confirm\n"
            )
            return 1
    except SpecSwitchError as exc:
        stderr.write(f"echelon spec switch: {exc}\n")
        return 1

    _print_outcome(outcome, stdout)
    return 0
