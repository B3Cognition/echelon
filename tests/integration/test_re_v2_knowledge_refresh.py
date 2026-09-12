"""Immutable source-authority merge for reviewed knowledge refreshes."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from types import SimpleNamespace

import pytest

from harness.re_registry import PublishedReIndex, PublishedSource, PublishedWorkspace
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_refresh import (
    CurrentSourceSnapshotV1,
    KnowledgeRefreshError,
    KnowledgeRefreshMergeAuthorityV1,
    merge_refresh_synthesis_parent,
    plan_knowledge_refresh,
)
from harness.re_v2.protocol_27.authority import ResolvedSynthesisParentV1
from harness.re_v2.protocol_27.model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    AcceptedSourceOverviewProjectionV1,
)
from tests.integration.test_re_v2_reviewed_synthesis import (
    _synthesis_agent,
    _terminal_reviewed_context_with_executor,
)
from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider
from tests.unit.test_re_v2_protocol_28_reconciliation import (
    KnowledgeBackend,
)


def _digest(value: str) -> str:
    return content_digest(value.encode("utf-8"))


_SYNTHETIC_AUTHORITY: dict[str, bytes] = {}


def _source(source_id: str, revision: str) -> AcceptedSourceOutcomeV1:
    root_payload = f"{source_id}:{revision}:root".encode("utf-8")
    lower_payload = f"{source_id}:{revision}:lower".encode("utf-8")
    root_hash = content_digest(root_payload)
    lower_hash = content_digest(lower_payload)
    _SYNTHETIC_AUTHORITY.update(
        {root_hash: root_payload, lower_hash: lower_payload}
    )
    return AcceptedSourceOutcomeV1(
        schema_version=1,
        source_id=source_id,
        source_root_key_id=_digest(f"{source_id}:{revision}:root-key"),
        source_root_hash=root_hash,
        outcome="complete",
        debt_manifest_hash=None,
        lower_authority_ids=(lower_hash,),
    )


def _parent(run_id: str, sources: tuple[AcceptedSourceOutcomeV1, ...]) -> ResolvedSynthesisParentV1:
    projections = tuple(
        AcceptedSourceOverviewProjectionV1(
            schema_version=1,
            source_id=source.source_id,
            selected_layer="reviewed",
            source_root_key_id=source.source_root_key_id,
            source_root_hash=source.source_root_hash,
            materializer_protocol_version="reviewed-v1",
            materializer_authority_hash=_digest("reviewed-materializer"),
            content_hash=_digest(f"{source.source_root_hash}:markdown"),
            object_hash=_digest(f"{source.source_root_hash}:markdown"),
        )
        for source in sources
    )
    payloads = {
        item.object_hash: f"# {item.source_id}\n".encode("utf-8")
        for item in projections
    }
    projections = tuple(
        replace(item, content_hash=content_digest(payloads[item.object_hash]), object_hash=content_digest(payloads[item.object_hash]))
        for item in projections
    )
    payloads = {
        item.object_hash: f"# {item.source_id}\n".encode("utf-8")
        for item in projections
    }
    authority = {
        value: _SYNTHETIC_AUTHORITY[value]
        for source in sources
        for value in (source.source_root_hash, *source.lower_authority_ids)
    }
    return ResolvedSynthesisParentV1(
        parent_run_id=run_id,
        parent_manifest_hash=_digest(f"{run_id}:manifest"),
        source_snapshot_id=_digest(f"{run_id}:snapshot"),
        partition_manifest_id=_digest(f"{run_id}:partition"),
        selected_layers={source.source_id: "reviewed" for source in sources},
        accepted_sources=sources,
        authority_objects=authority,
        debt_summary_hashes={},
        _overview_catalog=AcceptedSourceOverviewCatalogV1(1, projections),
        _overview_payloads=payloads,
        _overview_authorities={
            item.source_id: (item.source_root_key_id, item.content_hash)
            for item in projections
        },
    )


def _published() -> PublishedReIndex:
    return PublishedReIndex(
        schema_version=1,
        generation=3,
        publication_status="complete",
        published_at="2026-09-11T12:00:00Z",
        published_from_run="re-prior-synthesis",
        sources={
            source_id: PublishedSource(
                source_id=source_id,
                source_path=f"sources/{source_id}",
                published_path=f"re/sources/{source_id}",
                fingerprint=_digest(f"{source_id}:v1"),
                profile_hash=_digest("profile"),
                status="complete",
                manifest=f"re/sources/{source_id}/manifest.json",
                depth="standard",
            )
            for source_id in ("api", "worker")
        },
        workspace=PublishedWorkspace(
            manifest="re/workspace/manifest.json",
            overview="re/workspace/overview.md",
            relationships="re/workspace/relationships.md",
            contracts="re/workspace/contracts.md",
        ),
        warnings=(),
    )


def _refresh_plan(*, targeted: bool):
    selected = ("api",) if targeted else ("api", "worker")
    snapshots = tuple(
        CurrentSourceSnapshotV1(
            1,
            _digest("workspace:v2"),
            source_id,
            _digest(f"{source_id}:{'v2' if source_id == 'api' else 'v1'}"),
            f"sources/{source_id}",
        )
        for source_id in selected
    )
    return plan_knowledge_refresh(
        declared_source_ids=("api", "worker"),
        selected_snapshots=snapshots,
        selected_source_ids=selected if targeted else None,
        published=_published(),
        explicit_depth=None,
        workspace_default="standard",
    )


def _terminal_multi_source_context_with_executor(
    tmp_path,
    *,
    depth: str = "deep",
    api_extra_source_files: dict[str, str | bytes] | None = None,
    knowledge_backend=None,
):  # type: ignore[no-untyped-def]
    from harness.re_v2.knowledge_activation import (
        activate_reviewed_discovery,
        load_reviewed_discovery,
    )
    from harness.re_v2.knowledge_accounting import KnowledgeDispatchPolicy
    from harness.re_v2.knowledge_revision import activate_knowledge_workflow
    from harness.re_v2.protocol_22.executors import ExecutorContractCatalogV1
    from harness.re_v2.protocol_28.context import (
        initialize_protocol_28_run,
        load_protocol_28_run_context,
    )
    from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
    from harness.re_v2.protocol_28.inputs import (
        publish_protocol_28_run,
        stage_exhaustive_inputs,
    )
    from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
    from harness.re_v2.protocol_28.policies import build_repaired_exhaustive_policy
    from harness.re_v2.protocol_28.preparation import (
        ReviewedProtocol28PreparationOptions,
        prepare_protocol_28_request,
    )
    from tests.unit.test_re_v2_knowledge_activation import (
        activation_fixture,
        review_second_source,
    )
    from tests.unit.test_re_v2_protocol_22_executors import _shared_cli_entry

    api, account, review, l3, evidence, fixture = activation_fixture(
        tmp_path,
        multiple=True,
        depth=depth,
        extra_source_files=api_extra_source_files,
        account_policy=KnowledgeDispatchPolicy(5_000_000, 10_800_000, 3),
    )
    workspace, intent, parent, options = fixture
    first_root = activate_reviewed_discovery(api, account, review, l3, evidence)
    beta, beta_review = review_second_source(
        tmp_path,
        api,
        account,
        review,
        options,
        depth=depth,
    )
    second_root = activate_reviewed_discovery(
        beta,
        account,
        beta_review,
        l3,
        evidence,
    )
    bundles = tuple(
        load_reviewed_discovery(root, api.objects, l3, evidence)
        for root in (first_root, second_root)
    )
    executor_bytes = canonical_json_bytes(
        ExecutorContractCatalogV1(1, (_shared_cli_entry(),)).to_json_dict()
    )
    options = replace(
        options,
        inherited_executor_contract_bytes=executor_bytes,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )
    executor_catalog = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(executor_bytes),
        producer_agent_contract_hash=content_digest(options.producer_agent_bytes),
        verifier_agent_contract_hash=content_digest(options.verifier_agent_bytes),
    )
    policy = build_repaired_exhaustive_policy(
        producer_contract_hash=content_digest(options.producer_agent_bytes),
        verifier_contract_hash=content_digest(options.verifier_agent_bytes),
    )
    intent = replace(
        intent,
        executor_catalog_id=executor_catalog.identity,
        exhaustive_policy_catalog_id=policy.identity,
    )
    reviewed = ReviewedProtocol28PreparationOptions(
        **{field: getattr(options, field) for field in options.__dataclass_fields__},
        reviewed_discoveries=bundles,
    )
    inputs = prepare_protocol_28_request(workspace, intent, parent, reviewed)
    staged = stage_exhaustive_inputs(tmp_path / "private", inputs)
    published = publish_protocol_28_run(
        staged.root.parent,
        tmp_path / inputs.manifest.run_id,
        inputs.manifest,
    )
    context = load_protocol_28_run_context(published.root.parent)
    initialize_protocol_28_run(context)
    activate_knowledge_workflow(context, account, allow_debt=False)
    result = run_protocol_28_exhaustive(
        context.run_dir,
        lambda: knowledge_backend or KnowledgeBackend(),
    )
    assert result.state == "complete", result
    return context


@pytest.mark.integration
def test_refresh_merge_replaces_changed_source_and_authenticates_retained_source() -> None:
    prior = _parent("re-prior-synthesis", (_source("api", "v1"), _source("worker", "v1")))
    fresh = _parent("re-fresh-analysis", (_source("api", "v2"),))

    merged = merge_refresh_synthesis_parent(
        plan=_refresh_plan(targeted=True),
        fresh_parent=fresh,
        published_parent=prior,
        published=_published(),
    )

    by_source = {item.source_id: item for item in merged.accepted_sources}
    assert by_source["api"] == fresh.accepted_sources[0]
    assert by_source["worker"] == prior.accepted_sources[1]
    assert merged.parent_manifest_hash not in {
        fresh.parent_manifest_hash,
        prior.parent_manifest_hash,
    }
    assert merged.refresh_dispositions == {
        "api": "reanalyzed",
        "worker": "not_checked",
    }
    assert merged.checkpoint_origin_run_id == "re-prior-synthesis"


@pytest.mark.integration
def test_refresh_merge_rejects_stale_publication_before_synthesis() -> None:
    plan = _refresh_plan(targeted=True)
    prior = _parent("re-prior-synthesis", (_source("api", "v1"), _source("worker", "v1")))
    fresh = _parent("re-fresh-analysis", (_source("api", "v2"),))

    with pytest.raises(KnowledgeRefreshError, match="publication generation"):
        merge_refresh_synthesis_parent(
            plan=plan,
            fresh_parent=fresh,
            published_parent=prior,
            published=replace(_published(), generation=4),
        )

    with pytest.raises(KnowledgeRefreshError, match="fresh source coverage"):
        merge_refresh_synthesis_parent(
            plan=plan,
            fresh_parent=_parent(
                "re-fresh-analysis",
                (_source("api", "v2"), _source("worker", "v2")),
            ),
            published_parent=prior,
            published=_published(),
        )


@pytest.mark.integration
def test_refresh_topology_replaces_changed_source_and_keeps_retained_domains() -> None:
    from harness.re_v2.protocol_27.lifecycle import _merge_refresh_topology
    from tests.unit.test_re_v2_protocol_27_graph import _inputs

    prior = _inputs(source_ids=("api", "worker")).topology
    fresh = _inputs(source_ids=("api",)).topology
    merged = _merge_refresh_topology(
        prior,
        fresh,
        replaced_source_ids=frozenset({"api"}),
        partition_manifest_id=_digest("refresh-partition"),
        accepted_source_ids=frozenset({"api", "worker"}),
        fresh_source_ids=frozenset({"api"}),
    )

    assert merged.partition_manifest_id == _digest("refresh-partition")
    assert {item.source_id: item for item in merged.sources} == {
        "api": fresh.sources[0],
        "worker": next(item for item in prior.sources if item.source_id == "worker"),
    }
    assert {participant.source_id for domain in merged.workspace_domains for participant in domain.participants} == {
        "api",
        "worker",
    }


@pytest.mark.integration
def test_refresh_merge_authority_round_trips_for_child_recovery() -> None:
    merged = merge_refresh_synthesis_parent(
        plan=_refresh_plan(targeted=True),
        fresh_parent=_parent("re-fresh-analysis", (_source("api", "v2"),)),
        published_parent=_parent(
            "re-prior-synthesis",
            (_source("api", "v1"), _source("worker", "v1")),
        ),
        published=_published(),
    )
    authority = merged._refresh_authority
    assert isinstance(authority, KnowledgeRefreshMergeAuthorityV1)

    recovered = KnowledgeRefreshMergeAuthorityV1.from_json_dict(asdict(authority))

    assert recovered == authority
    assert recovered.identity == merged.parent_manifest_hash


@pytest.mark.integration
def test_refresh_workflow_persists_no_op_without_constructing_provider(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.re_v2 import knowledge_workflow

    published = _published()
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "worker"),
        selected_snapshots=tuple(
            CurrentSourceSnapshotV1(
                1,
                _digest("workspace:v1"),
                source_id,
                _digest(f"{source_id}:v1"),
                f"sources/{source_id}",
            )
            for source_id in ("api", "worker")
        ),
        selected_source_ids=None,
        published=published,
        explicit_depth=None,
        workspace_default="standard",
    )
    monkeypatch.setattr(knowledge_workflow, "load_published_index", lambda _root: published)

    result = knowledge_workflow.run_knowledge_refresh(
        tmp_path,
        plan,
        None,
        lambda: pytest.fail("no-op refresh constructed a provider"),
        token_limit=None,
        active_ms_limit=None,
    )

    assert result.state == "complete"
    assert result.reason_code == "already-current"
    receipt = tmp_path / result.receipt_path
    assert json.loads(receipt.read_text(encoding="utf-8"))["plan_id"] == plan.identity


@pytest.mark.integration
def test_refresh_workflow_reports_retryable_stale_generation(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.re_v2 import knowledge_workflow

    plan = _refresh_plan(targeted=True)
    monkeypatch.setattr(
        knowledge_workflow,
        "load_published_index",
        lambda _root: replace(_published(), generation=plan.publication_generation + 1),
    )

    result = knowledge_workflow.run_knowledge_refresh(
        tmp_path,
        plan,
        "re-fresh-analysis",
        lambda: pytest.fail("stale refresh constructed a provider"),
        token_limit=None,
        active_ms_limit=None,
    )

    assert result.state == "needs-attention"
    assert result.reason_code == "publication-conflict-retry-refresh"


@pytest.mark.integration
def test_refresh_workflow_continues_changed_analysis_into_merged_publication(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.re_v2 import knowledge_workflow

    plan = _refresh_plan(targeted=True)
    prior = _parent(
        "re-prior-synthesis",
        (_source("api", "v1"), _source("worker", "v1")),
    )
    fresh = _parent("re-fresh-analysis", (_source("api", "v2"),))
    current = _published()
    holder = {"index": current}
    (tmp_path / "runs" / "re-fresh-analysis").mkdir(parents=True)
    monkeypatch.setattr(
        knowledge_workflow,
        "load_published_index",
        lambda _root: holder["index"],
    )
    monkeypatch.setattr(
        knowledge_workflow,
        "run_protocol_28_exhaustive",
        lambda _run, _provider: SimpleNamespace(state="complete", reason_code=None),
    )
    monkeypatch.setattr(
        knowledge_workflow,
        "load_protocol_28_run_context",
        lambda _run: SimpleNamespace(resources=SimpleNamespace(records=())),
    )
    monkeypatch.setattr(
        knowledge_workflow,
        "resolve_reviewed_synthesis_parent",
        lambda _root, _run: fresh,
    )
    monkeypatch.setattr(
        knowledge_workflow,
        "resolve_synthesis_parent",
        lambda _root, _run, _partial: prior,
    )

    def publish(_root, merged, _budget, _provider, *, fault_hook=None):  # type: ignore[no-untyped-def]
        assert merged.refresh_dispositions == {
            "api": "reanalyzed",
            "worker": "not_checked",
        }
        holder["index"] = replace(
            current,
            generation=current.generation + 1,
            published_from_run="re-refresh-synthesis",
        )
        return SimpleNamespace(terminal_kind="complete")

    monkeypatch.setattr(knowledge_workflow, "execute_protocol_27_parent", publish)

    result = knowledge_workflow.run_knowledge_refresh(
        tmp_path,
        plan,
        "re-fresh-analysis",
        object,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )

    assert result.state == "complete"
    assert result.synthesis_run_id == "re-refresh-synthesis"
    assert result.publication_generation == 4


@pytest.mark.integration
def test_refresh_child_recovers_merge_authority_and_publishes_one_new_generation(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.re_registry import load_published_index
    from harness.re_v2.knowledge_workflow import run_knowledge_workflow
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
    from harness.re_v2.protocol_27.inputs import load_protocol_27_inputs
    from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_parent
    from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1

    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, _name: _synthesis_agent(),
    )
    prior_context = _terminal_multi_source_context_with_executor(tmp_path / "runs")
    initial_provider = _ScriptedProvider()
    initial = run_knowledge_workflow(
        tmp_path,
        prior_context.run_dir.name,
        lambda: initial_provider,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )
    assert initial.state == "complete", initial
    published = load_published_index(tmp_path)
    assert published is not None and published.generation == 1
    assert set(published.sources) == {"api", "beta"}
    from harness.published_re_context import attach_published_re_context

    old_consumer = tmp_path / "runs" / "spec-old"
    old_consumer.mkdir()
    old_context = attach_published_re_context(
        tmp_path,
        old_consumer,
        ignore=False,
    )
    old_snapshot = old_consumer / "context" / "published-re" / "workspace" / "overview.md"
    old_snapshot_bytes = old_snapshot.read_bytes()
    prior_parent = resolve_synthesis_parent(
        tmp_path,
        published.published_from_run,
        (),
    )

    fresh_context = _terminal_reviewed_context_with_executor(tmp_path / "fresh")
    fresh_parent = resolve_synthesis_parent(
        tmp_path / "fresh",
        fresh_context.run_dir.name,
        (),
    )
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "beta"),
        selected_snapshots=(
            CurrentSourceSnapshotV1(
                1,
                _digest("workspace:v2"),
                "api",
                _digest("api:v2"),
                "sources/api",
            ),
        ),
        selected_source_ids=("api",),
        published=published,
        explicit_depth=None,
        workspace_default="standard",
    )
    merged = merge_refresh_synthesis_parent(
        plan=plan,
        fresh_parent=fresh_parent,
        published_parent=prior_parent,
        published=published,
    )
    refresh_provider = _ScriptedProvider()

    result = execute_protocol_27_parent(
        tmp_path,
        merged,
        synthesis_budget_policy_v1(
            token_limit=10_000_000,
            active_ms_limit=10_000_000,
        ),
        lambda: refresh_provider,
    )

    assert result.synthesis_closure_complete
    refreshed = load_published_index(tmp_path)
    assert refreshed is not None and refreshed.generation == 2
    assert refreshed.published_from_run != published.published_from_run
    assert refreshed.sources["api"].freshness == "reanalyzed"
    assert refreshed.sources["beta"].freshness == "not_checked"
    new_consumer = tmp_path / "runs" / "spec-new"
    new_consumer.mkdir()
    new_context = attach_published_re_context(
        tmp_path,
        new_consumer,
        ignore=False,
    )
    assert old_context["generation"] == 1
    assert new_context["generation"] == 2
    assert old_snapshot.read_bytes() == old_snapshot_bytes
    loaded = load_protocol_27_inputs(
        tmp_path / "runs" / refreshed.published_from_run
    )
    assert loaded.parent_authority.refresh_dispositions == {
        "api": "reanalyzed",
        "beta": "not_checked",
    }
    assert loaded.parent_authority.checkpoint_origin_run_id == published.published_from_run
