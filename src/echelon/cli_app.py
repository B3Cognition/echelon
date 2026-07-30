"""Typer front door for Echelon's user-facing CLI.

This module owns modern command parsing while delegating execution to the
existing handlers in ``echelon.cli``. Keeping the execution layer unchanged lets
Echelon normalize CLI contracts incrementally without rewriting harness logic.
"""

from __future__ import annotations

import shlex
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
        "  add-input --input <role:path>...  Add evidence to a parked investigation run.\n"
        "  resolve ISS-<n> <decision>  Record one issue decision and run its targeted repair.\n"
        "  publish <spec-id-or-branch> | publish --all\n"
        "                    Commit spec-only snapshots to the local default branch.\n"
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
spec_memory_app = typer.Typer(
    add_completion=False,
    help="Mine and audit canonical spec memory in MemPalace.",
    no_args_is_help=True,
)
graph_app = typer.Typer(
    add_completion=False,
    help="Build and audit artifact graphs rooted at a specification.",
    no_args_is_help=True,
)
graph_workspace_app = typer.Typer(
    add_completion=False,
    help="Build, audit, refresh, and inspect the workspace artifact graph.",
    no_args_is_help=True,
)
memory_app = typer.Typer(
    add_completion=False,
    help="Search and inspect workspace memory in MemPalace.",
    no_args_is_help=True,
)
spec_evidence_app = typer.Typer(
    add_completion=False,
    help="Inspect and mine spec verification evidence.",
    no_args_is_help=True,
)
spec_evidence_memory_app = typer.Typer(
    add_completion=False,
    help="Mine spec verification evidence in MemPalace.",
    no_args_is_help=True,
)
harness_app = typer.Typer(
    add_completion=False,
    help="Compatibility alias for delivery init/run/resume.",
    no_args_is_help=True,
)
llm_app = typer.Typer(
    add_completion=False,
    help="LLM provider diagnostics.",
    no_args_is_help=True,
)
re_app = typer.Typer(
    add_completion=False,
    help="Publish and inspect workspace reverse engineering.",
    no_args_is_help=True,
)
re_memory_app = typer.Typer(
    add_completion=False,
    help="Mine workspace reverse-engineering memory in MemPalace.",
    no_args_is_help=True,
)
kb_app = typer.Typer(
    add_completion=False,
    help="Validate and apply Phase A knowledge-base proposals.",
    no_args_is_help=True,
)
wiki_app = typer.Typer(
    add_completion=False,
    help="Build and inspect local human navigation for Echelon artifacts.",
    no_args_is_help=True,
)
admin_app = typer.Typer(
    add_completion=False,
    help="Explicit catalog of diagnostic commands.",
    no_args_is_help=True,
)

app.add_typer(workspace_app, name="workspace")
app.add_typer(spec_app, name="spec")
app.add_typer(phase_app, name="phase")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(stack_app, name="stack")
app.add_typer(delivery_app, name="delivery")
app.add_typer(harness_app, name="harness", hidden=True)
app.add_typer(llm_app, name="llm")
app.add_typer(graph_app, name="graph")
app.add_typer(memory_app, name="memory")
app.add_typer(re_app, name="re")
app.add_typer(kb_app, name="kb")
app.add_typer(wiki_app, name="wiki")
app.add_typer(admin_app, name="admin", hidden=True)
workspace_app.add_typer(workspace_sources_app, name="sources")
spec_app.add_typer(spec_checkpoint_app, name="checkpoint")
spec_app.add_typer(spec_memory_app, name="memory")
spec_app.add_typer(spec_evidence_app, name="evidence")
delivery_app.add_typer(delivery_checkpoint_app, name="checkpoint")
re_app.add_typer(re_memory_app, name="memory")
spec_evidence_app.add_typer(spec_evidence_memory_app, name="memory")
graph_app.add_typer(graph_workspace_app, name="workspace")


@admin_app.command("commands")
def admin_commands() -> None:
    """List intentionally hidden diagnostic commands."""
    typer.echo("Diagnostic commands:")
    typer.echo("  echelon re analyze [PATH] [--run-id ID] [--format text|json]")


@wiki_app.command("build")
def wiki_build(
    include_runs: Optional[bool] = typer.Option(
        None,
        "--include-runs/--no-include-runs",
        help="Include local, ephemeral run analysis in the generated vault.",
    ),
) -> None:
    """Build from the configured local default branch without switching branches."""
    from echelon.wiki.service import WikiBuildError, build_wiki

    try:
        result = build_wiki(Path.cwd(), include_runs=include_runs)
    except WikiBuildError as exc:
        typer.echo(f"Wiki build failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Wiki generated: {result.output_dir}")
    typer.echo(f"Home: {result.home_path}")
    typer.echo(
        f"Inputs: {result.input_count}; outputs: {result.output_count}; "
        f"warnings: {result.warning_count}"
    )
    if result.catalog_branch and result.catalog_revision:
        typer.echo(
            f"Catalog: {result.catalog_branch}@{result.catalog_revision[:12]}"
        )
    typer.echo(
        "Optional viewer: open the generated directory as an Obsidian vault "
        "(https://obsidian.md/download)."
    )


@wiki_app.command("status")
def wiki_status_command() -> None:
    """Report whether the generated wiki matches canonical artifacts."""
    from echelon.wiki.service import wiki_status

    status = wiki_status(Path.cwd())
    typer.echo(f"State: {status.state}")
    typer.echo(f"Path: {status.output_dir}")
    if status.workspace_revision:
        typer.echo(f"Revision: {status.workspace_revision}")
    typer.echo(f"Dirty canonical inputs: {'yes' if status.workspace_dirty else 'no'}")
    for label, paths in (
        ("Added", status.added_inputs),
        ("Changed", status.changed_inputs),
        ("Removed", status.removed_inputs),
    ):
        if paths:
            typer.echo(f"{label}:")
            for path in paths:
                typer.echo(f"  - {path}")
    if status.operational_stale:
        typer.echo("Operational run analysis: stale")
    typer.echo(status.message)
    if status.state == "invalid":
        raise typer.Exit(code=1)


