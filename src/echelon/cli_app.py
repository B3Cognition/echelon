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
workspace_sources_app = typer.Typer(
    add_completion=False,
    help="Workspace source root discovery and config sync commands.",
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
    help=(
        "Phase B/delivery commands: build, verify, recover, review, and land specs.\n\n"
        "Common forms:\n"
        "  init\n"
        "  target <spec_id>\n"
        "  status [<spec_id>] [--strategy <s>]\n"
        "  run <spec_id> [--target <source-id-or-path>] [--mode <m>] [--strategy <s>]\n"
        "  continue <spec_id> [--mode <m>] [--strategy <s>]\n"
        "  resume <spec_id> \"<answer>\" [--mode <m>] [--strategy <s>]\n"
        "  land <spec_id> [--continue] [--prepare-only]"
    ),
    rich_markup_mode=None,
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
        "                    [--target <source-id-or-path>]... [--init]\n"
        "                    [--re-policy none|cached-only|changed|refresh-all]\n"
        "                    [--re-max-inner <n>]\n"
        "  checkpoint list|accept|commit [--spec <id>] [--phase <phase-id>]\n"
        "  targets <spec_id>  Display every task grouped by delivery target.\n"
        "  drop-target <spec_id> <target> --confirm\n"
        "                    Remove an unused target from an unfinished run.\n"
        "  Example: targets <spec_id>"
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
re_app = typer.Typer(
    add_completion=False,
    help="Publish and inspect workspace reverse engineering.",
    no_args_is_help=True,
)
kb_app = typer.Typer(
    add_completion=False,
    help="Validate and apply Phase A knowledge-base proposals.",
    no_args_is_help=True,
)

app.add_typer(workspace_app, name="workspace")
app.add_typer(spec_app, name="spec")
app.add_typer(phase_app, name="phase")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(stack_app, name="stack")
app.add_typer(delivery_app, name="delivery")
app.add_typer(harness_app, name="harness", hidden=True)
app.add_typer(re_app, name="re")
app.add_typer(kb_app, name="kb")
workspace_app.add_typer(workspace_sources_app, name="sources")
spec_app.add_typer(spec_checkpoint_app, name="checkpoint")
delivery_app.add_typer(delivery_checkpoint_app, name="checkpoint")


def _ctx_args(ctx: typer.Context) -> list[str]:
    return list(ctx.args)


def _extend_option(args: list[str], flag: str, value: object | None) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _extend_repeated_option(args: list[str], flag: str, values: list[str] | None) -> None:
    for value in values or []:
        args.extend([flag, value])


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


@kb_app.command("validate")
def kb_validate(
    run_id: str = typer.Option(..., "--run-id", help="Phase A run id below runs/."),
) -> None:
    """Validate Phase A KB proposal artifacts without mutating canonical KB."""
    from echelon.kb_proposals import load_proposals

    proposal_dir = Path.cwd() / "runs" / run_id / "kb-proposals"
    loaded = load_proposals(proposal_dir, expected_run_id=run_id)
    invalid = [item for item in loaded if not item.validation.ok]
    status = "valid" if loaded and not invalid else "degraded"
    typer.echo(f"kb_validation_status: {status}")
    typer.echo(f"proposals: {len(loaded)}")
    typer.echo(f"invalid: {len(invalid)}")


@kb_app.command("apply")
def kb_apply(
    run_id: str = typer.Option(..., "--run-id", help="Phase A run id below runs/."),
) -> None:
    """Apply valid Phase A KB proposal artifacts without blocking the run."""
    from echelon.kb_proposals import apply_proposals

    report = apply_proposals(Path.cwd(), run_id)
    typer.echo(f"kb_apply_status: {report.status}")
    typer.echo(f"report: {report.report_path}")
    typer.echo(f"accepted: {report.accepted_count}")
    typer.echo(f"rejected: {report.rejected_count}")


@app.command("version")
def version_command() -> None:
    """Print the Echelon CLI version."""
    legacy_cli = _legacy_cli()

    typer.echo(f"echelon {legacy_cli.CLI_VERSION}")


@re_app.command("run")
def re_run(
    re_policy: str = typer.Option(
        "changed",
        "--re-policy",
        help="Workspace RE policy: none, cached-only, changed, or refresh-all.",
    ),
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets.",
    ),
    reset: bool = typer.Option(False, "--reset", help="Abandon unfinished RE state and replan."),
) -> None:
    """Run or resume workspace reverse engineering and publish complete output."""
    args = ["--re-policy", re_policy]
    _extend_option(args, "--re-max-inner", re_max_inner)
    if reset:
        args.append("--reset")
    _legacy_cli()._cmd_re_run(args)


