from __future__ import annotations

import json

from typer.testing import CliRunner

from echelon.cli_app import app


def test_llm_smoke_openai_compatible_exercises_tool_loop(tmp_path, monkeypatch) -> None:
    captured_payloads = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCAL_LLM_API_KEY", "secret")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(self._payload).encode()

    responses = iter([
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_read",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({
                                        "path": "smoke-input.txt",
                                    }),
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"total_tokens": 4},
        },
        {
            "choices": [
                {
                    "message": {"content": "echelon_result:\n  verdict: PASS\n"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        },
    ])

    def fake_urlopen(request, timeout):
        captured_payloads.append(json.loads(request.data.decode()))
        return FakeResponse(next(responses))

    monkeypatch.setattr(
        "harness.ai_cli_backends.openai_compatible.urllib.request.urlopen",
        fake_urlopen,
    )

    result = CliRunner().invoke(app, [
        "llm",
        "smoke-openai-compatible",
        "--base-url",
        "http://127.0.0.1:8000/v1",
        "--model",
        "local-model",
        "--api-key-env",
        "LOCAL_LLM_API_KEY",
        "--no-streaming",
    ])

    assert result.exit_code == 0
    assert "OpenAI-compatible smoke: ok" in result.output
    assert "tool_calls=1" in result.output
    assert "transcript:" in result.output
    assert captured_payloads[0]["model"] == "local-model"
    assert captured_payloads[0]["tools"]
    assert captured_payloads[1]["messages"][-1]["role"] == "tool"
