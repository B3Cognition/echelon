"""Deterministic protocol-2.7 synthesis topology and dynamic work graph."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import ClassVar, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
)

from .model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    SynthesisArtifactDependencyV1,
    SynthesisArtifactKeyV1,
    SynthesisScopeV1,
    SynthesisWorkItemV1,
    SynthesisWorkTemplateV1,
)
from .policies import (
    SYNTHESIS_GENERATED_KINDS,
    SynthesisPolicyCatalogV1,
)


_LAYERS = ("source", "workspace-domain", "workspace")


class Protocol27GraphError(Protocol22SchemaError):
    """Raised when synthesis topology or dependency closure is invalid."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27GraphError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27GraphError(str(exc)) from exc


def _identity(value: object) -> str:
    return content_digest(value)


def _typed_tuple(
    value: object,
    expected: type,
    field: str,
    *,
    key,
    nonempty: bool = False,
) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, expected) for item in value
    ):
        raise Protocol27GraphError(f"{field} must contain {expected.__name__} values")
    result = tuple(value)
    keys = tuple(key(item) for item in result)
    if (nonempty and not result) or keys != tuple(sorted(set(keys))):
        raise Protocol27GraphError(f"{field} must be nonempty, sorted, and unique")
    return result


def _digests(value: object, field: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27GraphError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if (nonempty and not result) or result != tuple(sorted(set(result))):
        raise Protocol27GraphError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class WorkspaceDomainParticipantV1:
    schema_version: int
    source_id: str
    domain_key: str
    domain_content_id: str
    domain_partition_id: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "domain_key",
        "domain_content_id",
        "domain_partition_id",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "domain participant schema")
        _schema(safe_id, self.source_id, "domain participant source ID")
        for field in self.FIELDS[2:]:
            _schema(digest_value, getattr(self, field), field)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkspaceDomainParticipantV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class WorkspaceDomainV1:
    schema_version: int
    workspace_domain_id: str
    participants: tuple[WorkspaceDomainParticipantV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "workspace_domain_id",
        "participants",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "workspace domain schema")
        participants = _typed_tuple(
            self.participants,
            WorkspaceDomainParticipantV1,
            "workspace domain participants",
            key=lambda item: item.identity,
            nonempty=True,
        )
        expected = _identity(
            {
                "participants": [item.identity for item in participants],
                "schema_version": 1,
            }
        )
        if self.workspace_domain_id != expected:
            raise Protocol27GraphError(
                "workspace domain ID differs from canonical participant authority"
            )
        object.__setattr__(self, "participants", participants)

    @classmethod
    def from_participants(
        cls,
        participants: tuple[WorkspaceDomainParticipantV1, ...],
    ) -> "WorkspaceDomainV1":
        ordered = tuple(sorted(participants, key=lambda item: item.identity))
        domain_id = _identity(
            {
                "participants": [item.identity for item in ordered],
                "schema_version": 1,
            }
        )
        return cls(1, domain_id, ordered)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "workspace_domain_id": self.workspace_domain_id,
            "participants": [item.to_json_dict() for item in self.participants],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkspaceDomainV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        participants = raw["participants"]
        if not isinstance(participants, (list, tuple)):
            raise Protocol27GraphError("workspace domain participants must be an array")
        return cls(
            raw["schema_version"],
            raw["workspace_domain_id"],
            tuple(WorkspaceDomainParticipantV1.from_json_dict(item) for item in participants),
        )


@dataclass(frozen=True, slots=True)
class SynthesisSourceTopologyV1:
    schema_version: int
    source_id: str
    source_content_id: str
    source_partition_id: str
    domain_participant_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "source_id",
        "source_content_id",
        "source_partition_id",
        "domain_participant_ids",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "source topology schema")
        _schema(safe_id, self.source_id, "source topology source ID")
        _schema(digest_value, self.source_content_id, "source content ID")
        _schema(digest_value, self.source_partition_id, "source partition ID")
        object.__setattr__(
            self,
            "domain_participant_ids",
            _digests(self.domain_participant_ids, "source topology domain participants"),
        )

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_id": self.source_id,
            "source_content_id": self.source_content_id,
            "source_partition_id": self.source_partition_id,
            "domain_participant_ids": list(self.domain_participant_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisSourceTopologyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class WorkspaceSynthesisTopologyV1:
    schema_version: int
    partition_manifest_id: str
    sources: tuple[SynthesisSourceTopologyV1, ...]
    workspace_domains: tuple[WorkspaceDomainV1, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "partition_manifest_id",
        "sources",
        "workspace_domains",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "workspace synthesis topology schema")
        _schema(digest_value, self.partition_manifest_id, "partition manifest ID")
        sources = _typed_tuple(
            self.sources,
            SynthesisSourceTopologyV1,
            "workspace synthesis sources",
            key=lambda item: item.source_id,
            nonempty=True,
        )
        domains = _typed_tuple(
            self.workspace_domains,
            WorkspaceDomainV1,
            "workspace synthesis domains",
            key=lambda item: item.workspace_domain_id,
        )
        participant_ids = {
            item.identity
            for domain in domains
            for item in domain.participants
        }
        if participant_ids != {
            participant
            for source in sources
            for participant in source.domain_participant_ids
        }:
            raise Protocol27GraphError(
                "workspace topology source and domain participant authority disagree"
            )
        if any(
            participant.source_id not in {source.source_id for source in sources}
            for domain in domains
            for participant in domain.participants
        ):
            raise Protocol27GraphError("workspace domain references an unknown source")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "workspace_domains", domains)

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def topology_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "partition_manifest_id": self.partition_manifest_id,
            "sources": [item.to_json_dict() for item in self.sources],
            "workspace_domains": [item.to_json_dict() for item in self.workspace_domains],
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "WorkspaceSynthesisTopologyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        sources = raw["sources"]
        domains = raw["workspace_domains"]
        if not isinstance(sources, (list, tuple)) or not isinstance(domains, (list, tuple)):
            raise Protocol27GraphError("workspace topology sources/domains must be arrays")
        return cls(
            raw["schema_version"],
            raw["partition_manifest_id"],
            tuple(SynthesisSourceTopologyV1.from_json_dict(item) for item in sources),
            tuple(WorkspaceDomainV1.from_json_dict(item) for item in domains),
        )


