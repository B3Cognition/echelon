"""Typer front door for Echelon's user-facing CLI.

This module owns modern command parsing while delegating execution to the
existing handlers in ``echelon.cli``. Keeping the execution layer unchanged lets
Echelon normalize CLI contracts incrementally without rewriting harness logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer


app = typer.Typer(
    add_completion=False,
    help="Echelon CLI",
    no_args_is_help=True,
)
workspace_app = typer.Typer(
    add_completion=False,
    help="Workspace setup, doctor, and migration commands.",
    no_args_is_help=True,
)
phase_app = typer.Typer(
    add_completion=False,
    help="Workflow phase inspection and manual replay commands.",
    no_args_is_help=True,
)
benchmark_app = typer.Typer(
    add_completion=False,
    help="Experimental artifact-quality benchmark commands.",
    no_args_is_help=True,
)
stack_app = typer.Typer(
    add_completion=False,
    help="Stack detection and preflight commands.",
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
spec_app = typer.Typer(
    add_completion=False,
    help=(
        "Phase A/spec lifecycle commands.\n\n"
        "Common forms:\n"
        "  run <description> [--mode semi|banzai|guided] [--reset]\n"
        "                    [--target <source-id-or-path>]\n"
        "                    [--re-policy none|cached-only|changed|target-changed|target-only|refresh-all]\n"
        "  checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]\n"
        "  target <spec_id> <repo> <repo...> [--init]\n"
        "                    With --init, create/prepare target Git repo(s)."
    ),
    rich_markup_mode=None,
    no_args_is_help=True,
)
spec_checkpoint_app = typer.Typer(
    add_completion=False,
    help="Phase A/spec checkpoint commands.",
    no_args_is_help=True,
)
harness_app = typer.Typer(
    add_completion=False,
    help="Compatibility alias for delivery init/run/resume.",
    no_args_is_help=True,
)

app.add_typer(workspace_app, name="workspace")
app.add_typer(spec_app, name="spec")
app.add_typer(phase_app, name="phase")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(stack_app, name="stack")
app.add_typer(delivery_app, name="delivery")
app.add_typer(harness_app, name="harness")
spec_app.add_typer(spec_checkpoint_app, name="checkpoint")
delivery_app.add_typer(delivery_checkpoint_app, name="checkpoint")


def _ctx_args(ctx: typer.Context) -> list[str]:
    return list(ctx.args)


def _legacy_cli():
    from echelon import cli as legacy_cli

    return legacy_cli


def _dispatch_phase(args: list[str]) -> None:
    legacy_cli = _legacy_cli()
    project_root = Path.cwd()
    ext_dir = project_root / ".specify" / "extensions" / "echelon"
    if not ext_dir.exists():
        typer.echo(
            f"✗ Echelon extension not installed: {ext_dir}\n  Run: specify extension add echelon",
            err=True,
        )
        raise typer.Exit(1)
    cfg_file = legacy_cli._project_echelon_config(project_root)
    if not cfg_file.exists():
        typer.echo(
            f"✗ Project not initialized — config not found: {cfg_file}\n"
            "  Run: echelon workspace init",
            err=True,
        )
        raise typer.Exit(1)
    legacy_cli._cmd_phase(args, project_root=project_root, ext_dir=ext_dir)


@app.callback()
def root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show the Echelon CLI version and exit.",
    ),
) -> None:
    """Echelon CLI."""
    if version:
        legacy_cli = _legacy_cli()
        typer.echo(f"echelon {legacy_cli.CLI_VERSION}")
        raise typer.Exit()


@app.command("version")
def version_command() -> None:
    """Print the Echelon CLI version."""
    legacy_cli = _legacy_cli()

    typer.echo(f"echelon {legacy_cli.CLI_VERSION}")


@app.command("init", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_init() -> None:
    """Initialize the current workspace."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_init(Path.cwd())


