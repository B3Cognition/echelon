"""Echelon's compatibility adapter must not broaden explicit Prosaic grants."""
import json
import io

import pytest

from prosaic_runtime.openai_compatible import OpenAICompatibleBackend as SharedBackend
from prosaic_runtime.events import event_context
from harness.ai_cli_backend import CliRunRequest
from harness.ai_cli_backends.openai_compatible import OpenAICompatibleBackend, _OpenAIToolRegistry
from harness.config import HarnessConfig, LlmConfig


def _write(registry):
    result = registry.execute_message({"id": "write", "function": {
        "name": "write_file", "arguments": '{"path":"output","content":"bad"}'}})
    return json.loads(result["content"])


def test_echelon_inherits_shared_transport():
    assert issubclass(OpenAICompatibleBackend, SharedBackend)


def test_explicit_read_role_cannot_write(tmp_path):
    registry = _OpenAIToolRegistry(tmp_path, {}, {"tools": "read"})
    assert "write_file" not in {item["function"]["name"] for item in registry.openai_tools()}
    assert _write(registry)["status"] == "error"
    assert not (tmp_path / "output").exists()


def test_exclusive_empty_write_scope_denies_writes(tmp_path):
    registry = _OpenAIToolRegistry(tmp_path, {}, {"tool_write_scope_exclusive": True, "tool_write_paths": []})
    assert _write(registry)["status"] == "error"
    assert not (tmp_path / "output").exists()


def _response(message, streaming):
    if streaming:
        delta = dict(message)
        if "tool_calls" in delta:
            delta["tool_calls"] = [{"index": 0, **delta["tool_calls"][0]}]
        data = ("data: " + json.dumps({"choices": [{"delta": delta,
                "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}]})
                + "\n\ndata: [DONE]\n\n")
    else:
        data = json.dumps({"choices": [{"message": message,
                           "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}]})
    response = io.BytesIO(data.encode())
    response.status = 200
    response.headers = {"Content-Type": "text/event-stream" if streaming else "application/json"}
    return response


def _backend(tmp_path, streaming):
    return OpenAICompatibleBackend(HarnessConfig(target_repo=str(tmp_path), llm=LlmConfig(
        cli="openai-compatible", base_url="http://127.0.0.1:8000/v1", model="fixture-model",
        features={"tool_calls": True, "streaming": streaming},
    )))


def _read_request(tmp_path, prompt):
    return CliRunRequest(cwd=str(tmp_path), prompt=prompt, env={}, timeout_s=10,
        metadata={"prompt_metadata": {"tools": "read", "allowed_tools": ["read_file"],
            "tool_read_roots": [str(tmp_path / "evidence")],
            "tool_write_scope_exclusive": True, "tool_write_paths": [],
            "initial_tool": "read_file"}})


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("final_text", [
    '{"canary":"READ_CANARY_927"}',
    "echelon_result:\n  canary: READ_CANARY_927\n",
])
def test_tool_transport_leaves_output_contract_to_caller(
    tmp_path, monkeypatch, streaming, final_text,
):
    """Native reads must not add a competing global final-response contract."""
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence/input.txt").write_text("READ_CANARY_927\n")
    payloads = []

    def endpoint(request, timeout):
        payload = json.loads(request.data)
        payloads.append(payload)
        if len(payloads) == 1:
            return _response({"content": None, "tool_calls": [{"id": "read-1",
                "type": "function", "function": {"name": "read_file",
                "arguments": '{"path":"evidence/input.txt"}'}}]}, streaming)
        tool_message = payload["messages"][-1]
        assert tool_message["role"] == "tool"
        assert json.loads(tool_message["content"])["content"] == "1: READ_CANARY_927"
        return _response({"content": final_text}, streaming)

    monkeypatch.setattr("harness.ai_cli_backends.openai_compatible.urllib.request.urlopen", endpoint)
    result = _backend(tmp_path, streaming).run_agent(_read_request(tmp_path,
        'Call read_file with path="evidence/input.txt", then use the returned canary '
        f'in this exact final-response format: {final_text}'))

    assert result.exit_code == 0
    assert result.stdout == final_text
    assert len(payloads) == 2
    assert payloads[0]["tool_choice"] == {"type": "function", "function": {"name": "read_file"}}
    assert [tool["function"]["name"] for tool in payloads[0]["tools"]] == ["read_file"]
    assert "echelon_result" not in payloads[0]["messages"][0]["content"]


@pytest.mark.parametrize("streaming", [False, True])
def test_endpoint_skipping_required_native_read_is_rejected(tmp_path, monkeypatch, streaming):
    """Text claiming a read is not a native tool receipt, in either transport."""
    (tmp_path / "evidence").mkdir()
    evidence = tmp_path / "evidence/input.txt"
    evidence.write_text("UNREAD_CANARY_813\n")
    monkeypatch.setattr("harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        lambda request, timeout: _response({"content": "I read the file: guessed value"}, streaming))
    events = []
    with event_context(events.append):
        result = _backend(tmp_path, streaming).run_agent(_read_request(tmp_path,
            'Call read_file with path="evidence/input.txt" now; return the actual canary.'))
    assert result.exit_code == 1
    assert result.metadata["provider_error_code"] == "tool_choice_not_honored"
    assert not any(event["event"] == "tool_completed" for event in events)
    assert evidence.read_text() == "UNREAD_CANARY_813\n"
