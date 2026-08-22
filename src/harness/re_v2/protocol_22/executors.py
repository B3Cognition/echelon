"""Closed bounded executor contracts for protocol 2.2."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import ipaddress
from pathlib import PurePosixPath
import re
from typing import ClassVar, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from harness.config import HarnessConfig, ReV2BaselineHeaderConfig
from harness.re_v2.canonical import content_digest

from .authorities import InstalledAuthorityRegistry, Protocol22AuthorityError
from .model import ProviderGenerationV1
from .response_schemas import response_schema_hash
from .schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    nonnegative_int,
    optional_text,
    positive_int,
    safe_id,
    text_value,
)


ExecutionModeV1 = Literal["in_process", "cli", "api"]
RevisionAuthorityV1 = Literal[
    "immutable_model_id", "provider_resolved_revision"
]

_EXECUTION_MODES = frozenset({"in_process", "cli", "api"})
_REVISION_AUTHORITIES = frozenset(
    {"immutable_model_id", "provider_resolved_revision"}
)
_HEADER_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_CREDENTIAL_HEADER_MARKERS = (
    "api-key",
    "apikey",
    "auth-token",
    "credential",
    "secret",
    "access-token",
)
_CREDENTIAL_HEADER_NAMES = frozenset(
    {"authorization", "cookie", "proxy-authorization", "set-cookie"}
)
_MAX_BILLABLE_TOKENS_PER_DISPATCH = 262_144
_IN_PROCESS_ACTIVE_MS = 300_000

IN_PROCESS_ADAPTER_ID = "re-v2-in-process-v1"
BOUNDED_API_ADAPTER_ID = "bounded-api-baseline-v1"
COMPACT_RENDERER_ID = "compact-baseline-renderer-v1"
CONSERVATIVE_TOKENIZER_ID = "utf8-byte-upper-bound-v1"
IN_PROCESS_CALCULATOR_ID = "bounded-in-process-v1"
DISPATCH_CALCULATOR_ID = "bounded-dispatch-v1"
ZERO_USAGE_NORMALIZER_ID = "deterministic-zero-usage-v1"
OPENAI_USAGE_NORMALIZER_ID = "openai-usage-v1"
BASELINER_AGENT_ID = "echelon.re-baseliner"

_DETERMINISTIC_PROTOCOLS = {
    "context-bundle": "context-bundle-v1",
    "evidence-pack": "evidence-pack-v1",
    "inventory": "inventory-v1",
    "partition": "partition-v1",
    "source-baseline-root": "source-baseline-root-v1",
}
_GOAL_FAMILIES = {
    "inventory": ("evidence-pack", "inventory", "partition"),
    "baseline": (
        "context-bundle",
        "evidence-pack",
        "inventory",
        "partition",
        "source-baseline-root",
    ),
}


class Protocol22ExecutorError(Protocol22SchemaError):
    """Raised when an executor cannot prove the protocol-2.2 contract."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol22ExecutorError:
        raise
    except Protocol22SchemaError as exc:
        raise Protocol22ExecutorError(str(exc)) from exc


def _exact(value: object, fields: tuple[str, ...], label: str) -> Mapping[str, object]:
    return _schema(exact_object, value, frozenset(fields), label)


def _safe_id(value: object, field: str) -> str:
    return _schema(safe_id, value, field)


def _text(value: object, field: str) -> str:
    return _schema(text_value, value, field)


def _digest(value: object, field: str) -> str:
    return _schema(digest_value, value, field)


def _positive(value: object, field: str) -> int:
    return _schema(positive_int, value, field)


def _nonnegative(value: object, field: str) -> int:
    return _schema(nonnegative_int, value, field)


