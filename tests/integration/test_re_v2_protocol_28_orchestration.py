from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import pytest

from harness.re_v2.protocol_25.controller import plan_next_protocol_25
from harness.re_v2.protocol_25.recovery import recover_protocol_25_run
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.orchestration import resolve_l4_parent
from harness.re_v2.protocol_28.authority import (
    ValidatedL3ParentV1,
    ValidatedL3TargetV1,
)
from harness.re_v2.protocol_28.orchestration import (
    DeepenOrchestrationRequestV1,
    Protocol28OrchestrationOptions,
    ResolvedL4ParentV1,
    execute_deepen_orchestration,
)
from tests.integration.test_re_v2_protocol_25_recovery import (
    _accept_every_audit,
    _accept_every_prerequisite,
    _context,
)
from tests.re_v2_protocol_27_fixtures import manifest_v6
from tests.re_v2_protocol_24_fixtures import manifest_v3
from tests.unit.test_re_v2_protocol_28_inputs import _fixture as _l4_fixture
from tests.unit.test_re_v2_protocol_28_lifecycle import _PassingBackend


@pytest.mark.integration
def test_direct_terminal_l3_resolves_to_exact_selected_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    context = _context(workspace / "runs")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context)
    for expected_kind in ("freeze_epoch", "accept_roots", "terminal_complete"):
        action = plan_next_protocol_25(
            recover_protocol_25_run(context).controller_state
        )
        assert action is not None and action.kind == expected_kind
        context.apply_controller_action(action)

    import echelon.cli as cli

    monkeypatch.setattr(cli, "_re_v2_context", lambda *_args: context)
    resolved = resolve_l4_parent(
        workspace,
        context.semantic_graph.manifest.run_id,
        context.semantic_graph.manifest.selection,
    )

    assert resolved.prerequisite_required is False
    assert resolved.selected_l3 is not None
    assert resolved.selected_l3.terminal_state == "complete"
    assert resolved.selected_l3.manifest_hash in resolved.authority_objects
    assert resolved.selected_l3.terminal_event_hash in resolved.authority_objects
    assert resolved.selected_l3.frozen_epoch_id in resolved.authority_objects


@pytest.mark.integration
def test_unfinished_l3_is_not_silently_bypassed_to_l2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    context = _context(workspace / "runs")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    import echelon.cli as cli

    monkeypatch.setattr(cli, "_re_v2_context", lambda *_args: context)

    with pytest.raises(Exception, match="terminal-ineligible"):
        resolve_l4_parent(
            workspace,
            context.semantic_graph.manifest.run_id,
            context.semantic_graph.manifest.selection,
        )


@pytest.mark.integration
def test_l2_parent_reports_automatic_l3_prerequisite(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    manifest = manifest_v3(run_id="re-l2-parent")
    run_dir = workspace / "runs" / manifest.run_id
    (run_dir / "v2").mkdir(parents=True)
    (run_dir / "v2" / "run.json").write_bytes(
        canonical_json_bytes(manifest.to_json_dict())
    )

    resolved = resolve_l4_parent(workspace, manifest.run_id, manifest.selection)

    assert resolved.prerequisite_required is True
    assert resolved.selected_l3 is None
    assert resolved.analysis_run_dir == run_dir


@pytest.mark.integration
def test_synthesis_lineage_ignores_unselected_partial_but_rejects_selected_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    context = _context(workspace / "runs")
    context.event_store.append(
        "run_created",
        {"run_manifest_id": context.semantic_graph.manifest.run_manifest_id},
        occurred_at=context.semantic_graph.manifest.created_at,
    )
    _accept_every_prerequisite(context)
    _accept_every_audit(context)
    for _ in range(3):
        action = plan_next_protocol_25(
            recover_protocol_25_run(context).controller_state
        )
        assert action is not None
        context.apply_controller_action(action)

    parent_bytes = canonical_json_bytes(context.semantic_graph.manifest.to_json_dict())
    synthesis = manifest_v6(run_id="re-synthesis-lineage")
    acceptances = tuple(
        replace(
            item,
            parent_run_id=context.semantic_graph.manifest.run_id,
            parent_manifest_hash=content_digest(parent_bytes),
        )
        for item in synthesis.partial_acceptances
    )
    synthesis = replace(
        synthesis,
        parent_run_id=context.semantic_graph.manifest.run_id,
        parent_manifest_hash=content_digest(parent_bytes),
        partial_acceptances=acceptances,
    )
    synthesis_dir = workspace / "runs" / synthesis.run_id
    (synthesis_dir / "v2").mkdir(parents=True)
    (synthesis_dir / "v2" / "run.json").write_bytes(
        canonical_json_bytes(synthesis.to_json_dict())
    )
    import echelon.cli as cli

    monkeypatch.setattr(cli, "_re_v2_context", lambda *_args: context)
    api = SelectionScopeV1(1, False, ("api",), ())
    web = SelectionScopeV1(1, False, ("web",), ())

    assert resolve_l4_parent(workspace, synthesis.run_id, api).selected_l3 is not None
    with pytest.raises(Exception, match="next explicit L3 audit epoch"):
        resolve_l4_parent(workspace, synthesis.run_id, web)


@pytest.mark.integration
def test_durable_orchestration_completes_exact_l4_and_replays_zero_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, inputs = _l4_fixture("re-l4-orchestrated")
    projection = inputs.l3_projection_catalog.projections[0]
    membership = inputs.l3_projection_catalog.memberships[0]
    l3 = ValidatedL3ParentV1(
        1,
        manifest.lineage.direct_parent_run_id,
        manifest.lineage.direct_parent_manifest_hash,
        manifest.lineage.direct_parent_terminal_event_hash,
        manifest.source_snapshot_id,
        manifest.partition_manifest_id,
        manifest.selection.identity,
        inputs.parent_authority_bundle.frozen_epoch_id,
        "complete",
        (),
        manifest.workspace_partition_catalog_id,
        manifest.inherited_artifact_policy_catalog_id,
        inputs.parent_authority_bundle.lower_l0_l2_authority_ids,
        (
            ValidatedL3TargetV1(
                **projection.to_json_dict(),
                frozen_epoch_id=inputs.parent_authority_bundle.frozen_epoch_id,
                epoch_target_entry_hash=membership.epoch_target_entry_hash,
            ),
        ),
    )
    resolved = ResolvedL4ParentV1(
        tmp_path / "input",
        tmp_path / "analysis",
        l3,
        inputs.authority_objects,
        False,
    )
    import harness.re_v2.protocol_28.orchestration as orchestration

    monkeypatch.setattr(orchestration, "resolve_l4_parent", lambda *_args: resolved)
    request = DeepenOrchestrationRequestV1(
        1,
        "re-input",
        content_digest(b"input-manifest"),
        content_digest(b"input-terminal"),
        manifest.source_snapshot_id,
        manifest.partition_manifest_id,
        manifest.selection,
        manifest.exhaustive_policy_catalog_id,
        manifest.executor_catalog_id,
        content_digest(b"l3-prerequisite-request"),
    )
    options = Protocol28OrchestrationOptions(
        from_run="re-input",
        selection=manifest.selection,
        request=request,
        l4_inputs_factory=lambda *_args: inputs,
        clock=lambda: "2026-08-31T12:00:00Z",
    )
    backend = _PassingBackend()

    first = execute_deepen_orchestration(tmp_path, options, lambda: backend)
    second = execute_deepen_orchestration(tmp_path, options, lambda: backend)

    assert first.state == second.state == "complete"
    assert first.l4_run_id == manifest.run_id
    assert backend.roles == ["producer", "verifier"]
