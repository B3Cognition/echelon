"""Ordinary depth-based CLI routing for the reviewed knowledge workflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.integration
def test_normal_run_uses_current_reviewed_analysis_and_configured_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import echelon.cli as cli
    import harness.re_v2.knowledge_workflow as workflow

    run_dir = tmp_path / "runs" / "re-reviewed"
    run_dir.mkdir(parents=True)
    config_dir = tmp_path / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        """re:
  default_profile: balanced
  profiles:
    balanced:
      hard_token_limit: 17000000
      hard_active_minutes: 360
""",
        encoding="utf-8",
    )
    config = object()
    provider = object()
    calls: list[tuple[Path, str, object, int | None, int | None]] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run", lambda _root: run_dir
    )
    monkeypatch.setattr("harness.config.load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider",
        lambda actual: provider if actual is config else pytest.fail("wrong config"),
    )

    def execute(root, run_id, provider_factory, *, token_limit, active_ms_limit):
        calls.append((root, run_id, provider_factory(), token_limit, active_ms_limit))
        return workflow.KnowledgeWorkflowResultV1(
            run_id, "complete", "re-synthesis", 4, None
        )

    monkeypatch.setattr(workflow, "run_knowledge_workflow", execute)
    monkeypatch.setattr(cli, "_is_reviewed_analysis_run", lambda _path: True)
    monkeypatch.setattr(cli, "_reviewed_run_depths", lambda _path: {"api": "deep"})

    cli._cmd_re_knowledge_run(["--depth", "deep"])

    assert calls == [
        (tmp_path.resolve(), "re-reviewed", provider, 17_000_000, 21_600_000)
    ]
    output = capsys.readouterr().out
    assert "completed" in output
    assert "generation 4" in output
    assert "deep" in output


@pytest.mark.integration
@pytest.mark.parametrize("reset", [False, True])
def test_normal_run_creates_reviewed_analysis_when_none_is_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], reset: bool
) -> None:
    import echelon.cli as cli
    import harness.re_v2.knowledge_workflow as workflow

    run_dir = tmp_path / "runs" / "re-created-analysis"
    run_dir.mkdir(parents=True)
    config = object()
    provider = object()
    creations = []
    old_run = tmp_path / "runs" / "re-failed"
    old_run.mkdir(parents=True)
    old_state = old_run / "state.json"
    old_state.write_text('{"status":"blocked","blocked_reason":"re_token_budget_exhausted"}')
    old_bytes = old_state.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run", lambda _root: old_run if reset else None
    )
    monkeypatch.setattr("harness.config.load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        "harness.squad_provider.SquadCliProvider", lambda actual: provider
    )
    monkeypatch.setattr(cli, "_is_reviewed_analysis_run", lambda _path: False)
    monkeypatch.setattr(
        cli,
        "_create_or_resume_re_knowledge_analysis",
        lambda root, active, options, actual_config: (
            creations.append((root, active, options.depth, actual_config)) or run_dir,
            "standard",
        ),
    )
    monkeypatch.setattr(
        cli, "_reviewed_run_depths", lambda _path: {"api": "standard"}
    )
    monkeypatch.setattr(
        workflow,
        "run_knowledge_workflow",
        lambda root, run_id, provider_factory, **_kwargs: (
            provider_factory(),
            workflow.KnowledgeWorkflowResultV1(
                run_id, "complete", "re-synthesis", 1, None
            ),
        )[1],
    )

    cli._cmd_re_knowledge_run(["--reset"] if reset else [])

    assert creations == [(tmp_path.resolve(), None, None, config)]
    assert old_state.read_bytes() == old_bytes
    output = capsys.readouterr().out
    assert "completed" in output
    assert "generation 1" in output


@pytest.mark.integration
def test_continue_reviewed_analysis_resumes_full_configured_provider_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import echelon.cli as cli
    import harness.config
    import harness.re_v2.knowledge_workflow as workflow
    import harness.re_v2.protocol_28.context as context_module
    import harness.squad_provider

    class ReviewedContext:
        pass

    run_dir = tmp_path / "runs" / "re-reviewed-analysis"
    run_dir.mkdir(parents=True)
    config = object()
    provider = object()
    calls = []
    monkeypatch.setattr(context_module, "Protocol28RunContext", ReviewedContext)
    monkeypatch.setattr(cli, "_re_v2_context", lambda _root, _run: ReviewedContext())
    monkeypatch.setattr(cli, "_installed_re_runtime_or_exit", lambda _root: None)
    monkeypatch.setattr(cli, "_is_reviewed_analysis_run", lambda _run: True)
    monkeypatch.setattr(cli, "_reviewed_run_depths", lambda _run: {"api": "quick"})
    monkeypatch.setattr(harness.config, "load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        harness.squad_provider,
        "SquadCliProvider",
        lambda actual: provider if actual is config else pytest.fail("wrong config"),
    )

    def execute(root, run_id, provider_factory, *, token_limit, active_ms_limit):
        calls.append((root, run_id, provider_factory(), token_limit, active_ms_limit))
        return workflow.KnowledgeWorkflowResultV1(
            run_id, "complete", "re-synthesis", 5, None
        )

    monkeypatch.setattr(workflow, "run_knowledge_workflow", execute)

    cli._run_re_v2_continue(
        run_dir,
        token_limit=2_000_000,
        time_limit_minutes=30,
    )

    assert calls == [
        (tmp_path.resolve(), "re-reviewed-analysis", provider, 2_000_000, 1_800_000)
    ]
    output = capsys.readouterr().out
    assert "continue completed" in output
    assert "generation 5" in output


@pytest.mark.integration
def test_normal_refresh_accepts_multiple_sources_and_preserves_absolute_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import echelon.cli as cli

    captured: list[tuple[tuple[str, ...], str | None, int, int]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_run_re_knowledge_refresh_action",
        lambda _root, sources, depth, tokens, active: captured.append(
            (sources, depth, tokens, active)
        ),
        raising=False,
    )

    cli._cmd_re_knowledge_refresh(
        [
            "--source",
            "api",
            "--source=worker",
            "--depth",
            "standard",
            "--re-token-limit",
            "7000000",
            "--re-time-limit-minutes",
            "240",
        ]
    )

    assert captured == [(('api', 'worker'), 'standard', 7_000_000, 14_400_000)]


@pytest.mark.integration
def test_normal_refresh_uses_workspace_profile_limits_when_not_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import echelon.cli as cli

    config_dir = tmp_path / ".echelon"
    config_dir.mkdir()
    (config_dir / "config.yml").write_text(
        """re:
  default_profile: balanced
  profiles:
    balanced:
      hard_token_limit: 17000000
      hard_active_minutes: 360
