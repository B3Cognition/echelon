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
                self._usage_recorder(result)
            status = (
                "ERROR"
                if bool(getattr(result, "timed_out", False))
                or int(getattr(result, "exit_code", 0) or 0) != 0
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
                    "duration_ms": duration_ms, "model": str(getattr(result, "model_name", "") or ""),
                    "blocker": _blocker(result),
                })
                if bool(getattr(result, "echelon_result_repair_attempted", False)):
                    self._store.append_event({
                        "schema_version": 1, "type": "dispatch", "trace_id": self._store.trace_id,
                        "phase": context.phase, "agent": context.agent, "attempt": context.attempt + 1,
                        "reason": "provider_retry", "outcome": str(getattr(result, "echelon_result_repair_outcome", "ERROR") or "ERROR"),
                        "event_time": _timestamp(ended), "started_at": _timestamp(ended), "ended_at": _timestamp(ended),
                        "duration_ms": int(getattr(result, "echelon_result_repair_duration_ms", 0) or 0),
                        "model": str(getattr(result, "echelon_result_repair_model_name", "") or ""), "blocker": "",
                    })
            except Exception:
                logger.warning(
                    "Could not persist telemetry span for workflow=%s phase=%s",
                    self._store.workflow,
                    context.phase,
                    exc_info=True,
                )


def _token_usage(result: object | None) -> TokenUsage:
    if result is None:
        return TokenUsage.unknown()
    details = getattr(result, "token_usage_details", None)
    values = dict(details) if isinstance(details, dict) else {}
    total = getattr(result, "token_usage", 0)
    if (
        "total_tokens" not in values
        and isinstance(total, (int, float))
        and not isinstance(total, bool)
        and int(total) > 0
    ):
        values["total_tokens"] = int(total)
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
        "echelon.result.verdict": str(getattr(result, "verdict", None) or "UNKNOWN"),
        "gen_ai.operation.name": "agent",
    }
    provider = getattr(result, "provider_name", "")
    model = getattr(result, "model_name", "")
    if provider:
        attributes["gen_ai.provider.name"] = str(provider)
    if model:
        attributes["gen_ai.response.model"] = str(model)
    if result is not None:
        attributes["echelon.result.repair_attempted"] = bool(
            getattr(result, "echelon_result_repair_attempted", False)
        )
        attributes["echelon.result.repair_succeeded"] = bool(
            getattr(result, "echelon_result_repair_succeeded", False)
        )
    return attributes


def _blocker(result: object | None) -> str:
    updates = getattr(result, "state_updates", {})
    if isinstance(updates, dict):
        value = updates.get("blocked_reason")
        if isinstance(value, str) and value:
            return value
    return ""


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
