from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from harness.echelon_result_schema import EchelonResultContract
from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.cli_provider import (
    SquadCliBaselineExecutor,
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.protocol_22.executors import (
    SHARED_AI_CLI_ADAPTER_ID,
    SHARED_PROVIDER_USAGE_NORMALIZER_ID,
    ExecutorContractEntryV1,
)
from harness.re_v2.protocol_22.model import ExecutionInputV1
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    canonical_prosaic_agent_bytes,
    decode_normalized_usage_bytes,
)
from harness.re_v2.protocol_22.response_schemas import (
    canonical_response_schema_bytes,
)
from harness.squad_provider import SquadAgentResult
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_context import _domain_fixture


class _ProviderSpy:
    def __init__(self, result: SquadAgentResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def exec_agent(
        self,
        project_root: str,
        prompt: str,
        timeout_ms: int | None = None,
        result_contract: EchelonResultContract | None = None,
        prompt_metadata: dict[str, object] | None = None,
        allow_result_repair: bool = True,
        strict_result_envelope: bool = False,
        isolated_workspace: bool = False,
    ) -> SquadAgentResult:
        self.calls.append(
            {
                "project_root": project_root,
                "prompt": prompt,
                "timeout_ms": timeout_ms,
                "result_contract": result_contract,
                "prompt_metadata": prompt_metadata,
                "allow_result_repair": allow_result_repair,
                "strict_result_envelope": strict_result_envelope,
                "isolated_workspace": isolated_workspace,
            }
        )
        return self.result


def _cli_executor() -> ExecutorContractEntryV1:
    api = _domain_fixture().inputs.executor_contract.entry_for("compact-baseline")
    return replace(
        api,
        execution_mode="cli",
        provider_id="codex",
        api_transport=None,
        adapter_id=SHARED_AI_CLI_ADAPTER_ID,
        executor_implementation_digest=digest("shared CLI adapter"),
        model=None,
        request_tokenizer=None,
        generation=None,
        token_accounting=replace(
            api.token_accounting,
            normalization_id=SHARED_PROVIDER_USAGE_NORMALIZER_ID,
            implementation_digest=digest("shared usage normalizer"),
        ),
        limits=replace(
            api.limits,
            provider_context_tokens=None,
            max_completion_tokens_per_call=0,
        ),
    )


def _inputs() -> tuple[
    ExecutorContractEntryV1,
    ExecutionInputV1,
    bytes,
    dict[str, object],
    bytes,
    bytes,
    DispatchReservationV1,
]:
    executor = _cli_executor()
    frontmatter = {
        "name": "echelon.re-baseliner",
        "execution": "agent",
        "tools": "write",
        "model_tier": "strong",
        "effort": "high",
        "description": "must stay outside the prompt body",
    }
    agent_bytes = canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            body="Pinned baseliner body. \n",
            frontmatter=frontmatter,
        )
    )
    context_bytes = _domain_fixture().context_bytes
    schema_bytes = canonical_response_schema_bytes("domain-baseline")
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id="dispatch-1",
        work_item_id=digest("work item"),
        attempt_kind="initial_generation",
        executor_contract_hash=executor.executor_contract_hash,
        agent_contract_hash=content_digest(agent_bytes),
        context_bundle_hash=content_digest(context_bytes),
        # Task 4 generalizes this existing provider branch to permit null for CLI.
        provider_request_envelope_hash=digest("unused API envelope"),
        deterministic_invocation=None,
    )
    reservation = calculate_shared_cli_dispatch_reservation(
        agent_bytes,
        context_bytes,
        schema_bytes,
        executor,
    )
    return (
        executor,
        execution_input,
        agent_bytes,
        frontmatter,
        context_bytes,
        schema_bytes,
        reservation,
    )


def test_cli_reservation_is_the_exact_rendered_prompt_byte_upper_bound() -> None:
    executor, _input, agent, _metadata, context, schema, reservation = _inputs()

    assert reservation == calculate_shared_cli_dispatch_reservation(
        agent,
        context,
        schema,
        executor,
    )
    assert reservation.initial_input_tokens > len(context)
    assert reservation.billable_tokens == executor.limits.max_billable_tokens_per_dispatch


