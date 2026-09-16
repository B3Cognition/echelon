from types import SimpleNamespace as NS

import pytest

import echelon.cli as cli
import echelon.re_preflight as preflight
import harness.re_v2.knowledge_creation as creation

pytestmark = pytest.mark.unit


def setup_creation(tmp_path, monkeypatch, intent=None):
    partition = NS(identity="partition", sources=(NS(
        source_id="api", domains=(None,) * 8,
        files=(NS(object_kind="regular", text_status="eligible_utf8",
                  byte_count=1_200_000, line_count=30_000),)),))
    monkeypatch.setattr(cli, "_capture_re_knowledge_authority", lambda _: (
        NS(snapshot_id="snapshot"), partition, ("api",), ()))
    monkeypatch.setattr("harness.re_registry.load_published_index", lambda _: None)
    monkeypatch.setattr("echelon.re_cli_options.configured_workspace_depth", lambda _: "standard")
    monkeypatch.setattr(creation, "load_reviewed_analysis_creation_intent", lambda _: intent)
    monkeypatch.setattr(creation, "ReviewedAnalysisCreationOptions", NS)
    monkeypatch.setattr(cli, "_new_re_v2_run_id", lambda _: "re-test")
    monkeypatch.setattr(cli, "_re_v2_now", lambda: "2026-09-16T12:00:00Z")
    activations, dispatches = [], []
    monkeypatch.setattr(cli, "_activate_re_v2_run", lambda _, run: activations.append(run))
    monkeypatch.setattr(creation, "create_or_resume_reviewed_analysis", lambda _, options: (
        dispatches.append(options) or NS(state="ready", analysis_run_id="re-test-analysis")))
    return activations, dispatches