@app.command("cicd", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_cicd(ctx: typer.Context) -> None:
    """Retired CI/CD compatibility command."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_cicd(_ctx_args(ctx))


@app.command("artifacts", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_artifacts(ctx: typer.Context) -> None:
    """Generate a spec artifact index."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_artifacts(_ctx_args(ctx))


@app.command("land", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_land(ctx: typer.Context) -> None:
    """Compatibility alias for delivery land."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_land(_ctx_args(ctx))


@app.command("status")
def root_status() -> None:
    """Compatibility alias for spec status."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_status(Path.cwd())


@app.command("continue", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_continue(ctx: typer.Context) -> None:
    """Compatibility alias for spec continue."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_spec_continue(_ctx_args(ctx))


@app.command("rewind", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_rewind(ctx: typer.Context) -> None:
    """Compatibility alias for spec rewind."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_rewind(_ctx_args(ctx), project_root=Path.cwd())


@app.command("resume", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_resume(ctx: typer.Context) -> None:
    """Compatibility alias for spec resume."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_spec_resume(_ctx_args(ctx))


@app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_run(ctx: typer.Context) -> None:
    """Compatibility alias for spec run."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_spec_run(_ctx_args(ctx))


def _make_skill_command(command: str):
    def _command(ctx: typer.Context) -> None:
        legacy_cli = _legacy_cli()

        legacy_cli._dispatch_skill_command(command, _ctx_args(ctx))

    return _command


for _skill_command in ("bugfix", "build", "review", "change", "codegen", "verify-spec", "reopen"):
    app.command(
        _skill_command,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
        help=f"Dispatch the {_skill_command} skill-backed command.",
    )(_make_skill_command(_skill_command))


@workspace_app.command("init", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def workspace_init(ctx: typer.Context) -> None:
    """One-time project setup."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_workspace(["init", *_ctx_args(ctx)])


@workspace_app.command("doctor")
def workspace_doctor() -> None:
    """Validate workspace/source/runtime contract."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_workspace(["doctor"])


@workspace_app.command("migrate", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def workspace_migrate(ctx: typer.Context) -> None:
    """Migrate legacy workspace layout."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_workspace(["migrate", *_ctx_args(ctx)])


@phase_app.command("list")
def phase_list() -> None:
    """List workflow phases available for manual replay."""
    _dispatch_phase(["list"])


@phase_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def phase_run(ctx: typer.Context) -> None:
    """Run one explicit phase through COMMANDER contracts."""
    _dispatch_phase(["run", *_ctx_args(ctx)])


@benchmark_app.command("list")
def benchmark_list() -> None:
    """List experimental benchmark fixtures and variants."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_benchmark(["list"], project_root=Path.cwd())


@benchmark_app.command("show", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_show(ctx: typer.Context) -> None:
    """Print saved benchmark scores."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_benchmark(["show", *_ctx_args(ctx)], project_root=Path.cwd())


@benchmark_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_run(ctx: typer.Context) -> None:
    """Run or print an artifact-quality benchmark variant."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_benchmark(["run", *_ctx_args(ctx)], project_root=Path.cwd())


@stack_app.command("list", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_list(ctx: typer.Context) -> None:
    """List available Echelon stacks."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_stack(["list", *_ctx_args(ctx)], project_root=Path.cwd())


@stack_app.command("detect", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_detect(ctx: typer.Context) -> None:
    """Detect source/artifact stack evidence."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_stack(["detect", *_ctx_args(ctx)], project_root=Path.cwd())


@stack_app.command("preflight", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_preflight(ctx: typer.Context) -> None:
    """Check selected stack commands, registries, and tool probes."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_stack(["preflight", *_ctx_args(ctx)], project_root=Path.cwd())


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


@spec_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_run(ctx: typer.Context) -> None:
    """Run Phase A squad spec authoring."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_spec_run(list(ctx.args))


@spec_app.command("status")
def spec_status() -> None:
    """Show current spec run state and next action."""
    from pathlib import Path

    from echelon import cli as legacy_cli

    legacy_cli._cmd_status(Path.cwd())


@spec_app.command(
    "continue",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_continue(ctx: typer.Context) -> None:
    """Run the next no-input Phase A recovery action."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_spec_continue(list(ctx.args))


@spec_app.command(
    "resume",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_resume(ctx: typer.Context) -> None:
    """Answer escalation questions from a blocked run."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_spec_resume(list(ctx.args))


@spec_app.command(
    "rewind",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_rewind(ctx: typer.Context) -> None:
    """Rewind the active squad run to a safe checkpoint."""
    from pathlib import Path

    from echelon import cli as legacy_cli

    legacy_cli._cmd_rewind(list(ctx.args), project_root=Path.cwd())


@spec_checkpoint_app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_list(ctx: typer.Context) -> None:
    """List Phase A/spec checkpoints."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    run_checkpoint_command(["list", *list(ctx.args)], project_root=Path.cwd())


@spec_checkpoint_app.command(
    "accept",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_accept(ctx: typer.Context) -> None:
    """Accept a Phase A/spec checkpoint."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    run_checkpoint_command(["accept", *list(ctx.args)], project_root=Path.cwd())


@spec_checkpoint_app.command(
    "commit",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_commit(ctx: typer.Context) -> None:
    """Commit a Phase A/spec checkpoint."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    run_checkpoint_command(["commit", *list(ctx.args)], project_root=Path.cwd())


@spec_app.command(
    "target",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_target(ctx: typer.Context) -> None:
    """Set implementation targets in spec metadata."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_spec_target(list(ctx.args))


@spec_app.command(
    "artifacts",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_artifacts(ctx: typer.Context) -> None:
    """Generate specs/<id>/ARTIFACTS.md."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_artifacts(list(ctx.args))


@spec_app.command(
    "verify",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_verify(ctx: typer.Context) -> None:
    """Audit implementation against spec."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("verify-spec", list(ctx.args))


@spec_app.command(
    "reopen",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_reopen(ctx: typer.Context) -> None:
    """Reopen spec from fulfillment gaps."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("reopen", list(ctx.args))


@spec_app.command(
    "bugfix",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_bugfix(ctx: typer.Context) -> None:
    """Diagnose and plan a bugfix."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("bugfix", list(ctx.args))


@spec_app.command(
    "change",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_change(ctx: typer.Context) -> None:
    """Plan a scope change."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("change", list(ctx.args))


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
