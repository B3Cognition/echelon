"""Resolve schema-5 outer authority into existing layer recovery inputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from harness.re_v2.protocol_22.graph import (
    Protocol22Graph,
    build_protocol_22_graph,
)
from harness.re_v2.protocol_22.inputs import (
    ValidatedProtocol22Inputs,
    load_protocol_22_inputs,
)
from harness.re_v2.protocol_22.model import RunManifestV2
from harness.re_v2.protocol_24.graph import (
    Protocol24Graph,
    validate_protocol_24_graph_authority,
)
from harness.re_v2.protocol_24.inputs import (
    ValidatedProtocol24Inputs,
    load_protocol_24_inputs,
)
from harness.re_v2.protocol_24.model import RunManifestV3
from harness.re_v2.protocol_25.graph import Protocol25Graph
from harness.re_v2.protocol_25.inputs import (
    ValidatedProtocol25Inputs,
)
from harness.re_v2.protocol_25.model import RunManifestV4
from harness.re_v2.run_store import Manifest, load_run_manifest

from .inputs import load_protocol_26_inputs
from .model import RunManifestV5

if TYPE_CHECKING:
    from harness.re_v2.protocol_22.recovery import Protocol22RunContext


class Protocol26AuthorityError(RuntimeError):
    """Raised when outer and embedded layer authority do not agree exactly."""


@dataclass(frozen=True, slots=True)
class ResolvedRunAuthorityV1:
    active_manifest: Manifest
    layer_manifest: RunManifestV2 | RunManifestV3 | RunManifestV4
    shared_inputs: ValidatedProtocol22Inputs | ValidatedProtocol24Inputs
    shared_graph: Protocol22Graph | Protocol24Graph
    semantic_inputs: ValidatedProtocol25Inputs | None = None
    semantic_graph: Protocol25Graph | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.layer_manifest,
            (RunManifestV2, RunManifestV3, RunManifestV4),
        ):
            raise Protocol26AuthorityError("resolved layer manifest is invalid")
        if not isinstance(self.shared_inputs, ValidatedProtocol22Inputs):
            raise Protocol26AuthorityError("resolved shared inputs are invalid")
        if not isinstance(self.shared_graph, (Protocol22Graph, Protocol24Graph)):
            raise Protocol26AuthorityError("resolved shared graph is invalid")
        semantic = self.semantic_inputs is not None or self.semantic_graph is not None
        if semantic != isinstance(self.layer_manifest, RunManifestV4):
            raise Protocol26AuthorityError(
                "semantic authority must exist exactly for an L3 layer manifest"
            )
        if semantic and (
            not isinstance(self.semantic_inputs, ValidatedProtocol25Inputs)
            or not isinstance(self.semantic_graph, Protocol25Graph)
        ):
            raise Protocol26AuthorityError("resolved semantic authority is invalid")

    @property
    def run_manifest_id(self) -> str:
        return self.active_manifest.run_manifest_id


def resolve_run_authority(
    context: "Protocol22RunContext",
) -> ResolvedRunAuthorityV1:
    """Authenticate one run and expose its unchanged layer-level authority."""
    manifest = load_run_manifest(context.paths.root.parent)
    if isinstance(manifest, RunManifestV5):
        inputs = load_protocol_26_inputs(context.paths, manifest)
        return _resolve_layer_authority(
            context,
            manifest,
            inputs.layer_execution_contract.layer_manifest,
            inputs.layer_inputs,
        )
    if isinstance(manifest, RunManifestV2):
        inputs = load_protocol_22_inputs(context.paths, manifest)
        graph = build_protocol_22_graph(manifest, inputs)
        _require_shared_context(context, inputs, graph, "protocol-2.2")
        return ResolvedRunAuthorityV1(manifest, manifest, inputs, graph)
    if isinstance(manifest, RunManifestV3):
        inputs = load_protocol_24_inputs(context.paths, manifest)
        graph = _validated_l2_context(context, manifest, inputs)
        return ResolvedRunAuthorityV1(manifest, manifest, inputs, graph)
    if isinstance(manifest, RunManifestV4):
        inputs = getattr(context, "semantic_inputs", None)
        if not isinstance(inputs, ValidatedProtocol25Inputs):
            raise Protocol26AuthorityError(
                "schema-4 recovery requires authenticated semantic inputs"
            )
        return _resolved_l3_context(context, manifest, manifest, inputs)
    raise Protocol26AuthorityError(
        "shared recovery requires a schema-2, schema-3, schema-4, or schema-5 manifest"
    )


def _resolve_layer_authority(
    context: "Protocol22RunContext",
    active_manifest: RunManifestV5,
    layer_manifest: RunManifestV2 | RunManifestV3 | RunManifestV4,
    layer_inputs: object,
) -> ResolvedRunAuthorityV1:
    if isinstance(layer_manifest, RunManifestV2) and isinstance(
        layer_inputs, ValidatedProtocol22Inputs
    ):
        graph = build_protocol_22_graph(layer_manifest, layer_inputs)
        _require_shared_context(context, layer_inputs, graph, "protocol-2.6 L1")
        return ResolvedRunAuthorityV1(
            active_manifest,
            layer_manifest,
            layer_inputs,
            graph,
        )
    if isinstance(layer_manifest, RunManifestV3) and isinstance(
        layer_inputs, ValidatedProtocol24Inputs
    ):
        graph = _validated_l2_context(context, layer_manifest, layer_inputs)
        return ResolvedRunAuthorityV1(
            active_manifest,
            layer_manifest,
            layer_inputs,
            graph,
        )
    if isinstance(layer_manifest, RunManifestV4) and isinstance(
        layer_inputs, ValidatedProtocol25Inputs
    ):
        return _resolved_l3_context(
            context,
            active_manifest,
            layer_manifest,
            layer_inputs,
        )
    raise Protocol26AuthorityError(
        "schema-5 layer manifest and validated inputs disagree"
    )


def _validated_l2_context(
    context: "Protocol22RunContext",
    manifest: RunManifestV3,
    inputs: ValidatedProtocol24Inputs,
) -> Protocol24Graph:
    if not isinstance(context.graph, Protocol24Graph):
        raise Protocol26AuthorityError("L2 recovery requires a protocol-2.4 graph")
    if context.inputs != inputs:
        raise Protocol26AuthorityError(
            "context inputs differ from immutable catalog authority"
        )
    try:
        return validate_protocol_24_graph_authority(manifest, inputs, context.graph)
    except Exception as exc:
        raise Protocol26AuthorityError(str(exc)) from exc


def _resolved_l3_context(
    context: "Protocol22RunContext",
    active_manifest: Manifest,
    layer_manifest: RunManifestV4,
    inputs: ValidatedProtocol25Inputs,
) -> ResolvedRunAuthorityV1:
    semantic_graph = getattr(context, "semantic_graph", None)
    semantic_inputs = getattr(context, "semantic_inputs", None)
    if (
        not isinstance(semantic_graph, Protocol25Graph)
        or semantic_graph.manifest != layer_manifest
        or semantic_inputs != inputs
        or semantic_graph._inputs != inputs.graph_inputs
    ):
        raise Protocol26AuthorityError(
            "context semantic graph differs from immutable layer authority"
        )
    _require_shared_context(
        context,
        semantic_graph.inputs,
        semantic_graph.prerequisite_graph,
        "protocol-2.5",
    )
    return ResolvedRunAuthorityV1(
        active_manifest,
        layer_manifest,
        semantic_graph.inputs,
        semantic_graph.prerequisite_graph,
        inputs,
        semantic_graph,
    )


def _require_shared_context(
    context: "Protocol22RunContext",
    inputs: ValidatedProtocol22Inputs,
    graph: Protocol22Graph | Protocol24Graph,
    label: str,
) -> None:
    if context.inputs != inputs:
        raise Protocol26AuthorityError(
            "context inputs differ from immutable catalog authority"
        )
    if context.graph != graph:
        raise Protocol26AuthorityError(
            f"context graph differs from immutable {label} graph"
        )


__all__ = (
    "Protocol26AuthorityError",
    "ResolvedRunAuthorityV1",
    "resolve_run_authority",
)
