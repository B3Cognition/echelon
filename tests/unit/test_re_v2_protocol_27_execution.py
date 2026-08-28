from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.ledger import ObjectStore
from harness.squad_provider import SquadAgentResult
from tests.unit.test_re_v2_protocol_27_context import _source_item, _validated_inputs
from tests.unit.test_re_v2_protocol_27_runtime import _candidate


def _result(**overrides: object) -> SquadAgentResult:
    values: dict[str, object] = {
        "exit_code": 0,
        "echelon_result": {"verdict": "DONE", "state_updates": {}},
        "raw_output": "echelon_result:\n  verdict: DONE\n  state_updates: {}\n",
        "duration_ms": 20,
        "timed_out": False,
        "token_usage": 18,
        "token_usage_details": {"input_tokens": 10, "output_tokens": 8, "total_tokens": 18},
        "provider_name": "codex",
        "model_name": "gpt-5.6-codex",
        "stderr": "",
    }
    values.update(overrides)
    return SquadAgentResult(**values)  # type: ignore[arg-type]


class _WritingProvider:
    def __init__(self, payload: bytes | None, result: SquadAgentResult | None = None) -> None:
        self.payload = payload
        self.result = result or _result()
        self.calls: list[dict[str, object]] = []

    def exec_agent(self, project_root: str, prompt: str, **kwargs):
        self.calls.append({"project_root": project_root, "prompt": prompt, **kwargs})
        if self.payload is not None:
            (Path(project_root) / "synthesis.json").write_bytes(self.payload)
        return self.result


def _case(tmp_path: Path):
    from harness.re_v2.protocol_22.provider import decode_prosaic_agent_bytes
    from harness.re_v2.protocol_27.execution import (
        Protocol27ExecutionStore,
        build_synthesis_provider_dependencies,
    )

    inputs = _validated_inputs(tmp_path)
    item = _source_item(inputs)
    dependencies = build_synthesis_provider_dependencies(inputs, item, ())
    artifact = decode_prosaic_agent_bytes(dependencies.agent_bytes)
    context = __import__(
        "harness.re_v2.protocol_27.context", fromlist=["SynthesisContextV1"]
    ).SynthesisContextV1.from_json_dict(
        __import__("json").loads(dependencies.context_bytes)
    )
    candidate = _candidate(
        kind=item.output_key.artifact_kind,
        source_id=item.output_key.scope.source_id or "api",
        input_quality=context.input_quality,
        debt_refs=context.debt_refs,
        authority_id=context.dependency_artifacts[0].artifact_hash,
    )
    store = Protocol27ExecutionStore(
        inputs.paths,
        ObjectStore(inputs.paths.objects),
    )
    return inputs, item, dependencies, artifact, candidate, store


