"""Versioned, content-minimizing execution telemetry records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
import re
from typing import Iterable, Mapping


_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
_COMPLETION_ID_PATTERN = re.compile(r"\A[0-9a-f]{32}\Z")


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
        component_total = sum(int(getattr(self, name) or 0) for name in _TOKEN_KEYS)
        # Some providers emit a zero aggregate while still supplying usable
        # per-category counts. Preserve the more informative observation.
        if self.reported_total_tokens is not None and not (
            self.reported_total_tokens == 0 and component_total > 0
        ):
            return self.reported_total_tokens
        return component_total

    def to_json_dict(self) -> dict[str, int | None]:
        result = {name: getattr(self, name) for name in _TOKEN_KEYS}
        result["total_tokens"] = self.total
        return result


def aggregate_token_usage(usages: Iterable[TokenUsage]) -> TokenUsage:
    """Combine observed dispatch usage without inventing missing components."""
    known = tuple(usage for usage in usages if usage.known)
    if not known:
        return TokenUsage.unknown()

    def component(name: str) -> int | None:
        values = [getattr(usage, name) for usage in known]
        observed = [value for value in values if value is not None]
        return sum(observed) if observed else None

    return TokenUsage(
        **{name: component(name) for name in _TOKEN_KEYS},
        reported_total_tokens=sum(int(usage.total or 0) for usage in known),
    )


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
class PhaseTimingEvent:
    """An immutable phase lifecycle observation kept outside controller state."""

    trace_id: str
    phase: str
    event: str
    event_time: str
    budget_seconds: float
    elapsed_seconds: float | None = None
    over_budget: bool | None = None
    completion_id: str | None = None
    effect_id: str | None = None

    @classmethod
    def started(
        cls,
        *,
        trace_id: str,
        phase: str,
        budget_seconds: float,
        event_time: str,
        completion_id: str | None = None,
        effect_id: str | None = None,
    ) -> "PhaseTimingEvent":
        return cls(
            trace_id=trace_id,
            phase=phase,
            event="started",
            event_time=event_time,
            budget_seconds=budget_seconds,
            completion_id=completion_id,
            effect_id=effect_id,
        )

    @classmethod
    def finished(
        cls,
        *,
        trace_id: str,
        phase: str,
        budget_seconds: float,
        elapsed_seconds: float,
        event_time: str,
        completion_id: str | None = None,
        effect_id: str | None = None,
    ) -> "PhaseTimingEvent":
        return cls(
            trace_id=trace_id,
            phase=phase,
            event="finished",
            event_time=event_time,
            budget_seconds=budget_seconds,
            elapsed_seconds=elapsed_seconds,
            over_budget=elapsed_seconds > budget_seconds * 1.2 if budget_seconds > 0 else False,
            completion_id=completion_id,
            effect_id=effect_id,
        )

    def to_json_dict(self) -> dict[str, object]:
        record: dict[str, object] = {
            "schema_version": 1,
            "type": "phase_timing",
            "trace_id": self.trace_id,
            "phase": self.phase,
            "event": self.event,
            "event_time": self.event_time,
            "budget_seconds": self.budget_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "over_budget": self.over_budget,
        }
        if self.completion_id is not None:
            record["completion_id"] = self.completion_id
            record["effect_id"] = self.effect_id
        return record

    @classmethod
    def from_json_dict(cls, value: Mapping[str, object]) -> "PhaseTimingEvent":
        if value.get("schema_version") != 1 or value.get("type") != "phase_timing":
            raise ValueError("invalid phase timing event")
        event = value.get("event")
        if event not in {"started", "finished"}:
            raise ValueError("invalid phase timing event kind")
        trace_id = value.get("trace_id")
        phase = value.get("phase")
        event_time = value.get("event_time")
        budget = value.get("budget_seconds")
        if (
            not isinstance(trace_id, str)
            or not trace_id
            or not isinstance(phase, str)
            or not phase
            or not isinstance(event_time, str)
            or not event_time
            or isinstance(budget, bool)
            or not isinstance(budget, (int, float))
        ):
            raise ValueError("invalid phase timing event fields")
        elapsed = value.get("elapsed_seconds")
        if elapsed is not None and (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))):
            raise ValueError("invalid phase timing elapsed seconds")
        over_budget = value.get("over_budget")
        if over_budget is not None and not isinstance(over_budget, bool):
            raise ValueError("invalid phase timing over-budget value")
        completion_id = value.get("completion_id")
        effect_id = value.get("effect_id")
        if completion_id is not None or effect_id is not None:
            expected_keys = frozenset(
                {
                    "schema_version",
                    "type",
                    "trace_id",
                    "phase",
                    "event",
                    "event_time",
                    "budget_seconds",
                    "elapsed_seconds",
                    "over_budget",
                    "completion_id",
                    "effect_id",
                }
            )
            if frozenset(value) != expected_keys:
                raise ValueError(
                    "invalid phase timing completion identity"
                )
        if (completion_id is None) != (effect_id is None):
            raise ValueError("invalid phase timing completion identity")
        if completion_id is not None and (
            type(completion_id) is not str
            or _COMPLETION_ID_PATTERN.fullmatch(completion_id) is None
            or type(effect_id) is not str
            or effect_id
            != (
                f"{completion_id}:timing:"
                f"{'open' if event == 'started' else 'close'}:{phase}"
            )
            or len(effect_id) > 2_048
        ):
            raise ValueError("invalid phase timing completion identity")
        if completion_id is not None:
            normalized_time = (
                event_time[:-1] + "+00:00"
                if event_time.endswith("Z")
                else event_time
            )
            try:
                datetime.fromisoformat(normalized_time)
            except ValueError as exc:
                raise ValueError(
                    "invalid phase timing completion timestamp"
                ) from exc
            if (
                not math.isfinite(float(budget))
                or float(budget) < 0
            ):
                raise ValueError(
                    "invalid phase timing completion budget"
                )
        if (
            event == "started"
            and (elapsed is not None or over_budget is not None)
        ) or (
            event == "finished"
            and (elapsed is None or over_budget is None)
        ):
            raise ValueError("invalid phase timing event shape")
        if event == "finished" and completion_id is not None:
            assert elapsed is not None
            expected_over_budget = (
                float(elapsed) > float(budget) * 1.2
                if float(budget) > 0
                else False
            )
            if (
                not math.isfinite(float(elapsed))
                or float(elapsed) < 0
                or over_budget is not expected_over_budget
            ):
                raise ValueError(
                    "invalid phase timing completion elapsed value"
                )
        return cls(
            trace_id=trace_id,
            phase=phase,
            event=str(event),
            event_time=event_time,
            budget_seconds=float(budget),
            elapsed_seconds=float(elapsed) if elapsed is not None else None,
            over_budget=over_budget,
            completion_id=completion_id,
            effect_id=effect_id,
        )


@dataclass(frozen=True)
class TelemetryDiagnostic:
    code: str
    message: str
    line: int | None = None