@wiki_app.command("clean")
def wiki_clean() -> None:
    """Remove a manifest-owned generated wiki."""
    from echelon.wiki.service import WikiCleanError, clean_wiki

    try:
        removed = clean_wiki(Path.cwd())
    except WikiCleanError as exc:
        typer.echo(f"Wiki clean failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if removed is None:
        typer.echo("Wiki is absent; nothing to clean.")
    else:
        typer.echo(f"Removed: {removed}")


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


def _memory_exit_code(status: str) -> int:
    if status in {"pass", "warn", "complete"}:
        return 0
    if status in {"fail", "partial"}:
        return 1
    return 2


def _graph_exit_code(status: str) -> int:
    if status in {"pass", "warn"}:
        return 0
    if status == "fail":
        return 1
    return 2


def _echo_spec_graph_summary(graph: object, *, action: str) -> None:
    inputs = list(getattr(graph, "inputs", ()))
    memory = [
        str(getattr(item, "status", "unknown"))
        for item in inputs
        if getattr(item, "role", "") == "memory_audit_report"
    ]
    memory_status = ",".join(memory) if memory else "not-applicable"
    typer.echo(
        f"Spec graph {action}: spec={getattr(graph, 'spec_id')} "
        f"nodes={len(getattr(graph, 'nodes', ()))} "
        f"edges={len(getattr(graph, 'edges', ()))} "
        f"memory={memory_status}"
    )


def _echo_spec_graph_audit(report: object) -> None:
    findings = list(getattr(report, "findings", ()))
    typer.echo(
        f"Spec graph audit {getattr(report, 'status')}: "
        f"spec={getattr(report, 'spec_id')} findings={len(findings)}"
    )
    for finding in findings:
        typer.echo(
            f"  [{getattr(finding, 'severity')}] "
            f"{getattr(finding, 'code')}: {getattr(finding, 'message')}"
        )


def _echo_workspace_graph_summary(candidate: object, *, action: str) -> None:
    graph = getattr(candidate, "graph", candidate)
    typer.echo(
        f"Workspace graph {action}: workspace={getattr(graph, 'workspace_name', Path.cwd().name)} "
        f"nodes={len(getattr(graph, 'nodes', ()))} "
        f"edges={len(getattr(graph, 'edges', ()))}"
    )


def _echo_workspace_graph_audit(report: object) -> None:
    findings = list(getattr(report, "findings", ()))
    typer.echo(
        f"Workspace graph audit {getattr(report, 'status')}: "
        f"workspace={getattr(report, 'workspace_name', Path.cwd().name)} "
        f"findings={len(findings)}"
    )
    for finding in findings:
        typer.echo(
            f"  [{getattr(finding, 'severity')}] "
            f"{getattr(finding, 'code')}: {getattr(finding, 'message')}"
        )


def _cleanup_stale_memory_best_effort(project_root: Path, spec_selector: str) -> None:
    from echelon.mempalace_audit import cleanup_stale_spec_memory

    try:
        cleanup = cleanup_stale_spec_memory(project_root, spec_selector)
    except Exception as exc:
        typer.echo(
            f"warning: stale MemPalace cleanup skipped: {type(exc).__name__}",
            err=True,
        )
        return
    if cleanup.deleted_count:
        typer.echo(f"MemPalace cleanup: deleted={cleanup.deleted_count}")


def _echo_json(data: dict) -> None:
    import json

    typer.echo(json.dumps(data, indent=2, sort_keys=True))


def _echo_memory_facet(title: str, values: dict[str, int]) -> None:
    typer.echo(title)
    if not values:
        typer.echo("  (none)")
        return
    width = max(len(value) for value in values)
    for value, count in sorted(values.items()):
        typer.echo(f"  {value.ljust(width)}  {count}")


def _echo_memory_search(report: object) -> None:
    typer.echo(f"MemPalace search: {getattr(report, 'query')!r}")
    typer.echo(f"Wing: {getattr(report, 'wing')}")
    if getattr(report, "room", None):
        typer.echo(f"Room: {getattr(report, 'room')}")
    if getattr(report, "spec", None):
        typer.echo(f"Spec: {getattr(report, 'spec')}")
    if getattr(report, "kind", None):
        typer.echo(f"Kind: {getattr(report, 'kind')}")
    hits = list(getattr(report, "hits", []))
    if not hits:
        typer.echo("\nNo results.")
        return
    for index, hit in enumerate(hits, start=1):
        typer.echo("")
        typer.echo(
            f"[{index}] {hit.spec_id} / {hit.room} / {hit.kind} "
            f"(distance={hit.distance})"
        )
        typer.echo(f"    Source: {hit.artifact_path}")
        if hit.requirement_id:
            typer.echo(f"    ID: {hit.requirement_id}")
        typer.echo(f"    {hit.content}")


def _render_re_memory_audit_markdown(report: object) -> str:
    return _render_memory_audit_markdown(
        "MemPalace RE Audit",
        report,
        extra=[f"- RE root: {getattr(report, 're_root')}"],
    )


def _render_spec_evidence_memory_audit_markdown(report: object) -> str:
    return _render_memory_audit_markdown(
        "MemPalace Spec Evidence Audit",
        report,
        extra=[
            f"- Spec: {getattr(report, 'spec_id')}",
            f"- Spec dir: {getattr(report, 'spec_dir')}",
        ],
    )


def _render_memory_audit_markdown(
    title: str,
    report: object,
    *,
    extra: list[str],
) -> str:
    lines = [
        f"# {title}",
        "",
        *extra,
        f"- Status: {getattr(report, 'status')}",
        f"- Artifacts: {getattr(report, 'artifact_count')}",
        f"- Expected drawers: {getattr(report, 'expected_count')}",
        f"- Present current drawers: {getattr(report, 'present_current_count')}",
        f"- Missing: {len(getattr(report, 'missing', []))}",
        f"- Stale: {len(getattr(report, 'stale', []))}",
        f"- Wrong wing: {len(getattr(report, 'wrong_wing', []))}",
        f"- Wrong room: {len(getattr(report, 'wrong_room', []))}",
        f"- Non-canonical: {len(getattr(report, 'non_canonical', []))}",
        f"- Lifecycle excluded: {len(getattr(report, 'lifecycle_excluded', []))}",
        f"- Duplicate: {len(getattr(report, 'duplicate', []))}",
    ]
    return "\n".join(lines) + "\n"


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

    project_root = Path.cwd()
    proposal_dir = project_root / "runs" / run_id / "kb-proposals"
    loaded = load_proposals(
        proposal_dir,
        expected_run_id=run_id,
        project_root=project_root,
    )
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


@llm_app.command("smoke-openai-compatible")
def llm_smoke_openai_compatible(
    base_url: Optional[str] = typer.Option(
        None,
        "--base-url",
        help="OpenAI-compatible /v1 endpoint base URL.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="Model name to send in chat/completions requests.",
    ),
    api_key_env: Optional[str] = typer.Option(
        None,
        "--api-key-env",
        help="Environment variable containing the API key.",
    ),
    api_key_file: Optional[str] = typer.Option(
        None,
        "--api-key-file",
        help="File containing the API key.",
    ),
    timeout_s: float = typer.Option(
        120.0,
        "--timeout-s",
        min=1.0,
        help="Smoke request timeout in seconds.",
    ),
    streaming: bool = typer.Option(
        True,
        "--streaming/--no-streaming",
        help="Use SSE streaming for the smoke run.",
    ),
) -> None:
    """Exercise an OpenAI-compatible endpoint with a tiny tool-call loop."""
    from harness.ai_cli_backends.openai_compatible_smoke import (
        run_openai_compatible_smoke,
    )
    from harness.config import load_config

    project_root = Path.cwd()
    config = None
    if base_url is None or model is None or (api_key_env is None and api_key_file is None):
        try:
            config = load_config(project_root, squad_only=True)
        except Exception:
            config = None
    llm = config.llm if config is not None else None
    resolved_base_url = base_url or (llm.base_url if llm is not None else None)
    resolved_model = model or (llm.model if llm is not None else None)
    resolved_api_key_env = api_key_env or (llm.api_key_env if llm is not None else None)
    resolved_api_key_file = api_key_file or (
        llm.api_key_file if llm is not None else None
    )
    if not resolved_base_url:
        typer.echo("Missing --base-url and no llm.base_url in config.", err=True)
        raise typer.Exit(code=2)
    if not resolved_model:
        typer.echo("Missing --model and no llm.model in config.", err=True)
        raise typer.Exit(code=2)
    result = run_openai_compatible_smoke(
        project_root=project_root,
        base_url=resolved_base_url,
        model=resolved_model,
        api_key_env=resolved_api_key_env,
        api_key_file=resolved_api_key_file,
        timeout_s=timeout_s,
        streaming=streaming,
    )
    if result.ok:
        typer.echo("OpenAI-compatible smoke: ok")
    else:
        typer.echo("OpenAI-compatible smoke: failed", err=True)
    typer.echo(f"work_dir: {result.work_dir}")
    if result.transcript_path:
        typer.echo(f"transcript: {result.transcript_path}")
    typer.echo(f"tool_calls={result.tool_call_count}")
    typer.echo(f"tokens={result.token_usage}")
    if not result.ok:
        if result.stderr:
            typer.echo(result.stderr, err=True)
        raise typer.Exit(code=1)


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
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Execution goal: fast, balanced, or high.",
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help="Override the profile token ceiling for this run.",
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help="Override the profile active-time ceiling for this run.",
    ),
    reset: bool = typer.Option(False, "--reset", help="Abandon unfinished RE state and replan."),
    no_reuse: bool = typer.Option(
        False,
        "--no-reuse",
        help="Ignore published RE artifacts and reconstruct from source.",
    ),
) -> None:
    """Run or resume workspace reverse engineering; publish explicitly afterward."""
    args = ["--re-policy", re_policy]
    _extend_option(args, "--profile", profile)
    _extend_option(args, "--re-max-inner", re_max_inner)
    _extend_option(args, "--re-token-limit", re_token_limit)
    _extend_option(args, "--re-time-limit-minutes", re_time_limit_minutes)
    if reset:
        args.append("--reset")
    if no_reuse:
        args.append("--no-reuse")
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


