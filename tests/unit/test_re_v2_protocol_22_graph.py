from __future__ import annotations

from dataclasses import replace
from typing import Mapping

import pytest

from harness.config import HarnessConfig, LlmConfig, ReV2BaselineConfig
from harness.re_v2.canonical import content_digest
from harness.re_v2.model import WorkTemplate as LegacyWorkTemplate
from harness.re_v2.protocol_22.authorities import InstalledAuthorityRegistry
from harness.re_v2.protocol_22.executors import (
    ExecutorContractCatalogV1,
    resolve_executor_catalog,
)
from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    ExecutorFailureStateV2,
    PlanningAuthorityV2,
    Protocol22Graph,
    Protocol22GraphError,
    WorkFailureStateV2,
    build_protocol_22_graph,
    instantiate_ready_item,
    plan_next_v22,
)
from harness.re_v2.protocol_22.inputs import ValidatedProtocol22Inputs
from harness.re_v2.protocol_22.model import (
    CatalogReferenceV1,
    RunManifestV2,
    WorkTemplateV2,
)
from harness.re_v2.protocol_22.partition import (
    DomainDescriptorV1,
    FileRecordV1,
    ImplementationAuthorityV1,
    SourceDescriptorV1,
    SourcePartitionIdentityInputV1,
    WorkspacePartitionCatalogV1,
    domain_content_id,
    domain_key,
    domain_partition_id,
    source_content_id,
    source_partition_id,
)
from harness.re_v2.protocol_22.policies import (
    ArtifactPolicyCatalogV1,
    ContextBundlePolicyParametersV1,
    build_compact_v1_policy_catalog,
    layer_policy_hash,
)
from harness.re_v2.protocol_22.response_schemas import response_schema_hash
from tests.re_v2_protocol_22_fixtures import digest, manifest_v2


def _registry(*, api_executor_seed: str = "api executor") -> InstalledAuthorityRegistry:
    return InstalledAuthorityRegistry(
        executor_implementations={
            "bounded-api-baseline-v1": digest(api_executor_seed),
            "re-v2-in-process-v1": digest("in-process executor"),
        },
        renderer_implementations={
            "compact-baseline-renderer-v1": digest("renderer"),
        },
        tokenizer_implementations={
            "utf8-byte-upper-bound-v1": digest("tokenizer"),
        },
        calculator_implementations={
            "bounded-dispatch-v1": digest("dispatch calculator"),
            "bounded-in-process-v1": digest("in-process calculator"),
        },
        normalizer_implementations={
            "deterministic-zero-usage-v1": digest("zero normalizer"),
            "openai-usage-v1": digest("openai normalizer"),
        },
        verifier_implementations={"compact-verifier-v1": digest("verifier")},
        partitioner_implementations={"existing-domain-partitioner": digest("partitioner")},
        ownership_implementations={"explicit-domain-ownership": digest("ownership")},
        agent_contracts={"echelon.re-baseliner": digest("agent contract")},
        response_schemas={
            "domain-baseline": response_schema_hash("domain-baseline"),
            "source-overview": response_schema_hash("source-overview"),
        },
    )


def _config() -> HarnessConfig:
    return HarnessConfig(
        provider="docker",
        llm=LlmConfig(
            enabled=True,
            cli="openai-compatible",
            base_url="https://api.example.test/v1",
            model="gpt-example",
            temperature=0.2,
            max_tokens=8192,
            timeout_ms=300_000,
            re_v2_baseline=ReV2BaselineConfig(
                model_revision="gpt-example-2026-08-01",
                revision_authority="provider_resolved_revision",
                provider_context_tokens=200_000,
            ),
        ),
    )


