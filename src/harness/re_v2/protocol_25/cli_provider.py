"""Semantic request rendering over Echelon's frozen shared AI CLI adapter."""

from __future__ import annotations

import math
from pathlib import Path
import stat
import time
from typing import Callable

from harness.echelon_result_schema import EchelonResultContract
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.cli_provider import (
    SquadCliBaselineExecutor,
    calculate_shared_cli_dispatch_reservation,
)
from harness.re_v2.protocol_22.executors import (
    SHARED_AI_CLI_ADAPTER_ID,
    ExecutorContractEntryV1,
)
from harness.re_v2.protocol_22.execution import (
    PreparedExecutionV1,
    Protocol22ExecutionError,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
)
from harness.re_v2.protocol_22.model import ExecutionInputV1, WorkItemV2
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

from .policies import (
    SEMANTIC_ARTIFACT_KINDS,
    SEMANTIC_EXECUTOR_FAMILIES,
    SEMANTIC_RENDERER_ID,
)
from .runtime import Protocol25RuntimeError, SemanticContextV1


_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)

_SEMANTIC_MODE_BY_ARTIFACT = {
    "semantic-audit-findings": "AUDIT_EPOCH_TARGET",
    "semantic-resolution-overlay": "SEMANTIC_RESOLUTION",
    "target-closure-assessment": "CLOSURE_RECHECK",
    "source-composition-assessment": "SOURCE_COMPOSITION_GUARD",
}
_CANDIDATE_FILE_BY_ARTIFACT = {
    "semantic-audit-findings": "audit.json",
    "semantic-resolution-overlay": "resolution.json",
    "target-closure-assessment": "closure.json",
    "source-composition-assessment": "closure.json",
}


class Protocol25ExecutionStore(Protocol22ExecutionStore):
    """Extend the frozen execution store only for authenticated L3 CLI requests."""

    def _prepare_provider(
        self,
        work_item: WorkItemV2,
        attempt_kind: str,
        dispatch_id: str,
        dependencies: ProviderExecutionDependenciesV1,
        fault_hook: Callable[[str], None] | None,
    ) -> PreparedExecutionV1:
        if work_item.output_key.artifact_kind not in _SEMANTIC_MODE_BY_ARTIFACT:
            return super()._prepare_provider(
                work_item,
                attempt_kind,
                dispatch_id,
                dependencies,
                fault_hook,
            )
        executor = dependencies.executor
        if (attempt_kind == "initial_generation") != (
            not dependencies.retry_diagnostics
        ):
            raise Protocol22ExecutionError(
                "provider retry diagnostics must exist exactly for retry attempts"
            )
        if executor.execution_mode != "cli":
            raise Protocol22ExecutionError(
                "semantic provider preparation requires shared CLI execution"
            )
        validate_semantic_provider_content_authority(
            work_item,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            executor,
            content_digest(dependencies.response_schema_bytes),
        )
        agent_hash = self.object_store.put_blob(dependencies.agent_bytes)
        context_hash = self.object_store.put_blob(dependencies.context_bytes)
        self.object_store.put_blob(dependencies.response_schema_bytes)
        reservation = calculate_shared_cli_dispatch_reservation(
            dependencies.agent_bytes,
            dependencies.context_bytes,
            dependencies.response_schema_bytes,
            executor,
        )
        execution_input = ExecutionInputV1(
            schema_version=1,
            dispatch_id=dispatch_id,
            work_item_id=work_item.work_item_id,
            attempt_kind=attempt_kind,  # type: ignore[arg-type]
            executor_contract_hash=executor.executor_contract_hash,
            agent_contract_hash=agent_hash,
            context_bundle_hash=context_hash,
            provider_request_envelope_hash=None,
            deterministic_invocation=None,
        )
        input_hash = self.object_store.put_blob(
            canonical_json_bytes(execution_input.to_json_dict())
        )
        if fault_hook is not None:
            fault_hook("execution_input_fsynced")
        return PreparedExecutionV1(
            dispatch_id=dispatch_id,
            execution_input=execution_input,
            execution_input_hash=input_hash,
            provider_envelope=None,
            provider_envelope_hash=None,
            reservation=reservation,
        )

    def _validate_prepared_provider(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2,
        dependencies: ProviderExecutionDependenciesV1,
    ) -> PreparedExecutionV1:
        if work_item.output_key.artifact_kind not in _SEMANTIC_MODE_BY_ARTIFACT:
            return super()._validate_prepared_provider(
                prepared,
                work_item,
                dependencies,
            )
        if (
            dependencies.executor.execution_mode != "cli"
            or prepared.provider_envelope is not None
            or prepared.provider_envelope_hash is not None
        ):
            raise Protocol22ExecutionError(
                "prepared semantic CLI execution contains invalid provider authority"
            )
        validate_semantic_provider_content_authority(
            work_item,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            dependencies.executor,
            content_digest(dependencies.response_schema_bytes),
        )
        expected = calculate_shared_cli_dispatch_reservation(
            self.object_store.read_blob(
                prepared.execution_input.agent_contract_hash or ""
            ),
            self.object_store.read_blob(
                prepared.execution_input.context_bundle_hash or ""
            ),
            dependencies.response_schema_bytes,
            dependencies.executor,
        )
        if expected != prepared.reservation:
            raise Protocol22ExecutionError(
                "prepared semantic CLI reservation authority mismatch"
            )
        return prepared


