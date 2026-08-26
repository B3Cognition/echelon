from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_24.artifacts import build_deepening_executor_catalog
from harness.re_v2.protocol_25.lifecycle import prepare_new_audit_epoch
from harness.re_v2.protocol_25.policies import build_semantic_v1_policy_catalog
from harness.re_v2.protocol_25.policies import (
    SemanticExecutorAuthorityV1,
    build_semantic_executor_catalog,
)
from tests.integration.test_re_v2_protocol_24_controller import _completed_parent
from tests.integration.test_re_v2_protocol_24_cli import _registry
from tests.unit.test_re_v2_protocol_24_prosaic import _role_artifact
from tests.unit.test_re_v2_protocol_25_inputs import _executor_fixture


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
def test_l3_deepen_creates_and_exactly_reuses_one_schema4_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echelon import cli as legacy_cli
    from harness.re_v2.events import EventStore
    from harness.re_v2.protocol_25.events import PROTOCOL_25_EVENTS
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