def _partition(
    source_domains: Mapping[str, tuple[str, ...]],
    *,
    presentation_ids: Mapping[tuple[str, str], str] | None = None,
    domain_file_names: Mapping[tuple[str, str], str] | None = None,
) -> WorkspacePartitionCatalogV1:
    partitioner = ImplementationAuthorityV1(
        id="existing-domain-partitioner",
        version="5",
        implementation_digest=digest("partitioner"),
    )
    ownership = ImplementationAuthorityV1(
        id="explicit-domain-ownership",
        version="1",
        implementation_digest=digest("ownership"),
    )
    snapshot_id = digest("workspace-snapshot")
    sources: list[SourceDescriptorV1] = []
    for source_id, roots in sorted(source_domains.items()):
        records: list[FileRecordV1] = []
        domains: list[DomainDescriptorV1] = []
        for index, root in enumerate(sorted(roots), start=1):
            payload = f"{source_id}:{root}\n".encode()
            file_name = (domain_file_names or {}).get(
                (source_id, root), "main.py"
            )
            record = FileRecordV1(
                source_relative_path=f"{root}/{file_name}",
                mode="100644",
                object_kind="regular",
                content_hash=content_digest(payload),
                byte_count=len(payload),
                line_count=1,
                text_status="eligible_utf8",
            )
            records.append(record)
            stable_key = domain_key(source_id, root, ownership.version)
            partition_id = domain_partition_id(
                partitioner,
                ownership,
                stable_key,
                root,
                (file_name,),
                (),
            )
            domains.append(
                DomainDescriptorV1(
                    domain_key=stable_key,
                    presentation_domain_id=(
                        presentation_ids or {}
                    ).get((source_id, root), f"{index:03d}-re-{root}"),
                    source_relative_root=root,
                    owned_file_count=1,
                    owned_line_count=1,
                    supporting_file_count=0,
                    domain_content_id=domain_content_id(
                        ownership.version,
                        stable_key,
                        root,
                        (record,),
                        (),
                    ),
                    domain_partition_id=partition_id,
                    owned_domain_relative_paths=(file_name,),
                    supporting_source_relative_paths=(),
                )
            )
        ordered_records = tuple(sorted(records, key=lambda item: item.source_relative_path))
        ordered_domains = tuple(sorted(domains, key=lambda item: item.domain_key))
        partition_input = SourcePartitionIdentityInputV1(
            source_id=source_id,
            partitioner=partitioner,
            ownership_policy=ownership,
            source_supporting_paths=(),
            domains=tuple(domain.partition_projection() for domain in ordered_domains),
        )
        sources.append(
            SourceDescriptorV1(
                source_id=source_id,
                workspace_relative_path=f"sources/{source_id}",
                snapshot_id=snapshot_id,
                source_content_id=source_content_id(
                    "declared-clean-git-tree-v1", ordered_records
                ),
                source_partition_id=source_partition_id(partition_input),
                files=ordered_records,
                source_supporting_paths=(),
                domains=ordered_domains,
            )
        )
    return WorkspacePartitionCatalogV1(
        schema_version=1,
        snapshot_id=snapshot_id,
        source_selection_policy_version="declared-clean-git-tree-v1",
        partitioner=partitioner,
        ownership_policy=ownership,
        sources=tuple(sorted(sources, key=lambda item: item.source_id)),
    )


def _changed_l1_policy() -> ArtifactPolicyCatalogV1:
    original = build_compact_v1_policy_catalog()
    by_kind = {entry.artifact_kind: entry for entry in original.entries}
    domain = by_kind["domain-baseline"]
    domain_parameters = replace(
        domain.policy_parameters,
        max_statement_utf8_bytes=900,
    )
    changed_domain = replace(domain, policy_parameters=domain_parameters)
    context = by_kind["domain-context-bundle"]
    assert isinstance(context.policy_parameters, ContextBundlePolicyParametersV1)
    changed_context = replace(
        context,
        policy_parameters=replace(
            context.policy_parameters,
            target_policy_hash=layer_policy_hash(changed_domain),
        ),
    )
    entries = [
        changed_domain
        if entry.artifact_kind == "domain-baseline"
        else changed_context
        if entry.artifact_kind == "domain-context-bundle"
        else entry
        for entry in original.entries
    ]
    return ArtifactPolicyCatalogV1(schema_version=1, entries=tuple(entries))


