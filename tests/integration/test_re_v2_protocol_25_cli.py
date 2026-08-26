from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import time

import pytest

from dataclasses import replace

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_24.model import ParentAuthorityBundleV1
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_25.adoption import (
    ParentSemanticAuthorityV1,
    Protocol25ParentCandidateV1,
    validate_protocol_25_parent,
)
from harness.re_v2.protocol_25.inputs import ValidatedProtocol25Inputs
from harness.re_v2.protocol_25.lifecycle import (
    prepare_guided_successor,
    prepare_new_audit_epoch,
)
from harness.re_v2.protocol_25.policies import build_semantic_v1_policy_catalog
from harness.re_v2.protocol_25.policies import (
    SemanticExecutorAuthorityV1,
    build_semantic_executor_catalog,
)
from tests.integration.test_re_v2_protocol_24_controller import _completed_parent
from tests.integration.test_re_v2_protocol_24_cli import _registry
from tests.unit.test_re_v2_protocol_24_prosaic import _role_artifact
from tests.unit.test_re_v2_protocol_25_inputs import _executor_fixture
from tests.unit.test_re_v2_protocol_22_controller import _SnapshotReader


@pytest.mark.integration
def test_new_audit_preparation_layers_schema4_over_authenticated_parent(
    tmp_path: Path,
) -> None:
    parent = _completed_parent(tmp_path / "parent", provider_mode="cli")
    fixture_executor, semantic_objects = _executor_fixture()
    authorities = tuple(
        SemanticExecutorAuthorityV1(
            schema_version=1,
            producer_family=entry.producer_family,
            agent_contract_hash=entry.request_renderer.agent_contract_hash,
            response_schema_kind=entry.request_renderer.response_schemas[0].artifact_kind,
            response_schema_hash=entry.request_renderer.response_schemas[0].schema_hash,
            verifier_id=entry.verifier.verifier_id,
            verifier_implementation_digest=entry.verifier.implementation_digest,
            result_contract_id=entry.result_contract_id,
        )
        for entry in fixture_executor.semantic_entries
        if entry.request_renderer is not None
    )
    deepener = b"authenticated deepener role\n"
    semantic_objects[content_digest(deepener)] = deepener
    l2_executor = build_deepening_executor_catalog(
        parent.inputs.executor_contract,
        content_digest(deepener),
        content_digest(b"protocol-2.4 implementation"),
    )
    executor = build_semantic_executor_catalog(
        l2_executor,
        authorities,
    )
    policy = build_semantic_v1_policy_catalog()
    selection = SelectionScopeV1(1, True, (), ())

    first = prepare_new_audit_epoch(
        parent=parent,
        selection=selection,
        artifact_policy=policy,
        executor_contract=executor,
        semantic_objects=semantic_objects,
        created_at="2026-08-26T12:00:00Z",
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        semantic_token_limit=1_000_000,
        semantic_active_ms_limit=1_800_000,
    )
    changed_authorization = prepare_new_audit_epoch(
        parent=parent,
        selection=selection,
        artifact_policy=policy,
        executor_contract=executor,
        semantic_objects=semantic_objects,
        created_at="2026-08-26T12:00:00Z",
        token_limit=9_000_000,
        active_ms_limit=20_800_000,
        semantic_token_limit=2_000_000,
        semantic_active_ms_limit=2_800_000,
    )

    assert first.manifest.schema_version == 4
    assert first.manifest.engine_protocol_version == "2.5"
    assert first.manifest.run_mode == "new-audit-epoch"
    assert first.manifest.parent_run_id == parent.manifest.run_id
    assert first.inputs.parent_authority_bundle.semantic_authority.is_empty
    assert first.graph.manifest == first.manifest
    assert (
        first.manifest.semantic_request_id
        == changed_authorization.manifest.semantic_request_id
    )
    assert first.manifest.initial_budget_policy.token_limit == 5_000_000
    assert first.manifest.semantic_closure_policy.token_limit == 1_000_000


