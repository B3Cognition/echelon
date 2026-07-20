from __future__ import annotations

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
