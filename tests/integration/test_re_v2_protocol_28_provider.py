from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.prosaic_prompt_loader import ProsaicCommandArtifact
from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.provider import canonical_prosaic_agent_bytes
from harness.re_v2.protocol_28.artifacts import (
    EvidenceAnchorV1,
    ExhaustiveDiagnosticV1,
    ExhaustiveEvidenceSliceV1,
    ExhaustiveObservationV1,
    ExhaustiveVerificationV1,
)
from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
from harness.re_v2.protocol_28.lifecycle import (
    create_or_reuse_protocol_28_child,
    run_protocol_28_exhaustive,
)
from harness.re_v2.protocol_28.policies import build_initial_exhaustive_policy
from harness.re_v2.protocol_28.preparation import prepare_protocol_28_request
from harness.squad_provider import SquadAgentResult
from tests.unit.test_re_v2_protocol_28_preparation import _preparation_fixture


_CONTEXT_MARKER = "## Frozen slice context (canonical JSON)\n"
_SCHEMA_MARKER = "\n## Exact response schema authority (canonical JSON)\n"


def _agent(role: str) -> bytes:
    return canonical_prosaic_agent_bytes(
        ProsaicCommandArtifact(
            frontmatter={"model_tier": "strong", "effort": "high"},
            body=f"Act as the exhaustive L4 {role} and obey the exact contract.",
        )
    )


def _identity(value: object) -> str:
    return content_digest(value)