def build_workspace_synthesis_topology(
    partition: WorkspacePartitionCatalogV1,
) -> WorkspaceSynthesisTopologyV1:
    if not isinstance(partition, WorkspacePartitionCatalogV1):
        raise Protocol27GraphError("workspace topology requires partition authority")
    if not partition.sources:
        raise Protocol27GraphError("workspace topology requires at least one source")
    participants_by_source: dict[str, list[WorkspaceDomainParticipantV1]] = {}
    domains: list[WorkspaceDomainV1] = []
    for source in partition.sources:
        participants_by_source[source.source_id] = []
        for domain in source.domains:
            participant = WorkspaceDomainParticipantV1(
                1,
                source.source_id,
                domain.domain_key,
                domain.domain_content_id,
                domain.domain_partition_id,
            )
            participants_by_source[source.source_id].append(participant)
            # Partition authority does not claim cross-source semantic grouping.
            # Each authenticated source/domain membership is therefore one safe
            # workspace-domain synthesis unit.
            domains.append(WorkspaceDomainV1.from_participants((participant,)))
    sources = tuple(
        SynthesisSourceTopologyV1(
            1,
            source.source_id,
            source.source_content_id,
            source.source_partition_id,
            tuple(
                sorted(
                    item.identity for item in participants_by_source[source.source_id]
                )
            ),
        )
        for source in partition.sources
    )
    return WorkspaceSynthesisTopologyV1(
        1,
        partition.identity,
        sources,
        tuple(sorted(domains, key=lambda item: item.workspace_domain_id)),
    )


@dataclass(frozen=True, slots=True)
class SynthesisGraphInputsV1:
    accepted_sources: tuple[AcceptedSourceOutcomeV1, ...]
    source_overviews: AcceptedSourceOverviewCatalogV1
    topology: WorkspaceSynthesisTopologyV1
    policy_catalog: SynthesisPolicyCatalogV1
    response_schema_hashes: Mapping[str, str]
    context_policy_hash: str

    def __post_init__(self) -> None:
        sources = _typed_tuple(
            self.accepted_sources,
            AcceptedSourceOutcomeV1,
            "accepted source outcomes",
            key=lambda item: item.source_id,
            nonempty=True,
        )
        if not isinstance(self.source_overviews, AcceptedSourceOverviewCatalogV1):
            raise Protocol27GraphError("source overview catalog is invalid")
        if not isinstance(self.topology, WorkspaceSynthesisTopologyV1):
            raise Protocol27GraphError("synthesis topology is invalid")
        if not isinstance(self.policy_catalog, SynthesisPolicyCatalogV1):
            raise Protocol27GraphError("synthesis policy catalog is invalid")
        source_ids = tuple(item.source_id for item in sources)
        if source_ids != tuple(item.source_id for item in self.source_overviews.projections):
            raise Protocol27GraphError("accepted source and overview catalogs disagree")
        if source_ids != tuple(item.source_id for item in self.topology.sources):
            raise Protocol27GraphError("accepted source and topology catalogs disagree")
        outcomes = {item.source_id: item for item in sources}
        for projection in self.source_overviews.projections:
            source = outcomes[projection.source_id]
            if (
                projection.source_root_key_id != source.source_root_key_id
                or projection.source_root_hash != source.source_root_hash
            ):
                raise Protocol27GraphError(
                    f"source overview root authority mismatch: {projection.source_id}"
                )
        if not isinstance(self.response_schema_hashes, Mapping):
            raise Protocol27GraphError("response schema hashes must be a mapping")
        schemas = dict(sorted(self.response_schema_hashes.items()))
        if set(schemas) != SYNTHESIS_GENERATED_KINDS:
            raise Protocol27GraphError(
                "response schema hashes must exactly cover generated synthesis kinds"
            )
        for kind, schema_hash in schemas.items():
            _schema(safe_id, kind, "response schema kind")
            _schema(digest_value, schema_hash, "response schema hash")
        _schema(digest_value, self.context_policy_hash, "context policy hash")
        object.__setattr__(self, "accepted_sources", sources)
        object.__setattr__(
            self, "response_schema_hashes", MappingProxyType(schemas)
        )


