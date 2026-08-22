from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import time

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.executors import resolve_executor_catalog
from harness.re_v2.protocol_22.model import ExecutionInputV1
from harness.re_v2.protocol_22.provider import (
    BoundedApiBaselineExecutor,
    Protocol22ProviderError,
    calculate_bounded_dispatch_reservation,
    normalize_openai_usage,
    render_provider_request_envelope,
)
from harness.re_v2.protocol_22.response_schemas import (
    canonical_response_schema_bytes,
    response_schema_hash,
)
from tests.support.re_v2_bounded_api import (
    ScriptedBoundedApi,
    ScriptedResponse,
    valid_response,
)
from tests.unit.test_re_v2_protocol_22_executors import _config, _registry
from tests.unit.test_re_v2_protocol_22_provider import (
    AGENT_BYTES,
    _authority,
    _tokenizer,
)


def _setup(api: ScriptedBoundedApi, tmp_path: Path):  # type: ignore[no-untyped-def]
    config = _config()
    config.llm.base_url = api.base_url
    executor = resolve_executor_catalog(
        config,
        "baseline",
        _registry(),
    ).entry_for("compact-baseline")
    original_item, _original_executor, context = _authority()
    item = replace(
        original_item,
        executor_contract_hash=executor.executor_contract_hash,
    )
    envelope = render_provider_request_envelope(
        item,
        "dispatch-1",
        AGENT_BYTES,
        context,
        executor,
        response_schema_hash("domain-baseline"),
    )
    schema = canonical_response_schema_bytes("domain-baseline")
    reservation = calculate_bounded_dispatch_reservation(
        envelope,
        schema,
        executor,
        _tokenizer(executor, None),
    )
    execution_input = ExecutionInputV1(
        schema_version=1,
        dispatch_id=envelope.dispatch_id,
        work_item_id=envelope.work_item_id,
        attempt_kind="initial_generation",
        executor_contract_hash=envelope.executor_contract_hash,
        agent_contract_hash=content_digest(AGENT_BYTES),
        context_bundle_hash=content_digest(context),
        provider_request_envelope_hash=envelope.identity,
        deterministic_invocation=None,
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    adapter = BoundedApiBaselineExecutor(
        executor,
        credential_loader=lambda: ("authorization", "Bearer test-secret"),
    )
    return adapter, execution_input, envelope, reservation, candidate_root, executor


def _execute(
    api: ScriptedBoundedApi,
    tmp_path: Path,
    *,
    timeout_seconds: float = 2.0,
):  # type: ignore[no-untyped-def]
    adapter, execution_input, envelope, reservation, root, executor = _setup(
        api,
        tmp_path,
    )
    result = adapter.execute(
        execution_input,
        envelope,
        reservation,
        root,
        time.monotonic() + timeout_seconds,
    )
    return result, root, executor


def test_one_call_request_is_strict_bounded_and_tool_free(tmp_path: Path) -> None:
    content = '{"schema_version":1,"surfaces":{},"unknowns":[]}'
    with ScriptedBoundedApi(
        (ScriptedResponse(body=valid_response(content=content)),)
    ) as api:
        result, root, executor = _execute(api, tmp_path)

    assert result.outcome == "candidate_ready"
    assert result.stdout == (
        b"echelon_result:\n"
        b"  schema_version: 1\n"
        b"  outcome: candidate_ready\n"
    )
    assert result.stderr == b""
    assert (root / "baseline.json").read_bytes() == content.encode()
    assert len(api.requests) == 1
    request = api.requests[0]
    assert request.method == "POST"
    assert request.path == "/v1/chat/completions"
    assert set(request.headers) == {
        "authorization",
        "content-length",
        "content-type",
        "host",
        "openai-organization",
    }
    assert request.headers["authorization"] == "Bearer test-secret"
    assert request.headers["openai-organization"] == "org-example"
    body = request.json
    assert body["max_completion_tokens"] == (
        executor.limits.max_completion_tokens_per_call
    )
    assert body["tools"] == []
    assert body["tool_choice"] == "none"
    assert body["stream"] is False
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert "seed" not in body
    assert result.provider_usage == canonical_json_bytes(
        valid_response()["usage"]
    )
    assert result.timing.duration_ms >= 0
    assert result.timing.started_at.endswith("Z")
    assert result.timing.ended_at.endswith("Z")


def test_fixture_selects_a_response_script_by_work_item_context(
    tmp_path: Path,
) -> None:
    content = '{"schema_version":1,"surfaces":{"scripted":[]},"unknowns":[]}'
    marker = '"target_artifact_kind":"domain-baseline"'
    with ScriptedBoundedApi(
        responses_by_work_item={
            "domain-item": (
                ScriptedResponse(body=valid_response(content=content)),
            )
        },
        work_item_markers={"domain-item": marker},
    ) as api:
        result, root, _executor = _execute(api, tmp_path)

    assert result.outcome == "candidate_ready"
    assert (root / "baseline.json").read_text() == content
    assert len(api.requests) == 1


def _invalid_response(case: str) -> object:
    response = valid_response()
    if case == "multiple_choices":
        response["choices"] = [response["choices"][0], response["choices"][0]]
    elif case == "non_string_content":
        response["choices"][0]["message"]["content"] = {"bad": True}
    elif case == "refusal":
        response["choices"][0]["message"]["refusal"] = "no"
    elif case == "tool_calls":
        response["choices"][0]["message"]["tool_calls"] = [
            {"type": "function", "function": {"name": "escape"}}
        ]
    elif case == "tool_finish_reason":
        response["choices"][0]["finish_reason"] = "tool_calls"
    elif case == "model_revision":
        response["model"] = "mutable-model-alias"
    else:  # pragma: no cover - test authoring guard
        raise AssertionError(case)
    return response


@pytest.mark.parametrize(
    "case",
    (
        "multiple_choices",
        "non_string_content",
        "refusal",
        "tool_calls",
        "tool_finish_reason",
        "model_revision",
    ),
)
def test_invalid_authorial_response_never_extracts_prose_or_retries(
    tmp_path: Path,
    case: str,
) -> None:
    with ScriptedBoundedApi(
        (ScriptedResponse(body=_invalid_response(case)),)
    ) as api:
        result, root, _executor = _execute(api, tmp_path)

    assert result.outcome == "invalid_response"
    assert result.stdout == b""
    assert result.stderr
    assert list(root.iterdir()) == []
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    ("response", "outcome"),
    (
        (ScriptedResponse(status=503, body={"error": "unavailable"}), "http_error"),
        (ScriptedResponse(body=b"not-json"), "invalid_response"),
    ),
)
def test_http_and_json_failures_make_one_call_and_no_candidate(
    tmp_path: Path,
    response: ScriptedResponse,
    outcome: str,
) -> None:
    with ScriptedBoundedApi((response,)) as api:
        result, root, _executor = _execute(api, tmp_path)

    assert result.outcome == outcome
    assert list(root.iterdir()) == []
    assert len(api.requests) == 1