@pytest.mark.integration
def test_guided_audit_successor_binds_blocked_schema4_parent_and_retains_candidates(
    tmp_path: Path,
) -> None:
    """Catch successors that falsely bind the blocked run's L1/L2 ancestor."""
    parent = _completed_parent(tmp_path / "parent", provider_mode="cli")
    fixture_executor, semantic_objects = _executor_fixture()
    authorities = tuple(
        SemanticExecutorAuthorityV1(
            schema_version=1,
            producer_family=entry.producer_family,
            agent_contract_hash=entry.request_renderer.agent_contract_hash,
            response_schema_kind=entry.request_renderer.response_schemas[0].artifact_kind,
            response_schema_hash=entry.request_renderer.response_schemas[0].schema_hash,
            verifier_id=entry.verifier.verifier_id,
            verifier_implementation_digest=entry.verifier.implementation_digest,
            result_contract_id=entry.result_contract_id,
        )
        for entry in fixture_executor.semantic_entries
        if entry.request_renderer is not None
    )
    deepener = b"authenticated deepener role\n"
    semantic_objects[content_digest(deepener)] = deepener
    executor = build_semantic_executor_catalog(
        build_deepening_executor_catalog(
            parent.inputs.executor_contract,
            content_digest(deepener),
            content_digest(b"protocol-2.4 implementation"),
        ),
        authorities,
    )
    prepared_parent = prepare_new_audit_epoch(
        parent=parent,
        selection=SelectionScopeV1(1, True, (), ()),
        artifact_policy=build_semantic_v1_policy_catalog(),
        executor_contract=executor,
        semantic_objects=semantic_objects,
        created_at="2026-08-26T12:00:00Z",
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        semantic_token_limit=1_000_000,
        semantic_active_ms_limit=1_800_000,
    )
    blocked_manifest = replace(
        prepared_parent.manifest,
        run_id="re-blocked-l3-parent",
        created_at="2026-08-26T12:01:00Z",
    )
    manifest_bytes = canonical_json_bytes(blocked_manifest.to_json_dict())
    event_bytes = b'{"terminal":"blocked_incomplete"}\n'
    ledger_bytes = b'{"ledger":"authenticated"}\n'
    terminal_hash = content_digest(b"blocked terminal event")
    previous_lower = prepared_parent.inputs.parent_authority_bundle.lower_authority_bundle
    current_lower = ParentAuthorityBundleV1(
        schema_version=1,
        direct_parent_run_id=blocked_manifest.run_id,
        source_manifest_hash=content_digest(manifest_bytes),
        source_event_chain_hash=content_digest(event_bytes),
        source_terminal_event_hash=terminal_hash,
        source_ledger_chain_hash=content_digest(ledger_bytes),
        lineage_root_run_id=blocked_manifest.parent_lineage.lineage_root_run_id,
        ancestor_bundle_hashes=previous_lower.ancestor_bundle_hashes,
        artifacts=previous_lower.artifacts,
    )
    target_ids = tuple(
        sorted(item.audit_target_id for item in prepared_parent.graph.audit_target_plans)
    )
    assert len(target_ids) > 1
    candidate_payload = b'{"accepted":"audit sibling"}\n'
    candidate_hash = content_digest(candidate_payload)
    semantic = ParentSemanticAuthorityV1(
        schema_version=1,
        accepted_audit_target_ids=(target_ids[0],),
        accepted_audit_candidate_hashes=(candidate_hash,),
        unresolved_audit_target_ids=target_ids[1:],
        audit_epoch_id=None,
        resolution_overlay_hashes=(),
        target_assessment_hashes=(),
        source_assessment_hashes=(),
        closure_receipt_ids=(),
        closure_root_hash=None,
        unresolved_finding_ids=(),
        deferred_observation_ids=(),
        l3_source_root_hashes=(),
    )
    validated = validate_protocol_25_parent(
        Protocol25ParentCandidateV1(
            schema_version=1,
            parent_layer="L3",
            parent_state="blocked_incomplete",
            source_snapshot_id=blocked_manifest.source_snapshot_id,
            selection_id=blocked_manifest.selection.identity,
            terminal_event_hash=terminal_hash,
            authentication_state="authenticated",
            workspace_state="clean_exact_commits",
            lineage_state="acyclic",
            lower_authority_bundle=current_lower,
            semantic_authority=semantic,
        ),
        mode="audit-successor",
    )
    parent_inputs = ValidatedProtocol25Inputs(
        workspace_partition=prepared_parent.inputs.workspace_partition,
        artifact_policy=prepared_parent.inputs.artifact_policy,
        executor_contract=prepared_parent.inputs.executor_contract,
        audit_policy=prepared_parent.inputs.audit_policy,
        parent_authority_bundle=prepared_parent.inputs.parent_authority_bundle,
        immutable_objects=prepared_parent.inputs.immutable_objects,
        frozen_audit_epoch=None,
        human_guidance=None,
    )
    successor = prepare_guided_successor(
        parent=validated,
        parent_manifest=blocked_manifest,
        parent_inputs=parent_inputs,
        accepted_parent=parent.accepted_parent,
        parent_objects={
            **dict(prepared_parent.inputs.immutable_objects),
            current_lower.source_manifest_hash: manifest_bytes,
            current_lower.source_event_chain_hash: event_bytes,
            current_lower.source_ledger_chain_hash: ledger_bytes,
            candidate_hash: candidate_payload,
        },
        answer="  Retry only the missing audit targets.\r\n",
        created_at="2026-08-26T12:02:00Z",
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        semantic_token_limit=1_000_000,
        semantic_active_ms_limit=1_800_000,
    )

    assert successor.manifest.run_mode == "audit-successor"
    assert successor.manifest.parent_run_id == "re-blocked-l3-parent"
    assert successor.manifest.parent_lineage.lineage_root_run_id == (
        blocked_manifest.parent_lineage.lineage_root_run_id
    )
    assert successor.inputs.parent_authority_bundle.semantic_authority == semantic
    assert successor.inputs.human_guidance is not None
    assert b'"answer":"Retry only the missing audit targets."' in (
        successor.inputs.human_guidance
    )
    assert successor.graph.manifest == successor.manifest


