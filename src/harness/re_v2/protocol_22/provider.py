"""Pinned provider envelopes, reservations, usage, and bounded API execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import json
import math
import os
from pathlib import Path
import re
import socket
import stat
import time
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Protocol
from urllib.parse import urlsplit

from harness.re_v2.canonical import canonical_json_bytes, content_digest

from .artifacts import ContextBundleV1
from .executors import (
    BOUNDED_API_ADAPTER_ID,
    DISPATCH_CALCULATOR_ID,
    OPENAI_USAGE_NORMALIZER_ID,
    ExecutorContractEntryV1,
    TokenAccountingAuthorityV1,
)
from .model import (
    ExecutionInputV1,
    ProviderMessageV1,
    ProviderRequestEnvelopeV1,
    ProviderResponseFormatV1,
    RetryDiagnosticsV1,
    WorkItemV2,
)
from .response_schemas import canonical_response_schema_bytes
from .schema import (
    Protocol22SchemaError,
    load_canonical_object,
    nonnegative_int,
    positive_int,
    safe_id,
    utc_timestamp,
)


_MAX_BILLABLE_TOKENS = 262_144
_USAGE_CLASS_KEYS = frozenset(
    {
        "cached_input_tokens",
        "input_tokens",
        "reasoning_output_tokens",
        "visible_output_tokens",
    }
)
_USAGE_FIELDS = frozenset(
    {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_tokens_details",
        "completion_tokens_details",
    }
)
_HEADER_RE = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
_CREDENTIAL_HEADER_NAMES = frozenset({"authorization", "api-key", "x-api-key"})
_RESULT_STDOUT = b"echelon_result:\n  schema_version: 1\n  outcome: candidate_ready\n"


class Protocol22ProviderError(Protocol22SchemaError):
    """Raised when immutable provider or dispatch authority cannot be enforced."""


class RequestTokenizerV1(Protocol):
    tokenizer_id: str
    tokenizer_version: str
    implementation_digest: str

    def count_tokens(self, payload: bytes) -> int | None: ...


@dataclass(frozen=True, slots=True)
class DispatchReservationV1:
    initial_input_tokens: int
    billable_tokens: int
    active_ms: int

    def __post_init__(self) -> None:
        try:
            positive_int(
                self.initial_input_tokens,
                "DispatchReservationV1.initial_input_tokens",
            )
            positive_int(
                self.billable_tokens,
                "DispatchReservationV1.billable_tokens",
            )
            positive_int(self.active_ms, "DispatchReservationV1.active_ms")
        except Protocol22SchemaError as exc:
            raise Protocol22ProviderError(str(exc)) from exc
        if self.billable_tokens < self.initial_input_tokens:
            raise Protocol22ProviderError(
                "dispatch billable reservation cannot be below its input reservation"
            )


@dataclass(frozen=True, slots=True)
class NormalizedUsageV1:
    status: Literal["trusted_exact", "unavailable", "untrusted"]
    billable_tokens: int | None
    classes: Mapping[str, int]

    def __post_init__(self) -> None:
        if self.status not in {"trusted_exact", "unavailable", "untrusted"}:
            raise Protocol22ProviderError("normalized usage status is unsupported")
        if self.billable_tokens is not None:
            try:
                nonnegative_int(
                    self.billable_tokens,
                    "NormalizedUsageV1.billable_tokens",
                )
            except Protocol22SchemaError as exc:
                raise Protocol22ProviderError(str(exc)) from exc
        if not isinstance(self.classes, Mapping):
            raise Protocol22ProviderError("normalized usage classes must be a mapping")
        copied = dict(self.classes)
        if set(copied) - _USAGE_CLASS_KEYS or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in copied.values()
        ):
            raise Protocol22ProviderError("normalized usage classes are invalid")
        if self.status == "trusted_exact":
            if (
                self.billable_tokens is None
                or set(copied) != _USAGE_CLASS_KEYS
                or sum(copied.values()) != self.billable_tokens
            ):
                raise Protocol22ProviderError(
                    "trusted usage requires complete disjoint exact classes"
                )
        if self.status == "unavailable" and (
            self.billable_tokens is not None or copied
        ):
            raise Protocol22ProviderError(
                "unavailable usage cannot contain token observations"
            )
        object.__setattr__(
            self,
            "classes",
            MappingProxyType(dict(sorted(copied.items()))),
        )


@dataclass(frozen=True, slots=True)
class RawExecutionTimingV1:
    started_at: str
    ended_at: str
    duration_ms: int

    def __post_init__(self) -> None:
        try:
            utc_timestamp(self.started_at, "RawExecutionTimingV1.started_at")
            utc_timestamp(self.ended_at, "RawExecutionTimingV1.ended_at")
            nonnegative_int(self.duration_ms, "RawExecutionTimingV1.duration_ms")
        except Protocol22SchemaError as exc:
            raise Protocol22ProviderError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class RawExecutionResultV1:
    stdout: bytes
    stderr: bytes
    provider_usage: bytes | None
    timing: RawExecutionTimingV1
    outcome: Literal[
        "candidate_ready",
        "invalid_response",
        "http_error",
        "transport_error",
        "timed_out",
    ]

    def __post_init__(self) -> None:
        if not isinstance(self.stdout, bytes) or not isinstance(self.stderr, bytes):
            raise Protocol22ProviderError("raw execution output must be bytes")
        if self.provider_usage is not None and not isinstance(
            self.provider_usage, bytes
        ):
            raise Protocol22ProviderError("raw provider usage must be bytes or null")
        if not isinstance(self.timing, RawExecutionTimingV1):
            raise Protocol22ProviderError("raw execution timing is invalid")
        if self.outcome not in {
            "candidate_ready",
            "invalid_response",
            "http_error",
            "transport_error",
            "timed_out",
        }:
            raise Protocol22ProviderError("raw execution outcome is unsupported")
        if (self.outcome == "candidate_ready") != (self.stdout == _RESULT_STDOUT):
            raise Protocol22ProviderError(
                "candidate-ready outcome requires the exact minimal result block"
            )


def render_provider_request_envelope(
    work_item: WorkItemV2,
    dispatch_id: str,
    agent_bytes: bytes,
    context_bytes: bytes,
    executor: ExecutorContractEntryV1,
    schema_hash: str,
    retry_diagnostics: tuple[str, ...] = (),
) -> ProviderRequestEnvelopeV1:
    """Bind the exact agent, context, target, and executor into stored authority."""
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22ProviderError("provider envelope requires WorkItemV2")
    _validate_api_executor(executor)
    try:
        safe_id(dispatch_id, "provider dispatch_id")
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(str(exc)) from exc
    if work_item.executor_contract_hash != executor.executor_contract_hash:
        raise Protocol22ProviderError(
            "work item executor contract does not match provider authority"
        )
    if (
        work_item.producer_family != executor.producer_family
        or work_item.producer_protocol_version != executor.producer_protocol_version
        or work_item.result_contract_id != executor.result_contract_id
    ):
        raise Protocol22ProviderError(
            "work item producer contract does not match executor contract"
        )
    if (
        work_item.verifier_id != executor.verifier.verifier_id
        or work_item.verifier_version != executor.verifier.verifier_version
        or work_item.verifier_implementation_digest
        != executor.verifier.implementation_digest
    ):
        raise Protocol22ProviderError(
            "work item verifier does not match executor contract"
        )
    target_kind = work_item.output_key.artifact_kind
    if target_kind not in {"domain-baseline", "source-overview"}:
        raise Protocol22ProviderError(
            "provider work item has an unsupported target artifact kind"
        )
    renderer = executor.request_renderer
    model = executor.model
    generation = executor.generation
    if renderer is None or model is None or generation is None:  # fail-closed narrow
        raise Protocol22ProviderError("bounded API executor authority is incomplete")
    expected_schema = next(
        (
            reference.schema_hash
            for reference in renderer.response_schemas
            if reference.artifact_kind == target_kind
        ),
        None,
    )
    if expected_schema != schema_hash:
        raise Protocol22ProviderError(
            "response schema does not match target artifact kind authority"
        )
    if not isinstance(agent_bytes, bytes):
        raise Protocol22ProviderError("agent contract must be exact bytes")
    if content_digest(agent_bytes) != renderer.agent_contract_hash:
        raise Protocol22ProviderError("agent contract hash mismatch")
    agent_text = _decode_utf8(agent_bytes, "agent contract")
    context_text = _decode_utf8(context_bytes, "context bundle")
    try:
        context = load_canonical_object(
            context_bytes,
            ContextBundleV1.from_json_dict,
        )
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(f"invalid context bundle: {exc}") from exc
    context_hash = content_digest(context_bytes)
    if (
        context.target_artifact_kind != target_kind
        or context.scope != work_item.output_key.scope
        or context.target_policy_hash != work_item.output_key.layer_policy_hash
        or work_item.required_artifact_hashes != (context_hash,)
    ):
        raise Protocol22ProviderError(
            "context bundle target does not match work item artifact kind and scope"
        )
    try:
        messages = [
            ProviderMessageV1("system", agent_text),
            ProviderMessageV1("user", context_text),
        ]
        if retry_diagnostics:
            diagnostics = RetryDiagnosticsV1(1, retry_diagnostics)
            messages.append(
                ProviderMessageV1(
                    "user",
                    canonical_json_bytes(diagnostics.to_json_dict()).decode("utf-8"),
                )
            )
        return ProviderRequestEnvelopeV1(
            schema_version=1,
            dispatch_id=dispatch_id,
            work_item_id=work_item.work_item_id,
            executor_contract_hash=executor.executor_contract_hash,
            target_artifact_kind=target_kind,
            provider_id=executor.provider_id,
            model_id=model.model_id,
            model_revision=model.model_revision,
            reasoning_effort=model.reasoning_effort,
            messages=tuple(messages),
            response_format=ProviderResponseFormatV1(
                kind="json_schema",
                schema_name="echelon_compact_baseline_v1",
                strict=True,
                schema_hash=schema_hash,
            ),
            generation=generation,
            tools=(),
            tool_choice="none",
            stream=False,
        )
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(str(exc)) from exc


def render_wire_request(
    envelope: ProviderRequestEnvelopeV1,
    response_schema_bytes: bytes,
) -> bytes:
    """Expand one stored schema hash into the exact OpenAI-compatible request."""
    if not isinstance(envelope, ProviderRequestEnvelopeV1):
        raise Protocol22ProviderError("wire rendering requires a provider envelope")
    try:
        schema = load_canonical_object(response_schema_bytes, lambda value: value)
    except Protocol22SchemaError as exc:
        raise Protocol22ProviderError(
            f"response schema bytes are not canonical: {exc}"
        ) from exc
    if content_digest(response_schema_bytes) != envelope.response_format.schema_hash:
        raise Protocol22ProviderError("response schema hash mismatch")
    generation = envelope.generation
    request: dict[str, object] = {
        "model": envelope.model_id,
        "messages": [
            {"role": message.role, "content": message.content_utf8}
            for message in envelope.messages
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": envelope.response_format.schema_name,
                "strict": envelope.response_format.strict,
                "schema": schema,
            },
        },
        "temperature": _micros_value(generation.temperature_micros),
        "top_p": _micros_value(generation.top_p_micros),
        "max_completion_tokens": generation.max_completion_tokens,
        "tools": [],
        "tool_choice": envelope.tool_choice,
        "stream": envelope.stream,
    }
    if envelope.reasoning_effort is not None:
        request["reasoning_effort"] = envelope.reasoning_effort
    if generation.seed is not None:
        request["seed"] = generation.seed
    return canonical_json_bytes(request)


def calculate_bounded_dispatch_reservation(
    envelope: ProviderRequestEnvelopeV1,
    schema_bytes: bytes,
    executor: ExecutorContractEntryV1,
    tokenizer: RequestTokenizerV1,
) -> DispatchReservationV1:
    """Compute the exact-or-conservative reservation over complete wire bytes."""
    _validate_envelope_executor(envelope, executor)
    authority = executor.request_tokenizer
    if authority is None:  # pragma: no cover - guarded by executor validation
        raise Protocol22ProviderError("bounded API executor has no tokenizer authority")
    observed = (
        getattr(tokenizer, "tokenizer_id", None),
        getattr(tokenizer, "tokenizer_version", None),
        getattr(tokenizer, "implementation_digest", None),
    )
    expected = (
        authority.tokenizer_id,
        authority.tokenizer_version,
        authority.implementation_digest,
    )
    if observed[:2] != expected[:2]:
        raise Protocol22ProviderError("request tokenizer ID/version mismatch")
    if observed[2] != expected[2]:
        raise Protocol22ProviderError(
            "request tokenizer implementation digest mismatch"
        )
    count = getattr(tokenizer, "count_tokens", None)
    if not callable(count):
        raise Protocol22ProviderError("request tokenizer has no count_tokens method")
    wire = render_wire_request(envelope, schema_bytes)
    try:
        exact = count(wire)
    except Exception as exc:
        raise Protocol22ProviderError("request tokenizer execution failed") from exc
    if exact is None:
        initial = len(wire) + authority.fixed_framing_byte_upper_bound
    elif not isinstance(exact, int) or isinstance(exact, bool) or exact <= 0:
        raise Protocol22ProviderError(
            "exact request tokenizer must return a positive integer or null"
        )
    else:
        initial = exact
    limits = executor.limits
    completion = limits.max_completion_tokens_per_call
    context_window = limits.provider_context_tokens
    if context_window is None:  # pragma: no cover - executor contract guards this
        raise Protocol22ProviderError("bounded API executor lacks a context window")
    if initial + completion > context_window:
        raise Protocol22ProviderError(
            "provider request exceeds the pinned context window"
        )
    billable = (
        initial
        + limits.max_internal_calls * completion
        + (limits.max_internal_calls - 1) * limits.max_followup_input_tokens_per_call
    )
    if billable > limits.max_billable_tokens_per_dispatch:
        raise Protocol22ProviderError(
            "computed billable reservation exceeds executor ceiling"
        )
    if billable > _MAX_BILLABLE_TOKENS:
        raise Protocol22ProviderError(
            "computed billable reservation exceeds protocol safety ceiling"
        )
    return DispatchReservationV1(
        initial_input_tokens=initial,
        billable_tokens=billable,
        active_ms=limits.max_active_ms_per_dispatch,
    )


def normalize_openai_usage(
    raw_usage: object,
    contract: TokenAccountingAuthorityV1,
) -> NormalizedUsageV1:
    """Normalize OpenAI usage into four disjoint billable token classes."""
    if not isinstance(contract, TokenAccountingAuthorityV1) or (
        contract.normalization_id != OPENAI_USAGE_NORMALIZER_ID
        or contract.normalization_version != "1"
        or contract.unknown_class_policy != "untrusted"
    ):
        raise Protocol22ProviderError("OpenAI token accounting contract mismatch")
    if raw_usage is None:
        return NormalizedUsageV1("unavailable", None, {})
    if not isinstance(raw_usage, Mapping):
        return NormalizedUsageV1("untrusted", None, {})
    raw = dict(raw_usage)
    prompt = _usage_count(raw.get("prompt_tokens"))
    completion = _usage_count(raw.get("completion_tokens"))
    total = _usage_count(raw.get("total_tokens"))
    reported = total
    if prompt is None or completion is None or total is None:
        return NormalizedUsageV1("untrusted", reported, {})

    prompt_details, prompt_unknown = _usage_details(
        raw.get("prompt_tokens_details"),
        "cached_tokens",
    )
    completion_details, completion_unknown = _usage_details(
        raw.get("completion_tokens_details"),
        "reasoning_tokens",
    )
    cached = prompt_details
    reasoning = completion_details
    counts_coherent = (
        prompt + completion == total
        and cached is not None
        and reasoning is not None
        and cached <= prompt
        and reasoning <= completion
    )
    unknown = bool(set(raw) - _USAGE_FIELDS) or prompt_unknown or completion_unknown
    if not counts_coherent:
        return NormalizedUsageV1("untrusted", reported, {})
    classes = {
        "cached_input_tokens": cached,
        "input_tokens": prompt - cached,
        "reasoning_output_tokens": reasoning,
        "visible_output_tokens": completion - reasoning,
    }
    return NormalizedUsageV1(
        "untrusted" if unknown else "trusted_exact",
        total,
        classes,
    )


CredentialLoader = Callable[[], tuple[str, str] | None]


class _FallbackTokenizer:
    def __init__(self, executor: ExecutorContractEntryV1) -> None:
        authority = executor.request_tokenizer
        if authority is None:
            raise Protocol22ProviderError("bounded API executor has no tokenizer")
        self.tokenizer_id = authority.tokenizer_id
        self.tokenizer_version = authority.tokenizer_version
        self.implementation_digest = authority.implementation_digest

    def count_tokens(self, payload: bytes) -> None:
        del payload
        return None


class BoundedApiBaselineExecutor:
    """One-call, no-tool API adapter for protocol-2.2 compact baselines."""

    def __init__(
        self,
        executor: ExecutorContractEntryV1,
        *,
        credential_loader: CredentialLoader | None = None,
        tokenizer: RequestTokenizerV1 | None = None,
    ) -> None:
        _validate_api_executor(executor)
        self.executor = executor
        self._credential_loader = credential_loader or _environment_credential
        self._tokenizer = tokenizer or _FallbackTokenizer(executor)

    def execute(
        self,
        execution_input: ExecutionInputV1,
        envelope: ProviderRequestEnvelopeV1,
        reservation: DispatchReservationV1,
        candidate_root: Path,
        deadline: float,
    ) -> RawExecutionResultV1:
        schema_bytes = canonical_response_schema_bytes(envelope.target_artifact_kind)
        _validate_envelope_executor(envelope, self.executor)
        _validate_execution_input(execution_input, envelope)
        expected = calculate_bounded_dispatch_reservation(
            envelope,
            schema_bytes,
            self.executor,
            self._tokenizer,
        )
        if reservation != expected:
            raise Protocol22ProviderError(
                "dispatch reservation does not match immutable request authority"
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
        if deadline <= time.monotonic():
            moment = _utc_now()
            return RawExecutionResultV1(
                stdout=b"",
                stderr=b"deadline_expired\n",
                provider_usage=None,
                timing=RawExecutionTimingV1(moment, moment, 0),
                outcome="timed_out",
            )
        credential = _load_credential(self._credential_loader)
        wire = render_wire_request(envelope, schema_bytes)
        transport = self.executor.api_transport
        if transport is None:  # pragma: no cover - contract validation guards this
            raise Protocol22ProviderError("bounded API executor lacks transport")
        url = _request_target(transport.base_url, transport.request_path)
        headers = {header.name: header.value for header in transport.non_secret_headers}
        if any(
            name in headers
            for name in {"content-type", "content-length", "host", credential[0]}
        ):
            raise Protocol22ProviderError(
                "pinned non-secret headers conflict with transport headers"
            )
        headers["content-type"] = "application/json"
        headers[credential[0]] = credential[1]

        started_at = _utc_now()
        started_ns = time.monotonic_ns()
        response_status: int | None = None
        response_body: bytes | None = None
        outcome = "transport_error"
        stderr = b"transport_error\n"
        connection: http.client.HTTPConnection | None = None
        try:
            remaining = min(
                deadline - time.monotonic(),
                reservation.active_ms / 1000,
            )
            if remaining <= 0:
                outcome = "timed_out"
                stderr = b"deadline_expired\n"
            else:
                connection = _connection(url, remaining)
                _post_once(connection, url, wire, headers)
                response = connection.getresponse()
                response_status = int(response.status)
                response_body = response.read()
                if 200 <= response_status < 300:
                    outcome = "invalid_response"
                    stderr = b"invalid_response\n"
                else:
                    outcome = "http_error"
                    stderr = f"http_error:{response_status}\n".encode("ascii")
        except (TimeoutError, socket.timeout):
            outcome = "timed_out"
            stderr = b"request_timed_out\n"
        except (ConnectionError, http.client.HTTPException, OSError):
            outcome = "transport_error"
            stderr = b"transport_error\n"
        finally:
            if connection is not None:
                connection.close()
        ended_ns = time.monotonic_ns()
        ended_at = _utc_now()
        timing = RawExecutionTimingV1(
            started_at,
            ended_at,
            max(0, (ended_ns - started_ns) // 1_000_000),
        )
        if outcome != "invalid_response" or response_body is None:
            return RawExecutionResultV1(
                stdout=b"",
                stderr=stderr,
                provider_usage=None,
                timing=timing,
                outcome=outcome,  # type: ignore[arg-type]
            )

        response_value = _parse_response(response_body)
        if response_value is None:
            return RawExecutionResultV1(
                b"",
                b"invalid_response:json\n",
                None,
                timing,
                "invalid_response",
            )
        usage_bytes = _usage_bytes(response_value.get("usage"))
        content, reason = _assistant_content(response_value, envelope.model_revision)
        if content is None:
            return RawExecutionResultV1(
                b"",
                f"invalid_response:{reason}\n".encode("ascii"),
                usage_bytes,
                timing,
                "invalid_response",
            )
        _publish_candidate(root, content.encode("utf-8"))
        return RawExecutionResultV1(
            _RESULT_STDOUT,
            b"",
            usage_bytes,
            timing,
            "candidate_ready",
        )


def _validate_api_executor(executor: object) -> None:
    if not isinstance(executor, ExecutorContractEntryV1):
        raise Protocol22ProviderError("bounded provider requires an executor contract")
    limits = executor.limits
    if (
        executor.execution_mode != "api"
        or executor.adapter_id != BOUNDED_API_ADAPTER_ID
        or executor.api_transport is None
        or executor.provider_id is None
        or executor.model is None
        or executor.request_renderer is None
        or executor.request_tokenizer is None
        or executor.generation is None
        or executor.reservation_calculator.calculator_id != DISPATCH_CALCULATOR_ID
        or executor.reservation_calculator.calculator_version != 1
        or limits.max_internal_calls != 1
        or limits.max_followup_input_tokens_per_call != 0
        or limits.max_tool_rounds != 0
        or limits.max_tool_result_bytes_per_round != 0
    ):
        raise Protocol22ProviderError(
            "executor contract cannot enforce bounded one-call API execution"
        )


def _validate_envelope_executor(
    envelope: object,
    executor: ExecutorContractEntryV1,
) -> None:
    if not isinstance(envelope, ProviderRequestEnvelopeV1):
        raise Protocol22ProviderError("provider envelope is invalid")
    _validate_api_executor(executor)
    model = executor.model
    generation = executor.generation
    renderer = executor.request_renderer
    if model is None or generation is None or renderer is None:  # pragma: no cover
        raise Protocol22ProviderError("executor nested provider authority is missing")
    expected_schema = next(
        (
            reference.schema_hash
            for reference in renderer.response_schemas
            if reference.artifact_kind == envelope.target_artifact_kind
        ),
        None,
    )
    if envelope.executor_contract_hash != executor.executor_contract_hash:
        raise Protocol22ProviderError("envelope executor contract mismatch")
    if (
        envelope.provider_id != executor.provider_id
        or envelope.model_id != model.model_id
        or envelope.model_revision != model.model_revision
        or envelope.reasoning_effort != model.reasoning_effort
    ):
        raise Protocol22ProviderError("envelope model/provider authority mismatch")
    if envelope.generation.max_completion_tokens != (
        executor.limits.max_completion_tokens_per_call
    ):
        raise Protocol22ProviderError("envelope hard completion cap mismatch")
    if envelope.generation != generation:
        raise Protocol22ProviderError("envelope sampling authority mismatch")
    if envelope.response_format.schema_hash != expected_schema:
        raise Protocol22ProviderError("envelope response schema authority mismatch")
    if envelope.tools or envelope.tool_choice != "none" or envelope.stream:
        raise Protocol22ProviderError(
            "provider envelope must be tool-free and non-streaming"
        )


def _validate_execution_input(
    execution_input: object,
    envelope: ProviderRequestEnvelopeV1,
) -> None:
    if not isinstance(execution_input, ExecutionInputV1):
        raise Protocol22ProviderError("execution input is invalid")
    if (
        execution_input.dispatch_id != envelope.dispatch_id
        or execution_input.work_item_id != envelope.work_item_id
        or execution_input.executor_contract_hash != envelope.executor_contract_hash
        or execution_input.provider_request_envelope_hash != envelope.identity
        or execution_input.deterministic_invocation is not None
    ):
        raise Protocol22ProviderError(
            "execution input does not bind the stored provider envelope"
        )


def _decode_utf8(payload: object, label: str) -> str:
    if not isinstance(payload, bytes):
        raise Protocol22ProviderError(f"{label} must be bytes")
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise Protocol22ProviderError(f"{label} must be valid UTF-8") from exc


def _micros_value(value: int) -> float:
    return value / 1_000_000


def _usage_count(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _usage_details(value: object, field: str) -> tuple[int | None, bool]:
    if value is None:
        return 0, False
    if not isinstance(value, Mapping):
        return None, True
    raw = dict(value)
    return _usage_count(raw.get(field, 0)), bool(set(raw) - {field})


def _environment_credential() -> tuple[str, str] | None:
    token = os.environ.get("OPENAI_API_KEY")
    if not token:
        return None
    return "authorization", f"Bearer {token}"


def _load_credential(loader: CredentialLoader) -> tuple[str, str]:
    try:
        value = loader()
    except Exception as exc:
        raise Protocol22ProviderError("credential loading failed") from exc
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise Protocol22ProviderError("credential loader returned no valid credential")
    name, header_value = value
    if (
        name != name.lower()
        or not _HEADER_RE.fullmatch(name)
        or name not in _CREDENTIAL_HEADER_NAMES
        or header_value.strip() != header_value
        or any(character in header_value for character in "\r\n\x00")
    ):
        raise Protocol22ProviderError("credential header is invalid")
    return name, header_value


def _request_target(base_url: str, request_path: str):  # type: ignore[no-untyped-def]
    parsed = urlsplit(base_url)
    prefix = parsed.path.rstrip("/")
    path = f"{prefix}{request_path}"
    return parsed, path


def _connection(target, timeout: float):  # type: ignore[no-untyped-def]
    parsed, _path = target
    connection_type = (
        http.client.HTTPSConnection
        if parsed.scheme == "https"
        else http.client.HTTPConnection
    )
    return connection_type(parsed.hostname, parsed.port, timeout=timeout)


def _post_once(
    connection: http.client.HTTPConnection,
    target,
    wire: bytes,
    headers: Mapping[str, str],
) -> None:  # type: ignore[no-untyped-def]
    _parsed, path = target
    connection.putrequest("POST", path, skip_accept_encoding=True)
    for name, value in sorted(headers.items()):
        connection.putheader(name, value)
    connection.putheader("content-length", str(len(wire)))
    connection.endheaders(wire)


def _parse_response(payload: bytes) -> Mapping[str, object] | None:
    try:
        text = payload.decode("utf-8", errors="strict")
        raw = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, Protocol22ProviderError):
        return None
    return raw if isinstance(raw, Mapping) else None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Protocol22ProviderError("provider response contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise Protocol22ProviderError(
        f"provider response contains non-finite number {value}"
    )


def _usage_bytes(value: object) -> bytes | None:
    if value is None:
        return None
    try:
        return canonical_json_bytes(value)
    except (TypeError, ValueError, UnicodeEncodeError):
        return None


def _assistant_content(
    response: Mapping[str, object],
    expected_model_revision: str,
) -> tuple[str | None, str]:
    if response.get("model") != expected_model_revision:
        return None, "model_revision"
    choices = response.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        return None, "choices"
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return None, "choice"
    if choice.get("finish_reason") in {"tool_calls", "function_call"}:
        return None, "tool_calls"
    message = choice.get("message")
    if not isinstance(message, Mapping) or message.get("role") != "assistant":
        return None, "message"
    content = message.get("content")
    if not isinstance(content, str):
        return None, "content"
    if message.get("refusal") is not None:
        return None, "refusal"
    tool_calls = message.get("tool_calls")
    if tool_calls not in (None, []):
        return None, "tool_calls"
    if message.get("function_call") is not None:
        return None, "tool_calls"
    try:
        content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None, "content"
    return content, ""


def _validate_empty_candidate_root(path: Path) -> Path:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise Protocol22ProviderError("candidate root must be a safe directory")
    try:
        entries = tuple(os.scandir(root))
    except OSError as exc:
        raise Protocol22ProviderError("cannot inspect candidate root") from exc
    if entries:
        raise Protocol22ProviderError("candidate root must be empty before execution")
    return root


def _publish_candidate(root: Path, payload: bytes) -> None:
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    candidate_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    directory_fd: int | None = None
    candidate_created = False
    try:
        directory_fd = os.open(root, directory_flags)
        directory_metadata = os.fstat(directory_fd)
        if not stat.S_ISDIR(directory_metadata.st_mode) or not _same_directory(
            root,
            directory_metadata,
        ):
            raise Protocol22ProviderError("candidate root identity changed")
        if os.listdir(directory_fd):
            raise Protocol22ProviderError(
                "candidate root must remain empty until publication"
            )
        fd = os.open(
            "baseline.json",
            candidate_flags,
            0o600,
            dir_fd=directory_fd,
        )
        candidate_created = True
        try:
            written_metadata = os.fstat(fd)
            if not stat.S_ISREG(written_metadata.st_mode):
                raise Protocol22ProviderError("candidate output is not regular")
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.fsync(directory_fd)
        verify_fd = os.open(
            "baseline.json",
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=directory_fd,
        )
        try:
            verified_metadata = os.fstat(verify_fd)
            same_file = (
                verified_metadata.st_dev == written_metadata.st_dev
                and verified_metadata.st_ino == written_metadata.st_ino
            )
            if (
                not same_file
                or not stat.S_ISREG(verified_metadata.st_mode)
                or verified_metadata.st_size != len(payload)
                or _read_bounded(verify_fd, len(payload)) != payload
            ):
                raise Protocol22ProviderError("published candidate bytes are invalid")
        finally:
            os.close(verify_fd)
        if not _same_directory(root, directory_metadata):
            raise Protocol22ProviderError("candidate root identity changed")
        os.fsync(directory_fd)
    except Protocol22ProviderError:
        _discard_candidate(directory_fd, candidate_created)
        raise
    except OSError as exc:
        _discard_candidate(directory_fd, candidate_created)
        raise Protocol22ProviderError(
            "cannot durably publish provider candidate"
        ) from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _same_directory(root: Path, opened: os.stat_result) -> bool:
    try:
        visible = os.stat(root, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(visible.st_mode)
        and visible.st_dev == opened.st_dev
        and visible.st_ino == opened.st_ino
    )


def _discard_candidate(directory_fd: int | None, created: bool) -> None:
    if directory_fd is None or not created:
        return
    try:
        os.unlink("baseline.json", dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError:
        pass


def _read_bounded(fd: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = expected_size + 1
    while remaining:
        chunk = os.read(fd, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short candidate write")
        view = view[written:]


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


__all__ = (
    "BoundedApiBaselineExecutor",
    "CredentialLoader",
    "DispatchReservationV1",
    "NormalizedUsageV1",
    "Protocol22ProviderError",
    "RawExecutionResultV1",
    "RawExecutionTimingV1",
    "RequestTokenizerV1",
    "calculate_bounded_dispatch_reservation",
    "normalize_openai_usage",
    "render_provider_request_envelope",
    "render_wire_request",
)