@re_app.command("continue")
def re_continue(
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets before continuing.",
    ),
) -> None:
    """Continue the active RE run without a human answer."""
    args: list[str] = []
    _extend_option(args, "--re-max-inner", re_max_inner)
    _legacy_cli()._cmd_re_continue(args)


@re_app.command("resume")
def re_resume(
    answer: str = typer.Argument(..., help="Answer to the active RE human blocker."),
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets before resuming.",
    ),
) -> None:
    """Answer a typed human blocker and continue the active RE run."""
    args = [answer]
    _extend_option(args, "--re-max-inner", re_max_inner)
    _legacy_cli()._cmd_re_resume(args)


@re_app.command("publish")
def re_publish(
    run_id: str = typer.Argument(..., help="Run id below runs/ or squad/."),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Explicitly allow a structurally valid partial publication.",
    ),
    commit: bool = typer.Option(
        False,
        "--commit",
        help="Commit only durable published re/ artifacts.",
    ),
) -> None:
    """Publish validated reverse-engineering output from one run."""
    args = [run_id]
    if allow_partial:
        args.append("--allow-partial")
    if commit:
        args.append("--commit")
    _legacy_cli()._cmd_re_publish(args)


@re_app.command("execute-run", hidden=True)
def re_execute_run(
    run_id: str = typer.Argument(..., help="Active workspace run id."),
) -> None:
    """Execute active workspace RE with harness-owned transitions."""
    _legacy_cli()._cmd_re_execute_run([run_id])


@re_app.command("check-domain", hidden=True)
def re_check_domain(
    run_id: str = typer.Argument(..., help="Run id below runs/."),
    source_id: str = typer.Argument(..., help="Source id from the RE plan."),
    domain_id: str = typer.Argument(..., help="Domain id from the source manifest."),
) -> None:
    """Check one staged source-domain spec before the agent returns DONE."""
    _legacy_cli()._cmd_re_check_domain([run_id, source_id, domain_id])


@app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_init() -> None:
    """Initialize the current workspace."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_init(Path.cwd())


@app.command(
    "cicd",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_cicd(ctx: typer.Context) -> None:
    """Retired CI/CD compatibility command."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_cicd(_ctx_args(ctx))


