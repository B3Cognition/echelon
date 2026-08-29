from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.squad_provider import SquadAgentResult
from tests.re_v2_protocol_27_fixtures import synthesis_budget_policy_v1
from tests.unit.test_re_v2_protocol_27_inputs import _input_set


def _validated_controller_inputs(tmp_path: Path):
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )
    from harness.re_v2.protocol_27.lifecycle import (
        partial_acceptances_for,
        synthesis_request,
    )

    run_dir = tmp_path / "runs" / "re-synthesis-child"
    base = _input_set(run_dir.name)
    budget = synthesis_budget_policy_v1(
        token_limit=10_000_000,
        active_ms_limit=10_000_000,
    )
    request = synthesis_request(
        base.parent,
        budget,
        expected_v2_index_hash=content_digest(b""),
        expected_compatibility_generation=0,
    )
    inputs = replace(
        base,
        request=request,
        partial_acceptances=partial_acceptances_for(base.parent, request),
        budget_policy=budget,
    )
    create_protocol_27_run_store(run_dir, inputs)
    return load_protocol_27_inputs(run_dir)


def _result(**overrides: object) -> SquadAgentResult:
    values: dict[str, object] = {
        "exit_code": 0,
        "echelon_result": {"verdict": "DONE", "state_updates": {}},
        "raw_output": "echelon_result:\n  verdict: DONE\n  state_updates: {}\n",
        "duration_ms": 20,
        "timed_out": False,
        "token_usage": 18,
        "token_usage_details": {
            "input_tokens": 10,
            "output_tokens": 8,
            "total_tokens": 18,
        },
        "provider_name": "codex",
        "model_name": "gpt-5.6-codex",
        "stderr": "",
    }
    values.update(overrides)
    return SquadAgentResult(**values)  # type: ignore[arg-type]


def _context_from_prompt(prompt: str) -> dict[str, object]:
    payload = prompt.split("## Bounded context (canonical JSON)\n", 1)[1]
    payload = payload.split("\n\n## Authorial response schema", 1)[0]
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def _candidate(context: dict[str, object]) -> bytes:
    dependencies = context["dependency_artifacts"]
    authorized = context["authorized_objects"]
    assert isinstance(dependencies, list) and isinstance(authorized, list)
    if dependencies:
        evidence = dependencies[0]
        authority_kind = "dependency-artifact"
        authority_id = evidence["artifact_hash"]
    else:
        evidence = authorized[0]
        authority_kind = "authority-object"
        authority_id = evidence["object_hash"]
    source_ids = evidence["source_ids"]
    source_id = source_ids[0] if source_ids else None
    public_contract = context["public_contract"]
    assert isinstance(public_contract, dict)
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "artifact_kind": context["artifact_kind"],
            "scope": context["scope"],
            "sections": [
                {
                    "section_id": section_id,
                    "heading": str(section_id).replace("-", " ").title(),
                    "claim_ids": ["claim-1"],
                }
                for section_id in public_contract["required_section_ids"]
            ],
            "claims": [
                {
                    "claim_id": "claim-1",
                    "statement": "Accepted authority establishes this synthesis.",
                    "evidence": [
                        {
                            "authority_kind": authority_kind,
                            "authority_id": authority_id,
                            "source_id": source_id,
                        }
                    ],
                }
            ],
            "input_quality": context["input_quality"],
            "debt_refs": context["debt_refs"],
        }
    )


class _ScriptedProvider:
    def __init__(
        self,
        *,
        malformed_first: bool = False,
        invalid_result_first: bool = False,
        fail_work_item_id: str | None = None,
    ) -> None:
        self.malformed_first = malformed_first
        self.invalid_result_first = invalid_result_first
        self.fail_work_item_id = fail_work_item_id
        self.calls: list[str] = []

    def exec_agent(self, project_root: str, prompt: str, **_kwargs):
        context = _context_from_prompt(prompt)
        work_item_id = str(context["work_item_id"])
        self.calls.append(work_item_id)
        should_fail = (
            self.malformed_first and len(self.calls) == 1
        ) or work_item_id == self.fail_work_item_id
        payload = b"{}" if should_fail else _candidate(context)
        (Path(project_root) / "synthesis.json").write_bytes(payload)
        if self.invalid_result_first and len(self.calls) == 1:
            return _result(
                echelon_result={"verdict": "DONE", "state_updates": {"x": 1}}
            )
        return _result()


