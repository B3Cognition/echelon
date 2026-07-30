from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.telemetry.provider import DispatchContext, InstrumentedProvider
from echelon.telemetry.store import TelemetryStore
from harness.squad_provider import SquadAgentResult


class _Provider:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def exec_agent(self, project_root: str, prompt: str, **kwargs: object) -> SquadAgentResult:
        if self.fail:
            raise RuntimeError("provider failed")
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}, "journal_entries": []},
            raw_output="secret response",
            duration_ms=12,
            timed_out=False,
            token_usage=17,
            token_usage_details={"input_tokens": 10, "output_tokens": 7},
            provider_name="codex",
            model_name="gpt-test",
        )


def _instrumented(tmp_path: Path, provider: object) -> tuple[InstrumentedProvider, TelemetryStore]:
    store = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "default"},
        trace_id="a" * 32,
    )
    return InstrumentedProvider(provider, store), store


def test_successful_dispatch_emits_one_content_free_span(tmp_path: Path) -> None:
    provider, store = _instrumented(tmp_path, _Provider())

    with provider.dispatch(DispatchContext("phase1-what", "specifier", "phase", 1)):
        provider.exec_agent(str(tmp_path), "secret prompt")

    spans, diagnostics = store.read_spans()
    assert diagnostics == ()
    assert len(spans) == 1
    span = spans[0]
    assert span.status == "OK"
    assert span.token_usage.total == 17
    assert span.attributes["echelon.workflow.phase"] == "phase1-what"
    assert span.attributes["echelon.agent.name"] == "specifier"
    assert span.attributes["echelon.dispatch.kind"] == "phase"
    assert span.attributes["echelon.dispatch.reason"] == "initial"
    assert span.attributes["gen_ai.response.model"] == "gpt-test"
    raw = (tmp_path / "telemetry/spans.jsonl").read_text(encoding="utf-8")
    assert "secret prompt" not in raw
    assert "secret response" not in raw
    event = (tmp_path / "telemetry/events.jsonl").read_text(encoding="utf-8")
    assert '"reason":"initial"' in event


def test_dispatch_context_rejects_unbounded_reason() -> None:
    with pytest.raises(ValueError, match="invalid dispatch reason"):
        DispatchContext("phase", "agent", "phase", 1, reason="llm_invented")


def test_provider_records_result_repair_as_separate_retry_event(tmp_path: Path) -> None:
    class RepairingProvider(_Provider):
        def exec_agent(self, project_root: str, prompt: str, **kwargs: object) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt, **kwargs)
            result.echelon_result_repair_attempted = True
            result.echelon_result_repair_duration_ms = 25
            result.echelon_result_repair_model_name = "gpt-repair"
            result.echelon_result_repair_outcome = "OK"
            result.echelon_result_repair_started_at = "2026-07-20T00:00:01Z"
            result.echelon_result_repair_ended_at = "2026-07-20T00:00:02Z"
            return result

    provider, _ = _instrumented(tmp_path, RepairingProvider())
    provider.exec_agent(str(tmp_path), "prompt")

    events = [json.loads(line) for line in (tmp_path / "telemetry/events.jsonl").read_text().splitlines()]
    retry = events[-1]
    assert retry["reason"] == "provider_retry"
    assert retry["duration_ms"] == 25
    assert retry["model"] == "gpt-repair"
    assert retry["started_at"] == "2026-07-20T00:00:01Z"


def test_provider_exception_emits_error_span_and_propagates(tmp_path: Path) -> None:
    provider, store = _instrumented(tmp_path, _Provider(fail=True))

    with pytest.raises(RuntimeError, match="provider failed"):
        with provider.dispatch(DispatchContext("phase1-why1", "sage", "judgment", 2)):
            provider.exec_agent(str(tmp_path), "secret prompt")

    spans, _ = store.read_spans()
    assert len(spans) == 1
    assert spans[0].status == "ERROR"
    assert spans[0].token_usage.known is False


def test_telemetry_append_failure_does_not_mask_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, store = _instrumented(tmp_path, _Provider(fail=True))

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise OSError("telemetry storage failed")

    monkeypatch.setattr(store, "append_span", fail_append)

    with pytest.raises(RuntimeError, match="provider failed"):
        provider.exec_agent(str(tmp_path), "secret prompt")


def test_telemetry_append_failure_does_not_fail_successful_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, store = _instrumented(tmp_path, _Provider())

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise OSError("telemetry storage failed")

    monkeypatch.setattr(store, "append_span", fail_append)

    result = provider.exec_agent(str(tmp_path), "secret prompt")

    assert result.exit_code == 0


