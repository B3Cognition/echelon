from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.cli_provider import (
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.execution import ProviderExecutionDependenciesV1
from harness.re_v2.protocol_22.model import ExecutionInputV1, WorkItemV2
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_25.cli_provider import (
    Protocol25ExecutionStore,
    SquadCliSemanticRenderer,
)
from harness.re_v2.run_store import ReV2Paths
from tests.re_v2_protocol_22_fixtures import digest
from tests.re_v2_protocol_25_fixtures import audit_target_v1, l3_artifact_key_v2
from tests.unit.test_re_v2_protocol_22_cli_provider import _ProviderSpy, _result
from tests.unit.test_re_v2_protocol_25_inputs import _executor_fixture
from tests.unit.test_re_v2_protocol_25_runtime import _context


@pytest.mark.unit
def test_semantic_renderer_reuses_shared_provider_without_baseline_filename(
    tmp_path: Path,
) -> None:
    catalog, objects = _executor_fixture()
    executor = catalog.entry_for("semantic-audit")
    renderer = executor.request_renderer
    assert renderer is not None
    frontmatter = {
        "name": "echelon.re-validator",
        "execution": "agent",
        "tools": "write",
        "model_tier": "strong",
        "effort": "high",
        "description": "Semantic audit and closure validator",
    }
    agent_bytes = canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            body="Write exactly `audit.json` for the supplied target.\n",
            frontmatter=frontmatter,
        )
    )
    schema_bytes = objects[renderer.response_schemas[0].schema_hash]
    context_bytes = canonical_json_bytes(
        {
            "schema_version": 1,
            "mode": "AUDIT_EPOCH_TARGET",
            "audit_target_id": digest("audit target"),
        }
    )
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id="semantic-dispatch-1",
        work_item_id=digest("semantic work"),
        attempt_kind="initial_generation",
        executor_contract_hash=executor.executor_contract_hash,
        agent_contract_hash=content_digest(agent_bytes),
        context_bundle_hash=content_digest(context_bytes),
        provider_request_envelope_hash=digest("unused API envelope"),
        deterministic_invocation=None,
    )
    reservation = calculate_shared_cli_dispatch_reservation(
        agent_bytes,
        context_bytes,
        schema_bytes,
        executor,
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    provider = _ProviderSpy(_result())
    runtime = SquadCliSemanticRenderer(
        (executor,),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    )

    result = runtime.execute(
        execution_input,
        agent_bytes,
        context_bytes,
        schema_bytes,
        reservation,
        candidate_root,
        10**12,
    )

    assert result.outcome == "candidate_ready"
    assert len(provider.calls) == 1
    prompt = str(provider.calls[0]["prompt"])
    assert "candidate file required by the role contract" in prompt
    assert "baseline.json" not in prompt
    assert provider.calls[0]["prompt_metadata"] == frontmatter
    assert provider.calls[0]["isolated_workspace"] is True


@pytest.mark.unit
def test_semantic_execution_store_prepares_and_revalidates_l3_cli_authority(
    tmp_path: Path,
) -> None:
    catalog, objects = _executor_fixture()
    executor = catalog.entry_for("semantic-audit")
    renderer = executor.request_renderer
    assert renderer is not None
    agent_bytes = canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            body="Write exactly `audit.json` for the supplied target.\n",
            frontmatter={
                "name": "echelon.re-validator",
                "model_tier": "strong",
                "effort": "high",
                "tools": "write",
            },
        )
    )
    executor = replace(
        executor,
        request_renderer=replace(
            renderer,
            agent_contract_hash=content_digest(agent_bytes),
        ),
    )
    renderer = executor.request_renderer
    assert renderer is not None
    schema_bytes = objects[renderer.response_schemas[0].schema_hash]
    semantic_context = replace(
        _context(),
        response_schema_hash=content_digest(schema_bytes),
    )
    context_bytes = canonical_json_bytes(semantic_context.to_json_dict())
    target = audit_target_v1()
    key = l3_artifact_key_v2(
        "semantic-audit-findings",
        dependency_hashes=(target.identity,),
    )
    item = WorkItemV2(
        identity_schema_version=2,
        template_id=digest("semantic audit template"),
        goal_id="semantic-audit-closure",
        output_key=key,
        required_artifact_hashes=key.dependency_hashes,
        producer_id="semantic-audit-producer-v1",
        producer_family=executor.producer_family,
        producer_protocol_version=executor.producer_protocol_version,
        executor_contract_hash=executor.executor_contract_hash,
        verifier_id=executor.verifier.verifier_id,
        verifier_version=executor.verifier.verifier_version,
        verifier_implementation_digest=executor.verifier.implementation_digest,
        result_contract_id=executor.result_contract_id,
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_semantic_rounds=3,
        max_result_contract_retries=1,
        max_shared_retries=1,
        max_artifact_contract_retries=1,
    )
    registry = InstalledAuthorityRegistry(
        executor_implementations={
            executor.adapter_id: executor.executor_implementation_digest
        },
        renderer_implementations={
            renderer.renderer_id: renderer.implementation_digest
        },
        tokenizer_implementations={},
        calculator_implementations={
            executor.reservation_calculator.calculator_id:
                executor.reservation_calculator.implementation_digest
        },
        normalizer_implementations={
            executor.token_accounting.normalization_id:
                executor.token_accounting.implementation_digest
        },
        verifier_implementations={
            executor.verifier.verifier_id: executor.verifier.implementation_digest
        },
        partitioner_implementations={},
        ownership_implementations={},
        agent_contracts={"echelon.re-validator": content_digest(agent_bytes)},
        response_schemas={
            renderer.response_schemas[0].artifact_kind:
                renderer.response_schemas[0].schema_hash
        },
    )
    dependencies = ProviderExecutionDependenciesV1(
        executor=executor,
        registry=registry,
        agent_bytes=agent_bytes,
        context_bytes=context_bytes,
        response_schema_bytes=schema_bytes,
        tokenizer=None,
    )
    paths = ReV2Paths.for_run(tmp_path / "re-semantic-store")
    paths.root.mkdir(parents=True)
    objects_store = ObjectStore(paths.objects)
    store = Protocol25ExecutionStore(paths, objects_store)

    prepared = store.prepare_execution(item, "initial_generation", dependencies)

    assert prepared.provider_envelope is None
    assert prepared.execution_input.context_bundle_hash == content_digest(context_bytes)
    assert store.validate_prepared_execution(prepared, item, dependencies) == prepared