def _fixture(
    source_domains: Mapping[str, tuple[str, ...]],
    *,
    goal: str = "baseline",
    policy: ArtifactPolicyCatalogV1 | None = None,
    registry: InstalledAuthorityRegistry | None = None,
    presentation_ids: Mapping[tuple[str, str], str] | None = None,
    domain_file_names: Mapping[tuple[str, str], str] | None = None,
) -> tuple[RunManifestV2, ValidatedProtocol22Inputs]:
    workspace = _partition(
        source_domains,
        presentation_ids=presentation_ids,
        domain_file_names=domain_file_names,
    )
    artifact_policy = policy or build_compact_v1_policy_catalog()
    executor = resolve_executor_catalog(_config(), goal, registry or _registry())
    inputs = ValidatedProtocol22Inputs(
        workspace_partition=workspace,
        artifact_policy=artifact_policy,
        executor_contract=executor,
        immutable_objects={},
    )
    manifest = replace(
        manifest_v2(goal=goal, run_id=f"re-graph-{goal}"),
        source_snapshot_id=workspace.snapshot_id,
        workspace_partition_catalog=CatalogReferenceV1(
            object_hash=workspace.identity,
            relative_path="workspace-partition.json",
        ),
        artifact_policy_catalog=CatalogReferenceV1(
            object_hash=artifact_policy.identity,
            relative_path="artifact-policy.json",
        ),
        executor_contract_catalog=CatalogReferenceV1(
            object_hash=executor.identity,
            relative_path="executor-contract.json",
        ),
    )
    return manifest, inputs


def _graph(
    source_domains: Mapping[str, tuple[str, ...]],
    **kwargs: object,
) -> Protocol22Graph:
    manifest, inputs = _fixture(source_domains, **kwargs)
    return build_protocol_22_graph(manifest, inputs)


def _template(
    graph: Protocol22Graph,
    source_id: str,
    artifact_kind: str,
    *,
    domain_key_value: str | None = None,
) -> WorkTemplateV2:
    matches = [
        item
        for item in graph.templates
        if item.scope.source_id == source_id
        and item.scope.domain_key == domain_key_value
        and item.artifact_kind == artifact_kind
    ]
    assert len(matches) == 1
    return matches[0]


class _Authority(PlanningAuthorityV2):
    def __init__(self) -> None:
        self.artifacts: dict[str, AcceptedArtifactV2] = {}
        self.failures: dict[str, WorkFailureStateV2] = {}
        self.executor_failures: dict[str, ExecutorFailureStateV2] = {}
        self.unavailable: set[str] = set()

    def artifact_for_key(self, artifact_key_id: str) -> AcceptedArtifactV2 | None:
        return self.artifacts.get(artifact_key_id)

    def work_failure(self, work_item_id: str) -> WorkFailureStateV2 | None:
        return self.failures.get(work_item_id)

    def executor_failure(
        self, executor_contract_hash: str
    ) -> ExecutorFailureStateV2 | None:
        return self.executor_failures.get(executor_contract_hash)

    def pinned_authority_available(self, executor_contract_hash: str) -> bool:
        return executor_contract_hash not in self.unavailable

    def accept_ready(self, decision: object) -> None:
        for item in decision.ready:
            key_id = item.output_key.identity
            self.artifacts[key_id] = AcceptedArtifactV2(
                artifact_key_id=key_id,
                artifact_hash=digest(f"accepted:{item.work_item_id}"),
            )


class _Budget:
    def __init__(self, *, attempts: bool = True, run: bool = True) -> None:
        self.attempts = attempts
        self.run = run

    def item_attempt_available(self, work_item: object) -> bool:
        return self.attempts

    def run_budget_available(self, work_item: object) -> bool:
        return self.run


@pytest.mark.unit
def test_baseline_graph_has_exact_nodes_per_source_and_domain() -> None:
    graph = _graph({"api": ("orders", "users"), "web": ("ui",)})

    assert len(graph.templates) == (6 + 4 * 2) + (6 + 4 * 1)
    slots = {
        (item.scope.identity, item.artifact_kind, item.layer)
        for item in graph.templates
    }
    assert len(slots) == len(graph.templates)
    assert graph.requested_goals == ("baseline",)