def _choice(value: object, choices: frozenset[str], field: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise Protocol22ExecutorError(f"{field} must be one of {sorted(choices)}")
    return value


def _optional_id(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, field)


@dataclass(frozen=True, slots=True)
class NonSecretHeaderV1:
    name: str
    value: str

    FIELDS: ClassVar[tuple[str, ...]] = ("name", "value")

    def __post_init__(self) -> None:
        name = _text(self.name, "NonSecretHeaderV1.name")
        value = _text(self.value, "NonSecretHeaderV1.value")
        if not _HEADER_NAME_RE.fullmatch(name) or name.lower() != name:
            raise Protocol22ExecutorError(
                "non-secret header names must be canonical lowercase HTTP names"
            )
        if (
            name in _CREDENTIAL_HEADER_NAMES
            or any(marker in name for marker in _CREDENTIAL_HEADER_MARKERS)
        ):
            raise Protocol22ExecutorError(
                f"credential-bearing header is forbidden: {name}"
            )
        if value.strip() != value or any(character in value for character in "\r\n\x00"):
            raise Protocol22ExecutorError(
                f"non-secret header {name!r} has a noncanonical value"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_json_dict(cls, value: object) -> "NonSecretHeaderV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(name=raw["name"], value=raw["value"])


@dataclass(frozen=True, slots=True)
class ApiTransportAuthorityV1:
    authority_schema: Literal["api-transport-authority-v1"]
    api_protocol_id: Literal["openai-chat-completions"]
    api_protocol_version: Literal["1"]
    base_url: str
    request_path: str
    non_secret_headers: tuple[NonSecretHeaderV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "authority_schema",
        "api_protocol_id",
        "api_protocol_version",
        "base_url",
        "request_path",
        "non_secret_headers",
    )

    def __post_init__(self) -> None:
        if self.authority_schema != "api-transport-authority-v1":
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1.authority_schema is unsupported"
            )
        if self.api_protocol_id != "openai-chat-completions":
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1.api_protocol_id is unsupported"
            )
        if self.api_protocol_version != "1":
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1.api_protocol_version must be '1'"
            )
        _validate_base_url(self.base_url)
        _validate_request_path(self.request_path)
        if not isinstance(self.non_secret_headers, (list, tuple)):
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1.non_secret_headers must be an array"
            )
        headers: list[NonSecretHeaderV1] = []
        for header in self.non_secret_headers:
            headers.append(
                header
                if isinstance(header, NonSecretHeaderV1)
                else NonSecretHeaderV1.from_json_dict(header)
            )
        names = tuple(header.name for header in headers)
        if names != tuple(sorted(set(names))):
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1 headers must be sorted and unique by name"
            )
        object.__setattr__(self, "non_secret_headers", tuple(headers))

    def to_json_dict(self) -> dict[str, object]:
        return {
            "authority_schema": self.authority_schema,
            "api_protocol_id": self.api_protocol_id,
            "api_protocol_version": self.api_protocol_version,
            "base_url": self.base_url,
            "request_path": self.request_path,
            "non_secret_headers": [
                header.to_json_dict() for header in self.non_secret_headers
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ApiTransportAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        headers = raw["non_secret_headers"]
        if not isinstance(headers, (list, tuple)):
            raise Protocol22ExecutorError(
                "ApiTransportAuthorityV1.non_secret_headers must be an array"
            )
        return cls(
            authority_schema=raw["authority_schema"],
            api_protocol_id=raw["api_protocol_id"],
            api_protocol_version=raw["api_protocol_version"],
            base_url=raw["base_url"],
            request_path=raw["request_path"],
            non_secret_headers=tuple(
                NonSecretHeaderV1.from_json_dict(header) for header in headers
            ),
        )


@dataclass(frozen=True, slots=True)
class ModelAuthorityV1:
    model_id: str
    model_revision: str
    revision_authority: RevisionAuthorityV1
    reasoning_effort: str | None

    FIELDS: ClassVar[tuple[str, ...]] = (
        "model_id",
        "model_revision",
        "revision_authority",
        "reasoning_effort",
    )

    def __post_init__(self) -> None:
        _text(self.model_id, "ModelAuthorityV1.model_id")
        _text(self.model_revision, "ModelAuthorityV1.model_revision")
        _choice(
            self.revision_authority,
            _REVISION_AUTHORITIES,
            "ModelAuthorityV1.revision_authority",
        )
        try:
            optional_text(self.reasoning_effort, "ModelAuthorityV1.reasoning_effort")
        except Protocol22SchemaError as exc:
            raise Protocol22ExecutorError(str(exc)) from exc
        if (
            self.revision_authority == "immutable_model_id"
            and self.model_revision != self.model_id
        ):
            raise Protocol22ExecutorError(
                "immutable model authority requires model_revision to equal model_id"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ModelAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ResponseSchemaReferenceV1:
    artifact_kind: Literal["domain-baseline", "source-overview"]
    schema_hash: str

    FIELDS: ClassVar[tuple[str, ...]] = ("artifact_kind", "schema_hash")

    def __post_init__(self) -> None:
        _choice(
            self.artifact_kind,
            frozenset({"domain-baseline", "source-overview"}),
            "ResponseSchemaReferenceV1.artifact_kind",
        )
        _digest(self.schema_hash, "ResponseSchemaReferenceV1.schema_hash")

    def to_json_dict(self) -> dict[str, object]:
        return {"artifact_kind": self.artifact_kind, "schema_hash": self.schema_hash}

    @classmethod
    def from_json_dict(cls, value: object) -> "ResponseSchemaReferenceV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(artifact_kind=raw["artifact_kind"], schema_hash=raw["schema_hash"])


@dataclass(frozen=True, slots=True)
class RequestRendererAuthorityV1:
    renderer_id: str
    renderer_version: str
    implementation_digest: str
    agent_contract_hash: str
    response_schemas: tuple[ResponseSchemaReferenceV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "renderer_id",
        "renderer_version",
        "implementation_digest",
        "agent_contract_hash",
        "response_schemas",
    )

    def __post_init__(self) -> None:
        _safe_id(self.renderer_id, "RequestRendererAuthorityV1.renderer_id")
        _safe_id(self.renderer_version, "RequestRendererAuthorityV1.renderer_version")
        _digest(
            self.implementation_digest,
            "RequestRendererAuthorityV1.implementation_digest",
        )
        _digest(
            self.agent_contract_hash,
            "RequestRendererAuthorityV1.agent_contract_hash",
        )
        if not isinstance(self.response_schemas, (list, tuple)) or any(
            not isinstance(schema, ResponseSchemaReferenceV1)
            for schema in self.response_schemas
        ):
            raise Protocol22ExecutorError(
                "RequestRendererAuthorityV1.response_schemas must contain closed schema references"
            )
        schemas = tuple(self.response_schemas)
        kinds = tuple(schema.artifact_kind for schema in schemas)
        if kinds != ("domain-baseline", "source-overview"):
            raise Protocol22ExecutorError(
                "compact renderer response schemas must be exactly domain-baseline then source-overview"
            )
        object.__setattr__(self, "response_schemas", schemas)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "renderer_id": self.renderer_id,
            "renderer_version": self.renderer_version,
            "implementation_digest": self.implementation_digest,
            "agent_contract_hash": self.agent_contract_hash,
            "response_schemas": [
                schema.to_json_dict() for schema in self.response_schemas
            ],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "RequestRendererAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        schemas = raw["response_schemas"]
        if not isinstance(schemas, (list, tuple)):
            raise Protocol22ExecutorError(
                "RequestRendererAuthorityV1.response_schemas must be an array"
            )
        return cls(
            renderer_id=raw["renderer_id"],
            renderer_version=raw["renderer_version"],
            implementation_digest=raw["implementation_digest"],
            agent_contract_hash=raw["agent_contract_hash"],
            response_schemas=tuple(
                ResponseSchemaReferenceV1.from_json_dict(schema) for schema in schemas
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestTokenizerAuthorityV1:
    tokenizer_id: str
    tokenizer_version: str
    implementation_digest: str
    fallback_estimator_id: Literal["utf8-byte-upper-bound-v1"]
    fixed_framing_byte_upper_bound: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "tokenizer_id",
        "tokenizer_version",
        "implementation_digest",
        "fallback_estimator_id",
        "fixed_framing_byte_upper_bound",
    )

    def __post_init__(self) -> None:
        _safe_id(self.tokenizer_id, "RequestTokenizerAuthorityV1.tokenizer_id")
        _safe_id(self.tokenizer_version, "RequestTokenizerAuthorityV1.tokenizer_version")
        _digest(
            self.implementation_digest,
            "RequestTokenizerAuthorityV1.implementation_digest",
        )
        if self.fallback_estimator_id != "utf8-byte-upper-bound-v1":
            raise Protocol22ExecutorError(
                "RequestTokenizerAuthorityV1 fallback estimator is unsupported"
            )
        _nonnegative(
            self.fixed_framing_byte_upper_bound,
            "RequestTokenizerAuthorityV1.fixed_framing_byte_upper_bound",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "RequestTokenizerAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ReservationCalculatorAuthorityV1:
    calculator_id: Literal["bounded-dispatch-v1", "bounded-in-process-v1"]
    calculator_version: int
    implementation_digest: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "calculator_id",
        "calculator_version",
        "implementation_digest",
    )

    def __post_init__(self) -> None:
        _choice(
            self.calculator_id,
            frozenset({DISPATCH_CALCULATOR_ID, IN_PROCESS_CALCULATOR_ID}),
            "ReservationCalculatorAuthorityV1.calculator_id",
        )
        if self.calculator_version != 1 or isinstance(self.calculator_version, bool):
            raise Protocol22ExecutorError(
                "ReservationCalculatorAuthorityV1.calculator_version must be 1"
            )
        _digest(
            self.implementation_digest,
            "ReservationCalculatorAuthorityV1.implementation_digest",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ReservationCalculatorAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class TokenAccountingAuthorityV1:
    normalization_id: str
    normalization_version: str
    implementation_digest: str
    unknown_class_policy: Literal["untrusted"]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "normalization_id",
        "normalization_version",
        "implementation_digest",
        "unknown_class_policy",
    )

    def __post_init__(self) -> None:
        _safe_id(self.normalization_id, "TokenAccountingAuthorityV1.normalization_id")
        _safe_id(
            self.normalization_version,
            "TokenAccountingAuthorityV1.normalization_version",
        )
        _digest(
            self.implementation_digest,
            "TokenAccountingAuthorityV1.implementation_digest",
        )
        if self.unknown_class_policy != "untrusted":
            raise Protocol22ExecutorError(
                "TokenAccountingAuthorityV1.unknown_class_policy must be untrusted"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "TokenAccountingAuthorityV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExecutorLimitsV1:
    provider_context_tokens: int | None
    max_internal_calls: int
    max_followup_input_tokens_per_call: int
    max_completion_tokens_per_call: int
    max_tool_rounds: int
    max_tool_result_bytes_per_round: int
    max_billable_tokens_per_dispatch: int
    max_active_ms_per_dispatch: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "provider_context_tokens",
        "max_internal_calls",
        "max_followup_input_tokens_per_call",
        "max_completion_tokens_per_call",
        "max_tool_rounds",
        "max_tool_result_bytes_per_round",
        "max_billable_tokens_per_dispatch",
        "max_active_ms_per_dispatch",
    )

    def __post_init__(self) -> None:
        if self.provider_context_tokens is not None:
            _positive(
                self.provider_context_tokens,
                "ExecutorLimitsV1.provider_context_tokens",
            )
        for field in self.FIELDS[1:-1]:
            _nonnegative(getattr(self, field), f"ExecutorLimitsV1.{field}")
        _positive(
            self.max_active_ms_per_dispatch,
            "ExecutorLimitsV1.max_active_ms_per_dispatch",
        )

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutorLimitsV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class ExecutorContractEntryV1:
    producer_family: str
    execution_mode: ExecutionModeV1
    provider_id: str | None
    api_transport: ApiTransportAuthorityV1 | None
    adapter_id: str
    adapter_contract_version: str
    executor_implementation_digest: str
    producer_protocol_version: str
    result_contract_id: str
    model: ModelAuthorityV1 | None
    request_renderer: RequestRendererAuthorityV1 | None
    request_tokenizer: RequestTokenizerAuthorityV1 | None
    generation: ProviderGenerationV1 | None
    reservation_calculator: ReservationCalculatorAuthorityV1
    token_accounting: TokenAccountingAuthorityV1
    limits: ExecutorLimitsV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "producer_family",
        "execution_mode",
        "provider_id",
        "api_transport",
        "adapter_id",
        "adapter_contract_version",
        "executor_implementation_digest",
        "producer_protocol_version",
        "result_contract_id",
        "model",
        "request_renderer",
        "request_tokenizer",
        # The reviewed design required immutable sampling but omitted its slot.
        # Protocol 2.2 pins the already-closed generation value here so recovery
        # never reads temperature/top-p/seed from mutable configuration.
        "generation",
        "reservation_calculator",
        "token_accounting",
        "limits",
    )

    def __post_init__(self) -> None:
        _safe_id(self.producer_family, "ExecutorContractEntryV1.producer_family")
        mode = _choice(
            self.execution_mode,
            _EXECUTION_MODES,
            "ExecutorContractEntryV1.execution_mode",
        )
        _optional_id(self.provider_id, "ExecutorContractEntryV1.provider_id")
        _safe_id(self.adapter_id, "ExecutorContractEntryV1.adapter_id")
        _safe_id(
            self.adapter_contract_version,
            "ExecutorContractEntryV1.adapter_contract_version",
        )
        _digest(
            self.executor_implementation_digest,
            "ExecutorContractEntryV1.executor_implementation_digest",
        )
        _safe_id(
            self.producer_protocol_version,
            "ExecutorContractEntryV1.producer_protocol_version",
        )
        _safe_id(self.result_contract_id, "ExecutorContractEntryV1.result_contract_id")
        nested_authorities = (
            ("api_transport", self.api_transport, ApiTransportAuthorityV1),
            ("model", self.model, ModelAuthorityV1),
            ("request_renderer", self.request_renderer, RequestRendererAuthorityV1),
            ("request_tokenizer", self.request_tokenizer, RequestTokenizerAuthorityV1),
            ("generation", self.generation, ProviderGenerationV1),
        )
        for field, value, expected_type in nested_authorities:
            if value is not None and not isinstance(value, expected_type):
                raise Protocol22ExecutorError(
                    f"ExecutorContractEntryV1.{field} is invalid"
                )
        if not isinstance(
            self.reservation_calculator, ReservationCalculatorAuthorityV1
        ):
            raise Protocol22ExecutorError(
                "ExecutorContractEntryV1.reservation_calculator is invalid"
            )
        if not isinstance(self.token_accounting, TokenAccountingAuthorityV1):
            raise Protocol22ExecutorError(
                "ExecutorContractEntryV1.token_accounting is invalid"
            )
        if not isinstance(self.limits, ExecutorLimitsV1):
            raise Protocol22ExecutorError("ExecutorContractEntryV1.limits is invalid")

        if mode == "in_process":
            forbidden = (
                self.provider_id,
                self.api_transport,
                self.model,
                self.request_renderer,
                self.request_tokenizer,
                self.generation,
            )
            if any(value is not None for value in forbidden):
                raise Protocol22ExecutorError(
                    "in_process executor contracts cannot contain provider state"
                )
            if self.reservation_calculator.calculator_id != IN_PROCESS_CALCULATOR_ID:
                raise Protocol22ExecutorError(
                    "in_process executor requires bounded-in-process-v1"
                )
            if self.limits.provider_context_tokens is not None or any(
                getattr(self.limits, field) != 0
                for field in ExecutorLimitsV1.FIELDS[1:-1]
            ):
                raise Protocol22ExecutorError(
                    "in_process executor token/tool/call limits must be zero"
                )
            return

        if self.provider_id is None:
            raise Protocol22ExecutorError(
                f"{mode} executor requires a provider_id"
            )
        for field in ("model", "request_renderer", "request_tokenizer", "generation"):
            if getattr(self, field) is None:
                raise Protocol22ExecutorError(f"{mode} executor requires {field}")
        if self.reservation_calculator.calculator_id != DISPATCH_CALCULATOR_ID:
            raise Protocol22ExecutorError(
                f"{mode} executor requires bounded-dispatch-v1"
            )
        if self.limits.provider_context_tokens is None:
            raise Protocol22ExecutorError(f"{mode} executor requires a context window")
        if (
            self.limits.max_internal_calls <= 0
            or self.limits.max_completion_tokens_per_call <= 0
            or self.limits.max_billable_tokens_per_dispatch <= 0
        ):
            raise Protocol22ExecutorError(
                f"{mode} executor requires positive bounded call, completion, and billable limits"
            )
        if self.limits.max_billable_tokens_per_dispatch > _MAX_BILLABLE_TOKENS_PER_DISPATCH:
            raise Protocol22ExecutorError(
                "executor billable ceiling exceeds the 262144-token safety limit"
            )
        generation = self.generation
        if generation is None:  # Kept explicit for fail-closed optimized execution.
            raise Protocol22ExecutorError(f"{mode} executor requires generation")
        if (
            generation.max_completion_tokens
            != self.limits.max_completion_tokens_per_call
        ):
            raise Protocol22ExecutorError(
                "generation completion cap must equal executor completion limit"
            )
        if mode == "api":
            if not isinstance(self.api_transport, ApiTransportAuthorityV1):
                raise Protocol22ExecutorError("api executor requires api_transport")
        elif self.api_transport is not None:
            raise Protocol22ExecutorError("cli executor requires null api_transport")
        if self.adapter_id == BOUNDED_API_ADAPTER_ID and (
            mode != "api"
            or self.limits.max_internal_calls != 1
            or self.limits.max_followup_input_tokens_per_call != 0
            or self.limits.max_tool_rounds != 0
            or self.limits.max_tool_result_bytes_per_round != 0
        ):
            raise Protocol22ExecutorError(
                "bounded-api-baseline-v1 requires one call, no follow-up, and no tools"
            )

    @property
    def executor_contract_hash(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "producer_family": self.producer_family,
            "execution_mode": self.execution_mode,
            "provider_id": self.provider_id,
            "api_transport": (
                self.api_transport.to_json_dict()
                if self.api_transport is not None
                else None
            ),
            "adapter_id": self.adapter_id,
            "adapter_contract_version": self.adapter_contract_version,
            "executor_implementation_digest": self.executor_implementation_digest,
            "producer_protocol_version": self.producer_protocol_version,
            "result_contract_id": self.result_contract_id,
            "model": self.model.to_json_dict() if self.model is not None else None,
            "request_renderer": (
                self.request_renderer.to_json_dict()
                if self.request_renderer is not None
                else None
            ),
            "request_tokenizer": (
                self.request_tokenizer.to_json_dict()
                if self.request_tokenizer is not None
                else None
            ),
            "generation": (
                self.generation.to_json_dict() if self.generation is not None else None
            ),
            "reservation_calculator": self.reservation_calculator.to_json_dict(),
            "token_accounting": self.token_accounting.to_json_dict(),
            "limits": self.limits.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutorContractEntryV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(
            producer_family=raw["producer_family"],
            execution_mode=raw["execution_mode"],
            provider_id=raw["provider_id"],
            api_transport=(
                ApiTransportAuthorityV1.from_json_dict(raw["api_transport"])
                if raw["api_transport"] is not None
                else None
            ),
            adapter_id=raw["adapter_id"],
            adapter_contract_version=raw["adapter_contract_version"],
            executor_implementation_digest=raw["executor_implementation_digest"],
            producer_protocol_version=raw["producer_protocol_version"],
            result_contract_id=raw["result_contract_id"],
            model=(
                ModelAuthorityV1.from_json_dict(raw["model"])
                if raw["model"] is not None
                else None
            ),
            request_renderer=(
                RequestRendererAuthorityV1.from_json_dict(raw["request_renderer"])
                if raw["request_renderer"] is not None
                else None
            ),
            request_tokenizer=(
                RequestTokenizerAuthorityV1.from_json_dict(raw["request_tokenizer"])
                if raw["request_tokenizer"] is not None
                else None
            ),
            generation=(
                ProviderGenerationV1.from_json_dict(raw["generation"])
                if raw["generation"] is not None
                else None
            ),
            reservation_calculator=ReservationCalculatorAuthorityV1.from_json_dict(
                raw["reservation_calculator"]
            ),
            token_accounting=TokenAccountingAuthorityV1.from_json_dict(
                raw["token_accounting"]
            ),
            limits=ExecutorLimitsV1.from_json_dict(raw["limits"]),
        )


@dataclass(frozen=True, slots=True)
class ExecutorContractCatalogV1:
    schema_version: int
    entries: tuple[ExecutorContractEntryV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("schema_version", "entries")

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22ExecutorError(
                "ExecutorContractCatalogV1.schema_version must be 1"
            )
        if not isinstance(self.entries, (list, tuple)) or any(
            not isinstance(entry, ExecutorContractEntryV1) for entry in self.entries
        ):
            raise Protocol22ExecutorError(
                "ExecutorContractCatalogV1.entries must contain closed executor entries"
            )
        entries = tuple(self.entries)
        if not entries:
            raise Protocol22ExecutorError(
                "ExecutorContractCatalogV1.entries must be nonempty"
            )
        families = tuple(entry.producer_family for entry in entries)
        if families != tuple(sorted(set(families))):
            raise Protocol22ExecutorError(
                "ExecutorContractCatalogV1.entries must be sorted and unique by producer_family"
            )
        object.__setattr__(self, "entries", entries)
        _validate_shared_authorities(entries)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def entry_for(self, producer_family: str) -> ExecutorContractEntryV1:
        for entry in self.entries:
            if entry.producer_family == producer_family:
                return entry
        raise Protocol22ExecutorError(
            f"executor catalog has no producer family {producer_family!r}"
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_json_dict() for entry in self.entries],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "ExecutorContractCatalogV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        entries = raw["entries"]
        if not isinstance(entries, (list, tuple)):
            raise Protocol22ExecutorError(
                "ExecutorContractCatalogV1.entries must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            entries=tuple(
                ExecutorContractEntryV1.from_json_dict(entry) for entry in entries
            ),
        )


def resolve_executor_catalog(
    config: HarnessConfig,
    goal: Literal["baseline", "inventory"] | str,
    registry: InstalledAuthorityRegistry,
) -> ExecutorContractCatalogV1:
    """Resolve one immutable executor catalog from effective harness config."""
    if not isinstance(config, HarnessConfig):
        raise Protocol22ExecutorError("executor resolution requires HarnessConfig")
    if goal not in _GOAL_FAMILIES:
        raise Protocol22ExecutorError("executor goal must be baseline or inventory")
    if not isinstance(registry, InstalledAuthorityRegistry):
        raise Protocol22ExecutorError(
            "executor resolution requires InstalledAuthorityRegistry"
        )
    entries = [
        _in_process_entry(family, registry) for family in _GOAL_FAMILIES[goal]
    ]
    if goal == "baseline":
        entries.append(_bounded_api_entry(config, registry))
    return ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(sorted(entries, key=lambda entry: entry.producer_family)),
    )


def _in_process_entry(
    producer_family: str,
    registry: InstalledAuthorityRegistry,
) -> ExecutorContractEntryV1:
    return ExecutorContractEntryV1(
        producer_family=producer_family,
        execution_mode="in_process",
        provider_id=None,
        api_transport=None,
        adapter_id=IN_PROCESS_ADAPTER_ID,
        adapter_contract_version="1",
        executor_implementation_digest=_require(
            registry, "executor", IN_PROCESS_ADAPTER_ID
        ),
        producer_protocol_version=_DETERMINISTIC_PROTOCOLS[producer_family],
        result_contract_id="deterministic-artifact-v1",
        model=None,
        request_renderer=None,
        request_tokenizer=None,
        generation=None,
        reservation_calculator=ReservationCalculatorAuthorityV1(
            calculator_id=IN_PROCESS_CALCULATOR_ID,
            calculator_version=1,
            implementation_digest=_require(
                registry, "calculator", IN_PROCESS_CALCULATOR_ID
            ),
        ),
        token_accounting=TokenAccountingAuthorityV1(
            normalization_id=ZERO_USAGE_NORMALIZER_ID,
            normalization_version="1",
            implementation_digest=_require(
                registry, "normalizer", ZERO_USAGE_NORMALIZER_ID
            ),
            unknown_class_policy="untrusted",
        ),
        limits=ExecutorLimitsV1(
            provider_context_tokens=None,
            max_internal_calls=0,
            max_followup_input_tokens_per_call=0,
            max_completion_tokens_per_call=0,
            max_tool_rounds=0,
            max_tool_result_bytes_per_round=0,
            max_billable_tokens_per_dispatch=0,
            max_active_ms_per_dispatch=_IN_PROCESS_ACTIVE_MS,
        ),
    )


def _bounded_api_entry(
    config: HarnessConfig,
    registry: InstalledAuthorityRegistry,
) -> ExecutorContractEntryV1:
    llm = config.llm
    capability = llm.re_v2_baseline
    if llm.cli != "openai-compatible":
        raise Protocol22ExecutorError(
            f"LLM backend {llm.cli!r} cannot prove bounded-api-baseline-v1; "
            "agentic CLI execution is ineligible for protocol-2.2 compact baselines"
        )
    if not llm.base_url:
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires an API base_url"
        )
    if not llm.model:
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires an explicit model ID"
        )
    if not capability.model_revision:
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires an exact model revision"
        )
    if capability.revision_authority not in _REVISION_AUTHORITIES:
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 model revision authority is unresolved"
        )
    if (
        capability.revision_authority == "immutable_model_id"
        and capability.model_revision != llm.model
    ):
        raise Protocol22ExecutorError(
            "immutable model authority requires the model ID itself to be immutable"
        )
    context_tokens = capability.provider_context_tokens
    if (
        not isinstance(context_tokens, int)
        or isinstance(context_tokens, bool)
        or context_tokens <= 0
    ):
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires a positive provider context window"
        )
    completion_tokens = llm.max_tokens
    if (
        not isinstance(completion_tokens, int)
        or isinstance(completion_tokens, bool)
        or completion_tokens <= 0
    ):
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires a positive hard completion cap"
        )
    if completion_tokens > _MAX_BILLABLE_TOKENS_PER_DISPATCH:
        raise Protocol22ExecutorError(
            "hard completion cap exceeds the 262144-token dispatch safety ceiling"
        )
    if context_tokens <= completion_tokens:
        raise Protocol22ExecutorError(
            "provider context window must exceed the hard completion cap"
        )
    if (
        not isinstance(llm.timeout_ms, int)
        or isinstance(llm.timeout_ms, bool)
        or llm.timeout_ms <= 0
    ):
        raise Protocol22ExecutorError(
            "bounded-api-baseline-v1 requires a positive controller deadline"
        )
    temperature_micros = _decimal_micros(
        llm.temperature,
        "temperature",
        minimum=0,
        maximum=2_000_000,
    )
    top_p_micros = _decimal_micros(
        capability.top_p,
        "top_p",
        minimum=0,
        maximum=1_000_000,
    )
    seed = capability.seed
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        raise Protocol22ExecutorError("seed must be an integer or null")
    framing = capability.fixed_framing_byte_upper_bound
    if not isinstance(framing, int) or isinstance(framing, bool) or framing < 0:
        raise Protocol22ExecutorError(
            "fixed framing byte upper bound must be a nonnegative integer"
        )

    schemas = tuple(
        ResponseSchemaReferenceV1(
            artifact_kind=kind,
            schema_hash=_expected_schema_hash(registry, kind),
        )
        for kind in ("domain-baseline", "source-overview")
    )
    headers = tuple(
        sorted(
            (_header_from_config(header) for header in capability.non_secret_headers),
            key=lambda header: header.name,
        )
    )
    try:
        generation = ProviderGenerationV1(
            temperature_micros=temperature_micros,
            top_p_micros=top_p_micros,
            seed=seed,
            max_completion_tokens=completion_tokens,
        )
    except Protocol22SchemaError as exc:
        raise Protocol22ExecutorError(str(exc)) from exc
    return ExecutorContractEntryV1(
        producer_family="compact-baseline",
        execution_mode="api",
        provider_id="openai-compatible",
        api_transport=ApiTransportAuthorityV1(
            authority_schema="api-transport-authority-v1",
            api_protocol_id="openai-chat-completions",
            api_protocol_version=capability.api_protocol_version,
            base_url=llm.base_url,
            request_path=capability.request_path,
            non_secret_headers=headers,
        ),
        adapter_id=BOUNDED_API_ADAPTER_ID,
        adapter_contract_version="1",
        executor_implementation_digest=_require(
            registry, "executor", BOUNDED_API_ADAPTER_ID
        ),
        producer_protocol_version="compact-baseline-v1",
        result_contract_id="candidate-ready-v1",
        model=ModelAuthorityV1(
            model_id=llm.model,
            model_revision=capability.model_revision,
            revision_authority=capability.revision_authority,
            reasoning_effort=capability.reasoning_effort,
        ),
        request_renderer=RequestRendererAuthorityV1(
            renderer_id=COMPACT_RENDERER_ID,
            renderer_version="1",
            implementation_digest=_require(
                registry, "renderer", COMPACT_RENDERER_ID
            ),
            agent_contract_hash=_require(
                registry, "agent_contract", BASELINER_AGENT_ID
            ),
            response_schemas=schemas,
        ),
        request_tokenizer=RequestTokenizerAuthorityV1(
            tokenizer_id=CONSERVATIVE_TOKENIZER_ID,
            tokenizer_version="1",
            implementation_digest=_require(
                registry, "tokenizer", CONSERVATIVE_TOKENIZER_ID
            ),
            fallback_estimator_id="utf8-byte-upper-bound-v1",
            fixed_framing_byte_upper_bound=framing,
        ),
        generation=generation,
        reservation_calculator=ReservationCalculatorAuthorityV1(
            calculator_id=DISPATCH_CALCULATOR_ID,
            calculator_version=1,
            implementation_digest=_require(
                registry, "calculator", DISPATCH_CALCULATOR_ID
            ),
        ),
        token_accounting=TokenAccountingAuthorityV1(
            normalization_id=OPENAI_USAGE_NORMALIZER_ID,
            normalization_version="1",
            implementation_digest=_require(
                registry, "normalizer", OPENAI_USAGE_NORMALIZER_ID
            ),
            unknown_class_policy="untrusted",
        ),
        limits=ExecutorLimitsV1(
            provider_context_tokens=context_tokens,
            max_internal_calls=1,
            max_followup_input_tokens_per_call=0,
            max_completion_tokens_per_call=completion_tokens,
            max_tool_rounds=0,
            max_tool_result_bytes_per_round=0,
            max_billable_tokens_per_dispatch=_MAX_BILLABLE_TOKENS_PER_DISPATCH,
            max_active_ms_per_dispatch=llm.timeout_ms,
        ),
    )


