"""Configured-provider bridge for durable RE discovery and review."""
from __future__ import annotations

from dataclasses import replace
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from harness.ai_cli_backend import CliRunRequest, CliRunResult
from harness.config import HarnessConfig, LlmConfig
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import (
    KnowledgeDispatchAccount,
    KnowledgeDispatchPolicy,
    KnowledgeProviderContract,
)
from harness.re_v2.knowledge_discovery import DiscoveryError
from harness.re_v2.knowledge_dispatch import DiscoveryController
from harness.re_v2.knowledge_review_dispatch import DiscoveryReviewController
from harness.re_v2.protocol_22.provider import DispatchReservationV1
from tests.unit.test_re_v2_knowledge_acquisition import _phase_setup
from tests.unit.test_re_v2_knowledge_discovery import _proposal
from tests.unit.test_re_v2_knowledge_review_dispatch import _valid_review


_RESERVATION = DispatchReservationV1(100_000, 100_000, 10_000)
_PRODUCER_AGENT = b"Neutral discovery role. PRODUCER_PRIVATE_REASONING_MARKER"
_REVIEWER_AGENT = b"Neutral independent discovery review role"


def _config(cli: str = "codex") -> HarnessConfig:
    return HarnessConfig(
        target_repo=".",
        target_default_branch="main",
        provider="docker",
        llm=LlmConfig(cli=cli, timeout_ms=5_000),
    )


def _role_response(payload: dict | bytes) -> str:
    if isinstance(payload, bytes):
        payload = json.loads(payload)
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        + "\nechelon_result:\n  verdict: DONE\n  state_updates: {}\n"
    )


def _wire(answer: str, usages: list[dict[str, int] | None] | None = None) -> bytes:
    usages = usages if usages is not None else [{
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 5,
        "reasoning_output_tokens": 0,
    }]
    rows: list[dict] = []
    for index, usage in enumerate(usages):
        rows.append({
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": answer if index == len(usages) - 1 else "intermediate",
            },
        })
        rows.append({"type": "turn.completed", "usage": usage})
    return b"".join(
        json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows
    )


def _legacy_usage_wire(input_tokens, output_tokens):
    return canonical_json_bytes({"type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": {
            "input_tokens": input_tokens, "cached_input_tokens": 0,
            "output_tokens": output_tokens, "reasoning_output_tokens": 0,
        }},
    }})


class _NativeHarness:
    def __init__(self, monkeypatch, tmp_path: Path, account: KnowledgeDispatchAccount):
        self._real_popen = subprocess.Popen
        self._tmp_path = tmp_path
        self._account = account
        self.answers: list[bytes] = []
        self.calls: list[dict[str, object]] = []
        monkeypatch.setattr("harness.ai_cli_backends.codex.subprocess.Popen", self._launch)

    def _launch(self, command, **kwargs):
        index = len(self.calls)
        assert self._account.status().open_tokens == _RESERVATION.billable_tokens
        cwd = Path(kwargs["cwd"])
        assert cwd.is_dir() and not cwd.is_symlink() and list(cwd.iterdir()) == []
        capture = self._tmp_path / f"prompt-{index}.bin"
        wire = self.answers[index]
        script = (
            "import pathlib,sys; data=sys.stdin.buffer.read(); "
            f"pathlib.Path({str(capture)!r}).write_bytes(data); "
            f"sys.stdout.buffer.write({wire!r})"
        )
        self.calls.append({"command": list(command), "cwd": cwd, "capture": capture})
        return self._real_popen([sys.executable, "-c", script], **kwargs)

    def prompt(self, index: int) -> bytes:
        return Path(self.calls[index]["capture"]).read_bytes()


def _configured_backend(config, boundary, *, model="gpt-5.6-sol", capture=262_144):
    module = importlib.import_module("harness.re_v2.knowledge_llm")
    return module.KnowledgeLLMBackend(
        config,
        model=model,
        screen_output=boundary.screen_output,
        max_capture_bytes=capture,
    )


