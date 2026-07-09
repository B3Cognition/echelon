"""Typer front door for Echelon's user-facing CLI.

This module owns modern command parsing while delegating execution to the
existing handlers in ``echelon.cli``. Keeping the execution layer unchanged lets
Echelon normalize CLI contracts incrementally without rewriting harness logic.
"""

from __future__ import annotations

from typing import Optional

import typer


app = typer.Typer(
    add_completion=False,
    help="Echelon CLI",
    no_args_is_help=True,
)
delivery_app = typer.Typer(
    add_completion=False,
    help="Delivery commands: build, verify, recover, review, and land specs.",
    no_args_is_help=True,
)
delivery_checkpoint_app = typer.Typer(
    add_completion=False,
    help="Delivery checkpoint discovery commands.",
    no_args_is_help=True,
)
harness_app = typer.Typer(
    add_completion=False,
    help="Compatibility alias for delivery init/run/resume.",
    no_args_is_help=True,
)

app.add_typer(delivery_app, name="delivery")
app.add_typer(harness_app, name="harness")
delivery_app.add_typer(delivery_checkpoint_app, name="checkpoint")


def _option_pairs(**values: object) -> list[str]:
    pairs: list[str] = []
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            pairs.append(f"{key}={'true' if value else 'false'}")
        else:
            pairs.append(f"{key}={value}")
    return pairs


def _merge_run_args(
    spec_id: str,
    legacy_args: list[str] | None,
    *,
    mode: str | None,
    strategy: str | None,
    max_outer: int | None,
    max_inner: int | None,
    token_budget: int | None,
    auto_merge: bool | None,
    kill_losers: bool,
    reset: bool,
) -> list[str]:
    args = [spec_id, *(legacy_args or [])]
    args.extend(
        _option_pairs(
            mode=mode,
            strategy=strategy,
            max_outer=max_outer,
            max_inner=max_inner,
            token_budget=token_budget,
            auto_merge=auto_merge,
        )
    )
    if kill_losers:
        args.append("kill_losers=true")
    if reset:
        args.append("--reset")
    return args


def _display_run_args(
    spec_id: str,
    legacy_args: list[str] | None,
    *,
    mode: str | None,
    strategy: str | None,
    max_outer: int | None,
    max_inner: int | None,
    token_budget: int | None,
    auto_merge: bool | None,
    kill_losers: bool,
    reset: bool,
) -> list[str]:
    args = [spec_id, *(legacy_args or [])]
    if mode is not None:
        args.append(f"--mode={mode}")
    if strategy is not None:
        args.append(f"--strategy={strategy}")
    if max_outer is not None:
        args.append(f"--max-outer={max_outer}")
    if max_inner is not None:
        args.append(f"--max-inner={max_inner}")
    if token_budget is not None:
        args.append(f"--token-budget={token_budget}")
    if auto_merge is not None:
        args.append("--auto-merge" if auto_merge else "--no-auto-merge")
    if kill_losers:
        args.append("--kill-losers")
    if reset:
        args.append("--reset")
    return args


def _merge_resume_args(
    spec_id: str,
    legacy_args: list[str] | None,
    *,
    mode: str | None,
    strategy: str | None,
) -> list[str]:
    return [
        spec_id,
        *(legacy_args or []),
        *_option_pairs(mode=mode, strategy=strategy),
    ]


def _merge_land_args(
    spec_id: str,
    legacy_args: list[str] | None,
    *,
    continue_: bool,
    prepare_only: bool,
    no_autoresolve: bool,
    allow_fulfillment_gaps: bool,
    strategy: str | None,
) -> list[str]:
    args = [spec_id, *(legacy_args or [])]
    if continue_:
        args.append("--continue")
    if prepare_only:
        args.append("--prepare-only")
    if no_autoresolve:
        args.append("--no-autoresolve")
    if allow_fulfillment_gaps:
        args.append("--allow-fulfillment-gaps")
    if strategy is not None:
        args.extend(["--strategy", strategy])
    return args


@delivery_app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_init(ctx: typer.Context) -> None:
    """Initialize delivery environment: sandbox, mirror, verify."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_init(
        list(ctx.args),
        command_prefix="echelon delivery init",
    )


@delivery_app.command("target")
def delivery_target(spec_id: str) -> None:
    """Prepare delivery metadata for a spec's declared target repo."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_delivery_target([spec_id])


@harness_app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_init(ctx: typer.Context) -> None:
    """Compatibility alias for delivery init."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_init(
        list(ctx.args),
        command_prefix="echelon delivery init",
    )


@delivery_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_run(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Autonomy mode: semi, banzai, or guided.",
    ),
    strategy: Optional[str] = typer.Option(
        None,
        "--strategy",
        help="Build strategy, usually default or codegen.",
    ),
    max_outer: Optional[int] = typer.Option(
        None,
        "--max-outer",
        help="Maximum build/verify outer iterations.",
    ),
    max_inner: Optional[int] = typer.Option(
        None,
        "--max-inner",
        help="Maximum feedback inner iterations per outer iteration.",
    ),
    token_budget: Optional[int] = typer.Option(
        None,
        "--token-budget",
        help="Token budget for the delivery run.",
    ),
    auto_merge: Optional[bool] = typer.Option(
        None,
        "--auto-merge/--no-auto-merge",
        help="Enable or disable automatic landing after convergence.",
    ),
    kill_losers: bool = typer.Option(
        False,
        "--kill-losers",
        help="Cancel peer strategies after the first convergence.",
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Discard blocked state and start fresh.",
    ),
) -> None:
    """Run build, verification, review, and PR loop for a spec."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_run(
        _merge_run_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
            max_outer=max_outer,
            max_inner=max_inner,
            token_budget=token_budget,
            auto_merge=auto_merge,
            kill_losers=kill_losers,
            reset=reset,
        ),
        command_prefix="echelon delivery run",
        display_args=_display_run_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
            max_outer=max_outer,
            max_inner=max_inner,
            token_budget=token_budget,
            auto_merge=auto_merge,
            kill_losers=kill_losers,
            reset=reset,
        ),
    )