@pytest.mark.unit
def test_execution_resolves_frontmatter_through_existing_provider(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.execution import (
        SquadCliSynthesisRenderer,
        prepare_synthesis_execution,
        synthesis_candidate_bytes,
    )

    _inputs, item, dependencies, artifact, candidate, store = _case(tmp_path)
    payload = canonical_json_bytes(candidate.to_json_dict())
    provider = _WritingProvider(payload)
    renderer = SquadCliSynthesisRenderer(
        (dependencies.executor,),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    )
    prepared = prepare_synthesis_execution(
        store, item, dependencies, "initial_generation"
    )
    root = tmp_path / "candidate"
    root.mkdir()
    raw = renderer.execute(
        prepared.execution_input,
        dependencies.agent_bytes,
        dependencies.context_bytes,
        dependencies.response_schema_bytes,
        prepared.reservation,
        root,
        10**12,
    )
    captured = store.capture_provider_result(prepared, root, raw)
    store.commit_capture(captured)
    closure = store.validate_capture_closure(captured.commit)

    assert artifact.frontmatter["model_tier"] == "strong"
    assert artifact.frontmatter["effort"] == "high"
    assert provider.calls[0]["prompt_metadata"] == artifact.frontmatter
    assert provider.calls[0]["strict_result_envelope"] is True
    assert provider.calls[0]["isolated_workspace"] is True
    assert "synthesis.json" in str(provider.calls[0]["prompt"])
    assert synthesis_candidate_bytes(store, closure) == payload
    assert closure.capture.provider_name == "codex"
    assert closure.capture.resolved_model_revision == "gpt-5.6-codex"


@pytest.mark.unit
def test_renderer_rejects_invalid_result_envelope_without_private_repair(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.execution import (
        SquadCliSynthesisRenderer,
        prepare_synthesis_execution,
    )

    _inputs, item, dependencies, _artifact, candidate, store = _case(tmp_path)
    provider = _WritingProvider(
        canonical_json_bytes(candidate.to_json_dict()),
        _result(echelon_result={"verdict": "DONE", "state_updates": {"x": 1}}),
    )
    renderer = SquadCliSynthesisRenderer(
        (dependencies.executor,),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    )
    prepared = prepare_synthesis_execution(store, item, dependencies, "initial_generation")
    root = tmp_path / "candidate"
    root.mkdir()

    result = renderer.execute(
        prepared.execution_input,
        dependencies.agent_bytes,
        dependencies.context_bytes,
        dependencies.response_schema_bytes,
        prepared.reservation,
        root,
        10**12,
    )

    assert result.outcome == "invalid_response"
    assert provider.calls[0]["allow_result_repair"] is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("provider_result", "expected"),
    (
        (_result(timed_out=True), "timed_out"),
        (_result(exit_code=2, stderr="provider failed"), "transport_error"),
        (
            _result(
                echelon_result=None,
                echelon_result_validation_reason="missing echelon_result",
            ),
            "invalid_response",
        ),
        (
            _result(echelon_result={"verdict": "PASS", "state_updates": {}}),
            "invalid_response",
        ),
    ),
)
def test_renderer_maps_shared_provider_failures_without_repair(
    tmp_path: Path,
    provider_result: SquadAgentResult,
    expected: str,
) -> None:
    from harness.re_v2.protocol_27.execution import (
        SquadCliSynthesisRenderer,
        prepare_synthesis_execution,
    )

    _inputs, item, dependencies, _artifact, candidate, store = _case(tmp_path)
    provider = _WritingProvider(
        canonical_json_bytes(candidate.to_json_dict()),
        provider_result,
    )
    renderer = SquadCliSynthesisRenderer(
        (dependencies.executor,),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    )
    prepared = prepare_synthesis_execution(store, item, dependencies, "initial_generation")
    root = tmp_path / "candidate"
    root.mkdir()

    result = renderer.execute(
        prepared.execution_input,
        dependencies.agent_bytes,
        dependencies.context_bytes,
        dependencies.response_schema_bytes,
        prepared.reservation,
        root,
        10**12,
    )

    assert result.outcome == expected
    assert len(provider.calls) == 1
    assert provider.calls[0]["allow_result_repair"] is False


@pytest.mark.unit
def test_candidate_inventory_requires_exact_single_regular_synthesis_file(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.execution import (
        Protocol27ExecutionError,
        SquadCliSynthesisRenderer,
        prepare_synthesis_execution,
        synthesis_candidate_bytes,
    )

    _inputs, item, dependencies, _artifact, _candidate_value, store = _case(tmp_path)
    provider = _WritingProvider(None)
    renderer = SquadCliSynthesisRenderer(
        (dependencies.executor,),
        provider_factory=lambda: provider,  # type: ignore[return-value]
    )
    prepared = prepare_synthesis_execution(store, item, dependencies, "initial_generation")
    root = tmp_path / "candidate"
    root.mkdir()
    raw = renderer.execute(
        prepared.execution_input,
        dependencies.agent_bytes,
        dependencies.context_bytes,
        dependencies.response_schema_bytes,
        prepared.reservation,
        root,
        10**12,
    )
    captured = store.capture_provider_result(prepared, root, raw)
    closure = store.validate_capture_closure(captured.commit)

    with pytest.raises(Protocol27ExecutionError, match="exactly one"):
        synthesis_candidate_bytes(store, closure)


@pytest.mark.unit
def test_retry_diagnostics_are_exactly_bound_to_second_attempt(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.execution import (
        Protocol27ExecutionError,
        build_synthesis_provider_dependencies,
        prepare_synthesis_execution,
    )

    inputs, item, _dependencies, _artifact, _candidate_value, store = _case(tmp_path)
    diagnostics = ("authorial_schema_invalid",)
    retry = build_synthesis_provider_dependencies(inputs, item, diagnostics)
    prepared = prepare_synthesis_execution(
        store, item, retry, "artifact_contract_retry"
    )

    assert prepared.execution_input.attempt_kind == "artifact_contract_retry"
    with pytest.raises(Protocol27ExecutionError, match="diagnostics"):
        prepare_synthesis_execution(store, item, retry, "initial_generation")
    initial = build_synthesis_provider_dependencies(inputs, item, ())
    first = prepare_synthesis_execution(store, item, initial, "initial_generation")
    with pytest.raises(Protocol27ExecutionError, match="dependencies mismatch"):
        store.validate_prepared_execution(first, item, retry)