def test_cli_retry_diagnostics_are_in_the_exact_reserved_prompt(
    tmp_path: Path,
) -> None:
    (
        executor,
        execution_input,
        agent_bytes,
        _frontmatter,
        context_bytes,
        schema_bytes,
        initial_reservation,
    ) = _inputs()
    diagnostics = (
        "minimum_utility_not_met",
        "responsibilities_not_observed",
    )
    execution_input = replace(
        execution_input,
        attempt_kind="artifact_contract_retry",
    )
    reservation = calculate_shared_cli_dispatch_reservation(
        agent_bytes,
        context_bytes,
        schema_bytes,
        executor,
        diagnostics,
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    provider = _ProviderSpy(_result())

    SquadCliBaselineExecutor(executor, provider=provider).execute(
        execution_input,
        agent_bytes,
        context_bytes,
        schema_bytes,
        reservation,
        candidate_root,
        10**12,
        retry_diagnostics=diagnostics,
    )

    prompt = provider.calls[0]["prompt"]
    assert isinstance(prompt, str)
    assert reservation.initial_input_tokens > initial_reservation.initial_input_tokens
    assert "## Retry diagnostics (canonical JSON)" in prompt
    assert (
        '{"diagnostics":["minimum_utility_not_met",'
        '"responsibilities_not_observed"],"schema_version":1}'
        in prompt
    )


def _result(**overrides: object) -> SquadAgentResult:
    values: dict[str, object] = {
        "exit_code": 0,
        "echelon_result": {"verdict": "DONE", "state_updates": {}},
        "raw_output": "echelon_result:\n  verdict: DONE\n  state_updates: {}\n",
        "duration_ms": 125,
        "timed_out": False,
        "token_usage": 18,
        "token_usage_details": {
            "input_tokens": 10,
            "cached_input_tokens": 4,
            "output_tokens": 8,
            "reasoning_output_tokens": 3,
            "total_tokens": 18,
        },
        "provider_name": "codex",
        "model_name": "gpt-5.6-codex",
        "stderr": "",
    }
    values.update(overrides)
    return SquadAgentResult(**values)  # type: ignore[arg-type]


def _execute(
    tmp_path: Path,
    provider_result: SquadAgentResult,
    *,
    deadline: float = 10**12,
):
    (
        executor,
        execution_input,
        agent_bytes,
        frontmatter,
        context_bytes,
        schema_bytes,
        reservation,
    ) = _inputs()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    provider = _ProviderSpy(provider_result)
    result = SquadCliBaselineExecutor(executor, provider=provider).execute(
        execution_input,
        agent_bytes,
        context_bytes,
        schema_bytes,
        reservation,
        candidate_root,
        deadline,
    )
    return result, provider, candidate_root, frontmatter, context_bytes, schema_bytes


def test_adapter_delegates_exact_prosaic_metadata_and_strict_result_contract(
    tmp_path: Path,
) -> None:
    result, provider, candidate_root, frontmatter, context, schema = _execute(
        tmp_path,
        _result(),
    )

    call = provider.calls[0]
    assert call["project_root"] == str(candidate_root)
    assert call["prompt_metadata"] == frontmatter
    assert call["allow_result_repair"] is False
    assert call["strict_result_envelope"] is True
    assert call["isolated_workspace"] is True
    assert call["result_contract"] == EchelonResultContract(
        allowed_state_update_keys=frozenset(),
        allowed_verdicts=frozenset({"DONE"}),
        unexpected_state_updates="reject",
    )
    prompt = call["prompt"]
    assert isinstance(prompt, str)
    assert prompt.startswith("Pinned baseliner body. \n")
    assert "must stay outside the prompt body" not in prompt
    assert "baseline.json" in prompt
    assert context.decode("utf-8") in prompt
    assert schema.decode("utf-8") in prompt
    assert result.outcome == "candidate_ready"
    assert result.provider_name == "codex"
    assert result.resolved_model_revision == "gpt-5.6-codex"
    assert result.provider_usage is not None
    assert decode_normalized_usage_bytes(result.provider_usage).status == "trusted_exact"


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
def test_adapter_maps_shared_provider_failures_without_repair(
    tmp_path: Path,
    provider_result: SquadAgentResult,
    expected: str,
) -> None:
    result, provider, *_rest = _execute(tmp_path, provider_result)

    assert result.outcome == expected
    assert len(provider.calls) == 1


def test_adapter_marks_missing_usage_unavailable(tmp_path: Path) -> None:
    result, *_rest = _execute(
        tmp_path,
        _result(token_usage=0, token_usage_details={}),
    )

    assert result.provider_usage is not None
    usage = decode_normalized_usage_bytes(result.provider_usage)
    assert usage.status == "unavailable"
    assert usage.billable_tokens is None


def test_expired_deadline_does_not_invoke_shared_provider(tmp_path: Path) -> None:
    result, provider, *_rest = _execute(tmp_path, _result(), deadline=0)

    assert result.outcome == "timed_out"
    assert provider.calls == []