def _production_setup(tmp_path, monkeypatch, *, tokens=500_000):
    phase, paths, boundary, *_ = _phase_setup(tmp_path)
    backend = _configured_backend(_config(), boundary)
    account = KnowledgeDispatchAccount(
        paths,
        KnowledgeDispatchPolicy(tokens, 100_000, 3),
        backend.contract,
        boundary.run_authority(),
    )
    native = _NativeHarness(monkeypatch, tmp_path, account)
    producer = DiscoveryController(
        phase, account, _PRODUCER_AGENT, backend, _RESERVATION,
    )
    return phase, boundary, backend, account, native, producer


@pytest.mark.unit
def test_configured_codex_producer_and_independent_reviewer_use_one_reserved_account(
    tmp_path, monkeypatch
):
    phase, boundary, backend, account, native, producer = _production_setup(
        tmp_path, monkeypatch
    )
    proposal_payload = _proposal(json.loads(phase.provider_bytes()))
    native.answers.append(_wire(_role_response(proposal_payload)))

    proposal = producer.step()

    assert proposal.state == "proposal_ready"
    state = account.ledger.replay()
    producer_id = state.discovery_sources["api"][-1]
    producer_request = state.dispatches[producer_id]
    review_boundary = importlib.import_module(
        "harness.re_v2.knowledge_discovery_review"
    ).DiscoveryReviewBoundary(boundary)
    review_context = json.loads(review_boundary.provider_bytes(
        producer_request["binding_id"], proposal.receipt_id,
    ))
    native.answers.append(_wire(_role_response(_valid_review(review_context))))
    reviewer = DiscoveryReviewController(
        producer, _REVIEWER_AGENT, backend, _RESERVATION,
    )

    review = reviewer.step()

    assert review.state == "revision_required"
    assert len(native.calls) == 2
    for call in native.calls:
        command = call["command"]
        assert command[command.index("--model") + 1] == "gpt-5.6-sol"
    producer_prompt, review_prompt = native.prompt(0), native.prompt(1)
    assert producer_prompt.index(_PRODUCER_AGENT) < producer_prompt.index(
        b"## Untrusted frozen context"
    )
    assert phase.provider_bytes() in producer_prompt
    assert _REVIEWER_AGENT in review_prompt
    assert canonical_json_bytes(review_context).rstrip(b"\n") in review_prompt
    assert b"PRODUCER_PRIVATE_REASONING_MARKER" not in review_prompt
    assert account.status().open_tokens == 0


@pytest.mark.unit
def test_contract_enables_only_matching_accounted_rendered_prompt_combination():
    old = KnowledgeProviderContract(
        "scripted", "offline-fixture", content_digest({"adapter": "scripted"})
    )
    assert old.identity == "sha256:154de91e953c6154284b1b114d0913a5acc9eaa607875bd774bb2741b7c2f5e9"
    contract = KnowledgeProviderContract(
        "codex",
        "gpt-5.6-sol",
        content_digest(b"adapter"),
        "configured-provider-accounted",
        "rendered-prompt-utf8-bytes",
    )
    assert contract.identity != old.identity
    for execution_mode, accounting in (
        ("configured-provider-accounted", "utf8-byte-upper-bound"),
        ("offline-scripted", "rendered-prompt-utf8-bytes"),
    ):
        with pytest.raises(DiscoveryError, match="unsupported-discovery-input-accounting"):
            KnowledgeProviderContract(
                "codex", "gpt-5.6-sol", content_digest(b"adapter"),
                execution_mode, accounting,
            )


@pytest.mark.unit
def test_environment_selection_is_frozen_after_backend_construction(
    tmp_path, monkeypatch
):
    phase, paths, boundary, *_ = _phase_setup(tmp_path)
    monkeypatch.setenv("ECHELON_LLM", "codex")
    backend = _configured_backend(_config("claude"), boundary)
    frozen_id = backend.contract_id
    assert backend.contract.provider_id == "codex"
    monkeypatch.setenv("ECHELON_LLM", "claude")
    assert backend.contract_id == frozen_id
    assert backend.contract.provider_id == "codex"


