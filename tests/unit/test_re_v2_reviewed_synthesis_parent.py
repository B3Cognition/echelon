"""Authenticated protocol-2.8 reviewed knowledge can feed workspace synthesis."""

from __future__ import annotations

import stat

import pytest

from harness.re_v2.protocol_28.lifecycle import run_protocol_28_exhaustive
from tests.unit.test_re_v2_protocol_28_reconciliation import (
    KnowledgeBackend,
    reconciliation_fixture,
)


@pytest.mark.unit
def test_terminal_reviewed_run_freezes_exact_source_knowledge_for_synthesis(
    tmp_path,
) -> None:
    from harness.re_v2.reviewed_synthesis_parent import (
        resolve_reviewed_synthesis_parent,
    )

    context, *_ = reconciliation_fixture(tmp_path / "runs")
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert result.state == "complete"

    parent = resolve_reviewed_synthesis_parent(tmp_path, context.run_dir.name)

    assert parent.parent_run_id == context.run_dir.name
    assert parent.source_snapshot_id == context.inputs.manifest.source_snapshot_id
    assert parent.partition_manifest_id == context.inputs.manifest.partition_manifest_id
    assert parent.selected_layers == {"api": "reviewed"}
    assert [item.source_id for item in parent.accepted_sources] == ["api"]
    assert [item.outcome for item in parent.accepted_sources] == ["complete"]
    assert parent.debt_summary_hashes == {}

    catalog = parent._overview_catalog
    assert catalog is not None
    assert [item.source_id for item in catalog.projections] == ["api"]
    projection = catalog.projections[0]
    assert projection.selected_layer == "reviewed"
    assert parent._overview_payloads[projection.object_hash] == (
        b"Supported reconciled knowledge."
    )
    assert projection.source_root_hash == parent.accepted_sources[0].source_root_hash
    assert set(parent.accepted_sources[0].lower_authority_ids).issubset(
        parent.authority_objects
    )


@pytest.mark.unit
def test_incomplete_reviewed_run_is_not_synthesis_authority(tmp_path) -> None:
    from harness.re_v2.reviewed_synthesis_parent import (
        ReviewedSynthesisParentError,
        resolve_reviewed_synthesis_parent,
    )

    context, *_ = reconciliation_fixture(tmp_path / "runs")

    with pytest.raises(ReviewedSynthesisParentError, match="terminal reviewed"):
        resolve_reviewed_synthesis_parent(tmp_path, context.run_dir.name)


@pytest.mark.unit
def test_tampered_reviewed_candidate_cannot_become_synthesis_authority(
    tmp_path,
) -> None:
    from harness.re_v2.protocol_28.events import replay_protocol_28
    from harness.re_v2.reviewed_synthesis_parent import (
        ReviewedSynthesisParentError,
        resolve_reviewed_synthesis_parent,
    )

    context, *_ = reconciliation_fixture(tmp_path / "runs")
    assert run_protocol_28_exhaustive(
        context.run_dir, lambda: KnowledgeBackend()
    ).state == "complete"
    state = replay_protocol_28(context.events.replay())
    view = context.ledger.replay()
    run_root = view.knowledge_run_roots[state.run_root_id]
    source_root = view.knowledge_roots[run_root.source_root_ids[0]]
    candidate_id = source_root.candidate_id.removeprefix("sha256:")
    candidate_path = (
        context.objects.root / "sha256" / candidate_id[:2] / candidate_id[2:]
    )
    candidate_path.chmod(candidate_path.stat().st_mode | stat.S_IWUSR)
    candidate_path.write_bytes(b'{"tampered":true}')

    with pytest.raises(ReviewedSynthesisParentError, match="authenticate"):
        resolve_reviewed_synthesis_parent(tmp_path, context.run_dir.name)


@pytest.mark.unit
def test_reviewed_source_debt_remains_partial_synthesis_authority(tmp_path) -> None:
    from harness.re_v2.reviewed_synthesis_parent import (
        ReviewedSourceDebtSummaryV1,
        resolve_reviewed_synthesis_parent,
    )
    from tests.unit.test_re_v2_protocol_28_preparation import _accepted_debt_fixture

    inherited = _accepted_debt_fixture(tmp_path / "parent")
    context, *_ = reconciliation_fixture(
        tmp_path / "runs",
        prepared=inherited[:4],
    )
    result = run_protocol_28_exhaustive(context.run_dir, lambda: KnowledgeBackend())
    assert result.state == "complete-with-limitations"

    parent = resolve_reviewed_synthesis_parent(tmp_path, context.run_dir.name)

    (source,) = parent.accepted_sources
    assert source.outcome == "partial"
    assert source.debt_manifest_hash == parent.debt_summary_hashes[source.source_id]
    summary = ReviewedSourceDebtSummaryV1.from_json_dict(
        __import__("json").loads(parent.authority_objects[source.debt_manifest_hash])
    )
    view = context.ledger.replay()
    source_root = next(
        root for root in view.knowledge_roots.values() if root.scope == "source"
    )
    assert summary.debt_acceptance_ids == source_root.debt_acceptance_ids
    assert summary.debt_ids == source_root.debt_ids
