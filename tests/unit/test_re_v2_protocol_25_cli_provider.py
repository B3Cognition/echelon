from __future__ import annotations

from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.cli_provider import (
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.protocol_22.model import ExecutionInputV1
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_25.cli_provider import SquadCliSemanticRenderer
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_cli_provider import _ProviderSpy, _result
from tests.unit.test_re_v2_protocol_25_inputs import _executor_fixture


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