@pytest.mark.unit
def test_inventory_graph_is_exact_l0_dependency_closure() -> None:
    graph = _graph({"api": ("orders", "users")}, goal="inventory")

    assert len(graph.templates) == 3 + 2 * 2
    assert {item.layer for item in graph.templates} == {"L0"}
    assert {item.artifact_kind for item in graph.templates} == {
        "source-inventory",
        "source-partition",
        "source-evidence-pack",
        "domain-inventory",
        "domain-evidence-pack",
    }


@pytest.mark.unit
def test_graph_has_exact_domain_first_dependencies() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    graph = build_protocol_22_graph(manifest, inputs)
    domain_key_value = inputs.workspace_partition.sources[0].domains[0].domain_key
    source_inventory = _template(graph, "api", "source-inventory")
    source_partition = _template(graph, "api", "source-partition")
    source_pack = _template(graph, "api", "source-evidence-pack")
    domain_inventory = _template(
        graph, "api", "domain-inventory", domain_key_value=domain_key_value
    )
    domain_pack = _template(
        graph, "api", "domain-evidence-pack", domain_key_value=domain_key_value
    )
    domain_context = _template(
        graph, "api", "domain-context-bundle", domain_key_value=domain_key_value
    )
    domain_baseline = _template(
        graph, "api", "domain-baseline", domain_key_value=domain_key_value
    )
    overview_context = _template(graph, "api", "source-overview-context-bundle")
    overview = _template(graph, "api", "source-overview")
    root = _template(graph, "api", "source-baseline-root")

    assert source_pack.required_template_ids == tuple(
        sorted((source_inventory.template_id, source_partition.template_id))
    )
    assert domain_pack.required_template_ids == (domain_inventory.template_id,)
    assert domain_context.required_template_ids == tuple(
        sorted((domain_inventory.template_id, domain_pack.template_id))
    )
    assert domain_baseline.required_template_ids == (domain_context.template_id,)
    assert overview_context.required_template_ids == tuple(
        sorted(
            (
                source_inventory.template_id,
                source_partition.template_id,
                source_pack.template_id,
                domain_baseline.template_id,
            )
        )
    )
    assert overview.required_template_ids == (overview_context.template_id,)
    assert root.required_template_ids == tuple(
        sorted((overview.template_id, domain_baseline.template_id))
    )
    assert source_inventory.scope.content_id == inputs.workspace_partition.sources[0].source_content_id
    assert source_partition.scope.content_id is None
    assert domain_inventory.scope.content_id == inputs.workspace_partition.sources[0].domains[0].domain_content_id
    executor = inputs.executor_contract.entry_for(domain_baseline.producer_family)
    assert domain_baseline.verifier_id == executor.verifier.verifier_id
    assert (
        domain_baseline.verifier_implementation_digest
        == executor.verifier.implementation_digest
    )

    source_inventory_item = instantiate_ready_item(source_inventory, {}, inputs)
    source_partition_item = instantiate_ready_item(source_partition, {}, inputs)
    domain_inventory_item = instantiate_ready_item(domain_inventory, {}, inputs)
    assert source_inventory_item.output_key.partition_id is None
    assert (
        source_partition_item.output_key.partition_id
        == inputs.workspace_partition.sources[0].source_partition_id
    )
    assert (
        domain_inventory_item.output_key.partition_id
        == inputs.workspace_partition.sources[0].domains[0].domain_partition_id
    )


@pytest.mark.unit
def test_l1_policy_change_preserves_every_l0_template_and_key() -> None:
    compact = _graph({"api": ("orders",)})
    changed = _graph({"api": ("orders",)}, policy=_changed_l1_policy())

    compact_l0 = {
        (item.scope.identity, item.artifact_kind): item.template_id
        for item in compact.templates
        if item.layer == "L0"
    }
    changed_l0 = {
        (item.scope.identity, item.artifact_kind): item.template_id
        for item in changed.templates
        if item.layer == "L0"
    }
    assert compact_l0 == changed_l0
    assert {
        item.template_id for item in compact.templates if item.layer == "L1"
    } != {item.template_id for item in changed.templates if item.layer == "L1"}


