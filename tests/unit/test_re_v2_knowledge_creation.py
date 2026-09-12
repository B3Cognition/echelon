from __future__ import annotations

import json
from dataclasses import replace

import pytest

from harness.re_v2.canonical import canonical_json_bytes
from harness.re_v2.knowledge_dispatch import ProviderReply
from harness.re_v2.protocol_22.provider import NormalizedUsageV1
from harness.re_v2.protocol_24.model import SelectionScopeV1
from tests.unit.test_re_v2_knowledge_activation import _candidate
from tests.unit.test_re_v2_knowledge_discovery_review_v2 import _review_v2
from tests.unit.test_re_v2_knowledge_dispatch import _contract
from tests.unit.test_re_v2_protocol_28_evidence import _fixture


class _ReadyBackend:
    def __init__(self) -> None:
        self.contract = _contract("fresh-creation")
        self.contract_id = self.contract.identity
        self.calls: list[str] = []

    def __call__(self, _agent, context, _reservation):
        value = json.loads(context)
        self.calls.append(value["kind"])
        if value["kind"] == "untrusted_discovery_context":
            payload = _candidate(value)
            if value.get("schema_version") == 3:
                target = value["analysis_domain_targets"][0]["key"]
                payload["domains"][0]["key"] = target
                for row in (*payload["subjects"], *payload["obligations"]):
                    if row["target"] == "behavior":
                        row["target"] = target
        else:
            payload = _review_v2(value)
        return ProviderReply(
            canonical_json_bytes(payload),
            NormalizedUsageV1(
                "trusted_exact",
                20,
                {
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "visible_output_tokens": 10,
                },
            ),
        )


class _RevisionBackend(_ReadyBackend):
    def __call__(self, _agent, context, _reservation):
        value = json.loads(context)
        self.calls.append(value["kind"])
        if value["kind"] in {
            "untrusted_discovery_context",
            "untrusted_discovery_review_revision_context",
        }:
            discovery = (
                value
                if value["kind"] == "untrusted_discovery_context"
                else value["safe_discovery_context"]
            )
            payload = _candidate(discovery)
            if discovery.get("schema_version") == 3:
                target = discovery["analysis_domain_targets"][0]["key"]
                payload["domains"][0]["key"] = target
                for row in (*payload["subjects"], *payload["obligations"]):
                    if row["target"] == "behavior":
                        row["target"] = target
        else:
            payload = _review_v2(value)
            if self.calls.count("untrusted_discovery_review_context") == 1:
                payload["verdict"] = "revise"
                payload["subjects"][0]["verdict"] = "revise"
                payload["findings"] = [{
                    "target": "source",
                    "reason_class": "ownership",
                    "rationale": "Replace the candidate with corrected ownership.",
                    "evidence_ids": payload["subjects"][0]["evidence_ids"],
                }]
        return ProviderReply(
            canonical_json_bytes(payload),
            NormalizedUsageV1(
                "trusted_exact",
                20,
                {
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "visible_output_tokens": 10,
                },
            ),
        )


class _RevisionRepairBackend(_RevisionBackend):
    def __call__(self, agent, context, reservation):
        value = json.loads(context)
        if value["kind"] == "untrusted_discovery_review_revision_context":
            self.calls.append(value["kind"])
            return ProviderReply(
                b'{"not":"a discovery proposal"}',
                NormalizedUsageV1("unavailable", None, {}),
            )
        if value["kind"] == "untrusted_discovery_repair_context":
            assert value["independent_review_feedback"]["outcome"] == (
                "revision_required"
            )
            discovery = value["safe_discovery_context"]
            payload = _candidate(discovery)
            target = discovery["analysis_domain_targets"][0]["key"]
            payload["domains"][0]["key"] = target
            for row in (*payload["subjects"], *payload["obligations"]):
                if row["target"] == "behavior":
                    row["target"] = target
            self.calls.append(value["kind"])
            return ProviderReply(
                canonical_json_bytes(payload),
                NormalizedUsageV1("unavailable", None, {}),
            )
        return super().__call__(agent, context, reservation)


class _ReviewRepairBackend(_ReadyBackend):
    def __call__(self, _agent, context, _reservation):
        value = json.loads(context)
        self.calls.append(value["kind"])
        if value["kind"] == "untrusted_discovery_context":
            payload = _candidate(value)
            target = value["analysis_domain_targets"][0]["key"]
            payload["domains"][0]["key"] = target
            for row in (*payload["subjects"], *payload["obligations"]):
                if row["target"] == "behavior":
                    row["target"] = target
        elif value["kind"] == "untrusted_discovery_review_context":
            payload = _review_v2(value)
            payload["subjects"][0]["evidence_ids"] = ["sha256:" + "f" * 64]
        else:
            assert value["kind"] == "untrusted_discovery_review_repair_context"
            assert value["deterministic_feedback"]["reason_code"] == (
                "invalid-discovery-review-evidence"
            )
            payload = _review_v2(value["safe_review_context"])
        return ProviderReply(
            canonical_json_bytes(payload),
            NormalizedUsageV1("unavailable", None, {}),
        )


def _options(tmp_path, backend):
    from harness.re_v2.knowledge_creation import ReviewedAnalysisCreationOptions

    snapshot, partition = _fixture(
        tmp_path,
        {
            "README.md": "API service\n",
            "src/orders/handler.py": "def handle(): return 'ok'\n",
        },
    )
    return ReviewedAnalysisCreationOptions(
        request_run_id="re-fresh-request",
        analysis_run_id="re-fresh-analysis",
        created_at="2026-09-12T04:00:00Z",
        snapshot=snapshot,
        workspace_partition=partition,
        selection=SelectionScopeV1(1, True, (), ()),
        source_depths=(("api", "quick"),),
        token_limit=5_000_000,
        active_ms_limit=10_800_000,
        backend=backend,
        discovery_agent_bytes=b"neutral discovery contract",
        review_agent_bytes=b"independent review contract",
        analysis_producer_agent_bytes=b"neutral analysis producer",
        analysis_verifier_agent_bytes=b"independent analysis verifier",
    )


