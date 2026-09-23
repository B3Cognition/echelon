"""Typer front door for Echelon's user-facing CLI.

This module owns modern command parsing while delegating execution to the
existing handlers in ``echelon.cli``. Keeping the execution layer unchanged lets
Echelon normalize CLI contracts incrementally without rewriting harness logic.
"""

from __future__ import annotations

import json
import shlex
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

import typer

from harness.verbosity import verbose_mode


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
    help="Stack detection, preflight, and provisioning commands.",
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
        "  verify-local <spec_id> [--target <target-id>] [--engine auto|docker|podman]\n"
        "  cleanup-local <local-run-id>\n"
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
        "  run <description> [--mode semi|banzai|guided] [--reset] [--perfectionist]\n"
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
        "  defer-runnability <spec_id> --reason <owner-approved reason>\n"
        "                    Defer a failed user-runnability gate to advisory follow-up.\n"
        "  plan-runnability <spec_id>\n"
        "                    Restore a deferred user-runnability gate to current work.\n"
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
topology_app = typer.Typer(
    add_completion=False,
    help="Audit and inspect canonical source topology.",
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
    help="Compatibility aliases for delivery commands.",
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


class ReEngine(str, Enum):
    V1 = "v1"
    V2 = "v2"


class ReGoal(str, Enum):
    BASELINE = "baseline"
    INVENTORY = "inventory"


class ReKnowledgeDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class ReDeepeningLayer(str, Enum):
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


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
app.add_typer(topology_app, name="topology")
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


@harness_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_run(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to deliver."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode."),
) -> None:
    """Compatibility alias for ``echelon delivery run``."""
    delivery_run(
        ctx,
        spec_id,
        mode=mode,
        strategy=None,
        max_outer=None,
        max_inner=None,
        token_budget=None,
        auto_merge=None,
        kill_losers=False,
        reset=False,
    )


