"""Deterministic protocol-2.2 L0 inventory and source-partition producers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Mapping

from harness.re_v2.canonical import canonical_json_bytes

from .artifacts import (
    AcceptedDependencySetV2,
    ArtifactEnvelopeV1,
    DeterministicAssessmentInputV2,
    SourceBaselineRootV1,
)
from .executors import Protocol22ExecutorError
from .inputs import Protocol22InputSet, ValidatedProtocol22Inputs
from .model import ArtifactScope, WorkItemV2
from .partition import (
    DomainDescriptorV1,
    DomainPartitionDescriptorV1,
    FileRecordV1,
    ImplementationAuthorityV1,
    Protocol22PartitionError,
    SourceDescriptorV1,
    SourcePartitionIdentityInputV1,
    source_partition_id,
)
from .policies import Protocol22PolicyError, layer_policy_hash, policy_for
from .schema import (
    Protocol22SchemaError,
    exact_object,
    load_canonical_object,
    one_of,
    safe_relative_path,
)


InputsV2 = ValidatedProtocol22Inputs | Protocol22InputSet
OwnershipV1 = Literal["source", "owned", "shared_supporting"]
_OWNERSHIPS = frozenset({"source", "owned", "shared_supporting"})


class Protocol22InventoryError(Protocol22SchemaError):
    """Raised when deterministic catalog-copy authority is violated."""


def _exact(value: object, fields: tuple[str, ...], label: str) -> Mapping[str, object]:
    try:
        return exact_object(value, frozenset(fields), label)
    except Protocol22SchemaError as exc:
        raise Protocol22InventoryError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class InventoryFileV1:
    source_relative_path: str
    mode: str
    object_kind: str
    content_hash: str
    byte_count: int
    line_count: int
    text_status: str
    ownership: OwnershipV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        *FileRecordV1.FIELDS,
        "ownership",
    )

    def __post_init__(self) -> None:
        try:
            FileRecordV1(
                source_relative_path=self.source_relative_path,
                mode=self.mode,
                object_kind=self.object_kind,
                content_hash=self.content_hash,
                byte_count=self.byte_count,
                line_count=self.line_count,
                text_status=self.text_status,
            )
            one_of(self.ownership, _OWNERSHIPS, "InventoryFileV1.ownership")
        except (Protocol22SchemaError, Protocol22PartitionError) as exc:
            raise Protocol22InventoryError(str(exc)) from exc

    @property
    def sort_key(self) -> tuple[bytes, str]:
        return self.source_relative_path.encode("utf-8"), self.ownership

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_record(
        cls,
        record: FileRecordV1,
        ownership: OwnershipV1,
    ) -> "InventoryFileV1":
        if not isinstance(record, FileRecordV1):
            raise Protocol22InventoryError(
                "InventoryFileV1 requires a catalog FileRecordV1"
            )
        return cls(
            **{field: getattr(record, field) for field in FileRecordV1.FIELDS},
            ownership=ownership,
        )

    @classmethod
    def from_json_dict(cls, value: object) -> "InventoryFileV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class InventoryArtifactV1:
    schema_version: int
    artifact_kind: Literal["source-inventory", "domain-inventory"]
    scope: ArtifactScope
    partition_id: str | None
    files: tuple[InventoryFileV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "scope",
        "partition_id",
        "files",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22InventoryError(
                "InventoryArtifactV1.schema_version must be 1"
            )
        try:
            one_of(
                self.artifact_kind,
                frozenset({"source-inventory", "domain-inventory"}),
                "InventoryArtifactV1.artifact_kind",
            )
        except Protocol22SchemaError as exc:
            raise Protocol22InventoryError(str(exc)) from exc
        if not isinstance(self.scope, ArtifactScope):
            raise Protocol22InventoryError(
                "InventoryArtifactV1.scope must be ArtifactScope"
            )
        if self.scope.content_id is None:
            raise Protocol22InventoryError(
                "InventoryArtifactV1.scope requires a content_id"
            )
        if self.artifact_kind == "source-inventory":
            if self.scope.is_domain or self.partition_id is not None:
                raise Protocol22InventoryError(
                    "source inventory requires source scope and null partition_id"
                )
        elif not self.scope.is_domain or self.partition_id is None:
            raise Protocol22InventoryError(
                "domain inventory requires domain scope and partition_id"
            )
        if not isinstance(self.files, (list, tuple)) or any(
            not isinstance(item, InventoryFileV1) for item in self.files
        ):
            raise Protocol22InventoryError(
                "InventoryArtifactV1.files must contain InventoryFileV1 values"
            )
        files = tuple(self.files)
        keys = tuple(item.sort_key for item in files)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22InventoryError(
                "InventoryArtifactV1.files must be sorted and unique"
            )
        if self.artifact_kind == "source-inventory":
            if any(item.ownership != "source" for item in files):
                raise Protocol22InventoryError(
                    "source inventory files must use source ownership"
                )
        elif any(
            item.ownership not in {"owned", "shared_supporting"} for item in files
        ):
            raise Protocol22InventoryError(
                "domain inventory files must use owned or shared_supporting ownership"
            )
        object.__setattr__(self, "files", files)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "scope": self.scope.to_json_dict(),
            "partition_id": self.partition_id,
            "files": [item.to_json_dict() for item in self.files],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "InventoryArtifactV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        files = raw["files"]
        if not isinstance(files, (list, tuple)):
            raise Protocol22InventoryError(
                "InventoryArtifactV1.files must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            artifact_kind=raw["artifact_kind"],
            scope=ArtifactScope.from_json_dict(raw["scope"]),
            partition_id=raw["partition_id"],
            files=tuple(InventoryFileV1.from_json_dict(item) for item in files),
        )


@dataclass(frozen=True, slots=True)
class SourcePartitionArtifactV1:
    schema_version: int
    artifact_kind: Literal["source-partition"]
    source_scope: ArtifactScope
    source_partition_id: str
    partitioner: ImplementationAuthorityV1
    ownership_policy: ImplementationAuthorityV1
    source_supporting_paths: tuple[str, ...]
    domains: tuple[DomainPartitionDescriptorV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "artifact_kind",
        "source_scope",
        "source_partition_id",
        "partitioner",
        "ownership_policy",
        "source_supporting_paths",
        "domains",
    )

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.schema_version must be 1"
            )
        if self.artifact_kind != "source-partition":
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.artifact_kind must be source-partition"
            )
        if (
            not isinstance(self.source_scope, ArtifactScope)
            or self.source_scope.is_domain
            or self.source_scope.content_id is not None
        ):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1 requires content-free source scope"
            )
        if not isinstance(self.partitioner, ImplementationAuthorityV1) or not isinstance(
            self.ownership_policy, ImplementationAuthorityV1
        ):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1 requires partition authorities"
            )
        paths: list[str] = []
        if not isinstance(self.source_supporting_paths, (list, tuple)):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.source_supporting_paths must be an array"
            )
        for path in self.source_supporting_paths:
            try:
                paths.append(
                    safe_relative_path(
                        path,
                        "SourcePartitionArtifactV1.source_supporting_paths",
                    )
                )
            except Protocol22SchemaError as exc:
                raise Protocol22InventoryError(str(exc)) from exc
        frozen_paths = tuple(paths)
        if frozen_paths != tuple(sorted(set(frozen_paths))):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.source_supporting_paths must be sorted and unique"
            )
        object.__setattr__(self, "source_supporting_paths", frozen_paths)
        if not isinstance(self.domains, (list, tuple)) or any(
            not isinstance(item, DomainPartitionDescriptorV1) for item in self.domains
        ):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.domains must contain partition descriptors"
            )
        domains = tuple(self.domains)
        keys = tuple(item.domain_key for item in domains)
        if keys != tuple(sorted(set(keys))):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.domains must be sorted and unique"
            )
        object.__setattr__(self, "domains", domains)
        identity_input = SourcePartitionIdentityInputV1(
            source_id=self.source_scope.source_id,
            partitioner=self.partitioner,
            ownership_policy=self.ownership_policy,
            source_supporting_paths=self.source_supporting_paths,
            domains=self.domains,
        )
        if self.source_partition_id != source_partition_id(identity_input):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1 source_partition_id does not match bytes"
            )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": self.artifact_kind,
            "source_scope": self.source_scope.to_json_dict(),
            "source_partition_id": self.source_partition_id,
            "partitioner": self.partitioner.to_json_dict(),
            "ownership_policy": self.ownership_policy.to_json_dict(),
            "source_supporting_paths": list(self.source_supporting_paths),
            "domains": [item.to_json_dict() for item in self.domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SourcePartitionArtifactV1":
        raw = _exact(value, cls.FIELDS, cls.__name__)
        domains = raw["domains"]
        if not isinstance(domains, (list, tuple)):
            raise Protocol22InventoryError(
                "SourcePartitionArtifactV1.domains must be an array"
            )
        return cls(
            schema_version=raw["schema_version"],
            artifact_kind=raw["artifact_kind"],
            source_scope=ArtifactScope.from_json_dict(raw["source_scope"]),
            source_partition_id=raw["source_partition_id"],
            partitioner=ImplementationAuthorityV1.from_json_dict(raw["partitioner"]),
            ownership_policy=ImplementationAuthorityV1.from_json_dict(
                raw["ownership_policy"]
            ),
            source_supporting_paths=raw["source_supporting_paths"],
            domains=tuple(
                DomainPartitionDescriptorV1.from_json_dict(item) for item in domains
            ),
        )


def produce_source_inventory(work_item: WorkItemV2, inputs: InputsV2) -> bytes:
    source, _domain = _validate_work_item(work_item, inputs, "source-inventory")
    files = tuple(
        InventoryFileV1.from_record(record, "source") for record in source.files
    )
    artifact = InventoryArtifactV1(
        schema_version=1,
        artifact_kind="source-inventory",
        scope=work_item.output_key.scope,
        partition_id=None,
        files=files,
    )
    return _bounded_payload(work_item, inputs, artifact.to_json_dict())


def produce_domain_inventory(work_item: WorkItemV2, inputs: InputsV2) -> bytes:
    source, domain = _validate_work_item(work_item, inputs, "domain-inventory")
    if domain is None:
        raise Protocol22InventoryError("domain inventory has no domain descriptor")
    by_path = {record.source_relative_path: record for record in source.files}
    rows: list[InventoryFileV1] = []
    for relative in domain.owned_domain_relative_paths:
        path = (
            relative
            if domain.source_relative_root == "."
            else f"{domain.source_relative_root}/{relative}"
        )
        record = by_path.get(path)
        if record is None:
            raise Protocol22InventoryError(
                f"domain owned path is absent from source catalog: {path}"
            )
        rows.append(InventoryFileV1.from_record(record, "owned"))
    for path in domain.supporting_source_relative_paths:
        record = by_path.get(path)
        if record is None:
            raise Protocol22InventoryError(
                f"domain supporting path is absent from source catalog: {path}"
            )
        rows.append(InventoryFileV1.from_record(record, "shared_supporting"))
    artifact = InventoryArtifactV1(
        schema_version=1,
        artifact_kind="domain-inventory",
        scope=work_item.output_key.scope,
        partition_id=work_item.output_key.partition_id,
        files=tuple(sorted(rows, key=lambda item: item.sort_key)),
    )
    return _bounded_payload(work_item, inputs, artifact.to_json_dict())


def produce_source_partition(work_item: WorkItemV2, inputs: InputsV2) -> bytes:
    source, _domain = _validate_work_item(work_item, inputs, "source-partition")
    artifact = SourcePartitionArtifactV1(
        schema_version=1,
        artifact_kind="source-partition",
        source_scope=work_item.output_key.scope,
        source_partition_id=source.source_partition_id,
        partitioner=inputs.workspace_partition.partitioner,
        ownership_policy=inputs.workspace_partition.ownership_policy,
        source_supporting_paths=source.source_supporting_paths,
        domains=tuple(domain.partition_projection() for domain in source.domains),
    )
    return _bounded_payload(work_item, inputs, artifact.to_json_dict())


def validate_deterministic_artifact(
    work_item: WorkItemV2,
    payload: bytes,
    inputs: InputsV2,
    dependencies: AcceptedDependencySetV2,
) -> DeterministicAssessmentInputV2:
    """Validate deterministic bytes and invocation roles without mutation."""
    if not isinstance(payload, bytes):
        raise Protocol22InventoryError("deterministic artifact payload must be bytes")
    if not isinstance(dependencies, AcceptedDependencySetV2):
        raise Protocol22InventoryError(
            "deterministic validation requires AcceptedDependencySetV2"
        )
    kind = work_item.output_key.artifact_kind
    _validate_work_item(work_item, inputs, kind)

    diagnostics: set[str] = set()
    dependency_valid = _dependency_closure_valid(work_item, inputs, dependencies)
    if not dependency_valid:
        diagnostics.add("dependency_closure_invalid")

    canonical_valid = True
    decoded: object | None = None
    try:
        if kind in {"source-inventory", "domain-inventory"}:
            decoded = load_canonical_object(payload, InventoryArtifactV1.from_json_dict)
        elif kind == "source-partition":
            decoded = load_canonical_object(
                payload,
                SourcePartitionArtifactV1.from_json_dict,
            )
        elif kind == "source-baseline-root":
            decoded = load_canonical_object(payload, SourceBaselineRootV1.from_json_dict)
        else:
            raise Protocol22InventoryError(
                f"deterministic validator does not yet support {kind}"
            )
    except (Protocol22SchemaError, Protocol22InventoryError):
        canonical_valid = False
        diagnostics.add("canonical_schema_invalid")

    policy_valid = False
    if canonical_valid and decoded is not None:
        if kind == "source-inventory":
            expected = produce_source_inventory(work_item, inputs)
            policy_valid = payload == expected
        elif kind == "domain-inventory":
            expected = produce_domain_inventory(work_item, inputs)
            policy_valid = payload == expected
        elif kind == "source-partition":
            expected = produce_source_partition(work_item, inputs)
            policy_valid = payload == expected
        else:
            policy_valid = _source_root_matches(
                work_item,
                decoded,
                inputs,
                dependencies,
            )
        if not policy_valid:
            diagnostics.add("catalog_projection_mismatch")

    return DeterministicAssessmentInputV2(
        canonical_schema_valid=canonical_valid,
        dependency_closure_valid=dependency_valid,
        policy_conformance_valid=policy_valid,
        depth_debt=None,
        normalized_diagnostics=tuple(sorted(diagnostics)),
    )


def _validate_work_item(
    work_item: WorkItemV2,
    inputs: InputsV2,
    expected_kind: str,
) -> tuple[SourceDescriptorV1, DomainDescriptorV1 | None]:
    if not isinstance(work_item, WorkItemV2):
        raise Protocol22InventoryError(
            "deterministic producer requires schema-2 WorkItemV2"
        )
    if not isinstance(inputs, (ValidatedProtocol22Inputs, Protocol22InputSet)):
        raise Protocol22InventoryError(
            "deterministic producer requires validated protocol-2.2 inputs"
        )
    key = work_item.output_key
    if key.artifact_kind != expected_kind:
        raise Protocol22InventoryError(
            f"work item artifact kind must be {expected_kind}"
        )
    if expected_kind not in {
        "source-inventory",
        "domain-inventory",
        "source-partition",
        "source-baseline-root",
    }:
        raise Protocol22InventoryError(
            f"unsupported deterministic artifact kind: {expected_kind}"
        )
    if key.layer != ("L1" if expected_kind == "source-baseline-root" else "L0"):
        raise Protocol22InventoryError("work item layer does not match artifact kind")
    sources = [
        source
        for source in inputs.workspace_partition.sources
        if source.source_id == key.scope.source_id
    ]
    if len(sources) != 1:
        raise Protocol22InventoryError(
            "work item scope source is not uniquely declared"
        )
    source = sources[0]
    domain: DomainDescriptorV1 | None = None
    if expected_kind == "domain-inventory":
        domains = [
            item for item in source.domains if item.domain_key == key.scope.domain_key
        ]
        if len(domains) != 1:
            raise Protocol22InventoryError(
                "work item scope domain is not uniquely declared"
            )
        domain = domains[0]
        expected_scope = ArtifactScope(
            source_id=source.source_id,
            domain_key=domain.domain_key,
            content_id=domain.domain_content_id,
        )
        expected_partition = domain.domain_partition_id
    elif expected_kind == "source-partition":
        expected_scope = ArtifactScope(source.source_id, None, None)
        expected_partition = source.source_partition_id
    else:
        expected_scope = ArtifactScope(
            source.source_id,
            None,
            source.source_content_id,
        )
        expected_partition = (
            None if expected_kind == "source-inventory" else source.source_partition_id
        )
    if key.scope != expected_scope or key.partition_id != expected_partition:
        raise Protocol22InventoryError(
            "work item scope or partition does not match catalog authority"
        )
    family = {
        "source-inventory": "inventory",
        "domain-inventory": "inventory",
        "source-partition": "partition",
        "source-baseline-root": "source-baseline-root",
    }[expected_kind]
    if work_item.producer_family != family:
        raise Protocol22InventoryError(
            "work item producer family does not match artifact kind"
        )
    try:
        policy = policy_for(inputs.artifact_policy, key.layer, expected_kind)
        executor = inputs.executor_contract.entry_for(family)
    except (Protocol22PolicyError, Protocol22ExecutorError) as exc:
        raise Protocol22InventoryError(str(exc)) from exc
    expected_fields = {
        "producer_protocol_version": policy.producer_protocol_version,
        "layer_policy_hash": layer_policy_hash(policy),
        "executor_contract_hash": executor.executor_contract_hash,
        "verifier_id": executor.verifier.verifier_id,
        "verifier_version": executor.verifier.verifier_version,
        "verifier_implementation_digest": executor.verifier.implementation_digest,
        "result_contract_id": policy.result_contract_id,
    }
    for field, expected in expected_fields.items():
        actual = getattr(key, field) if field == "layer_policy_hash" else getattr(
            work_item, field
        )
        if actual != expected:
            raise Protocol22InventoryError(
                f"work item {field} does not match immutable policy/executor authority"
            )
    if executor.execution_mode != "in_process":
        raise Protocol22InventoryError(
            "deterministic producer requires in_process executor authority"
        )
    if expected_kind != "source-baseline-root" and key.dependency_hashes:
        raise Protocol22InventoryError(
            "inventory and partition work must have no graph dependencies"
        )
    return source, domain


def _bounded_payload(
    work_item: WorkItemV2,
    inputs: InputsV2,
    value: object,
) -> bytes:
    payload = canonical_json_bytes(value)
    policy = policy_for(
        inputs.artifact_policy,
        work_item.output_key.layer,
        work_item.output_key.artifact_kind,
    )
    if len(payload) > policy.max_canonical_json_bytes:
        raise Protocol22InventoryError(
            f"{work_item.output_key.artifact_kind} exceeds its canonical byte limit"
        )
    return payload


def _dependency_closure_valid(
    work_item: WorkItemV2,
    inputs: InputsV2,
    dependencies: AcceptedDependencySetV2,
) -> bool:
    kind = work_item.output_key.artifact_kind
    if kind in {"source-inventory", "domain-inventory", "source-partition"}:
        if set(dependencies.by_role) != {"workspace_partition"}:
            return False
        value = dependencies.by_role["workspace_partition"]
        expected = inputs.workspace_partition.identity
        return value.artifact_key_id == expected and value.artifact_hash == expected
    if kind == "source-baseline-root":
        source = next(
            item
            for item in inputs.workspace_partition.sources
            if item.source_id == work_item.output_key.scope.source_id
        )
        expected_roles = {
            "source_overview",
            *(f"domain:{domain.domain_key}" for domain in source.domains),
        }
        if set(dependencies.by_role) != expected_roles:
            return False
        hashes = tuple(
            sorted(value.artifact_hash for value in dependencies.by_role.values())
        )
        return hashes == work_item.output_key.dependency_hashes
    return False


def _source_root_matches(
    work_item: WorkItemV2,
    decoded: object,
    inputs: InputsV2,
    dependencies: AcceptedDependencySetV2,
) -> bool:
    if not isinstance(decoded, SourceBaselineRootV1):
        return False
    if not _dependency_closure_valid(work_item, inputs, dependencies):
        return False
    key = work_item.output_key
    expected_envelope = ArtifactEnvelopeV1(
        artifact_kind=key.artifact_kind,
        layer=key.layer,
        scope=key.scope,
        partition_id=key.partition_id,
        layer_policy_hash=key.layer_policy_hash,
        dependency_hashes=key.dependency_hashes,
    )
    if decoded.artifact != expected_envelope:
        return False
    source = next(
        item
        for item in inputs.workspace_partition.sources
        if item.source_id == key.scope.source_id
    )
    expected_domains = tuple(
        (
            domain.domain_key,
            domain.presentation_domain_id,
            dependencies.by_role[f"domain:{domain.domain_key}"].artifact_hash,
        )
        for domain in source.domains
    )
    actual_domains = tuple(
        (
            domain.domain_key,
            domain.presentation_domain_id,
            domain.baseline_artifact_hash,
        )
        for domain in decoded.domains
    )
    return (
        decoded.overview_artifact_hash
        == dependencies.by_role["source_overview"].artifact_hash
        and actual_domains == expected_domains
    )


__all__ = (
    "InventoryArtifactV1",
    "InventoryFileV1",
    "Protocol22InventoryError",
    "SourcePartitionArtifactV1",
    "produce_domain_inventory",
    "produce_source_inventory",
    "produce_source_partition",
    "validate_deterministic_artifact",
)
