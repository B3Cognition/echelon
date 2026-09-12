"""Reviewed RE authority enters the existing workspace-synthesis lifecycle."""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
from tests.unit.test_re_v2_protocol_28_reconciliation import (
    KnowledgeBackend,
    reconciliation_fixture,
)


def _reviewed_context_with_executor(
    tmp_path,
    *,
    complete: bool,
    depth: str = "deep",
    extra_source_files: dict[str, str | bytes] | None = None,
    knowledge_backend=None,
):
    from harness.re_v2.canonical import canonical_json_bytes, content_digest
    from harness.re_v2.protocol_22.executors import ExecutorContractCatalogV1
    from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
    from tests.unit.test_re_v2_protocol_22_executors import _shared_cli_entry
    from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture

    workspace, intent, parent_authority, options = _preparation_fixture(
        tmp_path / "runs",
        extra_source_files=extra_source_files,
    )
    executor_bytes = canonical_json_bytes(
        ExecutorContractCatalogV1(1, (_shared_cli_entry(),)).to_json_dict()
    )
    intent = replace(
        intent,
        executor_catalog_id=build_l4_executor_catalog(
            inherited_executor_contract_hash=content_digest(executor_bytes),
            producer_agent_contract_hash=content_digest(options.producer_agent_bytes),
            verifier_agent_contract_hash=content_digest(options.verifier_agent_bytes),
        ).identity,
    )
    context, *_ = reconciliation_fixture(
        tmp_path / "runs",
        prepared=(
            workspace,
            intent,
            parent_authority,
            replace(options, inherited_executor_contract_bytes=executor_bytes),
        ),
        depth=depth,
    )
    if complete:
        assert run_protocol_28_exhaustive(
            context.run_dir, lambda: knowledge_backend or KnowledgeBackend()
        ).state == "complete"
    return context


def _terminal_reviewed_context_with_executor(
    tmp_path,
    *,
    depth: str = "deep",
    extra_source_files: dict[str, str | bytes] | None = None,
    knowledge_backend=None,
):
    return _reviewed_context_with_executor(
        tmp_path,
        complete=True,
        depth=depth,
        extra_source_files=extra_source_files,
        knowledge_backend=knowledge_backend,
    )


def _synthesis_agent():
    from harness.prosaic_prompt_loader import ProsaicCommandArtifact

    return ProsaicCommandArtifact(
        frontmatter={
            "name": "echelon.re-synthesizer",
            "description": "Synthetic reviewed synthesis fixture",
            "execution": "agent",
            "tools": "write",
            "color": "orange",
            "model_tier": "strong",
            "effort": "high",
        },
        body="Synthesize only supported supplied knowledge.",
    )


@pytest.mark.integration
def test_synthesis_parent_router_accepts_only_terminal_reviewed_authority(
    tmp_path,
) -> None:
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent

    context, *_ = reconciliation_fixture(tmp_path / "runs")
    assert run_protocol_28_exhaustive(
        context.run_dir, lambda: KnowledgeBackend()
    ).state == "complete"

    parent = resolve_synthesis_parent(
        tmp_path,
        context.run_dir.name,
        (),
        context_loader=lambda _workspace, _run: SimpleNamespace(
            inputs=context.inputs
        ),
    )

    assert parent.parent_run_id == context.run_dir.name
    assert parent.selected_layers == {"api": "reviewed"}
    assert parent._overview_catalog is not None


