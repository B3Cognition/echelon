from __future__ import annotations

from dataclasses import replace

import pytest

from harness.re_v2.budget import BudgetDecision
from harness.re_v2.canonical import content_digest
from harness.re_v2.ledger import LedgerView
from harness.re_v2.model import (
    ArtifactKey,
    ArtifactReceipt,
    CertificationKey,
    CertificationReceipt,
    WorkItem,
    WorkTemplate,
)
from harness.re_v2.planner import (
    ReV2PlanError,
    build_initial_inventory_graph,
    plan_next,
    validate_work_graph,
)


SOURCE = content_digest(b"source")
PARTITIONS = content_digest(b"partitions")
POLICY = content_digest(b"policy")
NOW = "2026-08-14T12:00:00Z"


def template(
    goal: str,
    kind: str,
    *,
    dependencies: tuple[str, ...] = (),
    producer: str | None = None,
    protocol: str = "v1",
    policy: str = POLICY,
    provider_attempts: int = 2,
    generation_attempts: int = 2,
) -> WorkTemplate:
    return WorkTemplate(
        goal_id=goal,
        artifact_kind=kind,
        layer="L0",
        producer_id=producer or f"deterministic-{kind}",
        producer_protocol_version=protocol,
        layer_policy_hash=policy,
        required_template_ids=dependencies,
        verifier_id="fixture-verifier",
        verifier_version="v1",
        result_contract_id="fixture-result-v1",
        max_provider_attempts=provider_attempts,
        max_generation_attempts=generation_attempts,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )


def graph(
    templates: tuple[WorkTemplate, ...], goals: tuple[str, ...]
):
    return validate_work_graph(
        templates,
        requested_goals=goals,
        source_snapshot_id=SOURCE,
        partition_manifest_id=PARTITIONS,
    )


def open_budget(
    *,
    exhausted: tuple[str, ...] = (),
    provider_attempts: dict[str, int] | None = None,
    generation_attempts: dict[str, int] | None = None,
    token_limit: int | None = 10_000,
) -> BudgetDecision:
    return BudgetDecision(
        known_tokens=0,
        unknown_token_dispatches=0,
        active_ms=0,
        token_limit=token_limit,
        active_ms_limit=10_000,
        provider_attempts=provider_attempts or {},
        generation_attempts=generation_attempts or {},
        semantic_rounds={},
        result_contract_retries={},
        exhausted_dimensions=exhausted,
        provider_attempt_limit=10,
        generation_attempt_limit=10,
        semantic_round_limit=0,
        result_contract_retry_limit=0,
    )


def work_item_for(
    selected: WorkTemplate,
    dependency_hashes: tuple[str, ...] = (),
    *,
    output_key: ArtifactKey | None = None,
) -> WorkItem:
    key = output_key or ArtifactKey(
        source_snapshot_id=SOURCE,
        partition_manifest_id=PARTITIONS,
        artifact_kind=selected.artifact_kind,
        layer=selected.layer,
        producer_protocol_version=selected.producer_protocol_version,
        layer_policy_hash=selected.layer_policy_hash,
        dependency_hashes=dependency_hashes,
    )
    return WorkItem(
        template_id=selected.template_id,
        goal_id=selected.goal_id,
        output_key=key,
        required_artifact_hashes=key.dependency_hashes,
        producer_id=selected.producer_id,
        producer_protocol_version=selected.producer_protocol_version,
        verifier_id=selected.verifier_id,
        verifier_version=selected.verifier_version,
        result_contract_id=selected.result_contract_id,
        max_provider_attempts=selected.max_provider_attempts,
        max_generation_attempts=selected.max_generation_attempts,
        max_semantic_rounds=selected.max_semantic_rounds,
        max_result_contract_retries=selected.max_result_contract_retries,
    )


