from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_registry import (
    PublishedReIndex,
    PublishedSource,
    PublishedWorkspace,
)
from harness.re_v2.canonical import content_digest
from harness.re_v2.knowledge_refresh import (
    CurrentSourceSnapshotV1,
    KnowledgeRefreshError,
    plan_knowledge_refresh,
)


def _digest(label: str) -> str:
    return content_digest(label.encode("utf-8"))


def _current(
    source_id: str,
    revision: str,
    *,
    source_path: str | None = None,
) -> CurrentSourceSnapshotV1:
    return CurrentSourceSnapshotV1(
        schema_version=1,
        workspace_snapshot_id=_digest("workspace-current"),
        source_id=source_id,
        source_content_id=_digest(source_id + "-" + revision),
        source_path=source_path or f"sources/{source_id}",
    )


def _published(**depths: str) -> PublishedReIndex:
    sources = {
        source_id: PublishedSource(
            source_id=source_id,
            source_path=f"sources/{source_id}",
            published_path=f"re/sources/{source_id}",
            fingerprint=_digest(source_id + "-v1"),
            profile_hash=_digest("profile"),
            status="complete",
            manifest=f"re/sources/{source_id}/manifest.json",
            depth=depth,
        )
        for source_id, depth in depths.items()
    }
    return PublishedReIndex(
        schema_version=1,
        generation=4,
        publication_status="complete",
        published_at="2026-09-11T12:00:00Z",
        published_from_run="re-synthesis",
        sources=sources,
        workspace=PublishedWorkspace(
            manifest="re/workspace/manifest.json",
            overview="re/workspace/overview.md",
            relationships="re/workspace/relationships.md",
            contracts="re/workspace/contracts.md",
        ),
        warnings=(),
    )


@pytest.mark.unit
def test_unchanged_whole_workspace_refresh_is_deterministic_noop() -> None:
    current = (_current("api", "v1"), _current("worker", "v1"))
    published = _published(api="deep", worker="quick")

    first = plan_knowledge_refresh(
        declared_source_ids=("api", "worker"),
        selected_snapshots=current,
        selected_source_ids=None,
        published=published,
        explicit_depth=None,
        workspace_default="standard",
    )
    second = plan_knowledge_refresh(
        declared_source_ids=("worker", "api"),
        selected_snapshots=tuple(reversed(current)),
        selected_source_ids=None,
        published=published,
        explicit_depth=None,
        workspace_default="standard",
    )

    assert first == second
    assert first.identity == second.identity
    assert first.no_op
    assert first.reanalyze_source_ids == ()
    assert first.reusable_source_ids == ("api", "worker")
    assert {row.source_id: row.depth for row in first.sources} == {
        "api": "deep",
        "worker": "quick",
    }


@pytest.mark.unit
def test_changed_source_invalidates_its_knowledge_and_workspace_synthesis() -> None:
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "worker"),
        selected_snapshots=(_current("api", "v2"), _current("worker", "v1")),
        selected_source_ids=None,
        published=_published(api="deep", worker="standard"),
        explicit_depth=None,
        workspace_default="quick",
    )

    assert not plan.no_op
    assert plan.reanalyze_source_ids == ("api",)
    assert plan.reusable_source_ids == ("worker",)
    assert plan.invalidated_source_output_ids == ("api",)
    assert plan.invalidates_workspace_outputs
    assert next(row for row in plan.sources if row.source_id == "api").reason == "source-changed"


@pytest.mark.unit
def test_explicit_depth_change_requires_reanalysis_without_code_change() -> None:
    plan = plan_knowledge_refresh(
        declared_source_ids=("api",),
        selected_snapshots=(_current("api", "v1"),),
        selected_source_ids=None,
        published=_published(api="quick"),
        explicit_depth="deep",
        workspace_default="standard",
    )

    assert plan.reanalyze_source_ids == ("api",)
    assert plan.sources[0].reason == "depth-changed"
    assert plan.sources[0].depth == "deep"


@pytest.mark.unit
def test_source_path_change_requires_reanalysis_without_content_change() -> None:
    plan = plan_knowledge_refresh(
        declared_source_ids=("api",),
        selected_snapshots=(
            _current("api", "v1", source_path="services/api"),
        ),
        selected_source_ids=None,
        published=_published(api="standard"),
        explicit_depth=None,
        workspace_default="standard",
    )

    assert plan.reanalyze_source_ids == ("api",)
    assert plan.sources[0].reason == "source-path-changed"


@pytest.mark.unit
def test_targeted_refresh_does_not_accept_or_claim_unselected_checkout_reads() -> None:
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "worker"),
        selected_snapshots=(_current("api", "v2"),),
        selected_source_ids=("api",),
        published=_published(api="standard", worker="deep"),
        explicit_depth=None,
        workspace_default="standard",
    )

    assert plan.reanalyze_source_ids == ("api",)
    assert plan.not_checked_source_ids == ("worker",)
    assert plan.retained_source_ids == ("worker",)
    worker = next(row for row in plan.sources if row.source_id == "worker")
    assert worker.disposition == "not-checked"
    assert worker.current_content_id is None
    assert worker.depth == "deep"

    with pytest.raises(KnowledgeRefreshError, match="snapshot scope"):
        plan_knowledge_refresh(
            declared_source_ids=("api", "worker"),
            selected_snapshots=(_current("api", "v2"), _current("worker", "v1")),
            selected_source_ids=("api",),
            published=_published(api="standard", worker="deep"),
            explicit_depth=None,
            workspace_default="standard",
        )


@pytest.mark.unit
def test_targeted_refresh_needs_attention_when_unselected_source_has_no_authority() -> None:
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "new"),
        selected_snapshots=(_current("api", "v1"),),
        selected_source_ids=("api",),
        published=_published(api="standard"),
        explicit_depth=None,
        workspace_default="standard",
    )

    assert plan.missing_retained_source_ids == ("new",)
    assert plan.needs_attention
    assert plan.reason_code == "unselected-source-has-no-published-authority"
    assert not plan.no_op


@pytest.mark.unit
def test_added_and_removed_sources_change_the_current_union() -> None:
    old = _published(api="standard", removed="deep")
    plan = plan_knowledge_refresh(
        declared_source_ids=("api", "new"),
        selected_snapshots=(_current("api", "v1"), _current("new", "v1")),
        selected_source_ids=None,
        published=old,
        explicit_depth=None,
        workspace_default="quick",
    )

    assert plan.reanalyze_source_ids == ("new",)
    assert plan.removed_source_ids == ("removed",)
    assert plan.invalidates_workspace_outputs
    assert next(row for row in plan.sources if row.source_id == "new").reason == "new-source"


@pytest.mark.unit
def test_historical_source_without_depth_is_not_reused_as_repaired_authority() -> None:
    historical = _published(api="standard")
    historical = replace(
        historical,
        sources={"api": replace(historical.sources["api"], depth=None)},
    )

    plan = plan_knowledge_refresh(
        declared_source_ids=("api",),
        selected_snapshots=(_current("api", "v1"),),
        selected_source_ids=None,
        published=historical,
        explicit_depth=None,
        workspace_default="standard",
    )

    assert plan.reanalyze_source_ids == ("api",)
    assert plan.sources[0].reason == "missing-depth-authority"