def test_deadline_timeout_aborts_without_retry(tmp_path: Path) -> None:
    with ScriptedBoundedApi(
        (ScriptedResponse(body=valid_response(), delay_seconds=0.25),)
    ) as api:
        result, root, _executor = _execute(
            api,
            tmp_path,
            timeout_seconds=0.05,
        )

    assert result.outcome == "timed_out"
    assert list(root.iterdir()) == []
    assert len(api.requests) == 1


def test_expired_deadline_never_issues_request(tmp_path: Path) -> None:
    with ScriptedBoundedApi((ScriptedResponse(body=valid_response()),)) as api:
        adapter, execution_input, envelope, reservation, root, _executor = _setup(
            api,
            tmp_path,
        )
        result = adapter.execute(
            execution_input,
            envelope,
            reservation,
            root,
            time.monotonic() - 1,
        )

    assert result.outcome == "timed_out"
    assert api.requests == []
    assert list(root.iterdir()) == []


def test_candidate_publish_cannot_follow_a_replaced_root(tmp_path: Path) -> None:
    response = ScriptedResponse(body=valid_response(), delay_seconds=0.25)
    with ScriptedBoundedApi((response,)) as api:
        adapter, execution_input, envelope, reservation, root, _executor = _setup(
            api,
            tmp_path,
        )
        escaped = tmp_path / "escaped"
        escaped.mkdir()
        parked = tmp_path / "parked"
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                adapter.execute,
                execution_input,
                envelope,
                reservation,
                root,
                time.monotonic() + 2,
            )
            request_deadline = time.monotonic() + 1
            while not api.requests and time.monotonic() < request_deadline:
                time.sleep(0.005)
            assert len(api.requests) == 1
            root.rename(parked)
            root.symlink_to(escaped, target_is_directory=True)
            with pytest.raises(Protocol22ProviderError, match="candidate"):
                future.result(timeout=2)

    assert list(escaped.iterdir()) == []
    assert list(parked.iterdir()) == []


