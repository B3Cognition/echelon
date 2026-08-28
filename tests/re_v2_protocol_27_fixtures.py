from __future__ import annotations

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_27.model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    AcceptedSourceOverviewProjectionV1,
    PartialSourceAcceptanceV1,
    RunManifestV6,
    PublicationDescriptorV1,
    SynthesisArtifactAuthorityV1,
    SynthesisArtifactDependencyV1,
    SynthesisArtifactKeyV1,
    SynthesisBudgetPolicyV1,
    SynthesisRequestV1,
    SynthesisRootV1,
    SynthesisScopeV1,
    SynthesisWorkItemV1,
    SynthesisWorkTemplateV1,
)


def digest(seed: str) -> str:
    return content_digest(seed.encode("utf-8"))


def accepted_source_outcome_v1(
    source_id: str = "api",
    *,
    outcome: str = "complete",
) -> AcceptedSourceOutcomeV1:
    partial = outcome == "partial"
    return AcceptedSourceOutcomeV1(
        schema_version=1,
        source_id=source_id,
        source_root_key_id=digest(f"{source_id}:root-key"),
        source_root_hash=digest(f"{source_id}:root"),
        outcome=outcome,
        debt_manifest_hash=digest(f"{source_id}:debt") if partial else None,
        lower_authority_ids=(digest(f"{source_id}:lower"),),
    )


def accepted_source_overview_projection_v1(
    source_id: str = "api",
) -> AcceptedSourceOverviewProjectionV1:
    source = accepted_source_outcome_v1(source_id)
    payload_hash = digest(f"{source_id}:overview-markdown")
    return AcceptedSourceOverviewProjectionV1(
        schema_version=1,
        source_id=source_id,
        selected_layer="L3",
        source_root_key_id=source.source_root_key_id,
        source_root_hash=source.source_root_hash,
        materializer_protocol_version="2.5",
        materializer_authority_hash=digest("protocol-25-materializer"),
        content_hash=payload_hash,
        object_hash=payload_hash,
    )


def synthesis_budget_policy_v1(
    *,
    token_limit: int | None = 400_000,
    active_ms_limit: int | None = 600_000,
) -> SynthesisBudgetPolicyV1:
    return SynthesisBudgetPolicyV1(
        schema_version=1,
        token_limit=token_limit,
        active_ms_limit=active_ms_limit,
        provider_attempt_limit=2,
        generation_attempt_limit=2,
        result_contract_retry_limit=1,
        artifact_contract_retry_limit=1,
    )


def synthesis_request_v1(
    sources: tuple[AcceptedSourceOutcomeV1, ...],
    *,
    token_limit: int = 400_000,
) -> SynthesisRequestV1:
    return SynthesisRequestV1(
        schema_version=1,
        parent_manifest_hash=digest("parent-manifest"),
        accepted_source_outcome_ids=tuple(source.identity for source in sources),
        accepted_partial_source_ids=tuple(
            source.source_id for source in sources if source.outcome == "partial"
        ),
        budget_policy_hash=synthesis_budget_policy_v1(
            token_limit=token_limit
        ).identity,
        expected_v2_index_hash=digest("v2-index-base"),
        expected_compatibility_generation=7,
    )


def manifest_v6(*, run_id: str = "re-synthesis-child") -> RunManifestV6:
    sources = (
        accepted_source_outcome_v1("api"),
        accepted_source_outcome_v1("web", outcome="partial"),
    )
    request = synthesis_request_v1(sources)
    partial = sources[1]
    acceptance = PartialSourceAcceptanceV1(
        schema_version=1,
        parent_run_id="re-parent",
        parent_manifest_hash=request.parent_manifest_hash,
        source_id=partial.source_id,
        source_root_key_id=partial.source_root_key_id,
        source_root_hash=partial.source_root_hash,
        debt_manifest_hash=partial.debt_manifest_hash,
        debt_summary_hash=digest("web:debt-summary"),
        operation_id=request.request_id,
    )
    catalog = AcceptedSourceOverviewCatalogV1(
        schema_version=1,
        projections=tuple(
            accepted_source_overview_projection_v1(source.source_id)
            for source in sources
        ),
    )
    return RunManifestV6(
        schema_version=6,
        engine="re-v2",
        engine_protocol_version="2.7",
        goal="workspace-synthesis",
        run_id=run_id,
        created_at="2026-08-28T12:00:00Z",
        request_id=request.request_id,
        parent_run_id="re-parent",
        parent_manifest_hash=request.parent_manifest_hash,
        source_snapshot_id=digest("source-snapshot"),
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=digest("partition-manifest"),
        accepted_sources=sources,
        source_overview_catalog_id=catalog.identity,
        partial_acceptances=(acceptance,),
        input_authority_catalog_id=digest("input-authority-catalog"),
        synthesis_graph_id=digest("synthesis-graph"),
        synthesis_policy_hash=digest("synthesis-policy"),
        prosaic_authority_hash=digest("prosaic-authority"),
        budget_policy=synthesis_budget_policy_v1(),
        checkpoint_selection_id=digest("checkpoint-selection"),
        expected_v2_index_hash=request.expected_v2_index_hash,
        expected_compatibility_generation=request.expected_compatibility_generation,
    )


