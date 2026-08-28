"""Self-contained, manifest-last protocol-2.7 input publication."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Callable, ClassVar, Mapping

from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.ledger import ObjectStore, ReV2LedgerError, TREE_OBJECT_MAGIC
from harness.re_v2.protocol_22.schema import (
    Protocol22SchemaError,
    digest_value,
    exact_object,
    literal,
    load_canonical_object,
    safe_id,
    utc_timestamp,
)
from harness.re_v2.run_store import (
    ReV2Paths,
    ReV2RunStoreError,
    load_run_manifest,
    staged_v2_run_store,
)

from .authority import ResolvedSynthesisParentV1
from .graph import (
    SynthesisGraph,
    SynthesisGraphNodeV1,
    SynthesisRootSpecificationV1,
    WorkspaceSynthesisTopologyV1,
)
from .model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    PartialSourceAcceptanceV1,
    RunManifestV6,
    SynthesisBudgetPolicyV1,
    SynthesisRequestV1,
    SynthesisWorkTemplateV1,
)
from .policies import SynthesisPolicyCatalogV1


FaultHook = Callable[[str], None]

_INPUT_ROLES = frozenset(
    {
        "accepted-source-outcome",
        "budget-policy",
        "checkpoint-selection",
        "context-policy",
        "graph-node",
        "implementation-authority",
        "partial-acceptance",
        "prosaic-authority",
        "response-schema",
        "root-specification",
        "source-authority",
        "source-overview-catalog",
        "source-overview-markdown",
        "source-overview-projection",
        "synthesis-graph",
        "synthesis-policy",
        "synthesis-request",
        "synthesis-topology",
        "work-template",
    }
)


class Protocol27InputStoreError(RuntimeError):
    """Raised when schema-6 input authority is incomplete or unsafe."""


def _schema(function, *args):  # type: ignore[no-untyped-def]
    try:
        return function(*args)
    except Protocol27InputStoreError:
        raise
    except (Protocol22SchemaError, TypeError, ValueError) as exc:
        raise Protocol27InputStoreError(str(exc)) from exc


def _digest_tuple(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise Protocol27InputStoreError(f"{field} must be an array")
    result = tuple(_schema(digest_value, item, field) for item in value)
    if result != tuple(sorted(set(result))):
        raise Protocol27InputStoreError(f"{field} must be sorted and unique")
    return result


@dataclass(frozen=True, slots=True)
class Protocol27InputAuthorityCatalogV1:
    schema_version: int
    object_hashes_by_role: Mapping[str, tuple[str, ...]]
    object_hashes: tuple[str, ...]

    FIELDS: ClassVar[tuple[str, ...]] = (
        "schema_version",
        "object_hashes_by_role",
        "object_hashes",
    )

    def __post_init__(self) -> None:
        _schema(literal, self.schema_version, 1, "input authority catalog schema")
        if not isinstance(self.object_hashes_by_role, Mapping):
            raise Protocol27InputStoreError("input authority roles must be a mapping")
        roles: dict[str, tuple[str, ...]] = {}
        for role, hashes in sorted(self.object_hashes_by_role.items()):
            _schema(safe_id, role, "input authority role")
            if role not in _INPUT_ROLES:
                raise Protocol27InputStoreError(
                    f"input authority role is not registered: {role}"
                )
            selected = _digest_tuple(hashes, f"input authority role {role}")
            if not selected:
                raise Protocol27InputStoreError(
                    f"input authority role must not be empty: {role}"
                )
            roles[role] = selected
        hashes = _digest_tuple(self.object_hashes, "input authority object hashes")
        flattened = tuple(sorted({item for values in roles.values() for item in values}))
        if hashes != flattened:
            raise Protocol27InputStoreError(
                "input authority object closure differs from role catalog"
            )
        object.__setattr__(self, "object_hashes_by_role", MappingProxyType(roles))
        object.__setattr__(self, "object_hashes", hashes)

    @property
    def identity(self) -> str:
        return content_digest(self.to_json_dict())

    def hashes_for(self, role: str) -> tuple[str, ...]:
        return self.object_hashes_by_role.get(role, ())

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "object_hashes_by_role": {
                role: list(hashes)
                for role, hashes in self.object_hashes_by_role.items()
            },
            "object_hashes": list(self.object_hashes),
        }

    @classmethod
    def from_json_dict(cls, value: object) -> "Protocol27InputAuthorityCatalogV1":
        raw = _schema(exact_object, value, frozenset(cls.FIELDS), cls.__name__)
        roles = raw["object_hashes_by_role"]
        if not isinstance(roles, Mapping):
            raise Protocol27InputStoreError("input authority roles must be an object")
        return cls(
            schema_version=raw["schema_version"],
            object_hashes_by_role={
                role: tuple(hashes) if isinstance(hashes, (list, tuple)) else hashes
                for role, hashes in roles.items()
            },
            object_hashes=raw["object_hashes"],
        )


@dataclass(frozen=True, slots=True)
class Protocol27InputSet:
    run_id: str
    created_at: str
    parent: ResolvedSynthesisParentV1
    request: SynthesisRequestV1
    partial_acceptances: tuple[PartialSourceAcceptanceV1, ...]
    source_overview_catalog: AcceptedSourceOverviewCatalogV1
    source_overview_bytes: Mapping[str, bytes]
    graph: SynthesisGraph
    prosaic_authority_bytes: bytes
    budget_policy: SynthesisBudgetPolicyV1
    checkpoint_selection_bytes: bytes
    authority_objects: Mapping[str, bytes]

    def __post_init__(self) -> None:
        _schema(safe_id, self.run_id, "protocol-2.7 run ID")
        _schema(utc_timestamp, self.created_at, "protocol-2.7 creation time")
        if not isinstance(self.parent, ResolvedSynthesisParentV1):
            raise Protocol27InputStoreError("protocol-2.7 parent authority is invalid")
        if not isinstance(self.request, SynthesisRequestV1):
            raise Protocol27InputStoreError("protocol-2.7 synthesis request is invalid")
        if self.request.parent_manifest_hash != self.parent.parent_manifest_hash:
            raise Protocol27InputStoreError("synthesis request parent authority mismatch")
        expected_outcomes = tuple(sorted(item.identity for item in self.parent.accepted_sources))
        if self.request.accepted_source_outcome_ids != expected_outcomes:
            raise Protocol27InputStoreError("synthesis request source outcomes mismatch")
        if not isinstance(self.partial_acceptances, (list, tuple)) or any(
            not isinstance(item, PartialSourceAcceptanceV1)
            for item in self.partial_acceptances
        ):
            raise Protocol27InputStoreError("partial acceptance receipts are invalid")
        partials = tuple(self.partial_acceptances)
        if tuple(item.source_id for item in partials) != self.request.accepted_partial_source_ids:
            raise Protocol27InputStoreError("partial acceptance receipt coverage mismatch")
        if any(item.operation_id != self.request.request_id for item in partials):
            raise Protocol27InputStoreError("partial acceptance operation mismatch")
        if not isinstance(self.source_overview_catalog, AcceptedSourceOverviewCatalogV1):
            raise Protocol27InputStoreError("source overview catalog is invalid")
        if not isinstance(self.graph, SynthesisGraph):
            raise Protocol27InputStoreError("synthesis graph is invalid")
        _validate_graph_overviews(self.graph, self.source_overview_catalog)
        overview_bytes = _validated_payload_mapping(
            self.source_overview_bytes,
            "source overview bytes",
        )
        if set(overview_bytes) != {
            item.object_hash for item in self.source_overview_catalog.projections
        }:
            raise Protocol27InputStoreError(
                "source overview byte closure differs from projection catalog"
            )
        if self.graph.topology.partition_manifest_id != self.parent.partition_manifest_id:
            raise Protocol27InputStoreError("synthesis graph partition authority mismatch")
        if self.graph.root_specification.accepted_source_outcome_ids != expected_outcomes:
            raise Protocol27InputStoreError("synthesis graph source authority mismatch")
        if not isinstance(self.budget_policy, SynthesisBudgetPolicyV1):
            raise Protocol27InputStoreError("synthesis budget policy is invalid")
        if self.request.budget_policy_hash != self.budget_policy.identity:
            raise Protocol27InputStoreError("synthesis request budget authority mismatch")
        prosaic = _canonical_object_bytes(
            self.prosaic_authority_bytes,
            "Prosaic authority",
        )
        checkpoint = _canonical_object_bytes(
            self.checkpoint_selection_bytes,
            "checkpoint selection",
        )
        authority = _validated_payload_mapping(
            self.authority_objects,
            "protocol-2.7 authority objects",
        )
        object.__setattr__(self, "partial_acceptances", partials)
        object.__setattr__(self, "source_overview_bytes", overview_bytes)
        object.__setattr__(self, "prosaic_authority_bytes", prosaic)
        object.__setattr__(self, "checkpoint_selection_bytes", checkpoint)
        object.__setattr__(self, "authority_objects", authority)
        _build_input_closure(self)


@dataclass(frozen=True, slots=True)
class ValidatedProtocol27Inputs:
    paths: ReV2Paths
    manifest: RunManifestV6
    request: SynthesisRequestV1
    parent_authority: ResolvedSynthesisParentV1
    input_authority_catalog: Protocol27InputAuthorityCatalogV1
    source_overview_catalog: AcceptedSourceOverviewCatalogV1
    source_overview_bytes: Mapping[str, bytes]
    graph: SynthesisGraph
    prosaic_authority_bytes: bytes
    checkpoint_selection_bytes: bytes
    object_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_overview_bytes",
            MappingProxyType(dict(sorted(self.source_overview_bytes.items()))),
        )


@dataclass(frozen=True, slots=True)
class PreparedProtocol27Creation:
    run_dir: Path
    manifest: RunManifestV6

    def __post_init__(self) -> None:
        if self.run_dir.name != self.manifest.run_id:
            raise Protocol27InputStoreError(
                "prepared protocol-2.7 run directory and manifest disagree"
            )


def create_protocol_27_run_store(
    run_dir: Path,
    inputs: Protocol27InputSet,
    *,
    fault_hook: FaultHook | None = None,
) -> RunManifestV6:
    """Publish one complete immutable input closure and manifest atomically."""
    if not isinstance(inputs, Protocol27InputSet):
        raise Protocol27InputStoreError(
            "protocol-2.7 creation requires Protocol27InputSet"
        )
    if Path(run_dir).name != inputs.run_id:
        raise Protocol27InputStoreError("run directory and protocol-2.7 run ID disagree")
    roles, payloads = _build_input_closure(inputs)
    catalog = Protocol27InputAuthorityCatalogV1(
        schema_version=1,
        object_hashes_by_role=roles,
        object_hashes=tuple(sorted(payloads)),
    )
    manifest = _manifest_for(inputs, catalog)
    try:
        with staged_v2_run_store(Path(run_dir)) as paths:
            paths.inputs.mkdir(mode=0o700)
            store = ObjectStore(paths.objects)
            _fault(fault_hook, "after_object_store")
            _write_roles(store, roles, payloads, ("source-authority",))
            _fault(fault_hook, "after_source_authority")
            _write_roles(
                store,
                roles,
                payloads,
                (
                    "source-overview-catalog",
                    "source-overview-markdown",
                    "source-overview-projection",
                ),
            )
            _fault(fault_hook, "after_overview_objects")
            _write_roles(
                store,
                roles,
                payloads,
                tuple(sorted(set(roles) - {
                    "source-authority",
                    "source-overview-catalog",
                    "source-overview-markdown",
                    "source-overview-projection",
                })),
            )
            catalog_payload = canonical_json_bytes(catalog.to_json_dict())
            if store.put_blob(catalog_payload) != catalog.identity:
                raise Protocol27InputStoreError("input authority catalog identity changed")
            _fault(fault_hook, "after_graph_authority")
            _validate_staged(store, catalog, payloads)
            _fault(fault_hook, "before_manifest_publish")
            _write_manifest(paths.manifest, canonical_json_bytes(manifest.to_json_dict()))
        _fault(fault_hook, "after_manifest_publish")
    except Protocol27InputStoreError:
        raise
    except (OSError, ReV2LedgerError, ReV2RunStoreError, ValueError) as exc:
        raise Protocol27InputStoreError(
            f"cannot publish protocol-2.7 input store: {exc}"
        ) from exc
    except RuntimeError:
        # Fault hooks deliberately raise through this boundary so crash tests can
        # assert the exact interrupted publication point.
        raise
    return manifest


def load_protocol_27_inputs(run_dir: Path) -> ValidatedProtocol27Inputs:
    """Load schema-6 authority using only its manifest and content objects."""
    try:
        manifest = load_run_manifest(Path(run_dir))
        if not isinstance(manifest, RunManifestV6):
            raise Protocol27InputStoreError(
                "protocol-2.7 loading requires a schema-6 manifest"
            )
        paths = ReV2Paths.for_run(Path(run_dir))
        store = ObjectStore(paths.objects)
        catalog = load_canonical_object(
            store.read_blob(manifest.input_authority_catalog_id),
            Protocol27InputAuthorityCatalogV1.from_json_dict,
        )
        payloads = {
            object_hash: store.read_blob(object_hash)
            for object_hash in catalog.object_hashes
        }
        request = _one_typed(
            catalog,
            payloads,
            "synthesis-request",
            SynthesisRequestV1.from_json_dict,
        )
        graph = _one_typed(
            catalog,
            payloads,
            "synthesis-graph",
            SynthesisGraph.from_json_dict,
        )
        overview_catalog = _one_typed(
            catalog,
            payloads,
            "source-overview-catalog",
            AcceptedSourceOverviewCatalogV1.from_json_dict,
        )
        outcomes = tuple(
            sorted(
                (
                    load_canonical_object(
                        payloads[object_hash], AcceptedSourceOutcomeV1.from_json_dict
                    )
                    for object_hash in catalog.hashes_for("accepted-source-outcome")
                ),
                key=lambda item: item.source_id,
            )
        )
        acceptances = tuple(
            sorted(
                (
                    load_canonical_object(
                        payloads[object_hash], PartialSourceAcceptanceV1.from_json_dict
                    )
                    for object_hash in catalog.hashes_for("partial-acceptance")
                ),
                key=lambda item: item.source_id,
            )
        )
        budget = _one_typed(
            catalog,
            payloads,
            "budget-policy",
            SynthesisBudgetPolicyV1.from_json_dict,
        )
        overview_bytes = {
            object_hash: payloads[object_hash]
            for object_hash in catalog.hashes_for("source-overview-markdown")
        }
        source_authority = {
            object_hash: payloads[object_hash]
            for object_hash in catalog.hashes_for("source-authority")
        }
        parent = ResolvedSynthesisParentV1(
            parent_run_id=manifest.parent_run_id,
            parent_manifest_hash=manifest.parent_manifest_hash,
            source_snapshot_id=manifest.source_snapshot_id,
            partition_manifest_id=manifest.partition_manifest_id,
            selected_layers={
                item.source_id: item.selected_layer
                for item in overview_catalog.projections
            },
            accepted_sources=outcomes,
            authority_objects=source_authority,
            debt_summary_hashes={
                item.source_id: item.debt_summary_hash for item in acceptances
            },
            _overview_catalog=overview_catalog,
            _overview_payloads=dict(overview_bytes),
            _overview_authorities={
                item.source_id: (item.source_root_key_id, item.content_hash)
                for item in overview_catalog.projections
            },
        )
        _validate_loaded(
            manifest,
            request,
            parent,
            catalog,
            graph,
            overview_catalog,
            overview_bytes,
            acceptances,
            budget,
            payloads,
        )
        prosaic_hash = _one_hash(catalog, "prosaic-authority")
        checkpoint_hash = _one_hash(catalog, "checkpoint-selection")
        prosaic_bytes = _canonical_object_bytes(
            payloads[prosaic_hash], "loaded Prosaic authority"
        )
        checkpoint_bytes = _canonical_object_bytes(
            payloads[checkpoint_hash], "loaded checkpoint selection"
        )
        return ValidatedProtocol27Inputs(
            paths=paths,
            manifest=manifest,
            request=request,
            parent_authority=parent,
            input_authority_catalog=catalog,
            source_overview_catalog=overview_catalog,
            source_overview_bytes=overview_bytes,
            graph=graph,
            prosaic_authority_bytes=prosaic_bytes,
            checkpoint_selection_bytes=checkpoint_bytes,
            object_hashes=catalog.object_hashes,
        )
    except Protocol27InputStoreError:
        raise
    except Exception as exc:
        raise Protocol27InputStoreError(
            f"cannot load protocol-2.7 input authority: {exc}"
        ) from exc


def prepare_protocol_27_child(
    workspace_root: Path,
    run_id: str,
    inputs: Protocol27InputSet,
    *,
    fault_hook: FaultHook | None = None,
) -> PreparedProtocol27Creation:
    """Atomically prepare one child without mutating the active-run pointer."""
    root = Path(workspace_root).resolve()
    if inputs.run_id != run_id:
        raise Protocol27InputStoreError("prepared child run ID differs from inputs")
    run_dir = root / "runs" / run_id
    manifest = create_protocol_27_run_store(
        run_dir,
        inputs,
        fault_hook=fault_hook,
    )
    return PreparedProtocol27Creation(run_dir, manifest)


def _build_input_closure(
    inputs: Protocol27InputSet,
) -> tuple[Mapping[str, tuple[str, ...]], Mapping[str, bytes]]:
    roles: dict[str, set[str]] = {}
    payloads: dict[str, bytes] = {}

    def add(role: str, object_hash: str, payload: bytes) -> None:
        if content_digest(payload) != object_hash:
            raise Protocol27InputStoreError(f"{role} object hash mismatch: {object_hash}")
        existing = payloads.get(object_hash)
        if existing is not None and existing != payload:
            raise Protocol27InputStoreError(f"conflicting input object: {object_hash}")
        payloads[object_hash] = payload
        roles.setdefault(role, set()).add(object_hash)

    source_authority_hashes = {
        value
        for source in inputs.parent.accepted_sources
        for value in (
            source.source_root_hash,
            source.debt_manifest_hash,
            *source.lower_authority_ids,
        )
        if value is not None
    }
    response_hashes = set(inputs.graph.response_schema_hashes.values())
    implementation = inputs.graph.policy_catalog.implementation_authority
    implementation_hashes = {
        implementation.producer_authority_hash,
        implementation.executor_contract_hash,
        implementation.verifier_authority_hash,
    }
    context_hashes = {inputs.graph.context_policy_hash}
    classified = (
        source_authority_hashes
        | response_hashes
        | implementation_hashes
        | context_hashes
    )
    if set(inputs.authority_objects) != classified:
        missing = sorted(classified - set(inputs.authority_objects))
        extra = sorted(set(inputs.authority_objects) - classified)
        raise Protocol27InputStoreError(
            "authority object closure mismatch"
            + (f"; missing {missing[0]}" if missing else "")
            + (f"; unreferenced {extra[0]}" if extra else "")
        )
    for object_hash in sorted(source_authority_hashes):
        add("source-authority", object_hash, inputs.authority_objects[object_hash])
    for object_hash in sorted(response_hashes):
        add("response-schema", object_hash, inputs.authority_objects[object_hash])
    for object_hash in sorted(implementation_hashes):
        add(
            "implementation-authority",
            object_hash,
            inputs.authority_objects[object_hash],
        )
    for object_hash in sorted(context_hashes):
        add("context-policy", object_hash, inputs.authority_objects[object_hash])
    for source in inputs.parent.accepted_sources:
        add(
            "accepted-source-outcome",
            source.identity,
            canonical_json_bytes(source.to_json_dict()),
        )
    for projection in inputs.source_overview_catalog.projections:
        add(
            "source-overview-projection",
            projection.identity,
            canonical_json_bytes(projection.to_json_dict()),
        )
        add(
            "source-overview-markdown",
            projection.object_hash,
            inputs.source_overview_bytes[projection.object_hash],
        )
    add(
        "source-overview-catalog",
        inputs.source_overview_catalog.identity,
        canonical_json_bytes(inputs.source_overview_catalog.to_json_dict()),
    )
    for receipt in inputs.partial_acceptances:
        add(
            "partial-acceptance",
            receipt.receipt_id,
            canonical_json_bytes(receipt.to_json_dict()),
        )
    add(
        "synthesis-request",
        inputs.request.request_id,
        canonical_json_bytes(inputs.request.to_json_dict()),
    )
    add(
        "budget-policy",
        inputs.budget_policy.identity,
        canonical_json_bytes(inputs.budget_policy.to_json_dict()),
    )
    add(
        "synthesis-topology",
        inputs.graph.topology.identity,
        canonical_json_bytes(inputs.graph.topology.to_json_dict()),
    )
    add(
        "synthesis-policy",
        inputs.graph.policy_catalog.identity,
        canonical_json_bytes(inputs.graph.policy_catalog.to_json_dict()),
    )
    for template in inputs.graph.templates:
        add("work-template", template.template_id, canonical_json_bytes(template.to_json_dict()))
    for node in inputs.graph.required_nodes:
        add("graph-node", node.node_id, canonical_json_bytes(node.to_json_dict()))
    add(
        "root-specification",
        inputs.graph.root_specification.identity,
        canonical_json_bytes(inputs.graph.root_specification.to_json_dict()),
    )
    add(
        "synthesis-graph",
        inputs.graph.graph_id,
        canonical_json_bytes(inputs.graph.to_json_dict()),
    )
    add(
        "prosaic-authority",
        content_digest(inputs.prosaic_authority_bytes),
        inputs.prosaic_authority_bytes,
    )
    add(
        "checkpoint-selection",
        content_digest(inputs.checkpoint_selection_bytes),
        inputs.checkpoint_selection_bytes,
    )
    frozen_roles = MappingProxyType(
        {role: tuple(sorted(values)) for role, values in sorted(roles.items())}
    )
    return frozen_roles, MappingProxyType(dict(sorted(payloads.items())))


def _manifest_for(
    inputs: Protocol27InputSet,
    catalog: Protocol27InputAuthorityCatalogV1,
) -> RunManifestV6:
    return RunManifestV6(
        schema_version=6,
        engine="re-v2",
        engine_protocol_version="2.7",
        goal="workspace-synthesis",
        run_id=inputs.run_id,
        created_at=inputs.created_at,
        request_id=inputs.request.request_id,
        parent_run_id=inputs.parent.parent_run_id,
        parent_manifest_hash=inputs.parent.parent_manifest_hash,
        source_snapshot_id=inputs.parent.source_snapshot_id,
        source_snapshot_kind="workspace-git-composite",
        partition_manifest_id=inputs.parent.partition_manifest_id,
        accepted_sources=inputs.parent.accepted_sources,
        source_overview_catalog_id=inputs.source_overview_catalog.identity,
        partial_acceptances=inputs.partial_acceptances,
        input_authority_catalog_id=catalog.identity,
        synthesis_graph_id=inputs.graph.graph_id,
        synthesis_policy_hash=inputs.graph.policy_catalog.identity,
        prosaic_authority_hash=content_digest(inputs.prosaic_authority_bytes),
        budget_policy=inputs.budget_policy,
        checkpoint_selection_id=content_digest(inputs.checkpoint_selection_bytes),
        expected_v2_index_hash=inputs.request.expected_v2_index_hash,
        expected_compatibility_generation=(
            inputs.request.expected_compatibility_generation
        ),
    )


def _validate_loaded(
    manifest: RunManifestV6,
    request: SynthesisRequestV1,
    parent: ResolvedSynthesisParentV1,
    catalog: Protocol27InputAuthorityCatalogV1,
    graph: SynthesisGraph,
    overview_catalog: AcceptedSourceOverviewCatalogV1,
    overview_bytes: Mapping[str, bytes],
    acceptances: tuple[PartialSourceAcceptanceV1, ...],
    budget: SynthesisBudgetPolicyV1,
    payloads: Mapping[str, bytes],
) -> None:
    if request.request_id != manifest.request_id:
        raise Protocol27InputStoreError("manifest synthesis request identity mismatch")
    if (
        request.parent_manifest_hash != manifest.parent_manifest_hash
        or request.accepted_source_outcome_ids
        != tuple(sorted(item.identity for item in manifest.accepted_sources))
        or request.accepted_partial_source_ids
        != tuple(item.source_id for item in manifest.partial_acceptances)
        or request.budget_policy_hash != manifest.budget_policy.identity
        or request.expected_v2_index_hash != manifest.expected_v2_index_hash
        or request.expected_compatibility_generation
        != manifest.expected_compatibility_generation
    ):
        raise Protocol27InputStoreError("manifest and synthesis request disagree")
    if parent.accepted_sources != manifest.accepted_sources:
        raise Protocol27InputStoreError("loaded parent source outcomes mismatch")
    if acceptances != manifest.partial_acceptances:
        raise Protocol27InputStoreError("loaded partial acceptance receipts mismatch")
    if budget != manifest.budget_policy:
        raise Protocol27InputStoreError("loaded synthesis budget mismatch")
    if overview_catalog.identity != manifest.source_overview_catalog_id:
        raise Protocol27InputStoreError("loaded overview catalog identity mismatch")
    for projection in overview_catalog.projections:
        payload = overview_bytes.get(projection.object_hash)
        if payload is None or content_digest(payload) != projection.content_hash:
            raise Protocol27InputStoreError(
                f"loaded source overview hash mismatch: {projection.source_id}"
            )
    if (
        graph.graph_id != manifest.synthesis_graph_id
        or graph.policy_catalog.identity != manifest.synthesis_policy_hash
        or graph.topology.partition_manifest_id != manifest.partition_manifest_id
    ):
        raise Protocol27InputStoreError("loaded synthesis graph authority mismatch")
    _expect_semantic_authority_roles(catalog, manifest, graph, overview_catalog)
    _expect_component_objects(catalog, payloads, graph)
    if _one_hash(catalog, "prosaic-authority") != manifest.prosaic_authority_hash:
        raise Protocol27InputStoreError("loaded Prosaic authority mismatch")
    if _one_hash(catalog, "checkpoint-selection") != manifest.checkpoint_selection_id:
        raise Protocol27InputStoreError("loaded checkpoint selection mismatch")


def _expect_semantic_authority_roles(
    catalog: Protocol27InputAuthorityCatalogV1,
    manifest: RunManifestV6,
    graph: SynthesisGraph,
    overview_catalog: AcceptedSourceOverviewCatalogV1,
) -> None:
    implementation = graph.policy_catalog.implementation_authority
    expected_by_role = {
        "source-authority": {
            value
            for source in manifest.accepted_sources
            for value in (
                source.source_root_hash,
                source.debt_manifest_hash,
                *source.lower_authority_ids,
            )
            if value is not None
        },
        "source-overview-projection": {
            item.identity for item in overview_catalog.projections
        },
        "source-overview-markdown": {
            item.object_hash for item in overview_catalog.projections
        },
        "response-schema": set(graph.response_schema_hashes.values()),
        "context-policy": {graph.context_policy_hash},
        "implementation-authority": {
            implementation.producer_authority_hash,
            implementation.executor_contract_hash,
            implementation.verifier_authority_hash,
        },
    }
    for role, expected in expected_by_role.items():
        if set(catalog.hashes_for(role)) != expected:
            raise Protocol27InputStoreError(f"loaded {role} closure mismatch")


def _expect_component_objects(
    catalog: Protocol27InputAuthorityCatalogV1,
    payloads: Mapping[str, bytes],
    graph: SynthesisGraph,
) -> None:
    expected_by_role = {
        "synthesis-topology": {
            graph.topology.identity: canonical_json_bytes(graph.topology.to_json_dict())
        },
        "synthesis-policy": {
            graph.policy_catalog.identity: canonical_json_bytes(
                graph.policy_catalog.to_json_dict()
            )
        },
        "work-template": {
            item.template_id: canonical_json_bytes(item.to_json_dict())
            for item in graph.templates
        },
        "graph-node": {
            item.node_id: canonical_json_bytes(item.to_json_dict())
            for item in graph.required_nodes
        },
        "root-specification": {
            graph.root_specification.identity: canonical_json_bytes(
                graph.root_specification.to_json_dict()
            )
        },
    }
    for role, expected in expected_by_role.items():
        if set(catalog.hashes_for(role)) != set(expected):
            raise Protocol27InputStoreError(f"loaded {role} closure mismatch")
        if any(payloads[object_hash] != payload for object_hash, payload in expected.items()):
            raise Protocol27InputStoreError(f"loaded {role} bytes mismatch")


def _validate_graph_overviews(
    graph: SynthesisGraph,
    catalog: AcceptedSourceOverviewCatalogV1,
) -> None:
    expected = {
        item.identity: item.object_hash for item in catalog.projections
    }
    observed = {
        dependency.artifact_key_id: dependency.artifact_hash
        for node in graph.required_nodes
        for dependency in node.fixed_artifact_dependencies
    }
    if observed != expected:
        raise Protocol27InputStoreError(
            "source overview catalog differs from synthesis graph authority"
        )
    if any(
        graph.public_paths.get(item.identity)
        != f"re/sources/{item.source_id}/overview.md"
        for item in catalog.projections
    ):
        raise Protocol27InputStoreError("source overview public paths mismatch")


def _validated_payload_mapping(
    values: Mapping[str, bytes],
    label: str,
) -> Mapping[str, bytes]:
    if not isinstance(values, Mapping):
        raise Protocol27InputStoreError(f"{label} must be a mapping")
    copied: dict[str, bytes] = {}
    for object_hash, payload in values.items():
        _schema(digest_value, object_hash, f"{label} key")
        if not isinstance(payload, bytes) or content_digest(payload) != object_hash:
            raise Protocol27InputStoreError(f"{label} hash mismatch: {object_hash}")
        if payload.startswith(TREE_OBJECT_MAGIC):
            raise Protocol27InputStoreError(f"{label} must contain blob objects")
        copied[object_hash] = payload
    return MappingProxyType(dict(sorted(copied.items())))


def _canonical_object_bytes(payload: bytes, label: str) -> bytes:
    if not isinstance(payload, bytes) or payload.startswith(TREE_OBJECT_MAGIC):
        raise Protocol27InputStoreError(f"{label} must be canonical JSON bytes")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Protocol27InputStoreError(f"{label} must be canonical JSON") from exc
    if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
        raise Protocol27InputStoreError(f"{label} must be one canonical JSON object")
    return payload


def _write_roles(
    store: ObjectStore,
    roles: Mapping[str, tuple[str, ...]],
    payloads: Mapping[str, bytes],
    selected_roles: tuple[str, ...],
) -> None:
    for object_hash in sorted(
        {
            item
            for role in selected_roles
            for item in roles.get(role, ())
        }
    ):
        if store.put_blob(payloads[object_hash]) != object_hash:
            raise Protocol27InputStoreError(
                f"staged protocol-2.7 object changed identity: {object_hash}"
            )


def _validate_staged(
    store: ObjectStore,
    catalog: Protocol27InputAuthorityCatalogV1,
    payloads: Mapping[str, bytes],
) -> None:
    for object_hash in catalog.object_hashes:
        if store.read_blob(object_hash) != payloads[object_hash]:
            raise Protocol27InputStoreError(
                f"staged protocol-2.7 object bytes changed: {object_hash}"
            )
    if store.read_blob(catalog.identity) != canonical_json_bytes(catalog.to_json_dict()):
        raise Protocol27InputStoreError("staged input authority catalog changed")


def _write_manifest(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short manifest write")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _one_hash(catalog: Protocol27InputAuthorityCatalogV1, role: str) -> str:
    hashes = catalog.hashes_for(role)
    if len(hashes) != 1:
        raise Protocol27InputStoreError(f"input authority role requires one object: {role}")
    return hashes[0]


def _one_typed(catalog, payloads, role, decoder):  # type: ignore[no-untyped-def]
    object_hash = _one_hash(catalog, role)
    return load_canonical_object(payloads[object_hash], decoder)


def _fault(hook: FaultHook | None, boundary: str) -> None:
    if hook is not None:
        hook(boundary)


__all__ = (
    "PreparedProtocol27Creation",
    "Protocol27InputAuthorityCatalogV1",
    "Protocol27InputSet",
    "Protocol27InputStoreError",
    "ValidatedProtocol27Inputs",
    "create_protocol_27_run_store",
    "load_protocol_27_inputs",
    "prepare_protocol_27_child",
)
