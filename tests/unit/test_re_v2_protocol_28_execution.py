from __future__ import annotations

from pathlib import Path

import pytest

from harness.re_v2.ledger import ObjectStore, ReV2LedgerError
from harness.re_v2.protocol_28.execution import (
    L4ExecutionEnvelopeV1,
    Protocol28ExecutionError,
    parse_captured_result,
    persist_provider_result,
)
from tests.re_v2_protocol_28_fixtures import digest


def _envelope(*, role: str = "producer", dispatch_id: str = "dispatch-producer") -> L4ExecutionEnvelopeV1:
    return L4ExecutionEnvelopeV1(
        schema_version=1,
        dispatch_id=dispatch_id,
        role=role,
        slice_spec_id=digest("slice-spec"),
        plan_entry_id=digest("plan-entry"),
        attempt_number=1,
        agent_contract_hash=digest(f"{role}-contract"),
        context_bundle_hash=digest(f"{role}-context"),
        provider_request_hash=digest(f"{role}-request"),
        candidate_id=digest("candidate") if role == "verifier" else None,
    )


@pytest.mark.unit
def test_raw_result_is_durable_before_capture_or_parse(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")
    seen: list[str] = []

    def stop_after_raw(stage: str) -> None:
        seen.append(stage)
        if stage == "raw_result_durable":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        persist_provider_result(
            store,
            _envelope(),
            b'{"candidate":"captured"}\n',
            provider_name="codex",
            model_revision="gpt-test",
            started_at="2026-08-31T12:00:00Z",
            ended_at="2026-08-31T12:00:01Z",
            duration_ms=1000,
            fault=stop_after_raw,
        )

    assert seen == ["before_raw_result", "raw_result_durable"]
    assert store.read_blob(digest('{"candidate":"captured"}\n')) == b'{"candidate":"captured"}\n'


@pytest.mark.unit
def test_fault_before_raw_result_leaves_no_provider_object(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")

    def stop_before_raw(stage: str) -> None:
        if stage == "before_raw_result":
            raise RuntimeError("simulated pre-write crash")

    with pytest.raises(RuntimeError, match="pre-write crash"):
        persist_provider_result(
            store,
            _envelope(),
            b"must-not-exist",
            provider_name="codex",
            model_revision="gpt-test",
            started_at="2026-08-31T12:00:00Z",
            ended_at="2026-08-31T12:00:01Z",
            duration_ms=1000,
            fault=stop_before_raw,
        )

    with pytest.raises(ReV2LedgerError, match="cannot inspect object"):
        store.read_blob(digest("must-not-exist"))


@pytest.mark.unit
def test_capture_is_published_before_ledger_and_parse_reads_only_durable_raw(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")
    seen: list[str] = []

    class Recorder:
        def record_execution_capture(self, envelope, capture):  # type: ignore[no-untyped-def]
            assert store.read_blob(envelope.identity)
            assert store.read_blob(capture.identity)

    persisted = persist_provider_result(
        store,
        _envelope(),
        b'{"candidate":"captured"}\n',
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:00Z",
        ended_at="2026-08-31T12:00:01Z",
        duration_ms=1000,
        ledger=Recorder(),
        fault=seen.append,
    )

    assert seen == [
        "before_raw_result",
        "raw_result_durable",
        "capture_durable",
        "ledger_appended",
    ]
    parsed = parse_captured_result(store, persisted.capture, lambda raw: raw.decode("utf-8"))
    assert parsed == '{"candidate":"captured"}\n'


@pytest.mark.unit
def test_capture_rejects_conflicting_dispatch_identity(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")

    class Recorder:
        recorded = None

        def record_execution_capture(self, envelope, capture):  # type: ignore[no-untyped-def]
            if self.recorded is not None and self.recorded != (envelope, capture):
                raise Protocol28ExecutionError("conflicting execution capture for dispatch")
            self.recorded = (envelope, capture)

    ledger = Recorder()
    arguments = dict(
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:00Z",
        ended_at="2026-08-31T12:00:01Z",
        duration_ms=1000,
        ledger=ledger,
    )
    persist_provider_result(store, _envelope(), b"first", **arguments)

    with pytest.raises(Protocol28ExecutionError, match="conflicting execution capture"):
        persist_provider_result(store, _envelope(), b"second", **arguments)


@pytest.mark.unit
def test_parse_fault_cannot_run_parser_before_durable_capture(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")
    persisted = persist_provider_result(
        store,
        _envelope(),
        b"provider-result",
        provider_name="codex",
        model_revision="gpt-test",
        started_at="2026-08-31T12:00:00Z",
        ended_at="2026-08-31T12:00:01Z",
        duration_ms=1000,
    )
    parsed = False

    def parser(_raw: bytes) -> str:
        nonlocal parsed
        parsed = True
        return "parsed"

    def stop_before_parse(stage: str) -> None:
        if stage == "before_parse":
            raise RuntimeError("simulated parse crash")

    with pytest.raises(RuntimeError, match="parse crash"):
        parse_captured_result(store, persisted.capture, parser, fault=stop_before_parse)

    assert parsed is False
    assert store.read_blob(persisted.capture.raw_result_hash) == b"provider-result"


@pytest.mark.unit
def test_verifier_envelope_requires_candidate_and_distinct_role_contract() -> None:
    with pytest.raises(Protocol28ExecutionError, match="verifier.*candidate"):
        L4ExecutionEnvelopeV1(
            schema_version=1,
            dispatch_id="dispatch-verifier",
            role="verifier",
            slice_spec_id=digest("slice-spec"),
            plan_entry_id=digest("plan-entry"),
            attempt_number=1,
            agent_contract_hash=digest("verifier-contract"),
            context_bundle_hash=digest("verifier-context"),
            provider_request_hash=digest("verifier-request"),
            candidate_id=None,
        )


@pytest.mark.unit
def test_capture_rejects_reversed_wall_clock_interval(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "objects")

    with pytest.raises(Protocol28ExecutionError, match="wall-clock interval"):
        persist_provider_result(
            store,
            _envelope(),
            b"provider-result",
            provider_name="codex",
            model_revision="gpt-test",
            started_at="2026-08-31T12:00:02Z",
            ended_at="2026-08-31T12:00:01Z",
            duration_ms=1000,
        )