@pytest.mark.integration
def test_l3_deepen_creates_and_exactly_reuses_one_schema4_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
    from harness.re_v2.protocol_25.inputs import load_protocol_25_inputs
    from harness.re_v2.protocol_25.model import RunManifestV4
    from harness.re_v2.run_store import ReV2Paths, load_run_manifest

    parent = _completed_parent(tmp_path / "authority", provider_mode="cli")
    workspace = tmp_path / "workspace"
    (workspace / "runs").mkdir(parents=True)
    monkeypatch.setattr(
        "harness.re_v2.protocol_24.adoption.validate_parent_for_deepening",
        lambda _run, _workspace: parent,
    )
    monkeypatch.setattr(
        legacy_cli,
        "ProsaicPromptLoader",
        lambda _workspace: SimpleNamespace(
            load_subagent=lambda _agent_id: _role_artifact()
        ),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_schema2_installed_registry",
        lambda agent, *, provider_mode: (_registry(parent), agent, {}),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_re_v22_implementation_digest",
        lambda *_modules: content_digest(b"installed implementation"),
    )
    live: list[Path] = []
    monkeypatch.setattr(
        legacy_cli,
        "_re_v2_context",
        lambda _workspace, run_dir: SimpleNamespace(run_dir=run_dir),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_run_re_v2_live",
        lambda context: live.append(context.run_dir),
    )
    options = legacy_cli._parse_re_deepen_options(
        ["--to", "L3", "--all", "--from-run", "re-parent"]
    )

    first = legacy_cli._run_re_v25_deepen(workspace, options)
    second = legacy_cli._run_re_v25_deepen(workspace, options)

    assert first == second
    manifest = load_run_manifest(first)
    assert isinstance(manifest, RunManifestV4)
    assert manifest.run_mode == "new-audit-epoch"
    assert live == [first]
    events = EventStore(
        ReV2Paths.for_run(first),
        protocol=PROTOCOL_25_EVENTS,
    ).replay()
    assert events[0].type == "run_created"
    assert sum(event.type == "artifact_adopted" for event in events) == len(
        parent.ledger.accepted_artifacts
    )
    assert (workspace / "runs" / ".current-re").read_text() == first.name + "\n"

    loaded_inputs = load_protocol_25_inputs(ReV2Paths.for_run(first), manifest)
    payloads = {
        (source.source_id, record.source_relative_path): b"print('ok')\n"
        for source in loaded_inputs.workspace_partition.sources
        for record in source.files
    }
    reader = _SnapshotReader(loaded_inputs.workspace_partition, payloads)
    monkeypatch.setattr(legacy_cli, "_load_re_v2_snapshot", lambda *_args: object())
    monkeypatch.setattr(
        "harness.re_v2.protocol_22.evidence.PinnedSnapshotReaderV1",
        lambda _snapshot, _partition: reader,
    )
    monkeypatch.setattr(
        "harness.re_v2.snapshot.validate_source_snapshot",
        lambda _snapshot: None,
    )
    rebuilt = legacy_cli._re_v25_context(workspace, first, manifest)

    assert rebuilt.semantic_graph.manifest == manifest
    assert rebuilt.event_store.protocol is PROTOCOL_25_EVENTS
    assert tuple(rebuilt.executors) == ("shared-ai-cli-baseline-v1",)

    rebuilt.event_store.append(
        "run_paused",
        {
            "reason": "semantic resource authorization required",
            "reason_code": "budget_authorization_required",
        },
        occurred_at=manifest.created_at,
    )
    continued: list[object] = []
    monkeypatch.setattr(legacy_cli, "_run_re_v2_live", continued.append)
    legacy_cli._run_re_v25_continue(
        rebuilt,
        token_limit=6_000_000,
        time_limit_minutes=200,
        semantic_token_limit=2_000_000,
        semantic_time_limit_minutes=40,
    )
    continuation_events = rebuilt.event_store.replay()

    assert [
        event.type
        for event in continuation_events[-5:]
    ] == [
        "budget_authorized",
        "budget_authorized",
        "semantic_budget_authorized",
        "semantic_budget_authorized",
        "run_resumed",
    ]
    assert continued == [rebuilt]