def test_declined_preflight_does_not_activate_or_dispatch(tmp_path, monkeypatch):
    activations, dispatches = setup_creation(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Authorize explicitly"):
        cli._create_or_resume_re_knowledge_analysis(
            tmp_path, None, cli._ReKnowledgeActionOptions((), None, 5_000_000, 10_800_000), NS())
    assert activations == dispatches == []


def test_approved_ceiling_is_frozen_before_creation(tmp_path, monkeypatch):
    activations, dispatches = setup_creation(tmp_path, monkeypatch)
    monkeypatch.setattr(preflight, "authorize_knowledge_preflight", lambda *a, **k: 28_000_000)
    cli._create_or_resume_re_knowledge_analysis(
        tmp_path, None, cli._ReKnowledgeActionOptions((), None, 5_000_000, 10_800_000), NS())
    assert dispatches[0].token_limit == 28_000_000
    assert dispatches[0].active_ms_limit == 10_800_000


def test_resumed_creation_skips_preflight_and_preserves_frozen_ceiling(tmp_path, monkeypatch):
    intent = dict(snapshot_id="snapshot", workspace_partition_id="partition",
                  request_run_id="re-test", analysis_run_id="re-test-analysis",
                  created_at="2026-09-16T12:00:00Z", source_depths=[["api", "standard"]],
                  token_limit=28_000_000, active_ms_limit=10_800_000)
    _, dispatches = setup_creation(tmp_path, monkeypatch, intent)
    monkeypatch.setattr(preflight, "authorize_knowledge_preflight", lambda *a, **k: pytest.fail("resume must not estimate"))
    cli._create_or_resume_re_knowledge_analysis(
        tmp_path, tmp_path / "runs" / "re-test",
        cli._ReKnowledgeActionOptions((), None, 5_000_000, 10_800_000), NS())
    assert dispatches[0].token_limit == 28_000_000


def test_explicit_limit_provenance_survives_profile_resolution(tmp_path):
    explicit = cli._parse_re_knowledge_action_options(["--re-token-limit", "1000000"], allow_sources=False)
    configured = cli._parse_re_knowledge_action_options([], allow_sources=False)
    assert cli._resolve_re_knowledge_action_options(tmp_path, explicit).token_limit_explicit
    assert not cli._resolve_re_knowledge_action_options(tmp_path, configured).token_limit_explicit


def setup_refresh(tmp_path, monkeypatch, *, no_op=False, intent=None):
    from echelon.workspace_model import SourceRoot, WorkspaceInfo, WorkspaceManifest
    import harness.re_v2.knowledge_refresh as refresh
    import harness.re_v2.knowledge_workflow as workflow

    activations, dispatches = setup_creation(tmp_path, monkeypatch, intent)
    snapshot, partition, _, _ = cli._capture_re_knowledge_authority(tmp_path)
    manifest = WorkspaceManifest(1, WorkspaceInfo(tmp_path, "orchestration", False),
                                 (SourceRoot("api", "sources/api", True),))
    plan = NS(identity="plan", reanalyze_source_ids=() if no_op else ("api",),
              reusable_source_ids=("api",) if no_op else (), retained_source_ids=("sibling",),
              sources=(NS(source_id="api", depth="standard"),),
              no_op=no_op, needs_attention=False)
    monkeypatch.setattr(cli, "discover_workspace", lambda _: manifest)
    monkeypatch.setattr("harness.re_registry.load_published_index", lambda _: NS())
    monkeypatch.setattr("harness.config.load_config", lambda *a, **k: NS())
    monkeypatch.setattr("harness.re_v2.workspace_snapshot.capture_workspace_snapshot", lambda *a, **k: snapshot)
    monkeypatch.setattr("harness.re_v2.protocol_22.partition.build_workspace_partition_catalog", lambda *a: partition)
    monkeypatch.setattr(refresh, "snapshots_from_partition", lambda _: ())
    monkeypatch.setattr(refresh, "plan_knowledge_refresh", lambda **k: plan)
    monkeypatch.setattr("harness.re_lifecycle.resolve_current_re_run", lambda _: tmp_path / "runs" / "re-test" if intent else None)
    monkeypatch.setattr(workflow, "run_knowledge_refresh", lambda *a, **k: NS(state="complete"))
    return activations, dispatches


def test_refresh_estimates_changed_sources_and_freezes_approved_limit(tmp_path, monkeypatch):
    _, dispatches = setup_refresh(tmp_path, monkeypatch)
    estimates = []
    monkeypatch.setattr(preflight, "authorize_knowledge_preflight", lambda estimate, **k: estimates.append((estimate, k)) or 28_000_000)
    cli._run_re_knowledge_refresh_action(tmp_path, ("api",), "standard", 5_000_000, 10_800_000,
                                         token_limit_explicit=True)
    assert len(estimates) == 1
    assert estimates[0][0].source_count == 1
    assert estimates[0][1]["explicit_token_limit"] is True
    assert "--source" in estimates[0][1]["command"]
    assert dispatches[0].token_limit == 28_000_000


def test_no_op_refresh_has_zero_estimate_and_no_dispatch(tmp_path, monkeypatch):
    activations, dispatches = setup_refresh(tmp_path, monkeypatch, no_op=True)
    estimates = []
    monkeypatch.setattr(preflight, "authorize_knowledge_preflight", lambda estimate, **k: estimates.append(estimate) or k["token_limit"])
    cli._run_re_knowledge_refresh_action(tmp_path, (), None, 5_000_000, 10_800_000)
    assert len(estimates) == 1
    assert estimates[0].recommended_tokens == 0
    assert activations == dispatches == []


def test_refresh_resume_preserves_frozen_budget_without_new_preflight(tmp_path, monkeypatch):
    intent = dict(snapshot_id="snapshot", workspace_partition_id="partition",
                  request_run_id="re-test", analysis_run_id="re-test-analysis",
                  created_at="2026-09-16T12:00:00Z", source_depths=[["api", "standard"]],
                  token_limit=28_000_000, active_ms_limit=10_800_000,
                  selection=dict(schema_version=1, all_sources=False, source_ids=["api"], domain_keys=[]))
    _, dispatches = setup_refresh(tmp_path, monkeypatch, intent=intent)
    monkeypatch.setattr(preflight, "authorize_knowledge_preflight", lambda *a, **k: pytest.fail("resume must not estimate"))
    cli._run_re_knowledge_refresh_action(tmp_path, (), None, 5_000_000, 10_800_000)
    assert dispatches[0].token_limit == 28_000_000