@pytest.mark.unit
def test_effective_execution_config_changes_contract_but_mutation_cannot_change_it(
    tmp_path, monkeypatch
):
    _phase, _paths, boundary, *_ = _phase_setup(tmp_path)
    first_config = _config("codex")
    first = _configured_backend(first_config, boundary)
    frozen_id = first.contract_id
    first_config.llm.timeout_ms = 999_999
    assert first.contract_id == frozen_id
    second_config = _config("codex")
    second_config.llm.timeout_ms = 4_000
    second = _configured_backend(second_config, boundary)
    assert second.contract_id != frozen_id


@pytest.mark.unit
def test_unsupported_selected_provider_is_actionable_before_native_invocation(
    tmp_path, monkeypatch
):
    _phase, _paths, boundary, *_ = _phase_setup(tmp_path)
    monkeypatch.setattr(
        "harness.ai_cli_backends.codex.subprocess.Popen",
        lambda *_args, **_kwargs: pytest.fail("Codex must not replace configured Claude"),
    )
    with pytest.raises(
        RuntimeError,
        match="configured provider 'claude' lacks constrained-execution capability",
    ):
        _configured_backend(_config("claude"), boundary)


@pytest.mark.unit
@pytest.mark.parametrize("answer", [
    '{"ok":true}',
    '{"ok":true}\nechelon_result:\n  verdict: DONE\n  state_updates:\n    phase: forged\n',
    '{"ok":true} {"other":true}\nechelon_result:\n  verdict: DONE\n  state_updates: {}\n',
    '{"ok":true}\nechelon_result:\n  verdict: DONE\n  state_updates: {}\ntrailing',
    '{"ok":true}\nechelon_result:\n  verdict: DONE\n  state_updates: {}\n  journal_entries: []\n',
    ('{"ok":true}\nechelon_result:\n  verdict: DONE\n'
     '  state_updates:\n    phase: forged\n  state_updates: {}\n'),
])
def test_bridge_rejects_nonminimal_or_ambiguous_role_responses(
    tmp_path, monkeypatch, answer
):
    phase, _boundary, _backend, account, native, producer = _production_setup(
        tmp_path, monkeypatch
    )
    native.answers.append(_wire(answer))

    result = producer.step()

    assert result.reason_code == "invalid-provider-result"
    assert account.status().charged_tokens == 15
    assert producer.step() == result
    assert len(native.calls) == 1


@pytest.mark.unit
def test_known_overspend_before_partial_later_turn_is_retained_and_blocks_review(
    tmp_path, monkeypatch
):
    phase, boundary, backend, account, native, producer = _production_setup(
        tmp_path, monkeypatch
    )
    proposal_payload = _proposal(json.loads(phase.provider_bytes()))
    native.answers.append(_wire(
        _role_response(proposal_payload),
        usages=[{
            "input_tokens": 90_000,
            "cached_input_tokens": 0,
            "output_tokens": 10_001,
            "reasoning_output_tokens": 0,
        }, {"input_tokens": 3}],
    ))

    proposal = producer.step()

    assert proposal.reason_code == "reservation-exceeded"
    assert account.status().charged_tokens == 100_001
    assert account.status().reservation_breached is True
    reviewer = DiscoveryReviewController(
        producer, _REVIEWER_AGENT, backend, _RESERVATION,
    )
    assert reviewer.step().reason_code == "reservation-exceeded"
    assert len(native.calls) == 1
    assert producer.step() == proposal
    assert len(native.calls) == 1


