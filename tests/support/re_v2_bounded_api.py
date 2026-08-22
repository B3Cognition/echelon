from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Lock, Thread
import time
from typing import Mapping


@dataclass(frozen=True, slots=True)
class CapturedRequest:
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes

    @property
    def json(self) -> object:
        return json.loads(self.body)


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    status: int = 200
    body: object = field(default_factory=dict)
    delay_seconds: float = 0.0
    headers: Mapping[str, str] = field(default_factory=dict)


class ScriptedBoundedApi:
    """Loopback one-call fixture with observable requests and scripted responses."""

    def __init__(
        self,
        responses: tuple[ScriptedResponse, ...] = (),
        *,
        responses_by_work_item: Mapping[
            str, tuple[ScriptedResponse, ...]
        ] | None = None,
        work_item_markers: Mapping[str, str] | None = None,
        default_response: ScriptedResponse | None = None,
    ) -> None:
        self._responses = list(responses)
        self._default_response = default_response
        self.responses_by_work_item = {
            work_item_id: list(script)
            for work_item_id, script in (responses_by_work_item or {}).items()
        }
        self.work_item_markers = dict(work_item_markers or {})
        self._lock = Lock()
        self.requests: list[CapturedRequest] = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("content-length", "0"))
                body = self.rfile.read(length)
                captured = CapturedRequest(
                    method="POST",
                    path=self.path,
                    headers={key.lower(): value for key, value in self.headers.items()},
                    body=body,
                )
                with fixture._lock:
                    fixture.requests.append(captured)
                    response = fixture._select_response(captured)
                if response.delay_seconds:
                    time.sleep(response.delay_seconds)
                payload = (
                    response.body
                    if isinstance(response.body, bytes)
                    else json.dumps(
                        response.body,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                try:
                    self.send_response(response.status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(payload)))
                    for name, value in response.headers.items():
                        self.send_header(name, value)
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, format: str, *args: object) -> None:
                del format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        host, port = self._server.server_address[:2]
        self.base_url = f"http://{host}:{port}/v1"
        self._thread = Thread(target=self._server.serve_forever, daemon=True)

    @classmethod
    def for_scenario(cls, scenario: str) -> "ScriptedBoundedApi":
        if scenario in {"valid", "complete", "invalid-domain", "large-source"}:
            if scenario == "valid":
                return cls((ScriptedResponse(body=valid_response()),))
            return cls(
                default_response=ScriptedResponse(body=valid_response())
            )
        if scenario == "executor-breach":
            response = valid_response()
            response["usage"] = {
                "prompt_tokens": 300_000,
                "completion_tokens": 1,
                "total_tokens": 300_001,
            }
            return cls((ScriptedResponse(body=response),))
        if scenario == "timeout":
            return cls(
                (
                    ScriptedResponse(
                        body=valid_response(),
                        delay_seconds=0.25,
                    ),
                )
            )
        if scenario == "http_error":
            return cls((ScriptedResponse(status=503, body={"error": "unavailable"}),))
        raise ValueError(f"unknown bounded API scenario: {scenario}")

    def enqueue(self, response: ScriptedResponse) -> None:
        with self._lock:
            self._responses.append(response)

    def script_work_item(
        self,
        work_item_id: str,
        responses: tuple[ScriptedResponse, ...],
        *,
        context_marker: str | None = None,
    ) -> None:
        """Associate a response sequence with a stable marker in user context."""
        if not work_item_id or not responses:
            raise ValueError("work-item scripts require an ID and responses")
        with self._lock:
            self.responses_by_work_item[work_item_id] = list(responses)
            self.work_item_markers[work_item_id] = context_marker or work_item_id

    def _select_response(self, request: CapturedRequest) -> ScriptedResponse:
        try:
            raw = request.json
            messages = raw["messages"]
            user_content = next(
                message["content"]
                for message in messages
                if message.get("role") == "user"
            )
        except (KeyError, StopIteration, TypeError):
            user_content = ""
        for work_item_id in sorted(self.responses_by_work_item):
            marker = self.work_item_markers.get(work_item_id, work_item_id)
            script = self.responses_by_work_item[work_item_id]
            if marker in user_content and script:
                return script.pop(0)
        if self._responses:
            return self._responses.pop(0)
        if self._default_response is not None:
            return self._default_response
        return ScriptedResponse(status=500, body={"error": "unscripted"})

    def __enter__(self) -> "ScriptedBoundedApi":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        del exc
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


def valid_response(
    *,
    content: object = '{"schema_version":1,"surfaces":{},"unknowns":[]}',
    model: str = "gpt-example-2026-08-01",
    usage: object = None,
) -> dict[str, object]:
    if usage is None:
        usage = {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        }
    return {
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "refusal": None,
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


__all__ = (
    "CapturedRequest",
    "ScriptedBoundedApi",
    "ScriptedResponse",
    "valid_response",
)