def accepted_receipt(
    selected: WorkTemplate,
    artifact_hash: str,
    dependency_hashes: tuple[str, ...] = (),
    *,
    output_key: ArtifactKey | None = None,
) -> tuple[CertificationReceipt, ArtifactReceipt]:
    item = work_item_for(selected, dependency_hashes, output_key=output_key)
    certification = CertificationReceipt(
        certification_key=CertificationKey(
            artifact_hash=artifact_hash,
            verifier_id=selected.verifier_id,
            verifier_version=selected.verifier_version,
            source_snapshot_id=item.output_key.source_snapshot_id,
            audit_epoch_id=None,
        ),
        candidate_id=f"candidate-{selected.artifact_kind}",
        work_item_id=item.work_item_id,
        verdict="accepted",
        normalized_diagnostics=(),
        evidence_references=(),
        scope_verified=True,
        certified_at=NOW,
    )
    receipt = ArtifactReceipt(
        artifact_key=item.output_key,
        artifact_hash=artifact_hash,
        certification_id=certification.identity,
        candidate_id=certification.candidate_id,
        work_item_id=item.work_item_id,
        accepted_at=NOW,
    )
    return certification, receipt


def ledger_view(
    *accepted: tuple[CertificationReceipt, ArtifactReceipt]
) -> LedgerView:
    return LedgerView(
        accepted_artifacts={receipt.artifact_key.identity: receipt for _, receipt in accepted},
        certifications={certification.identity: certification for certification, _ in accepted},
    )


def three_node_graph() -> tuple[WorkTemplate, WorkTemplate, WorkTemplate]:
    inventory = template("inventory", "inventory")
    api = template("api", "api-depth", dependencies=(inventory.template_id,))
    worker = template("worker", "worker-depth", dependencies=(inventory.template_id,))
    return inventory, api, worker


def test_planner_reuses_certified_nodes_and_schedules_only_delta() -> None:
    inventory, api_depth, worker_depth = three_node_graph()
    inventory_hash = content_digest(b"inventory-object")
    worker_hash = content_digest(b"worker-object")
    ledger = ledger_view(
        accepted_receipt(inventory, inventory_hash),
        accepted_receipt(worker_depth, worker_hash, (inventory_hash,)),
    )

    decision = plan_next(
        graph((worker_depth, inventory, api_depth), ("api", "worker")),
        ledger,
        open_budget(),
    )

    assert tuple(item.template_id for item in decision.ready) == (api_depth.template_id,)
    assert decision.ready[0].required_artifact_hashes == (inventory_hash,)
    assert decision.explanations[inventory.template_id].action == "reuse"
    assert decision.explanations[worker_depth.template_id].action == "reuse"


def test_planner_rejects_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    # WorkTemplate content IDs make a natural hash cycle unrepresentable. Rebinding
    # the ID accessor models adversarial decoded nodes and proves the DFS guard.
    monkeypatch.setattr(WorkTemplate, "template_id", property(lambda item: item.producer_id))
    first = template("first", "first", dependencies=("second",), producer="first")
    second = template("second", "second", dependencies=("first",), producer="second")

    with pytest.raises(ReV2PlanError, match="cycle"):
        validate_work_graph(
            (first, second),
            requested_goals=("first",),
            source_snapshot_id=SOURCE,
            partition_manifest_id=PARTITIONS,
        )


def test_graph_validation_rejects_noncanonical_duplicate_missing_and_self_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = template("inventory", "inventory")
    with pytest.raises(ReV2PlanError, match="WorkTemplate"):
        validate_work_graph(
            (object(),), requested_goals=("inventory",),
            source_snapshot_id=SOURCE, partition_manifest_id=PARTITIONS,
        )
    with pytest.raises(ReV2PlanError, match="duplicate template"):
        graph((item, item), ("inventory",))

    missing = template("api", "api", dependencies=(content_digest(b"absent"),))
    with pytest.raises(ReV2PlanError, match="missing dependency"):
        graph((missing,), ("api",))

    monkeypatch.setattr(WorkTemplate, "template_id", property(lambda value: value.producer_id))
    self_dependent = template(
        "self", "self", dependencies=("self-producer",), producer="self-producer"
    )
    with pytest.raises(ReV2PlanError, match="self"):
        validate_work_graph(
            (self_dependent,), requested_goals=("self",),
            source_snapshot_id=SOURCE, partition_manifest_id=PARTITIONS,
        )


