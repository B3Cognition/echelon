"""Strict command-line parsing and rendering for ``echelon spec retarget``."""
from __future__ import annotations

from pathlib import Path
import sys

from echelon.spec_retarget import RetargetCommandResult, prepare_spec_retarget


_USAGE = (
    "Usage: echelon spec retarget <spec-id> "
    "--target <source-id-or-path> [--target <source-id-or-path> ...] [--confirm]"
)


def _usage_error(message: str) -> None:
    print(f"✗ echelon spec retarget: {message}\n{_USAGE}", file=sys.stderr)
    raise SystemExit(2)


def _parse_args(args: list[str]) -> tuple[str, tuple[str, ...], bool]:
    if not args or not args[0].strip() or args[0].startswith("-"):
        _usage_error("exactly one active spec selector is required")
    spec_id = args[0].strip()
    targets: list[str] = []
    confirm = False
    index = 1
    while index < len(args):
        token = args[index]
        if token == "--target":
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                _usage_error("--target requires a nonempty source id or path")
            value = args[index + 1].strip()
            if not value:
                _usage_error("--target requires a nonempty source id or path")
            targets.append(value)
            index += 2
            continue
        if token == "--confirm":
            if confirm:
                _usage_error("--confirm may be supplied at most once")
            confirm = True
            index += 1
            continue
        if token == "--init":
            _usage_error("--init is not supported by destructive retarget")
        if token.startswith("-"):
            _usage_error(f"unknown option: {token}")
        _usage_error(f"unexpected positional target or spec selector: {token}")
    if not targets:
        _usage_error("one or more --target values are required")
    return spec_id, tuple(targets), confirm


def _resolved_targets(project_root: Path, raw_targets: tuple[str, ...]) -> tuple[str, ...]:
    from echelon.cli import _resolve_spec_run_implementation_targets

    resolved: list[str] = []
    for raw in raw_targets:
        item = _resolve_spec_run_implementation_targets(
            project_root,
            [raw],
            allow_missing=False,
        )
        if len(item) != 1:
            _usage_error(f"target did not resolve uniquely: {raw}")
        if item[0] in resolved:
            _usage_error(f"duplicate target after normalization: {item[0]}")
        resolved.append(item[0])
    return tuple(resolved)


def _render_preview(result: RetargetCommandResult) -> None:
    print("RETARGET PREVIEW — DESTRUCTIVE TARGET REPLACEMENT")
    print(f"  spec: {result.spec_id}")
    print(f"  baseline run: {result.baseline_run_id}")
    print(f"  old targets: {', '.join(result.old_targets)}")
    print(f"  replacement targets: {', '.join(result.replacement_targets)}")
    baseline_label = (
        "ready to build" if result.baseline_ready_to_build else "Phase A incomplete"
    )
    print(f"  baseline result: {baseline_label}")
    print(f"  invalidated artifacts: {', '.join(result.invalidated_paths) or '(none)'}")
    print("  memory domains: exact selected spec")
    print("  graphs: selected spec and composed workspace graph")
    print(f"  recovery: {result.recovery_command}")
    print("WARNING: --confirm crosses a DESTRUCTIVE boundary and leaves the spec non-buildable until Phase A completes.")


def run_spec_retarget_command(
    args: list[str],
    project_root: Path,
) -> RetargetCommandResult:
    spec_id, raw_targets, confirm = _parse_args(args)
    targets = _resolved_targets(Path(project_root).resolve(), raw_targets)

    def checkpoint_created(checkpoint: object) -> None:
        checkpoint_id = getattr(checkpoint, "id")
        print(f"echelon spec rewind checkpoint:{checkpoint_id} --confirm")
        sys.stdout.flush()

    result = prepare_spec_retarget(
        project_root,
        spec_id,
        targets,
        confirm=confirm,
        checkpoint_created=checkpoint_created if confirm else None,
    )
    if not confirm:
        _render_preview(result)
    return result