def synthesis_artifact_key_v1() -> SynthesisArtifactKeyV1:
    dependency = SynthesisArtifactDependencyV1(
        digest("source-overview-key"), digest("source-overview")
    )
    return SynthesisArtifactKeyV1(
        identity_schema_version=1,
        scope=SynthesisScopeV1(1, "source", "api", None, ("api",)),
        artifact_kind="source-architecture",
        producer_protocol_version="2.7",
        synthesis_policy_hash=digest("synthesis-policy"),
        response_schema_hash=digest("source-architecture-schema"),
        context_policy_hash=digest("synthesis-context-policy"),
        artifact_dependencies=(dependency,),
        non_artifact_dependency_hashes=(digest("topology"),),
        debt_manifest_hashes=(),
    )


def synthesis_work_template_v1() -> SynthesisWorkTemplateV1:
    key = synthesis_artifact_key_v1()
    return SynthesisWorkTemplateV1(
        schema_version=1,
        artifact_kind=key.artifact_kind,
        scope_kind=key.scope.kind,
        producer_id="echelon.re-synthesizer",
        producer_protocol_version="2.7",
        producer_authority_hash=digest("synthesizer"),
        executor_contract_hash=digest("executor-contract"),
        verifier_id="re-v2-synthesis-verifier",
        verifier_version="1",
        verifier_authority_hash=digest("verifier"),
        synthesis_policy_hash=key.synthesis_policy_hash,
        response_schema_hash=key.response_schema_hash,
        context_policy_hash=key.context_policy_hash,
        required_artifact_kinds=("source-overview-projection",),
        max_provider_attempts=2,
        max_generation_attempts=2,
        max_result_contract_retries=1,
        max_artifact_contract_retries=1,
    )


def synthesis_work_item_v1() -> SynthesisWorkItemV1:
    key = synthesis_artifact_key_v1()
    template = synthesis_work_template_v1()
    return SynthesisWorkItemV1(
        schema_version=1,
        template_id=template.template_id,
        output_key=key,
        dependency_key_ids=tuple(
            sorted(item.artifact_key_id for item in key.artifact_dependencies)
        ),
        executor_contract_hash=template.executor_contract_hash,
        verifier_id=template.verifier_id,
        verifier_version=template.verifier_version,
        verifier_authority_hash=template.verifier_authority_hash,
    )


def synthesis_root_v1() -> SynthesisRootV1:
    item = synthesis_work_item_v1()
    authority = SynthesisArtifactAuthorityV1(
        item.output_key.artifact_key_id,
        digest("source-architecture-artifact"),
        digest("source-architecture-acceptance"),
    )
    return SynthesisRootV1(
        schema_version=1,
        accepted_source_outcome_ids=(
            accepted_source_outcome_v1("api", outcome="partial").identity,
        ),
        accepted_artifacts=(authority,),
        partial_acceptance_receipt_ids=(digest("partial-acceptance"),),
        debt_manifest_hashes=(digest("api:debt"),),
        topology_id=digest("topology"),
        graph_id=digest("graph"),
        materialization_policy_hash=digest("materialization-policy"),
        producer_authority_hash=digest("synthesizer"),
        verifier_authority_hash=digest("verifier"),
        synthesis_policy_hash=digest("synthesis-policy"),
        input_quality="partial",
    )


def publication_descriptor_v1() -> PublicationDescriptorV1:
    root = synthesis_root_v1()
    return PublicationDescriptorV1(
        schema_version=1,
        run_id="re-synthesis-child",
        synthesis_root_id=root.identity,
        input_quality=root.input_quality,
        accepted_source_outcome_ids=root.accepted_source_outcome_ids,
        debt_manifest_hashes=root.debt_manifest_hashes,
        partial_acceptance_receipt_ids=root.partial_acceptance_receipt_ids,
        materialization_manifest_id=digest("materialization-manifest"),
        compatibility_generation=8,
        compatibility_index_hash=digest("compatibility-index"),
        synthesis_policy_hash=root.synthesis_policy_hash,
    )


__all__ = (
    "accepted_source_outcome_v1",
    "accepted_source_overview_projection_v1",
    "digest",
    "manifest_v6",
    "publication_descriptor_v1",
    "synthesis_artifact_key_v1",
    "synthesis_budget_policy_v1",
    "synthesis_request_v1",
    "synthesis_root_v1",
    "synthesis_work_item_v1",
    "synthesis_work_template_v1",
)