@app.command(
    "artifacts",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_artifacts(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to index."),
) -> None:
    """Generate a spec artifact index."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_artifacts([spec_id, *_ctx_args(ctx)])


@app.command(
    "land",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_land(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to land."),
    continue_: bool = typer.Option(
        False,
        "--continue",
        help="Resume an interrupted land operation.",
    ),
    prepare_only: bool = typer.Option(
        False,
        "--prepare-only",
        help="Prepare landing artifacts without merging.",
    ),
    no_autoresolve: bool = typer.Option(
        False,
        "--no-autoresolve",
        help="Disable automatic local conflict resolution.",
    ),
    allow_fulfillment_gaps: bool = typer.Option(
        False,
        "--allow-fulfillment-gaps",
        help="Allow landing with open fulfillment gaps.",
    ),
    strategy: Optional[str] = typer.Option(
        None,
        "--strategy",
        help="Landing strategy, usually merge or rebase.",
    ),
) -> None:
    """Compatibility alias for delivery land."""
    legacy_cli = _legacy_cli()

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


@app.command("status", hidden=True)
def root_status() -> None:
    """Compatibility alias for spec status."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_status(Path.cwd())


@app.command(
    "continue",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_continue(
    ctx: typer.Context,
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode override."),
) -> None:
    """Compatibility alias for spec continue."""
    legacy_cli = _legacy_cli()

    args = _ctx_args(ctx)
    _extend_option(args, "--mode", mode)
    legacy_cli._cmd_spec_continue(args)


@app.command(
    "rewind",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_rewind(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., help="Safe phase id to rewind to."),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Compatibility alias for spec rewind."""
    legacy_cli = _legacy_cli()

    args = [phase_id, *_ctx_args(ctx)]
    if confirm:
        args.append("--confirm")
    legacy_cli._cmd_rewind(args, project_root=Path.cwd())


@app.command(
    "resume",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_resume(
    ctx: typer.Context,
    answer: Optional[str] = typer.Argument(None, help="Answer for the blocked Phase A run."),
) -> None:
    """Compatibility alias for spec resume."""
    legacy_cli = _legacy_cli()

    args: list[str] = []
    if answer is not None:
        args.append(answer)
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_spec_resume(args)


@app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_run(
    ctx: typer.Context,
    description: Optional[str] = typer.Argument(None, help="Spec request or task description."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    reset: bool = typer.Option(False, "--reset", help="Discard blocked state and start fresh."),
    init: bool = typer.Option(False, "--init", help="Create or prepare the targeted source root."),
    message: Optional[str] = typer.Option(None, "--message", help="Additional run message."),
    next_phase: Optional[str] = typer.Option(None, "--next-phase", help="Resume at an explicit workflow phase."),
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        help="Implementation source id or path; repeat for multi-repo delivery.",
    ),
    ignore_re: bool = typer.Option(
        False,
        "--ignore-re",
        help="Do not attach the latest published RE context.",
    ),
) -> None:
    """Compatibility alias for spec run."""
    spec_run(
        ctx,
        description=description,
        mode=mode,
        reset=reset,
        init=init,
        message=message,
        next_phase=next_phase,
        target=target,
        input_values=None,
        ignore_re=ignore_re,
    )


def _dispatch_skill(command: str, args: list[str]) -> None:
    legacy_cli = _legacy_cli()

    legacy_cli._dispatch_skill_command(command, args)


@app.command(
    "build",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_build(
    ctx: typer.Context,
    spec_id: Optional[str] = typer.Argument(None, help="Spec id to build."),
    fix: bool = typer.Option(False, "--fix", help="Run build as a targeted fix pass."),
    failures: Optional[str] = typer.Option(None, "--failures", help="Failure payload for fix passes."),
    context: Optional[str] = typer.Option(None, "--context", help="Additional build context label."),
) -> None:
    """Compatibility alias for the build skill command."""
    args: list[str] = []
    if spec_id is not None:
        args.append(spec_id)
    if fix:
        args.append("--fix")
    _extend_option(args, "--failures", failures)
    _extend_option(args, "--context", context)
    args.extend(_ctx_args(ctx))
    _dispatch_skill("build", args)


@app.command(
    "review",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_review(
    ctx: typer.Context,
    spec_id: Optional[str] = typer.Argument(None, help="Spec id to review."),
    pr_url: Optional[str] = typer.Option(None, "--pr-url", help="Pull request URL to review."),
) -> None:
    """Compatibility alias for the review skill command."""
    args: list[str] = []
    if spec_id is not None:
        args.append(spec_id)
    _extend_option(args, "--pr-url", pr_url)
    args.extend(_ctx_args(ctx))
    _dispatch_skill("review", args)


@app.command(
    "codegen",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_codegen(
    ctx: typer.Context,
    spec_id: Optional[str] = typer.Argument(None, help="Spec id to build with SOAR codegen."),
) -> None:
    """Compatibility alias for the codegen skill command."""
    args: list[str] = []
    if spec_id is not None:
        args.append(spec_id)
    args.extend(_ctx_args(ctx))
    _dispatch_skill("codegen", args)


@app.command(
    "verify-spec",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_verify_spec(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to audit."),
    reconcile: bool = typer.Option(False, "--reconcile", help="Apply deterministic reconciliation fixes."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview reconciliation changes only."),
) -> None:
    """Compatibility alias for spec verify."""
    args = [spec_id, *_ctx_args(ctx)]
    if reconcile:
        args.append("--reconcile")
    if dry_run:
        args.append("--dry-run")
    _dispatch_skill("verify-spec", args)


@app.command(
    "reopen",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_reopen(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to reopen."),
    report: Optional[str] = typer.Argument(None, help="Optional from=<report> fulfillment report selector."),
) -> None:
    """Compatibility alias for spec reopen."""
    args = [spec_id]
    if report is not None:
        args.append(report)
    args.extend(_ctx_args(ctx))
    _dispatch_skill("reopen", args)


@app.command(
    "bugfix",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_bugfix(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to update."),
    description: str = typer.Argument(..., help="Bug description."),
) -> None:
    """Compatibility alias for spec bugfix."""
    _dispatch_skill("bugfix", [spec_id, description, *_ctx_args(ctx)])


@app.command(
    "change",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def root_change(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to update."),
    description: str = typer.Argument(..., help="Change description."),
) -> None:
    """Compatibility alias for spec change."""
    _dispatch_skill("change", [spec_id, description, *_ctx_args(ctx)])


@workspace_app.command("init", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def workspace_init(
    ctx: typer.Context,
    llm: Optional[str] = typer.Option(
        None,
        "--llm",
        "--llm-cli",
        help="Persist the workspace AI CLI provider.",
    ),
    allow_unsafe_host_execution: Optional[bool] = typer.Option(
        None,
        "--allow-unsafe-host-execution/--no-unsafe-host-execution",
        help="Persist or deny local approval for unsafe host execution flags.",
    ),
) -> None:
    """One-time project setup."""
    legacy_cli = _legacy_cli()

    args = ["init"]
    _extend_option(args, "--llm", llm)
    if allow_unsafe_host_execution is True:
        args.append("--allow-unsafe-host-execution")
    elif allow_unsafe_host_execution is False:
        args.append("--no-unsafe-host-execution")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_workspace(args)


@workspace_app.command("doctor")
def workspace_doctor() -> None:
    """Validate workspace/source/runtime contract."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_workspace(["doctor"])


@workspace_app.command("migrate", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def workspace_migrate(
    ctx: typer.Context,
    write: bool = typer.Option(False, "--write", help="Write migration changes."),
    commit: bool = typer.Option(False, "--commit", help="Commit migration changes."),
    message: Optional[str] = typer.Option(None, "--message", help="Migration commit message."),
) -> None:
    """Migrate legacy workspace layout."""
    legacy_cli = _legacy_cli()

    args = ["migrate"]
    if write:
        args.append("--write")
    if commit:
        args.append("--commit")
    _extend_option(args, "--message", message)
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_workspace(args)


@workspace_sources_app.command(
    "sync",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def workspace_sources_sync(
    ctx: typer.Context,
    write: bool = typer.Option(False, "--write", help="Write sources to workspace config."),
) -> None:
    """Sync configured source roots from the canonical sources/ directory."""
    legacy_cli = _legacy_cli()

    args = ["sources", "sync"]
    if write:
        args.append("--write")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_workspace(args)


@phase_app.command("list")
def phase_list() -> None:
    """List workflow phases available for manual replay."""
    _dispatch_phase(["list"])


@phase_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def phase_run(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., help="Workflow phase id to replay."),
    spec: Optional[str] = typer.Option(None, "--spec", help="Spec id to use as phase context."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    message: Optional[str] = typer.Option(None, "--message", help="Additional phase replay context."),
) -> None:
    """Run one explicit phase through COMMANDER contracts."""
    args = ["run", phase_id]
    _extend_option(args, "--spec", spec)
    _extend_option(args, "--mode", mode)
    _extend_option(args, "--message", message)
    args.extend(_ctx_args(ctx))
    _dispatch_phase(args)


@benchmark_app.command("list")
def benchmark_list() -> None:
    """List experimental benchmark fixtures and variants."""
    legacy_cli = _legacy_cli()

    legacy_cli._cmd_benchmark(["list"], project_root=Path.cwd())


@benchmark_app.command("show", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_show(
    ctx: typer.Context,
    target: Optional[str] = typer.Argument(
        None,
        help="latest, a summary path, or a benchmark run directory.",
    ),
) -> None:
    """Print saved benchmark scores."""
    legacy_cli = _legacy_cli()

    args = ["show"]
    if target is not None:
        args.append(target)
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_benchmark(args, project_root=Path.cwd())


@benchmark_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_run(
    ctx: typer.Context,
    fixture_id: str = typer.Argument(..., help="Benchmark fixture id."),
    variant: Optional[str] = typer.Option(None, "--variant", help="Benchmark variant id."),
    baseline_ref: Optional[str] = typer.Option(
        None,
        "--baseline-ref",
        help="Git ref to use as the baseline snapshot.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without running them."),
) -> None:
    """Run or print an artifact-quality benchmark variant."""
    legacy_cli = _legacy_cli()

    args = ["run", fixture_id]
    _extend_option(args, "--variant", variant)
    _extend_option(args, "--baseline-ref", baseline_ref)
    if dry_run:
        args.append("--dry-run")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_benchmark(args, project_root=Path.cwd())


@stack_app.command("list", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Print stack definitions as JSON."),
) -> None:
    """List available Echelon stacks."""
    legacy_cli = _legacy_cli()

    args = ["list"]
    if json_output:
        args.append("--json")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_stack(args, project_root=Path.cwd())


@stack_app.command("detect", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_detect(
    ctx: typer.Context,
    target: Optional[str] = typer.Option(None, "--target", help="Source tree to inspect."),
    artifacts: Optional[list[str]] = typer.Option(
        None,
        "--artifacts",
        help="Additional artifact root to include; repeat for multiple roots.",
    ),
    write: bool = typer.Option(False, "--write", help="Write detection reports under runs/stack-detect."),
    output_format: Optional[str] = typer.Option(
        None,
        "--format",
        help="Output format: text, yaml, or json.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    """Detect source/artifact stack evidence."""
    legacy_cli = _legacy_cli()

    args = ["detect"]
    _extend_option(args, "--target", target)
    _extend_repeated_option(args, "--artifacts", artifacts)
    if write:
        args.append("--write")
    _extend_option(args, "--format", output_format)
    if json_output:
        args.append("--json")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_stack(args, project_root=Path.cwd())


@stack_app.command("preflight", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_preflight(
    ctx: typer.Context,
    stack: Optional[list[str]] = typer.Option(
        None,
        "--stack",
        help="Stack id to preflight; repeat for multiple stacks.",
    ),
    target_archetype: Optional[list[str]] = typer.Option(
        None,
        "--target-archetype",
        help="Target archetype filter; repeat for multiple archetypes.",
    ),
    from_detect: Optional[str] = typer.Option(
        None,
        "--from-detect",
        help="Load stack selections from a detection report.",
    ),
    probe_tools: bool = typer.Option(False, "--probe-tools", help="Probe selected stack tools."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    """Check selected stack commands, registries, and tool probes."""
    legacy_cli = _legacy_cli()

    args = ["preflight"]
    _extend_repeated_option(args, "--stack", stack)
    _extend_repeated_option(args, "--target-archetype", target_archetype)
    _extend_option(args, "--from-detect", from_detect)
    if probe_tools:
        args.append("--probe-tools")
    if json_output:
        args.append("--json")
    args.extend(_ctx_args(ctx))
    legacy_cli._cmd_stack(args, project_root=Path.cwd())


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
def spec_run(
    ctx: typer.Context,
    description: Optional[str] = typer.Argument(None, help="Spec request or task description."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    reset: bool = typer.Option(False, "--reset", help="Discard blocked state and start fresh."),
    init: bool = typer.Option(False, "--init", help="Create or prepare the targeted source root."),
    message: Optional[str] = typer.Option(None, "--message", help="Additional run message."),
    next_phase: Optional[str] = typer.Option(None, "--next-phase", help="Resume at an explicit workflow phase."),
    target: Optional[list[str]] = typer.Option(
        None,
        "--target",
        help="Implementation source id or path; repeat for multi-repo delivery.",
    ),
    input_values: Optional[list[str]] = typer.Option(
        None,
        "--input",
        help="Product input as requirement:<path> or reference:<path>; repeat as needed.",
    ),
    ignore_re: bool = typer.Option(
        False,
        "--ignore-re",
        help="Do not attach the latest published RE context.",
    ),
) -> None:
    """Run Phase A squad spec authoring."""
    from echelon import cli as legacy_cli

    args: list[str] = []
    if description is not None:
        args.append(description)
    args.extend(list(ctx.args))
    _extend_option(args, "--mode", mode)
    if reset:
        args.append("--reset")
    if init:
        args.append("--init")
    _extend_option(args, "--message", message)
    _extend_option(args, "--next-phase", next_phase)
    _extend_repeated_option(args, "--target", target)
    _extend_repeated_option(args, "--input", input_values)
    if ignore_re:
        args.append("--ignore-re")
    legacy_cli._cmd_spec_run(args)


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
def spec_continue(
    ctx: typer.Context,
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode override."),
) -> None:
    """Run the next no-input Phase A recovery action."""
    from echelon import cli as legacy_cli

    args = list(ctx.args)
    _extend_option(args, "--mode", mode)
    legacy_cli._cmd_spec_continue(args)


@spec_app.command(
    "resume",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_resume(
    ctx: typer.Context,
    answer: Optional[str] = typer.Argument(None, help="Answer for the blocked Phase A run."),
) -> None:
    """Answer escalation questions from a blocked run."""
    from echelon import cli as legacy_cli

    args: list[str] = []
    if answer is not None:
        args.append(answer)
    args.extend(list(ctx.args))
    legacy_cli._cmd_spec_resume(args)


@spec_app.command(
    "rewind",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_rewind(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., help="Safe phase id to rewind to."),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Rewind the active squad run to a safe checkpoint."""
    from pathlib import Path

    from echelon import cli as legacy_cli

    args = [phase_id, *list(ctx.args)]
    if confirm:
        args.append("--confirm")
    legacy_cli._cmd_rewind(args, project_root=Path.cwd())


@spec_app.command("drop-target")
def spec_drop_target(
    spec_id: str = typer.Argument(..., help="Active unfinished spec id."),
    target: str = typer.Argument(..., help="Declared target to remove when it owns no tasks."),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the target removal."),
) -> None:
    """Remove an unused target and re-run task planning for the remaining targets."""
    from echelon import cli as legacy_cli

    args = [spec_id, target]
    if confirm:
        args.append("--confirm")
    legacy_cli._cmd_drop_target(args, project_root=Path.cwd())


@spec_checkpoint_app.command(
    "list",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_list(
    ctx: typer.Context,
    spec: Optional[str] = typer.Option(None, "--spec", help="Spec id to inspect."),
) -> None:
    """List Phase A/spec checkpoints."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    args = ["list"]
    _extend_option(args, "--spec", spec)
    args.extend(list(ctx.args))
    run_checkpoint_command(args, project_root=Path.cwd())


@spec_checkpoint_app.command(
    "accept",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_accept(
    ctx: typer.Context,
    phase: str = typer.Option(..., "--phase", help="Phase id whose checkpoint to accept."),
    spec: Optional[str] = typer.Option(None, "--spec", help="Spec id to inspect."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Checkpoint run id."),
) -> None:
    """Accept a Phase A/spec checkpoint."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    args = ["accept", "--phase", phase]
    _extend_option(args, "--spec", spec)
    _extend_option(args, "--run-id", run_id)
    args.extend(list(ctx.args))
    run_checkpoint_command(args, project_root=Path.cwd())


@spec_checkpoint_app.command(
    "commit",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_checkpoint_commit(
    ctx: typer.Context,
    phase: str = typer.Option(..., "--phase", help="Phase id whose checkpoint to commit."),
    spec: Optional[str] = typer.Option(None, "--spec", help="Spec id to inspect."),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Checkpoint run id."),
    message: Optional[str] = typer.Option(None, "--message", help="Checkpoint commit message."),
) -> None:
    """Commit a Phase A/spec checkpoint."""
    from pathlib import Path

    from echelon.checkpoint_cli import run_checkpoint_command

    args = ["commit", "--phase", phase]
    _extend_option(args, "--spec", spec)
    _extend_option(args, "--run-id", run_id)
    _extend_option(args, "--message", message)
    args.extend(list(ctx.args))
    run_checkpoint_command(args, project_root=Path.cwd())


@spec_app.command(
    "target",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    hidden=True,
)
def spec_target(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to update."),
    repo: list[str] = typer.Argument(..., help="Target repository path or id."),
    init: bool = typer.Option(False, "--init", help="Create or prepare target Git repo(s)."),
) -> None:
    """Set implementation targets in spec metadata."""
    from echelon import cli as legacy_cli

    args = [spec_id, *repo, *list(ctx.args)]
    if init:
        args.append("--init")
    legacy_cli._cmd_spec_target(args)


@spec_app.command("targets")
def spec_targets(
    spec_id: str = typer.Argument(..., help="Spec id to inspect."),
) -> None:
    """Display every task grouped by delivery target."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_spec_targets([spec_id])


@spec_app.command(
    "artifacts",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_artifacts(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to index."),
) -> None:
    """Generate specs/<id>/ARTIFACTS.md."""
    from echelon import cli as legacy_cli

    legacy_cli._cmd_artifacts([spec_id, *list(ctx.args)])


@spec_app.command(
    "verify",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_verify(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to audit."),
    reconcile: bool = typer.Option(
        False,
        "--reconcile",
        help="Apply deterministic task-progress reconciliation fixes.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview reconciliation changes only."),
) -> None:
    """Audit implementation against spec."""
    from echelon import cli as legacy_cli

    args = [spec_id, *list(ctx.args)]
    if reconcile:
        args.append("--reconcile")
    if dry_run:
        args.append("--dry-run")
    legacy_cli._dispatch_skill_command("verify-spec", args)


@spec_app.command(
    "reopen",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_reopen(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to reopen."),
    report: Optional[str] = typer.Argument(
        None,
        help="Optional from=<report> fulfillment report selector.",
    ),
) -> None:
    """Reopen spec from fulfillment gaps."""
    from echelon import cli as legacy_cli

    args = [spec_id]
    if report is not None:
        args.append(report)
    args.extend(list(ctx.args))
    legacy_cli._dispatch_skill_command("reopen", args)


@spec_app.command("defer")
def spec_defer(
    spec_id: str = typer.Argument(..., help="Spec id whose scope is being deferred."),
    ids: list[str] = typer.Argument(..., help="Canonical task or requirement IDs to defer."),
    reason: str = typer.Option(..., "--reason", help="Owner reason for removing the scope."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the defer without writing files."),
) -> None:
    """Defer explicit spec scope without invoking an LLM."""
    _run_scope_change(spec_id, ids, action="defer", reason=reason, dry_run=dry_run)


@spec_app.command("plan")
def spec_plan(
    spec_id: str = typer.Argument(..., help="Spec id whose deferred scope is being restored."),
    ids: list[str] = typer.Argument(..., help="Deferred task or requirement IDs to plan."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the restore without writing files."),
) -> None:
    """Return deferred spec scope to planned work without invoking an LLM."""
    _run_scope_change(spec_id, ids, action="plan", dry_run=dry_run)


def _run_scope_change(
    spec_id: str,
    ids: list[str],
    *,
    action: str,
    dry_run: bool,
    reason: str | None = None,
) -> None:
    from harness.deferred_scope import (
        DeferredScopeError,
        apply_defer,
        apply_restore,
        ledger_path,
        plan_defer,
        plan_restore,
    )
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is None:
        raise typer.BadParameter(f"spec not found: {spec_id}")
    try:
        if action == "defer":
            plan = (
                plan_defer(spec_dir, ids, reason=reason or "")
                if dry_run
                else apply_defer(spec_dir, ids, reason=reason or "")
            )
            heading = "DEFERRED SCOPE"
        else:
            plan = plan_restore(spec_dir, ids) if dry_run else apply_restore(spec_dir, ids)
            heading = "PLANNED SCOPE"
    except DeferredScopeError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(heading)
    typer.echo(f"spec: {spec_id}")
    typer.echo(f"direct IDs: {', '.join(plan.selected_ids)}")
    task_label = "deferred tasks" if action == "defer" else "planned tasks"
    typer.echo(
        f"{task_label}: "
        + (", ".join(plan.derived_task_ids) if plan.derived_task_ids else "none")
    )
    for item_id in plan.related_active_ids:
        typer.echo(f"{item_id} remains active")
    typer.echo(f"ledger: {ledger_path(spec_dir)}")
    typer.echo("status: dry run" if dry_run else "status: applied")


@spec_app.command(
    "bugfix",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_bugfix(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to update."),
    description: str = typer.Argument(..., help="Bug description."),
) -> None:
    """Diagnose and plan a bugfix."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("bugfix", [spec_id, description, *list(ctx.args)])


@spec_app.command(
    "change",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_change(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to update."),
    description: str = typer.Argument(..., help="Change description."),
) -> None:
    """Plan a scope change."""
    from echelon import cli as legacy_cli

    legacy_cli._dispatch_skill_command("change", [spec_id, description, *list(ctx.args)])


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


@delivery_app.command("status")
def delivery_status(
    spec_id: Optional[str] = typer.Argument(None, help="Spec id to inspect."),
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Delivery strategy id."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show current Phase B delivery/Ralph state."""
    from echelon import cli as legacy_cli

    args: list[str] = []
    if spec_id is not None:
        args.append(spec_id)
    if strategy is not None:
        args.extend(["--strategy", strategy])
    if json_output:
        args.append("--json")
    legacy_cli._cmd_delivery_status(args)


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
    answer: Optional[str] = typer.Argument(None, help="Answer for blocker escalation."),
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Resume a blocked delivery run with a human answer."""
    from echelon import cli as legacy_cli

    legacy_args: list[str] = []
    if answer is not None:
        legacy_args.append(answer)
    legacy_args.extend(list(ctx.args))
    legacy_cli._cmd_harness_resume(
        _merge_resume_args(
            spec_id,
            legacy_args,
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
    answer: Optional[str] = typer.Argument(None, help="Answer for blocker escalation."),
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Compatibility alias for delivery resume."""
    delivery_resume(ctx, spec_id, answer=answer, mode=mode, strategy=strategy)


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
    if argv in (["-v"], ["--version"], ["version"]):
        legacy_cli = _legacy_cli()
        typer.echo(f"echelon {legacy_cli.CLI_VERSION}")
        return
    app(args=argv, standalone_mode=False)
