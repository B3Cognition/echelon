"""Semantic request rendering over Echelon's frozen shared AI CLI adapter."""

from __future__ import annotations

import math
from pathlib import Path
import time
from typing import Callable

from harness.echelon_result_schema import EchelonResultContract
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.cli_provider import (
    SquadCliBaselineExecutor,
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.protocol_22.executors import (
    SHARED_AI_CLI_ADAPTER_ID,
    ExecutorContractEntryV1,
)
from harness.re_v2.protocol_22.model import ExecutionInputV1
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    Protocol22ProviderError,
    RawExecutionResultV1,
    RawExecutionTimingV1,
    _RESULT_STDOUT,
    _utc_now,
    _validate_empty_candidate_root,
    canonical_normalized_usage_bytes,
    decode_prosaic_agent_bytes,
    normalize_shared_provider_usage,
)
from harness.re_v2.protocol_22.schema import Protocol22SchemaError, load_canonical_object
from harness.squad_provider import SquadCliProvider

from .policies import SEMANTIC_EXECUTOR_FAMILIES, SEMANTIC_RENDERER_ID


_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)


class SquadCliSemanticRenderer:
    """Route inherited work unchanged and render only registered L3 requests."""

    def __init__(
        self,
        executors: tuple[ExecutorContractEntryV1, ...],
        *,
        provider_factory: Callable[[], SquadCliProvider],
    ) -> None:
        if not executors or not callable(provider_factory):
            raise Protocol22ProviderError(
                "semantic shared CLI rendering requires contracts and a provider factory"
            )
        if len({item.executor_contract_hash for item in executors}) != len(executors):
            raise Protocol22ProviderError("shared CLI executor contracts must be unique")
        if len({item.provider_id for item in executors}) != 1:
            raise Protocol22ProviderError("shared CLI contracts must use one provider")
        self._executors = {
            item.executor_contract_hash: item for item in executors
        }
        self._provider_factory = provider_factory
        self._provider: SquadCliProvider | None = None
        self._inherited = {
            item.executor_contract_hash: SquadCliBaselineExecutor(
                item,
                provider_factory=self._shared_provider,
            )
            for item in executors
            if item.producer_family not in SEMANTIC_EXECUTOR_FAMILIES
        }

    def execute(
        self,
        execution_input: ExecutionInputV1,
        agent_bytes: bytes,
        context_bytes: bytes,
        response_schema_bytes: bytes,
        reservation: DispatchReservationV1,
        candidate_root: Path,
        deadline: float,
    ) -> RawExecutionResultV1:
        executor = self._executors.get(execution_input.executor_contract_hash)
        if executor is None:
            raise Protocol22ProviderError("execution input executor contract mismatch")
        inherited = self._inherited.get(execution_input.executor_contract_hash)
        if inherited is not None:
            return inherited.execute(
                execution_input,
                agent_bytes,
                context_bytes,
                response_schema_bytes,
                reservation,
                candidate_root,
                deadline,
            )
        artifact = _validate_semantic_inputs(
            executor,
            execution_input,
            agent_bytes,
            context_bytes,
            response_schema_bytes,
            reservation,
        )
        root = _validate_empty_candidate_root(candidate_root)
        if (
            not isinstance(deadline, (int, float))
            or isinstance(deadline, bool)
            or not math.isfinite(deadline)
        ):
            raise Protocol22ProviderError("executor deadline must be finite monotonic time")
        remaining_seconds = min(
            deadline - time.monotonic(),
            reservation.active_ms / 1000,
        )
        if remaining_seconds <= 0:
            moment = _utc_now()
            return RawExecutionResultV1(
                stdout=b"",
                stderr=b"deadline_expired\n",
                provider_usage=canonical_normalized_usage_bytes(
                    normalize_shared_provider_usage(0, {})
                ),
                timing=RawExecutionTimingV1(moment, moment, 0),
                outcome="timed_out",
            )
        prompt = _render_semantic_prompt(
            artifact.body,
            context_bytes.decode("utf-8"),
            response_schema_bytes.decode("utf-8"),
        )
        if len(prompt.encode("utf-8")) > reservation.initial_input_tokens:
            raise Protocol22ProviderError(
                "semantic prompt exceeds the inherited conservative reservation"
            )
        started_at = _utc_now()
        result = self._shared_provider().exec_agent(
            str(root),
            prompt,
            timeout_ms=max(1, int(remaining_seconds * 1000)),
            result_contract=_RESULT_CONTRACT,
            prompt_metadata=dict(artifact.frontmatter),
            allow_result_repair=False,
            strict_result_envelope=True,
            isolated_workspace=True,
        )
        timing = RawExecutionTimingV1(
            started_at,
            _utc_now(),
            max(0, int(result.duration_ms)),
        )
        usage = canonical_normalized_usage_bytes(
            normalize_shared_provider_usage(
                result.token_usage,
                result.token_usage_details,
            )
        )
        provider_name = result.provider_name.strip() or None
        model_name = result.model_name.strip() or None
        stderr = result.stderr.encode("utf-8", errors="replace")
        if result.timed_out:
            return RawExecutionResultV1(
                b"",
                stderr or b"request_timed_out\n",
                usage,
                timing,
                "timed_out",
                provider_name,
                model_name,
            )
        if result.exit_code != 0:
            return RawExecutionResultV1(
                b"",
                stderr or b"transport_error\n",
                usage,
                timing,
                "transport_error",
                provider_name,
                model_name,
            )
        if (
            result.echelon_result_validation_reason
            or result.verdict != "DONE"
            or result.state_updates
        ):
            return RawExecutionResultV1(
                b"",
                b"invalid_response:echelon_result\n",
                usage,
                timing,
                "invalid_response",
                provider_name,
                model_name,
            )
        return RawExecutionResultV1(
            _RESULT_STDOUT,
            stderr,
            usage,
            timing,
            "candidate_ready",
            provider_name,
            model_name,
        )

    def _shared_provider(self) -> SquadCliProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider


def _validate_semantic_inputs(
    executor: ExecutorContractEntryV1,
    execution_input: ExecutionInputV1,
    agent_bytes: bytes,
    context_bytes: bytes,
    response_schema_bytes: bytes,
    reservation: DispatchReservationV1,
):  # type: ignore[no-untyped-def]
    renderer = executor.request_renderer
    if (
        executor.producer_family not in SEMANTIC_EXECUTOR_FAMILIES
        or executor.execution_mode != "cli"
        or executor.adapter_id != SHARED_AI_CLI_ADAPTER_ID
        or renderer is None
        or renderer.renderer_id != SEMANTIC_RENDERER_ID
        or len(renderer.response_schemas) != 1
    ):
        raise Protocol22ProviderError("semantic shared CLI authority is invalid")
    if not isinstance(execution_input, ExecutionInputV1):
        raise Protocol22ProviderError("shared CLI execution requires ExecutionInputV1")
    if execution_input.executor_contract_hash != executor.executor_contract_hash:
        raise Protocol22ProviderError("execution input executor contract mismatch")
    if execution_input.agent_contract_hash != content_digest(agent_bytes):
        raise Protocol22ProviderError("execution input agent contract mismatch")
    if execution_input.context_bundle_hash != content_digest(context_bytes):
        raise Protocol22ProviderError("execution input context bundle mismatch")
    artifact = decode_prosaic_agent_bytes(agent_bytes)
    try:
        load_canonical_object(context_bytes, lambda value: value)
        load_canonical_object(response_schema_bytes, lambda value: value)
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(str(exc)) from exc
    if renderer.response_schemas[0].schema_hash != content_digest(
        response_schema_bytes
    ):
        raise Protocol22ProviderError("response schema authority mismatch")
    expected = calculate_shared_cli_dispatch_reservation(
        agent_bytes,
        context_bytes,
        response_schema_bytes,
        executor,
    )
    if reservation != expected:
        raise Protocol22ProviderError("shared CLI dispatch reservation mismatch")
    return artifact


def _render_semantic_prompt(body: str, context: str, response_schema: str) -> str:
    return (
        body
        + ("" if body.endswith("\n") else "\n")
        + "\n## Dispatch contract\n"
        + "Write exactly the candidate file required by the role contract. The file "
        + "must contain only the authorial JSON payload matching the supplied schema. "
        + "Finish with exactly the required `echelon_result` block.\n\n"
        + "## Bounded context (canonical JSON)\n"
        + context
        + "\n\n## Authorial response schema (canonical JSON)\n"
        + response_schema
        + "\n"
    )


__all__ = ("SquadCliSemanticRenderer",)