@pytest.mark.unit
def test_planner_dispatches_only_dependency_ready_missing_work(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import (
        SynthesisControllerStateV1,
        plan_next_synthesis,
    )

    inputs = _validated_controller_inputs(tmp_path)
    ready = inputs.graph.ready_work_items({})
    first = ready[0]
    node = inputs.graph.node_for_work_item(first)
    state = SynthesisControllerStateV1(
        graph=inputs.graph,
        accepted_node_hashes={},
        accepted_work_item_ids=(),
        adopted_work_item_ids=(),
        selected_checkpoint_work_item_ids=(),
        attempts_by_work_item={},
        last_failure_by_work_item={},
        pending_capture_work_item_id=None,
        pending_candidate_work_item_id=None,
        root_accepted=False,
        budget_allowed=True,
    )

    action = plan_next_synthesis(state)

    assert action.kind == "dispatch"
    assert action.work_item_id == first.work_item_id
    assert node.generated_dependency_node_ids == ()


@pytest.mark.unit
def test_planner_materializes_only_after_root_closure(tmp_path: Path) -> None:
    from harness.re_v2.canonical import content_digest
    from harness.re_v2.protocol_27.controller import (
        SynthesisControllerStateV1,
        plan_next_synthesis,
    )

    inputs = _validated_controller_inputs(tmp_path)
    accepted = {
        node.node_id: content_digest(node.node_id.encode("utf-8"))
        for node in inputs.graph.required_nodes
    }
    state = SynthesisControllerStateV1(
        graph=inputs.graph,
        accepted_node_hashes=accepted,
        accepted_work_item_ids=(),
        adopted_work_item_ids=(),
        selected_checkpoint_work_item_ids=(),
        attempts_by_work_item={},
        last_failure_by_work_item={},
        pending_capture_work_item_id=None,
        pending_candidate_work_item_id=None,
        root_accepted=True,
        budget_allowed=True,
    )

    assert plan_next_synthesis(state).kind == "materialize"
    materialized = replace(state, materialization_complete=True)
    assert plan_next_synthesis(materialized).kind == "publish"
    assert plan_next_synthesis(replace(materialized, publication_complete=True)).kind == "complete"


@pytest.mark.unit
def test_controller_closes_graph_with_one_shared_provider_instance(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider()
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        return provider

    result = Protocol27Controller(inputs, provider_factory=factory).run_to_closure()  # type: ignore[arg-type]

    assert result.synthesis_closure_complete
    assert result.terminal_kind == "complete"
    assert result.accepted_artifact_count == result.required_artifact_count == 13
    assert result.provider_attempts == 13
    assert result.contract_retries == 0
    assert result.synthesis_root_id is not None
    assert factory_calls == 1
    assert len(provider.calls) == 13


@pytest.mark.unit
def test_malformed_candidate_gets_exactly_one_contract_retry(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider(malformed_first=True)

    result = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    ).run_to_closure()

    assert result.synthesis_closure_complete
    assert result.provider_attempts == 14
    assert result.contract_retries == 1
    assert provider.calls[0] == provider.calls[1]


@pytest.mark.unit
def test_invalid_result_gets_exactly_one_result_contract_retry(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller

    inputs = _validated_controller_inputs(tmp_path)
    provider = _ScriptedProvider(invalid_result_first=True)
    controller = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    result = controller.run_to_closure()
    attempts = [
        event.payload["attempt_kind"]
        for event in controller.events.replay()
        if event.type == "dispatch_started"
    ]

    assert result.synthesis_closure_complete
    assert result.provider_attempts == 14
    assert result.contract_retries == 1
    assert attempts[:2] == ["initial_generation", "result_contract_retry"]


@pytest.mark.unit
def test_exhausted_artifact_retains_unrelated_siblings_on_continuation(
    tmp_path: Path,
) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller

    inputs = _validated_controller_inputs(tmp_path)
    target = inputs.graph.ready_work_items({})[0]
    provider = _ScriptedProvider(fail_work_item_id=target.work_item_id)
    controller = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    )

    first = controller.run_to_closure()
    first_call_count = len(provider.calls)
    second = controller.run_to_closure()

    assert not first.synthesis_closure_complete
    assert first.accepted_artifact_count > 0
    assert first.accepted_artifact_count < first.required_artifact_count
    assert provider.calls.count(target.work_item_id) == 2
    assert len(provider.calls) == first_call_count
    assert second.accepted_artifact_count == first.accepted_artifact_count


@pytest.mark.unit
def test_reservation_refusal_returns_explicit_incomplete_result(tmp_path: Path) -> None:
    from harness.re_v2.protocol_27.controller import Protocol27Controller
    from harness.re_v2.protocol_27.inputs import (
        create_protocol_27_run_store,
        load_protocol_27_inputs,
    )

    run_dir = tmp_path / "small" / "runs" / "re-synthesis-child"
    create_protocol_27_run_store(run_dir, _input_set(run_dir.name))
    inputs = load_protocol_27_inputs(run_dir)
    provider = _ScriptedProvider()

    result = Protocol27Controller(
        inputs,
        provider_factory=lambda: provider,  # type: ignore[arg-type]
    ).run_to_closure()

    assert not result.synthesis_closure_complete
    assert result.terminal_kind == "synthesis-reservation-exceeds-remaining-budget"
    assert len(provider.calls) == 1
