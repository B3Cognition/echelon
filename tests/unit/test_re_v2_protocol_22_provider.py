from __future__ import annotations

from dataclasses import dataclass, replace
import json

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.executors import ExecutorContractEntryV1
from harness.re_v2.protocol_22.model import (
    ExecutionInputV1,
    ProviderRequestEnvelopeV1,
)
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    Protocol22ProviderError,
    calculate_bounded_dispatch_reservation,
    canonical_prosaic_agent_bytes,
    decode_prosaic_agent_bytes,
    normalize_openai_usage,
    render_provider_request_envelope,
    render_wire_request,
)
from harness.re_v2.protocol_22.response_schemas import (
    authorial_response_schema,
    canonical_response_schema_bytes,
    response_schema_hash,
)
from tests.re_v2_protocol_22_fixtures import digest
from tests.unit.test_re_v2_protocol_22_context import (
    _domain_baseline_bytes,
    _domain_fixture,
)


AGENT_BYTES = b"agent contract"


def test_prosaic_agent_contract_round_trips_body_and_frontmatter_separately() -> None:
    artifact = ProsaicCommandArtifact(
        body="Baseliner body.\n",
        frontmatter={
            "name": "echelon.re-baseliner",
            "execution": "agent",
            "tools": "write",
            "model_tier": "strong",
            "effort": "high",
        },
    )

    payload = canonical_prosaic_agent_bytes(artifact)

    assert decode_prosaic_agent_bytes(payload) == artifact
    assert not payload.startswith(b"---")


def test_prosaic_agent_contract_rejects_unknown_fields() -> None:
    payload = canonical_json_bytes(
        {"body": "Baseliner body.\n", "frontmatter": {}, "unexpected": True}
    )

    with pytest.raises(Protocol22ProviderError, match="unknown fields"):
        decode_prosaic_agent_bytes(payload)


def _authority() -> tuple[object, ExecutorContractEntryV1, bytes]:
    fixture = _domain_fixture()
    item, _artifact = _domain_baseline_bytes(fixture, {})
    executor = fixture.inputs.executor_contract.entry_for("compact-baseline")
    assert executor.request_tokenizer is not None
    assert executor.request_renderer is not None
    assert content_digest(AGENT_BYTES) == executor.request_renderer.agent_contract_hash
    return item, executor, fixture.context_bytes


def _envelope(
    *,
    item: object | None = None,
    executor: ExecutorContractEntryV1 | None = None,
    agent_bytes: bytes = AGENT_BYTES,
    context_bytes: bytes | None = None,
) -> ProviderRequestEnvelopeV1:
    default_item, default_executor, default_context = _authority()
    selected_item = item or default_item
    selected_executor = executor or default_executor
    return render_provider_request_envelope(
        selected_item,
        "dispatch-1",
        agent_bytes,
        context_bytes or default_context,
        selected_executor,
        response_schema_hash("domain-baseline"),
    )


@dataclass(frozen=True)
class _Tokenizer:
    tokenizer_id: str
    tokenizer_version: str
    implementation_digest: str
    exact_count: int | None

    def count_tokens(self, payload: bytes) -> int | None:
        assert payload
        return self.exact_count


def _tokenizer(
    executor: ExecutorContractEntryV1,
    exact_count: int | None,
    *,
    implementation_digest: str | None = None,
) -> _Tokenizer:
    authority = executor.request_tokenizer
    assert authority is not None
    return _Tokenizer(
        tokenizer_id=authority.tokenizer_id,
        tokenizer_version=authority.tokenizer_version,
        implementation_digest=(
            implementation_digest or authority.implementation_digest
        ),
        exact_count=exact_count,
    )


