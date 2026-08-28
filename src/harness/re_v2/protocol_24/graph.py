"""Selected protocol-2.4 graph over the shared RE v2 planning kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Mapping, TypeAlias

from harness.re_v2.protocol_22.graph import (
    AcceptedArtifactV2,
    Protocol22GraphError,
    build_work_template_v2,
    instantiate_ready_item,
    normalize_graph_templates_v2,
)
from harness.re_v2.protocol_22.inputs import (
    Protocol22InputSet,
    ValidatedProtocol22Inputs,
)
from harness.re_v2.protocol_22.model import WorkTemplateV2
from harness.re_v2.protocol_22.partition import (
    DomainDescriptorV1,
    SourceDescriptorV1,
)
from harness.re_v2.protocol_22.schema import digest_value

from .model import ParentAuthorityBundleV1, RunManifestV3


AcceptedParentClosureV2: TypeAlias = Mapping[
    str,
    tuple[WorkTemplateV2, AcceptedArtifactV2],
]

_CATALOG_HASH_KEYS = frozenset(
    {
        "artifact_policy_catalog",
        "executor_contract_catalog",
        "workspace_partition_catalog",
    }
)
_DOMAIN_PARENT_KINDS = (
    "domain-inventory",
    "domain-evidence-pack",
    "domain-context-bundle",
    "domain-baseline",
)
_SOURCE_PARENT_KINDS = (
    "source-overview",
    "source-baseline-root",
)
_SOURCE_CONTEXT_INPUT_KINDS = (
    "source-inventory",
    "source-partition",
    "source-evidence-pack",
)


class Protocol24GraphError(Protocol22GraphError):
    """Raised when selected L2 graph authority is incoherent."""


@dataclass(frozen=True, slots=True)
class Protocol24Graph:
    templates: tuple[WorkTemplateV2, ...]
    requested_goals: tuple[str, ...]
    catalog_hashes: Mapping[str, str]
    selected_source_ids: tuple[str, ...]
    selected_domain_keys: tuple[str, ...]
    required_output_template_ids: tuple[str, ...]
    _inputs: ValidatedProtocol22Inputs | Protocol22InputSet = field(
        repr=False,
        compare=False,
    )

    CATALOG_HASH_KEYS: ClassVar[frozenset[str]] = _CATALOG_HASH_KEYS

    def __post_init__(self) -> None:
        try:
            templates = normalize_graph_templates_v2(
                self.templates,
                label="Protocol24Graph",
            )
        except Protocol22GraphError as exc:
            raise Protocol24GraphError(str(exc)) from exc
        if tuple(self.requested_goals) != ("selective-deepening",):
            raise Protocol24GraphError(
                "Protocol24Graph requested_goals must be selective-deepening"
            )
        if any(
            template.goal_id != "selective-deepening"
            for template in templates
            if template.layer == "L2"
        ):
            raise Protocol24GraphError(
                "every L2 template must use the selective-deepening goal"
            )
        if any(
            template.goal_id not in {"inventory", "baseline"}
            for template in templates
            if template.layer != "L2"
        ):
            raise Protocol24GraphError(
                "imported prerequisite templates must retain inventory/baseline goals"
            )
        if not isinstance(self.catalog_hashes, Mapping) or set(
            self.catalog_hashes
        ) != _CATALOG_HASH_KEYS:
            raise Protocol24GraphError(
                "Protocol24Graph.catalog_hashes must contain the three immutable catalogs"
            )
        hashes = {
            key: digest_value(value, f"Protocol24Graph.catalog_hashes[{key}]")
            for key, value in self.catalog_hashes.items()
        }
        if not isinstance(
            self._inputs,
            (ValidatedProtocol22Inputs, Protocol22InputSet),
        ):
            raise Protocol24GraphError(
                "Protocol24Graph inputs must be authenticated shared RE v2 inputs"
            )
        actual_hashes = {
            "workspace_partition_catalog": self._inputs.workspace_partition.identity,
            "artifact_policy_catalog": self._inputs.artifact_policy.identity,
            "executor_contract_catalog": self._inputs.executor_contract.identity,
        }
        if actual_hashes != hashes:
            raise Protocol24GraphError(
                "Protocol24Graph catalog hashes do not match authenticated inputs"
            )
        source_ids = _sorted_unique(self.selected_source_ids, "selected_source_ids")
        domain_keys = _sorted_unique(
            self.selected_domain_keys,
            "selected_domain_keys",
            digests=True,
        )
        required = _sorted_unique(
            self.required_output_template_ids,
            "required_output_template_ids",
            digests=True,
        )
        by_id = {template.template_id: template for template in templates}
        if not required or any(
            template_id not in by_id
            or by_id[template_id].layer != "L2"
            or by_id[template_id].artifact_kind != "source-baseline-root"
            for template_id in required
        ):
            raise Protocol24GraphError(
                "required outputs must be selected L2 source roots"
            )
        object.__setattr__(self, "templates", templates)
        object.__setattr__(self, "requested_goals", ("selective-deepening",))
        object.__setattr__(self, "catalog_hashes", MappingProxyType(dict(sorted(hashes.items()))))
        object.__setattr__(self, "selected_source_ids", source_ids)
        object.__setattr__(self, "selected_domain_keys", domain_keys)
        object.__setattr__(self, "required_output_template_ids", required)

    @property
    def inputs(self) -> ValidatedProtocol22Inputs | Protocol22InputSet:
        return self._inputs


def build_protocol_24_graph(
    manifest: RunManifestV3,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
    accepted_parent: AcceptedParentClosureV2,
) -> Protocol24Graph:
    """Build the exact imported prerequisite closure plus selected L2 delta."""
    if not isinstance(manifest, RunManifestV3):
        raise Protocol24GraphError("graph building requires RunManifestV3")
    if not isinstance(inputs, (ValidatedProtocol22Inputs, Protocol22InputSet)):
        raise Protocol24GraphError(
            "graph building requires authenticated shared RE v2 inputs"
        )
    _validate_manifest_inputs(manifest, inputs)
    parent = _validate_parent_mapping(accepted_parent)
    selected = _resolve_selection(manifest, inputs)

    parent_by_slot = {
        (
            template.scope.source_id,
            template.scope.domain_key,
            template.layer,
            template.artifact_kind,
        ): template
        for template, _artifact in parent.values()
    }
    required_parent_ids: set[str] = set()
    for source, domains in selected:
        for kind in _SOURCE_PARENT_KINDS:
            required_parent_ids.add(
                _parent_template(parent_by_slot, source.source_id, None, "L1", kind).template_id
            )
        for domain in domains:
            for layer, kind in (
                ("L0", "domain-inventory"),
                ("L0", "domain-evidence-pack"),
                ("L1", "domain-context-bundle"),
                ("L1", "domain-baseline"),
            ):
                required_parent_ids.add(
                    _parent_template(
                        parent_by_slot,
                        source.source_id,
                        domain.domain_key,
                        layer,
                        kind,
                    ).template_id
                )
    imported = _parent_dependency_closure(parent, required_parent_ids)
    imported_artifacts = _validate_accepted_parent(imported, inputs)

    templates: list[WorkTemplateV2] = [template for template, _artifact in imported.values()]
    required_outputs: list[str] = []
    for source, domains in selected:
        l2_domains: list[WorkTemplateV2] = []
        for domain in domains:
            inventory_id = _parent_template(
                parent_by_slot,
                source.source_id,
                domain.domain_key,
                "L0",
                "domain-inventory",
            ).template_id
            evidence = _l2_template(
                manifest,
                inputs,
                source,
                domain,
                "domain-evidence-pack",
                (inventory_id,),
            )
            context = _l2_template(
                manifest,
                inputs,
                source,
                domain,
                "domain-context-bundle",
                (inventory_id, evidence.template_id),
            )
            baseline = _l2_template(
                manifest,
                inputs,
                source,
                domain,
                "domain-baseline",
                (context.template_id,),
            )
            templates.extend((evidence, context, baseline))
            l2_domains.append(baseline)

        source_context_input_ids = tuple(
            _parent_template(parent_by_slot, source.source_id, None, "L0", kind).template_id
            for kind in _SOURCE_CONTEXT_INPUT_KINDS
        )
        selected_domain_ids = tuple(item.template_id for item in l2_domains)
        source_context = _l2_template(
            manifest,
            inputs,
            source,
            None,
            "source-overview-context-bundle",
            (*source_context_input_ids, *selected_domain_ids),
        )
        source_overview = _l2_template(
            manifest,
            inputs,
            source,
            None,
            "source-overview",
            (source_context.template_id,),
        )
        source_root = _l2_template(
            manifest,
            inputs,
            source,
            None,
            "source-baseline-root",
            (source_overview.template_id, *selected_domain_ids),
        )
        templates.extend((source_context, source_overview, source_root))
        required_outputs.append(source_root.template_id)

    graph = Protocol24Graph(
        templates=tuple(templates),
        requested_goals=manifest.requested_goals,
        catalog_hashes={
            "workspace_partition_catalog": manifest.workspace_partition_catalog.object_hash,
            "artifact_policy_catalog": manifest.artifact_policy_catalog.object_hash,
            "executor_contract_catalog": manifest.executor_contract_catalog.object_hash,
        },
        selected_source_ids=tuple(
            sorted(source.source_id for source, _domains in selected)
        ),
        selected_domain_keys=tuple(
            sorted(
                domain.domain_key
                for _source, domains in selected
                for domain in domains
            )
        ),
        required_output_template_ids=tuple(sorted(required_outputs)),
        _inputs=inputs,
    )
    # The imported artifacts are validated here; the same projections are replayed
    # into the child authority before the shared planner is allowed to dispatch.
    if len(imported_artifacts) != len(imported):
        raise Protocol24GraphError("accepted parent closure validation was incomplete")
    return graph


def reconstruct_adopted_parent_closure(
    bundle: ParentAuthorityBundleV1,
    ledger: object,
) -> Mapping[str, tuple[WorkTemplateV2, AcceptedArtifactV2]]:
    """Recover exact parent templates from the child's imported typed receipts."""
    if not isinstance(bundle, ParentAuthorityBundleV1):
        raise Protocol24GraphError(
            "parent reconstruction requires ParentAuthorityBundleV1"
        )
    work_items = getattr(ledger, "certification_work_items", None)
    if not isinstance(work_items, Mapping):
        raise Protocol24GraphError(
            "parent reconstruction requires imported certification work items"
        )
    indexed: list[tuple[object, AcceptedArtifactV2]] = []
    template_id_by_artifact_hash: dict[str, str] = {}
    for authority in bundle.artifacts:
        item = work_items.get(authority.certification_receipt_id)
        if item is None or getattr(item, "output_key", None) is None:
            raise Protocol24GraphError(
                "parent bundle references a missing certification work item"
            )
        if (
            item.output_key.identity != authority.artifact_key_id
            or tuple(item.required_artifact_hashes) != authority.dependency_hashes
        ):
            raise Protocol24GraphError(
                "parent bundle and imported work-item authority disagree"
            )
        previous = template_id_by_artifact_hash.get(authority.artifact_hash)
        if previous is not None and previous != item.template_id:
            raise Protocol24GraphError(
                "parent artifact hashes cannot resolve exact dependency templates"
            )
        template_id_by_artifact_hash[authority.artifact_hash] = item.template_id
        indexed.append(
            (
                item,
                AcceptedArtifactV2(
                    artifact_key_id=authority.artifact_key_id,
                    artifact_hash=authority.artifact_hash,
                ),
            )
        )

    result: dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]] = {}
    for item, artifact in indexed:
        try:
            required_template_ids = tuple(
                sorted(
                    template_id_by_artifact_hash[artifact_hash]
                    for artifact_hash in item.required_artifact_hashes
                )
            )
        except KeyError as exc:
            raise Protocol24GraphError(
                "parent work item references an artifact outside the adopted closure"
            ) from exc
        template = WorkTemplateV2(
            identity_schema_version=item.identity_schema_version,
            goal_id=item.goal_id,
            scope=item.output_key.scope,
            artifact_kind=item.output_key.artifact_kind,
            layer=item.output_key.layer,
            producer_id=item.producer_id,
            producer_family=item.producer_family,
            producer_protocol_version=item.producer_protocol_version,
            layer_policy_hash=item.output_key.layer_policy_hash,
            required_template_ids=required_template_ids,
            executor_contract_hash=item.executor_contract_hash,
            verifier_id=item.verifier_id,
            verifier_version=item.verifier_version,
            verifier_implementation_digest=item.verifier_implementation_digest,
            result_contract_id=item.result_contract_id,
            max_provider_attempts=item.max_provider_attempts,
            max_generation_attempts=item.max_generation_attempts,
            max_semantic_rounds=item.max_semantic_rounds,
            max_result_contract_retries=item.max_result_contract_retries,
            max_shared_retries=item.max_shared_retries,
            max_artifact_contract_retries=item.max_artifact_contract_retries,
        )
        if template.template_id != item.template_id:
            raise Protocol24GraphError(
                "imported work item cannot reconstruct its exact parent template"
            )
        result[template.template_id] = (template, artifact)
    try:
        normalize_graph_templates_v2(
            tuple(template for template, _artifact in result.values()),
            label="reconstructed parent closure",
        )
    except Protocol22GraphError as exc:
        raise Protocol24GraphError(str(exc)) from exc
    return MappingProxyType(dict(sorted(result.items())))


