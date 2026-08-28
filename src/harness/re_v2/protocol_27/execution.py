"""Protocol-2.7 synthesis composition over the shared Prosaic CLI provider."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from pathlib import Path
import time
from typing import Callable

from harness.echelon_result_schema import EchelonResultContract
from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.cli_provider import (
    calculate_shared_cli_dispatch_reservation,
    render_cli_retry_section,
)
from harness.re_v2.protocol_22.execution import (
    PreparedExecutionV1,
    Protocol22ExecutionError,
    Protocol22ExecutionStore,
    ProviderExecutionDependenciesV1,
    ValidatedCaptureClosureV1,
)
from harness.re_v2.protocol_22.executors import (
    DISPATCH_CALCULATOR_ID,
    SHARED_AI_CLI_ADAPTER_ID,
    SHARED_PROVIDER_USAGE_NORMALIZER_ID,
    ExecutorContractEntryV1,
    ExecutorLimitsV1,
    RequestRendererAuthorityV1,
    ReservationCalculatorAuthorityV1,
    ResponseSchemaReferenceV1,
    TokenAccountingAuthorityV1,
    VerifierAuthorityV1,
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
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
    safe_id,
)
from harness.squad_provider import SquadCliProvider

from .context import (
    Protocol27ContextError,
    SynthesisContextV1,
    build_synthesis_context,
)
from .inputs import ValidatedProtocol27Inputs
from .model import SynthesisWorkItemV1
from .policies import SYNTHESIS_GENERATED_KINDS


SYNTHESIS_PRODUCER_FAMILY = "workspace-synthesis"
SYNTHESIS_RENDERER_ID = "synthesis-renderer-v1"
SYNTHESIS_RESULT_CONTRACT_ID = "synthesis-json-result-v1"
SYNTHESIS_CANDIDATE_FILE = "synthesis.json"

_RESULT_CONTRACT = EchelonResultContract(
    allowed_state_update_keys=frozenset(),
    allowed_verdicts=frozenset({"DONE"}),
    unexpected_state_updates="reject",
)


class Protocol27ExecutionError(Protocol22ExecutionError):
    """Raised when synthesis execution authority is incomplete or unsafe."""


class SynthesisResponseSchemaReferenceV1(ResponseSchemaReferenceV1):
    def __post_init__(self) -> None:
        try:
            safe_id(self.artifact_kind, "synthesis response schema kind")
            digest_value(self.schema_hash, "synthesis response schema hash")
        except Protocol22SchemaError as exc:
            raise Protocol27ExecutionError(str(exc)) from exc
        if self.artifact_kind not in SYNTHESIS_GENERATED_KINDS:
            raise Protocol27ExecutionError("synthesis response schema kind is unsupported")

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisResponseSchemaReferenceV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        return cls(raw["artifact_kind"], raw["schema_hash"])


class SynthesisRequestRendererAuthorityV1(RequestRendererAuthorityV1):
    def __post_init__(self) -> None:
        try:
            safe_id(self.renderer_id, "synthesis renderer ID")
            safe_id(self.renderer_version, "synthesis renderer version")
            digest_value(self.implementation_digest, "synthesis renderer implementation")
            digest_value(self.agent_contract_hash, "synthesis renderer agent contract")
        except Protocol22SchemaError as exc:
            raise Protocol27ExecutionError(str(exc)) from exc
        if self.renderer_id != SYNTHESIS_RENDERER_ID:
            raise Protocol27ExecutionError("synthesis renderer ID is unsupported")
        if not isinstance(self.response_schemas, (list, tuple)) or any(
            not isinstance(item, SynthesisResponseSchemaReferenceV1)
            for item in self.response_schemas
        ):
            raise Protocol27ExecutionError("synthesis renderer schemas are invalid")
        schemas = tuple(self.response_schemas)
        if tuple(item.artifact_kind for item in schemas) != tuple(
            sorted(SYNTHESIS_GENERATED_KINDS)
        ):
            raise Protocol27ExecutionError(
                "synthesis renderer must register every generated schema exactly once"
            )
        object.__setattr__(self, "response_schemas", schemas)

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisRequestRendererAuthorityV1":
        raw = exact_object(value, frozenset(cls.FIELDS), cls.__name__)
        schemas = raw["response_schemas"]
        if not isinstance(schemas, (list, tuple)):
            raise Protocol27ExecutionError("synthesis renderer schemas must be an array")
        return cls(
            renderer_id=raw["renderer_id"],
            renderer_version=raw["renderer_version"],
            implementation_digest=raw["implementation_digest"],
            agent_contract_hash=raw["agent_contract_hash"],
            response_schemas=tuple(
                SynthesisResponseSchemaReferenceV1.from_json_dict(item)
                for item in schemas
            ),
        )


def synthesis_executor_from_json(value: object) -> ExecutorContractEntryV1:
    """Decode the existing executor shape with a protocol-2.7 renderer subtype."""
    raw = exact_object(
        value,
        frozenset(ExecutorContractEntryV1.FIELDS),
        "synthesis executor entry",
    )
    if any(
        raw[field] is not None
        for field in ("api_transport", "model", "request_tokenizer", "generation")
    ):
        raise Protocol27ExecutionError(
            "synthesis execution must remain on shared CLI authority"
        )
    return ExecutorContractEntryV1(
        producer_family=raw["producer_family"],
        execution_mode=raw["execution_mode"],
        provider_id=raw["provider_id"],
        api_transport=None,
        adapter_id=raw["adapter_id"],
        adapter_contract_version=raw["adapter_contract_version"],
        executor_implementation_digest=raw["executor_implementation_digest"],
        producer_protocol_version=raw["producer_protocol_version"],
        result_contract_id=raw["result_contract_id"],
        verifier=VerifierAuthorityV1.from_json_dict(raw["verifier"]),
        model=None,
        request_renderer=SynthesisRequestRendererAuthorityV1.from_json_dict(
            raw["request_renderer"]
        ),
        request_tokenizer=None,
        generation=None,
        reservation_calculator=ReservationCalculatorAuthorityV1.from_json_dict(
            raw["reservation_calculator"]
        ),
        token_accounting=TokenAccountingAuthorityV1.from_json_dict(
            raw["token_accounting"]
        ),
        limits=ExecutorLimitsV1.from_json_dict(raw["limits"]),
    )


def compose_synthesis_executor(
    inherited_cli: ExecutorContractEntryV1,
    *,
    agent_contract_hash: str,
    response_schema_hashes: dict[str, str],
    renderer_implementation_digest: str,
    verifier_implementation_digest: str,
) -> ExecutorContractEntryV1:
    """Reuse one configured shared CLI entry and replace only synthesis authority."""
    if (
        not isinstance(inherited_cli, ExecutorContractEntryV1)
        or inherited_cli.execution_mode != "cli"
        or inherited_cli.adapter_id != SHARED_AI_CLI_ADAPTER_ID
    ):
        raise Protocol27ExecutionError(
            "synthesis executor composition requires the configured shared CLI entry"
        )
    if set(response_schema_hashes) != SYNTHESIS_GENERATED_KINDS:
        raise Protocol27ExecutionError("synthesis executor schema set is incomplete")
    renderer = SynthesisRequestRendererAuthorityV1(
        renderer_id=SYNTHESIS_RENDERER_ID,
        renderer_version="1",
        implementation_digest=renderer_implementation_digest,
        agent_contract_hash=agent_contract_hash,
        response_schemas=tuple(
            SynthesisResponseSchemaReferenceV1(kind, response_schema_hashes[kind])
            for kind in sorted(response_schema_hashes)
        ),
    )
    return replace(
        inherited_cli,
        producer_family=SYNTHESIS_PRODUCER_FAMILY,
        producer_protocol_version="protocol-2.7-workspace-synthesis-v1",
        result_contract_id=SYNTHESIS_RESULT_CONTRACT_ID,
        verifier=VerifierAuthorityV1(
            verifier_id="re-v2-synthesis-verifier",
            verifier_version="1",
            implementation_digest=verifier_implementation_digest,
        ),
        request_renderer=renderer,
    )


def _installed_registry(executor: ExecutorContractEntryV1) -> InstalledAuthorityRegistry:
    renderer = executor.request_renderer
    if not isinstance(renderer, SynthesisRequestRendererAuthorityV1):
        raise Protocol27ExecutionError("synthesis executor renderer is invalid")
    return InstalledAuthorityRegistry(
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
        agent_contracts={"echelon.re-synthesizer": renderer.agent_contract_hash},
        response_schemas={
            item.artifact_kind: item.schema_hash for item in renderer.response_schemas
        },
    )


def build_synthesis_provider_dependencies(
    inputs: ValidatedProtocol27Inputs,
    work_item: SynthesisWorkItemV1,
    retry_diagnostics: tuple[str, ...],
) -> ProviderExecutionDependenciesV1:
    if not isinstance(inputs, ValidatedProtocol27Inputs) or not isinstance(
        work_item, SynthesisWorkItemV1
    ):
        raise Protocol27ExecutionError(
            "synthesis provider dependencies require validated inputs and work"
        )
    try:
        store = ObjectStore(inputs.paths.objects)
        executor = load_canonical_object(
            store.read_blob(work_item.executor_contract_hash),
            synthesis_executor_from_json,
        )
        context = build_synthesis_context(inputs, work_item)
        schema_bytes = store.read_blob(work_item.output_key.response_schema_hash)
        dependencies = ProviderExecutionDependenciesV1(
            executor=executor,
            registry=_installed_registry(executor),
            agent_bytes=inputs.prosaic_authority_bytes,
            context_bytes=canonical_json_bytes(context.to_json_dict()),
            response_schema_bytes=schema_bytes,
            tokenizer=None,
            retry_diagnostics=retry_diagnostics,
        )
        validate_synthesis_provider_content_authority(
            work_item,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            executor,
            content_digest(schema_bytes),
        )
        return dependencies
    except Protocol27ExecutionError:
        raise
    except (Protocol22SchemaError, Protocol22ProviderError, Protocol27ContextError, ReV2LedgerError) as exc:
        raise Protocol27ExecutionError(
            f"synthesis provider authority is unavailable: {exc}"
        ) from exc


def validate_synthesis_provider_content_authority(
    work_item: SynthesisWorkItemV1,
    agent_bytes: bytes,
    context_bytes: bytes,
    executor: ExecutorContractEntryV1,
    schema_hash: str,
) -> SynthesisContextV1:
    renderer = executor.request_renderer
    schema = next(
        (
            item
            for item in renderer.response_schemas
            if item.artifact_kind == work_item.output_key.artifact_kind
        ),
        None,
    ) if isinstance(renderer, SynthesisRequestRendererAuthorityV1) else None
    if (
        not isinstance(work_item, SynthesisWorkItemV1)
        or executor.producer_family != SYNTHESIS_PRODUCER_FAMILY
        or executor.execution_mode != "cli"
        or executor.adapter_id != SHARED_AI_CLI_ADAPTER_ID
        or executor.executor_contract_hash != work_item.executor_contract_hash
        or executor.result_contract_id != SYNTHESIS_RESULT_CONTRACT_ID
        or executor.verifier.verifier_id != work_item.verifier_id
        or executor.verifier.verifier_version != work_item.verifier_version
        or executor.verifier.implementation_digest != work_item.verifier_authority_hash
        or schema is None
        or schema.schema_hash != schema_hash
    ):
        raise Protocol27ExecutionError("synthesis shared CLI content authority is invalid")
    if content_digest(agent_bytes) != renderer.agent_contract_hash:
        raise Protocol27ExecutionError("synthesis Prosaic agent contract hash mismatch")
    artifact = decode_prosaic_agent_bytes(agent_bytes)
    if artifact.frontmatter.get("model_tier") != "strong" or artifact.frontmatter.get(
        "effort"
    ) != "high":
        raise Protocol27ExecutionError("synthesis Prosaic model/effort authority is invalid")
    try:
        context = load_canonical_object(context_bytes, SynthesisContextV1.from_json_dict)
    except Exception as exc:
        raise Protocol27ExecutionError(f"invalid synthesis context: {exc}") from exc
    if (
        context.work_item_id != work_item.work_item_id
        or context.artifact_key_id != work_item.output_key.artifact_key_id
        or context.artifact_kind != work_item.output_key.artifact_kind
        or context.scope != work_item.output_key.scope
        or context.response_schema_hash != schema_hash
    ):
        raise Protocol27ExecutionError(
            "synthesis context does not match work and response authority"
        )
    return context


class Protocol27ExecutionStore(Protocol22ExecutionStore):
    """Reuse durable execution/capture storage with synthesis work validation."""

    def prepare_execution(
        self,
        work_item: WorkItemV2 | SynthesisWorkItemV1,
        attempt_kind: str,
        dependencies,
        fault_hook=None,
    ) -> PreparedExecutionV1:
        if isinstance(work_item, WorkItemV2):
            return super().prepare_execution(
                work_item, attempt_kind, dependencies, fault_hook
            )
        if not isinstance(work_item, SynthesisWorkItemV1) or not isinstance(
            dependencies, ProviderExecutionDependenciesV1
        ):
            raise Protocol27ExecutionError(
                "protocol-2.7 execution requires synthesis work and provider dependencies"
            )
        return self._prepare_synthesis(
            work_item, attempt_kind, dependencies, fault_hook
        )

    def _prepare_synthesis(
        self,
        work_item: SynthesisWorkItemV1,
        attempt_kind: str,
        dependencies: ProviderExecutionDependenciesV1,
        fault_hook,
    ) -> PreparedExecutionV1:
        if (attempt_kind == "initial_generation") != (
            not dependencies.retry_diagnostics
        ):
            raise Protocol27ExecutionError(
                "synthesis retry diagnostics must exist exactly for retry attempts"
            )
        if attempt_kind not in {
            "initial_generation",
            "result_contract_retry",
            "artifact_contract_retry",
        }:
            raise Protocol27ExecutionError("synthesis attempt kind is unsupported")
        executor = dependencies.executor
        validate_synthesis_provider_content_authority(
            work_item,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            executor,
            content_digest(dependencies.response_schema_bytes),
        )
        _validate_synthesis_registry(executor, dependencies.registry)
        dispatch_id = _synthesis_dispatch_id(work_item.work_item_id, attempt_kind)
        agent_hash = self.object_store.put_blob(dependencies.agent_bytes)
        context_hash = self.object_store.put_blob(dependencies.context_bytes)
        self.object_store.put_blob(dependencies.response_schema_bytes)
        reservation = calculate_shared_cli_dispatch_reservation(
            dependencies.agent_bytes,
            dependencies.context_bytes,
            dependencies.response_schema_bytes,
            executor,
            dependencies.retry_diagnostics,
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
            dispatch_id,
            execution_input,
            input_hash,
            None,
            None,
            reservation,
        )

    def validate_prepared_execution(
        self,
        prepared: PreparedExecutionV1,
        work_item: WorkItemV2 | SynthesisWorkItemV1,
        dependencies,
    ) -> PreparedExecutionV1:
        if isinstance(work_item, WorkItemV2):
            return super().validate_prepared_execution(
                prepared, work_item, dependencies
            )
        if not isinstance(work_item, SynthesisWorkItemV1) or not isinstance(
            dependencies, ProviderExecutionDependenciesV1
        ):
            raise Protocol27ExecutionError("prepared synthesis authority is invalid")
        stored = load_canonical_object(
            self.object_store.read_blob(prepared.execution_input_hash),
            ExecutionInputV1.from_json_dict,
        )
        if stored != prepared.execution_input or (
            stored.work_item_id != work_item.work_item_id
            or stored.executor_contract_hash != dependencies.executor.executor_contract_hash
            or stored.dispatch_id != prepared.dispatch_id
            or stored.dispatch_id
            != _synthesis_dispatch_id(work_item.work_item_id, stored.attempt_kind)
        ):
            raise Protocol27ExecutionError("stored synthesis execution input mismatch")
        if (
            stored.agent_contract_hash is None
            or stored.context_bundle_hash is None
            or self.object_store.read_blob(stored.agent_contract_hash)
            != dependencies.agent_bytes
            or self.object_store.read_blob(stored.context_bundle_hash)
            != dependencies.context_bytes
            or (stored.attempt_kind == "initial_generation")
            != (not dependencies.retry_diagnostics)
        ):
            raise Protocol27ExecutionError(
                "stored synthesis execution dependencies mismatch"
            )
        validate_synthesis_provider_content_authority(
            work_item,
            dependencies.agent_bytes,
            dependencies.context_bytes,
            dependencies.executor,
            content_digest(dependencies.response_schema_bytes),
        )
        _validate_synthesis_registry(dependencies.executor, dependencies.registry)
        expected = calculate_shared_cli_dispatch_reservation(
            dependencies.agent_bytes,
            dependencies.context_bytes,
            dependencies.response_schema_bytes,
            dependencies.executor,
            dependencies.retry_diagnostics,
        )
        if prepared.provider_envelope is not None or prepared.reservation != expected:
            raise Protocol27ExecutionError("prepared synthesis reservation mismatch")
        return prepared


def prepare_synthesis_execution(
    store: Protocol27ExecutionStore,
    work_item: SynthesisWorkItemV1,
    dependencies: ProviderExecutionDependenciesV1,
    attempt_kind: str,
) -> PreparedExecutionV1:
    return store.prepare_execution(work_item, attempt_kind, dependencies)


class SquadCliSynthesisRenderer:
    """Render synthesis content and reuse exactly one shared provider instance."""

    def __init__(
        self,
        executors: tuple[ExecutorContractEntryV1, ...],
        *,
        provider_factory: Callable[[], SquadCliProvider],
    ) -> None:
        if not executors or not callable(provider_factory):
            raise Protocol27ExecutionError(
                "synthesis rendering requires executor authority and provider factory"
            )
        if len({item.executor_contract_hash for item in executors}) != len(executors):
            raise Protocol27ExecutionError("synthesis executor contracts must be unique")
        self._executors = {item.executor_contract_hash: item for item in executors}
        for item in executors:
            if item.producer_family != SYNTHESIS_PRODUCER_FAMILY:
                raise Protocol27ExecutionError("renderer received non-synthesis executor")
        self._provider_factory = provider_factory
        self._provider: SquadCliProvider | None = None

    def execute(
        self,
        execution_input: ExecutionInputV1,
        agent_bytes: bytes,
        context_bytes: bytes,
        response_schema_bytes: bytes,
        reservation: DispatchReservationV1,
        candidate_root: Path,
        deadline: float,
        *,
        retry_diagnostics: tuple[str, ...] = (),
    ) -> RawExecutionResultV1:
        executor = self._executors.get(execution_input.executor_contract_hash)
        if executor is None:
            raise Protocol27ExecutionError("synthesis execution input executor mismatch")
        artifact, _context = _validate_renderer_inputs(
            executor,
            execution_input,
            agent_bytes,
            context_bytes,
            response_schema_bytes,
            reservation,
            retry_diagnostics,
        )
        root = _validate_empty_candidate_root(candidate_root)
        if (
            not isinstance(deadline, (int, float))
            or isinstance(deadline, bool)
            or not math.isfinite(deadline)
        ):
            raise Protocol27ExecutionError("synthesis deadline must be finite")
        remaining = min(deadline - time.monotonic(), reservation.active_ms / 1000)
        if remaining <= 0:
            moment = _utc_now()
            return RawExecutionResultV1(
                b"",
                b"deadline_expired\n",
                canonical_normalized_usage_bytes(normalize_shared_provider_usage(0, {})),
                RawExecutionTimingV1(moment, moment, 0),
                "timed_out",
            )
        prompt = _render_synthesis_prompt(
            artifact.body,
            context_bytes.decode("utf-8"),
            response_schema_bytes.decode("utf-8"),
            retry_diagnostics,
        )
        if len(prompt.encode("utf-8")) > reservation.initial_input_tokens:
            raise Protocol27ExecutionError("synthesis prompt exceeds reservation")
        started_at = _utc_now()
        result = self._shared_provider().exec_agent(
            str(root),
            prompt,
            timeout_ms=max(1, int(remaining * 1000)),
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
            normalize_shared_provider_usage(result.token_usage, result.token_usage_details)
        )
        provider_name = result.provider_name.strip() or None
        model_name = result.model_name.strip() or None
        stderr = result.stderr.encode("utf-8", errors="replace")
        if result.timed_out:
            return RawExecutionResultV1(
                b"", stderr or b"request_timed_out\n", usage, timing,
                "timed_out", provider_name, model_name,
            )
        if result.exit_code != 0:
            return RawExecutionResultV1(
                b"", stderr or b"transport_error\n", usage, timing,
                "transport_error", provider_name, model_name,
            )
        if (
            result.echelon_result_validation_reason
            or result.verdict != "DONE"
            or result.state_updates
        ):
            return RawExecutionResultV1(
                b"", b"invalid_response:echelon_result\n", usage, timing,
                "invalid_response", provider_name, model_name,
            )
        return RawExecutionResultV1(
            _RESULT_STDOUT, stderr, usage, timing, "candidate_ready",
            provider_name, model_name,
        )

    def _shared_provider(self) -> SquadCliProvider:
        if self._provider is None:
            self._provider = self._provider_factory()
        return self._provider


def synthesis_candidate_bytes(
    store: Protocol27ExecutionStore,
    closure: ValidatedCaptureClosureV1,
) -> bytes:
    inventory = closure.candidate_inventory
    if inventory is None or len(inventory.entries) != 1:
        raise Protocol27ExecutionError(
            "synthesis candidate inventory must contain exactly one file"
        )
    entry = inventory.entries[0]
    if (
        entry.relative_path != SYNTHESIS_CANDIDATE_FILE
        or entry.object_kind != "regular"
        or entry.content_hash is None
        or entry.byte_count <= 0
    ):
        raise Protocol27ExecutionError("synthesis candidate tree is invalid")
    payload = store.object_store.read_blob(entry.content_hash)
    if len(payload) != entry.byte_count:
        raise Protocol27ExecutionError("synthesis candidate byte count mismatch")
    return payload


def _validate_renderer_inputs(
    executor: ExecutorContractEntryV1,
    execution_input: ExecutionInputV1,
    agent_bytes: bytes,
    context_bytes: bytes,
    response_schema_bytes: bytes,
    reservation: DispatchReservationV1,
    retry_diagnostics: tuple[str, ...],
) -> tuple[ProsaicCommandArtifact, SynthesisContextV1]:
    if not isinstance(execution_input, ExecutionInputV1):
        raise Protocol27ExecutionError("synthesis renderer requires execution input")
    context = load_canonical_object(context_bytes, SynthesisContextV1.from_json_dict)
    # Reconstruct the minimal work binding validated by the renderer. Full graph
    # equality was already established while dependencies were built.
    if (
        execution_input.executor_contract_hash != executor.executor_contract_hash
        or execution_input.agent_contract_hash != content_digest(agent_bytes)
        or execution_input.context_bundle_hash != content_digest(context_bytes)
        or (execution_input.attempt_kind == "initial_generation")
        != (not retry_diagnostics)
    ):
        raise Protocol27ExecutionError("synthesis renderer input authority mismatch")
    renderer = executor.request_renderer
    schema = next(
        (
            item for item in renderer.response_schemas
            if item.artifact_kind == context.artifact_kind
        ),
        None,
    ) if isinstance(renderer, SynthesisRequestRendererAuthorityV1) else None
    if schema is None or schema.schema_hash != content_digest(response_schema_bytes):
        raise Protocol27ExecutionError("synthesis renderer response schema mismatch")
    expected = calculate_shared_cli_dispatch_reservation(
        agent_bytes,
        context_bytes,
        response_schema_bytes,
        executor,
        retry_diagnostics,
    )
    if expected != reservation:
        raise Protocol27ExecutionError("synthesis renderer reservation mismatch")
    return decode_prosaic_agent_bytes(agent_bytes), context


def _render_synthesis_prompt(
    body: str,
    context: str,
    response_schema: str,
    retry_diagnostics: tuple[str, ...],
) -> str:
    return (
        body
        + ("" if body.endswith("\n") else "\n")
        + "\n## Dispatch contract\n"
        + "Write exactly one file named `synthesis.json` in the current working "
        + "directory. It must contain only the authorial JSON payload matching "
        + "the supplied schema. Finish with exactly the required `echelon_result` block.\n\n"
        + "## Bounded context (canonical JSON)\n"
        + context
        + "\n\n## Authorial response schema (canonical JSON)\n"
        + response_schema
        + "\n"
        + render_cli_retry_section(retry_diagnostics)
    )


def _validate_synthesis_registry(
    executor: ExecutorContractEntryV1,
    registry: InstalledAuthorityRegistry,
) -> None:
    renderer = executor.request_renderer
    assert isinstance(renderer, SynthesisRequestRendererAuthorityV1)
    expected = (
        ("executor", executor.adapter_id, executor.executor_implementation_digest),
        ("renderer", renderer.renderer_id, renderer.implementation_digest),
        ("calculator", executor.reservation_calculator.calculator_id, executor.reservation_calculator.implementation_digest),
        ("normalizer", executor.token_accounting.normalization_id, executor.token_accounting.implementation_digest),
        ("verifier", executor.verifier.verifier_id, executor.verifier.implementation_digest),
        ("agent_contract", "echelon.re-synthesizer", renderer.agent_contract_hash),
    )
    expected += tuple(
        ("response_schema", item.artifact_kind, item.schema_hash)
        for item in renderer.response_schemas
    )
    mismatches = [
        f"{kind}:{authority_id}"
        for kind, authority_id, digest in expected
        if registry.digest_for(kind, authority_id) != digest
    ]
    if mismatches:
        raise Protocol27ExecutionError(
            "installed synthesis authority mismatch: " + ", ".join(mismatches)
        )


def _synthesis_dispatch_id(work_item_id: str, attempt_kind: str) -> str:
    payload = canonical_json_bytes(
        {"attempt_kind": attempt_kind, "work_item_id": work_item_id}
    )
    return "dispatch-" + hashlib.sha256(payload).hexdigest()


__all__ = (
    "Protocol27ExecutionError",
    "Protocol27ExecutionStore",
    "SYNTHESIS_CANDIDATE_FILE",
    "SYNTHESIS_PRODUCER_FAMILY",
    "SYNTHESIS_RENDERER_ID",
    "SquadCliSynthesisRenderer",
    "SynthesisRequestRendererAuthorityV1",
    "SynthesisResponseSchemaReferenceV1",
    "build_synthesis_provider_dependencies",
    "compose_synthesis_executor",
    "prepare_synthesis_execution",
    "synthesis_candidate_bytes",
    "synthesis_executor_from_json",
    "validate_synthesis_provider_content_authority",
)