@harness_app.command(
    "land",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def harness_land(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to land."),
    continue_landing: bool = typer.Option(False, "--continue", help="Resume landing."),
) -> None:
    """Compatibility alias for ``echelon delivery land``."""
    delivery_land(
        ctx,
        spec_id,
        continue_=continue_landing,
        prepare_only=False,
        no_autoresolve=False,
        allow_fulfillment_gaps=False,
        strategy=None,
    )


@harness_app.command("continue", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def harness_continue(ctx: typer.Context, spec_id: str = typer.Argument(...)) -> None:
    delivery_continue(ctx, spec_id, mode=None, strategy=None)


@harness_app.command("resume", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def harness_resume(
    ctx: typer.Context,
    spec_id: str = typer.Argument(...),
    answer: Optional[str] = typer.Argument(None),
) -> None:
    delivery_resume(ctx, spec_id, answer=answer, mode=None, strategy=None)


class TopologyDirection(str, Enum):
    """Accepted stored-edge directions for topology neighbors."""

    incoming = "in"
    outgoing = "out"
    both = "both"


def _emit_topology_result(result: object) -> None:
    stdout = str(getattr(result, "stdout", ""))
    stderr = str(getattr(result, "stderr", ""))
    exit_code = int(getattr(result, "exit_code", 2))
    if stdout:
        typer.echo(stdout, nl=False)
    if stderr:
        typer.echo(stderr, err=True, nl=False)
    if exit_code:
        raise typer.Exit(code=exit_code)


@topology_app.command("audit")
def topology_audit(
    source: Optional[str] = typer.Option(None, "--source", help="Audit one configured source ID."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Audit canonical topology structure, providers, and live freshness."""
    from echelon.topology_cli import audit_command

    _emit_topology_result(audit_command(Path.cwd(), source=source, as_json=as_json))


@topology_app.command("list-sources")
def topology_list_sources(
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List configured sources represented by canonical topology."""
    from echelon.topology_cli import list_sources_command

    _emit_topology_result(list_sources_command(Path.cwd(), as_json=as_json))


@topology_app.command("search")
def topology_search(
    query: str = typer.Argument(..., metavar="QUERY", help="Lexical node query."),
    source: Optional[str] = typer.Option(None, "--source", help="Read one configured source ID."),
    node_types: Optional[list[str]] = typer.Option(
        None,
        "--type",
        help="Node type filter; repeat for multiple types.",
    ),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="Maximum result nodes."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Search canonical topology nodes deterministically."""
    from echelon.topology_cli import search_command

    _emit_topology_result(
        search_command(
            Path.cwd(),
            query,
            source=source,
            node_types=tuple(node_types or ()),
            limit=limit,
            as_json=as_json,
        )
    )


@topology_app.command("explain")
def topology_explain(
    node: str = typer.Argument(..., metavar="NODE", help="Exact or unambiguous topology node selector."),
    source: Optional[str] = typer.Option(None, "--source", help="Read one configured source ID."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Explain one topology node and its direct relationships."""
    from echelon.topology_cli import explain_command

    _emit_topology_result(
        explain_command(Path.cwd(), node, source=source, as_json=as_json)
    )


@topology_app.command("neighbors")
def topology_neighbors(
    node: str = typer.Argument(..., help="Exact or unambiguous topology node selector."),
    source: Optional[str] = typer.Option(None, "--source", help="Read one configured source ID."),
    direction: TopologyDirection = typer.Option(
        TopologyDirection.both,
        "--direction",
        help="Stored edge direction: in, out, or both.",
    ),
    relations: Optional[list[str]] = typer.Option(
        None,
        "--relation",
        help="Relationship filter; repeat for multiple types.",
    ),
    limit: int = typer.Option(50, "--limit", min=1, max=500, help="Maximum relationships."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List deterministic one-hop topology relationships."""
    from echelon.topology_cli import neighbors_command

    _emit_topology_result(
        neighbors_command(
            Path.cwd(),
            node,
            source=source,
            direction=direction.value,
            relations=tuple(relations or ()),
            limit=limit,
            as_json=as_json,
        )
    )


@topology_app.command("impact")
def topology_impact(
    node: str = typer.Argument(..., help="Exact or unambiguous topology node selector."),
    source: Optional[str] = typer.Option(None, "--source", help="Read one configured source ID."),
    max_depth: int = typer.Option(
        3,
        "--max-depth",
        min=1,
        max=10,
        help="Maximum impact depth.",
    ),
    relations: Optional[list[str]] = typer.Option(
        None,
        "--relation",
        help="Relationship filter; repeat for multiple types.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Traverse deterministic affected topology paths."""
    from echelon.topology_cli import impact_command

    _emit_topology_result(
        impact_command(
            Path.cwd(),
            node,
            source=source,
            max_depth=max_depth,
            relations=tuple(relations or ()),
            as_json=as_json,
        )
    )


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


def _graph_renderer(renderer: str) -> str:
    normalized = renderer.casefold()
    if normalized in {"cytoscape", "vis"}:
        return normalized
    raise ValueError(
        f"unknown graph renderer {renderer!r}; expected cytoscape or vis"
    )


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


def _run_graph_consumption(
    command: str,
    spec: Optional[str],
    as_json: bool,
    request: dict[str, object],
    operation: Callable[[object], object],
) -> None:
    """Load one read scope, execute one traversal, and preserve audit exits."""
    from echelon.graph_output import graph_result_payload, render_graph_result_text
    from echelon.graph_read import GraphReadError, graph_read_exit_code, load_graph

    try:
        model = load_graph(Path.cwd(), spec)
        result = operation(model)
    except (GraphReadError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc

    if as_json:
        _echo_json(graph_result_payload(model, command, request, result))  # type: ignore[arg-type]
    else:
        typer.echo(render_graph_result_text(model, command, result))  # type: ignore[arg-type]
    raise typer.Exit(code=graph_read_exit_code(model))


def _positive_graph_bound(value: int, option: str) -> int:
    if value <= 0:
        raise ValueError(f"{option} must be positive")
    return value


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


@app.callback()
def root(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show the Echelon CLI version and exit.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Suppress provider diagnostics and verbose failure captures.",
    ),
) -> None:
    """Echelon CLI."""
    if version:
        from echelon.version import CLI_VERSION

        typer.echo(f"echelon {CLI_VERSION}")
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
    from echelon.version import CLI_VERSION

    typer.echo(f"echelon {CLI_VERSION}")


@re_app.command("run")
def re_run(
    depth: Optional[ReKnowledgeDepth] = typer.Option(
        None,
        "--depth",
        case_sensitive=True,
        help="Knowledge depth: quick, standard (default), or deep.",
    ),
    re_policy: str = typer.Option(
        "changed",
        "--re-policy",
        help="Workspace RE policy: none, cached-only, changed, or refresh-all.",
        hidden=True,
    ),
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets.",
        hidden=True,
    ),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Execution goal: fast, balanced, or high.",
        hidden=True,
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help="Override the profile token ceiling for this run.",
        hidden=True,
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help="Override the profile active-time ceiling for this run.",
        hidden=True,
    ),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Abandon unfinished RE state and replan.",
        hidden=True,
    ),
    no_reuse: bool = typer.Option(
        False,
        "--no-reuse",
        help="Ignore published RE artifacts and reconstruct from source.",
        hidden=True,
    ),
    engine: Optional[ReEngine] = typer.Option(
        None,
        "--engine",
        case_sensitive=True,
        help="Compatibility engine override: v1 or pinned v2.",
        hidden=True,
    ),
    shadow: bool = typer.Option(
        False,
        "--shadow",
        help="For v2 only, explain the authoritative plan without dispatching work.",
        hidden=True,
    ),
    goal: list[ReGoal] = typer.Option(
        [],
        "--goal",
        case_sensitive=True,
        help="For v2 only: baseline (default) or inventory.",
        hidden=True,
    ),
) -> None:
    """Analyze the workspace and publish one validated knowledge generation."""
    from echelon.re_service import ReRunRequest, run_re

    legacy = bool(
        engine is not None
        or shadow
        or goal
        or re_max_inner is not None
        or profile is not None
        or reset
        or no_reuse
        or re_policy != "changed"
    )
    if legacy and depth is not None:
        raise typer.BadParameter(
            "--depth cannot be combined with legacy RE controls",
            param_hint="--depth",
        )
    if len(goal) > 1:
        raise typer.BadParameter("--goal may be supplied only once", param_hint="--goal")
    if goal and engine is not ReEngine.V2:
        raise typer.BadParameter("--goal is valid only with --engine v2", param_hint="--goal")
    run_re(
        ReRunRequest(
            depth=depth.value if depth is not None else None,
            re_policy=re_policy,
            re_max_inner=re_max_inner,
            profile=profile,
            re_token_limit=re_token_limit,
            re_time_limit_minutes=re_time_limit_minutes,
            reset=reset,
            no_reuse=no_reuse,
            engine=engine.value if engine is not None else None,
            shadow=shadow,
            goals=tuple(item.value for item in goal),
        )
    )


@re_app.command("refresh")
def re_refresh(
    source: list[str] = typer.Option(
        [],
        "--source",
        help="Repeat for each declared source to check; omit to check all sources.",
    ),
    depth: Optional[ReKnowledgeDepth] = typer.Option(
        None,
        "--depth",
        case_sensitive=True,
        help="Override knowledge depth: quick, standard, or deep.",
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help="Advanced absolute token ceiling for newly analyzed work.",
        hidden=True,
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help="Advanced absolute active-time ceiling for newly analyzed work.",
        hidden=True,
    ),
) -> None:
    """Check selected sources and atomically publish affected knowledge."""
    from echelon.re_service import ReRefreshRequest, refresh_re

    refresh_re(
        ReRefreshRequest(
            sources=tuple(source),
            depth=depth.value if depth is not None else None,
            re_token_limit=re_token_limit,
            re_time_limit_minutes=re_time_limit_minutes,
        )
    )


@re_app.command("deepen")
def re_deepen(
    target_layer: ReDeepeningLayer = typer.Option(
        ...,
        "--to",
        case_sensitive=True,
        help="Registered deeper layer to generate: L2, L3, or L4.",
    ),
    all_sources: bool = typer.Option(
        False,
        "--all",
        help="Deepen every source and domain from the completed parent.",
    ),
    source: list[str] = typer.Option(
        [],
        "--source",
        help="Repeat for each source ID to deepen.",
    ),
    domain: list[str] = typer.Option(
        [],
        "--domain",
        help="Repeat for a domain ID within exactly one selected source.",
    ),
    from_run: Optional[str] = typer.Option(
        None,
        "--from-run",
        help="Completed RE v2 parent run; defaults to the active RE run.",
    ),
    token_limit: Optional[int] = typer.Option(
        None,
        "--token-limit",
        min=1,
        help="Authorize the child run's token ceiling.",
    ),
    active_ms_limit: Optional[int] = typer.Option(
        None,
        "--active-ms-limit",
        min=1,
        help="Authorize the child run's active-time ceiling in milliseconds.",
    ),
    semantic_token_limit: Optional[int] = typer.Option(
        None,
        "--semantic-token-limit",
        min=1,
        help="For L3, authorize the independent semantic token ceiling.",
    ),
    semantic_active_ms_limit: Optional[int] = typer.Option(
        None,
        "--semantic-active-ms-limit",
        min=1,
        help="For L3, authorize the independent semantic active-time ceiling.",
    ),
    new_audit_epoch: bool = typer.Option(
        False,
        "--new-audit-epoch",
        help="For L3, explicitly create the next audit epoch from an eligible parent.",
    ),
    shadow: bool = typer.Option(
        False,
        "--shadow",
        help="For L4, validate and preview exact work without mutation or dispatch.",
    ),
) -> None:
    """Deepen a completed RE v2 run to L2, L3, or L4.

    L4 automatically creates or reuses its required L3 prerequisite. If that
    prerequisite pauses, run the copy-paste continuation command shown in the
    status output, then rerun the same deepen command after L3 completes.
    """
    from echelon.re_service import ReDeepenRequest, deepen_re

    if all_sources and (source or domain):
        raise typer.BadParameter(
            "--all cannot be combined with --source or --domain",
            param_hint="--all",
        )
    if not all_sources and not source:
        raise typer.BadParameter(
            "exactly one selector form is required: --all or --source",
            param_hint="--source",
        )
    if domain and len(source) != 1:
        raise typer.BadParameter(
            "--domain requires exactly one --source",
            param_hint="--domain",
        )
    if target_layer is not ReDeepeningLayer.L3 and (
        semantic_token_limit is not None
        or semantic_active_ms_limit is not None
        or new_audit_epoch
    ):
        raise typer.BadParameter(
            "semantic limits and --new-audit-epoch are valid only for L3",
            param_hint="--to",
        )
    if shadow and target_layer is not ReDeepeningLayer.L4:
        raise typer.BadParameter("--shadow is valid only for L4", param_hint="--shadow")
    if shadow and (token_limit is not None or active_ms_limit is not None):
        raise typer.BadParameter(
            "L4 --shadow cannot be combined with resource authorization",
            param_hint="--shadow",
        )
    deepen_re(
        ReDeepenRequest(
            target_layer=target_layer.value,
            all_sources=all_sources,
            sources=tuple(source),
            domains=tuple(domain),
            from_run=from_run,
            token_limit=token_limit,
            active_ms_limit=active_ms_limit,
            semantic_token_limit=semantic_token_limit,
            semantic_active_ms_limit=semantic_active_ms_limit,
            new_audit_epoch=new_audit_epoch,
            shadow=shadow,
        )
    )


@re_app.command("status")
def re_status(
    run_id: Optional[str] = typer.Argument(
        None,
        help="RE run id below runs/; defaults to the active RE run.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Render the authoritative v2 status document as JSON.",
    ),
) -> None:
    """Show live RE state, source quality, debt, and the next safe action."""
    from echelon.re_service import ReStatusRequest, show_re_status

    show_re_status(ReStatusRequest(run_id=run_id, as_json=as_json))


@re_app.command("continue")
def re_continue(
    run_id: Optional[str] = typer.Argument(
        None,
        help="RE v2 run ID below runs/; defaults to the active RE run.",
    ),
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets before continuing.",
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help=(
            "Set a higher absolute total token ceiling for the active run; "
            "this is not an increment."
        ),
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help=(
            "Set a higher absolute total active-time ceiling in minutes; "
            "this is not an increment."
        ),
    ),
    re_semantic_token_limit: Optional[int] = typer.Option(
        None,
        "--re-semantic-token-limit",
        min=1,
        help=(
            "Set a higher absolute total token ceiling for the active L3 "
            "semantic pool."
        ),
    ),
    re_semantic_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-semantic-time-limit-minutes",
        min=1,
        help=(
            "Set a higher absolute total active-time ceiling in minutes for "
            "the active L3 semantic pool."
        ),
    ),
) -> None:
    """Continue the active RE run without a human answer."""
    from echelon.re_service import ReContinueRequest, continue_re

    continue_re(
        ReContinueRequest(
            run_id=run_id,
            re_max_inner=re_max_inner,
            re_token_limit=re_token_limit,
            re_time_limit_minutes=re_time_limit_minutes,
            re_semantic_token_limit=re_semantic_token_limit,
            re_semantic_time_limit_minutes=re_semantic_time_limit_minutes,
        )
    )


@re_app.command("resume")
def re_resume(
    answer: Optional[str] = typer.Argument(
        None,
        help="Custom guidance for the active RE human blocker.",
    ),
    recommended: bool = typer.Option(
        False,
        "--recommended",
        help="Use Echelon's installed conservative convergence guidance.",
    ),
    banzai: bool = typer.Option(
        False,
        "--banzai",
        help=(
            "Authorize one automatic successor which may finish with "
            "documented residual debt."
        ),
    ),
    re_max_inner: Optional[int] = typer.Option(
        None,
        "--re-max-inner",
        min=1,
        help="Raise source-local RE repair budgets before resuming.",
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help="Raise the active run's token ceiling without resetting it.",
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help="Raise the active run's active-time ceiling without resetting it.",
    ),
    re_semantic_token_limit: Optional[int] = typer.Option(
        None,
        "--re-semantic-token-limit",
        min=1,
        help="Set the absolute L3 semantic token ceiling for the successor.",
    ),
    re_semantic_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-semantic-time-limit-minutes",
        min=1,
        help="Set the absolute L3 semantic active-time ceiling in minutes.",
    ),
) -> None:
    """Resume with exactly one custom, recommended, or bounded Banzai mode."""
    selected_modes = int(answer is not None) + int(recommended) + int(banzai)
    if selected_modes != 1:
        raise typer.BadParameter(
            'exactly one resume mode is required: "<guidance>", '
            "--recommended, or --banzai",
            param_hint="answer/--recommended/--banzai",
        )

    from echelon.re_service import ReResumeRequest, resume_re

    resume_re(
        ReResumeRequest(
            answer=answer,
            recommended=recommended,
            banzai=banzai,
            re_max_inner=re_max_inner,
            re_token_limit=re_token_limit,
            re_time_limit_minutes=re_time_limit_minutes,
            re_semantic_token_limit=re_semantic_token_limit,
            re_semantic_time_limit_minutes=re_semantic_time_limit_minutes,
        )
    )


@re_app.command("publish")
def re_publish(
    run_id: str = typer.Argument(..., metavar="RUN_ID", help="Run id below runs/ or squad/."),
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
    from echelon.re_service import RePublishRequest, publish_re

    publish_re(
        RePublishRequest(
            run_id=run_id,
            allow_partial=allow_partial,
            commit=commit,
        )
    )


@re_app.command("finalize")
def re_finalize(
    run_id: Optional[str] = typer.Argument(
        None,
        help="Blocked RE run id below runs/; defaults to the active RE run.",
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Acknowledge unresolved debt and finalize as partial.",
    ),
) -> None:
    """Finalize a structurally publishable blocked RE run with explicit debt."""
    from echelon.re_service import ReFinalizeRequest, finalize_re

    finalize_re(
        ReFinalizeRequest(run_id=run_id, allow_partial=allow_partial)
    )


@re_app.command("synthesize")
def re_synthesize(
    run_id: Optional[str] = typer.Argument(
        None,
        help="Finalized partial RE run id; defaults to the active RE run.",
    ),
    allow_partial: bool = typer.Option(
        False,
        "--allow-partial",
        help="Use accepted partial source results as synthesis inputs.",
    ),
    re_token_limit: Optional[int] = typer.Option(
        None,
        "--re-token-limit",
        min=1,
        help="Raise the run token ceiling for the synthesis dispatch.",
    ),
    re_time_limit_minutes: Optional[int] = typer.Option(
        None,
        "--re-time-limit-minutes",
        min=1,
        help="Raise the run active-time ceiling for the synthesis dispatch.",
    ),
    from_run: Optional[str] = typer.Option(
        None,
        "--from-run",
        help="Create or reuse an exact protocol-2.7 synthesis child.",
    ),
    accept_partial: Optional[list[str]] = typer.Option(
        None,
        "--accept-partial",
        help="Accept one authenticated partial source; repeat per source.",
    ),
    token_limit: Optional[int] = typer.Option(
        None,
        "--token-limit",
        min=1,
        help="Set the immutable protocol-2.7 synthesis token ceiling.",
    ),
    active_ms_limit: Optional[int] = typer.Option(
        None,
        "--active-ms-limit",
        min=1,
        help="Set the immutable protocol-2.7 synthesis active-time ceiling.",
    ),
) -> None:
    """Regenerate workspace synthesis from finalized partial source results."""
    from echelon.re_service import ReSynthesizeRequest, synthesize_re

    if from_run is not None:
        if run_id is not None or allow_partial or re_token_limit is not None or re_time_limit_minutes is not None:
            raise typer.BadParameter(
                "--from-run cannot be combined with legacy run-id/--allow-partial/--re-* options",
                param_hint="--from-run",
            )
        synthesize_re(
            ReSynthesizeRequest(
                from_run=from_run,
                accept_partial=tuple(accept_partial or ()),
                token_limit=token_limit,
                active_ms_limit=active_ms_limit,
            )
        )
        return
    if accept_partial or token_limit is not None or active_ms_limit is not None:
        raise typer.BadParameter(
            "--accept-partial, --token-limit, and --active-ms-limit require --from-run",
            param_hint="--from-run",
        )
    synthesize_re(
        ReSynthesizeRequest(
            run_id=run_id,
            allow_partial=allow_partial,
            re_token_limit=re_token_limit,
            re_time_limit_minutes=re_time_limit_minutes,
        )
    )


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
    from echelon.re_service import execute_re_run

    execute_re_run(run_id=run_id)


@re_app.command("check-domain", hidden=True)
def re_check_domain(
    run_id: str = typer.Argument(..., help="Run id below runs/."),
    source_id: str = typer.Argument(..., help="Source id from the RE plan."),
    domain_id: str = typer.Argument(..., help="Domain id from the source manifest."),
) -> None:
    """Check one staged source-domain spec before the agent returns DONE."""
    from echelon.re_service import check_re_domain

    check_re_domain(run_id=run_id, source_id=source_id, domain_id=domain_id)


@app.command("init", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_init() -> None:
    """Compatibility alias for workspace init."""
    from echelon.workspace_service import initialize_workspace

    initialize_workspace(Path.cwd())


@app.command("artifacts", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_artifacts(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to index."),
) -> None:
    """Compatibility alias for spec artifact indexing."""
    spec_artifacts(ctx, spec_id)


@app.command("status", hidden=True)
def root_status() -> None:
    """Compatibility alias for spec status."""
    spec_status()


@app.command("land", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_land(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to land."),
    continue_: bool = typer.Option(False, "--continue", help="Resume an interrupted land operation."),
    prepare_only: bool = typer.Option(False, "--prepare-only", help="Prepare landing artifacts without merging."),
    no_autoresolve: bool = typer.Option(False, "--no-autoresolve", help="Disable automatic local conflict resolution."),
    allow_fulfillment_gaps: bool = typer.Option(False, "--allow-fulfillment-gaps", help="Allow landing with open fulfillment gaps."),
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Landing strategy, usually merge or rebase."),
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


@app.command("continue", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_continue(
    ctx: typer.Context,
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode override for legacy runs."),
) -> None:
    """Compatibility alias for spec continue."""
    spec_continue(ctx, mode=mode)


@app.command("rewind", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_rewind(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., metavar="CHECKPOINT", help="Recorded checkpoint phase or ID to rewind to."),
    checkpoint_commit: Optional[str] = typer.Option(None, "--commit", help="Full checkpoint commit or unique abbreviated prefix."),
    checkpoint_next_phase: Optional[str] = typer.Option(None, "--next-phase", help="Exact next phase recorded by the selected checkpoint row."),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Compatibility alias for spec rewind."""
    spec_rewind(
        ctx,
        phase_id,
        checkpoint_commit=checkpoint_commit,
        checkpoint_next_phase=checkpoint_next_phase,
        confirm=confirm,
    )


@app.command("resume", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_resume(
    ctx: typer.Context,
    answer: Optional[str] = typer.Argument(None, metavar="ANSWER", help="Answer for an awaiting-human Phase A decision."),
) -> None:
    """Compatibility alias for spec resume."""
    spec_resume(ctx, answer=answer)


@app.command("run", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_run(
    ctx: typer.Context,
    description: Optional[str] = typer.Argument(None, metavar="DESCRIPTION", help="Spec request or task description."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    reset: bool = typer.Option(False, "--reset", help="Discard blocked state and start fresh."),
    init: bool = typer.Option(False, "--init", help="Create or prepare the targeted source root."),
    message: Optional[str] = typer.Option(None, "--message", help="Additional run message."),
    next_phase: Optional[str] = typer.Option(None, "--next-phase", help="Resume at an explicit workflow phase."),
    target: Optional[list[str]] = typer.Option(None, "--target", help="Implementation source id or path; repeat for multi-repo delivery."),
    ignore_re: bool = typer.Option(False, "--ignore-re", help="Do not attach the latest published RE context."),
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
        perfectionist=False,
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


def _dispatch_review_compatibility(args: list[str]) -> None:
    """Keep the unmatched review alias behind one explicit legacy boundary."""
    from echelon.skill_command_service import dispatch_skill

    dispatch_skill("review", args, project_root=Path.cwd())


@app.command("review", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_review(
    ctx: typer.Context,
    spec_id: Optional[str] = typer.Argument(None, metavar="SPEC_ID", help="Spec id to review."),
    pr_url: Optional[str] = typer.Option(None, "--pr-url", help="Pull request URL to review."),
) -> None:
    """Compatibility alias for the review skill command."""
    args = ([spec_id] if spec_id else [])
    _extend_option(args, "--pr-url", pr_url)
    _dispatch_review_compatibility(args + _ctx_args(ctx))


@app.command("verify-spec", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_verify_spec(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to audit."),
    reconcile: bool = typer.Option(False, "--reconcile", help="Apply deterministic reconciliation fixes."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview reconciliation changes only."),
) -> None:
    """Compatibility alias for spec verify."""
    spec_verify(ctx, spec_id, reconcile=reconcile, dry_run=dry_run)


@app.command("reopen", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_reopen(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to reopen."),
    report: Optional[str] = typer.Argument(None, help="Optional from=<report> fulfillment report selector."),
) -> None:
    """Compatibility alias for spec reopen."""
    spec_reopen(ctx, spec_id, report=report)


@app.command("bugfix", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_bugfix(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to update."),
    description: str = typer.Argument(..., metavar="DESCRIPTION", help="Bug description."),
) -> None:
    """Compatibility alias for spec bugfix."""
    spec_bugfix(ctx, spec_id, description)


@app.command("change", hidden=True, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def root_change(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to update."),
    description: str = typer.Argument(..., metavar="DESCRIPTION", help="Change description."),
) -> None:
    """Compatibility alias for spec change."""
    spec_change(ctx, spec_id, description)


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
    from echelon.workspace_service import (
        bootstrap_workspace_git,
        initialize_workspace,
        wants_unsafe_host_execution_interactively,
    )

    if ctx.args:
        typer.echo(
            f"echelon workspace init: unknown option '{ctx.args[0]}'",
            err=True,
        )
        raise typer.Exit(code=1)
    allow_unsafe = (
        wants_unsafe_host_execution_interactively()
        if allow_unsafe_host_execution is None
        else allow_unsafe_host_execution
    )
    project_root = Path.cwd()
    initialize_workspace(
        project_root,
        allow_unsafe_host_execution=allow_unsafe,
        llm_cli=llm,
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        openai_api_key_file=openai_api_key_file,
        openai_api_key_env=openai_api_key_env,
    )
    bootstrap_workspace_git(project_root)


@workspace_app.command("doctor")
def workspace_doctor() -> None:
    """Validate workspace/source/runtime contract."""
    from echelon.workspace_service import inspect_workspace

    result = inspect_workspace(Path.cwd())
    typer.echo(f"Workspace: {result.workspace_root}")
    typer.echo(f"Buildable: {'yes' if result.buildable else 'no'}")
    if not result.findings:
        typer.echo("Findings: none")
    else:
        typer.echo("Findings:")
        for finding in result.findings:
            path = f" [{finding.path}]" if finding.path else ""
            typer.echo(
                f"  {finding.severity.upper()} {finding.code}{path}: "
                f"{finding.message}"
            )
    if result.has_errors:
        raise typer.Exit(code=1)


@workspace_app.command("migrate-to-prosaic")
def workspace_migrate_to_prosaic() -> None:
    """Deploy and validate the Prosaic runtime without deleting legacy files."""
    from echelon.workspace_service import migrate_to_prosaic

    migrate_to_prosaic(Path.cwd())


@workspace_app.command("migrate", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def workspace_migrate(
    ctx: typer.Context,
    write: bool = typer.Option(False, "--write", help="Write migration changes."),
    commit: bool = typer.Option(False, "--commit", help="Commit migration changes."),
    message: Optional[str] = typer.Option(None, "--message", help="Migration commit message."),
) -> None:
    """Migrate legacy workspace layout."""
    import subprocess

    from echelon.workspace_git_migration import MigrationError
    from echelon.workspace_service import migrate_workspace_layout

    if ctx.args:
        typer.echo(
            f"echelon workspace migrate: unknown option '{ctx.args[0]}'",
            err=True,
        )
        raise typer.Exit(code=1)
    try:
        result = migrate_workspace_layout(
            Path.cwd(),
            write=write,
            commit=commit,
            commit_message=message or "chore: initialize echelon workspace",
        )
    except (MigrationError, subprocess.CalledProcessError) as exc:
        typer.echo(f"migration failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    _render_workspace_migration(result)


@workspace_sources_app.command(
    "sync",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def workspace_sources_sync(
    ctx: typer.Context,
    write: bool = typer.Option(False, "--write", help="Write sources to workspace config."),
) -> None:
    """Sync configured source roots from the canonical sources/ directory."""
    from echelon.workspace_service import sync_workspace_sources

    if ctx.args:
        typer.echo(
            f"echelon workspace sources sync: unknown option '{ctx.args[0]}'",
            err=True,
        )
        raise typer.Exit(code=1)
    result = sync_workspace_sources(Path.cwd(), write=write)

    def label(values: tuple[str, ...]) -> str:
        return ", ".join(values) if values else "none"

    typer.echo(f"Config: {result.config_path}")
    typer.echo(f"Dry run: {'yes' if result.dry_run else 'no'}")
    typer.echo(f"discovered: {label(result.discovered)}")
    typer.echo(f"added: {label(result.added)}")
    typer.echo(f"removed: {label(result.removed)}")
    typer.echo(f"unchanged: {label(result.unchanged)}")
    if result.dry_run:
        typer.echo("Next: echelon workspace sources sync --write")
    else:
        typer.echo(f"updated: {'yes' if result.changed else 'no changes'}")


def _render_workspace_migration(result) -> None:
    plan = result.plan
    typer.echo(f"Workspace: {plan.workspace_root}")
    typer.echo(f"Git-backed: {'yes' if plan.already_git_backed else 'no'}")
    typer.echo("Gitignore entries:")
    for entry in plan.gitignore_entries:
        typer.echo(f"  {entry}")
    typer.echo("Stage paths:")
    for path in plan.stage_paths:
        typer.echo(f"  {path}")
    if plan.canonical_config_needed:
        typer.echo(
            f"Canonical config: copy {plan.legacy_config} -> {plan.canonical_config}"
        )
    if not result.write_requested:
        typer.echo("Dry-run only. Re-run with --write to apply.")
    elif not any(
        (
            result.git_initialized,
            result.canonical_config_copied,
            result.source_roots_scaffolded,
            result.gitignore_updated,
            result.untracked_runtime_paths,
            result.staged_paths,
            result.committed,
        )
    ):
        typer.echo("No changes needed.")
    else:
        typer.echo("Applied:")
        typer.echo(f"  git_initialized: {result.git_initialized}")
        typer.echo(f"  canonical_config_copied: {result.canonical_config_copied}")
        typer.echo(f"  source_roots_scaffolded: {result.source_roots_scaffolded}")
        typer.echo(f"  gitignore_updated: {result.gitignore_updated}")
        typer.echo(
            "  untracked_runtime_paths: "
            f"{', '.join(result.untracked_runtime_paths) or '(none)'}"
        )
        typer.echo(f"  staged_paths: {', '.join(result.staged_paths) or '(none)'}")
        typer.echo(f"  committed: {result.committed}")
        if not result.committed:
            typer.echo("Next: echelon workspace migrate --commit")


@phase_app.command("list")
def phase_list() -> None:
    """List workflow phases available for manual replay."""
    from echelon.phase_service import list_phases
    from echelon.ui import banner

    phases = list_phases(Path.cwd())
    banner(
        "PHASES",
        [
            (phase.phase_id, f"{phase.label}  [{phase.phase_type}]")
            for phase in phases
        ],
        subtitle="Workflow phases available for manual replay",
    )


@phase_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def phase_run(
    ctx: typer.Context,
    phase_id: str = typer.Argument(..., metavar="PHASE_ID", help="Workflow phase id to replay."),
    spec: Optional[str] = typer.Option(None, "--spec", help="Spec id to use as phase context."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    message: Optional[str] = typer.Option(None, "--message", help="Additional phase replay context."),
) -> None:
    """Run one explicit phase through COMMANDER contracts."""
    from echelon.phase_service import run_phase

    if ctx.args:
        typer.echo(f"✗ Unknown phase run argument: {ctx.args[0]}", err=True)
        typer.echo(
            "  Usage: echelon phase run <phase-id> [--spec <id>] "
            "[--mode semi|banzai|guided] [--message <text>]",
            err=True,
        )
        raise typer.Exit(code=1)
    run_phase(
        Path.cwd(),
        phase_id,
        spec_id=spec,
        mode=mode,
        message=message,
    )


@benchmark_app.command("list")
def benchmark_list() -> None:
    """List experimental benchmark fixtures and variants."""
    from echelon.benchmark import list_fixtures, list_variants
    from echelon.ui import banner

    fixtures = list_fixtures()
    variants = list_variants()
    banner(
        "BENCHMARKS",
        [("Fixtures", "benchmark prompts"), ("Variants", "pass with --variant <id>")],
        subtitle="Experimental artifact-quality benchmark fixtures and variants",
    )
    typer.echo("Fixtures:")
    for fixture in fixtures:
        typer.echo(f"  {fixture.id:<30} {fixture.name}")
    typer.echo("\nVariants (--variant <id>):")
    for variant in variants:
        typer.echo(f"  {variant.id:<30} {variant.label}")
    typer.echo("\nExample:")
    typer.echo("  echelon benchmark run tiny-notes --variant baseline")
    typer.echo("\nBaseline snapshot:")
    typer.echo("  --baseline-ref is optional; omitted runs commit the current workspace first.")
    typer.echo("\nPrint saved scores:")
    typer.echo("  echelon benchmark show")
    typer.echo("\nFor an existing spec, use: echelon delivery run <spec-id>")


@benchmark_app.command("show", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_show(
    ctx: typer.Context,
    target: Optional[str] = typer.Argument(
        None,
        metavar="TARGET",
        help="latest, a summary path, or a benchmark run directory.",
    ),
) -> None:
    """Print saved benchmark scores."""
    from echelon.benchmark import latest_summary_path, load_saved_scorecard, load_summary
    from echelon.ui import banner

    if ctx.args:
        typer.echo("✗ Usage: echelon benchmark show [latest|<summary-path-or-run-dir>]", err=True)
        raise typer.Exit(code=1)

    project_root = Path.cwd()
    selected = target or "latest"
    latest_path = latest_summary_path(project_root)
    summary_path = latest_path if selected == "latest" else Path(selected)
    if summary_path is None:
        typer.echo("✗ No benchmark summaries found under runs/benchmarks/.", err=True)
        raise typer.Exit(code=1)
    summary = (
        load_saved_scorecard(project_root)
        if selected == "latest"
        else load_summary(summary_path)
    )
    if not summary:
        typer.echo(f"✗ Could not read benchmark summary: {summary_path}", err=True)
        raise typer.Exit(code=1)

    banner(
        "BENCHMARK SUMMARY",
        [("summary", str(summary_path)), ("best_variant", str(summary.get("best_variant")))],
        subtitle="Saved benchmark scores",
    )
    typer.echo(
        "| Variant | Render | Status | Spec | Delivery | Gaps | Verify Failures | "
        "Blocks | Retries | Dispatches | Context Bytes | Context Tokens | "
        "Context Reduction | Seconds |"
    )
    typer.echo("|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    records = summary.get("variants")
    if isinstance(records, dict):
        for variant_id, record in records.items():
            if not isinstance(record, dict):
                continue
            typer.echo(
                f"| {variant_id} | {record.get('context_render') or '-'} | "
                f"{record.get('status', '')} | {record.get('spec_id') or '-'} | "
                f"{record.get('delivery_run_id') or '-'} | {record.get('fulfillment_gaps', 0)} | "
                f"{record.get('verification_failures', 0)} | {record.get('blocked_states', 0)} | "
                f"{record.get('retries', 0)} | {record.get('build_dispatches', 0)} | "
                f"{record.get('context_prompt_bytes', 0)} | "
                f"{record.get('context_prompt_tokens_estimate', 0)} | "
                f"{record.get('context_reduction_pct', 0)} | "
                f"{float(record.get('elapsed_seconds') or 0.0):.1f} |"
            )


@benchmark_app.command("run", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark_run(
    ctx: typer.Context,
    fixture_id: str = typer.Argument(..., metavar="FIXTURE_ID", help="Benchmark fixture id."),
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
    from echelon.benchmark import (
        CONTEXT_RENDER_MODES,
        baseline_snapshot_commands,
        format_variant_execution_commands,
        list_fixtures,
        list_variants,
        plan_variant_commands,
        run_benchmark_variant,
    )
    from echelon.ui import banner

    if ctx.args:
        typer.echo(f"✗ Unknown benchmark argument: {ctx.args[0]}", err=True)
        raise typer.Exit(code=1)
    if context_render not in CONTEXT_RENDER_MODES:
        typer.echo(f"✗ Unknown context render mode: {context_render}", err=True)
        raise typer.Exit(code=1)

    variant_id = variant or "baseline"
    fixture_ids = {fixture.id for fixture in list_fixtures()}
    variant_ids = {item.id for item in list_variants()}
    try:
        plan = plan_variant_commands(fixture_id, variant_id, artifact_only=artifact_only)
    except ValueError as exc:
        if variant_id in fixture_ids and variant_id not in variant_ids:
            typer.echo(
                f"✗ {variant_id} is a fixture id, not a variant id.\n"
                "  Use --variant baseline, constitution, constitution-tasks, "
                "or constitution-tasks-adrs.",
                err=True,
            )
        elif variant_id.startswith("variant:"):
            typer.echo(
                f"✗ Use --variant {variant_id.removeprefix('variant:')}, "
                f"not --variant {variant_id}.",
                err=True,
            )
        else:
            typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if dry_run:
        baseline_marker = baseline_ref or "BENCHMARK_BASELINE_SNAPSHOT"
        render_modes = (
            ("legacy", "bounded") if context_render == "both" else (context_render,)
        )
        commands = (() if baseline_ref else baseline_snapshot_commands()) + tuple(
            formatted_command
            for render_mode in render_modes
            for formatted_command in format_variant_execution_commands(
                plan,
                baseline_marker,
                context_render=render_mode,
            )
        )
        banner(
            "BENCHMARK DRY RUN",
            [
                ("fixture", plan.fixture_id),
                ("variant", plan.variant_id),
                ("context_render", context_render),
                ("mode", "artifact-only" if artifact_only else "full"),
            ],
            subtitle="Commands that would run",
        )
        for command in commands:
            typer.echo(command if isinstance(command, str) else " ".join(command))
        return

    output_dir = run_benchmark_variant(
        Path.cwd(),
        fixture_id,
        variant_id,
        baseline_ref=baseline_ref,
        artifact_only=artifact_only,
        context_render=context_render,
    )
    banner(
        "BENCHMARK COMPLETE",
        [
            ("fixture", fixture_id),
            ("variant", variant_id),
            ("context_render", context_render),
            ("mode", "artifact-only" if artifact_only else "full"),
            ("output", str(output_dir)),
        ],
    )


@stack_app.command("list", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_list(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Print stack definitions as JSON."),
) -> None:
    """List available Echelon stacks."""
    from echelon.stack_service import load_stack_catalog, stack_definition_to_dict

    if ctx.args:
        typer.echo(f"echelon stack list: unknown argument '{ctx.args[0]}'", err=True)
        raise typer.Exit(code=1)
    definitions = load_stack_catalog(Path.cwd())
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "stacks": [
                        stack_definition_to_dict(definitions[stack_id])
                        for stack_id in sorted(definitions)
                    ]
                },
                indent=2,
            )
        )
        return

    typer.echo("Available Echelon stacks:")
    for stack_id in sorted(definitions):
        stack = definitions[stack_id]
        archetypes = ", ".join(stack.applies_to_archetypes)
        typer.echo(f"- {stack.id} ({stack.kind}; {archetypes}) {stack.name}")


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
    from harness.stacks import detection_report_to_yaml, render_detection_markdown
    from harness.stacks.errors import StackError
    from echelon.stack_service import detect_stack_candidates

    if ctx.args:
        typer.echo(f"echelon stack detect: unknown argument '{ctx.args[0]}'", err=True)
        raise typer.Exit(code=1)

    selected_format = "json" if json_output else (output_format or "text")
    if selected_format not in {"text", "yaml", "json"}:
        typer.echo("echelon stack detect: --format must be text or yaml", err=True)
        raise typer.Exit(code=1)

    project_root = Path.cwd()

    def resolve_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else project_root / path

    try:
        outcome = detect_stack_candidates(
            project_root,
            target=resolve_path(target) if target else project_root,
            artifact_roots=[resolve_path(value) for value in artifacts or []],
            write_report=write,
        )
    except (StackError, FileNotFoundError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if selected_format == "json":
        typer.echo(json.dumps(outcome.report.to_dict(), indent=2))
    elif selected_format == "yaml":
        typer.echo(detection_report_to_yaml(outcome.report).rstrip())
    else:
        typer.echo(render_detection_markdown(outcome.report).rstrip())
        if outcome.written is not None:
            try:
                yaml_path = outcome.written.yaml_path.resolve().relative_to(
                    project_root.resolve()
                )
                markdown_path = outcome.written.markdown_path.resolve().relative_to(
                    project_root.resolve()
                )
            except ValueError:
                yaml_path = outcome.written.yaml_path
                markdown_path = outcome.written.markdown_path
            typer.echo()
            typer.echo(f"Wrote detection report: {yaml_path}")
            typer.echo(f"Wrote detection summary: {markdown_path}")


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
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Target directory for target-aware verification preflight.",
    ),
    probe_tools: bool = typer.Option(False, "--probe-tools", help="Probe selected stack tools."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    """Check selected stack commands, registries, and tool probes."""
    import os

    from harness.stacks import (
        preflight_to_dict,
        render_preflight_markdown,
        resolved_to_dict,
    )
    from harness.stacks.errors import StackError
    from echelon.stack_service import preflight_stacks

    if ctx.args:
        typer.echo(
            f"echelon stack preflight: unknown argument '{ctx.args[0]}'",
            err=True,
        )
        raise typer.Exit(code=1)

    project_root = Path.cwd()

    def resolve_path(value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        return path if path.is_absolute() else project_root / path

    try:
        outcome = preflight_stacks(
            project_root,
            selected=stack or [],
            target_archetypes=target_archetype or [],
            from_detection=resolve_path(from_detect),
            target_root=resolve_path(target),
            probe_tools=probe_tools,
            environment=os.environ,
        )
    except StackError as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if outcome.message is not None:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "status": "pass",
                        "message": outcome.message,
                        "selected": [],
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(outcome.message)
        return

    assert outcome.resolved is not None
    assert outcome.result is not None
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "resolved": resolved_to_dict(outcome.resolved),
                    "preflight": preflight_to_dict(outcome.result),
                },
                indent=2,
            )
        )
    else:
        typer.echo("Resolved Echelon stacks:")
        for stack_id in outcome.resolved.resolved_ids:
            typer.echo(f"- {stack_id}")
        typer.echo()
        typer.echo(render_preflight_markdown(outcome.result).rstrip())

    if outcome.result.has_errors:
        raise typer.Exit(code=1)


@stack_app.command("provision", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def stack_provision(
    ctx: typer.Context,
    stack: Optional[list[str]] = typer.Option(
        None,
        "--stack",
        help="Stack id to provision; repeat for multiple stacks.",
    ),
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Target directory for verification-only provisioning files.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite existing provisioning files."),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    """Render verification provisioning files without starting Docker."""
    import os

    from harness.stacks import ProvisioningError
    from harness.stacks.errors import StackError
    from echelon.stack_service import provision_stacks

    if ctx.args:
        typer.echo(
            f"echelon stack provision: unknown argument '{ctx.args[0]}'",
            err=True,
        )
        raise typer.Exit(code=1)

    project_root = Path.cwd()
    target_root = Path(target) if target else project_root
    if not target_root.is_absolute():
        target_root = project_root / target_root
    try:
        outcome = provision_stacks(
            project_root,
            selected=stack or [],
            target_root=target_root,
            force=force,
            environment=os.environ,
        )
    except (StackError, ProvisioningError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if outcome.message is not None:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "target": str(outcome.target_root),
                        "generated": [],
                        "message": outcome.message,
                    },
                    indent=2,
                )
            )
        else:
            typer.echo(outcome.message)
        return

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "target": str(outcome.target_root),
                    "generated": [str(path) for path in outcome.generated],
                    "provisioners": [
                        {
                            "id": status.provisioner_id,
                            "stack_id": status.owner_stack_id,
                            "state": status.state,
                            "message": status.message,
                            "path": str(status.path) if status.path is not None else None,
                        }
                        for status in outcome.statuses
                    ],
                },
                indent=2,
            )
        )
        return

    assert outcome.resolved is not None
    if not outcome.resolved.provisioners:
        typer.echo("Selected stacks declare no verification provisioners.")
        return
    if outcome.generated:
        typer.echo("Generated verification provisioning files:")
        for path in outcome.generated:
            typer.echo(f"- {path}")
    else:
        typer.echo("No verification provisioning files were generated.")
    typer.echo("Echelon did not start Docker. Review the files, then run:")
    typer.echo("  docker compose -f docker-compose.echelon-verify.yml up -d")
    typer.echo("  export DATABASE_URL='postgresql://<user>:<password>@<host>/<database>'")
    typer.echo(
        "  docker compose -f docker-compose.echelon-verify.yml exec postgres "
        "pg_isready -U echelon -d echelon_verify"
    )
    typer.echo(
        "  docker compose -f docker-compose.echelon-verify.yml exec postgres "
        "psql -U echelon -d echelon_verify"
    )
    typer.echo("  docker compose -f docker-compose.echelon-verify.yml down -v")


@stack_app.command("enable")
def stack_enable(
    stack_ids: list[str] = typer.Argument(..., help="Stack IDs to add to the project selection."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing config."),
) -> None:
    """Add stacks to the committed project selection."""
    _change_stack_selection("enable", stack_ids, dry_run=dry_run)


@stack_app.command("disable")
def stack_disable(
    stack_ids: list[str] = typer.Argument(..., help="Explicit stack IDs to remove."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing config."),
) -> None:
    """Remove explicitly selected stacks from the committed project config."""
    _change_stack_selection("disable", stack_ids, dry_run=dry_run)


@stack_app.command("select")
def stack_select(
    stack_ids: Optional[list[str]] = typer.Argument(
        None,
        help="Complete explicit selection; omit all IDs to clear it.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing config."),
) -> None:
    """Replace the committed project stack selection."""
    _change_stack_selection("select", stack_ids or [], dry_run=dry_run)


@stack_app.command("selected")
def stack_selected(
    json_output: bool = typer.Option(False, "--json", help="Print selection as JSON."),
) -> None:
    """Show explicit, effective, and implied project stack selection."""
    from harness.stacks.errors import StackError
    from echelon.stack_selection import StackSelectionError
    from echelon.stack_service import read_selected_stacks

    try:
        selection = read_selected_stacks(Path.cwd())
    except (StackError, StackSelectionError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(json.dumps(selection.__dict__, indent=2))
        return
    typer.echo(f"Explicit stacks: {', '.join(selection.explicit) or 'none'}")
    typer.echo(f"Effective stacks: {', '.join(selection.effective) or 'none'}")
    typer.echo(f"Resolved stacks: {', '.join(selection.resolved) or 'none'}")
    if selection.local_override:
        typer.echo("Warning: .echelon/local.yml overrides stacks.selected.")


def _change_stack_selection(
    operation: str,
    stack_ids: list[str],
    *,
    dry_run: bool,
) -> None:
    import yaml

    from harness.stacks.errors import StackError
    from echelon.stack_selection import StackSelectionError
    from echelon.stack_service import change_selected_stacks

    try:
        selection = change_selected_stacks(
            Path.cwd(),
            stack_ids,
            operation=operation,
            dry_run=dry_run,
        )
    except (StackError, StackSelectionError) as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc

    prefix = "Dry run: " if dry_run else ""
    label = {"enable": "Enabled", "disable": "Disabled", "select": "Selected"}[
        operation
    ]
    values = ", ".join(
        stack_ids if operation == "disable" else selection.explicit
    ) or "none"
    typer.echo(f"{prefix}{label} stacks: {values}")
    if dry_run:
        typer.echo(
            yaml.safe_dump(
                {"stacks": {"selected": selection.explicit}},
                sort_keys=False,
            ).rstrip()
        )
    if selection.local_override:
        typer.echo("Warning: .echelon/local.yml overrides stacks.selected.")


@spec_app.command(
    "run",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_run(
    ctx: typer.Context,
    description: Optional[str] = typer.Argument(None, metavar="DESCRIPTION", help="Spec request or task description."),
    mode: Optional[str] = typer.Option(None, "--mode", help="Autonomy mode: semi, banzai, or guided."),
    reset: bool = typer.Option(False, "--reset", help="Discard blocked state and start fresh."),
    perfectionist: bool = typer.Option(
        False,
        "--perfectionist",
        help="Request systematic exhaustive Cartographer authoring.",
    ),
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
    from echelon.spec_service import SpecRunRequest, run_spec

    run_spec(Path.cwd(), SpecRunRequest(
        description=description,
        extra_args=tuple(ctx.args),
        mode=mode,
        reset=reset,
        perfectionist=perfectionist,
        init=init,
        message=message,
        next_phase=next_phase,
        targets=tuple(target or ()),
        input_values=tuple(input_values or ()),
        ignore_re=ignore_re,
        stash=stash,
        discard=discard,
        confirm=confirm,
    ))


@spec_app.command("retarget")
def spec_retarget(
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Active unimplemented spec id."),
    target: list[str] = typer.Option(
        ...,
        "--target",
        help="Complete replacement implementation target set; repeat as needed.",
    ),
    confirm: int = typer.Option(
        0,
        "--confirm",
        count=True,
        help="Create the checkpoint and rebuild Phase A.",
    ),
) -> None:
    """Destructively replace the active spec's complete target set."""
    from echelon.spec_service import SpecRetargetRequest, retarget_spec

    retarget_spec(Path.cwd(), SpecRetargetRequest(
        spec_id=spec_id,
        targets=tuple(target),
        confirm_count=confirm,
    ))


@spec_app.command("status")
def spec_status() -> None:
    """Show current spec run state and next action."""
    from echelon.spec_service import show_status

    show_status(Path.cwd())


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
    from echelon.spec_service import continue_spec

    continue_spec(Path.cwd(), mode=mode, extra_args=tuple(ctx.args))


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
    from echelon.spec_service import resume_spec

    resume_spec(Path.cwd(), answer=answer, extra_args=tuple(ctx.args))


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
    from echelon.spec_service import add_input

    add_input(Path.cwd(), input_values=tuple(input_values or ()))


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
    from echelon.spec_service import resolve_issue

    resolve_issue(
        Path.cwd(),
        issue_id=issue_id,
        decision=decision,
        extra_args=tuple(ctx.args),
    )


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
    checkpoint_next_phase: Optional[str] = typer.Option(
        None,
        "--next-phase",
        help="Exact next phase recorded by the selected checkpoint row.",
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Apply the rewind instead of previewing."),
) -> None:
    """Rewind the active squad run to a safe checkpoint."""
    from echelon.spec_service import SpecRewindRequest, rewind_spec

    rewind_spec(Path.cwd(), SpecRewindRequest(
        phase_id=phase_id,
        extra_args=tuple(ctx.args),
        checkpoint_commit=checkpoint_commit,
        checkpoint_next_phase=checkpoint_next_phase,
        confirm=confirm,
    ))


@spec_app.command("repair-traceability")
def spec_repair_traceability(
    confirm: bool = typer.Option(False, "--confirm", help="Apply the safe traceability repair."),
) -> None:
    """Repair safely-prunable product-input task mappings and resume finalization."""
    from echelon.spec_service import repair_traceability

    repair_traceability(Path.cwd(), confirm=confirm)


@spec_app.command("switch")
def spec_switch(
    spec_or_run_id: str = typer.Argument(..., metavar="SPEC_OR_RUN_ID", help="Checkpointed spec id or Phase A run id."),
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
    from echelon.spec_service import drop_target

    drop_target(
        Path.cwd(),
        spec_id=spec_id,
        target=target,
        confirm=confirm,
    )


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
            commit = _graph_output_commit(spec_dir, audit=False)
            write_spec_graph(graph, spec_dir)
            commit.commit()
    except (SpecGraphError, SpecMemoryError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _echo_spec_graph_summary(graph, action="built")


@graph_app.command("query")
def graph_query(
    question: str,
    spec: Optional[str] = typer.Option(None, "--spec", help="Read one persisted spec graph."),
    node_type: Optional[str] = typer.Option(None, "--type", help="Restrict results to one node type."),
    depth: int = typer.Option(2, "--depth", help="Maximum evidence-path depth."),
    limit: int = typer.Option(20, "--limit", "-n", help="Maximum result nodes."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Query persisted graph nodes with deterministic lexical matching."""
    from echelon.graph_traversal import query_graph

    _run_graph_consumption(
        "query",
        spec,
        as_json,
        {"question": question, "type": node_type, "depth": depth, "limit": limit},
        lambda model: query_graph(model, question, node_type, depth, limit),  # type: ignore[arg-type]
    )


@graph_app.command("explain")
def graph_explain(
    node: str,
    spec: Optional[str] = typer.Option(None, "--spec", help="Read one persisted spec graph."),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum relationships."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Explain one graph node and its persisted relationships."""
    from echelon.graph_read import resolve_node_id
    from echelon.graph_traversal import explain_node

    _run_graph_consumption(
        "explain",
        spec,
        as_json,
        {"node": node, "limit": limit},
        lambda model: explain_node(model, resolve_node_id(model, node), limit),  # type: ignore[arg-type]
    )


@graph_app.command("path")
def graph_path(
    source: str,
    target: str,
    spec: Optional[str] = typer.Option(None, "--spec", help="Read one persisted spec graph."),
    max_hops: int = typer.Option(8, "--max-hops", help="Maximum path hops."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Find one deterministic shortest path over persisted relationships."""
    from echelon.graph_read import resolve_node_id
    from echelon.graph_traversal import shortest_path

    _run_graph_consumption(
        "path",
        spec,
        as_json,
        {"source": source, "target": target, "max_hops": max_hops},
        lambda model: shortest_path(
            model,
            resolve_node_id(model, source),
            resolve_node_id(model, target),
            _positive_graph_bound(max_hops, "--max-hops"),
        ),  # type: ignore[arg-type]
    )


@graph_app.command("neighbors")
def graph_neighbors(
    node: str,
    spec: Optional[str] = typer.Option(None, "--spec", help="Read one persisted spec graph."),
    direction: str = typer.Option("both", "--direction", help="Stored edge direction: both, in, or out."),
    relation: Optional[str] = typer.Option(None, "--relation", help="Stored relationship type."),
    limit: int = typer.Option(50, "--limit", "-n", help="Maximum relationships."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """List deterministic one-hop persisted graph relationships."""
    from echelon.graph_read import resolve_node_id
    from echelon.graph_traversal import neighbors

    _run_graph_consumption(
        "neighbors",
        spec,
        as_json,
        {
            "node": node,
            "direction": direction,
            "relation": relation,
            "limit": limit,
        },
        lambda model: neighbors(
            model,
            resolve_node_id(model, node),
            direction,
            relation,
            limit,
        ),  # type: ignore[arg-type]
    )


@graph_app.command("impact")
def graph_impact(
    node: str,
    spec: Optional[str] = typer.Option(None, "--spec", help="Read one persisted spec graph."),
    max_depth: int = typer.Option(4, "--max-depth", help="Maximum impact depth."),
    all_relations: bool = typer.Option(False, "--all-relations", help="Traverse all stored relationships."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Calculate typed downstream impact from one persisted graph node."""
    from echelon.graph_read import resolve_node_id
    from echelon.graph_traversal import impact

    _run_graph_consumption(
        "impact",
        spec,
        as_json,
        {
            "node": node,
            "max_depth": max_depth,
            "all_relations": all_relations,
        },
        lambda model: impact(
            model,
            resolve_node_id(model, node),
            max_depth,
            all_relations,
        ),  # type: ignore[arg-type]
    )


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
    renderer: str = typer.Option("cytoscape", "--renderer"),
    output: Optional[Path] = typer.Option(None, "--output"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Create and optionally open an offline workspace graph viewer."""
    import webbrowser

    from echelon.graph_visualization import (
        GraphVisualizationError,
        build_graph_view_payload,
        load_cytoscape_source,
        load_graph_document,
        render_graph_html,
    )
    from echelon.graph_vis_network import load_vis_network_source, render_vis_graph_html
    from echelon.workspace_graph import workspace_graph_path, write_workspace_graph_bytes
    from echelon.workspace_graph_audit import (
        audit_workspace_graph,
        persisted_workspace_graph_is_invalid,
    )

    try:
        selected_renderer = _graph_renderer(renderer)
        root = Path.cwd()
        report = audit_workspace_graph(root)
        if persisted_workspace_graph_is_invalid(report):
            raise GraphVisualizationError("workspace graph artifact fails its full contract")
        document = load_graph_document(workspace_graph_path(root))
        initial_lens = lens or ("exceptions" if report.findings else "portfolio")
        if selected_renderer == "cytoscape":
            html = render_graph_html(
                document,
                report,
                cytoscape_source=load_cytoscape_source(),
                initial_lens=initial_lens,
            )
        else:
            payload = build_graph_view_payload(document, report, initial_lens)
            html = render_vis_graph_html(payload, load_vis_network_source())
        output_path = output or workspace_graph_path(root).with_name(
            "workspace-vis.html" if selected_renderer == "vis" else "workspace.html"
        )
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
            commit = _graph_output_commit(spec_dir, graph=False)
            write_spec_graph_audit(report, spec_dir)
            commit.commit()
    except (SpecGraphError, SpecMemoryError, OSError, ValueError, RuntimeError) as exc:
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
        commit = _graph_output_commit(spec_dir) if write else None
        if write:
            write_spec_graph(graph, spec_dir)
        report = audit_spec_graph(Path.cwd(), spec_selector)
        if write:
            write_spec_graph_audit(report, spec_dir)
            commit.commit()
    except (SpecGraphError, SpecMemoryError, OSError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _echo_spec_graph_summary(graph, action="refreshed")
    _echo_spec_graph_audit(report)
    raise typer.Exit(code=_graph_exit_code(report.status))


def _graph_output_commit(spec_dir: Path, *, graph: bool = True, audit: bool = True):
    from echelon.mempalace_requirements import _require_legacy_spec_memory
    from echelon.owned_output_commit import OwnedOutputCommit

    _require_legacy_spec_memory(
        Path.cwd(),
        spec_id=spec_dir.name,
        resolved_spec_id=spec_dir.resolve().name,
    )
    names = (["spec-artifact-graph.json"] if graph else []) + (
        ["spec-artifact-graph-audit.json"] if audit else []
    )
    return OwnedOutputCommit(
        Path.cwd(), [spec_dir / name for name in names],
        f"chore: record graph evidence for {spec_dir.name}",
    )


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
    renderer: str = typer.Option("cytoscape", "--renderer"),
    output: Optional[Path] = typer.Option(None, "--output"),
    open_browser: bool = typer.Option(True, "--open/--no-open"),
) -> None:
    """Create and optionally open an offline persisted-graph viewer."""
    import webbrowser

    from echelon.graph_visualization import (
        GRAPH_LENSES,
        GraphVisualizationError,
        build_graph_view_payload,
        load_cytoscape_source,
        load_graph_document,
        render_graph_html,
    )
    from echelon.graph_vis_network import load_vis_network_source, render_vis_graph_html
    from echelon.mempalace_requirements import (
        SpecMemoryError,
        resolve_spec_dir,
    )
    from echelon.spec_graph import GRAPH_FILENAME, SpecGraphError
    from echelon.spec_graph_audit import audit_spec_graph

    try:
        selected_renderer = _graph_renderer(renderer)
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
        if selected_renderer == "cytoscape":
            html = render_graph_html(
                document,
                report,
                cytoscape_source=load_cytoscape_source(),
                initial_lens=initial_lens,
            )
        else:
            payload = build_graph_view_payload(document, report, initial_lens)
            html = render_vis_graph_html(payload, load_vis_network_source())
        output_path = output or (
            Path.cwd()
            / ".echelon"
            / "graph"
            / (
                f"{spec_dir.name}-vis.html"
                if selected_renderer == "vis"
                else f"{spec_dir.name}.html"
            )
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
            try:
                opened = webbrowser.open(output_path.resolve().as_uri())
            except webbrowser.Error:
                typer.echo("warning: graph viewer was not opened", err=True)
            else:
                if not opened:
                    typer.echo("warning: graph viewer was not opened", err=True)
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
    from echelon.mempalace_requirements import (
        SpecMemoryError,
        _require_legacy_spec_memory,
        resolve_spec_dir,
    )

    try:
        report = audit_spec_memory(Path.cwd(), spec_selector, probe_retrieval=probe_retrieval)
        if write and report.status != "unavailable":
            spec_dir = resolve_spec_dir(Path.cwd(), spec_selector)
            _require_legacy_spec_memory(
                Path.cwd(),
                spec_id=spec_dir.name,
                resolved_spec_id=Path(report.spec_dir).resolve().name,
            )
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
    del ctx, spec_id, repo, init
    from echelon.spec_service import reject_target_mutation

    reject_target_mutation()


@spec_app.command("targets")
def spec_targets(
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to inspect."),
) -> None:
    """Display every task grouped by delivery target."""
    from echelon.spec_service import show_targets

    show_targets(Path.cwd(), spec_id=spec_id)


@spec_app.command(
    "artifacts",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_artifacts(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., help="Spec id to index."),
) -> None:
    """Generate specs/<id>/ARTIFACTS.md."""
    from echelon.spec_service import write_artifacts

    write_artifacts(Path.cwd(), spec_id=spec_id, extra_args=tuple(ctx.args))


@spec_app.command(
    "verify",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_verify(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to audit."),
    reconcile: bool = typer.Option(
        False,
        "--reconcile",
        help="Apply deterministic task-progress reconciliation fixes.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview reconciliation changes only."),
) -> None:
    """Audit implementation against spec."""
    _reject_spec_verify_extra_args(ctx)
    _run_spec_verify(
        Path.cwd(),
        spec_id,
        reconcile=reconcile,
        dry_run=dry_run,
    )


@spec_app.command("reconcile-fulfillment")
def spec_reconcile_fulfillment(
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec whose historical delivery receipts to inspect."),
    write: bool = typer.Option(False, "--write", help="Apply only a receipt-compatible reconciliation."),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable preview output."),
) -> None:
    """Preview or apply receipt-backed fulfillment reconciliation."""
    from harness.fulfillment_reconciliation_discovery import reconcile_from_delivery_state
    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.verified_fulfillment_ledger import (
        read_verified_ledger,
        verified_fulfillment_ledger_path,
        write_verified_ledger,
    )

    root = Path.cwd().resolve()
    spec_dir = find_spec_dir(spec_id, root)
    if spec_dir is None:
        raise typer.BadParameter(f"spec not found: {spec_id}")
    ledger_path = verified_fulfillment_ledger_path(spec_dir)
    if not ledger_path.is_file():
        typer.echo("status: reverify_required\nreason: no canonical verified-fulfillment ledger")
        raise typer.Exit(1)
    targets = read_targets(spec_dir)
    if len(targets) != 1 or not (target := (root / targets[0]).resolve()).is_dir():
        typer.echo("status: reverify_required\nreason: exactly one existing delivery target is required")
        raise typer.Exit(1)
    result = reconcile_from_delivery_state(
        root=root, spec_dir=spec_dir, target=target, ledger=read_verified_ledger(ledger_path)
    )
    payload = {
        "spec_id": spec_dir.name, "status": result.status, "write": write,
        "rejected_reasons": list(result.rejected_reasons),
        "rows": [{"requirement_id": row.requirement_id, "status": row.status,
                  "receipt_refs": [dict(item) for item in row.receipt_refs]}
                 for row in result.ledger.rows],
    }
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"status: {result.status}")
        typer.echo("mode: write" if write else "mode: preview (pass --write to apply)")
        for reason in result.rejected_reasons:
            typer.echo(f"rejected: {reason}")
    if write and result.status == "reconciled":
        write_verified_ledger(ledger_path, result.ledger)
        typer.echo(f"ledger: updated {ledger_path}")
        return
    if result.status != "reconciled":
        if result.status == "no_candidates":
            typer.echo(f"next: echelon spec verify {spec_dir.name}")
        raise typer.Exit(1)


def _reject_spec_verify_extra_args(ctx: typer.Context) -> None:
    if not ctx.args:
        return
    typer.echo(
        "spec verify: unsupported arguments: " + " ".join(ctx.args),
        err=True,
    )
    raise typer.Exit(code=2)


def _run_spec_verify(
    project_root: Path,
    selector: str,
    *,
    reconcile: bool,
    dry_run: bool,
) -> None:
    from echelon.prosaic_packages import install_prosaic_bundle
    from harness.authoritative_spec_verifier import AuthoritativeSpecVerifier
    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.fulfillment_runner import FulfillmentRunner
    from harness.llm_provider import AICodingCliProvider
    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.verification_stack_runtime import resolve_verification_stacks

    if dry_run and not reconcile:
        typer.echo("spec verify: --dry-run requires --reconcile", err=True)
        raise typer.Exit(code=2)

    workspace = project_root.resolve()
    spec_dir = find_spec_dir(selector, workspace)
    if spec_dir is None:
        typer.echo(f"spec verify: spec not found: {selector}", err=True)
        raise typer.Exit(code=2)
    spec_dir = spec_dir.resolve()

    targets = read_targets(spec_dir)
    if len(targets) > 1:
        typer.echo("spec verify requires exactly one target repo", err=True)
        raise typer.Exit(code=2)
    target = workspace if not targets else (workspace / targets[0]).resolve()
    if not target.is_dir():
        typer.echo(f"spec verify: target repo not found: {targets[0]}", err=True)
        raise typer.Exit(code=2)

    install_prosaic_bundle(workspace)
    config = load_config(workspace, squad_only=True)
    config.target_repo = str(target)
    resolved = resolve_verification_stacks(workspace, target)
    config.verification_services = list(resolved.services)
    config.resolved_stacks = resolved
    config.resolved_runnability = resolved.runnability
    prompt_executor = AICodingCliProvider(config)
    container_cli = getattr(config, "container_cli", "docker")
    if container_cli not in {"docker", "podman"}:
        container_cli = "docker"
    sandbox_provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=container_cli,
    )
    from echelon.owned_output_commit import OwnedOutputCommit

    output_commit = OwnedOutputCommit(
        workspace,
        [spec_dir / name for name in (
            "fulfillment-report.md", "fulfillment-gaps.md",
            "verified-fulfillment-ledger.json",
        )] + ([spec_dir / "tasks.md"] if reconcile and not dry_run else []),
        f"chore: record verification evidence for {spec_dir.name}",
    )
    result = AuthoritativeSpecVerifier(
        target=target,
        spec_dir=spec_dir,
        config=config,
        fulfillment_runner=FulfillmentRunner(prompt_executor),
        provider=sandbox_provider,
        diagnostic_executor=prompt_executor,
    ).run(
        reconcile=reconcile,
        dry_run=dry_run,
    )
    output_commit.commit()
    typer.echo("evidence: authoritative sandbox")
    typer.echo(f"status: {result.status}")
    typer.echo(f"verify run: {result.verify_run_dir}")
    if result.failure_class:
        typer.echo(f"failure class: {result.failure_class}")
    if result.reason:
        typer.echo(f"reason: {result.reason}")
    if result.report_path:
        typer.echo(f"report: {result.report_path}")
    if getattr(result, "diagnostic_path", None):
        typer.echo(f"coverage diagnosis (advisory only): {result.diagnostic_path}")
    if result.verified_ledger is not None:
        ledger = " ".join(
            f"{key}={value}" for key, value in result.verified_ledger.items()
        )
        typer.echo(f"ledger: {ledger}")
    if not result.ok or result.status not in {"cached", "refreshed"}:
        raise typer.Exit(code=result.exit_code or 1)


@spec_app.command(
    "reopen",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_reopen(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to reopen."),
    report: Optional[str] = typer.Argument(
        None,
        help="Optional from=<report> fulfillment report selector.",
    ),
) -> None:
    """Reopen spec from fulfillment gaps."""
    from echelon.skill_command_service import dispatch_skill

    args = [spec_id]
    if report is not None:
        args.append(report)
    args.extend(list(ctx.args))
    dispatch_skill("reopen", args, project_root=Path.cwd())


@spec_app.command("defer")
def spec_defer(
    spec_id: str = typer.Argument(..., help="Spec id whose scope is being deferred."),
    ids: list[str] = typer.Argument(..., help="Canonical task or requirement IDs to defer."),
    reason: str = typer.Option(..., "--reason", help="Owner reason for removing the scope."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview the defer without writing files."),
) -> None:
    """Defer explicit spec scope without invoking an LLM."""
    _run_scope_change(spec_id, ids, action="defer", reason=reason, dry_run=dry_run)


@spec_app.command("defer-runnability")
def spec_defer_runnability(
    spec_id: str = typer.Argument(..., help="Spec id whose runnability gate is being deferred."),
    reason: str = typer.Option(..., "--reason", help="Owner-approved reason for the deferral."),
) -> None:
    """Defer a failed runnability gate to an advisory follow-up proposal."""
    from harness.runnability_disposition import (
        RunnabilityDispositionError,
        defer_runnability,
        find_latest_runnability_report,
        follow_up_path,
    )
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is None:
        raise typer.BadParameter(f"spec not found: {spec_id}")
    workspace_root = spec_dir.parent.parent
    evidence_report = find_latest_runnability_report(workspace_root, spec_dir.name)
    if evidence_report is None:
        raise typer.BadParameter(
            f"no user-runnability report found for {spec_dir.name}; run delivery first"
        )
    try:
        report = _read_runnability_report_summary(evidence_report)
        disposition = defer_runnability(
            spec_dir=spec_dir,
            target=str(report.get("target_id") or ""),
            reason=reason,
            evidence_report=evidence_report,
        )
    except RunnabilityDispositionError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("RUNNABILITY DEFERRED")
    typer.echo(f"spec: {spec_dir.name}")
    typer.echo(f"target: {disposition.target}")
    typer.echo(f"reason: {disposition.reason}")
    typer.echo(f"evidence: {disposition.evidence_report}")
    typer.echo(f"proposal: {follow_up_path(spec_dir)}")
    typer.echo("status: applied")
    typer.echo("next: review the advisory proposal before creating its follow-up spec")


@spec_app.command("plan-runnability")
def spec_plan_runnability(
    spec_id: str = typer.Argument(..., help="Spec id whose runnability gate is returning to current work."),
) -> None:
    """Restore a deferred required runnability gate to current-spec work."""
    from harness.runnability_disposition import (
        RunnabilityDispositionError,
        disposition_path,
        plan_runnability,
    )
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, Path.cwd())
    if spec_dir is None:
        raise typer.BadParameter(f"spec not found: {spec_id}")
    try:
        disposition = plan_runnability(spec_dir)
    except RunnabilityDispositionError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo("RUNNABILITY PLANNED")
    typer.echo(f"spec: {spec_dir.name}")
    typer.echo(f"target: {disposition.target}")
    typer.echo(f"ledger: {disposition_path(spec_dir)}")
    typer.echo("gate: current-spec blocking restored")
    typer.echo("status: applied")


def _read_runnability_report_summary(path: Path) -> dict[str, object]:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        from harness.runnability_disposition import RunnabilityDispositionError

        raise RunnabilityDispositionError(f"invalid runnability report: {exc}") from exc
    if not isinstance(payload, dict):
        from harness.runnability_disposition import RunnabilityDispositionError

        raise RunnabilityDispositionError("invalid runnability report: expected an object")
    return payload


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
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to update."),
    description: str = typer.Argument(..., metavar="DESCRIPTION", help="Bug description."),
) -> None:
    """Diagnose and plan a bugfix."""
    from echelon.skill_command_service import dispatch_skill

    dispatch_skill(
        "bugfix",
        [spec_id, description, *list(ctx.args)],
        project_root=Path.cwd(),
    )


@spec_app.command(
    "change",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_change(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Spec id to update."),
    description: str = typer.Argument(..., metavar="DESCRIPTION", help="Change description."),
) -> None:
    """Plan a scope change."""
    from echelon.skill_command_service import dispatch_skill

    dispatch_skill(
        "change",
        [spec_id, description, *list(ctx.args)],
        project_root=Path.cwd(),
    )


@spec_app.command(
    "amend",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def spec_amend(
    ctx: typer.Context,
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Planned spec id to amend."),
    description: str = typer.Argument(..., metavar="DESCRIPTION", help="Product change summary."),
    input_values: Optional[list[str]] = typer.Option(
        None,
        "--input",
        help="Product input as requirement:<path> or reference:<path>; repeat as needed.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview baseline and inputs without mutation."),
) -> None:
    """Prepare an isolated amendment for an unbuilt spec."""
    from echelon.spec_service import prepare_amendment

    prepare_amendment(
        Path.cwd(),
        spec_id=spec_id,
        description=description,
        input_values=tuple(input_values or ()),
        dry_run=dry_run,
        extra_args=tuple(ctx.args),
    )


@delivery_app.command(
    "init",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def delivery_init(ctx: typer.Context) -> None:
    """Initialize delivery environment: sandbox, mirror, verify."""
    from echelon.delivery_service import initialize_delivery

    initialize_delivery(
        Path.cwd(),
        extra_args=tuple(ctx.args),
    )


@delivery_app.command("target")
def delivery_target(spec_id: str) -> None:
    """Prepare delivery metadata for a spec's declared target repo."""
    from echelon.delivery_service import prepare_target

    prepare_target(Path.cwd(), spec_id=spec_id)


@delivery_app.command("status")
def delivery_status(
    spec_id: Optional[str] = typer.Argument(None, metavar="SPEC_ID", help="Spec id to inspect."),
    strategy: Optional[str] = typer.Option(None, "--strategy", help="Delivery strategy id."),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
) -> None:
    """Show current Phase B delivery/Ralph state."""
    from echelon.delivery_status import command

    command(
        spec_id=spec_id or "",
        strategy=strategy or "",
        json_output=json_output,
    )


@delivery_app.command("verify-local")
def delivery_verify_local(
    spec_id: str = typer.Argument(..., metavar="SPEC_ID", help="Converged spec to verify locally."),
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Declared target id when the spec has multiple targets.",
    ),
    engine: str = typer.Option(
        "auto",
        "--engine",
        help="Local macOS engine: auto, docker, or podman.",
    ),
    assume_yes: bool = typer.Option(
        False,
        "--yes",
        help="Confirm the displayed host-local action plan.",
    ),
    keep_on_failure: bool = typer.Option(
        False,
        "--keep-on-failure",
        help="Leave only journalled resources for explicit cleanup after a failure.",
    ),
) -> None:
    """Explicit macOS verification; it never changes delivery landing authority."""
    from echelon.delivery_service import LocalVerificationRequest, verify_local

    try:
        verify_local(
            Path.cwd(),
            LocalVerificationRequest(
                spec_id=spec_id,
                target_id=target,
                engine=engine,
                assume_yes=assume_yes,
                keep_on_failure=keep_on_failure,
            ),
        )
    except ValueError as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc


@delivery_app.command("cleanup-local")
def delivery_cleanup_local(
    local_run_id: str = typer.Argument(..., metavar="LOCAL_RUN_ID", help="Journal-bound run id to recover."),
) -> None:
    """Clean one interrupted local verification using its ownership journal."""
    from echelon.delivery_service import cleanup_local

    try:
        cleanup_local(Path.cwd(), local_run_id=local_run_id)
    except ValueError as exc:
        typer.echo(f"✗ {exc}", err=True)
        raise typer.Exit(code=1) from exc


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
        help="Build strategy name (default recommended).",
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
    from echelon.delivery_service import DeliveryRunRequest, run_delivery

    run_delivery(
        Path.cwd(),
        DeliveryRunRequest(
            spec_id,
            extra_args=tuple(ctx.args),
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
    spec_id: str = typer.Argument(..., metavar="SPEC_ID"),
    answer: Optional[str] = typer.Argument(None, metavar="ANSWER", help="Answer for blocker escalation."),
    mode: Optional[str] = typer.Option(None, "--mode"),
    strategy: Optional[str] = typer.Option(None, "--strategy"),
) -> None:
    """Resume a blocked delivery run with a human answer."""
    from echelon.delivery_service import DeliveryRecoveryRequest, resume_delivery

    resume_delivery(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id=spec_id,
            extra_args=tuple(ctx.args),
            answer=answer,
            mode=mode,
            strategy=strategy,
        ),
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
    from echelon.delivery_service import DeliveryRecoveryRequest, continue_delivery

    continue_delivery(
        Path.cwd(),
        DeliveryRecoveryRequest(
            spec_id=spec_id,
            extra_args=tuple(ctx.args),
            mode=mode,
            strategy=strategy,
        ),
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
    from echelon.delivery_service import DeliveryLandRequest, land_delivery

    land_delivery(
        Path.cwd(),
        DeliveryLandRequest(
            spec_id,
            extra_args=tuple(ctx.args),
            continue_existing=continue_,
            prepare_only=prepare_only,
            autoresolve=not no_autoresolve,
            allow_fulfillment_gaps=allow_fulfillment_gaps,
            strategy=strategy,
        ),
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
    from echelon.delivery_service import list_checkpoints

    list_checkpoints(
        Path.cwd(),
        spec_id=spec_id,
        strategy=strategy,
        extra_args=tuple(ctx.args),
    )


def run(argv: list[str] | None = None) -> int | None:
    """Run the Typer CLI app with an explicit argv for tests or sys.argv[1:]."""
    args, quiet = _extract_quiet_option(argv)
    if args in (["-v"], ["--version"], ["version"]):
        from echelon.version import CLI_VERSION

        typer.echo(f"echelon {CLI_VERSION}")
        return
    from echelon.wiki import service as wiki_service

    project_root = Path.cwd()
    try:
        before = wiki_service.capture_input_snapshot(project_root)
    except Exception:
        before = None
    with verbose_mode(not quiet):
        exit_code = app(args=args, standalone_mode=False)
    try:
        refreshed = wiki_service.refresh_after_changed_command(project_root, before)
    except Exception as exc:
        typer.echo(f"warning: wiki auto-refresh failed: {exc}", err=True)
    else:
        if refreshed is not None:
            typer.echo(f"Wiki auto-refreshed: {refreshed.home_path}")
    return exit_code


def _extract_quiet_option(argv: list[str] | None) -> tuple[list[str] | None, bool]:
    """Accept --quiet at any command level without passing it to legacy handlers."""
    if argv is None:
        return None, False
    return [arg for arg in argv if arg != "--quiet"], "--quiet" in argv
