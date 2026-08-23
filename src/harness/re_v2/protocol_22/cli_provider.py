"""Thin protocol adapter for Echelon's existing shared AI CLI provider."""

from __future__ import annotations

import math
from pathlib import Path
import time

from harness.echelon_result_schema import EchelonResultContract
from harness.re_v2.canonical import content_digest
from harness.squad_provider import SquadCliProvider

from .artifacts import ContextBundleV1
from .executors import (
    DISPATCH_CALCULATOR_ID,
    SHARED_AI_CLI_ADAPTER_ID,
    SHARED_PROVIDER_USAGE_NORMALIZER_ID,
    ExecutorContractEntryV1,
)
from .model import ExecutionInputV1
from .provider import (
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
from .schema import Protocol22SchemaError, load_canonical_object


_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)


class SquadCliBaselineExecutor:
    """Adapt one shared-provider dispatch to the existing raw capture surface."""

    def __init__(
        self,
        executor: ExecutorContractEntryV1,
        *,
        provider: SquadCliProvider,
    ) -> None:
        _validate_cli_executor(executor)
        self.executor = executor
        self._provider = provider

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
        artifact = _validate_dispatch_inputs(
            self.executor,
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
            raise Protocol22ProviderError(
                "executor deadline must be finite monotonic time"
            )
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

        prompt = _render_prompt(
            artifact.body,
            context_bytes.decode("utf-8"),
            response_schema_bytes.decode("utf-8"),
        )
        started_at = _utc_now()
        result = self._provider.exec_agent(
            str(root),
            prompt,
            timeout_ms=max(1, int(remaining_seconds * 1000)),
            result_contract=_RESULT_CONTRACT,
            prompt_metadata=dict(artifact.frontmatter),
            allow_result_repair=False,
            strict_result_envelope=True,
        )
        ended_at = _utc_now()
        timing = RawExecutionTimingV1(
            started_at,
            ended_at,
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


def _validate_cli_executor(executor: object) -> None:
    if not isinstance(executor, ExecutorContractEntryV1) or (
        executor.execution_mode != "cli"
        or executor.adapter_id != SHARED_AI_CLI_ADAPTER_ID
        or executor.provider_id is None
        or executor.request_renderer is None
        or executor.reservation_calculator.calculator_id != DISPATCH_CALCULATOR_ID
        or executor.token_accounting.normalization_id
        != SHARED_PROVIDER_USAGE_NORMALIZER_ID
    ):
        raise Protocol22ProviderError(
            "shared CLI baseline requires its registered executor contract"
        )


def _validate_dispatch_inputs(
    executor: ExecutorContractEntryV1,
    execution_input: ExecutionInputV1,
    agent_bytes: bytes,
    context_bytes: bytes,
    response_schema_bytes: bytes,
    reservation: DispatchReservationV1,
):
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
        context = load_canonical_object(context_bytes, ContextBundleV1.from_json_dict)
        load_canonical_object(response_schema_bytes, lambda value: value)
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(str(exc)) from exc
    renderer = executor.request_renderer
    assert renderer is not None
    expected_schema = next(
        (
            reference.schema_hash
            for reference in renderer.response_schemas
            if reference.artifact_kind == context.target_artifact_kind
        ),
        None,
    )
    if expected_schema != content_digest(response_schema_bytes):
        raise Protocol22ProviderError("response schema authority mismatch")
    if not isinstance(reservation, DispatchReservationV1) or (
        reservation.billable_tokens
        != executor.limits.max_billable_tokens_per_dispatch
        or reservation.active_ms != executor.limits.max_active_ms_per_dispatch
    ):
        raise Protocol22ProviderError("shared CLI dispatch reservation mismatch")
    return artifact


def _render_prompt(body: str, context: str, response_schema: str) -> str:
    return (
        body
        + ("" if body.endswith("\n") else "\n")
        + "\n## Dispatch contract\n"
        + "Write exactly one file named `baseline.json` in the current working "
        + "directory. The file must contain only the authorial JSON payload that "
        + "matches the supplied schema. Finish with exactly the required "
        + "`echelon_result` block.\n\n"
        + "## Bounded context (canonical JSON)\n"
        + context
        + "\n\n## Authorial response schema (canonical JSON)\n"
        + response_schema
        + "\n"
    )


__all__ = ("SquadCliBaselineExecutor",)