def validate_protocol_24_graph_authority(
    manifest: RunManifestV3,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
    graph: Protocol24Graph,
) -> Protocol24Graph:
    """Bind an already-closed child graph to its immutable manifest and inputs."""
    if not isinstance(manifest, RunManifestV3):
        raise Protocol24GraphError("graph validation requires RunManifestV3")
    if not isinstance(graph, Protocol24Graph):
        raise Protocol24GraphError("graph validation requires Protocol24Graph")
    _validate_manifest_inputs(manifest, inputs)
    if graph.inputs != inputs:
        raise Protocol24GraphError(
            "protocol-2.4 graph inputs differ from immutable input authority"
        )
    expected_catalogs = {
        "workspace_partition_catalog": manifest.workspace_partition_catalog.object_hash,
        "artifact_policy_catalog": manifest.artifact_policy_catalog.object_hash,
        "executor_contract_catalog": manifest.executor_contract_catalog.object_hash,
    }
    if dict(graph.catalog_hashes) != expected_catalogs:
        raise Protocol24GraphError(
            "protocol-2.4 graph catalogs differ from immutable manifest authority"
        )
    selected = _resolve_selection(manifest, inputs)
    source_ids = tuple(sorted(source.source_id for source, _domains in selected))
    domain_keys = tuple(
        sorted(domain.domain_key for _source, domains in selected for domain in domains)
    )
    if (
        graph.selected_source_ids != source_ids
        or graph.selected_domain_keys != domain_keys
    ):
        raise Protocol24GraphError(
            "protocol-2.4 graph selection differs from immutable manifest authority"
        )
    return graph