@dataclass(frozen=True, slots=True)
class SynthesisGraphNodeV1:
    schema_version: int
    scope: SynthesisScopeV1
    artifact_kind: str
    template_id: str
    generated_dependency_node_ids: tuple[str, ...]
    fixed_artifact_dependencies: tuple[SynthesisArtifactDependencyV1, ...]
    non_artifact_dependency_hashes: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]
    public_path: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "scope",
        "artifact_kind",
        "template_id",
        "generated_dependency_node_ids",
        "fixed_artifact_dependencies",
        "non_artifact_dependency_hashes",
        "debt_manifest_hashes",
        "public_path",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis graph node schema")
        if not isinstance(self.scope, SynthesisScopeV1):
            raise Protocol27GraphError("synthesis graph node scope is invalid")
        _schema(one_of, self.artifact_kind, SYNTHESIS_GENERATED_KINDS, "node kind")
        _schema(digest_value, self.template_id, "node template ID")
        object.__setattr__(
            self,
            "generated_dependency_node_ids",
            _digests(self.generated_dependency_node_ids, "generated dependency nodes"),
        )
        fixed = _typed_tuple(
            self.fixed_artifact_dependencies,
            SynthesisArtifactDependencyV1,
            "fixed artifact dependencies",
            key=lambda item: item.identity,
        )
        object.__setattr__(self, "fixed_artifact_dependencies", fixed)
        object.__setattr__(
            self,
            "non_artifact_dependency_hashes",
            _digests(self.non_artifact_dependency_hashes, "non-artifact dependencies"),
        )
        object.__setattr__(
            self,
            "debt_manifest_hashes",
            _digests(self.debt_manifest_hashes, "node debt manifests"),
        )
        path = PurePosixPath(self.public_path)
        if (
            path.is_absolute()
            or path.as_posix() != self.public_path
            or any(part in {"", ".", ".."} for part in path.parts)
            or not self.public_path.startswith("re/")
        ):
            raise Protocol27GraphError("synthesis node public path is unsafe")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def node_id(self) -> str:
        return self.identity

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "scope": self.scope.to_json_dict(),
            "artifact_kind": self.artifact_kind,
            "template_id": self.template_id,
            "generated_dependency_node_ids": list(self.generated_dependency_node_ids),
            "fixed_artifact_dependencies": [
                item.to_json_dict() for item in self.fixed_artifact_dependencies
            ],
            "non_artifact_dependency_hashes": list(self.non_artifact_dependency_hashes),
            "debt_manifest_hashes": list(self.debt_manifest_hashes),
            "public_path": self.public_path,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisGraphNodeV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        dependencies = raw["fixed_artifact_dependencies"]
        if not isinstance(dependencies, (list, tuple)):
            raise Protocol27GraphError("fixed artifact dependencies must be an array")
        return cls(
            schema_version=raw["schema_version"],
            scope=SynthesisScopeV1.from_json_dict(raw["scope"]),
            artifact_kind=raw["artifact_kind"],
            template_id=raw["template_id"],
            generated_dependency_node_ids=raw["generated_dependency_node_ids"],
            fixed_artifact_dependencies=tuple(
                SynthesisArtifactDependencyV1.from_json_dict(item)
                for item in dependencies
            ),
            non_artifact_dependency_hashes=raw["non_artifact_dependency_hashes"],
            debt_manifest_hashes=raw["debt_manifest_hashes"],
            public_path=raw["public_path"],
        )