@pytest.mark.integration
def test_reviewed_parent_builds_existing_protocol_27_synthesis_inputs(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.prosaic_prompt_loader import (
        ProsaicCommandArtifact,
        ProsaicPromptLoader,
    )
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
    from harness.re_v2.protocol_27.lifecycle import (
        _protocol_27_input_set,
        synthesis_request,
    )
    from harness.re_v2.protocol_27.inputs import (
        load_protocol_27_inputs,
        prepare_protocol_27_child,
    )
    from harness.re_v2.publication import EMPTY_INDEX_HASH
    from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1
    context = _terminal_reviewed_context_with_executor(tmp_path)
    parent = resolve_synthesis_parent(tmp_path, context.run_dir.name, ())
    budget = synthesis_budget_policy_v1()
    request = synthesis_request(
        parent,
        budget,
        expected_v2_index_hash=EMPTY_INDEX_HASH,
        expected_compatibility_generation=0,
    )
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, _name: _synthesis_agent(),
    )

    inputs = _protocol_27_input_set(
        tmp_path,
        "re-reviewed-synthesis",
        "2026-09-11T12:00:00Z",
        parent,
        request,
        budget,
    )

    assert inputs.parent == parent
    assert inputs.source_overview_catalog.projections[0].selected_layer == "reviewed"
    assert inputs.graph.topology.partition_manifest_id == parent.partition_manifest_id
    assert {item.source_id for item in inputs.graph.topology.sources} == {"api"}
    assert inputs.graph.root_specification.input_quality == "complete"
    prepared = prepare_protocol_27_child(
        tmp_path,
        "re-reviewed-synthesis",
        inputs,
    )
    loaded = load_protocol_27_inputs(prepared.run_dir)
    assert loaded.manifest.parent_run_id == context.run_dir.name
    assert loaded.source_overview_catalog == inputs.source_overview_catalog


@pytest.mark.integration
def test_reviewed_synthesis_publishes_and_is_consumed_as_one_generation(
    tmp_path,
    monkeypatch,
) -> None:
    from harness.prosaic_prompt_loader import (
        ProsaicCommandArtifact,
        ProsaicPromptLoader,
    )
    from harness.published_re_context import attach_published_re_context
    from harness.re_registry import load_published_index
    from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_request
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    from harness.re_v2.reviewed_synthesis_parent import resolve_reviewed_synthesis_parent
    from tests.unit.test_re_v2_protocol_27_controller import _ScriptedProvider

    context = _terminal_reviewed_context_with_executor(tmp_path)
    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, _name: _synthesis_agent(),
    )
    provider = _ScriptedProvider()

    result = execute_protocol_27_request(
        tmp_path,
        SimpleNamespace(
            from_run=context.run_dir.name,
            accepted_partial_sources=(),
            token_limit=10_000_000,
            active_ms_limit=10_000_000,
        ),
        lambda: provider,
    )

    assert result.synthesis_closure_complete
    index = load_published_index(tmp_path)
    assert index is not None
    assert index.generation == 1
    assert index.publication_status == "complete"
    assert index.published_from_run != context.run_dir.name
    assert index.sources["api"].depth == "deep"
    source_target = next(
        item
        for item in context.inputs.l3_projection_catalog.projections
        if item.source_id == "api" and item.target_kind == "source"
    )
    assert index.sources["api"].fingerprint == source_target.target_content_id
    assert index.sources["api"].source_path == "sources/api"
    source_manifest = json.loads(
        (tmp_path / index.sources["api"].manifest).read_text(encoding="utf-8")
    )
    assert source_manifest["depth"] == "deep"
    assert source_manifest["run_id"] == index.published_from_run
    assert source_manifest["snapshot_id"] == context.inputs.manifest.source_snapshot_id
    assert source_manifest["knowledge_root_id"] in {
        item.source_root_hash
        for item in resolve_reviewed_synthesis_parent(
            tmp_path, context.run_dir.name
        ).accepted_sources
    }
    assert index.synthesis_quality is not None
    assert source_manifest["accepted_source_outcome_id"] in set(
        index.synthesis_quality.accepted_source_outcome_ids
    )
    assert source_manifest["quality"] == "complete"
    assert source_manifest["debt_manifest_id"] is None
    consumer_run = tmp_path / "runs" / "spec-consumer"
    consumer_run.mkdir()
    attached = attach_published_re_context(
        tmp_path,
        consumer_run,
        ignore=False,
        re_sources=["api"],
    )
    assert attached["status"] == "attached"
    assert attached["generation"] == 1
    assert attached["synthesis_quality"]["input_quality"] == "complete"
    status = protocol_28_status_document(context.run_dir)
    assert status["post_l4"] == {
        "synthesis": "complete",
        "publication": "published_complete",
        "run_id": index.published_from_run,
    }