def test_envelope_binds_exact_messages_target_and_executor_authority() -> None:
    item, executor, context = _authority()

    envelope = _envelope(item=item, executor=executor, context_bytes=context)

    assert envelope.work_item_id == item.work_item_id
    assert envelope.executor_contract_hash == executor.executor_contract_hash
    assert envelope.target_artifact_kind == "domain-baseline"
    assert tuple(message.role for message in envelope.messages) == ("system", "user")
    assert envelope.messages[0].content_utf8.encode() == AGENT_BYTES
    assert envelope.messages[1].content_utf8.encode() == context
    assert envelope.provider_id == executor.provider_id
    assert envelope.model_id == executor.model.model_id
    assert envelope.model_revision == executor.model.model_revision
    assert envelope.reasoning_effort == executor.model.reasoning_effort
    assert envelope.generation == executor.generation
    assert envelope.response_format.schema_hash == response_schema_hash(
        "domain-baseline"
    )
    assert envelope.tools == ()
    assert envelope.tool_choice == "none"
    assert envelope.stream is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("agent", "agent contract"),
        ("schema", "response schema"),
        ("executor", "executor contract"),
        ("kind", "artifact kind"),
    ),
)
def test_envelope_rejects_authority_mismatch(mutation: str, message: str) -> None:
    item, executor, context = _authority()
    agent = AGENT_BYTES
    schema_hash = response_schema_hash("domain-baseline")
    if mutation == "agent":
        agent = b"mutable prompt"
    elif mutation == "schema":
        schema_hash = digest("wrong schema")
    elif mutation == "executor":
        item = replace(item, executor_contract_hash=digest("wrong executor"))
    else:
        item = replace(
            item,
            output_key=replace(
                item.output_key,
                artifact_kind="source-overview",
                scope=replace(item.output_key.scope, domain_key=None),
                partition_id=digest("source partition"),
            ),
        )

    with pytest.raises(Protocol22ProviderError, match=message):
        render_provider_request_envelope(
            item,
            "dispatch-1",
            agent,
            context,
            executor,
            schema_hash,
        )


def test_wire_request_expands_schema_and_omits_null_seed() -> None:
    envelope = _envelope()
    schema_bytes = canonical_response_schema_bytes("domain-baseline")

    raw = json.loads(render_wire_request(envelope, schema_bytes))

    expected = {
        "model": envelope.model_id,
        "messages": [
            {"role": "system", "content": envelope.messages[0].content_utf8},
            {"role": "user", "content": envelope.messages[1].content_utf8},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "echelon_compact_baseline_v1",
                "strict": True,
                "schema": authorial_response_schema("domain-baseline"),
            },
        },
        "temperature": 0.2,
        "top_p": 1.0,
        "max_completion_tokens": 8192,
        "tools": [],
        "tool_choice": "none",
        "stream": False,
    }
    if envelope.reasoning_effort is not None:
        expected["reasoning_effort"] = envelope.reasoning_effort
    assert raw == expected
    assert "seed" not in raw


def test_wire_request_includes_non_null_seed_and_is_canonical() -> None:
    envelope = _envelope()
    envelope = replace(
        envelope,
        generation=replace(envelope.generation, seed=42),
    )

    wire = render_wire_request(
        envelope,
        canonical_response_schema_bytes("domain-baseline"),
    )

    assert json.loads(wire)["seed"] == 42
    assert wire == canonical_json_bytes(json.loads(wire))


def test_wire_rejects_schema_hash_or_noncanonical_bytes() -> None:
    envelope = _envelope()
    schema = canonical_response_schema_bytes("domain-baseline")

    with pytest.raises(Protocol22ProviderError, match="schema hash"):
        render_wire_request(
            replace(
                envelope,
                response_format=replace(
                    envelope.response_format,
                    schema_hash=digest("wrong"),
                ),
            ),
            schema,
        )
    with pytest.raises(Protocol22ProviderError, match="canonical"):
        render_wire_request(envelope, b" " + schema)


def test_fallback_reservation_covers_complete_wire_request() -> None:
    envelope = _envelope()
    _item, executor, _context = _authority()
    schema = canonical_response_schema_bytes("domain-baseline")
    wire = render_wire_request(envelope, schema)

    reservation = calculate_bounded_dispatch_reservation(
        envelope,
        schema,
        executor,
        _tokenizer(executor, None),
    )

    framing = executor.request_tokenizer.fixed_framing_byte_upper_bound
    expected_input = len(wire) + framing
    assert reservation == DispatchReservationV1(
        initial_input_tokens=expected_input,
        billable_tokens=(
            expected_input
            + executor.limits.max_internal_calls
            * executor.limits.max_completion_tokens_per_call
            + (executor.limits.max_internal_calls - 1)
            * executor.limits.max_followup_input_tokens_per_call
        ),
        active_ms=executor.limits.max_active_ms_per_dispatch,
    )