@re_app.command("analyze", hidden=True)
def re_analyze(
    runs_dir: Path = typer.Argument(
        Path("runs"),
        exists=False,
        file_okay=False,
        help="An RE run directory or a directory containing RE runs.",
    ),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Analyze one RE run."),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: text or json."
    ),
) -> None:
    """Analyze RE cost, convergence, quality debt, and telemetry coverage."""
    import json
    import re

    from echelon.telemetry.re_adapter import analyze_re_run, analyze_re_runs
    from echelon.telemetry.render import analysis_to_json, render_analysis_text

    if output_format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json", param_hint="--format")
    if run_id is not None:
        if not re.fullmatch(r"re-[A-Za-z0-9._-]+", run_id):
            raise typer.BadParameter("unsafe run id", param_hint="--run-id")
        candidate = runs_dir.resolve() / run_id
        if not candidate.is_dir() or not candidate.resolve().is_relative_to(
            runs_dir.resolve()
        ):
            raise typer.BadParameter(f"RE run not found: {run_id}", param_hint="--run-id")
        reports = (analyze_re_run(candidate),)
    elif (runs_dir / "state.json").is_file() and (runs_dir / "re/state.json").is_file():
        reports = (analyze_re_run(runs_dir),)
    else:
        reports = analyze_re_runs(runs_dir)
    if output_format == "json":
        if len(reports) == 1:
            typer.echo(analysis_to_json(reports[0]), nl=False)
        else:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workflow": "re",
                        "runs": [report.to_json_dict() for report in reports],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return
    if not reports:
        typer.echo(f"No RE runs found under {runs_dir}.")
        return
    for index, report in enumerate(reports):
        if index:
            typer.echo()
        typer.echo(render_analysis_text(report), nl=False)