@pytest.mark.unit
def test_provider_change_does_not_change_artifact_key() -> None:
    first_manifest, first_inputs = _fixture({"api": ("orders",)})
    second_manifest, second_inputs = _fixture(
        {"api": ("orders",)},
        registry=_registry(api_executor_seed="changed api executor"),
    )
    first_graph = build_protocol_22_graph(first_manifest, first_inputs)
    second_graph = build_protocol_22_graph(second_manifest, second_inputs)
    domain_key_value = first_inputs.workspace_partition.sources[0].domains[0].domain_key
    first = _template(
        first_graph, "api", "domain-baseline", domain_key_value=domain_key_value
    )
    second = _template(
        second_graph, "api", "domain-baseline", domain_key_value=domain_key_value
    )
    dependency = AcceptedArtifactV2(digest("context-key"), digest("context"))

    first_item = instantiate_ready_item(
        first,
        {first.required_template_ids[0]: dependency},
        first_inputs,
    )
    second_item = instantiate_ready_item(
        second,
        {second.required_template_ids[0]: dependency},
        second_inputs,
    )

    assert first_item.work_item_id != second_item.work_item_id
    assert first_item.output_key == second_item.output_key


@pytest.mark.unit
def test_presentation_renumbering_preserves_domain_template_identity() -> None:
    original = _graph({"api": ("orders", "users")})
    renumbered = _graph(
        {"api": ("orders", "users")},
        presentation_ids={
            ("api", "orders"): "099-re-orders",
            ("api", "users"): "001-re-users",
        },
    )

    original_domains = {
        (item.scope.domain_key, item.artifact_kind): item.template_id
        for item in original.templates
        if item.scope.domain_key is not None
    }
    renumbered_domains = {
        (item.scope.domain_key, item.artifact_kind): item.template_id
        for item in renumbered.templates
        if item.scope.domain_key is not None
    }
    assert original_domains == renumbered_domains


@pytest.mark.unit
def test_graph_canonicalizes_input_order_and_rejects_duplicate_output() -> None:
    graph = _graph({"api": ("orders",)})
    reordered = Protocol22Graph(
        templates=tuple(reversed(graph.templates)),
        requested_goals=graph.requested_goals,
        catalog_hashes=graph.catalog_hashes,
    )
    duplicate = replace(graph.templates[0], producer_id="different-producer")

    assert reordered == graph
    with pytest.raises(Protocol22GraphError, match="duplicate logical output"):
        Protocol22Graph(
            templates=(*graph.templates, duplicate),
            requested_goals=graph.requested_goals,
            catalog_hashes=graph.catalog_hashes,
        )


@pytest.mark.unit
def test_graph_rejects_private_inputs_that_do_not_match_catalog_hashes() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    graph = build_protocol_22_graph(manifest, inputs)
    _changed_manifest, changed_inputs = _fixture(
        {"api": ("orders",)},
        policy=_changed_l1_policy(),
    )

    with pytest.raises(Protocol22GraphError, match="private.*artifact policy.*hash"):
        Protocol22Graph(
            graph.templates,
            graph.requested_goals,
            graph.catalog_hashes,
            _inputs=changed_inputs,
        )


@pytest.mark.unit
def test_graph_rejects_missing_dependency_and_schema_1_template() -> None:
    graph = _graph({"api": ("orders",)})
    changed = tuple(
        replace(item, required_template_ids=(digest("missing"),))
        if item.artifact_kind == "source-evidence-pack"
        else item
        for item in graph.templates
    )
    legacy = LegacyWorkTemplate(
        goal_id="inventory",
        artifact_kind="source-inventory",
        layer="L0",
        producer_id="legacy",
        producer_protocol_version="v1",
        layer_policy_hash=digest("legacy-policy"),
        required_template_ids=(),
        verifier_id="legacy-verifier",
        verifier_version="v1",
        result_contract_id="legacy-result",
        max_provider_attempts=0,
        max_generation_attempts=1,
        max_semantic_rounds=0,
        max_result_contract_retries=0,
    )

    with pytest.raises(Protocol22GraphError, match="missing dependency"):
        Protocol22Graph(changed, graph.requested_goals, graph.catalog_hashes)
    with pytest.raises(Protocol22GraphError, match="schema-2 WorkTemplateV2"):
        Protocol22Graph((legacy,), ("inventory",), graph.catalog_hashes)


