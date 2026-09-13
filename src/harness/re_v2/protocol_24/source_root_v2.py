"""Versioned source-root authority that supports selected zero-domain sources."""

from __future__ import annotations

from dataclasses import dataclass, replace

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.protocol_22.artifacts import (
    AcceptedDependencySetV2,
    DeterministicAssessmentInputV2,
)
from harness.re_v2.protocol_22.baseline import (
    Protocol22CertificationError,
    certify_deterministic_artifact,
)
from harness.re_v2.protocol_22.executors import ExecutorContractCatalogV1
from harness.re_v2.protocol_22.model import WorkItemV2
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    load_canonical_object,
)
from harness.re_v2.protocol_24.artifacts import (
    L2SourceBaselineRootV1,
    L2SourceRootEnvelopeV1,
    L2_ROOT_PRODUCER_FAMILY,
    SourceBaselineDomainV1,
)


SOURCE_ROOT_V2_ADAPTER_ID = "re-v2-in-process-deepening-source-root-v2"
SOURCE_ROOT_V2_VERIFIER_ID = "deepening-source-root-verifier-v2"
SOURCE_ROOT_V2_PROTOCOL_VERSION = "source-baseline-root-v2"


@dataclass(frozen=True, slots=True)
class Protocol24SourceRootRuntimeV2:
    inputs: object

    def produce(self, item: object, dependencies: object) -> bytes:
        return build_l2_source_baseline_root_v2(
            item,
            dependencies,
            self.inputs.workspace_partition,
        )

    def certify_deterministic(
        self,
        item: object,
        payload: bytes,
        dependencies: object,
    ) -> object:
        expected = self.produce(item, dependencies)
        canonical_valid = True
        try:
            load_canonical_object(payload, L2SourceBaselineRootV2.from_json_dict)
        except Exception:
            canonical_valid = False
        diagnostics = tuple(
            sorted(
                {
                    *(() if canonical_valid else ("canonical_schema_invalid",)),
                    *(
                        ()
                        if payload == expected
                        else ("deterministic_reconstruction_mismatch",)
                    ),
                }
            )
        )
        assessment = DeterministicAssessmentInputV2(
            canonical_schema_valid=canonical_valid,
            dependency_closure_valid=True,
            policy_conformance_valid=payload == expected,
            depth_debt=None,
            normalized_diagnostics=diagnostics,
        )
        executor = self.inputs.executor_contract.entry_for(
            getattr(item, "producer_family")
        )
        return certify_deterministic_artifact(
            item,
            content_digest(payload),
            assessment,
            executor.verifier,
        )


@dataclass(frozen=True, slots=True)
class L2SourceBaselineRootV2(L2SourceBaselineRootV1):
    """The v1 envelope with an explicitly valid empty selected-domain set."""

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22SchemaError("L2 source root schema_version must be 1")
        if not isinstance(self.artifact, L2SourceRootEnvelopeV1):
            raise Protocol22SchemaError("L2 source root envelope is invalid")
        digest_value(self.overview_artifact_hash, "L2 source root overview hash")
        if not isinstance(self.domains, (list, tuple)) or any(
            not isinstance(item, SourceBaselineDomainV1) for item in self.domains
        ):
            raise Protocol22SchemaError("L2 source root domains are invalid")
        domains = tuple(self.domains)
        keys = tuple(item.domain_key for item in domains)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22SchemaError(
                "L2 source root domains must be sorted and unique"
            )
        expected = tuple(
            sorted(
                (
                    self.overview_artifact_hash,
                    *(item.baseline_artifact_hash for item in domains),
                )
            )
        )
        if self.artifact.dependency_hashes != expected:
            raise Protocol22SchemaError(
                "L2 source root dependency hashes do not equal selected outputs"
            )
        object.__setattr__(self, "domains", domains)