def _validate_manifest_inputs(
    manifest: RunManifestV3,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> None:
    if inputs.workspace_partition.snapshot_id != manifest.source_snapshot_id:
        raise Protocol24GraphError(
            "workspace partition snapshot does not match the run manifest"
        )
    references = (
        (inputs.workspace_partition.identity, manifest.workspace_partition_catalog.object_hash),
        (inputs.artifact_policy.identity, manifest.artifact_policy_catalog.object_hash),
        (inputs.executor_contract.identity, manifest.executor_contract_catalog.object_hash),
    )
    if any(actual != expected for actual, expected in references):
        raise Protocol24GraphError("protocol-2.4 catalog hash mismatch")


def _validate_parent_mapping(
    value: AcceptedParentClosureV2,
) -> dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]]:
    if not isinstance(value, Mapping) or not value:
        raise Protocol24GraphError("accepted parent closure must be a nonempty mapping")
    result: dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]] = {}
    for template_id, pair in value.items():
        if (
            not isinstance(template_id, str)
            or not isinstance(pair, tuple)
            or len(pair) != 2
            or not isinstance(pair[0], WorkTemplateV2)
            or not isinstance(pair[1], AcceptedArtifactV2)
            or pair[0].template_id != template_id
        ):
            raise Protocol24GraphError(
                "accepted parent closure must pair exact templates and accepted artifacts"
            )
        result[template_id] = pair
    return result