@pytest.mark.unit
def test_graph_rejects_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _graph({"api": ("orders",)}, goal="inventory")
    first_id = digest("cycle-first")
    second_id = digest("cycle-second")
    first = replace(graph.templates[0], required_template_ids=(second_id,))
    second = replace(graph.templates[1], required_template_ids=(first_id,))
    monkeypatch.setattr(
        WorkTemplateV2,
        "template_id",
        property(lambda item: first_id if item.producer_id == first.producer_id else second_id),
    )

    with pytest.raises(Protocol22GraphError, match="cycle"):
        Protocol22Graph((first, second), ("inventory",), graph.catalog_hashes)


@pytest.mark.unit
def test_builder_rejects_policy_executor_family_mismatch() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    entries = tuple(
        replace(entry, producer_protocol_version="wrong-v1")
        if entry.producer_family == "evidence-pack"
        else entry
        for entry in inputs.executor_contract.entries
    )
    executor = ExecutorContractCatalogV1(schema_version=1, entries=entries)
    forged_inputs = replace(inputs, executor_contract=executor)
    forged_manifest = replace(
        manifest,
        executor_contract_catalog=replace(
            manifest.executor_contract_catalog,
            object_hash=executor.identity,
        ),
    )

    with pytest.raises(Protocol22GraphError, match="producer protocol"):
        build_protocol_22_graph(forged_manifest, forged_inputs)


@pytest.mark.unit
def test_instantiate_ready_item_sorts_hashes_and_requires_exact_dependencies() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    graph = build_protocol_22_graph(manifest, inputs)
    target = _template(graph, "api", "source-evidence-pack")
    dependencies = {
        target.required_template_ids[1]: AcceptedArtifactV2(
            digest("key-b"), digest("hash-z")
        ),
        target.required_template_ids[0]: AcceptedArtifactV2(
            digest("key-a"), digest("hash-a")
        ),
    }

    item = instantiate_ready_item(target, dependencies, inputs)

    assert item.required_artifact_hashes == tuple(
        sorted((digest("hash-z"), digest("hash-a")))
    )
    with pytest.raises(Protocol22GraphError, match="exactly match"):
        instantiate_ready_item(target, {}, inputs)


@pytest.mark.unit
def test_planner_reuses_exact_artifacts_and_advances_delta() -> None:
    manifest, inputs = _fixture({"api": ("orders",)}, goal="inventory")
    graph = build_protocol_22_graph(manifest, inputs)
    authority = _Authority()

    initial = plan_next_v22(graph, authority, _Budget())
    assert {item.output_key.artifact_kind for item in initial.ready} == {
        "source-inventory",
        "source-partition",
        "domain-inventory",
    }
    authority.accept_ready(initial)

    advanced = plan_next_v22(graph, authority, _Budget())

    assert {item.output_key.artifact_kind for item in advanced.ready} == {
        "source-evidence-pack",
        "domain-evidence-pack",
    }
    assert {
        explanation.reason_code
        for explanation in advanced.explanations.values()
        if explanation.action == "reuse"
    } == {"accepted_exact_artifact"}