def _header_from_config(value: object) -> NonSecretHeaderV1:
    if isinstance(value, ReV2BaselineHeaderConfig):
        return NonSecretHeaderV1(value.name, value.value)
    if isinstance(value, Mapping):
        return NonSecretHeaderV1.from_json_dict(value)
    raise Protocol22ExecutorError(
        "non_secret_headers must contain typed name/value entries"
    )


def _require(
    registry: InstalledAuthorityRegistry,
    authority_kind: str,
    authority_id: str,
) -> str:
    try:
        return registry.require(authority_kind, authority_id)
    except Protocol22AuthorityError as exc:
        raise Protocol22ExecutorError(str(exc)) from exc


def _expected_schema_hash(
    registry: InstalledAuthorityRegistry,
    artifact_kind: str,
) -> str:
    expected = response_schema_hash(artifact_kind)
    installed = _require(registry, "response_schema", artifact_kind)
    if installed != expected:
        raise Protocol22ExecutorError(
            f"installed response schema for {artifact_kind} has the wrong hash"
        )
    return expected


def _decimal_micros(
    value: object,
    field: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool):
        raise Protocol22ExecutorError(f"{field} must be a finite decimal")
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise Protocol22ExecutorError(f"{field} must be a finite decimal") from exc
    if not decimal.is_finite():
        raise Protocol22ExecutorError(f"{field} must be a finite decimal")
    fractional_digits = max(0, -decimal.as_tuple().exponent)
    if fractional_digits > 6:
        raise Protocol22ExecutorError(
            f"{field} must have at most six fractional digits"
        )
    scaled = decimal * Decimal(1_000_000)
    if scaled != scaled.to_integral_value():
        raise Protocol22ExecutorError(
            f"{field} cannot be represented exactly in integer micros"
        )
    micros = int(scaled)
    if micros < minimum or micros > maximum:
        raise Protocol22ExecutorError(
            f"{field} is outside the supported range"
        )
    return micros