@pytest.mark.parametrize(
    ("usage", "expected_status"),
    (
        (None, "unavailable"),
        (
            {
                "prompt_tokens": 2,
                "completion_tokens": 1,
                "total_tokens": 3,
                "unknown_tokens": 1,
            },
            "untrusted",
        ),
        (
            {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            "trusted_exact",
        ),
    ),
)
def test_usage_is_preserved_losslessly_and_normalized_conservatively(
    tmp_path: Path,
    usage: object,
    expected_status: str,
) -> None:
    response = valid_response()
    if usage is None:
        response.pop("usage")
    else:
        response["usage"] = usage
    with ScriptedBoundedApi((ScriptedResponse(body=response),)) as api:
        result, _root, executor = _execute(api, tmp_path)

    expected_bytes = None if usage is None else canonical_json_bytes(usage)
    assert result.provider_usage == expected_bytes
    normalized_input = (
        None if result.provider_usage is None else json.loads(result.provider_usage)
    )
    assert normalize_openai_usage(
        normalized_input,
        executor.token_accounting,
    ).status == expected_status


def test_missing_completion_cap_or_reservation_mismatch_fails_before_call(
    tmp_path: Path,
) -> None:
    with ScriptedBoundedApi((ScriptedResponse(body=valid_response()),)) as api:
        adapter, execution_input, envelope, reservation, root, _executor = _setup(
            api,
            tmp_path,
        )
        missing_cap = replace(
            envelope,
            generation=replace(
                envelope.generation,
                max_completion_tokens=envelope.generation.max_completion_tokens - 1,
            ),
        )
        with pytest.raises(Protocol22ProviderError, match="completion cap"):
            adapter.execute(
                execution_input,
                missing_cap,
                reservation,
                root,
                time.monotonic() + 1,
            )
        with pytest.raises(Protocol22ProviderError, match="reservation"):
            adapter.execute(
                execution_input,
                envelope,
                replace(reservation, billable_tokens=reservation.billable_tokens + 1),
                root,
                time.monotonic() + 1,
            )

    assert api.requests == []


def test_credential_is_loaded_only_at_dispatch_and_not_stored_in_body(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    with ScriptedBoundedApi((ScriptedResponse(body=valid_response()),)) as api:
        adapter, execution_input, envelope, reservation, root, executor = _setup(
            api,
            tmp_path,
        )
        adapter = BoundedApiBaselineExecutor(
            executor,
            credential_loader=lambda: (
                calls.append("loaded") or "authorization",
                "Bearer rotated-secret",
            ),
        )
        assert calls == []
        adapter.execute(
            execution_input,
            envelope,
            reservation,
            root,
            time.monotonic() + 2,
        )

    assert calls == ["loaded"]
    assert api.requests[0].headers["authorization"] == "Bearer rotated-secret"
    assert b"rotated-secret" not in api.requests[0].body


def test_input_or_credential_failure_makes_zero_requests(tmp_path: Path) -> None:
    with ScriptedBoundedApi((ScriptedResponse(body=valid_response()),)) as api:
        adapter, execution_input, envelope, reservation, root, executor = _setup(
            api,
            tmp_path,
        )
        with pytest.raises(Protocol22ProviderError, match="execution input"):
            adapter.execute(
                replace(execution_input, dispatch_id="different-dispatch"),
                envelope,
                reservation,
                root,
                time.monotonic() + 1,
            )
        no_credential = BoundedApiBaselineExecutor(
            executor,
            credential_loader=lambda: None,
        )
        with pytest.raises(Protocol22ProviderError, match="credential"):
            no_credential.execute(
                execution_input,
                envelope,
                reservation,
                root,
                time.monotonic() + 1,
            )

    assert api.requests == []
