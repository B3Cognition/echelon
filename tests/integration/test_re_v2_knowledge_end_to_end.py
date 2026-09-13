"""Offline acceptance for reviewed two-service knowledge and refresh."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_refresh import (
    CurrentSourceSnapshotV1,
    merge_refresh_synthesis_parent,
    plan_knowledge_refresh,
)
from tests.integration.test_re_v2_knowledge_refresh import (
    _terminal_multi_source_context_with_executor,
)
from tests.integration.test_re_v2_reviewed_synthesis import (
    _synthesis_agent,
    _terminal_reviewed_context_with_executor,
)
from tests.unit.test_re_v2_protocol_27_controller import (
    _candidate,
    _context_from_prompt,
    _result,
)
from tests.unit.test_re_v2_protocol_28_reconciliation import KnowledgeBackend


class _TwoServiceSynthesisProvider:
    """Deterministic offline stand-in for the configured synthesis provider."""

    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []

    def exec_agent(
        self,
        project_root: str,
        prompt: str,
        **_kwargs,
    ):  # type: ignore[no-untyped-def]
        context = _context_from_prompt(prompt)
        self.contexts.append(context)
        payload = json.loads(_candidate(context))
        kind = str(context["artifact_kind"])
        scope = context["scope"]
        assert isinstance(scope, dict)
        source_id = scope.get("source_id")
        if kind == "workspace-relationships":
            statement = (
                "Service api calls service beta through the observed order interface."
            )
        elif source_id == "api":
            statement = "Service api owns the caller side of the beta integration."
        elif source_id == "beta":
            statement = "Service beta owns the called order-handling interface."
        else:
            statement = "The accepted source authorities establish this workspace view."
        payload["claims"][0]["statement"] = statement
        Path(project_root, "synthesis.json").write_bytes(
            canonical_json_bytes(payload)
        )
        return _result()


class _OfflineProvider:
    def __init__(self) -> None:
        self.analysis = KnowledgeBackend()
        self.synthesis = _TwoServiceSynthesisProvider()

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.analysis.execute(*args, **kwargs)

    def exec_agent(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return self.synthesis.exec_agent(*args, **kwargs)


def _digest(value: str) -> str:
    return content_digest(value.encode("utf-8"))


def _two_service_analysis(role, context, value):  # type: ignore[no-untyped-def]
    if role != "producer":
        return value
    if context.get("kind") == "knowledge-reconciliation":
        work = context["work_item"]
        if work["scope"] == "source" and work["source_id"] == "api":
            value["rendered_markdown"] = (
                "# api\n\nThe API service calls beta through create_order.\n"
            )
        elif work["scope"] == "source" and work["source_id"] == "beta":
            value["rendered_markdown"] = (
                "# beta\n\nThe beta service provides create_order handling.\n"
            )
        return value
    source_id = context["plan_entry"]["source_id"]
    if source_id == "api":
        value["claims"][0]["statement"] = (
            "The observed API handler calls beta.create_order."
        )
    elif source_id == "beta":
        value["claims"][0]["statement"] = (
            "The observed beta handler provides order handling."
        )
    return value


def _assert_full_publication(root: Path, source_ids: tuple[str, ...]) -> None:
    for source_id in source_ids:
        for filename in (
            "overview.md",
            "architecture.md",
            "contracts.md",
            "components.md",
            "manifest.json",
        ):
            assert (root / "re" / "sources" / source_id / filename).is_file()
    for filename in ("overview.md", "relationships.md", "contracts.md"):
        assert (root / "re" / "workspace" / filename).is_file()
    assert list((root / "re" / "workspace" / "domains").glob("*.md"))


@pytest.mark.integration
def test_standard_two_service_run_refresh_and_consumer_pinning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.prosaic_prompt_loader import ProsaicPromptLoader
    from harness.published_re_context import attach_published_re_context
    from harness.re_registry import load_published_index
    from harness.re_v2.knowledge_workflow import run_knowledge_workflow
    from harness.re_v2.protocol_27.authority import resolve_synthesis_parent
    from harness.re_v2.protocol_27.lifecycle import execute_protocol_27_parent
    from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1

    monkeypatch.setattr(
        ProsaicPromptLoader,
        "load_subagent",
        lambda _self, _name: _synthesis_agent(),
    )
    initial_context = _terminal_multi_source_context_with_executor(
        tmp_path / "runs",
        depth="standard",
        knowledge_backend=KnowledgeBackend(mutate=_two_service_analysis),
        api_extra_source_files={
            "src/orders/handler.py": (
                "def handle(beta):\n    return beta.create_order(version=1)\n"
            )
        },
    )
    initial_provider = _OfflineProvider()
    initial = run_knowledge_workflow(
        tmp_path,
        initial_context.run_dir.name,
        lambda: initial_provider,
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )

    assert initial.state == "complete"
    generation_one = load_published_index(tmp_path)
    assert generation_one is not None and generation_one.generation == 1
    assert set(generation_one.sources) == {"api", "beta"}
    assert {source.depth for source in generation_one.sources.values()} == {
        "standard"
    }
    _assert_full_publication(tmp_path, ("api", "beta"))
    api_overview = (tmp_path / "re" / "sources" / "api" / "overview.md").read_text(
        encoding="utf-8"
    )
    assert "calls beta through create_order" in api_overview
    relationships = (tmp_path / "re" / "workspace" / "relationships.md").read_text(
        encoding="utf-8"
    )
    assert "Service api calls service beta" in relationships

    old_spec = tmp_path / "runs" / "spec-generation-one"
    old_spec.mkdir()
    old_context = attach_published_re_context(tmp_path, old_spec, ignore=False)
    old_overview = (
        old_spec / "context" / "published-re" / "workspace" / "overview.md"
    )
    old_overview_bytes = old_overview.read_bytes()

    prior_parent = resolve_synthesis_parent(
        tmp_path,
        generation_one.published_from_run,
        (),
    )
    fresh_context = _terminal_reviewed_context_with_executor(
        tmp_path / "fresh",
        depth="standard",
        knowledge_backend=KnowledgeBackend(mutate=_two_service_analysis),
        extra_source_files={
            "src/orders/handler.py": (
                "def handle(beta):\n    return beta.create_order(version=2)\n"
            )
        },
    )
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
                _digest("workspace:A2"),
                "api",
                fresh_context.inputs.manifest.source_snapshot_id,
                "sources/api",
            ),
        ),
        selected_source_ids=("api",),
        published=generation_one,
        explicit_depth=None,
        workspace_default="standard",
    )
    merged = merge_refresh_synthesis_parent(
        plan=plan,
        fresh_parent=fresh_parent,
        published_parent=prior_parent,
        published=generation_one,
    )
    refresh_provider = _TwoServiceSynthesisProvider()
    refreshed_result = execute_protocol_27_parent(
        tmp_path,
        merged,
        synthesis_budget_policy_v1(
            token_limit=10_000_000,
            active_ms_limit=10_000_000,
        ),
        lambda: refresh_provider,
    )

    assert refreshed_result.synthesis_closure_complete
    generation_two = load_published_index(tmp_path)
    assert generation_two is not None and generation_two.generation == 2
    assert generation_two.sources["api"].freshness == "reanalyzed"
    assert generation_two.sources["beta"].freshness == "not_checked"
    source_dispatches = {
        str(context["scope"]["source_id"])
        for context in refresh_provider.contexts
        if str(context["artifact_kind"]).startswith("source-")
    }
    assert source_dispatches == {"api"}
    assert {
        str(context["artifact_kind"])
        for context in refresh_provider.contexts
        if str(context["artifact_kind"]).startswith("workspace-")
    } >= {
        "workspace-overview",
        "workspace-relationships",
        "workspace-contracts",
        "workspace-domain-summary",
    }
    _assert_full_publication(tmp_path, ("api", "beta"))

    new_spec = tmp_path / "runs" / "spec-generation-two"
    new_spec.mkdir()
    new_context = attach_published_re_context(tmp_path, new_spec, ignore=False)
    assert old_context["generation"] == 1
    assert new_context["generation"] == 2
    assert old_overview.read_bytes() == old_overview_bytes
    generation_manifests = list(
        (tmp_path / "re" / "v2" / "generations").glob("*/manifest.json")
    )
    assert len(generation_manifests) == 2