@pytest.mark.unit
def test_fresh_creation_publishes_reviewed_analysis_and_transfers_one_account(tmp_path):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis
    from harness.re_v2.knowledge_revision import load_knowledge_revision
    from harness.re_v2.protocol_28.context import load_protocol_28_run_context
    from harness.re_v2.protocol_28.inputs import ReviewedProtocol28CreationInputs

    backend = _ReadyBackend()
    options = _options(tmp_path, backend)
    workspace = tmp_path / "workspace"

    result = create_or_resume_reviewed_analysis(workspace, options)

    assert result.state == "ready"
    assert result.analysis_run_id == "re-fresh-analysis"
    assert backend.calls == [
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
    ]
    context = load_protocol_28_run_context(workspace / "runs" / result.analysis_run_id)
    assert isinstance(context.inputs, ReviewedProtocol28CreationInputs)
    revision = load_knowledge_revision(context)
    assert revision is not None
    assert revision.manifest.logical_run_id == "re-fresh-request"
    assert len(context.resources.records) == 1
    assert context.resources.records[0].charged_tokens == 40


@pytest.mark.unit
def test_fresh_creation_reopen_is_idempotent_and_makes_no_provider_calls(tmp_path):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _ReadyBackend()
    options = _options(tmp_path, backend)
    workspace = tmp_path / "workspace"
    first = create_or_resume_reviewed_analysis(workspace, options)
    calls = tuple(backend.calls)

    second = create_or_resume_reviewed_analysis(workspace, options)

    assert second == first
    assert tuple(backend.calls) == calls


@pytest.mark.unit
def test_fresh_creation_routes_one_review_revision_back_to_producer(tmp_path):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _RevisionBackend()
    options = _options(tmp_path, backend)
    workspace = tmp_path / "workspace"

    result = create_or_resume_reviewed_analysis(workspace, options)

    assert result.state == "ready"
    assert backend.calls == [
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
        "untrusted_discovery_review_revision_context",
        "untrusted_discovery_review_context",
    ]
    request_dir = workspace / "runs" / options.request_run_id / "v2"
    rows = [json.loads(line) for line in (request_dir / "knowledge-dispatch.jsonl").read_text().splitlines()]
    assert [row["type"] for row in rows].count("review_reserved") == 2


@pytest.mark.unit
def test_fresh_creation_repairs_revised_candidate_and_authenticates_activation(
    tmp_path,
):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _RevisionRepairBackend()
    options = _options(tmp_path, backend)

    result = create_or_resume_reviewed_analysis(tmp_path / "workspace", options)

    assert result.state == "ready"
    assert backend.calls == [
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
        "untrusted_discovery_review_revision_context",
        "untrusted_discovery_repair_context",
        "untrusted_discovery_review_context",
    ]


@pytest.mark.unit
def test_fresh_creation_repairs_invalid_independent_review(tmp_path):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _ReviewRepairBackend()
    options = _options(tmp_path, backend)

    result = create_or_resume_reviewed_analysis(tmp_path / "workspace", options)

    assert result.state == "ready"
    assert backend.calls == [
        "untrusted_discovery_context",
        "untrusted_discovery_review_context",
        "untrusted_discovery_review_repair_context",
    ]


@pytest.mark.unit
def test_fresh_creation_recovers_crash_after_account_import_without_provider_replay(
    tmp_path,
):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _ReadyBackend()
    base = _options(tmp_path, backend)
    workspace = tmp_path / "workspace"

    def crash(point: str) -> None:
        if point == "after_account_imported":
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated crash"):
        create_or_resume_reviewed_analysis(
            workspace, replace(base, fault_hook=crash)
        )
    calls = tuple(backend.calls)

    recovered = create_or_resume_reviewed_analysis(workspace, base)

    assert recovered.state == "ready"
    assert tuple(backend.calls) == calls


@pytest.mark.unit
def test_fresh_creation_returns_durable_provider_failure_without_child(tmp_path):
    from harness.re_v2.knowledge_creation import create_or_resume_reviewed_analysis

    backend = _ReadyBackend()

    def fail(_agent, _context, _reservation):
        backend.calls.append("failed")
        return ProviderReply(
            b"", NormalizedUsageV1("unavailable", None, {}), "provider-failed"
        )

    fail.contract = backend.contract
    fail.contract_id = backend.contract_id
    options = _options(tmp_path, fail)
    workspace = tmp_path / "workspace"

    first = create_or_resume_reviewed_analysis(workspace, options)
    second = create_or_resume_reviewed_analysis(workspace, options)

    assert first.state == second.state == "needs-attention"
    assert first.reason_code == second.reason_code == "provider-failed"
    assert backend.calls == ["failed"]
    assert not (workspace / "runs" / "re-fresh-analysis").exists()


@pytest.mark.unit
def test_fresh_creation_rejects_changed_absolute_ceiling_on_reopen(tmp_path):
    from harness.re_v2.knowledge_creation import (
        KnowledgeCreationError,
        create_or_resume_reviewed_analysis,
    )

    backend = _ReadyBackend()
    options = _options(tmp_path, backend)
    workspace = tmp_path / "workspace"
    create_or_resume_reviewed_analysis(workspace, options)

    with pytest.raises(
        KnowledgeCreationError,
        match="reviewed-analysis-creation-intent-conflict",
    ):
        create_or_resume_reviewed_analysis(
            workspace, replace(options, token_limit=options.token_limit + 1)
        )