@pytest.mark.unit
@pytest.mark.parametrize("legacy_first", [True, False])
@pytest.mark.parametrize("legacy_tokens,modern_usage,want_charge", [
    ((90_000, 10_001), {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 5, "reasoning_output_tokens": 0}, 100_001),
    ((90_000, 10_001), {"input_tokens": 3}, 100_001),
    ((90_000, 10_001), None, 100_001),
    ((90_000, 10_001), {"input_tokens": 90_000, "cached_input_tokens": 0, "output_tokens": 10_003, "reasoning_output_tokens": 0}, 100_003),
    ((16, 7), {"input_tokens": 100_001}, 100_001),
    ((16, 7), {"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}, 100_001),
])
def test_mixed_usage_retains_greatest_overspend_and_blocks_review_after_reopen(
    tmp_path, monkeypatch, legacy_first, legacy_tokens, modern_usage, want_charge,
):
    phase, boundary, backend, account, native, producer = _production_setup(tmp_path, monkeypatch)
    modern = _wire(_role_response(_proposal(json.loads(phase.provider_bytes()))), [modern_usage])
    legacy = _legacy_usage_wire(*legacy_tokens)
    native.answers.append(legacy + modern if legacy_first else modern + legacy)

    result = producer.step()

    assert result.reason_code == "reservation-exceeded"
    assert account.status().charged_tokens == want_charge
    assert account.status().reservation_breached is True
    captured = next(iter(account.ledger.replay().captures.values()))
    assert captured["usage"]["status"] == "untrusted"
    assert captured["usage"]["billable_tokens"] == want_charge
    before = {p.relative_to(phase.paths.root): p.read_bytes()
        for p in phase.paths.root.rglob("*") if p.is_file()}
    reopened = KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3),
        backend.contract, boundary.run_authority())
    resumed = DiscoveryController(phase, reopened, _PRODUCER_AGENT, backend, _RESERVATION)
    reviewer = DiscoveryReviewController(resumed, _REVIEWER_AGENT, backend, _RESERVATION)
    assert resumed.step() == result
    assert reviewer.step().reason_code == "reservation-exceeded"
    assert len(native.calls) == 1
    assert {p.relative_to(phase.paths.root): p.read_bytes()
        for p in phase.paths.root.rglob("*") if p.is_file()} == before


@pytest.mark.unit
@pytest.mark.parametrize("legacy_first", [True, False])
@pytest.mark.parametrize("format_name,want_charge,want_status", [
    ("mixed", 100_000, "untrusted"), ("modern", 15, "trusted_exact"),
    ("legacy", 23, "trusted_exact"), ("overlapping-mixed", 100_000, "untrusted"),
    ("partial-mixed", 100_000, "untrusted"),
    ("inconsistent-mixed", 100_000, "untrusted"),
    ("two-turn-mixed-at-ceiling", 100_000, "untrusted"),
    ("missing", 100_000, "unavailable"),
    ("incomplete", 100_000, "unavailable"),
])
def test_safe_mixed_and_pure_usage_preserve_configured_reviewer_dispatch(
    tmp_path, monkeypatch, legacy_first, format_name, want_charge, want_status,
):
    phase, boundary, backend, account, native, producer = _production_setup(tmp_path, monkeypatch)
    answer = _role_response(_proposal(json.loads(phase.provider_bytes())))
    legacy = _legacy_usage_wire(16, 7)
    wire = _wire(answer)
    if format_name == "mixed":
        pass
    elif format_name == "overlapping-mixed":
        legacy = _legacy_usage_wire(50_000, 10_000)
        wire = _wire(answer, [{
            "input_tokens": 45_000, "cached_input_tokens": 0,
            "output_tokens": 15_000, "reasoning_output_tokens": 0,
        }])
    elif format_name == "partial-mixed":
        wire = _wire(answer, [{"input_tokens": 60_000}])
    elif format_name == "inconsistent-mixed":
        wire = _wire(answer, [{"input_tokens": 45_000, "output_tokens": 15_000, "total_tokens": 15}])
    elif format_name == "two-turn-mixed-at-ceiling":
        wire = _wire(answer, [
            {"input_tokens": 40_000, "output_tokens": 10_000},
            {"input_tokens": 40_000, "output_tokens": 10_000},
        ])
    elif format_name == "missing":
        wire = _wire(answer, [None])
    elif format_name == "incomplete":
        wire = _wire(answer, [{"input_tokens": 11}])
    elif format_name == "legacy":
        wire = legacy + canonical_json_bytes({"type": "event_msg", "payload": {
            "type": "task_complete", "last_agent_message": answer}})
    if "mixed" in format_name:
        wire = legacy + wire if legacy_first else wire + legacy
    native.answers.append(wire)
    result = producer.step()
    assert result.state == "proposal_ready"
    assert account.status().charged_tokens == want_charge
    state = account.ledger.replay()
    assert next(iter(state.captures.values()))["usage"]["status"] == want_status
    request = state.dispatches[state.discovery_sources["api"][-1]]
    review_boundary = importlib.import_module("harness.re_v2.knowledge_discovery_review").DiscoveryReviewBoundary(boundary)
    supplied = json.loads(review_boundary.provider_bytes(request["binding_id"], result.receipt_id))
    native.answers.append(_wire(_role_response(_valid_review(supplied))))
    reviewer = DiscoveryReviewController(producer, _REVIEWER_AGENT, backend, _RESERVATION)
    assert reviewer.step().state == "revision_required"
    assert account.status().charged_tokens == want_charge + 15
    assert account.status().reservation_breached is False
    assert len(native.calls) == 2