class _ContractProvider:
    """File-writing shared CLI double driven only by the frozen prompt context."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._repair_emitted = False

    def exec_agent(self, project_root: str, prompt: str, **kwargs):  # type: ignore[no-untyped-def]
        context = json.loads(
            prompt.split(_CONTEXT_MARKER, 1)[1].split(_SCHEMA_MARKER, 1)[0]
        )
        role = context["role"]
        attempt = int(context["producer_attempt_number"])
        self.calls.append((role, context["slice_spec"]["output_artifact_key_id"], attempt))
        assert kwargs["strict_result_envelope"] is True
        assert kwargs["isolated_workspace"] is True
        if role == "producer":
            filename = "exhaustive-evidence-slice.json"
            value = self._candidate(context).to_json_dict()
        else:
            filename = "exhaustive-verification.json"
            value = self._verification(context).to_json_dict()
        Path(project_root, filename).write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return SquadAgentResult(
            exit_code=0,
            echelon_result={"verdict": "DONE", "state_updates": {}},
            raw_output="",
            duration_ms=10,
            timed_out=False,
            token_usage=7,
            token_usage_details={
                "input_tokens": 4,
                "cached_input_tokens": 0,
                "reasoning_output_tokens": 1,
                "visible_output_tokens": 2,
            },
            provider_name="fixture-cli",
            model_name="fixture-model",
        )

    @staticmethod
    def _candidate(context: dict[str, object]) -> ExhaustiveEvidenceSliceV1:
        entry = context["plan_entry"]
        spec = context["slice_spec"]
        assert isinstance(entry, dict) and isinstance(spec, dict)
        evidence_by_id = {
            _identity(item): item for item in context["snapshot_evidence"]
        }
        anchors = []
        for evidence_id in entry["primary_snapshot_evidence_ids"]:
            item = evidence_by_id[evidence_id]
            anchors.append(
                EvidenceAnchorV1(
                    1,
                    evidence_id,
                    item["source_id"],
                    item["source_relative_path"],
                    item.get("byte_start", 0),
                    item.get("byte_end", item.get("byte_count", 0)),
                    item.get("raw_hash", item["file_content_hash"]),
                )
            )
        attempt = int(context["producer_attempt_number"])
        return ExhaustiveEvidenceSliceV1(
            1,
            _identity(spec),
            _identity(entry),
            entry["target_kind"],
            entry["source_id"],
            entry["target_id"],
            entry["category_id"],
            tuple(entry["primary_subject_ids"]),
            tuple(entry["primary_source_record_ids"]),
            tuple(entry["primary_snapshot_evidence_ids"]),
            tuple(sorted(anchors, key=lambda item: item.identity)),
            (),
            (
                ExhaustiveObservationV1(
                    1,
                    "applicable",
                    entry["category_id"],
                    tuple(entry["primary_subject_ids"]),
                    tuple(entry["primary_snapshot_evidence_ids"]),
                    tuple(entry["assigned_finding_ids"]),
                    f"Exact planned evidence was reviewed on attempt {attempt}.",
                ),
            ),
            tuple(entry["assigned_finding_ids"]),
            (),
            f"# Exhaustive evidence\n\nExact planned evidence, attempt {attempt}.\n",
        )

    def _verification(self, context: dict[str, object]) -> ExhaustiveVerificationV1:
        entry = context["plan_entry"]
        spec = context["slice_spec"]
        assert isinstance(entry, dict) and isinstance(spec, dict)
        candidate = ExhaustiveEvidenceSliceV1.from_json_dict(context["candidate"])
        if not self._repair_emitted:
            self._repair_emitted = True
            diagnostic = ExhaustiveDiagnosticV1(
                1,
                candidate.identity,
                entry["verifier_contract_hash"],
                "invalid-or-insufficient-evidence",
                candidate.covered_primary_subject_ids,
                candidate.covered_primary_evidence_ids,
                (),
                "Strengthen the evidence explanation once.",
            )
            return ExhaustiveVerificationV1(
                1,
                _identity(spec),
                candidate.identity,
                entry["verifier_contract_hash"],
                "REPAIR",
                (diagnostic,),
                candidate.covered_primary_evidence_ids,
                candidate.addressed_finding_ids,
            )
        return ExhaustiveVerificationV1(
            1,
            _identity(spec),
            candidate.identity,
            entry["verifier_contract_hash"],
            "PASS",
            (),
            candidate.covered_primary_evidence_ids,
            candidate.addressed_finding_ids,
        )


def _prepared_child(tmp_path: Path) -> Path:
    workspace, intent, parent, options = _preparation_fixture(tmp_path)
    producer = _agent("analyst")
    verifier = _agent("verifier")
    policy = build_initial_exhaustive_policy(
        producer_contract_hash=content_digest(producer),
        verifier_contract_hash=content_digest(verifier),
    )
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(
            options.inherited_executor_contract_bytes
        ),
        producer_agent_contract_hash=content_digest(producer),
        verifier_agent_contract_hash=content_digest(verifier),
    )
    intent = replace(
        intent,
        exhaustive_policy_catalog_id=policy.identity,
        executor_catalog_id=executors.identity,
    )
    options = replace(
        options,
        token_limit=10_000_000,
        active_ms_limit=100_000_000,
        producer_agent_bytes=producer,
        verifier_agent_bytes=verifier,
    )
    inputs = prepare_protocol_28_request(workspace, intent, parent, options)
    return create_or_reuse_protocol_28_child(workspace, inputs)


@pytest.mark.integration
def test_installed_style_provider_repairs_recovers_and_replays_without_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import harness.re_v2.protocol_28.lifecycle as lifecycle

    run_dir = _prepared_child(tmp_path)
    provider = _ContractProvider()
    original = lifecycle.record_candidate_result
    crashed = False

    def interrupt_once(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal crashed
        if not crashed:
            crashed = True
            raise RuntimeError("interrupt-after-durable-provider-capture")
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "record_candidate_result", interrupt_once)
    with pytest.raises(RuntimeError, match="interrupt-after-durable"):
        run_protocol_28_exhaustive(run_dir, lambda: provider)
    assert [role for role, _output, _attempt in provider.calls] == ["producer"]

    monkeypatch.setattr(lifecycle, "record_candidate_result", original)
    completed = run_protocol_28_exhaustive(run_dir, lambda: provider)
    calls_after_completion = tuple(provider.calls)
    replayed = run_protocol_28_exhaustive(run_dir, lambda: provider)

    assert completed.state == replayed.state == "evidence_complete"
    assert completed.accepted_slices == completed.planned_slices
    assert sum(role == "producer" for role, _output, _attempt in provider.calls) >= 2
    assert sum(role == "verifier" for role, _output, _attempt in provider.calls) >= 2
    assert tuple(provider.calls) == calls_after_completion


class _TimeoutProvider(_ContractProvider):
    """Exercise real capture, accounting and retries with a timed-out CLI call."""

    def __init__(self, role: str, *, always: bool = False, overhead_ms: int = 54):
        super().__init__()
        self._repair_emitted = True
        self.timeout_role = role
        self.always = always
        self.overhead_ms = overhead_ms
        self.failed_once = False

    def exec_agent(self, project_root, prompt, **kwargs):  # type: ignore[no-untyped-def]
        result = super().exec_agent(project_root, prompt, **kwargs)
        if self.calls[-1][0] == self.timeout_role and (self.always or not self.failed_once):
            self.failed_once = True
            return replace(
                result, exit_code=-1, timed_out=True,
                duration_ms=kwargs['timeout_ms'] + self.overhead_ms,
                token_usage=0, token_usage_details={}, echelon_result=None,
            )
        return result


@pytest.mark.integration
@pytest.mark.parametrize('role', ['producer', 'verifier'])
@pytest.mark.parametrize('restart', [0, 1, 2])
def test_timeout_shutdown_overhead_does_not_poison_bounded_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str, restart: int,
) -> None:
    import harness.re_v2.protocol_28.lifecycle as lifecycle
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context

    run_dir = _prepared_child(tmp_path)
    provider = _TimeoutProvider(role)
    if restart:
        name = 'record_candidate_result' if role == 'producer' else 'record_verification_result'
        original = getattr(lifecycle, name)
        captures = 0
        def interrupt(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal captures
            captures += 1
            if captures == restart:
                raise RuntimeError('interrupt-after-timeout-capture')
            return original(*args, **kwargs)
        monkeypatch.setattr(lifecycle, name, interrupt)
        with pytest.raises(RuntimeError, match='interrupt-after-timeout-capture'):
            run_protocol_28_exhaustive(run_dir, lambda: provider)
        monkeypatch.setattr(lifecycle, name, original)
    result = run_protocol_28_exhaustive(run_dir, lambda: provider)
    context = load_protocol_28_run_context(run_dir)
    assert result.state == 'evidence_complete'
    assert context.resources.decision.reservation_breaches == ()
    captures = tuple(context.ledger.replay().execution_captures.values())
    failed = next(c for c in captures if c.result_kind != 'provider_result')
    assert failed.result_kind == 'provider_timeout'
    assert failed.duration_ms < 300_000
    assert any(e.payload.get('reason_code') == 'provider-timeout' for e in context.events.replay())
    assert [r for r, _, _ in provider.calls] == (
        ['producer', 'producer', 'verifier'] if role == 'producer'
        else ['producer', 'verifier', 'verifier']
    ) + ['producer', 'verifier']  # The fixture also has a source-level slice.


@pytest.mark.integration
def test_actual_reservation_overrun_is_not_reported_as_budget_exhaustion(tmp_path: Path) -> None:
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.status import protocol_28_status_document
    run_dir = _prepared_child(tmp_path)
    result = run_protocol_28_exhaustive(run_dir, lambda: _TimeoutProvider('producer', overhead_ms=10_000))
    context = load_protocol_28_run_context(run_dir)
    assert context.resources.decision.reservation_breaches
    assert context.resources.decision.exhausted_dimensions == ()
    assert result.reason_code == 'l4_reservation_breach'
    assert 'raise' not in protocol_28_status_document(run_dir)['next_action']


@pytest.mark.integration
@pytest.mark.parametrize('role,attempts', [('producer', 3), ('verifier', 2)])
def test_exhausted_timeouts_remain_provider_failures_not_contract_errors(
    tmp_path: Path, role: str, attempts: int,
) -> None:
    run_dir = _prepared_child(tmp_path)
    provider = _TimeoutProvider(role, always=True)
    result = run_protocol_28_exhaustive(run_dir, lambda: provider)
    assert result.accepted_slices == 0
    assert result.reason_code == f'{role}_provider_timeout_attempts_exhausted'
    assert sum(r == role for r, _, _ in provider.calls) == attempts