def build_l2_source_baseline_root_v2(
    work_item: WorkItemV2,
    accepted_inputs: AcceptedDependencySetV2,
    partition: WorkspacePartitionCatalogV1,
) -> bytes:
    """Bind an L2 overview and zero or more selected L2 domain outputs."""
    if (
        not isinstance(work_item, WorkItemV2)
        or work_item.output_key.artifact_kind != "source-baseline-root"
        or work_item.output_key.layer != "L2"
        or work_item.goal_id != "selective-deepening"
        or work_item.producer_family != L2_ROOT_PRODUCER_FAMILY
        or work_item.producer_protocol_version != SOURCE_ROOT_V2_PROTOCOL_VERSION
        or not isinstance(accepted_inputs, AcceptedDependencySetV2)
        or not isinstance(partition, WorkspacePartitionCatalogV1)
    ):
        raise Protocol22CertificationError("L2 source root v2 invocation is invalid")
    source = next(
        (
            value
            for value in partition.sources
            if value.source_id == work_item.output_key.scope.source_id
        ),
        None,
    )
    if source is None or work_item.output_key.partition_id != source.source_partition_id:
        raise Protocol22CertificationError("L2 source root scope is not partitioned")
    domain_roles = tuple(
        sorted(role for role in accepted_inputs.by_role if role.startswith("domain:"))
    )
    if frozenset(accepted_inputs.by_role) != frozenset(
        {"source_overview", *domain_roles}
    ):
        raise Protocol22CertificationError(
            "L2 source root dependency roles are invalid"
        )
    if tuple(
        sorted(artifact.artifact_hash for artifact in accepted_inputs.by_role.values())
    ) != work_item.required_artifact_hashes:
        raise Protocol22CertificationError(
            "accepted dependency hashes do not match work item authority"
        )
    by_domain = {domain.domain_key: domain for domain in source.domains}
    domains: list[SourceBaselineDomainV1] = []
    for role in domain_roles:
        domain_key = role.removeprefix("domain:")
        descriptor = by_domain.get(domain_key)
        if descriptor is None:
            raise Protocol22CertificationError(
                "L2 source root contains an unpartitioned domain"
            )
        domains.append(
            SourceBaselineDomainV1(
                domain_key=domain_key,
                presentation_domain_id=descriptor.presentation_domain_id,
                baseline_artifact_hash=accepted_inputs.by_role[role].artifact_hash,
            )
        )
    root = L2SourceBaselineRootV2(
        schema_version=1,
        artifact=L2SourceRootEnvelopeV1(
            artifact_kind="source-baseline-root",
            layer="L2",
            scope=work_item.output_key.scope,
            partition_id=work_item.output_key.partition_id,
            layer_policy_hash=work_item.output_key.layer_policy_hash,
            dependency_hashes=work_item.output_key.dependency_hashes,
        ),
        overview_artifact_hash=accepted_inputs.by_role[
            "source_overview"
        ].artifact_hash,
        domains=tuple(sorted(domains, key=lambda value: value.domain_key)),
    )
    return canonical_json_bytes(root.to_json_dict())


def upgrade_source_root_executor_catalog_v2(
    catalog: object,
    implementation_digest: str,
) -> ExecutorContractCatalogV1:
    """Version only the root entry, preserving every unrelated authority byte."""
    if not isinstance(catalog, ExecutorContractCatalogV1):
        raise Protocol22SchemaError("source-root v2 upgrade requires executor catalog")
    implementation = digest_value(
        implementation_digest,
        "source_root_v2_implementation_digest",
    )
    legacy = catalog.entry_for(L2_ROOT_PRODUCER_FAMILY)
    root = replace(
        legacy,
        adapter_id=SOURCE_ROOT_V2_ADAPTER_ID,
        executor_implementation_digest=implementation,
        producer_protocol_version=SOURCE_ROOT_V2_PROTOCOL_VERSION,
        verifier=replace(
            legacy.verifier,
            verifier_id=SOURCE_ROOT_V2_VERIFIER_ID,
            verifier_version="v2",
            implementation_digest=implementation,
        ),
    )
    return ExecutorContractCatalogV1(
        schema_version=1,
        entries=tuple(
            sorted(
                (
                    *(entry for entry in catalog.entries if entry != legacy),
                    root,
                ),
                key=lambda entry: entry.producer_family,
            )
        ),
    )


__all__ = (
    "L2SourceBaselineRootV2",
    "Protocol24SourceRootRuntimeV2",
    "SOURCE_ROOT_V2_ADAPTER_ID",
    "SOURCE_ROOT_V2_PROTOCOL_VERSION",
    "SOURCE_ROOT_V2_VERIFIER_ID",
    "build_l2_source_baseline_root_v2",
    "upgrade_source_root_executor_catalog_v2",
)