def test_graph_validation_rejects_duplicate_logical_outputs_and_unsafe_goals() -> None:
    first = template("inventory", "inventory", producer="producer-a")
    second = template("inventory", "inventory", producer="producer-b")
    with pytest.raises(ReV2PlanError, match="logical output"):
        graph((first, second), ("inventory",))
    with pytest.raises(ReV2PlanError, match="requested goal"):
        graph((first,), ("../escape",))
    with pytest.raises(ReV2PlanError, match="requested goals"):
        validate_work_graph(
            (first,), requested_goals="inventory",
            source_snapshot_id=SOURCE, partition_manifest_id=PARTITIONS,
        )
    with pytest.raises(ReV2PlanError, match="unknown requested goal"):
        graph((first,), ("api",))

    other_goal = template("api", "inventory", producer="producer-c")
    with pytest.raises(ReV2PlanError, match="logical output"):
        graph((first, other_goal), ("inventory", "api"))


def test_input_order_does_not_change_graph_or_plan_output() -> None:
    inventory, api, worker = three_node_graph()
    first = graph((inventory, api, worker), ("worker", "api"))
    second = graph((worker, api, inventory), ("api", "worker"))

    first_plan = plan_next(first, ledger_view(), open_budget())
    second_plan = plan_next(second, ledger_view(), open_budget())

    assert first == second
    assert tuple(item.to_json_dict() for item in first_plan.ready) == tuple(
        item.to_json_dict() for item in second_plan.ready
    )
    assert dict(first_plan.explanations) == dict(second_plan.explanations)


def test_requested_goal_schedules_only_its_dependency_closure() -> None:
    inventory, api, worker = three_node_graph()
    inventory_hash = content_digest(b"inventory")

    decision = plan_next(
        graph((worker, api, inventory), ("api",)),
        ledger_view(accepted_receipt(inventory, inventory_hash)),
        open_budget(),
    )

    assert tuple(item.template_id for item in decision.ready) == (api.template_id,)
    assert decision.explanations[worker.template_id].action == "blocked_dependency"
    assert decision.explanations[worker.template_id].reason_code == "goal_not_requested"


def test_plan_time_requested_goals_are_explicit_and_order_independent() -> None:
    inventory, api, worker = three_node_graph()
    validated = graph((worker, inventory, api), ("api", "worker"))

    decision = plan_next(
        validated,
        ledger_view(),
        open_budget(),
        requested_goals=("api",),
    )

    assert tuple(item.template_id for item in decision.ready) == (inventory.template_id,)
    assert decision.explanations[worker.template_id].reason_code == "goal_not_requested"

    api_only = graph((worker, inventory, api), ("api",))
    with pytest.raises(ReV2PlanError, match="validated requested goals"):
        plan_next(
            api_only,
            ledger_view(),
            open_budget(),
            requested_goals=("worker",),
        )


@pytest.mark.parametrize(
    "changed_field",
    [
        "source_snapshot_id",
        "partition_manifest_id",
        "producer_protocol_version",
        "layer_policy_hash",
        "dependency_hashes",
    ],
)
def test_stale_full_artifact_key_is_rejected_never_reused(changed_field: str) -> None:
    selected = template("inventory", "inventory")
    exact = work_item_for(selected).output_key
    replacements: dict[str, object] = {
        "source_snapshot_id": content_digest(b"stale-source"),
        "partition_manifest_id": content_digest(b"stale-partitions"),
        "producer_protocol_version": "v0",
        "layer_policy_hash": content_digest(b"stale-policy"),
        "dependency_hashes": (content_digest(b"stale-dependency"),),
    }
    stale_key = replace(exact, **{changed_field: replacements[changed_field]})
    stale = accepted_receipt(
        selected, content_digest(b"stale-object"), output_key=stale_key
    )

    decision = plan_next(
        graph((selected,), ("inventory",)), ledger_view(stale), open_budget()
    )

    assert decision.ready == ()
    assert decision.explanations[selected.template_id].action == "reject_incompatible"
    assert decision.explanations[selected.template_id].reason_code == "artifact_key_incompatible"