@pytest.mark.unit
def test_failed_domain_blocks_only_its_closure_and_keeps_sibling_ready() -> None:
    manifest, inputs = _fixture({"api": ("orders", "users")})
    graph = build_protocol_22_graph(manifest, inputs)
    authority = _Authority()
    first = plan_next_v22(graph, authority, _Budget())
    authority.accept_ready(first)
    second = plan_next_v22(graph, authority, _Budget())
    source_pack = next(
        item
        for item in second.ready
        if item.output_key.artifact_kind == "source-evidence-pack"
    )
    authority.artifacts[source_pack.output_key.identity] = AcceptedArtifactV2(
        source_pack.output_key.identity, digest("accepted-source-pack")
    )
    domain_packs = sorted(
        (
            item
            for item in second.ready
            if item.output_key.artifact_kind == "domain-evidence-pack"
        ),
        key=lambda item: item.output_key.scope.domain_key or "",
    )
    failed, sibling = domain_packs
    authority.failures[failed.work_item_id] = WorkFailureStateV2(
        work_item_id=failed.work_item_id,
        reason_code="authorial_schema_invalid",
        failure_receipt_id=digest("failure receipt"),
    )

    decision = plan_next_v22(graph, authority, _Budget())

    assert sibling.work_item_id in {item.work_item_id for item in decision.ready}
    assert decision.explanations[failed.template_id].reason_code == "authorial_schema_invalid"
    failed_domain_context = _template(
        graph,
        "api",
        "domain-context-bundle",
        domain_key_value=failed.output_key.scope.domain_key,
    )
    assert (
        decision.explanations[failed_domain_context.template_id].reason_code
        == "blocked_by_failed_dependency"
    )
    overview_context = _template(
        graph,
        "api",
        "source-overview-context-bundle",
    )
    assert (
        decision.explanations[overview_context.template_id].reason_code
        == "blocked_by_failed_dependency"
    )


@pytest.mark.unit
def test_executor_failure_blocks_same_contract_and_failed_dependency_closure() -> None:
    manifest, inputs = _fixture({"api": ("orders", "users")}, goal="inventory")
    graph = build_protocol_22_graph(manifest, inputs)
    authority = _Authority()
    initial = plan_next_v22(graph, authority, _Budget())
    inventories = [item for item in initial.ready if item.producer_family == "inventory"]
    trigger = inventories[0]
    failure = ExecutorFailureStateV2(
        executor_contract_hash=trigger.executor_contract_hash,
        reason_code="usage_exceeded_reservation",
        executor_failure_receipt_id=digest("executor failure"),
    )
    authority.executor_failures[trigger.executor_contract_hash] = failure
    authority.failures[trigger.work_item_id] = WorkFailureStateV2(
        work_item_id=trigger.work_item_id,
        reason_code="failed_executor_contract",
        failure_receipt_id=failure.executor_failure_receipt_id,
    )

    decision = plan_next_v22(graph, authority, _Budget())

    assert decision.explanations[trigger.template_id].reason_code == "failed_executor_contract"
    for item in inventories[1:]:
        assert (
            decision.explanations[item.template_id].reason_code
            == "blocked_by_executor_failure"
        )
    partition = next(item for item in initial.ready if item.producer_family == "partition")
    assert partition.work_item_id in {item.work_item_id for item in decision.ready}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("budget", "unavailable", "reason"),
    (
        (_Budget(attempts=False), False, "item_attempts_exhausted"),
        (_Budget(run=False), False, "run_budget_exhausted"),
        (_Budget(), True, "pinned_authority_unavailable"),
    ),
)
def test_planner_reports_attempt_run_and_authority_blocks(
    budget: _Budget,
    unavailable: bool,
    reason: str,
) -> None:
    graph = _graph({"api": ("orders",)}, goal="inventory")
    authority = _Authority()
    if unavailable:
        authority.unavailable.update(
            item.executor_contract_hash for item in graph.templates
        )

    decision = plan_next_v22(graph, authority, budget)

    assert reason in {
        explanation.reason_code for explanation in decision.explanations.values()
    }


@pytest.mark.unit
def test_builder_rejects_manifest_catalog_hash_mismatch() -> None:
    manifest, inputs = _fixture({"api": ("orders",)})
    forged = replace(
        manifest,
        artifact_policy_catalog=replace(
            manifest.artifact_policy_catalog,
            object_hash=digest("forged policy"),
        ),
    )

    with pytest.raises(Protocol22GraphError, match="artifact policy catalog hash"):
        build_protocol_22_graph(forged, inputs)