@pytest.mark.unit
@pytest.mark.parametrize("legacy_first", [True, False])
@pytest.mark.parametrize("legacy_usages,modern_usages,want_observed", [
    ([{"input_tokens": 100_001}], None, 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}], None, 100_001),
    ([{"input_tokens": 100_001}, {"input_tokens": 10, "output_tokens": 5}], None, 100_001),
    ([{"input_tokens": 10, "output_tokens": 5}, {"input_tokens": 100_001}], None, 100_001),
    ([{"input_tokens": 90_000, "output_tokens": 10_001, "total_tokens": 15}, {}], None, 100_001),
    ([{"input_tokens": 100_001}, {"total_tokens": 20}], [{"input_tokens": 100_003}], 100_003),
    ([{"input_tokens": 100_001}], [{"total_tokens": 60_000}, {"input_tokens": 60_000}], 120_000),
    ([{"input_tokens": 100_001}], [
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 60_000},
        {"input_tokens": 60_000, "total_tokens": 15}], 120_000),
    ([{"input_tokens": 60_000}, {"output_tokens": 60_000}], [{"input_tokens": 60_000}], 60_000),
    ([{"input_tokens": 45_000, "output_tokens": 15_000, "total_tokens": 15}],
     [{"input_tokens": 60_000}], 60_000),
    ([{"input_tokens": 100_000, "cached_input_tokens": 100_000,
       "reasoning_output_tokens": 100_000, "cache_write_input_tokens": 100_000}],
     [{"input_tokens": 60_000}], 100_000),
])
def test_mixed_legacy_component_bound_survives_configured_capture_and_reopen(
    tmp_path, monkeypatch, legacy_first, legacy_usages, modern_usages, want_observed,
):
    phase, boundary, backend, account, native, producer = _production_setup(tmp_path, monkeypatch)
    modern = _wire(_role_response(_proposal(json.loads(phase.provider_bytes()))), modern_usages)
    legacy = b"".join(canonical_json_bytes({"type": "event_msg", "payload": {
        "type": "token_count", "info": {"total_token_usage": usage},
    }}) for usage in legacy_usages)
    native.answers.append(legacy + modern if legacy_first else modern + legacy)

    result = producer.step()

    breached = want_observed > 100_000
    assert result.reason_code == ("reservation-exceeded" if breached else None)
    assert account.status().charged_tokens == max(100_000, want_observed)
    assert account.status().reservation_breached is breached
    state = account.ledger.replay()
    captured = next(iter(state.captures.values()))
    assert captured["usage"]["status"] == "untrusted"
    assert captured["usage"]["billable_tokens"] == want_observed
    before = {p.relative_to(phase.paths.root): p.read_bytes()
        for p in phase.paths.root.rglob("*") if p.is_file()}
    reopened = KnowledgeDispatchAccount(phase.paths, KnowledgeDispatchPolicy(500_000, 100_000, 3),
        backend.contract, boundary.run_authority())
    resumed = DiscoveryController(phase, reopened, _PRODUCER_AGENT, backend, _RESERVATION)
    assert resumed.step() == result
    assert len(native.calls) == 1
    assert {p.relative_to(phase.paths.root): p.read_bytes()
        for p in phase.paths.root.rglob("*") if p.is_file()} == before

    reviewer = DiscoveryReviewController(resumed, _REVIEWER_AGENT, backend, _RESERVATION)
    if breached:
        assert reviewer.step().reason_code == "reservation-exceeded"
        assert len(native.calls) == 1
        assert {p.relative_to(phase.paths.root): p.read_bytes()
            for p in phase.paths.root.rglob("*") if p.is_file()} == before
    else:
        assert result.state == "proposal_ready"
        request = state.dispatches[state.discovery_sources["api"][-1]]
        review_boundary = importlib.import_module("harness.re_v2.knowledge_discovery_review").DiscoveryReviewBoundary(boundary)
        supplied = json.loads(review_boundary.provider_bytes(request["binding_id"], result.receipt_id))
        native.answers.append(_wire(_role_response(_valid_review(supplied))))
        assert reviewer.step().state == "revision_required"
        assert reopened.status().charged_tokens == 100_015
        assert reopened.status().reservation_breached is False
        assert len(native.calls) == 2


