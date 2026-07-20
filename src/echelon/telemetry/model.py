"""Versioned, content-minimizing execution telemetry records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reported_total_tokens: int | None = None

    @classmethod
    def unknown(cls) -> "TokenUsage":
        return cls()

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> "TokenUsage":
        if not isinstance(value, Mapping):
            return cls.unknown()

        def component(name: str) -> int | None:
            raw = value.get(name)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                return None
            parsed = int(raw)
            return parsed if parsed >= 0 else None

        components = {name: component(name) for name in _TOKEN_KEYS}
        components["input_tokens"] = components["input_tokens"] or component(
            "prompt_tokens"
        )
        components["output_tokens"] = components["output_tokens"] or component(
            "completion_tokens"
        )
        return cls(
            **components,
            reported_total_tokens=component("total_tokens"),
        )

    @property
    def known(self) -> bool:
        return self.reported_total_tokens is not None or any(
            getattr(self, name) is not None for name in _TOKEN_KEYS
        )

    @property
    def total(self) -> int | None:
        if not self.known:
            return None
        if self.reported_total_tokens is not None:
            return self.reported_total_tokens
        return sum(int(getattr(self, name) or 0) for name in _TOKEN_KEYS)

    def to_json_dict(self) -> dict[str, int | None]:
        result = {name: getattr(self, name) for name in _TOKEN_KEYS}
        result["total_tokens"] = self.total
        return result


@dataclass(frozen=True)
class ExecutionSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_time: str
    end_time: str
    duration_ms: int
    status: str
    attributes: dict[str, object] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage.unknown)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": dict(sorted(self.attributes.items())),
            "token_usage": self.token_usage.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: Mapping[str, object]) -> "ExecutionSpan":
        required = ("trace_id", "span_id", "name", "start_time", "end_time", "status")
        if value.get("schema_version") != 1 or any(not value.get(key) for key in required):
            raise ValueError("invalid execution span record")
        duration = value.get("duration_ms")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            raise ValueError("invalid execution span duration")
        attributes = value.get("attributes")
        return cls(
            trace_id=str(value["trace_id"]),
            span_id=str(value["span_id"]),
            parent_span_id=(
                str(value["parent_span_id"])
                if value.get("parent_span_id") is not None
                else None
            ),
            name=str(value["name"]),
            start_time=str(value["start_time"]),
            end_time=str(value["end_time"]),
            duration_ms=int(duration),
            status=str(value["status"]),
            attributes=dict(attributes) if isinstance(attributes, Mapping) else {},
            token_usage=TokenUsage.from_mapping(
                value.get("token_usage") if isinstance(value.get("token_usage"), Mapping) else None
            ),
        )


@dataclass(frozen=True)
class TelemetryDiagnostic:
    code: str
    message: str
    line: int | None = None