def _resolve_selection(
    manifest: RunManifestV3,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> tuple[tuple[SourceDescriptorV1, tuple[DomainDescriptorV1, ...]], ...]:
    workspace = inputs.workspace_partition
    by_source = {source.source_id: source for source in workspace.sources}
    source_ids = (
        tuple(sorted(by_source))
        if manifest.selection.all_sources
        else manifest.selection.source_ids
    )
    if any(source_id not in by_source for source_id in source_ids):
        raise Protocol24GraphError("selection references an unknown source")
    selected: list[tuple[SourceDescriptorV1, tuple[DomainDescriptorV1, ...]]] = []
    requested_domains = set(manifest.selection.domain_keys)
    for source_id in source_ids:
        source = by_source[source_id]
        domains = tuple(
            domain
            for domain in source.domains
            if not requested_domains or domain.domain_key in requested_domains
        )
        if not domains:
            raise Protocol24GraphError("selection resolves to no domains")
        selected.append((source, domains))
    resolved_domains = {domain.domain_key for _source, domains in selected for domain in domains}
    if requested_domains != (requested_domains & resolved_domains):
        raise Protocol24GraphError("selection references an unknown domain")
    return tuple(selected)


def _parent_template(
    by_slot: Mapping[tuple[str, str | None, str, str], WorkTemplateV2],
    source_id: str,
    domain_key: str | None,
    layer: str,
    artifact_kind: str,
) -> WorkTemplateV2:
    template = by_slot.get((source_id, domain_key, layer, artifact_kind))
    if template is None:
        raise Protocol24GraphError(
            f"accepted parent is missing prerequisite {(source_id, domain_key, layer, artifact_kind)!r}"
        )
    return template


def _parent_dependency_closure(
    parent: Mapping[str, tuple[WorkTemplateV2, AcceptedArtifactV2]],
    required_ids: set[str],
) -> dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]]:
    pending = list(required_ids)
    selected: dict[str, tuple[WorkTemplateV2, AcceptedArtifactV2]] = {}
    while pending:
        template_id = pending.pop()
        pair = parent.get(template_id)
        if pair is None:
            raise Protocol24GraphError(
                f"accepted parent is missing template {template_id}"
            )
        if template_id in selected:
            continue
        selected[template_id] = pair
        pending.extend(pair[0].required_template_ids)
    try:
        normalize_graph_templates_v2(
            tuple(template for template, _artifact in selected.values()),
            label="accepted parent closure",
        )
    except Protocol22GraphError as exc:
        raise Protocol24GraphError(str(exc)) from exc
    return selected