def _validate_base_url(value: object) -> str:
    text = _text(value, "ApiTransportAuthorityV1.base_url")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as exc:
        raise Protocol22ExecutorError("API base_url is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise Protocol22ExecutorError(
            "API base_url requires a scheme and authority without userinfo, query, or fragment"
        )
    host = parsed.hostname.lower()
    rendered_host = f"[{host}]" if ":" in host else host
    netloc = rendered_host if port is None else f"{rendered_host}:{port}"
    path = parsed.path
    if "\\" in path or "%" in path or "//" in path:
        raise Protocol22ExecutorError("API base_url path is not canonical")
    if path not in {"", "/"}:
        pure = PurePosixPath(path)
        if (
            not path.startswith("/")
            or pure.as_posix() != path
            or any(part in {"", ".", ".."} for part in pure.parts)
            or path.endswith("/")
        ):
            raise Protocol22ExecutorError("API base_url path is not canonical")
    canonical = urlunsplit((parsed.scheme, netloc, path, "", ""))
    if canonical != text:
        raise Protocol22ExecutorError("API base_url is not canonical")
    if parsed.scheme == "http" and not _is_loopback(host):
        raise Protocol22ExecutorError(
            "API base_url must use HTTPS except for loopback conformance endpoints"
        )
    return text


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_request_path(value: object) -> str:
    text = _text(value, "ApiTransportAuthorityV1.request_path")
    if (
        not text.startswith("/")
        or text == "/"
        or text.endswith("/")
        or "\\" in text
        or "%" in text
        or "//" in text
        or "?" in text
        or "#" in text
        or PurePosixPath(text).as_posix() != text
        or any(part in {"", ".", ".."} for part in PurePosixPath(text).parts)
    ):
        raise Protocol22ExecutorError("API request_path is not canonical")
    return text