""",
        encoding="utf-8",
    )
    captured: list[tuple[tuple[str, ...], str | None, int, int]] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_run_re_knowledge_refresh_action",
        lambda _root, sources, depth, tokens, active: captured.append(
            (sources, depth, tokens, active)
        ),
        raising=False,
    )

    cli._cmd_re_knowledge_refresh(["--depth", "deep"])

    assert captured == [((), "deep", 17_000_000, 21_600_000)]


@pytest.mark.integration
def test_normal_refresh_rejects_duplicate_source_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import echelon.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "_run_re_knowledge_refresh_action",
        lambda *_a: pytest.fail("duplicate source reached execution"),
        raising=False,
    )

    with pytest.raises(SystemExit) as failure:
        cli._cmd_re_knowledge_refresh(
            ["--source", "api", "--source", "api"]
        )

    assert failure.value.code == 2


@pytest.mark.integration
def test_depth_refresh_creates_fresh_reviewed_analysis_instead_of_using_published_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import echelon.cli as cli
    import harness.config
    import harness.re_registry as registry
    import harness.re_v2.knowledge_creation as creation
    import harness.re_v2.knowledge_workflow as workflow
    import harness.re_v2.protocol_22.partition as partition_module
    import harness.re_v2.workspace_snapshot as snapshot_module
    import harness.squad_provider
    from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_22.partition import (
        ImplementationAuthorityV1,
        PartitionAuthoritiesV1,
        build_workspace_partition_catalog,
    )
    from harness.re_v2.workspace_snapshot import capture_workspace_snapshot
    from tests.unit.test_re_v2_protocol_28_evidence import _git

    workspace = tmp_path / "workspace"
    source_root = workspace / "sources" / "api"
    source_root.mkdir(parents=True)
    _git(source_root, "init")
    (source_root / "README.md").write_text("API service\n", encoding="utf-8")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "fixture")
    source = SourceRoot(id="api", path="sources/api", git_present=True)
    manifest = WorkspaceManifest(
        schema_version=1,
        workspace=WorkspaceInfo(
            root=workspace.resolve(), git_role="orchestration", git_present=False
        ),
        sources=(source,),
    )
    snapshot = capture_workspace_snapshot(workspace, (source,), tmp_path / "snapshots")
    partition = build_workspace_partition_catalog(
        snapshot,
        manifest,
        PartitionAuthoritiesV1(
            ImplementationAuthorityV1(
                "existing-domain-partitioner", "5", content_digest(b"partitioner")
            ),
            ImplementationAuthorityV1(
                "explicit-domain-ownership", "1", content_digest(b"ownership")
            ),
        ),
    )
    published_run = workspace / "runs" / "re-published-synthesis"
    published_run.mkdir(parents=True)
    published = registry.PublishedReIndex(
        schema_version=1,
        generation=1,
        publication_status="complete",
        published_at="2026-09-12T12:00:00Z",
        published_from_run=published_run.name,
        sources={
            "api": registry.PublishedSource(
                source_id="api",
                source_path="sources/api",
                published_path="re/sources/api",
                fingerprint=partition.sources[0].source_content_id,
                profile_hash=content_digest(b"profile"),
                status="complete",
                manifest="re/sources/api/manifest.json",
                depth="quick",
            )
        },
        workspace=registry.PublishedWorkspace(
            manifest="re/workspace/manifest.json",
            overview="re/workspace/overview.md",
            relationships="re/workspace/relationships.md",
            contracts="re/workspace/contracts.md",
        ),
        warnings=(),
    )
    captured: dict[str, object] = {}
    config = object()

    monkeypatch.setattr(cli, "discover_workspace", lambda _root: manifest)
    monkeypatch.setattr(registry, "load_published_index", lambda _root: published)
    monkeypatch.setattr(snapshot_module, "capture_workspace_snapshot", lambda *_a: snapshot)
    monkeypatch.setattr(
        partition_module, "build_workspace_partition_catalog", lambda *_a: partition
    )
    monkeypatch.setattr(harness.config, "load_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        "harness.re_lifecycle.resolve_current_re_run", lambda _root: published_run
    )
    monkeypatch.setattr(cli, "_new_re_v2_run_id", lambda _root: "re-refresh-request")
    monkeypatch.setattr(cli, "_re_v2_now", lambda: "2026-09-12T12:30:00Z")
    monkeypatch.setattr(cli, "_activate_re_v2_run", lambda *_a: None)

    def create(_root, options):  # type: ignore[no-untyped-def]
        captured["creation"] = options
        return creation.KnowledgeCreationResultV1(
            options.request_run_id, "ready", options.analysis_run_id
        )

    monkeypatch.setattr(creation, "create_or_resume_reviewed_analysis", create)
    monkeypatch.setattr(harness.squad_provider, "SquadCliProvider", lambda _c: object())

    def refresh(_root, plan, analysis_run_id, _provider_factory, **_limits):  # type: ignore[no-untyped-def]
        captured["plan"] = plan
        captured["analysis_run_id"] = analysis_run_id
        return workflow.KnowledgeRefreshResultV1(
            plan.identity,
            analysis_run_id,
            "complete",
            "re-refresh-synthesis",
            2,
            None,
            "runs/re-refresh/result.json",
        )

    monkeypatch.setattr(workflow, "run_knowledge_refresh", refresh)

    cli._run_re_knowledge_refresh_action(
        workspace,
        (),
        "standard",
        8_000_000,
        10_800_000,
    )

    options = captured["creation"]
    assert options.request_run_id == "re-refresh-request"
    assert options.analysis_run_id == "re-refresh-request-analysis"
    assert options.selection.source_ids == ("api",)
    assert options.source_depths == (("api", "standard"),)
    assert captured["analysis_run_id"] == "re-refresh-request-analysis"
    assert "aggregate ceiling 8000000 tokens / 180 minutes" in capsys.readouterr().out
