from __future__ import annotations

from contextlib import contextmanager
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
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.events import replay_protocol_28
from harness.re_v2.protocol_28.orchestration import (
    DeepenOrchestrationController,
    DeepenOrchestrationRequestV1,
    Protocol28OrchestrationOptions,
    ResolvedL4ParentV1,
    create_or_load_orchestration,
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
    recovered = recover_protocol_25_run(context)
    epoch = recovered.ledger.audit_epochs[resolved.selected_l3.frozen_epoch_id]
    for target in resolved.selected_l3.targets:
        assert target.audit_policy_id in resolved.authority_objects
        assert target.executor_policy_id in resolved.authority_objects
        assert target.relevant_l2_root_ids == epoch.audited_l2_root_hashes
        assert all(
            root_id in resolved.authority_objects
            for root_id in target.relevant_l2_root_ids
        )


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
def test_resource_paused_l3_reports_distinct_prerequisite_state(
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
    context.event_store.append(
        "run_paused",
        {"reason": "resource ceiling reached", "reason_code": "tokens_exhausted"},
        occurred_at="2026-08-31T12:00:01Z",
    )
    import echelon.cli as cli

    monkeypatch.setattr(cli, "_re_v2_context", lambda *_args: context)

    with pytest.raises(Exception, match="terminal-ineligible: paused_resource"):
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
    progress_events: list[tuple[str, Path]] = []

    @contextmanager
    def l4_progress(run_dir: Path):
        progress_events.append(("entered", run_dir))
        yield
        progress_events.append(("exited", run_dir))

    options = Protocol28OrchestrationOptions(
        from_run="re-input",
        selection=manifest.selection,
        request=request,
        l4_inputs_factory=lambda *_args: inputs,
        l4_progress_factory=l4_progress,
        clock=lambda: "2026-08-31T12:00:00Z",
    )
    backend = _PassingBackend()

    first = execute_deepen_orchestration(tmp_path, options, lambda: backend)
    second = execute_deepen_orchestration(tmp_path, options, lambda: backend)

    assert first.state == second.state == "complete"
    assert first.l4_run_id == manifest.run_id
    assert backend.roles == ["producer", "verifier"]
    assert progress_events == [
        ("entered", tmp_path / "runs" / manifest.run_id),
        ("exited", tmp_path / "runs" / manifest.run_id),
        ("entered", tmp_path / "runs" / manifest.run_id),
        ("exited", tmp_path / "runs" / manifest.run_id),
    ]
    l4_context = load_protocol_28_run_context(
        tmp_path / "runs" / manifest.run_id
    )
    assert replay_protocol_28(l4_context.events.replay()).lifecycle_state == "complete"
    assert (tmp_path / "runs" / manifest.run_id / "re" / "l4" / "materialization.json").is_file()


@pytest.mark.integration
def test_l3_status_retains_true_header_and_links_pending_l4_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness.re_v2.status import render_v2_status
    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture as _l3_fixture
    import harness.re_v2.protocol_25.status as l3_status

    workspace = tmp_path / "workspace"
    l3_inputs, l3_manifest = _l3_fixture()
    run_dir = workspace / "runs" / l3_manifest.run_id
    create_protocol_25_run_store(run_dir, l3_manifest, l3_inputs)
    monkeypatch.setattr(
        l3_status,
        "render_protocol_25_status",
        lambda *_args, **_kwargs: (
            "RE V2 — PROTOCOL 2.5\n"
            + "=" * 72
            + "\nL3 SELECTED SCOPE IN PROGRESS\n"
        ),
    )
    manifest = l3_manifest
    request = DeepenOrchestrationRequestV1(
        1,
        "re-input",
        content_digest(b"input-manifest"),
        content_digest(b"input-terminal"),
        manifest.source_snapshot_id,
        manifest.partition_manifest_id,
        manifest.selection,
        content_digest(b"l4-policy"),
        content_digest(b"l4-executors"),
        content_digest(b"l3-request"),
    )
    intent = create_or_load_orchestration(
        workspace,
        request,
        clock=lambda: "2026-08-31T12:00:00Z",
    )
    DeepenOrchestrationController(
        intent, clock=lambda: "2026-08-31T12:00:00Z"
    ).bind_l3_child(manifest.run_id, content_digest(b"l3-manifest"))

    output = render_v2_status(run_dir)

    assert output.startswith("RE V2 — PROTOCOL 2.5\n")
    assert f"pending L4 orchestration: {request.request_id}" in output
    assert output.rstrip().endswith("L3 SELECTED SCOPE IN PROGRESS")


@pytest.mark.integration
def test_l3_status_lists_every_open_l4_intent_without_ambiguity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    from harness.re_v2.status import render_v2_status
    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture as _l3_fixture
    import harness.re_v2.protocol_25.status as l3_status

    workspace = tmp_path / "workspace"
    l3_inputs, manifest = _l3_fixture()
    run_dir = workspace / "runs" / manifest.run_id
    create_protocol_25_run_store(run_dir, manifest, l3_inputs)
    monkeypatch.setattr(
        l3_status,
        "render_protocol_25_status",
        lambda *_args, **kwargs: (
            "{}\n"
            if kwargs.get("as_json")
            else "RE V2 — PROTOCOL 2.5\n" + "=" * 72 + "\n"
        ),
    )
    requests = tuple(
        DeepenOrchestrationRequestV1(
            1,
            "re-input",
            content_digest(b"input-manifest"),
            content_digest(b"input-terminal"),
            manifest.source_snapshot_id,
            manifest.partition_manifest_id,
            replace(manifest.selection, source_ids=(source_id,)),
            content_digest(f"l4-policy-{source_id}".encode()),
            content_digest(b"l4-executors"),
            content_digest(b"l3-request"),
        )
        for source_id in ("api", "worker")
    )
    for request in requests:
        intent = create_or_load_orchestration(
            workspace,
            request,
            clock=lambda: "2026-08-31T12:00:00Z",
        )
        DeepenOrchestrationController(
            intent, clock=lambda: "2026-08-31T12:00:00Z"
        ).bind_l3_child(manifest.run_id, content_digest(b"l3-manifest"))

    output = render_v2_status(run_dir)

    assert "pending L4 orchestrations: 2 open" in output
    assert all(request.request_id in output for request in requests)
    document = json.loads(render_v2_status(run_dir, as_json=True))
    assert [item["request_id"] for item in document["pending_l4_orchestrations"]] == [
        request.request_id for request in sorted(requests, key=lambda item: item.request_id)
    ]