def _validate_shared_authorities(
    entries: tuple[ExecutorContractEntryV1, ...],
) -> None:
    seen: dict[tuple[str, str], str] = {}
    for entry in entries:
        authorities = [
            ("executor", entry.adapter_id, entry.executor_implementation_digest),
            (
                "calculator",
                entry.reservation_calculator.calculator_id,
                entry.reservation_calculator.implementation_digest,
            ),
            (
                "normalizer",
                entry.token_accounting.normalization_id,
                entry.token_accounting.implementation_digest,
            ),
        ]
        if entry.request_renderer is not None:
            authorities.append(
                (
                    "renderer",
                    entry.request_renderer.renderer_id,
                    entry.request_renderer.implementation_digest,
                )
            )
        if entry.request_tokenizer is not None:
            authorities.append(
                (
                    "tokenizer",
                    entry.request_tokenizer.tokenizer_id,
                    entry.request_tokenizer.implementation_digest,
                )
            )
        for kind, authority_id, implementation_digest in authorities:
            key = (kind, authority_id)
            previous = seen.get(key)
            if previous is not None and previous != implementation_digest:
                raise Protocol22ExecutorError(
                    f"executor catalog has conflicting {kind} digest for {authority_id!r}"
                )
            seen[key] = implementation_digest


__all__ = (
    "ApiTransportAuthorityV1",
    "BOUNDED_API_ADAPTER_ID",
    "ExecutorContractCatalogV1",
    "ExecutorContractEntryV1",
    "ExecutorLimitsV1",
    "ModelAuthorityV1",
    "NonSecretHeaderV1",
    "Protocol22ExecutorError",
    "RequestRendererAuthorityV1",
    "RequestTokenizerAuthorityV1",
    "ReservationCalculatorAuthorityV1",
    "ResponseSchemaReferenceV1",
    "TokenAccountingAuthorityV1",
    "resolve_executor_catalog",
)