@dataclass(frozen=True, slots=True)
class SynthesisRootSpecificationV1:
    schema_version: int
    accepted_source_outcome_ids: tuple[str, ...]
    required_node_ids: tuple[str, ...]
    debt_manifest_hashes: tuple[str, ...]
    input_quality: str

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "accepted_source_outcome_ids",
        "required_node_ids",
        "debt_manifest_hashes",
        "input_quality",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "root specification schema")
        object.__setattr__(
            self,
            "accepted_source_outcome_ids",
            _digests(self.accepted_source_outcome_ids, "root source outcomes", nonempty=True),
        )
        object.__setattr__(
            self,
            "required_node_ids",
            _digests(self.required_node_ids, "root required nodes", nonempty=True),
        )
        debts = _digests(self.debt_manifest_hashes, "root debt manifests")
        object.__setattr__(self, "debt_manifest_hashes", debts)
        _schema(one_of, self.input_quality, frozenset({"complete", "partial"}), "input quality")
        if (self.input_quality == "partial") != bool(debts):
            raise Protocol27GraphError("root input quality disagrees with debt authority")

    @property
    def identity(self) -> str:
        return _identity(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "accepted_source_outcome_ids": list(self.accepted_source_outcome_ids),
            "required_node_ids": list(self.required_node_ids),
            "debt_manifest_hashes": list(self.debt_manifest_hashes),
            "input_quality": self.input_quality,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisRootSpecificationV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisGraph:
    schema_version: int
    topology: WorkspaceSynthesisTopologyV1
    policy_catalog: SynthesisPolicyCatalogV1
    response_schema_hashes: Mapping[str, str]
    context_policy_hash: str
    templates: tuple[SynthesisWorkTemplateV1, ...]
    required_nodes: tuple[SynthesisGraphNodeV1, ...]
    public_paths: Mapping[str, str]
    root_specification: SynthesisRootSpecificationV1

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "topology",
        "policy_catalog",
        "response_schema_hashes",
        "context_policy_hash",
        "templates",
        "required_nodes",
        "public_paths",
        "root_specification",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis graph schema")
        if not isinstance(self.topology, WorkspaceSynthesisTopologyV1):
            raise Protocol27GraphError("synthesis graph topology is invalid")
        if not isinstance(self.policy_catalog, SynthesisPolicyCatalogV1):
            raise Protocol27GraphError("synthesis graph policy is invalid")
        schemas = dict(sorted(self.response_schema_hashes.items()))
        if set(schemas) != SYNTHESIS_GENERATED_KINDS:
            raise Protocol27GraphError("synthesis graph response schema set is invalid")
        for value in schemas.values():
            _schema(digest_value, value, "synthesis graph response schema")
        _schema(digest_value, self.context_policy_hash, "synthesis graph context policy")
        templates = _typed_tuple(
            self.templates,
            SynthesisWorkTemplateV1,
            "synthesis graph templates",
            key=lambda item: item.artifact_kind,
            nonempty=True,
        )
        nodes = _typed_tuple(
            self.required_nodes,
            SynthesisGraphNodeV1,
            "synthesis graph nodes",
            key=lambda item: item.node_id,
            nonempty=True,
        )
        by_id = {item.node_id: item for item in nodes}
        template_by_kind = {item.artifact_kind: item for item in templates}
        if set(template_by_kind) != SYNTHESIS_GENERATED_KINDS:
            raise Protocol27GraphError(
                "synthesis graph templates must exactly cover generated kinds"
            )
        _validate_templates(
            template_by_kind,
            self.policy_catalog,
            schemas,
            self.context_policy_hash,
        )
        if any(
            dependency not in by_id
            for item in nodes
            for dependency in item.generated_dependency_node_ids
        ):
            raise Protocol27GraphError("synthesis graph has an unknown dependency node")
        _validate_acyclic(by_id)
        _validate_graph_shape(
            self.topology,
            self.policy_catalog,
            template_by_kind,
            by_id,
        )
        paths = dict(sorted(self.public_paths.items()))
        for key, path in paths.items():
            _schema(digest_value, key, "public path authority ID")
            candidate = PurePosixPath(path)
            if (
                candidate.is_absolute()
                or candidate.as_posix() != path
                or not path.startswith("re/")
            ):
                raise Protocol27GraphError("synthesis public path is unsafe")
        if len(paths.values()) != len(set(paths.values())):
            raise Protocol27GraphError("synthesis public paths must be unique")
        if {item.public_path for item in nodes} - set(paths.values()):
            raise Protocol27GraphError("synthesis graph node public path is unregistered")
        expected_path_ids = set(by_id) | {
            dependency.artifact_key_id
            for item in nodes
            for dependency in item.fixed_artifact_dependencies
        }
        if set(paths) != expected_path_ids:
            raise Protocol27GraphError(
                "synthesis public paths do not exactly cover nodes and adopted overviews"
            )
        if not isinstance(self.root_specification, SynthesisRootSpecificationV1):
            raise Protocol27GraphError("synthesis root specification is invalid")
        if self.root_specification.required_node_ids != tuple(sorted(by_id)):
            raise Protocol27GraphError("synthesis root does not cover every graph node")
        object.__setattr__(self, "response_schema_hashes", MappingProxyType(schemas))
        object.__setattr__(self, "templates", templates)
        object.__setattr__(self, "required_nodes", nodes)
        object.__setattr__(self, "public_paths", MappingProxyType(paths))

    @property
    def graph_id(self) -> str:
        return _identity(self.to_json_dict())

    @property
    def required_node_ids(self) -> tuple[str, ...]:
        return tuple(item.node_id for item in self.required_nodes)

    def ready_work_items(
        self,
        accepted_node_hashes: Mapping[str, str],
    ) -> tuple[SynthesisWorkItemV1, ...]:
        accepted = self._validated_accepted_prefix(accepted_node_hashes)
        result = []
        for node in self.required_nodes:
            if node.node_id in accepted:
                continue
            if not set(node.generated_dependency_node_ids).issubset(accepted):
                continue
            result.append(self._work_item(node, accepted))
        return tuple(sorted(result, key=lambda item: item.work_item_id))

    def node_for_work_item(self, item: SynthesisWorkItemV1) -> SynthesisGraphNodeV1:
        matches = [
            node
            for node in self.required_nodes
            if node.template_id == item.template_id
            and node.scope == item.output_key.scope
            and node.artifact_kind == item.output_key.artifact_kind
        ]
        if len(matches) != 1:
            raise Protocol27GraphError("work item does not resolve to one graph node")
        return matches[0]

    def affected_by_source(self, source_id: str) -> tuple[str, ...]:
        source_nodes = {
            item.node_id
            for item in self.required_nodes
            if item.scope.kind == "source" and item.scope.source_id == source_id
        }
        source_domains = {
            domain.workspace_domain_id
            for domain in self.topology.workspace_domains
            if any(item.source_id == source_id for item in domain.participants)
        }
        affected = source_nodes | {
            item.node_id
            for item in self.required_nodes
            if item.scope.workspace_domain_id in source_domains
        }
        changed = True
        while changed:
            before = len(affected)
            affected.update(
                item.node_id
                for item in self.required_nodes
                if set(item.generated_dependency_node_ids) & affected
            )
            changed = len(affected) != before
        return tuple(sorted(affected))

    def _validated_accepted_prefix(
        self, accepted_node_hashes: Mapping[str, str]
    ) -> Mapping[str, str]:
        if not isinstance(accepted_node_hashes, Mapping):
            raise Protocol27GraphError("accepted synthesis artifacts must be a mapping")
        accepted = dict(sorted(accepted_node_hashes.items()))
        by_id = {item.node_id: item for item in self.required_nodes}
        if not set(accepted).issubset(by_id):
            raise Protocol27GraphError("accepted synthesis artifact names an unknown node")
        for node_id, artifact_hash in accepted.items():
            _schema(digest_value, node_id, "accepted synthesis node ID")
            _schema(digest_value, artifact_hash, "accepted synthesis artifact hash")
            if not set(by_id[node_id].generated_dependency_node_ids).issubset(accepted):
                raise Protocol27GraphError(
                    "accepted synthesis artifacts are not dependency closed"
                )
        return MappingProxyType(accepted)

    def _work_item(
        self,
        node: SynthesisGraphNodeV1,
        accepted: Mapping[str, str],
    ) -> SynthesisWorkItemV1:
        template = next(item for item in self.templates if item.template_id == node.template_id)
        dependencies = list(node.fixed_artifact_dependencies)
        for dependency_node_id in node.generated_dependency_node_ids:
            dependency_node = next(
                item for item in self.required_nodes if item.node_id == dependency_node_id
            )
            dependency_key = self._artifact_key(dependency_node, accepted)
            dependencies.append(
                SynthesisArtifactDependencyV1(
                    dependency_key.artifact_key_id,
                    accepted[dependency_node_id],
                )
            )
        ordered = tuple(sorted(dependencies, key=lambda item: item.identity))
        key = SynthesisArtifactKeyV1(
            identity_schema_version=1,
            scope=node.scope,
            artifact_kind=node.artifact_kind,
            producer_protocol_version="2.7",
            synthesis_policy_hash=self.policy_catalog.identity,
            response_schema_hash=self.response_schema_hashes[node.artifact_kind],
            context_policy_hash=self.context_policy_hash,
            artifact_dependencies=ordered,
            non_artifact_dependency_hashes=node.non_artifact_dependency_hashes,
            debt_manifest_hashes=node.debt_manifest_hashes,
        )
        return SynthesisWorkItemV1(
            schema_version=1,
            template_id=template.template_id,
            output_key=key,
            dependency_key_ids=tuple(
                sorted(item.artifact_key_id for item in ordered)
            ),
            executor_contract_hash=template.executor_contract_hash,
            verifier_id=template.verifier_id,
            verifier_version=template.verifier_version,
            verifier_authority_hash=template.verifier_authority_hash,
        )

    def _artifact_key(
        self,
        node: SynthesisGraphNodeV1,
        accepted: Mapping[str, str],
    ) -> SynthesisArtifactKeyV1:
        return self._work_item(node, accepted).output_key

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "topology": self.topology.to_json_dict(),
            "policy_catalog": self.policy_catalog.to_json_dict(),
            "response_schema_hashes": dict(self.response_schema_hashes),
            "context_policy_hash": self.context_policy_hash,
            "templates": [item.to_json_dict() for item in self.templates],
            "required_nodes": [item.to_json_dict() for item in self.required_nodes],
            "public_paths": dict(self.public_paths),
            "root_specification": self.root_specification.to_json_dict(),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisGraph":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        templates = raw["templates"]
        nodes = raw["required_nodes"]
        if not isinstance(templates, (list, tuple)) or not isinstance(nodes, (list, tuple)):
            raise Protocol27GraphError("synthesis graph templates/nodes must be arrays")
        return cls(
            schema_version=raw["schema_version"],
            topology=WorkspaceSynthesisTopologyV1.from_json_dict(raw["topology"]),
            policy_catalog=SynthesisPolicyCatalogV1.from_json_dict(raw["policy_catalog"]),
            response_schema_hashes=raw["response_schema_hashes"],
            context_policy_hash=raw["context_policy_hash"],
            templates=tuple(SynthesisWorkTemplateV1.from_json_dict(item) for item in templates),
            required_nodes=tuple(SynthesisGraphNodeV1.from_json_dict(item) for item in nodes),
            public_paths=raw["public_paths"],
            root_specification=SynthesisRootSpecificationV1.from_json_dict(
                raw["root_specification"]
            ),
        )


def build_synthesis_graph(inputs: SynthesisGraphInputsV1) -> SynthesisGraph:
    if not isinstance(inputs, SynthesisGraphInputsV1):
        raise Protocol27GraphError("synthesis graph requires validated graph inputs")
    templates = tuple(
        _template(inputs, kind) for kind in sorted(SYNTHESIS_GENERATED_KINDS)
    )
    template_by_kind = {item.artifact_kind: item for item in templates}
    sources = {item.source_id: item for item in inputs.accepted_sources}
    overviews = {item.source_id: item for item in inputs.source_overviews.projections}
    source_topology = {item.source_id: item for item in inputs.topology.sources}
    nodes: list[SynthesisGraphNodeV1] = []
    source_nodes: dict[tuple[str, str], SynthesisGraphNodeV1] = {}
    public_paths: dict[str, str] = {
        projection.identity: f"re/sources/{projection.source_id}/overview.md"
        for projection in inputs.source_overviews.projections
    }
    for source_id in sorted(sources):
        source = sources[source_id]
        overview = overviews[source_id]
        fixed = (
            SynthesisArtifactDependencyV1(overview.identity, overview.object_hash),
        )
        debt = () if source.debt_manifest_hash is None else (source.debt_manifest_hash,)
        for kind, filename in (
            ("source-architecture", "architecture.md"),
            ("source-contracts", "contracts.md"),
            ("source-components", "components.md"),
        ):
            node = SynthesisGraphNodeV1(
                schema_version=1,
                scope=SynthesisScopeV1(1, "source", source_id, None, (source_id,)),
                artifact_kind=kind,
                template_id=template_by_kind[kind].template_id,
                generated_dependency_node_ids=(),
                fixed_artifact_dependencies=fixed,
                non_artifact_dependency_hashes=tuple(
                    sorted((source.identity, source_topology[source_id].identity))
                ),
                debt_manifest_hashes=debt,
                public_path=f"re/sources/{source_id}/{filename}",
            )
            source_nodes[(source_id, kind)] = node
            nodes.append(node)
            public_paths[node.node_id] = node.public_path
    domain_nodes: dict[str, SynthesisGraphNodeV1] = {}
    for domain in inputs.topology.workspace_domains:
        participant_source_ids = tuple(
            sorted({item.source_id for item in domain.participants})
        )
        dependency_ids = tuple(
            sorted(
                source_nodes[(source_id, kind)].node_id
                for source_id in participant_source_ids
                for kind in (
                    "source-architecture",
                    "source-components",
                    "source-contracts",
                )
            )
        )
        debts = tuple(
            sorted(
                source.debt_manifest_hash
                for source_id in participant_source_ids
                for source in (sources[source_id],)
                if source.debt_manifest_hash is not None
            )
        )
        node = SynthesisGraphNodeV1(
            schema_version=1,
            scope=SynthesisScopeV1(
                1,
                "workspace-domain",
                None,
                domain.workspace_domain_id,
                tuple(item.identity for item in domain.participants),
            ),
            artifact_kind="workspace-domain-summary",
            template_id=template_by_kind["workspace-domain-summary"].template_id,
            generated_dependency_node_ids=dependency_ids,
            fixed_artifact_dependencies=(),
            non_artifact_dependency_hashes=(domain.identity,),
            debt_manifest_hashes=debts,
            public_path=(
                "re/workspace/domains/"
                + domain.workspace_domain_id.removeprefix("sha256:")
                + ".md"
            ),
        )
        domain_nodes[domain.workspace_domain_id] = node
        nodes.append(node)
        public_paths[node.node_id] = node.public_path

    workspace_participants = tuple(sorted(sources))
    all_debts = tuple(
        sorted(
            source.debt_manifest_hash
            for source in sources.values()
            if source.debt_manifest_hash is not None
        )
    )
    domain_dependency_ids = tuple(
        sorted(item.node_id for item in domain_nodes.values())
    )
    workspace_specs = (
        (
            "workspace-overview",
            tuple(
                sorted(
                    (
                        *domain_dependency_ids,
                        *(
                            source_nodes[(source_id, kind)].node_id
                            for source_id in sorted(sources)
                            for kind in ("source-architecture", "source-components")
                        ),
                    )
                )
            ),
            tuple(
                sorted(
                    (
                        SynthesisArtifactDependencyV1(item.identity, item.object_hash)
                        for item in inputs.source_overviews.projections
                    ),
                    key=lambda item: item.identity,
                )
            ),
            "overview.md",
        ),
        (
            "workspace-relationships",
            tuple(
                sorted(
                    (
                        *domain_dependency_ids,
                        *(
                            source_nodes[(source_id, kind)].node_id
                            for source_id in sorted(sources)
                            for kind in ("source-architecture", "source-contracts")
                        ),
                    )
                )
            ),
            (),
            "relationships.md",
        ),
    )
    workspace_nodes: dict[str, SynthesisGraphNodeV1] = {}
    for kind, dependencies, fixed, filename in workspace_specs:
        node = SynthesisGraphNodeV1(
            1,
            SynthesisScopeV1(1, "workspace", None, None, workspace_participants),
            kind,
            template_by_kind[kind].template_id,
            dependencies,
            fixed,
            tuple(
                sorted(
                    (
                        inputs.topology.identity,
                        *(item.identity for item in inputs.accepted_sources),
                    )
                )
            ),
            all_debts,
            f"re/workspace/{filename}",
        )
        workspace_nodes[kind] = node
        nodes.append(node)
        public_paths[node.node_id] = node.public_path
    contracts = SynthesisGraphNodeV1(
        1,
        SynthesisScopeV1(1, "workspace", None, None, workspace_participants),
        "workspace-contracts",
        template_by_kind["workspace-contracts"].template_id,
        tuple(
            sorted(
                (
                    workspace_nodes["workspace-relationships"].node_id,
                    *(
                        source_nodes[(source_id, "source-contracts")].node_id
                        for source_id in sorted(sources)
                    ),
                )
            )
        ),
        (),
        tuple(
            sorted(
                (
                    inputs.topology.identity,
                    *(item.identity for item in inputs.accepted_sources),
                )
            )
        ),
        all_debts,
        "re/workspace/contracts.md",
    )
    nodes.append(contracts)
    public_paths[contracts.node_id] = contracts.public_path
    ordered_nodes = tuple(sorted(nodes, key=lambda item: item.node_id))
    root = SynthesisRootSpecificationV1(
        1,
        tuple(sorted(item.identity for item in inputs.accepted_sources)),
        tuple(item.node_id for item in ordered_nodes),
        all_debts,
        "partial" if all_debts else "complete",
    )
    return SynthesisGraph(
        1,
        inputs.topology,
        inputs.policy_catalog,
        inputs.response_schema_hashes,
        inputs.context_policy_hash,
        templates,
        ordered_nodes,
        public_paths,
        root,
    )


def _template(
    inputs: SynthesisGraphInputsV1,
    kind: str,
) -> SynthesisWorkTemplateV1:
    policy = inputs.policy_catalog.entry_for(kind)
    authority = inputs.policy_catalog.implementation_authority
    return SynthesisWorkTemplateV1(
        schema_version=1,
        artifact_kind=kind,
        scope_kind=policy.scope_kind,  # type: ignore[arg-type]
        producer_id=inputs.policy_catalog.producer_id,
        producer_protocol_version=inputs.policy_catalog.producer_protocol_version,
        producer_authority_hash=authority.producer_authority_hash,
        executor_contract_hash=authority.executor_contract_hash,
        verifier_id=inputs.policy_catalog.verifier_id,
        verifier_version=inputs.policy_catalog.verifier_version,
        verifier_authority_hash=authority.verifier_authority_hash,
        synthesis_policy_hash=inputs.policy_catalog.identity,
        response_schema_hash=inputs.response_schema_hashes[kind],
        context_policy_hash=inputs.context_policy_hash,
        required_artifact_kinds=policy.required_artifact_kinds,
        max_provider_attempts=policy.max_provider_attempts,
        max_generation_attempts=policy.max_generation_attempts,
        max_result_contract_retries=policy.max_result_contract_retries,
        max_artifact_contract_retries=policy.max_artifact_contract_retries,
    )


def _validate_acyclic(by_id: Mapping[str, SynthesisGraphNodeV1]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise Protocol27GraphError("synthesis graph contains a cycle")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id].generated_dependency_node_ids:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in sorted(by_id):
        visit(node_id)


def _validate_templates(
    templates: Mapping[str, SynthesisWorkTemplateV1],
    catalog: SynthesisPolicyCatalogV1,
    schemas: Mapping[str, str],
    context_policy_hash: str,
) -> None:
    authority = catalog.implementation_authority
    for kind, template in templates.items():
        policy = catalog.entry_for(kind)
        observed = (
            template.scope_kind,
            template.producer_id,
            template.producer_protocol_version,
            template.producer_authority_hash,
            template.executor_contract_hash,
            template.verifier_id,
            template.verifier_version,
            template.verifier_authority_hash,
            template.synthesis_policy_hash,
            template.response_schema_hash,
            template.context_policy_hash,
            template.required_artifact_kinds,
            template.max_provider_attempts,
            template.max_generation_attempts,
            template.max_result_contract_retries,
            template.max_artifact_contract_retries,
        )
        expected = (
            policy.scope_kind,
            catalog.producer_id,
            catalog.producer_protocol_version,
            authority.producer_authority_hash,
            authority.executor_contract_hash,
            catalog.verifier_id,
            catalog.verifier_version,
            authority.verifier_authority_hash,
            catalog.identity,
            schemas[kind],
            context_policy_hash,
            policy.required_artifact_kinds,
            policy.max_provider_attempts,
            policy.max_generation_attempts,
            policy.max_result_contract_retries,
            policy.max_artifact_contract_retries,
        )
        if observed != expected:
            raise Protocol27GraphError(
                f"synthesis template differs from closed policy: {kind}"
            )


def _validate_graph_shape(
    topology: WorkspaceSynthesisTopologyV1,
    catalog: SynthesisPolicyCatalogV1,
    templates: Mapping[str, SynthesisWorkTemplateV1],
    by_id: Mapping[str, SynthesisGraphNodeV1],
) -> None:
    nodes = tuple(by_id.values())
    for source in topology.sources:
        observed = sorted(
            item.artifact_kind
            for item in nodes
            if item.scope.kind == "source" and item.scope.source_id == source.source_id
        )
        if observed != [
            "source-architecture",
            "source-components",
            "source-contracts",
        ]:
            raise Protocol27GraphError(
                f"synthesis graph source shape is incomplete: {source.source_id}"
            )
    known_sources = {item.source_id for item in topology.sources}
    if any(
        item.scope.kind == "source" and item.scope.source_id not in known_sources
        for item in nodes
    ):
        raise Protocol27GraphError("synthesis graph contains an unknown source scope")
    for domain in topology.workspace_domains:
        matching = [
            item
            for item in nodes
            if item.scope.kind == "workspace-domain"
            and item.scope.workspace_domain_id == domain.workspace_domain_id
        ]
        if len(matching) != 1 or matching[0].artifact_kind != "workspace-domain-summary":
            raise Protocol27GraphError(
                "synthesis graph workspace-domain shape is incomplete"
            )
    workspace_kinds = sorted(
        item.artifact_kind for item in nodes if item.scope.kind == "workspace"
    )
    if workspace_kinds != [
        "workspace-contracts",
        "workspace-overview",
        "workspace-relationships",
    ]:
        raise Protocol27GraphError("synthesis graph workspace shape is incomplete")
    for node in nodes:
        template = templates[node.artifact_kind]
        if node.template_id != template.template_id or node.scope.kind != template.scope_kind:
            raise Protocol27GraphError(
                f"synthesis node differs from its template: {node.artifact_kind}"
            )
        generated_kinds = {
            by_id[dependency].artifact_kind
            for dependency in node.generated_dependency_node_ids
        }
        fixed_kinds = (
            {"source-overview-projection"}
            if node.fixed_artifact_dependencies
            else set()
        )
        expected_kinds = set(catalog.entry_for(node.artifact_kind).required_artifact_kinds)
        if not topology.workspace_domains:
            expected_kinds.discard("workspace-domain-summary")
        if generated_kinds | fixed_kinds != expected_kinds:
            raise Protocol27GraphError(
                f"synthesis node dependency kinds are incomplete: {node.artifact_kind}"
            )
        if node.fixed_artifact_dependencies and node.artifact_kind not in {
            "source-architecture",
            "source-contracts",
            "source-components",
            "workspace-overview",
        }:
            raise Protocol27GraphError(
                f"synthesis node has forbidden fixed dependencies: {node.artifact_kind}"
            )


__all__ = (
    "Protocol27GraphError",
    "SynthesisGraph",
    "SynthesisGraphInputsV1",
    "SynthesisGraphNodeV1",
    "SynthesisRootSpecificationV1",
    "SynthesisSourceTopologyV1",
    "WorkspaceDomainParticipantV1",
    "WorkspaceDomainV1",
    "WorkspaceSynthesisTopologyV1",
    "build_synthesis_graph",
    "build_workspace_synthesis_topology",
)