@pytest.mark.unit
def test_missing_usage_failure_is_fully_charged_and_never_retried(
    tmp_path, monkeypatch
):
    _phase, _boundary, _backend, account, native, producer = _production_setup(
        tmp_path, monkeypatch
    )
    native.answers.append(_wire("not a role response", usages=[None]))

    first = producer.step()

    assert first.reason_code == "invalid-provider-result"
    assert account.status().charged_tokens == _RESERVATION.billable_tokens
    assert producer.step() == first
    assert len(native.calls) == 1


@pytest.mark.unit
def test_active_reservation_is_the_native_call_deadline(tmp_path, monkeypatch):
    phase, _boundary, backend, account, native, _producer = _production_setup(
        tmp_path, monkeypatch
    )
    reservation = DispatchReservationV1(100_000, 100_000, 50)

    def slow_launch(_command, **kwargs):
        return native._real_popen(
            [sys.executable, "-c", "import time; time.sleep(1)"], **kwargs
        )

    monkeypatch.setattr(
        "harness.ai_cli_backends.codex.subprocess.Popen", slow_launch
    )
    producer = DiscoveryController(
        phase, account, _PRODUCER_AGENT, backend, reservation,
    )
    started = time.monotonic()

    result = producer.step()

    assert time.monotonic() - started < 0.5
    assert result.reason_code in {"provider-failed", "reservation-exceeded"}
    assert 0 < account.status().charged_active_ms <= reservation.active_ms + 100


@pytest.mark.unit
def test_insufficient_shared_budget_prevents_review_spawn(tmp_path, monkeypatch):
    phase, _boundary, backend, account, native, producer = _production_setup(
        tmp_path, monkeypatch, tokens=150_000,
    )
    native.answers.append(_wire(
        _role_response(_proposal(json.loads(phase.provider_bytes()))),
        usages=[None],
    ))
    assert producer.step().state == "proposal_ready"

    reviewer = DiscoveryReviewController(
        producer, _REVIEWER_AGENT, backend, _RESERVATION,
    )
    result = reviewer.step()

    assert result.reason_code == "budget-exhausted"
    assert len(native.calls) == 1


@pytest.mark.unit
def test_facade_generic_optional_capability_preserves_environment_and_arguments(
    tmp_path, monkeypatch
):
    calls = []

    class FocusedBackend:
        name = "claude"
        constrained_execution_contract_id = "synthetic-focused-contract-v1"

        def run_prompt(self, request):
            raise AssertionError("ordinary fallback is forbidden")

        run_agent = run_prompt

        def run_constrained_prompt(self, request, **kwargs):
            calls.append((request, kwargs))
            return CliRunResult(0, "ok", "")

    monkeypatch.setattr(
        "harness.llm_provider.create_ai_cli_backend",
        lambda _config: FocusedBackend(),
    )
    provider = importlib.import_module("harness.llm_provider").AICodingCliProvider(
        _config("claude")
    )
    result = provider.run_constrained_prompt_result(
        str(tmp_path),
        "prompt",
        model="focused-model",
        screen_output=lambda value: value,
        max_input_bytes=123,
        max_capture_bytes=456,
    )

    assert result.exit_code == 0
    assert provider.provider_id == "claude"
    assert provider.constrained_execution_contract_id == "synthetic-focused-contract-v1"
    request, kwargs = calls[0]
    assert request.prompt == "prompt"
    assert request.env == provider._build_env()
    assert kwargs["model"] == "focused-model"
    assert kwargs["max_input_bytes"] == 123
    assert kwargs["max_capture_bytes"] == 456