def test_exact_tokenizer_count_is_used_without_fallback_framing() -> None:
    envelope = _envelope()
    _item, executor, _context = _authority()
    schema = canonical_response_schema_bytes("domain-baseline")

    reservation = calculate_bounded_dispatch_reservation(
        envelope,
        schema,
        executor,
        _tokenizer(executor, 1234),
    )

    assert reservation.initial_input_tokens == 1234
    assert reservation.billable_tokens == 1234 + 8192


def test_reservation_rejects_context_ceiling_billable_ceiling_and_tokenizer_drift() -> None:
    item, executor, context = _authority()
    envelope = _envelope(item=item, executor=executor, context_bytes=context)
    schema = canonical_response_schema_bytes("domain-baseline")

    small_context_executor = replace(
        executor,
        limits=replace(executor.limits, provider_context_tokens=8193),
    )
    small_context_item = replace(
        item,
        executor_contract_hash=small_context_executor.executor_contract_hash,
    )
    small_context_envelope = _envelope(
        item=small_context_item,
        executor=small_context_executor,
        context_bytes=context,
    )
    with pytest.raises(Protocol22ProviderError, match="context window"):
        calculate_bounded_dispatch_reservation(
            small_context_envelope,
            schema,
            small_context_executor,
            _tokenizer(small_context_executor, 2),
        )

    small_billable_executor = replace(
        executor,
        limits=replace(executor.limits, max_billable_tokens_per_dispatch=8192),
    )
    small_billable_item = replace(
        item,
        executor_contract_hash=small_billable_executor.executor_contract_hash,
    )
    small_billable_envelope = _envelope(
        item=small_billable_item,
        executor=small_billable_executor,
        context_bytes=context,
    )
    with pytest.raises(Protocol22ProviderError, match="billable.*ceiling"):
        calculate_bounded_dispatch_reservation(
            small_billable_envelope,
            schema,
            small_billable_executor,
            _tokenizer(small_billable_executor, 1),
        )

    with pytest.raises(Protocol22ProviderError, match="tokenizer.*digest"):
        calculate_bounded_dispatch_reservation(
            envelope,
            schema,
            executor,
            _tokenizer(executor, 1, implementation_digest=digest("drift")),
        )


def test_mutable_provider_defaults_cannot_change_stored_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    envelope = _envelope()
    stored = canonical_json_bytes(envelope.to_json_dict())
    monkeypatch.setenv("OPENAI_MODEL", "different")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_TEMPERATURE", "2")

    loaded = ProviderRequestEnvelopeV1.from_json_dict(json.loads(stored))

    assert canonical_json_bytes(loaded.to_json_dict()) == stored


def test_execution_input_must_bind_stored_envelope() -> None:
    envelope = _envelope()
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id=envelope.dispatch_id,
        work_item_id=envelope.work_item_id,
        attempt_kind="initial_generation",
        executor_contract_hash=envelope.executor_contract_hash,
        agent_contract_hash=content_digest(AGENT_BYTES),
        context_bundle_hash=digest("context"),
        provider_request_envelope_hash=envelope.identity,
        deterministic_invocation=None,
    )
    assert execution_input.provider_request_envelope_hash == envelope.identity


def test_openai_usage_normalization_produces_disjoint_exact_classes() -> None:
    _item, executor, _context = _authority()
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 8,
        "total_tokens": 18,
        "prompt_tokens_details": {"cached_tokens": 4},
        "completion_tokens_details": {"reasoning_tokens": 3},
    }

    normalized = normalize_openai_usage(usage, executor.token_accounting)

    assert normalized.status == "trusted_exact"
    assert normalized.billable_tokens == 18
    assert dict(normalized.classes) == {
        "cached_input_tokens": 4,
        "input_tokens": 6,
        "reasoning_output_tokens": 3,
        "visible_output_tokens": 5,
    }
    assert sum(normalized.classes.values()) == normalized.billable_tokens


@pytest.mark.parametrize(
    "usage",
    (
        None,
        {},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 3},
        {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "mystery": 1},
        {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 2},
        },
    ),
)
def test_missing_or_unclassifiable_usage_is_never_trusted_zero(
    usage: object,
) -> None:
    _item, executor, _context = _authority()

    normalized = normalize_openai_usage(usage, executor.token_accounting)

    assert normalized.status in {"unavailable", "untrusted"}
    assert not (
        normalized.status == "trusted_exact"
        and normalized.billable_tokens == 0
    )