def validate_semantic_provider_content_authority(
    work_item: WorkItemV2,
    agent_bytes: bytes,
    context_bytes: bytes,
    executor: ExecutorContractEntryV1,
    schema_hash: str,
) -> SemanticContextV1:
    """Validate L3 request bytes without widening protocol 2.2's frozen schema."""
    kind = work_item.output_key.artifact_kind
    renderer = executor.request_renderer
    expected_mode = _SEMANTIC_MODE_BY_ARTIFACT.get(kind)
    schema = (
        None
        if renderer is None
        else next(
            (
                item
                for item in renderer.response_schemas
                if item.artifact_kind == kind
            ),
            None,
        )
    )
    if (
        work_item.output_key.layer != "L3"
        or kind not in SEMANTIC_ARTIFACT_KINDS
        or executor.producer_family not in SEMANTIC_EXECUTOR_FAMILIES
        or executor.execution_mode != "cli"
        or executor.adapter_id != SHARED_AI_CLI_ADAPTER_ID
        or renderer is None
        or renderer.renderer_id != SEMANTIC_RENDERER_ID
        or schema is None
        or schema.schema_hash != schema_hash
        or expected_mode is None
    ):
        raise Protocol22ProviderError("semantic shared CLI content authority is invalid")
    if content_digest(agent_bytes) != renderer.agent_contract_hash:
        raise Protocol22ProviderError("semantic agent contract hash mismatch")
    decode_prosaic_agent_bytes(agent_bytes)
    try:
        context = load_canonical_object(
            context_bytes,
            SemanticContextV1.from_json_dict,
        )
    except (Protocol22SchemaError, Protocol25RuntimeError) as exc:
        raise Protocol22ProviderError(f"invalid semantic context: {exc}") from exc
    if (
        context.mode != expected_mode
        or context.audit_target.scope != work_item.output_key.scope
        or context.response_schema_hash != schema_hash
    ):
        raise Protocol22ProviderError(
            "semantic context does not match work item and response authority"
        )
    return context


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
        result_invalid = bool(
            result.echelon_result_validation_reason
            or result.verdict != "DONE"
            or result.state_updates
        )
        if result_invalid:
            if (
                result.echelon_result_validation_reason
                and result.echelon_result is None
                and not result.state_updates
                and _has_exact_semantic_candidate(root, execution_input, executor)
            ):
                return RawExecutionResultV1(
                    _RESULT_STDOUT,
                    stderr,
                    usage,
                    timing,
                    "candidate_ready",
                    provider_name,
                    model_name,
                )
            return RawExecutionResultV1(
                b"",
                b"invalid_response:echelon_result\n",
                usage,
                timing,
                "invalid_response",
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


def _has_exact_semantic_candidate(
    root: Path,
    execution_input: ExecutionInputV1,
    executor: ExecutorContractEntryV1,
) -> bool:
    """Recover only one regular candidate; certification still validates its bytes."""
    renderer = executor.request_renderer
    if renderer is None or len(renderer.response_schemas) != 1:
        return False
    expected = _CANDIDATE_FILE_BY_ARTIFACT.get(
        renderer.response_schemas[0].artifact_kind
    )
    if expected is None:
        return False
    try:
        entries = tuple(root.iterdir())
        metadata = entries[0].lstat() if len(entries) == 1 else None
    except OSError:
        return False
    return bool(
        metadata is not None
        and entries[0].name == expected
        and stat.S_ISREG(metadata.st_mode)
        and metadata.st_size > 0
        and execution_input.executor_contract_hash == executor.executor_contract_hash
    )


__all__ = ("Protocol25ExecutionStore", "SquadCliSemanticRenderer")
