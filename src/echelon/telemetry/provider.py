"""Content-free execution telemetry at the shared provider boundary."""

from __future__ import annotations

import contextvars
import inspect
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.store import TelemetryStore


logger = logging.getLogger(__name__)

DISPATCH_REASONS = frozenset({"initial", "planned_iteration", "semantic_repair", "deterministic_repair", "provider_retry", "resume", "manual_rerun"})


@dataclass(frozen=True)
class DispatchContext:
    phase: str
    agent: str
    kind: str
    attempt: int
    reason: str = "initial"

    def __post_init__(self) -> None:
        if self.reason not in DISPATCH_REASONS:
            raise ValueError(f"invalid dispatch reason: {self.reason!r}")


class InstrumentedProvider:
    """Decorate an agent provider and emit exactly one span for every call."""

    def __init__(
        self,
        provider: object,
        store: TelemetryStore,
        *,
        usage_recorder: Callable[[object], None] | None = None,
    ) -> None:
        self._provider = provider
        self._store = store
        self._usage_recorder = usage_recorder
        self.supports_result_contract = bool(
            getattr(type(provider), "supports_result_contract", False)
        )
        self.supports_prompt_metadata = bool(
            getattr(type(provider), "supports_prompt_metadata", False)
        )
        try:
            parameters = inspect.signature(provider.exec_agent).parameters.values()
            self.accepts_prompt_metadata = any(
                parameter.name == "prompt_metadata"
                or parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            )
        except (AttributeError, TypeError, ValueError):
            self.accepts_prompt_metadata = False
        self._context: contextvars.ContextVar[DispatchContext | None] = (
            contextvars.ContextVar("echelon_spec_dispatch_context", default=None)
        )
        self._default_context: DispatchContext | None = None

    def __getattr__(self, name: str) -> object:
        return getattr(self._provider, name)

    @contextmanager
    def dispatch(self, context: DispatchContext) -> Iterator[None]:
        token = self._context.set(context)
        previous_default = self._default_context
        self._default_context = context
        try:
            yield
        finally:
            self._default_context = previous_default
            self._context.reset(token)

    def exec_agent(self, project_root: str, prompt: str, **kwargs: object) -> object:
        context = self._context.get() or self._default_context or DispatchContext(
            phase="unknown", agent="unknown", kind="phase", attempt=1
        )
        started = datetime.now(timezone.utc)
        monotonic_started = time.monotonic()
        result: object | None = None
        status = "ERROR"
        try:
            result = self._provider.exec_agent(project_root, prompt, **kwargs)
            if self._usage_recorder is not None:
                try:
                    self._usage_recorder(result)
                except Exception:
                    logger.warning(
                        "Could not record provider usage for workflow=%s phase=%s",
                        self._store.workflow,
                        context.phase,
                    )
            timed_out = _raw_result_field(result, "timed_out")
            exit_code = _raw_result_field(result, "exit_code")
            status = (
                "ERROR"
                if type(timed_out) is not bool
                or timed_out
                or type(exit_code) is not int
                or exit_code != 0
                else "OK"
            )
            return result
        finally:
            ended = datetime.now(timezone.utc)
            duration_ms = max(0, int((time.monotonic() - monotonic_started) * 1000))
            try:
                self._store.append_span(
                    ExecutionSpan(
                        trace_id=self._store.trace_id,
                        span_id=uuid.uuid4().hex[:16],
                        parent_span_id=None,
                        name=context.phase,
                        start_time=_timestamp(started),
                        end_time=_timestamp(ended),
                        duration_ms=duration_ms,
                        status=status,
                        attributes=_attributes(self._store, context, result),
                        token_usage=_token_usage(result),
                    )
                )
                self._store.append_event({
                    "schema_version": 1, "type": "dispatch", "trace_id": self._store.trace_id,
                        "phase": context.phase, "agent": context.agent, "attempt": context.attempt,
                        "reason": context.reason, "outcome": status, "event_time": _timestamp(ended),
                        "started_at": _timestamp(started), "ended_at": _timestamp(ended),
                        "duration_ms": duration_ms,
                        "model": _exact_text(
                            _raw_result_field(result, "model_name")
                        ),
                        "blocker": _blocker(result),
                    })
                if (
                    _raw_result_field(
                        result,
                        "echelon_result_repair_attempted",
                    )
                    is True
                ):
                    repair_outcome = _exact_text(
                        _raw_result_field(
                            result,
                            "echelon_result_repair_outcome",
                        )
                    )
                    repair_started_at = _exact_text(
                        _raw_result_field(
                            result,
                            "echelon_result_repair_started_at",
                        )
                    )
                    repair_ended_at = _exact_text(
                        _raw_result_field(
                            result,
                            "echelon_result_repair_ended_at",
                        )
                    )
                    repair_duration = _raw_result_field(
                        result,
                        "echelon_result_repair_duration_ms",
                    )
                    repair_model = _exact_text(
                        _raw_result_field(
                            result,
                            "echelon_result_repair_model_name",
                        )
                    )
                    self._store.append_event({
                        "schema_version": 1, "type": "dispatch", "trace_id": self._store.trace_id,
                        "phase": context.phase, "agent": context.agent, "attempt": context.attempt + 1,
                        "reason": "provider_retry",
                        "outcome": repair_outcome or "ERROR",
                        "event_time": repair_ended_at or _timestamp(ended),
                        "started_at": repair_started_at or _timestamp(ended),
                        "ended_at": repair_ended_at or _timestamp(ended),
                        "duration_ms": (
                            repair_duration
                            if type(repair_duration) is int
                            and repair_duration >= 0
                            else 0
                        ),
                        "model": repair_model,
                        "blocker": "",
                    })
            except Exception:
                logger.warning(
                    "Could not persist telemetry span for workflow=%s phase=%s",
                    self._store.workflow,
                    context.phase,
                    exc_info=True,
                )


