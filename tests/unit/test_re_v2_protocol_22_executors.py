from __future__ import annotations

from dataclasses import replace

import pytest

from harness.config import (
    HarnessConfig,
    LlmConfig,
    ReV2BaselineConfig,
    ReV2BaselineHeaderConfig,
)
from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.executors import (
    ApiTransportAuthorityV1,
    ExecutorContractCatalogV1,
    ExecutorContractEntryV1,
    Protocol22ExecutorError,
    SHARED_AI_CLI_ADAPTER_ID,
    SHARED_PROVIDER_USAGE_NORMALIZER_ID,
    resolve_executor_catalog,
)
from harness.re_v2.protocol_22.response_schemas import response_schema_hash
from harness.re_v2.protocol_22.schema import load_canonical_object
from tests.re_v2_protocol_22_fixtures import digest


def _registry() -> InstalledAuthorityRegistry:
    return InstalledAuthorityRegistry(
        executor_implementations={
            "bounded-api-baseline-v1": digest("api executor"),
            "re-v2-in-process-v1": digest("in-process executor"),
            "shared-ai-cli-baseline-v1": digest("shared CLI adapter"),
        },
        renderer_implementations={
            "compact-baseline-renderer-v1": digest("renderer"),
        },
        tokenizer_implementations={
            "utf8-byte-upper-bound-v1": digest("tokenizer"),
        },
        calculator_implementations={
            "bounded-dispatch-v1": digest("dispatch calculator"),
            "bounded-in-process-v1": digest("in-process calculator"),
        },
        normalizer_implementations={
            "deterministic-zero-usage-v1": digest("zero normalizer"),
            "openai-usage-v1": digest("openai normalizer"),
            "shared-provider-usage-v1": digest("shared usage normalizer"),
        },
        verifier_implementations={"compact-verifier-v1": digest("verifier")},
        partitioner_implementations={},
        ownership_implementations={},
        agent_contracts={"echelon.re-baseliner": digest("agent contract")},
        response_schemas={
            "domain-baseline": response_schema_hash("domain-baseline"),
            "source-overview": response_schema_hash("source-overview"),
        },
    )


def _config(*, cli: str = "openai-compatible") -> HarnessConfig:
    return HarnessConfig(
        provider="docker",
        llm=LlmConfig(
            enabled=True,
            cli=cli,
            base_url="https://api.example.test/v1",
            model="gpt-example",
            temperature=0.2,
            max_tokens=8192,
            timeout_ms=300_000,
            re_v2_baseline=ReV2BaselineConfig(
                model_revision="gpt-example-2026-08-01",
                revision_authority="provider_resolved_revision",
                provider_context_tokens=200_000,
                reasoning_effort="high",
                top_p="1.0",
                seed=None,
                request_path="/chat/completions",
                api_protocol_version="1",
                non_secret_headers=(
                    ReV2BaselineHeaderConfig("openai-organization", "org-example"),
                ),
                fixed_framing_byte_upper_bound=4096,
            ),
        ),
    )


def _baseline_entry(catalog: ExecutorContractCatalogV1) -> ExecutorContractEntryV1:
    return next(
        entry for entry in catalog.entries if entry.producer_family == "compact-baseline"
    )


def _shared_cli_entry() -> ExecutorContractEntryV1:
    api = _baseline_entry(resolve_executor_catalog(_config(), "baseline", _registry()))
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


@pytest.mark.unit
def test_shared_cli_contract_delegates_model_generation_and_tokenizer() -> None:
    entry = _shared_cli_entry()

    assert entry.execution_mode == "cli"
    assert entry.provider_id == "codex"
    assert entry.api_transport is None
    assert entry.model is None
    assert entry.request_tokenizer is None
    assert entry.generation is None
    assert entry.request_renderer is not None
    assert entry.limits.max_billable_tokens_per_dispatch == 262_144
    assert ExecutorContractEntryV1.from_json_dict(entry.to_json_dict()) == entry


@pytest.mark.unit
@pytest.mark.parametrize("cli", ("claude", "codex", "copilot", "opencode"))
def test_baseline_catalog_resolves_shared_cli_without_model_authority(
    cli: str,
) -> None:
    entry = _baseline_entry(
        resolve_executor_catalog(
            _config(cli=cli),
            "baseline",
            _registry(),
            provider_mode="cli",
        )
    )

    assert entry.execution_mode == "cli"
    assert entry.provider_id == cli
    assert entry.adapter_id == SHARED_AI_CLI_ADAPTER_ID
    assert entry.api_transport is None
    assert entry.model is None
    assert entry.request_tokenizer is None
    assert entry.generation is None
    assert entry.token_accounting.normalization_id == (
        SHARED_PROVIDER_USAGE_NORMALIZER_ID
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "mutation",
    ("api_transport", "model", "request_tokenizer", "generation"),
)
def test_shared_cli_contract_rejects_reinvented_provider_authority(
    mutation: str,
) -> None:
    entry = _shared_cli_entry()
    api = _baseline_entry(resolve_executor_catalog(_config(), "baseline", _registry()))

    with pytest.raises(Protocol22ExecutorError, match="shared-ai-cli-baseline-v1"):
        replace(entry, **{mutation: getattr(api, mutation)})