@pytest.mark.integration
def test_schema4_context_dispatches_to_protocol25_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from harness.re_v2.protocol_25.inputs import create_protocol_25_run_store
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture

    inputs, manifest = _fixture()
    run_dir = tmp_path / manifest.run_id
    create_protocol_25_run_store(run_dir, manifest, inputs)
    marker = object()
    calls: list[tuple[Path, Path, object]] = []

    def build(project_root: Path, received: Path, authoritative: object) -> object:
        calls.append((project_root, received, authoritative))
        return marker

    monkeypatch.setattr(legacy_cli, "_re_v25_context", build, raising=False)

    assert legacy_cli._re_v2_context(tmp_path, run_dir) is marker
    assert calls == [(tmp_path, run_dir, manifest)]


@pytest.mark.integration
def test_schema4_live_execution_uses_protocol25_controller(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from echelon import cli as legacy_cli
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture

    calls: list[object] = []

    class ContextMarker:
        paths = SimpleNamespace(root=Path("/tmp/run/v2"))

    context = ContextMarker()
    _inputs, manifest = _fixture()

    class Controller:
        def __init__(self, received: object) -> None:
            calls.append(received)

        def run_until_stopped(self) -> object:
            return SimpleNamespace(status="paused")

    monkeypatch.setattr(
        "harness.re_v2.protocol_22.recovery.Protocol22RunContext",
        ContextMarker,
    )
    monkeypatch.setattr(
        "harness.re_v2.run_store.load_run_manifest",
        lambda _run_dir: manifest,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.controller.Protocol25Controller",
        Controller,
    )

    legacy_cli._run_re_v2_live(context)

    assert calls == [context]
    assert "PROTOCOL 2.5" in capsys.readouterr().out


@pytest.mark.integration
def test_concurrent_identical_resume_creates_one_child_and_one_paid_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch exact resume checking outside the workspace creation lock."""
    from echelon import cli as legacy_cli
    from tests.unit.test_re_v2_protocol_25_inputs import _fixture

    workspace = tmp_path / "workspace"
    parent_run = workspace / "runs" / "re-blocked-parent"
    parent_run.mkdir(parents=True)
    inputs, manifest = _fixture(mode="audit-successor")
    manifest = replace(manifest, run_id="re-concurrent-successor")
    prepared = SimpleNamespace(manifest=manifest, inputs=inputs)
    exported = SimpleNamespace(
        parent=object(),
        manifest=manifest,
        inputs=inputs,
        accepted_parent={},
        immutable_objects=inputs.immutable_objects,
    )
    created: list[Path] = []
    initialized: list[Path] = []
    paid: list[Path] = []

    monkeypatch.setattr(
        legacy_cli,
        "_re_v2_context",
        lambda _workspace, run_dir: SimpleNamespace(run_dir=run_dir),
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.lifecycle.export_protocol_25_parent",
        lambda _context: exported,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.lifecycle.prepare_guided_successor",
        lambda **_kwargs: prepared,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.lifecycle.find_exact_protocol_25_child",
        lambda _workspace, _request: (created[0] if created else None),
    )

    def create(run_dir: Path, _manifest: object, _inputs: object) -> None:
        run_dir.mkdir(parents=True)
        time.sleep(0.05)
        created.append(run_dir)

    monkeypatch.setattr(
        "harness.re_v2.protocol_25.inputs.create_protocol_25_run_store",
        create,
    )
    monkeypatch.setattr(
        "harness.re_v2.protocol_25.lifecycle.initialize_protocol_25_successor",
        lambda run_dir, _exported: initialized.append(run_dir),
    )
    monkeypatch.setattr(
        legacy_cli,
        "_new_re_v2_run_id",
        lambda _workspace: "re-concurrent-successor",
    )
    monkeypatch.setattr(
        legacy_cli,
        "_run_re_v2_live",
        lambda context: paid.append(context.run_dir),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(
            pool.map(
                lambda _index: legacy_cli._run_re_v25_resume(
                    workspace,
                    parent_run,
                    "Use retained evidence only.",
                    None,
                    None,
                ),
                range(2),
            )
        )

    expected = workspace / "runs" / "re-concurrent-successor"
    assert results == (expected, expected)
    assert created == [expected]
    assert initialized == [expected, expected]
    assert paid == [expected]
    assert (workspace / "runs" / ".current-re").read_text() == (
        "re-concurrent-successor\n"
    )
