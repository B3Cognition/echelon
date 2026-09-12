from __future__ import annotations

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


@pytest.mark.unit
def test_snapshot_bootstrap_projects_exact_partition_targets(tmp_path):
    from harness.re_v2.knowledge_bootstrap import build_snapshot_bootstrap

    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
    )

    result = build_snapshot_bootstrap(
        "re-fresh-analysis",
        snapshot,
        partition,
        SelectionScopeV1(1, True, (), ()),
    )

    source = partition.sources[0]
    expected = {
        ("source", source.source_id, source.source_content_id),
        *{
            ("domain", domain.domain_key, domain.domain_content_id)
            for domain in source.domains
        },
    }
    assert {
        (target.target_kind, target.target_id, target.target_content_id)
        for target in result.parent.targets
    } == expected
    assert result.parent.source_snapshot_id == snapshot.snapshot_id
    assert result.parent.workspace_partition_catalog_id == partition.identity
    assert result.parent.selection_id == result.selection.identity
    assert result.parent.terminal_state == "complete"
    assert all(not target.finding_ids for target in result.parent.targets)
    assert all(
        content_digest(payload) == object_id
        for object_id, payload in result.authority_objects.items()
    )
    assert result.bootstrap_authority_id in result.authority_objects
    assert result.partition_manifest_id in result.authority_objects


@pytest.mark.unit
def test_snapshot_bootstrap_scopes_sources_without_relabeling_snapshot(tmp_path):
    from harness.re_v2.knowledge_bootstrap import build_snapshot_bootstrap

    snapshot, partition = _fixture(
        tmp_path,
        {"README.md": "API service\n", "src/app.py": "run()\n"},
    )
    selection = SelectionScopeV1(1, False, (partition.sources[0].source_id,), ())

    result = build_snapshot_bootstrap(
        "re-selected-analysis", snapshot, partition, selection
    )

    assert result.selection == selection
    assert {target.source_id for target in result.parent.targets} == set(
        selection.source_ids
    )
    assert result.parent.source_snapshot_id == snapshot.snapshot_id


@pytest.mark.unit
def test_snapshot_bootstrap_rejects_cross_snapshot_and_unknown_selection(tmp_path):
    from harness.re_v2.knowledge_bootstrap import (
        KnowledgeBootstrapError,
        build_snapshot_bootstrap,
    )

    snapshot, partition = _fixture(
        tmp_path / "first", {"README.md": "first\n", "src/app.py": "run()\n"}
    )
    other_snapshot, _ = _fixture(
        tmp_path / "second", {"README.md": "second\n", "src/app.py": "run()\n"}
    )

    with pytest.raises(KnowledgeBootstrapError, match="snapshot-partition-mismatch"):
        build_snapshot_bootstrap(
            "re-cross-snapshot",
            other_snapshot,
            partition,
            SelectionScopeV1(1, True, (), ()),
        )
    with pytest.raises(KnowledgeBootstrapError, match="selection-source-mismatch"):
        build_snapshot_bootstrap(
            "re-unknown-source",
            snapshot,
            partition,
            SelectionScopeV1(1, False, ("unknown",), ()),
        )


@pytest.mark.unit
def test_snapshot_bootstrap_authority_changes_with_target_content(tmp_path):
    from harness.re_v2.knowledge_bootstrap import build_snapshot_bootstrap

    first_snapshot, first_partition = _fixture(
        tmp_path / "first",
        {"README.md": "API service\n", "src/app.py": "run()\n"},
    )
    second_snapshot, second_partition = _fixture(
        tmp_path / "second",
        {"README.md": "API service\n", "src/app.py": "run(2)\n"},
    )
    selection = SelectionScopeV1(1, True, (), ())
    first = build_snapshot_bootstrap(
        "re-content-bound", first_snapshot, first_partition, selection
    )
    second = build_snapshot_bootstrap(
        "re-content-bound", second_snapshot, second_partition, selection
    )

    assert first.bootstrap_authority_id != second.bootstrap_authority_id
    assert {
        target.candidate_authority_hash for target in first.parent.targets
    } != {
        target.candidate_authority_hash for target in second.parent.targets
    }
