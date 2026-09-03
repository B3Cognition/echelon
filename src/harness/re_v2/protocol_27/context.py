"""Bounded authenticated context construction for protocol-2.7 synthesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import ClassVar

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    one_of,
    safe_id,
)

from .model import AcceptedSourceOutcomeV1, SynthesisScopeV1, SynthesisWorkItemV1
from .schemas import required_section_ids


_AUTHORITY_ROLES = frozenset(
    {
        "debt-manifest",
        "source-outcome",
        "source-topology",
        "workspace-domain",
        "workspace-topology",
    }
)
MAX_SYNTHESIS_CONTEXT_BYTES = 262_144
MAX_SYNTHESIS_EXCERPT_BYTES = 16_384
MAX_SYNTHESIS_CONTEXT_OBJECTS = 128


class Protocol27ContextError(RuntimeError):
    """Raised when one synthesis context exceeds or escapes its authority."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27ContextError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27ContextError(str(exc)) from exc


def _safe_ids(value: object, field: str, *, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27ContextError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if (nonempty and not result) or result != tuple(sorted(set(result))):
        raise Protocol27ContextError(f"{field} must be sorted and unique")
    return result


def _ordered_safe_ids(
    value: object,
    field: str,
    *,
    nonempty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27ContextError(f"{field} must be an array")
    result = tuple(_schema(safe_id, item, field) for item in value)
    if (nonempty and not result) or len(result) != len(set(result)):
        raise Protocol27ContextError(f"{field} must be ordered and unique")
    return result


def _digests(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27ContextError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol27ContextError(f"{field} must be sorted and unique")
    return result


def _bounded_text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise Protocol27ContextError(f"{field} must be text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise Protocol27ContextError(f"{field} must be UTF-8") from exc
    if len(encoded) > limit:
        raise Protocol27ContextError(f"{field} exceeds its byte ceiling")
    return value


@dataclass(frozen=True, slots=True)
class SynthesisContextPolicyV1:
    schema_version: int
    max_canonical_json_bytes: int
    max_object_excerpt_bytes: int
    max_objects: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "max_canonical_json_bytes",
        "max_object_excerpt_bytes",
        "max_objects",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis context policy schema")
        for field in self.FIELDS[1:]:
            value = getattr(self, field)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise Protocol27ContextError(f"{field} must be a positive integer")
        if self.max_object_excerpt_bytes > self.max_canonical_json_bytes:
            raise Protocol27ContextError("object excerpt ceiling exceeds context ceiling")
        if (
            self.max_canonical_json_bytes > MAX_SYNTHESIS_CONTEXT_BYTES
            or self.max_object_excerpt_bytes > MAX_SYNTHESIS_EXCERPT_BYTES
            or self.max_objects > MAX_SYNTHESIS_CONTEXT_OBJECTS
        ):
            raise Protocol27ContextError("synthesis context policy exceeds protocol limits")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in self.FIELDS}

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisContextPolicyV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


def default_synthesis_context_policy() -> SynthesisContextPolicyV1:
    return SynthesisContextPolicyV1(
        schema_version=1,
        max_canonical_json_bytes=MAX_SYNTHESIS_CONTEXT_BYTES,
        max_object_excerpt_bytes=MAX_SYNTHESIS_EXCERPT_BYTES,
        max_objects=MAX_SYNTHESIS_CONTEXT_OBJECTS,
    )


@dataclass(frozen=True, slots=True)
class SynthesisAuthorizedObjectV1:
    object_hash: str
    role: str
    source_ids: tuple[str, ...]
    excerpt: str
    truncated: bool

    FIELDS: ClassVar[tuple[str, ...]] = (
        "object_hash",
        "role",
        "source_ids",
        "excerpt",
        "truncated",
    )

    def __post_init__(self) -> None:
        _schema(digest_value, self.object_hash, "authorized object hash")
        _schema(one_of, self.role, _AUTHORITY_ROLES, "authorized object role")
        object.__setattr__(
            self,
            "source_ids",
            _safe_ids(self.source_ids, "authorized object sources"),
        )
        _bounded_text(
            self.excerpt,
            "authorized object excerpt",
            MAX_SYNTHESIS_EXCERPT_BYTES,
        )
        if not isinstance(self.truncated, bool):
            raise Protocol27ContextError("authorized object truncated flag is invalid")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "object_hash": self.object_hash,
            "role": self.role,
            "source_ids": list(self.source_ids),
            "excerpt": self.excerpt,
            "truncated": self.truncated,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisAuthorizedObjectV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisDependencyArtifactV1:
    artifact_key_id: str
    artifact_hash: str
    source_ids: tuple[str, ...]
    excerpt: str
    truncated: bool

    FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_key_id",
        "artifact_hash",
        "source_ids",
        "excerpt",
        "truncated",
    )

    def __post_init__(self) -> None:
        _schema(digest_value, self.artifact_key_id, "dependency artifact key")
        _schema(digest_value, self.artifact_hash, "dependency artifact hash")
        object.__setattr__(
            self,
            "source_ids",
            _safe_ids(self.source_ids, "dependency artifact sources", nonempty=True),
        )
        _bounded_text(
            self.excerpt,
            "dependency artifact excerpt",
            MAX_SYNTHESIS_EXCERPT_BYTES,
        )
        if not isinstance(self.truncated, bool):
            raise Protocol27ContextError("dependency artifact truncated flag is invalid")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "artifact_key_id": self.artifact_key_id,
            "artifact_hash": self.artifact_hash,
            "source_ids": list(self.source_ids),
            "excerpt": self.excerpt,
            "truncated": self.truncated,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisDependencyArtifactV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(**{field: raw[field] for field in cls.FIELDS})


@dataclass(frozen=True, slots=True)
class SynthesisPublicContractV1:
    public_path: str
    required_section_ids: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = ("public_path", "required_section_ids")

    def __post_init__(self) -> None:
        path = PurePosixPath(self.public_path)
        if (
            path.is_absolute()
            or path.as_posix() != self.public_path
            or not self.public_path.startswith("re/")
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise Protocol27ContextError("synthesis public contract path is unsafe")
        sections = _ordered_safe_ids(
            self.required_section_ids,
            "synthesis public contract sections",
            nonempty=True,
        )
        object.__setattr__(self, "required_section_ids", sections)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "public_path": self.public_path,
            "required_section_ids": list(self.required_section_ids),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisPublicContractV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        return cls(raw["public_path"], tuple(raw["required_section_ids"]))


@dataclass(frozen=True, slots=True)
class SynthesisContextV1:
    schema_version: int
    work_item_id: str
    artifact_key_id: str
    artifact_kind: str
    scope: SynthesisScopeV1
    source_ids: tuple[str, ...]
    authorized_objects: tuple[SynthesisAuthorizedObjectV1, ...]
    dependency_artifacts: tuple[SynthesisDependencyArtifactV1, ...]
    source_outcomes: tuple[AcceptedSourceOutcomeV1, ...]
    debt_refs: tuple[str, ...]
    input_quality: str
    public_contract: SynthesisPublicContractV1
    response_schema_hash: str
    context_policy_hash: str
    max_canonical_json_bytes: int

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "work_item_id",
        "artifact_key_id",
        "artifact_kind",
        "scope",
        "source_ids",
        "authorized_objects",
        "dependency_artifacts",
        "source_outcomes",
        "debt_refs",
        "input_quality",
        "public_contract",
        "response_schema_hash",
        "context_policy_hash",
        "max_canonical_json_bytes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "synthesis context schema")
        for field in (
            "work_item_id",
            "artifact_key_id",
            "response_schema_hash",
            "context_policy_hash",
        ):
            _schema(digest_value, getattr(self, field), f"synthesis context {field}")
        _schema(safe_id, self.artifact_kind, "synthesis context artifact kind")
        if not isinstance(self.scope, SynthesisScopeV1):
            raise Protocol27ContextError("synthesis context scope is invalid")
        sources = _safe_ids(self.source_ids, "synthesis context sources", nonempty=True)
        objects = tuple(self.authorized_objects)
        dependencies = tuple(self.dependency_artifacts)
        outcomes = tuple(self.source_outcomes)
        if any(not isinstance(item, SynthesisAuthorizedObjectV1) for item in objects):
            raise Protocol27ContextError("synthesis context authority objects are invalid")
        if any(not isinstance(item, SynthesisDependencyArtifactV1) for item in dependencies):
            raise Protocol27ContextError("synthesis context dependencies are invalid")
        if any(not isinstance(item, AcceptedSourceOutcomeV1) for item in outcomes):
            raise Protocol27ContextError("synthesis context source outcomes are invalid")
        if tuple(item.object_hash for item in objects) != tuple(
            sorted({item.object_hash for item in objects})
        ):
            raise Protocol27ContextError("authorized objects must be sorted and unique")
        if tuple(item.artifact_key_id for item in dependencies) != tuple(
            sorted({item.artifact_key_id for item in dependencies})
        ):
            raise Protocol27ContextError("dependency artifacts must be sorted and unique")
        if tuple(item.source_id for item in outcomes) != sources:
            raise Protocol27ContextError("source outcomes must exactly cover context sources")
        debts = _digests(self.debt_refs, "synthesis context debt references")
        expected_quality = "partial" if debts else "complete"
        if self.input_quality != expected_quality:
            raise Protocol27ContextError("synthesis context input quality disagrees with debt")
        if not isinstance(self.public_contract, SynthesisPublicContractV1):
            raise Protocol27ContextError("synthesis public contract is invalid")
        if (
            not isinstance(self.max_canonical_json_bytes, int)
            or isinstance(self.max_canonical_json_bytes, bool)
            or self.max_canonical_json_bytes <= 0
        ):
            raise Protocol27ContextError("synthesis context byte ceiling is invalid")
        object.__setattr__(self, "source_ids", sources)
        object.__setattr__(self, "authorized_objects", objects)
        object.__setattr__(self, "dependency_artifacts", dependencies)
        object.__setattr__(self, "source_outcomes", outcomes)
        object.__setattr__(self, "debt_refs", debts)
        if len(canonical_json_bytes(self.to_json_dict())) > self.max_canonical_json_bytes:
            raise Protocol27ContextError("synthesis context exceeds its byte ceiling")

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "work_item_id": self.work_item_id,
            "artifact_key_id": self.artifact_key_id,
            "artifact_kind": self.artifact_kind,
            "scope": self.scope.to_json_dict(),
            "source_ids": list(self.source_ids),
            "authorized_objects": [item.to_json_dict() for item in self.authorized_objects],
            "dependency_artifacts": [
                item.to_json_dict() for item in self.dependency_artifacts
            ],
            "source_outcomes": [item.to_json_dict() for item in self.source_outcomes],
            "debt_refs": list(self.debt_refs),
            "input_quality": self.input_quality,
            "public_contract": self.public_contract.to_json_dict(),
            "response_schema_hash": self.response_schema_hash,
            "context_policy_hash": self.context_policy_hash,
            "max_canonical_json_bytes": self.max_canonical_json_bytes,
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "SynthesisContextV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        for field in (
            "source_ids",
            "authorized_objects",
            "dependency_artifacts",
            "source_outcomes",
            "debt_refs",
        ):
            if not isinstance(raw[field], (list, tuple)):
                raise Protocol27ContextError(f"{field} must be an array")
        return cls(
            schema_version=raw["schema_version"],
            work_item_id=raw["work_item_id"],
            artifact_key_id=raw["artifact_key_id"],
            artifact_kind=raw["artifact_kind"],
            scope=SynthesisScopeV1.from_json_dict(raw["scope"]),
            source_ids=tuple(raw["source_ids"]),
            authorized_objects=tuple(
                SynthesisAuthorizedObjectV1.from_json_dict(item)
                for item in raw["authorized_objects"]
            ),
            dependency_artifacts=tuple(
                SynthesisDependencyArtifactV1.from_json_dict(item)
                for item in raw["dependency_artifacts"]
            ),
            source_outcomes=tuple(
                AcceptedSourceOutcomeV1.from_json_dict(item)
                for item in raw["source_outcomes"]
            ),
            debt_refs=tuple(raw["debt_refs"]),
            input_quality=raw["input_quality"],
            public_contract=SynthesisPublicContractV1.from_json_dict(
                raw["public_contract"]
            ),
            response_schema_hash=raw["response_schema_hash"],
            context_policy_hash=raw["context_policy_hash"],
            max_canonical_json_bytes=raw["max_canonical_json_bytes"],
        )


def build_synthesis_context(
    inputs,  # ValidatedProtocol27Inputs; kept lazy to avoid an inputs/context cycle.
    work_item: SynthesisWorkItemV1,
    *,
    policy: SynthesisContextPolicyV1 | None = None,
) -> SynthesisContextV1:
    from .inputs import ValidatedProtocol27Inputs

    if not isinstance(inputs, ValidatedProtocol27Inputs):
        raise Protocol27ContextError("synthesis context requires validated child inputs")
    if not isinstance(work_item, SynthesisWorkItemV1):
        raise Protocol27ContextError("synthesis context requires a synthesis work item")
    selected_policy = policy or _load_context_policy(inputs)
    if selected_policy.identity != work_item.output_key.context_policy_hash:
        raise Protocol27ContextError("synthesis context policy authority mismatch")
    node = inputs.graph.node_for_work_item(work_item)
    _validate_work_item_shape(inputs, work_item, node)
    source_ids = _source_ids_for_scope(inputs, work_item.output_key.scope)
    store = ObjectStore(inputs.paths.objects)
    overview_sources = {
        item.identity: item.source_id
        for item in inputs.source_overview_catalog.projections
    }
    dependencies = []
    for dependency in work_item.output_key.artifact_dependencies:
        payload = _read_authority_object(store, dependency.artifact_hash)
        excerpt, truncated = _excerpt(
            payload,
            selected_policy.max_object_excerpt_bytes,
        )
        dependency_sources = (
            (overview_sources[dependency.artifact_key_id],)
            if dependency.artifact_key_id in overview_sources
            else source_ids
        )
        dependencies.append(
            SynthesisDependencyArtifactV1(
                dependency.artifact_key_id,
                dependency.artifact_hash,
                dependency_sources,
                excerpt,
                truncated,
            )
        )
    outcomes_by_id = {
        item.source_id: item for item in inputs.parent_authority.accepted_sources
    }
    outcomes = tuple(outcomes_by_id[source_id] for source_id in source_ids)
    authorized = []
    for object_hash in work_item.output_key.non_artifact_dependency_hashes:
        role, object_sources = _classify_non_artifact(inputs, object_hash, source_ids)
        payload = _read_authority_object(store, object_hash)
        excerpt, truncated = _excerpt(
            payload,
            selected_policy.max_object_excerpt_bytes,
        )
        authorized.append(
            SynthesisAuthorizedObjectV1(
                object_hash,
                role,
                object_sources,
                excerpt,
                truncated,
            )
        )
    for debt_hash in work_item.output_key.debt_manifest_hashes:
        payload = _read_authority_object(store, debt_hash)
        debt_sources = tuple(
            item.source_id for item in outcomes if item.debt_manifest_hash == debt_hash
        )
        if not debt_sources:
            raise Protocol27ContextError("debt authority is outside context sources")
        excerpt, truncated = _excerpt(
            payload,
            selected_policy.max_object_excerpt_bytes,
        )
        authorized.append(
            SynthesisAuthorizedObjectV1(
                debt_hash,
                "debt-manifest",
                debt_sources,
                excerpt,
                truncated,
            )
        )
    authorized = sorted(authorized, key=lambda item: item.object_hash)
    if len(authorized) + len(dependencies) > selected_policy.max_objects:
        raise Protocol27ContextError("synthesis context exceeds its object ceiling")
    contract = SynthesisPublicContractV1(
        public_path=node.public_path,
        required_section_ids=required_section_ids(node.artifact_kind),
    )
    return SynthesisContextV1(
        schema_version=1,
        work_item_id=work_item.work_item_id,
        artifact_key_id=work_item.output_key.artifact_key_id,
        artifact_kind=work_item.output_key.artifact_kind,
        scope=work_item.output_key.scope,
        source_ids=source_ids,
        authorized_objects=tuple(authorized),
        dependency_artifacts=tuple(
            sorted(dependencies, key=lambda item: item.artifact_key_id)
        ),
        source_outcomes=outcomes,
        debt_refs=work_item.output_key.debt_manifest_hashes,
        input_quality="partial" if work_item.output_key.debt_manifest_hashes else "complete",
        public_contract=contract,
        response_schema_hash=work_item.output_key.response_schema_hash,
        context_policy_hash=work_item.output_key.context_policy_hash,
        max_canonical_json_bytes=selected_policy.max_canonical_json_bytes,
    )


def _load_context_policy(inputs) -> SynthesisContextPolicyV1:  # type: ignore[no-untyped-def]
    hashes = inputs.input_authority_catalog.hashes_for("context-policy")
    if len(hashes) != 1:
        raise Protocol27ContextError("synthesis context policy authority is not unique")
    store = ObjectStore(inputs.paths.objects)
    payload = _read_authority_object(store, hashes[0])
    try:
        import json

        raw = json.loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise Protocol27ContextError("synthesis context policy is not JSON") from exc
    policy = SynthesisContextPolicyV1.from_json_dict(raw)
    if canonical_json_bytes(policy.to_json_dict()) != payload:
        raise Protocol27ContextError("synthesis context policy is not canonical")
    return policy


def _validate_work_item_shape(inputs, work_item, node) -> None:  # type: ignore[no-untyped-def]
    key = work_item.output_key
    template = next(
        (item for item in inputs.graph.templates if item.template_id == node.template_id),
        None,
    )
    if template is None or (
        work_item.template_id != template.template_id
        or work_item.executor_contract_hash != template.executor_contract_hash
        or work_item.verifier_id != template.verifier_id
        or work_item.verifier_version != template.verifier_version
        or work_item.verifier_authority_hash != template.verifier_authority_hash
        or key.scope != node.scope
        or key.artifact_kind != node.artifact_kind
        or key.synthesis_policy_hash != inputs.graph.policy_catalog.identity
        or key.response_schema_hash
        != inputs.graph.response_schema_hashes[node.artifact_kind]
        or key.context_policy_hash != inputs.graph.context_policy_hash
        or key.non_artifact_dependency_hashes
        != node.non_artifact_dependency_hashes
        or key.debt_manifest_hashes != node.debt_manifest_hashes
    ):
        raise Protocol27ContextError("synthesis work item differs from graph authority")
    dependencies = {
        item.artifact_key_id: item.artifact_hash
        for item in key.artifact_dependencies
    }
    fixed = {
        item.artifact_key_id: item.artifact_hash
        for item in node.fixed_artifact_dependencies
    }
    if (
        not set(fixed).issubset(dependencies)
        or any(dependencies[item] != value for item, value in fixed.items())
        or len(dependencies)
        != len(fixed) + len(node.generated_dependency_node_ids)
    ):
        raise Protocol27ContextError(
            "synthesis work item dependency shape differs from graph authority"
        )


def _source_ids_for_scope(inputs, scope: SynthesisScopeV1) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    if scope.kind == "source":
        assert scope.source_id is not None
        return (scope.source_id,)
    if scope.kind == "workspace":
        return tuple(scope.participant_ids)
    matches = [
        domain
        for domain in inputs.graph.topology.workspace_domains
        if domain.workspace_domain_id == scope.workspace_domain_id
    ]
    if len(matches) != 1:
        raise Protocol27ContextError("workspace-domain scope is not in topology")
    return tuple(sorted({item.source_id for item in matches[0].participants}))


def _classify_non_artifact(
    inputs,  # type: ignore[no-untyped-def]
    object_hash: str,
    source_ids: tuple[str, ...],
) -> tuple[str, tuple[str, ...]]:
    for outcome in inputs.parent_authority.accepted_sources:
        if outcome.identity == object_hash and outcome.source_id in source_ids:
            return "source-outcome", (outcome.source_id,)
    if inputs.graph.topology.identity == object_hash:
        return "workspace-topology", source_ids
    for source in inputs.graph.topology.sources:
        if source.identity == object_hash and source.source_id in source_ids:
            return "source-topology", (source.source_id,)
    for domain in inputs.graph.topology.workspace_domains:
        if domain.identity == object_hash:
            participants = tuple(sorted({item.source_id for item in domain.participants}))
            if set(participants).issubset(source_ids):
                return "workspace-domain", participants
    raise Protocol27ContextError(f"authority object is outside work item: {object_hash}")


def _read_authority_object(store: ObjectStore, object_hash: str) -> bytes:
    try:
        return store.read_blob(object_hash)
    except Exception as exc:
        raise Protocol27ContextError(
            f"authority object is unavailable: {object_hash}"
        ) from exc


def _excerpt(payload: bytes, limit: int) -> tuple[str, bool]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return "", True
    if "\x00" in text:
        return "", True
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    shortened = encoded[:limit]
    while shortened:
        try:
            return shortened.decode("utf-8"), True
        except UnicodeDecodeError as exc:
            shortened = shortened[: exc.start]
    return "", True


__all__ = (
    "MAX_SYNTHESIS_CONTEXT_BYTES",
    "MAX_SYNTHESIS_CONTEXT_OBJECTS",
    "MAX_SYNTHESIS_EXCERPT_BYTES",
    "Protocol27ContextError",
    "SynthesisAuthorizedObjectV1",
    "SynthesisContextPolicyV1",
    "SynthesisContextV1",
    "SynthesisDependencyArtifactV1",
    "SynthesisPublicContractV1",
    "build_synthesis_context",
    "default_synthesis_context_policy",
)
