"""Aggregate-safe workspace renderer authority for protocol-2.7 synthesis."""

from __future__ import annotations

from dataclasses import replace

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_22.execution import ProviderExecutionDependenciesV1
from harness.re_v2.protocol_22.cli_provider import _render_prompt
from harness.re_v2.protocol_22.executors import (
    ExecutorContractEntryV1,
    ExecutorLimitsV1,
    ReservationCalculatorAuthorityV1,
    TokenAccountingAuthorityV1,
    VerifierAuthorityV1,
)
from harness.re_v2.protocol_22.provider import (
    Protocol22ProviderError,
    decode_prosaic_agent_bytes,
)
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    load_canonical_object,
    safe_id,
)

from .context import Protocol27ContextError
from .context_v2 import build_synthesis_context_v2
from .execution import (
    Protocol27ExecutionError,
    SYNTHESIS_GENERATED_KINDS,
    SynthesisRequestRendererAuthorityV1,
    SynthesisResponseSchemaReferenceV1,
    _installed_registry,
    compose_synthesis_executor,
    validate_synthesis_provider_content_authority,
)
from .inputs import ValidatedProtocol27Inputs
from .model import SynthesisWorkItemV1


SYNTHESIS_RENDERER_V2_ID = "synthesis-renderer-v2"


class SynthesisRequestRendererAuthorityV2(SynthesisRequestRendererAuthorityV1):
    """Renderer subtype pinning aggregate-safe context construction."""

    def __post_init__(self) -> None:
        try:
            safe_id(self.renderer_id, "synthesis renderer ID")
            safe_id(self.renderer_version, "synthesis renderer version")
            digest_value(self.implementation_digest, "synthesis renderer implementation")
            digest_value(self.agent_contract_hash, "synthesis renderer agent contract")
        except Protocol22SchemaError as exc:
            raise Protocol27ExecutionError(str(exc)) from exc
        if self.renderer_id != SYNTHESIS_RENDERER_V2_ID or self.renderer_version != "2":
            raise Protocol27ExecutionError("aggregate-safe synthesis renderer is unsupported")
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
    def from_json_dict(cls, value: object) -> "SynthesisRequestRendererAuthorityV2":
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


def synthesis_executor_v2_from_json(value: object) -> ExecutorContractEntryV1:
    raw = exact_object(
        value,
        frozenset(ExecutorContractEntryV1.FIELDS),
        "aggregate-safe synthesis executor entry",
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
        request_renderer=SynthesisRequestRendererAuthorityV2.from_json_dict(
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


def compose_synthesis_executor_v2(
    inherited_cli: ExecutorContractEntryV1,
    *,
    agent_contract_hash: str,
    response_schema_hashes: dict[str, str],
    renderer_implementation_digest: str,
    verifier_implementation_digest: str,
) -> ExecutorContractEntryV1:
    base = compose_synthesis_executor(
        inherited_cli,
        agent_contract_hash=agent_contract_hash,
        response_schema_hashes=response_schema_hashes,
        renderer_implementation_digest=renderer_implementation_digest,
        verifier_implementation_digest=verifier_implementation_digest,
    )
    return promote_synthesis_executor_v2(
        base,
        renderer_implementation_digest=renderer_implementation_digest,
    )


def promote_synthesis_executor_v2(
    base: ExecutorContractEntryV1,
    *,
    renderer_implementation_digest: str,
) -> ExecutorContractEntryV1:
    """Promote an authenticated synthesis executor to aggregate-safe rendering."""
    renderer = base.request_renderer
    assert isinstance(renderer, SynthesisRequestRendererAuthorityV1)
    return replace(
        base,
        request_renderer=SynthesisRequestRendererAuthorityV2(
            renderer_id=SYNTHESIS_RENDERER_V2_ID,
            renderer_version="2",
            implementation_digest=renderer_implementation_digest,
            agent_contract_hash=renderer.agent_contract_hash,
            response_schemas=renderer.response_schemas,
        ),
    )


def uses_synthesis_renderer_v2(
    inputs: ValidatedProtocol27Inputs,
    work_item: SynthesisWorkItemV1,
) -> bool:
    store = ObjectStore(inputs.paths.objects)
    try:
        raw = __import__("json").loads(store.read_blob(work_item.executor_contract_hash))
    except Exception as exc:
        raise Protocol27ExecutionError(
            f"synthesis executor authority is unavailable: {exc}"
        ) from exc
    renderer = raw.get("request_renderer") if isinstance(raw, dict) else None
    return isinstance(renderer, dict) and renderer.get("renderer_id") == SYNTHESIS_RENDERER_V2_ID


def build_synthesis_provider_dependencies_v2(
    inputs: ValidatedProtocol27Inputs,
    work_item: SynthesisWorkItemV1,
    retry_diagnostics: tuple[str, ...],
) -> ProviderExecutionDependenciesV1:
    if work_item.output_key.scope.kind != "workspace":
        raise Protocol27ExecutionError(
            "aggregate-safe synthesis renderer is restricted to workspace scope"
        )
    try:
        store = ObjectStore(inputs.paths.objects)
        executor = load_canonical_object(
            store.read_blob(work_item.executor_contract_hash),
            synthesis_executor_v2_from_json,
        )
        schema_bytes = store.read_blob(work_item.output_key.response_schema_hash)
        artifact = decode_prosaic_agent_bytes(inputs.prosaic_authority_bytes)
        response_schema = schema_bytes.decode("utf-8", errors="strict")
        empty_prompt_bytes = len(
            _render_prompt(
                artifact.body,
                "",
                response_schema,
                retry_diagnostics,
            ).encode("utf-8")
        )
        context_limit = (
            executor.limits.max_billable_tokens_per_dispatch - empty_prompt_bytes
        )
        context = build_synthesis_context_v2(
            inputs,
            work_item,
            aggregate_byte_limit=context_limit,
        )
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
    except (
        Protocol22SchemaError,
        Protocol22ProviderError,
        Protocol27ContextError,
        ReV2LedgerError,
    ) as exc:
        raise Protocol27ExecutionError(
            f"synthesis provider authority is unavailable: {exc}"
        ) from exc


__all__ = (
    "SYNTHESIS_RENDERER_V2_ID",
    "build_synthesis_provider_dependencies_v2",
    "compose_synthesis_executor_v2",
    "synthesis_executor_v2_from_json",
    "uses_synthesis_renderer_v2",
)