def test_successful_dispatch_reports_usage_once(tmp_path: Path) -> None:
    recorded: list[int] = []
    store = TelemetryStore(
        tmp_path,
        workflow="spec",
        run_id="spec-1",
        profile={"name": "default"},
        trace_id="a" * 32,
    )
    provider = InstrumentedProvider(
        _Provider(), store, usage_recorder=lambda result: recorded.append(result.token_usage)
    )

    provider.exec_agent(str(tmp_path), "prompt")

    assert recorded == [17]


def test_raw_result_telemetry_does_not_invoke_hostile_scalar_protocols(
    tmp_path: Path,
) -> None:
    protocol_calls: list[str] = []

    class HostileInt(int):
        def __int__(self) -> int:
            protocol_calls.append("__int__")
            raise RuntimeError("raw telemetry secret")

        def __bool__(self) -> bool:
            protocol_calls.append("__bool__")
            raise RuntimeError("raw telemetry secret")

    class HostileString(str):
        def __str__(self) -> str:
            protocol_calls.append("__str__")
            raise RuntimeError("raw telemetry secret")

    class HostileProvider(_Provider):
        def exec_agent(
            self,
            project_root: str,
            prompt: str,
            **kwargs: object,
        ) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt, **kwargs)
            result.token_usage = HostileInt(17)
            result.token_usage_details = {
                "input_tokens": HostileInt(10),
            }
            result.model_name = HostileString("sensitive-model")
            return result

    provider, store = _instrumented(tmp_path, HostileProvider())

    result = provider.exec_agent(str(tmp_path), "prompt")

    assert type(result.token_usage) is HostileInt
    assert protocol_calls == []
    spans, diagnostics = store.read_spans()
    assert diagnostics == ()
    assert len(spans) == 1
    assert spans[0].token_usage.known is False
    assert "gen_ai.response.model" not in spans[0].attributes


def test_raw_result_status_does_not_invoke_hostile_boolean_protocol(
    tmp_path: Path,
) -> None:
    protocol_calls: list[str] = []

    class HostileTimedOut(int):
        def __bool__(self) -> bool:
            protocol_calls.append("__bool__")
            raise RuntimeError("raw status secret")

    class HostileProvider(_Provider):
        def exec_agent(
            self,
            project_root: str,
            prompt: str,
            **kwargs: object,
        ) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt, **kwargs)
            result.timed_out = HostileTimedOut(0)  # type: ignore[assignment]
            return result

    provider, store = _instrumented(tmp_path, HostileProvider())

    provider.exec_agent(str(tmp_path), "prompt")

    assert protocol_calls == []
    spans, _ = store.read_spans()
    assert spans[0].status == "ERROR"


def test_raw_result_token_telemetry_does_not_invoke_integer_protocol(
    tmp_path: Path,
) -> None:
    protocol_calls: list[str] = []

    class HostileInt(int):
        def __int__(self) -> int:
            protocol_calls.append("__int__")
            raise RuntimeError("raw token secret")

    class HostileProvider(_Provider):
        def exec_agent(
            self,
            project_root: str,
            prompt: str,
            **kwargs: object,
        ) -> SquadAgentResult:
            result = super().exec_agent(project_root, prompt, **kwargs)
            result.token_usage = HostileInt(17)
            result.token_usage_details = {
                "input_tokens": HostileInt(10),
            }
            return result

    provider, store = _instrumented(tmp_path, HostileProvider())

    provider.exec_agent(str(tmp_path), "prompt")

    assert protocol_calls == []
    spans, _ = store.read_spans()
    assert spans[0].token_usage.known is False


def test_raw_non_result_object_is_not_introspected(tmp_path: Path) -> None:
    protocol_calls: list[str] = []

    class HostileResult:
        def __getattribute__(self, name: str) -> object:
            protocol_calls.append(name)
            raise RuntimeError("raw object secret")

    class HostileProvider:
        def exec_agent(
            self,
            project_root: str,
            prompt: str,
            **kwargs: object,
        ) -> object:
            return HostileResult()

    provider, store = _instrumented(tmp_path, HostileProvider())

    result = provider.exec_agent(str(tmp_path), "prompt")

    assert type(result) is HostileResult
    assert protocol_calls == []
    spans, _ = store.read_spans()
    assert spans[0].status == "ERROR"
    assert spans[0].token_usage.known is False
