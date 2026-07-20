from __future__ import annotations

import json
from pathlib import Path

import pytest

from echelon.telemetry.model import ExecutionSpan, TokenUsage
from echelon.telemetry.store import TelemetryStore


pytestmark = pytest.mark.unit


def test_token_usage_preserves_known_components() -> None:
    usage = TokenUsage.from_mapping(
        {
            "input_tokens": 10,
            "output_tokens": 4,
            "reasoning_output_tokens": 2,
            "cache_read_input_tokens": 3,
        }
    )

    assert usage.total == 19
    assert usage.known is True


def test_missing_provider_usage_remains_unknown() -> None:
    usage = TokenUsage.unknown()

    assert usage.known is False
    assert usage.total is None


def test_store_writes_manifest_and_append_only_spans(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="re",
        run_id="re-1",
        profile={"name": "balanced"},
        trace_id="a" * 32,
    )
    store.ensure_manifest()
    store.append_span(
        ExecutionSpan(
            trace_id="a" * 32,
            span_id="b" * 16,
            parent_span_id=None,
            name="re-extract-5-validate",
            start_time="2026-07-20T00:00:00Z",
            end_time="2026-07-20T00:00:01Z",
            duration_ms=1000,
            status="OK",
            attributes={"echelon.workflow.phase": "re-extract-5-validate"},
            token_usage=TokenUsage(input_tokens=10, output_tokens=2),
        )
    )

    manifest = json.loads((tmp_path / "telemetry/manifest.json").read_text())
    spans, diagnostics = store.read_spans()
    assert manifest["workflow"] == "re"
    assert manifest["trace_id"] == "a" * 32
    assert len(spans) == 1
    assert spans[0].token_usage.total == 12
    assert diagnostics == ()


def test_store_ignores_only_truncated_final_line(tmp_path: Path) -> None:
    store = TelemetryStore(
        tmp_path,
        workflow="re",
        run_id="re-1",
        profile={"name": "balanced"},
        trace_id="a" * 32,
    )
    path = tmp_path / "telemetry/spans.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"trace_id":"bad"}\n{"trace_id":', encoding="utf-8")

    spans, diagnostics = store.read_spans()

    assert spans == ()
    assert len(diagnostics) == 2
    assert diagnostics[-1].code == "truncated-final-line"