@spec_app.command("analyze", hidden=True)
def spec_analyze(
    path: Path = typer.Argument(
        Path("runs"),
        exists=False,
        file_okay=False,
        help="A Spec run directory or a directory containing Spec runs.",
    ),
    output_format: str = typer.Option(
        "text", "--format", help="Output format: text or json."
    ),
    health: bool = typer.Option(
        False,
        "--health",
        help="Render an observe-only reliability and telemetry exception report.",
    ),
) -> None:
    """Analyze Spec execution cost, repair loops, blockers, and telemetry."""
    import json

    from echelon.telemetry.health import analyze_spec_health
    from echelon.telemetry.render import (
        analysis_to_json,
        health_to_json,
        render_analysis_text,
        render_health_text,
    )
    from echelon.telemetry.spec_adapter import analyze_spec_run, analyze_spec_runs

    if output_format not in {"text", "json"}:
        raise typer.BadParameter("format must be text or json", param_hint="--format")
    resolved = path.resolve()
    if (resolved / "state.json").is_file():
        if (resolved / "re/state.json").is_file():
            raise typer.BadParameter("not a Spec run", param_hint="path")
        reports = (analyze_spec_run(resolved),)
    else:
        reports = analyze_spec_runs(resolved)
    if not reports:
        typer.echo(f"No Spec runs found under {path}.")
        return
    if health:
        health_report = analyze_spec_health(reports)
        typer.echo(
            (
                health_to_json(health_report)
                if output_format == "json"
                else render_health_text(health_report)
            ),
            nl=False,
        )
        return
    if output_format == "json":
        if len(reports) == 1:
            typer.echo(analysis_to_json(reports[0]), nl=False)
        else:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workflow": "spec",
                        "runs": [report.to_json_dict() for report in reports],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return
    for index, report in enumerate(reports):
        if index:
            typer.echo()
        typer.echo(render_analysis_text(report), nl=False)


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
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Autonomy mode override for legacy runs; sealed decisions keep their persisted mode.",
    ),
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
    phase_id: str = typer.Argument(..., help="Recorded checkpoint phase or ID to rewind to."),
    checkpoint_commit: Optional[str] = typer.Option(
        None,
        "--commit",
        help="Full checkpoint commit or unique abbreviated prefix.",
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Compatibility alias for spec rewind."""
    legacy_cli = _legacy_cli()

    args = [phase_id, *_ctx_args(ctx)]
    _extend_option(args, "--commit", checkpoint_commit)
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
    answer: Optional[str] = typer.Argument(
        None,
        help="Answer for an awaiting-human Phase A decision.",
    ),
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
    stash: bool = typer.Option(False, "--stash", help="Stash dirty outgoing spec changes."),
    discard: bool = typer.Option(False, "--discard", help="Discard dirty changes to checkpoint."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm destructive discard."),
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
        stash=stash,
        discard=discard,
        confirm=confirm,
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
    openai_base_url: Optional[str] = typer.Option(
        None,
        "--openai-base-url",
        help="Persist OpenAI-compatible API base URL.",
    ),
    openai_model: Optional[str] = typer.Option(
        None,
        "--openai-model",
        help="Persist OpenAI-compatible model name.",
    ),
    openai_api_key_file: Optional[str] = typer.Option(
        None,
        "--openai-api-key-file",
        help="Persist file path containing the OpenAI-compatible API key.",
    ),
    openai_api_key_env: Optional[str] = typer.Option(
        None,
        "--openai-api-key-env",
        help="Persist environment variable containing the OpenAI-compatible API key.",
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
    _extend_option(args, "--openai-base-url", openai_base_url)
    _extend_option(args, "--openai-model", openai_model)
    _extend_option(args, "--openai-api-key-file", openai_api_key_file)
    _extend_option(args, "--openai-api-key-env", openai_api_key_env)
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
    artifact_only: bool = typer.Option(
        False,
        "--artifact-only",
        help="Run only spec/Phase A artifact generation and skip delivery/build.",
    ),
    context_render: str = typer.Option(
        "bounded",
        "--context-render",
        help="Context render mode: bounded, legacy, or both.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print planned commands without running them."),
) -> None:
    """Run or print an artifact-quality benchmark variant."""
    legacy_cli = _legacy_cli()

    args = ["run", fixture_id]
    _extend_option(args, "--variant", variant)
    _extend_option(args, "--baseline-ref", baseline_ref)
    _extend_option(args, "--context-render", context_render)
    if artifact_only:
        args.append("--artifact-only")
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
    stash: bool = typer.Option(False, "--stash", help="Stash dirty outgoing spec changes."),
    discard: bool = typer.Option(False, "--discard", help="Discard dirty changes to checkpoint."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm destructive discard."),
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
    if stash:
        args.append("--stash")
    if discard:
        args.append("--discard")
    if confirm:
        args.append("--confirm")
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
    mode: Optional[str] = typer.Option(
        None,
        "--mode",
        help="Autonomy mode override for legacy runs; sealed decisions keep their persisted mode.",
    ),
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
    answer: Optional[str] = typer.Argument(
        None,
        help="Answer for an awaiting-human Phase A decision.",
    ),
) -> None:
    """Answer escalation questions from a blocked run."""
    from echelon import cli as legacy_cli

    args: list[str] = []
    if answer is not None:
        args.append(answer)
    args.extend(list(ctx.args))
    legacy_cli._cmd_spec_resume(args)


@spec_app.command("add-input")
def spec_add_input(
    input_values: Optional[list[str]] = typer.Option(
        None,
        "--input",
        help=(
            "Reference material for a parked investigation checkpoint as "
            "requirement:<path> or reference:<path>; repeat as needed."
        ),
    ),
) -> None:
    """Add declared evidence to a parked investigation access checkpoint."""
    from echelon import cli as legacy_cli

    args: list[str] = []
    _extend_repeated_option(args, "--input", input_values)
    legacy_cli._cmd_spec_add_input(args)


@spec_app.command(
    "resolve",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_resolve(
    ctx: typer.Context,
    issue_id: str = typer.Argument(..., help="SAGE issue ID, for example ISS-002."),
    decision: Optional[str] = typer.Argument(None, help="Explicit project decision for this issue."),
) -> None:
    """Record one issue decision and dispatch its targeted WHAT repair."""
    from echelon import cli as legacy_cli

    project_root = Path.cwd()
    args = [issue_id]
    if decision is not None:
        args.append(decision)
    args.extend(list(ctx.args))
    ext_dir = legacy_cli._installed_extension_or_exit(project_root)
    legacy_cli._require_provider_capability(
        "echelon spec resolve",
        legacy_cli.ProviderCapability.ARTIFACT,
        project_dir=project_root,
    )
    legacy_cli._require_phase_a_git_ownership(
        project_root, command_name="echelon spec resolve"
    )
    legacy_cli._cmd_spec_resolve(args, project_root=project_root, ext_dir=ext_dir)


@spec_app.command(
    "rewind",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_rewind(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., help="Recorded checkpoint phase or ID to rewind to."),
    checkpoint_commit: Optional[str] = typer.Option(
        None,
        "--commit",
        help="Full checkpoint commit or unique abbreviated prefix.",
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Rewind the active squad run to a safe checkpoint."""
    from pathlib import Path

    from echelon import cli as legacy_cli

    args = [phase_id, *list(ctx.args)]
    _extend_option(args, "--commit", checkpoint_commit)
    if confirm:
        args.append("--confirm")
    legacy_cli._cmd_rewind(args, project_root=Path.cwd())


@spec_app.command("repair-traceability")
def spec_repair_traceability(
    confirm: bool = typer.Option(False, "--confirm", help="Apply the safe traceability repair."),
) -> None:
    """Repair safely-prunable product-input task mappings and resume finalization."""
    from pathlib import Path

    from echelon import cli as legacy_cli

    legacy_cli._cmd_repair_traceability(
        ["--confirm"] if confirm else [], project_root=Path.cwd()
    )


@spec_app.command("switch")
def spec_switch(
    spec_or_run_id: str = typer.Argument(..., help="Checkpointed spec id or Phase A run id."),
    stash: bool = typer.Option(False, "--stash", help="Stash dirty outgoing spec changes."),
    discard: bool = typer.Option(False, "--discard", help="Discard dirty changes to the checkpoint."),
    confirm: bool = typer.Option(False, "--confirm", help="Confirm destructive discard."),
    restore_stash: bool = typer.Option(
        False,
        "--restore-stash",
        help="Restore this spec's managed stash after switching.",
    ),
) -> None:
    """Select a checkpointed Phase A spec run."""
    from echelon.spec_switch_cli import run_spec_switch_command

    args = [spec_or_run_id]
    if stash:
        args.append("--stash")
    if discard:
        args.append("--discard")
    if confirm:
        args.append("--confirm")
    if restore_stash:
        args.append("--restore-stash")
    exit_code = run_spec_switch_command(args, project_root=Path.cwd())
    if exit_code:
        raise typer.Exit(exit_code)


@spec_app.command("publish")
def spec_publish(
    spec_or_id: Optional[str] = typer.Argument(
        None,
        help="Canonical local spec branch name or unique numeric ID.",
    ),
    publish_all: bool = typer.Option(
        False,
        "--all",
        help="Publish every canonical local spec branch in one commit.",
    ),
) -> None:
    """Publish committed spec snapshots to the local default branch.

    Copies only matching specs/<id>/ trees. Uses local branches only.

    This does not merge implementation history.

    It does not fetch, push, or delete source branches.

    Selected spec paths must be clean. The default-branch worktree must be clean.
    """
    from echelon.spec_publish import SpecPublishError, publish_specs

    identity = str(spec_or_id or "").strip()
    if bool(identity) == publish_all:
        raise typer.BadParameter("choose exactly one spec identity or --all")

    try:
        result = publish_specs(
            Path.cwd(),
            identity=identity or None,
            publish_all=publish_all,
        )
    except SpecPublishError as exc:
        typer.echo(f"Spec publish failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if result.created_commit:
        typer.echo(
            f"Published specs to local {result.default_branch} commit "
            f"{result.default_commit}."
        )
    else:
        typer.echo(
            "No publication commit was needed; the local default-branch "
            "snapshots are current."
        )
    for published in result.published:
        state = "updated" if published.changed else "unchanged"
        typer.echo(
            f"  {published.spec_id}: {published.source_branch}@"
            f"{published.source_commit[:12]} ({state})"
        )
    typer.echo(
        "Source branches retained: "
        + ", ".join(item.source_branch for item in result.published)
    )
    typer.echo("Nothing was pushed, fetched, merged, or deleted.")
    typer.echo(f"Default-branch worktree: {result.destination_worktree}")
    for warning in result.warnings:
        typer.echo(f"Warning: {warning}", err=True)
    quoted_branch = shlex.quote(result.default_branch)
    typer.echo(f"To share: git push origin {quoted_branch}")
    typer.echo("Refresh navigation: echelon wiki build")


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


@graph_app.command("build")
def graph_build(
    spec_selector: str,
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Build a deterministic graph from current canonical sources."""
    from echelon.mempalace_requirements import SpecMemoryError, resolve_spec_dir
    from echelon.spec_graph import (
        SpecGraphError,
        build_spec_graph,
        write_spec_graph,
    )

    try:
        graph = build_spec_graph(Path.cwd(), spec_selector)
        spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
        if write:
            write_spec_graph(graph, spec_dir)
    except (SpecGraphError, SpecMemoryError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _echo_spec_graph_summary(graph, action="built")


@graph_workspace_app.command("build")
def graph_workspace_build(
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Compose the workspace graph from current persisted member graphs."""
    from echelon.workspace_graph import (
        WorkspaceGraphError,
        build_workspace_graph,
        write_workspace_graph,
    )

    try:
        candidate = build_workspace_graph(Path.cwd())
        if write:
            write_workspace_graph(candidate.graph, Path.cwd())
    except (WorkspaceGraphError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _echo_workspace_graph_summary(candidate, action="built")


@graph_workspace_app.command("audit")
def graph_workspace_audit(
    as_json: bool = typer.Option(False, "--json"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Audit workspace graph freshness without updating upstream members."""
    from echelon.workspace_graph import WorkspaceGraphError
    from echelon.workspace_graph_audit import (
        audit_workspace_graph,
        write_workspace_graph_audit,
    )

    try:
        report = audit_workspace_graph(Path.cwd())
        if write:
            write_workspace_graph_audit(report, Path.cwd())
    except (WorkspaceGraphError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    else:
        _echo_workspace_graph_audit(report)
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_workspace_app.command("refresh")
def graph_workspace_refresh(
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Preview or explicitly refresh workspace graph members and receipts."""
    from echelon.workspace_graph import WorkspaceGraphError
    from echelon.workspace_graph_refresh import refresh_workspace_graph

    try:
        result = refresh_workspace_graph(Path.cwd(), write=write)
    except (WorkspaceGraphError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    for outcome in result.outcomes:
        typer.echo(
            f"Workspace refresh {outcome.action}: {outcome.subject_id} "
            f"{outcome.domain} ({outcome.status or outcome.detail or 'unknown'})"
        )
    _echo_workspace_graph_summary(
        result.candidate,
        action="refreshed" if write else "previewed",
    )
    _echo_workspace_graph_audit(result.report)
    raise typer.Exit(code=_graph_exit_code(result.report.status))


@graph_workspace_app.command("export")
def graph_workspace_export(
    output_format: str = typer.Option("dot", "--format"),
    lens: str = typer.Option("portfolio", "--lens"),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    """Export a persisted workspace graph without refreshing its members."""
    from echelon.graph_visualization import (
        GraphVisualizationError,
        load_graph_document,
        render_graph_dot,
    )
    from echelon.workspace_graph import workspace_graph_path, write_workspace_graph_bytes
    from echelon.workspace_graph_audit import (
        audit_workspace_graph,
        persisted_workspace_graph_is_invalid,
    )

    try:
        if output_format != "dot":
            raise GraphVisualizationError(
                f"unsupported graph export format {output_format!r}; expected dot"
            )
        root = Path.cwd()
        report = audit_workspace_graph(root)
        if persisted_workspace_graph_is_invalid(report):
            raise GraphVisualizationError("workspace graph artifact fails its full contract")
        document = load_graph_document(workspace_graph_path(root))
        rendered = render_graph_dot(document, report, lens=lens)
        if output is None:
            typer.echo(rendered, nl=False)
        else:
            output_path = output if output.is_absolute() else root / output
            write_workspace_graph_bytes(output_path, rendered.encode("utf-8"))
            typer.echo(f"Workspace graph DOT: {output_path}")
    except (GraphVisualizationError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_workspace_app.command("view")
def graph_workspace_view(
    lens: Optional[str] = typer.Option(None, "--lens"),
    output: Optional[Path] = typer.Option(None, "--output"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Create and optionally open an offline workspace graph viewer."""
    import webbrowser

    from echelon.graph_visualization import (
        GraphVisualizationError,
        load_cytoscape_source,
        load_graph_document,
        render_graph_html,
    )
    from echelon.workspace_graph import workspace_graph_path, write_workspace_graph_bytes
    from echelon.workspace_graph_audit import (
        audit_workspace_graph,
        persisted_workspace_graph_is_invalid,
    )

    try:
        root = Path.cwd()
        report = audit_workspace_graph(root)
        if persisted_workspace_graph_is_invalid(report):
            raise GraphVisualizationError("workspace graph artifact fails its full contract")
        document = load_graph_document(workspace_graph_path(root))
        initial_lens = lens or ("exceptions" if report.findings else "portfolio")
        html = render_graph_html(
            document,
            report,
            cytoscape_source=load_cytoscape_source(),
            initial_lens=initial_lens,
        )
        output_path = output or workspace_graph_path(root).with_name("workspace.html")
        if not output_path.is_absolute():
            output_path = root / output_path
        write_workspace_graph_bytes(output_path, html.encode("utf-8"))
        typer.echo(
            f"Workspace graph viewer: {output_path} "
            f"(audit={report.status}, findings={len(report.findings)})"
        )
        if open_browser:
            try:
                opened = webbrowser.open(output_path.resolve().as_uri())
            except webbrowser.Error:
                typer.echo("warning: workspace graph viewer was not opened", err=True)
            else:
                if not opened:
                    typer.echo("warning: workspace graph viewer was not opened", err=True)
    except (GraphVisualizationError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_app.command("audit")
def graph_audit(
    spec_selector: str,
    as_json: bool = typer.Option(False, "--json"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Audit graph freshness and source coherence without mining memory."""
    from echelon.mempalace_requirements import SpecMemoryError, resolve_spec_dir
    from echelon.spec_graph import SpecGraphError
    from echelon.spec_graph_audit import (
        audit_spec_graph,
        write_spec_graph_audit,
    )

    try:
        report = audit_spec_graph(Path.cwd(), spec_selector)
        if write:
            spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
            write_spec_graph_audit(report, spec_dir)
    except (SpecGraphError, SpecMemoryError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    else:
        _echo_spec_graph_audit(report)
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_app.command("refresh")
def graph_refresh(
    spec_selector: str,
    write: bool = typer.Option(False, "--write"),
) -> None:
    """Rebuild and audit the graph without refreshing MemPalace."""
    from echelon.mempalace_requirements import SpecMemoryError, resolve_spec_dir
    from echelon.spec_graph import (
        SpecGraphError,
        build_spec_graph,
        write_spec_graph,
    )
    from echelon.spec_graph_audit import (
        audit_spec_graph,
        write_spec_graph_audit,
    )

    try:
        spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
        graph = build_spec_graph(Path.cwd(), spec_selector)
        if write:
            write_spec_graph(graph, spec_dir)
        report = audit_spec_graph(Path.cwd(), spec_selector)
        if write:
            write_spec_graph_audit(report, spec_dir)
    except (SpecGraphError, SpecMemoryError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _echo_spec_graph_summary(graph, action="refreshed")
    _echo_spec_graph_audit(report)
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_app.command("export")
def graph_export(
    spec_selector: str,
    output_format: str = typer.Option("dot", "--format"),
    lens: str = typer.Option("all", "--lens"),
    output: Optional[Path] = typer.Option(None, "--output"),
) -> None:
    """Export a persisted artifact graph without building or mining."""
    from echelon.graph_visualization import (
        GraphVisualizationError,
        load_graph_document,
        render_graph_dot,
    )
    from echelon.mempalace_requirements import (
        SpecMemoryError,
        resolve_spec_dir,
    )
    from echelon.spec_graph import GRAPH_FILENAME, SpecGraphError
    from echelon.spec_graph_audit import audit_spec_graph

    try:
        if output_format != "dot":
            raise GraphVisualizationError(
                f"unsupported graph export format {output_format!r}; expected dot"
            )
        spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
        document = load_graph_document(spec_dir / GRAPH_FILENAME)
        report = audit_spec_graph(Path.cwd(), spec_selector)
        rendered = render_graph_dot(document, report, lens=lens)
        if output is None:
            typer.echo(rendered, nl=False)
        else:
            output_path = output if output.is_absolute() else Path.cwd() / output
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered, encoding="utf-8")
            typer.echo(f"Graph DOT: {output_path}")
    except (
        GraphVisualizationError,
        SpecGraphError,
        SpecMemoryError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    raise typer.Exit(code=_graph_exit_code(report.status))


@graph_app.command("view")
def graph_view(
    spec_selector: str,
    lens: Optional[str] = typer.Option(None, "--lens"),
    output: Optional[Path] = typer.Option(None, "--output"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Create and optionally open an offline persisted-graph viewer."""
    import webbrowser

    from echelon.graph_visualization import (
        GRAPH_LENSES,
        GraphVisualizationError,
        load_cytoscape_source,
        load_graph_document,
        render_graph_html,
    )
    from echelon.mempalace_requirements import (
        SpecMemoryError,
        resolve_spec_dir,
    )
    from echelon.spec_graph import GRAPH_FILENAME, SpecGraphError
    from echelon.spec_graph_audit import audit_spec_graph

    try:
        spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
        document = load_graph_document(spec_dir / GRAPH_FILENAME)
        report = audit_spec_graph(Path.cwd(), spec_selector)
        initial_lens = lens or (
            "exceptions" if report.findings else "traceability"
        )
        if initial_lens not in GRAPH_LENSES:
            raise GraphVisualizationError(
                f"unknown graph lens {initial_lens!r}; "
                f"expected one of {', '.join(GRAPH_LENSES)}"
            )
        html = render_graph_html(
            document,
            report,
            cytoscape_source=load_cytoscape_source(),
            initial_lens=initial_lens,
        )
        output_path = output or (
            Path.cwd() / ".echelon" / "graph" / f"{spec_dir.name}.html"
        )
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html, encoding="utf-8")
        typer.echo(
            f"Graph viewer: {output_path} "
            f"(audit={report.status}, findings={len(report.findings)})"
        )
        if open_browser:
            webbrowser.open(output_path.resolve().as_uri())
    except (
        GraphVisualizationError,
        SpecGraphError,
        SpecMemoryError,
        OSError,
        ValueError,
    ) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    raise typer.Exit(code=_graph_exit_code(report.status))


@spec_memory_app.command("mine")
def spec_memory_mine(
    spec_selector: str,
    write_report: bool = typer.Option(False, "--write-report"),
) -> None:
    from echelon.mempalace_requirements import SpecMemoryError, mine_spec_requirements

    try:
        report = mine_spec_requirements(Path.cwd(), spec_selector, run_id="manual")
        if report.status == "complete":
            _cleanup_stale_memory_best_effort(Path.cwd(), spec_selector)
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"MemPalace mine {report.status}: expected={report.expected_count} "
        f"written={report.written_count} adopted={report.adopted_count} "
        f"drifted={report.drifted_count} failed={report.failed_count}"
    )
    if write_report and report.status != "unavailable":
        spec_dir = Path(report.spec_dir)
        spec_dir.joinpath("mempalace-mine.json").write_text(
            __import__("json").dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_memory_app.command("audit")
def spec_memory_audit(
    spec_selector: str,
    as_json: bool = typer.Option(False, "--json"),
    write: bool = typer.Option(False, "--write"),
    probe_retrieval: bool = typer.Option(False, "--probe-retrieval"),
) -> None:
    from echelon.mempalace_audit import audit_spec_memory, render_audit_markdown, write_audit_reports
    from echelon.mempalace_requirements import SpecMemoryError

    try:
        report = audit_spec_memory(Path.cwd(), spec_selector, probe_retrieval=probe_retrieval)
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if write and report.status != "unavailable":
        write_audit_reports(report, Path(report.spec_dir))
    if as_json:
        _echo_json(report.to_dict())
    else:
        typer.echo(render_audit_markdown(report).rstrip())
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_memory_app.command("refresh")
def spec_memory_refresh(
    spec_selector: str,
    audit: bool = typer.Option(True, "--audit/--no-audit"),
    write: bool = typer.Option(False, "--write"),
) -> None:
    from echelon.mempalace_audit import audit_spec_memory, render_audit_markdown, write_audit_reports
    from echelon.mempalace_requirements import mine_spec_requirements
    from echelon.mempalace_requirements import SpecMemoryError

    try:
        mine_report = mine_spec_requirements(Path.cwd(), spec_selector, run_id="manual")
        if mine_report.status == "complete":
            _cleanup_stale_memory_best_effort(Path.cwd(), spec_selector)
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(
        f"MemPalace mine {mine_report.status}: expected={mine_report.expected_count} "
        f"written={mine_report.written_count} adopted={mine_report.adopted_count} "
        f"drifted={mine_report.drifted_count} failed={mine_report.failed_count}"
    )
    if not audit:
        raise typer.Exit(code=_memory_exit_code(mine_report.status))
    try:
        audit_report = audit_spec_memory(Path.cwd(), spec_selector)
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if write and audit_report.status != "unavailable":
        write_audit_reports(audit_report, Path(audit_report.spec_dir))
    typer.echo(render_audit_markdown(audit_report).rstrip())
    raise typer.Exit(code=max(_memory_exit_code(mine_report.status), _memory_exit_code(audit_report.status)))


@memory_app.command("search")
def memory_search(
    query: str,
    room: Optional[str] = typer.Option(None, "--room", help="Restrict search to one memory room."),
    spec: Optional[str] = typer.Option(None, "--spec", help="Restrict results to one spec slug."),
    kind: Optional[str] = typer.Option(None, "--kind", help="Restrict to one memory artifact kind."),
    limit: int = typer.Option(10, "--limit", "-n", min=1, max=100),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.workspace_memory_search import WorkspaceMemorySearchError, search_workspace_memory

    try:
        report = search_workspace_memory(
            Path.cwd(),
            query,
            room=room,
            spec=spec,
            kind=kind,
            limit=limit,
        )
    except WorkspaceMemorySearchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    else:
        _echo_memory_search(report)


@memory_app.command("list-rooms")
def memory_list_rooms(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.workspace_memory_search import WorkspaceMemorySearchError, list_workspace_memory_facets

    try:
        report = list_workspace_memory_facets(Path.cwd())
    except WorkspaceMemorySearchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"wing": report.wing, "rooms": report.rooms})
    else:
        _echo_memory_facet("MemPalace rooms", report.rooms)


@memory_app.command("list-specs")
def memory_list_specs(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.workspace_memory_search import WorkspaceMemorySearchError, list_workspace_memory_facets

    try:
        report = list_workspace_memory_facets(Path.cwd())
    except WorkspaceMemorySearchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"wing": report.wing, "specs": report.specs})
    else:
        _echo_memory_facet("MemPalace specs", report.specs)


@memory_app.command("list-kinds")
def memory_list_kinds(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.workspace_memory_search import WorkspaceMemorySearchError, list_workspace_memory_facets

    try:
        report = list_workspace_memory_facets(Path.cwd())
    except WorkspaceMemorySearchError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"wing": report.wing, "kinds": report.kinds})
    else:
        _echo_memory_facet("MemPalace kinds", report.kinds)


@re_memory_app.command("refresh")
def re_memory_refresh(
    audit: bool = typer.Option(True, "--audit/--no-audit"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.mempalace_re import audit_re_memory, mine_re_memory
    from echelon.mempalace_requirements import SpecMemoryError

    try:
        report = mine_re_memory(Path.cwd(), run_id="manual")
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json and not audit:
        _echo_json(report.to_dict())
    elif not as_json:
        typer.echo(
            f"MemPalace RE mine {report.status}: artifacts={report.artifact_count} "
            f"expected={report.expected_count} written={report.written_count} "
            f"adopted={report.adopted_count} drifted={report.drifted_count} "
            f"failed={report.failed_count}"
        )
    if not audit:
        raise typer.Exit(code=_memory_exit_code(report.status))
    try:
        audit_report = audit_re_memory(Path.cwd())
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"mine": report.to_dict(), "audit": audit_report.to_dict()})
    else:
        typer.echo(_render_re_memory_audit_markdown(audit_report).rstrip())
    raise typer.Exit(code=max(_memory_exit_code(report.status), _memory_exit_code(audit_report.status)))


@re_memory_app.command("audit")
def re_memory_audit(
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    from echelon.mempalace_re import audit_re_memory
    from echelon.mempalace_requirements import SpecMemoryError

    try:
        report = audit_re_memory(Path.cwd())
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    else:
        typer.echo(_render_re_memory_audit_markdown(report).rstrip())
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_evidence_memory_app.command("refresh")
def spec_evidence_memory_refresh(
    spec_selector: str,
    audit: bool = typer.Option(True, "--audit/--no-audit"),
    as_json: bool = typer.Option(False, "--json"),
    allow_unlanded: bool = typer.Option(
        False,
        "--allow-unlanded",
        help="Mine evidence for a spec whose frontmatter status is not landed.",
    ),
) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import (
        audit_spec_evidence_memory,
        mine_spec_evidence_memory,
    )

    try:
        report = mine_spec_evidence_memory(
            Path.cwd(),
            spec_selector,
            run_id="manual",
            allow_unlanded=allow_unlanded,
        )
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json and not audit:
        _echo_json(report.to_dict())
    elif not as_json:
        typer.echo(
            f"MemPalace spec evidence mine {report.status}: "
            f"spec={report.spec_id} artifacts={report.artifact_count} "
            f"expected={report.expected_count} written={report.written_count} "
            f"adopted={report.adopted_count} drifted={report.drifted_count} "
            f"failed={report.failed_count}"
        )
    if not audit:
        raise typer.Exit(code=_memory_exit_code(report.status))
    try:
        audit_report = audit_spec_evidence_memory(
            Path.cwd(),
            spec_selector,
            allow_unlanded=allow_unlanded,
        )
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json({"mine": report.to_dict(), "audit": audit_report.to_dict()})
    else:
        typer.echo(_render_spec_evidence_memory_audit_markdown(audit_report).rstrip())
    raise typer.Exit(code=max(_memory_exit_code(report.status), _memory_exit_code(audit_report.status)))


@spec_evidence_memory_app.command("audit")
def spec_evidence_memory_audit(
    spec_selector: str,
    as_json: bool = typer.Option(False, "--json"),
    allow_unlanded: bool = typer.Option(
        False,
        "--allow-unlanded",
        help="Audit evidence for a spec whose frontmatter status is not landed.",
    ),
) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import audit_spec_evidence_memory

    try:
        report = audit_spec_evidence_memory(
            Path.cwd(),
            spec_selector,
            allow_unlanded=allow_unlanded,
        )
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    else:
        typer.echo(_render_spec_evidence_memory_audit_markdown(report).rstrip())
    raise typer.Exit(code=_memory_exit_code(report.status))


@spec_evidence_app.command("publish")
def spec_evidence_publish(
    spec_selector: Optional[str] = typer.Argument(None),
    all_specs: bool = typer.Option(False, "--all", help="Publish evidence packages for all published specs."),
    run_id: Optional[str] = typer.Option(None, "--from-run", help="Use a specific run id below runs/."),
    as_json: bool = typer.Option(False, "--json"),
    allow_unlanded: bool = typer.Option(
        False,
        "--allow-unlanded",
        help="Publish evidence for a spec whose frontmatter status is not landed.",
    ),
) -> None:
    from echelon.mempalace_requirements import SpecMemoryError
    from echelon.mempalace_spec_evidence import (
        publish_all_spec_evidence_packages,
        publish_spec_evidence_package,
    )

    try:
        if all_specs:
            report = publish_all_spec_evidence_packages(
                Path.cwd(),
                allow_unlanded=allow_unlanded,
            )
        else:
            if spec_selector is None:
                typer.echo("spec selector is required unless --all is used", err=True)
                raise typer.Exit(code=2)
            report = publish_spec_evidence_package(
                Path.cwd(),
                spec_selector,
                run_id=run_id,
                allow_unlanded=allow_unlanded,
            )
    except SpecMemoryError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    if as_json:
        _echo_json(report.to_dict())
    elif all_specs:
        typer.echo(
            f"Spec evidence packages {report.status}: total={report.total_count} "
            f"published={report.published_count} failed={report.failed_count}"
        )
    else:
        typer.echo(
            f"Spec evidence package {report.status}: spec={report.spec_id} "
            f"artifacts={report.published_count} skipped={report.skipped_count}"
        )
        typer.echo(f"Evidence dir: {report.evidence_dir}")
    raise typer.Exit(code=0 if report.status in {"published", "complete"} else 1)


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


@spec_app.command(
    "amend",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_amend(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Planned spec id to amend."),
    description: str = typer.Argument(..., help="Product change summary."),
    input_values: Optional[list[str]] = typer.Option(
        None,
        "--input",
        help="Product input as requirement:<path> or reference:<path>; repeat as needed.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview baseline and inputs without mutation."),
) -> None:
    """Prepare an isolated amendment for an unbuilt spec."""
    from echelon import cli as legacy_cli

    args = [spec_id, description, *list(ctx.args)]
    _extend_repeated_option(args, "--input", input_values)
    if dry_run:
        args.append("--dry-run")
    legacy_cli._cmd_spec_amend(args)


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


def run(argv: list[str] | None = None) -> int | None:
    """Run the Typer CLI app with an explicit argv for tests or sys.argv[1:]."""
    if argv in (["-v"], ["--version"], ["version"]):
        legacy_cli = _legacy_cli()
        typer.echo(f"echelon {legacy_cli.CLI_VERSION}")
        return
    from echelon.wiki import service as wiki_service

    project_root = Path.cwd()
    try:
        before = wiki_service.capture_input_snapshot(project_root)
    except Exception:
        before = None
    exit_code = app(args=argv, standalone_mode=False)
    try:
        refreshed = wiki_service.refresh_after_changed_command(project_root, before)
    except Exception as exc:
        typer.echo(f"warning: wiki auto-refresh failed: {exc}", err=True)
    else:
        if refreshed is not None:
            typer.echo(f"Wiki auto-refreshed: {refreshed.home_path}")
    return exit_code