@pytest.mark.unit
def test_shared_cli_adapter_id_cannot_be_attached_to_api_mode() -> None:
    api = _baseline_entry(resolve_executor_catalog(_config(), "baseline", _registry()))

    with pytest.raises(Protocol22ExecutorError, match="shared-ai-cli-baseline-v1"):
        replace(api, adapter_id=SHARED_AI_CLI_ADAPTER_ID)


@pytest.mark.unit
def test_cli_mode_rejects_an_unregistered_adapter_id() -> None:
    entry = _shared_cli_entry()

    with pytest.raises(Protocol22ExecutorError, match="registered shared adapter"):
        replace(entry, adapter_id="unknown-cli-adapter-v1")


@pytest.mark.unit
@pytest.mark.parametrize("cli", ("claude", "codex", "copilot", "opencode"))
def test_agentic_cli_is_ineligible_for_baseline(cli: str) -> None:
    with pytest.raises(Protocol22ExecutorError, match="bounded-api-baseline-v1"):
        resolve_executor_catalog(_config(cli=cli), "baseline", _registry())


@pytest.mark.unit
@pytest.mark.parametrize("cli", ("claude", "codex", "copilot", "opencode"))
def test_inventory_goal_does_not_resolve_an_unused_provider(cli: str) -> None:
    catalog = resolve_executor_catalog(_config(cli=cli), "inventory", _registry())

    assert all(entry.execution_mode == "in_process" for entry in catalog.entries)
    assert {entry.producer_family for entry in catalog.entries} == {
        "evidence-pack",
        "inventory",
        "partition",
    }


@pytest.mark.unit
def test_baseline_catalog_pins_one_call_tool_free_api_and_sampling() -> None:
    catalog = resolve_executor_catalog(_config(), "baseline", _registry())
    entry = _baseline_entry(catalog)

    assert entry.execution_mode == "api"
    assert entry.adapter_id == "bounded-api-baseline-v1"
    assert entry.limits.max_internal_calls == 1
    assert entry.limits.max_followup_input_tokens_per_call == 0
    assert entry.limits.max_tool_rounds == 0
    assert entry.limits.max_tool_result_bytes_per_round == 0
    assert entry.limits.max_completion_tokens_per_call == 8192
    assert entry.limits.max_billable_tokens_per_dispatch == 262_144
    assert entry.generation is not None
    assert entry.generation.temperature_micros == 200_000
    assert entry.generation.top_p_micros == 1_000_000
    assert entry.generation.seed is None
    assert entry.model is not None
    assert entry.model.model_revision == "gpt-example-2026-08-01"
    assert entry.verifier.verifier_id == "compact-verifier-v1"
    assert entry.verifier.implementation_digest == digest("verifier")
    assert entry.request_renderer is not None
    assert [row.artifact_kind for row in entry.request_renderer.response_schemas] == [
        "domain-baseline",
        "source-overview",
    ]

    payload = canonical_json_bytes(catalog.to_json_dict())
    assert load_canonical_object(payload, ExecutorContractCatalogV1.from_json_dict) == catalog


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("model_revision", None, "model revision"),
        ("provider_context_tokens", None, "context window"),
        ("provider_context_tokens", 0, "context window"),
        ("seed", True, "seed"),
        ("top_p", "0.1234567", "six fractional"),
        ("fixed_framing_byte_upper_bound", -1, "framing"),
    ),
)
def test_baseline_rejects_invalid_capability_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    config = _config()
    config.llm.re_v2_baseline = replace(
        config.llm.re_v2_baseline,
        **{field: value},
    )

    with pytest.raises(Protocol22ExecutorError, match=message):
        resolve_executor_catalog(config, "baseline", _registry())


@pytest.mark.unit
@pytest.mark.parametrize(
    "temperature",
    ("0.1234567", float("nan"), float("inf"), -0.1, 2.1),
)
def test_baseline_rejects_noncanonical_temperature(temperature: object) -> None:
    config = _config()
    config.llm.temperature = temperature  # type: ignore[assignment]

    with pytest.raises(Protocol22ExecutorError, match="temperature"):
        resolve_executor_catalog(config, "baseline", _registry())