@harness_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_run(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
    max_outer: Optional[int] = typer.Option(None, "--max-outer"),
    max_inner: Optional[int] = typer.Option(None, "--max-inner"),
    token_budget: Optional[int] = typer.Option(None, "--token-budget"),
    auto_merge: Optional[bool] = typer.Option(None, "--auto-merge/--no-auto-merge"),
    kill_losers: bool = typer.Option(False, "--kill-losers"),
    reset: bool = typer.Option(False, "--reset"),
) -> None:
    """Compatibility alias for delivery run."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_run(
        _merge_run_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
            max_outer=max_outer,
            max_inner=max_inner,
            token_budget=token_budget,
            auto_merge=auto_merge,
            kill_losers=kill_losers,
            reset=reset,
        ),
        command_prefix="echelon delivery run",
        display_args=_display_run_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
            max_outer=max_outer,
            max_inner=max_inner,
            token_budget=token_budget,
            auto_merge=auto_merge,
            kill_losers=kill_losers,
            reset=reset,
        ),
    )


@delivery_app.command(
    "resume",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_resume(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Resume a blocked delivery run with a human answer."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_resume(
        _merge_resume_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
        )
    )


@delivery_app.command(
    "continue",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_continue(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Continue a blocked delivery run when no answer is needed."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_harness_continue(
        _merge_resume_args(
            spec_id,
            list(ctx.args),
            mode=mode,
            strategy=strategy,
        )
    )


@harness_app.command(
    "resume",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_resume(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Compatibility alias for delivery resume."""
    delivery_resume(ctx, spec_id, mode=mode, strategy=strategy)


@harness_app.command(
    "continue",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_continue(
    ctx: typer.Context,
    spec_id: str,
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Compatibility alias for delivery continue."""
    delivery_continue(ctx, spec_id, mode=mode, strategy=strategy)


@harness_app.command(
    "land",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_land(
    ctx: typer.Context,
    spec_id: str,
    continue_: bool = typer.Option(
        False,
        "--continue",
        help="Continue an interrupted land operation.",
    ),
    prepare_only: bool = typer.Option(
        False,
        "--prepare-only",
        help="Prepare the feature branch but do not merge it.",
    ),
    no_autoresolve: bool = typer.Option(
        False,
        "--no-autoresolve",
        help="Disable deterministic conflict autoresolution.",
    ),
    allow_fulfillment_gaps: bool = typer.Option(
        False,
        "--allow-fulfillment-gaps",
        help="Allow landing despite unresolved fulfillment gaps.",
    ),
    strategy: Optional[str] = typer.Option(
        None,
        "--strategy",
        help="Landing strategy: merge or rebase.",
    ),
) -> None:
    """Compatibility alias for delivery land."""
    delivery_land(
        ctx,
        spec_id,
        continue_=continue_,
        prepare_only=prepare_only,
        no_autoresolve=no_autoresolve,
        allow_fulfillment_gaps=allow_fulfillment_gaps,
        strategy=strategy,
    )


@delivery_app.command(
    "land",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_land(
    ctx: typer.Context,
    spec_id: str,
    continue_: bool = typer.Option(
        False,
        "--continue",
        help="Continue an interrupted land operation.",
    ),
    prepare_only: bool = typer.Option(
        False,
        "--prepare-only",
        help="Prepare the feature branch but do not merge it.",
    ),
    no_autoresolve: bool = typer.Option(
        False,
        "--no-autoresolve",
        help="Disable deterministic conflict autoresolution.",
    ),
    allow_fulfillment_gaps: bool = typer.Option(
        False,
        "--allow-fulfillment-gaps",
        help="Allow landing despite unresolved fulfillment gaps.",
    ),
    strategy: Optional[str] = typer.Option(
        None,
        "--strategy",
        help="Landing strategy: merge or rebase.",
    ),
) -> None:
    """Land a spec by merging PR/branch and cleaning up."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_land(
        _merge_land_args(
            spec_id,
            list(ctx.args),
            continue_=continue_,
            prepare_only=prepare_only,
            no_autoresolve=no_autoresolve,
            allow_fulfillment_gaps=allow_fulfillment_gaps,
            strategy=strategy,
        )
    )


@delivery_checkpoint_app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_checkpoint_list(
    ctx: typer.Context,
    spec_id: str,
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """List delivery checkpoint and recovery commits for a spec."""
    from echelon import cli as legacy_cli

    args = ["list", spec_id]
    if strategy is not None:
        args.extend(["--strategy", strategy])
    args.extend(list(ctx.args))
    legacy_cli._cmd_delivery_checkpoint(args)


def run(argv: list[str] | None = None) -> None:
    """Run the Typer CLI app with an explicit argv for tests or sys.argv[1:]."""
    app(args=argv, standalone_mode=False)
