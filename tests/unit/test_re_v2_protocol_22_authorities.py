from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.protocol_22.authorities import (
    InstalledAuthorityRegistry,
    Protocol22AuthorityError,
    implementation_closure_digest,
    validate_installed_authorities,
)
from harness.re_v2.protocol_22.executors import resolve_executor_catalog
from harness.re_v2.protocol_22.response_schemas import response_schema_hash
from harness.config import HarnessConfig, LlmConfig, ReV2BaselineConfig
from tests.re_v2_protocol_22_fixtures import digest


def _registry() -> InstalledAuthorityRegistry:
    return InstalledAuthorityRegistry(
        executor_implementations={
            "bounded-api-baseline-v1": digest("api executor"),
            "re-v2-in-process-v1": digest("in-process executor"),
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
        },
        verifier_implementations={"compact-verifier-v1": digest("verifier")},
        partitioner_implementations={"existing-domain-partitioner": digest("partitioner")},
        ownership_implementations={"explicit-domain-ownership": digest("ownership")},
        agent_contracts={"echelon.re-baseliner": digest("agent contract")},
        response_schemas={
            "domain-baseline": response_schema_hash("domain-baseline"),
            "source-overview": response_schema_hash("source-overview"),
        },
    )


def _config() -> HarnessConfig:
    return HarnessConfig(
        provider="docker",
        llm=LlmConfig(
            enabled=True,
            cli="openai-compatible",
            base_url="https://api.example.test/v1",
            model="gpt-example",
            temperature=0.2,
            max_tokens=8192,
            timeout_ms=300_000,
            re_v2_baseline=ReV2BaselineConfig(
                model_revision="gpt-example-2026-08-01",
                revision_authority="provider_resolved_revision",
                provider_context_tokens=200_000,
                top_p="1.0",
                seed=None,
                request_path="/chat/completions",
                api_protocol_version="1",
                fixed_framing_byte_upper_bound=4096,
            ),
        ),
    )


@pytest.mark.unit
def test_closure_digest_ignores_install_path_and_input_order_but_not_bytes() -> None:
    first = implementation_closure_digest(
        {"provider.py": b"one\n", "schema.py": b"two\n"}
    )
    reordered = implementation_closure_digest(
        {"schema.py": b"two\n", "provider.py": b"one\n"}
    )
    changed = implementation_closure_digest(
        {"provider.py": b"changed\n", "schema.py": b"two\n"}
    )

    assert first == reordered
    assert first != changed


@pytest.mark.unit
@pytest.mark.parametrize("path", ("/absolute.py", "../escape.py", "a/../b.py", ""))
def test_closure_digest_rejects_unsafe_logical_paths(path: str) -> None:
    with pytest.raises(Protocol22AuthorityError, match="logical path"):
        implementation_closure_digest({path: b"payload"})


@pytest.mark.unit
def test_registry_is_closed_and_immutable() -> None:
    registry = _registry()

    with pytest.raises(TypeError):
        registry.executor_implementations["new"] = digest("new")  # type: ignore[index]
    with pytest.raises(Protocol22AuthorityError, match="digest"):
        replace(
            registry,
            calculator_implementations={"bounded-dispatch-v1": "not-a-digest"},
        )


@pytest.mark.unit
def test_installed_authority_validation_reports_all_drift_without_mutation() -> None:
    registry = _registry()
    catalog = resolve_executor_catalog(_config(), "baseline", registry)
    drifted = replace(
        registry,
        executor_implementations={
            **registry.executor_implementations,
            "bounded-api-baseline-v1": digest("changed executor"),
        },
        renderer_implementations={},
        verifier_implementations={
            "compact-verifier-v1": digest("changed verifier"),
        },
        response_schemas={
            **registry.response_schemas,
            "domain-baseline": digest("wrong schema"),
        },
    )

    mismatches = validate_installed_authorities(catalog, drifted)

    assert [(item.authority_kind, item.authority_id) for item in mismatches] == [
        ("executor", "bounded-api-baseline-v1"),
        ("renderer", "compact-baseline-renderer-v1"),
        ("response_schema", "domain-baseline"),
        ("verifier", "compact-verifier-v1"),
    ]
    assert mismatches[1].installed_digest is None
    assert validate_installed_authorities(catalog, registry) == ()