@pytest.mark.unit
def test_baseline_rejects_unresolved_immutable_model_alias() -> None:
    config = _config()
    config.llm.re_v2_baseline = replace(
        config.llm.re_v2_baseline,
        revision_authority="immutable_model_id",
        model_revision="different-revision",
    )

    with pytest.raises(Protocol22ExecutorError, match="immutable model"):
        resolve_executor_catalog(config, "baseline", _registry())


@pytest.mark.unit
@pytest.mark.parametrize(
    "base_url",
    (
        "http://api.example.test/v1",
        "https://user@example.test/v1",
        "https://api.example.test/v1?route=x",
        "https://api.example.test/v1#fragment",
    ),
)
def test_baseline_rejects_unsafe_api_base_url(base_url: str) -> None:
    config = _config()
    config.llm.base_url = base_url

    with pytest.raises(Protocol22ExecutorError, match="base_url"):
        resolve_executor_catalog(config, "baseline", _registry())


@pytest.mark.unit
def test_loopback_http_transport_is_allowed_for_conformance() -> None:
    config = _config()
    config.llm.base_url = "http://127.0.0.1:8000/v1"

    entry = _baseline_entry(resolve_executor_catalog(config, "baseline", _registry()))

    assert entry.api_transport is not None
    assert entry.api_transport.base_url == "http://127.0.0.1:8000/v1"


@pytest.mark.unit
@pytest.mark.parametrize(
    "header",
    (
        ReV2BaselineHeaderConfig("authorization", "Bearer secret"),
        ReV2BaselineHeaderConfig("x-api-key", "secret"),
        ReV2BaselineHeaderConfig("cookie", "session=secret"),
    ),
)
def test_baseline_rejects_credential_bearing_headers(
    header: ReV2BaselineHeaderConfig,
) -> None:
    config = _config()
    config.llm.re_v2_baseline = replace(
        config.llm.re_v2_baseline,
        non_secret_headers=(header,),
    )

    with pytest.raises(Protocol22ExecutorError, match="credential"):
        resolve_executor_catalog(config, "baseline", _registry())


@pytest.mark.unit
def test_transport_rejects_duplicate_or_noncanonical_headers() -> None:
    with pytest.raises(Protocol22ExecutorError, match="sorted and unique"):
        ApiTransportAuthorityV1(
            authority_schema="api-transport-authority-v1",
            api_protocol_id="openai-chat-completions",
            api_protocol_version="1",
            base_url="https://api.example.test/v1",
            request_path="/chat/completions",
            non_secret_headers=(
                {"name": "x-route", "value": "one"},
                {"name": "x-route", "value": "two"},
            ),
        )


@pytest.mark.unit
def test_baseline_requires_hard_completion_cap_and_positive_deadline() -> None:
    no_cap = _config()
    no_cap.llm.max_tokens = None
    zero_deadline = _config()
    zero_deadline.llm.timeout_ms = 0

    with pytest.raises(Protocol22ExecutorError, match="completion cap"):
        resolve_executor_catalog(no_cap, "baseline", _registry())
    with pytest.raises(Protocol22ExecutorError, match="deadline"):
        resolve_executor_catalog(zero_deadline, "baseline", _registry())


@pytest.mark.unit
def test_baseline_rejects_wrong_generated_schema_authority() -> None:
    registry = replace(
        _registry(),
        response_schemas={
            "domain-baseline": digest("wrong"),
            "source-overview": response_schema_hash("source-overview"),
        },
    )

    with pytest.raises(Protocol22ExecutorError, match="response schema"):
        resolve_executor_catalog(_config(), "baseline", registry)


@pytest.mark.unit
def test_entry_rejects_deterministic_contract_with_provider_state() -> None:
    catalog = resolve_executor_catalog(_config(), "inventory", _registry())
    entry = catalog.entries[0]

    with pytest.raises(Protocol22ExecutorError, match="in_process"):
        replace(entry, provider_id="forbidden")


@pytest.mark.unit
def test_executor_catalog_rejects_empty_entries() -> None:
    with pytest.raises(Protocol22ExecutorError, match="nonempty"):
        ExecutorContractCatalogV1(schema_version=1, entries=())


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    ("verifier", "model", "request_renderer", "request_tokenizer", "generation"),
)
def test_api_entry_rejects_malformed_nested_provider_authority(field: str) -> None:
    entry = _baseline_entry(resolve_executor_catalog(_config(), "baseline", _registry()))

    with pytest.raises(Protocol22ExecutorError, match=field):
        replace(entry, **{field: object()})