def test_reuse_requires_matching_replayed_certification() -> None:
    selected = template("inventory", "inventory")
    certification, receipt = accepted_receipt(selected, content_digest(b"object"))
    unsupported = replace(
        certification,
        certification_key=replace(
            certification.certification_key,
            verifier_version="v0",
        ),
    )
    forged = LedgerView(
        accepted_artifacts={receipt.artifact_key.identity: receipt},
        certifications={receipt.certification_id: unsupported},
    )

    decision = plan_next(graph((selected,), ("inventory",)), forged, open_budget())

    assert decision.ready == ()
    assert decision.explanations[selected.template_id].action == "reject_incompatible"
    assert decision.explanations[selected.template_id].reason_code == "certification_incompatible"


def test_downstream_item_is_instantiated_only_from_accepted_exact_hashes() -> None:
    inventory = template("inventory", "inventory")
    api = template("api", "api-depth", dependencies=(inventory.template_id,))

    decision = plan_next(
        graph((api, inventory), ("api",)), ledger_view(), open_budget()
    )

    assert tuple(item.template_id for item in decision.ready) == (inventory.template_id,)
    assert decision.explanations[api.template_id].action == "blocked_dependency"
    assert decision.explanations[api.template_id].work_item_id == api.template_id


def test_ready_order_is_lexicographic_by_template_id() -> None:
    first = template("a", "a")
    second = template("b", "b")
    decision = plan_next(graph((second, first), ("b", "a")), ledger_view(), open_budget())

    assert tuple(item.template_id for item in decision.ready) == tuple(
        sorted((first.template_id, second.template_id))
    )


def test_work_item_identity_excludes_global_resource_limits() -> None:
    selected = template("inventory", "inventory")
    validated = graph((selected,), ("inventory",))

    bounded = plan_next(validated, ledger_view(), open_budget(token_limit=10_000))
    unbounded = plan_next(validated, ledger_view(), open_budget(token_limit=None))

    assert bounded.ready[0].work_item_id == unbounded.ready[0].work_item_id


def test_budget_blocks_only_relevant_generation_dimensions() -> None:
    selected = template("inventory", "inventory", provider_attempts=1)
    validated = graph((selected,), ("inventory",))
    initial = plan_next(validated, ledger_view(), open_budget())
    item_id = initial.ready[0].work_item_id

    irrelevant = plan_next(
        validated,
        ledger_view(),
        open_budget(exhausted=("semantic_rounds:another-item",)),
    )
    blocked = plan_next(
        validated,
        ledger_view(),
        open_budget(provider_attempts={item_id: 1}),
    )

    assert tuple(item.work_item_id for item in irrelevant.ready) == (item_id,)
    assert blocked.ready == ()
    assert blocked.explanations[selected.template_id].action == "blocked_budget"
    assert blocked.explanations[selected.template_id].reason_code == "provider_attempts_exhausted"


def test_global_resource_exhaustion_blocks_ready_generation() -> None:
    selected = template("inventory", "inventory")
    decision = plan_next(
        graph((selected,), ("inventory",)),
        ledger_view(),
        open_budget(exhausted=("tokens",)),
    )
    assert decision.ready == ()
    assert decision.explanations[selected.template_id].action == "blocked_budget"
    assert decision.explanations[selected.template_id].reason_code == "tokens_exhausted"


def test_initial_inventory_graph_contains_only_deterministic_l0_nodes() -> None:
    initial = build_initial_inventory_graph(SOURCE, PARTITIONS)

    assert initial.source_snapshot_id == SOURCE
    assert initial.partition_manifest_id == PARTITIONS
    assert initial.requested_goals == ("inventory",)
    assert {item.layer for item in initial.templates} == {"L0"}
    assert {item.artifact_kind for item in initial.templates} == {
        "partition-inventory",
        "source-inventory",
    }
    assert all(item.producer_id.startswith("deterministic-") for item in initial.templates)