def _validate_accepted_parent(
    imported: Mapping[str, tuple[WorkTemplateV2, AcceptedArtifactV2]],
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
) -> dict[str, AcceptedArtifactV2]:
    remaining = dict(imported)
    accepted: dict[str, AcceptedArtifactV2] = {}
    while remaining:
        progressed = False
        for template_id in sorted(tuple(remaining)):
            template, artifact = remaining[template_id]
            if any(
                dependency_id not in accepted
                for dependency_id in template.required_template_ids
            ):
                continue
            dependencies = {
                dependency_id: accepted[dependency_id]
                for dependency_id in template.required_template_ids
            }
            try:
                item = instantiate_ready_item(template, dependencies, inputs)
            except Protocol22GraphError as exc:
                raise Protocol24GraphError(str(exc)) from exc
            if item.output_key.identity != artifact.artifact_key_id:
                raise Protocol24GraphError(
                    "accepted parent artifact key does not match its exact template closure"
                )
            accepted[template_id] = artifact
            del remaining[template_id]
            progressed = True
        if not progressed:
            raise Protocol24GraphError("accepted parent closure cannot be resolved")
    return accepted


def _l2_template(
    manifest: RunManifestV3,
    inputs: ValidatedProtocol22Inputs | Protocol22InputSet,
    source: SourceDescriptorV1,
    domain: DomainDescriptorV1 | None,
    artifact_kind: str,
    required_template_ids: tuple[str, ...],
) -> WorkTemplateV2:
    try:
        return build_work_template_v2(
            goal_id="selective-deepening",
            budget=manifest.initial_budget_policy,
            inputs=inputs,
            source=source,
            domain=domain,
            artifact_kind=artifact_kind,
            layer="L2",
            required_template_ids=tuple(sorted(required_template_ids)),
        )
    except (KeyError, Protocol22GraphError) as exc:
        raise Protocol24GraphError(str(exc)) from exc


def _sorted_unique(
    values: object,
    field_name: str,
    *,
    digests: bool = False,
) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or any(
        not isinstance(value, str) for value in values
    ):
        raise Protocol24GraphError(f"{field_name} must be an array of strings")
    result = tuple(values)
    if result != tuple(sorted(set(result))):
        raise Protocol24GraphError(f"{field_name} must be sorted and unique")
    if digests:
        for value in result:
            digest_value(value, field_name)
    return result


__all__ = (
    "AcceptedParentClosureV2",
    "Protocol24Graph",
    "Protocol24GraphError",
    "build_protocol_24_graph",
    "reconstruct_adopted_parent_closure",
    "validate_protocol_24_graph_authority",
)