def _raw_result_field(
    result: object | None,
    name: str,
    default: object = None,
) -> object:
    """Read one stored result field without invoking producer protocols."""
    from harness.squad_provider import SquadAgentResult

    if type(result) is not SquadAgentResult:
        return default
    try:
        return object.__getattribute__(result, name)
    except Exception:
        return default


def _exact_text(value: object) -> str:
    return value if type(value) is str else ""


def _token_usage(result: object | None) -> TokenUsage:
    if result is None:
        return TokenUsage.unknown()
    details = _raw_result_field(result, "token_usage_details")
    values = (
        {
            key: value
            for key, value in dict.items(details)
            if type(key) is str
            and type(value) is int
            and value >= 0
        }
        if type(details) is dict
        else {}
    )
    total = _raw_result_field(result, "token_usage")
    if (
        "total_tokens" not in values
        and type(total) is int
        and total > 0
    ):
        values["total_tokens"] = total
    return TokenUsage.from_mapping(values)


def _attributes(
    store: TelemetryStore,
    context: DispatchContext,
    result: object | None,
) -> dict[str, object]:
    attributes: dict[str, object] = {
        "echelon.run.id": store.run_id,
        "echelon.workflow.name": store.workflow,
        "echelon.workflow.phase": context.phase,
        "echelon.agent.name": context.agent,
        "echelon.dispatch.kind": context.kind,
        "echelon.dispatch.attempt": context.attempt,
        "echelon.dispatch.reason": context.reason,
        "echelon.result.verdict": _result_verdict(result),
        "gen_ai.operation.name": "agent",
    }
    provider = _exact_text(_raw_result_field(result, "provider_name"))
    model = _exact_text(_raw_result_field(result, "model_name"))
    if provider:
        attributes["gen_ai.provider.name"] = provider
    if model:
        attributes["gen_ai.response.model"] = model
    if result is not None:
        attributes["echelon.result.repair_attempted"] = (
            _raw_result_field(
                result,
                "echelon_result_repair_attempted",
            )
            is True
        )
        attributes["echelon.result.repair_succeeded"] = (
            _raw_result_field(
                result,
                "echelon_result_repair_succeeded",
            )
            is True
        )
    return attributes


def _result_verdict(result: object | None) -> str:
    payload = _raw_result_field(result, "echelon_result")
    if type(payload) is not dict:
        return "UNKNOWN"
    verdict = dict.get(payload, "verdict")
    return verdict if type(verdict) is str and verdict else "UNKNOWN"


def _blocker(result: object | None) -> str:
    payload = _raw_result_field(result, "echelon_result")
    if type(payload) is dict:
        updates = dict.get(payload, "state_updates")
        if type(updates) is dict:
            value = dict.get(updates, "blocked_reason")
            if type(value) is str and value:
                return value
    quarantined = _raw_result_field(result, "quarantined_state_updates")
    if type(quarantined) is dict:
        value = dict.get(quarantined, "blocked_reason")
        if type(value) is str and value:
            return value
    return ""


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
