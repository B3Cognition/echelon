"""Stable terminal source authority for protocol-2.7 synthesis children."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

from harness.re_v2.canonical import content_digest
from harness.re_v2.events import EventStore
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.materialization import (
    materialize_accepted_l1,
    materialize_accepted_l2,
)
from harness.re_v2.protocol_22.artifacts import SourceBaselineRootV1
from harness.re_v2.protocol_22.recovery import recover_protocol_22_run
from harness.re_v2.protocol_22.schema import load_canonical_object
from harness.re_v2.protocol_25.materialization import materialize_accepted_l3
from harness.re_v2.protocol_25.recovery import recover_protocol_25_run
from harness.re_v2.protocol_24.artifacts import L2SourceBaselineRootV1
from harness.re_v2.protocol_26.authority import resolve_run_authority
from harness.re_v2.run_store import ReV2Paths, load_run_manifest

from .model import (
    AcceptedSourceOutcomeV1,
    AcceptedSourceOverviewCatalogV1,
    AcceptedSourceOverviewProjectionV1,
    RunManifestV6,
)


class Protocol27AuthorityError(RuntimeError):
    """Raised when a synthesis parent is mutable, incomplete, or ambiguous."""


@dataclass(frozen=True, slots=True)
class ResolvedSynthesisParentV1:
    parent_run_id: str
    parent_manifest_hash: str
    source_snapshot_id: str
    partition_manifest_id: str
    selected_layers: Mapping[str, str]
    accepted_sources: tuple[AcceptedSourceOutcomeV1, ...]
    authority_objects: Mapping[str, bytes]
    debt_summary_hashes: Mapping[str, str]
    _context: object | None = field(default=None, repr=False, compare=False)
    _overview_catalog: AcceptedSourceOverviewCatalogV1 | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _overview_payloads: dict[str, bytes] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )
    _overview_authorities: Mapping[str, tuple[str, str]] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.accepted_sources:
            raise Protocol27AuthorityError("synthesis parent has no accepted sources")
        source_ids = tuple(item.source_id for item in self.accepted_sources)
        if source_ids != tuple(sorted(set(source_ids))):
            raise Protocol27AuthorityError(
                "synthesis parent sources must be canonically sorted and unique"
            )
        selected_layers = dict(sorted(self.selected_layers.items()))
        if set(selected_layers) != set(source_ids) or any(
            layer not in {"L1", "L2", "L3"} for layer in selected_layers.values()
        ):
            raise Protocol27AuthorityError(
                "synthesis parent selected layers must exactly cover accepted sources"
            )
        objects = dict(sorted(self.authority_objects.items()))
        for object_hash, payload in objects.items():
            if not isinstance(payload, bytes) or content_digest(payload) != object_hash:
                raise Protocol27AuthorityError(
                    f"synthesis parent authority object hash mismatch: {object_hash}"
                )
        summaries = dict(sorted(self.debt_summary_hashes.items()))
        partial_ids = {
            item.source_id for item in self.accepted_sources if item.outcome == "partial"
        }
        if set(summaries) != partial_ids:
            raise Protocol27AuthorityError(
                "synthesis parent debt summaries must exactly cover partial sources"
            )
        object.__setattr__(self, "authority_objects", MappingProxyType(objects))
        object.__setattr__(self, "debt_summary_hashes", MappingProxyType(summaries))
        object.__setattr__(self, "selected_layers", MappingProxyType(selected_layers))
        object.__setattr__(
            self,
            "_overview_authorities",
            MappingProxyType(dict(sorted(self._overview_authorities.items()))),
        )


ContextLoader = Callable[[Path, Path], object]


def resolve_synthesis_parent(
    workspace_root: Path,
    from_run: str,
    accepted_partial_sources: tuple[str, ...],
    *,
    context_loader: ContextLoader | None = None,
) -> ResolvedSynthesisParentV1:
    """Resolve one explicit terminal parent without trusting mutable projections."""
    root = Path(workspace_root).resolve()
    run_dir = _run_directory(root, from_run)
    before = load_run_manifest(run_dir)
    if isinstance(before, RunManifestV6):
        resolved = _resolve_embedded_protocol_27(run_dir, before)
    else:
        loader = context_loader or _default_context_loader
        resolved = _resolve_layer_parent(root, run_dir, loader(root, run_dir))
    after = load_run_manifest(run_dir)
    if after != before or after.run_manifest_id != resolved.parent_manifest_hash:
        raise Protocol27AuthorityError("parent manifest changed during authority read")
    _validate_exact_partial_selection(
        resolved.accepted_sources,
        accepted_partial_sources,
    )
    return resolved


def freeze_accepted_source_overviews(
    parent: ResolvedSynthesisParentV1,
) -> AcceptedSourceOverviewCatalogV1:
    """Rebuild and freeze the selected layer's canonical overview Markdown."""
    if parent._overview_catalog is not None:
        _validate_overview_catalog(parent, parent._overview_catalog)
        return parent._overview_catalog
    context = parent._context
    if context is None:
        raise Protocol27AuthorityError("parent has no reconstructable layer context")
    reports: dict[str, object] = {}
    layers = frozenset(parent.selected_layers.values())
    if "L1" in layers:
        reports["L1"] = materialize_accepted_l1(context)  # type: ignore[arg-type]
    if "L2" in layers:
        reports["L2"] = materialize_accepted_l2(context)  # type: ignore[arg-type]
    if "L3" in layers:
        reports["L3"] = materialize_accepted_l3(context)  # type: ignore[arg-type]
    shared_module = __import__(
        "harness.re_v2.protocol_22.materialization", fromlist=["materialization"]
    )
    semantic_module = __import__(
        "harness.re_v2.protocol_25.materialization", fromlist=["materialization"]
    )
    protocol_by_layer = {"L1": "2.2", "L2": "2.4", "L3": "2.5"}
    authority_by_layer = {
        "L1": _module_authority_hash(shared_module),
        "L2": _module_authority_hash(shared_module),
        "L3": _module_authority_hash(semantic_module),
    }
    ledger = context.ledger.replay()
    source_by_key = {
        receipt.artifact_key.identity: receipt.artifact_key.scope.source_id
        for receipt in ledger.accepted_artifacts.values()
        if receipt.artifact_key.artifact_kind == "source-overview"
    }
    projection_by_layer_source: dict[tuple[str, str], object] = {}
    for layer, report in reports.items():
        for item in report.projections:  # type: ignore[attr-defined]
            if layer == "L3" and item.artifact_kind == "l3-composed-overview":
                projection_by_layer_source[(layer, item.path.parent.name)] = item
            elif item.artifact_kind == "source-overview" and item.artifact_key_id in source_by_key:
                projection_by_layer_source[(layer, source_by_key[item.artifact_key_id])] = item

    projections: list[AcceptedSourceOverviewProjectionV1] = []
    for source in parent.accepted_sources:
        selected_layer = parent.selected_layers[source.source_id]
        materialized = projection_by_layer_source.get((selected_layer, source.source_id))
        if materialized is None:
            raise Protocol27AuthorityError(
                f"accepted source overview is missing: {source.source_id}"
            )
        path = materialized.path
        payload_path = path / "baseline.md" if path.is_dir() else path
        try:
            payload = payload_path.read_bytes()
        except OSError as exc:
            raise Protocol27AuthorityError(
                f"cannot freeze accepted source overview: {source.source_id}"
            ) from exc
        payload_hash = content_digest(payload)
        expected_overview = parent._overview_authorities.get(source.source_id)
        if expected_overview is None:
            raise Protocol27AuthorityError(
                f"accepted source overview authority is missing: {source.source_id}"
            )
        if selected_layer == "L3":
            if materialized.artifact_key_id != source.source_root_key_id:
                raise Protocol27AuthorityError(
                    f"L3 overview authority differs from source root: {source.source_id}"
                )
            if materialized.artifact_hash != payload_hash:
                raise Protocol27AuthorityError(
                    f"L3 overview content hash mismatch: {source.source_id}"
                )
        elif (
            materialized.artifact_key_id,
            materialized.artifact_hash,
        ) != expected_overview:
            raise Protocol27AuthorityError(
                f"accepted overview authority mismatch: {source.source_id}"
            )
        parent._overview_payloads[payload_hash] = payload
        projections.append(
            AcceptedSourceOverviewProjectionV1(
                schema_version=1,
                source_id=source.source_id,
                selected_layer=selected_layer,  # type: ignore[arg-type]
                source_root_key_id=source.source_root_key_id,
                source_root_hash=source.source_root_hash,
                materializer_protocol_version=protocol_by_layer[selected_layer],
                materializer_authority_hash=authority_by_layer[selected_layer],
                content_hash=payload_hash,
                object_hash=payload_hash,
            )
        )
    catalog = AcceptedSourceOverviewCatalogV1(1, tuple(projections))
    _validate_overview_catalog(parent, catalog)
    return catalog


def frozen_overview_payloads(
    parent: ResolvedSynthesisParentV1,
) -> Mapping[str, bytes]:
    """Return the exact bytes populated by overview freezing."""
    return MappingProxyType(dict(sorted(parent._overview_payloads.items())))


def _resolve_embedded_protocol_27(
    run_dir: Path,
    manifest: RunManifestV6,
) -> ResolvedSynthesisParentV1:
    paths = ReV2Paths.for_run(run_dir)
    events = EventStore(paths).replay()
    if not events or events[-1].type != "run_completed":
        raise Protocol27AuthorityError(
            "protocol-2.7 synthesis parent is not terminal complete"
        )
    objects = ObjectStore(paths.objects)
    authority_objects: dict[str, bytes] = {}
    required = {
        value
        for source in manifest.accepted_sources
        for value in (
            source.source_root_hash,
            source.debt_manifest_hash,
            *source.lower_authority_ids,
        )
        if value is not None
    }
    required.add(manifest.source_overview_catalog_id)
    for object_hash in sorted(required):
        try:
            authority_objects[object_hash] = objects.read_blob(object_hash)
        except Exception as exc:
            raise Protocol27AuthorityError(
                f"embedded synthesis authority object is unavailable: {object_hash}"
            ) from exc
    catalog = load_canonical_object(
        authority_objects[manifest.source_overview_catalog_id],
        AcceptedSourceOverviewCatalogV1.from_json_dict,
    )
    payloads: dict[str, bytes] = {}
    for projection in catalog.projections:
        try:
            payload = objects.read_blob(projection.object_hash)
        except Exception as exc:
            raise Protocol27AuthorityError(
                f"embedded source overview is unavailable: {projection.source_id}"
            ) from exc
        if content_digest(payload) != projection.content_hash:
            raise Protocol27AuthorityError(
                f"embedded source overview hash mismatch: {projection.source_id}"
            )
        authority_objects[projection.object_hash] = payload
        payloads[projection.object_hash] = payload
    summaries = {
        receipt.source_id: receipt.debt_summary_hash
        for receipt in manifest.partial_acceptances
    }
    resolved = ResolvedSynthesisParentV1(
        parent_run_id=manifest.run_id,
        parent_manifest_hash=manifest.run_manifest_id,
        source_snapshot_id=manifest.source_snapshot_id,
        partition_manifest_id=manifest.partition_manifest_id,
        selected_layers={
            item.source_id: item.selected_layer for item in catalog.projections
        },
        accepted_sources=manifest.accepted_sources,
        authority_objects=authority_objects,
        debt_summary_hashes=summaries,
        _overview_catalog=catalog,
        _overview_payloads=payloads,
        _overview_authorities={
            item.source_id: (item.source_root_key_id, item.content_hash)
            for item in catalog.projections
        },
    )
    _validate_overview_catalog(resolved, catalog)
    return resolved


def _resolve_layer_parent(
    workspace_root: Path,
    run_dir: Path,
    context: object,
) -> ResolvedSynthesisParentV1:
    del workspace_root
    try:
        authority = resolve_run_authority(context)  # type: ignore[arg-type]
    except Exception as exc:
        raise Protocol27AuthorityError(f"cannot authenticate synthesis parent: {exc}") from exc
    manifest = authority.active_manifest
    target_layer = getattr(manifest, "target_layer", None)
    if target_layer not in {"L1", "L2", "L3"}:
        raise Protocol27AuthorityError("synthesis parent has no supported terminal layer")
    authority_objects: dict[str, bytes] = {}
    summaries: dict[str, str] = {}
    outcomes: list[AcceptedSourceOutcomeV1] = []
    selected_layers: dict[str, str] = {}
    overview_authorities: dict[str, tuple[str, str]] = {}
    if target_layer == "L3":
        recovered = recover_protocol_25_run(context)  # type: ignore[arg-type]
        if recovered.state.terminal_state not in {"complete", "next_epoch_required"}:
            raise Protocol27AuthorityError("L3 parent is running, blocked, or incomplete")
        target_ids = tuple(authority.semantic_graph.selected_source_ids)
        l3_roots = recovered.ledger.l3_source_roots
        if tuple(sorted(l3_roots)) != tuple(sorted(target_ids)):
            raise Protocol27AuthorityError("L3 parent does not root every selected source")
        shared_ledger = recovered.ledger
    else:
        recovered = recover_protocol_22_run(context)  # type: ignore[arg-type]
        if (
            recovered.operational_state != "terminal"
            or not recovered.events
            or recovered.events[-1].type != "run_completed"
            or recovered.ledger is None
        ):
            raise Protocol27AuthorityError(
                f"{target_layer} parent is running, failed, or incomplete"
            )
        target_ids = _target_source_ids(authority.layer_manifest, authority.shared_inputs)
        shared_ledger = recovered.ledger

    all_source_ids = tuple(
        sorted(
            source.source_id
            for source in authority.shared_inputs.workspace_partition.sources
        )
    )
    roots_by_layer_source = {
        (receipt.artifact_key.layer, receipt.artifact_key.scope.source_id): receipt
        for receipt in shared_ledger.accepted_artifacts.values()
        if receipt.artifact_key.artifact_kind == "source-baseline-root"
        and receipt.artifact_key.layer in {"L1", "L2"}
    }
    overviews_by_layer_source = {
        (receipt.artifact_key.layer, receipt.artifact_key.scope.source_id): receipt
        for receipt in shared_ledger.accepted_artifacts.values()
        if receipt.artifact_key.artifact_kind == "source-overview"
        and receipt.artifact_key.layer in {"L1", "L2"}
    }
    for source_id in all_source_ids:
        if target_layer == "L3" and source_id in target_ids:
            root = l3_roots[source_id]
            if root.state not in {"complete", "next_epoch_required"}:
                raise Protocol27AuthorityError(
                    f"source is not a terminal synthesis input: {source_id}"
                )
            payload = context.object_store.read_blob(root.identity)
            authority_objects[root.identity] = payload
            partial = root.state == "next_epoch_required"
            if partial:
                summaries[source_id] = content_digest(
                    {
                        "deferred_observation_ids": list(root.deferred_observation_ids),
                        "source_id": source_id,
                        "source_root_hash": root.identity,
                    }
                )
            selected_layers[source_id] = "L3"
            overview_authorities[source_id] = (root.identity, root.identity)
            outcomes.append(
                AcceptedSourceOutcomeV1(
                    schema_version=1,
                    source_id=source_id,
                    source_root_key_id=root.identity,
                    source_root_hash=root.identity,
                    outcome="partial" if partial else "complete",
                    debt_manifest_hash=root.identity if partial else None,
                    lower_authority_ids=tuple(
                        sorted(
                            {
                                root.adopted_l2_root_hash,
                                *root.closure_root_hashes,
                                *root.audit_target_ids,
                                *root.deferred_observation_ids,
                            }
                        )
                    ),
                )
            )
            continue
        preferred = (
            ("L2", "L1") if target_layer in {"L2", "L3"} else ("L1",)
        )
        selected = next(
            (
                (layer, roots_by_layer_source[(layer, source_id)])
                for layer in preferred
                if (layer, source_id) in roots_by_layer_source
            ),
            None,
        )
        if selected is None:
            raise Protocol27AuthorityError(
                f"parent does not contain a terminal source root: {source_id}"
            )
        layer, receipt = selected
        if source_id in target_ids and layer != target_layer:
            raise Protocol27AuthorityError(
                f"parent did not close requested {target_layer} source: {source_id}"
            )
        overview_receipt = overviews_by_layer_source.get((layer, source_id))
        if overview_receipt is None:
            raise Protocol27AuthorityError(
                f"parent source root has no accepted overview: {source_id}"
            )
        payload = context.object_store.read_blob(receipt.artifact_hash)
        root_value = load_canonical_object(
            payload,
            (
                SourceBaselineRootV1.from_json_dict
                if layer == "L1"
                else L2SourceBaselineRootV1.from_json_dict
            ),
        )
        if root_value.overview_artifact_hash != overview_receipt.artifact_hash:
            raise Protocol27AuthorityError(
                f"source root overview dependency mismatch: {source_id}"
            )
        authority_objects[receipt.artifact_hash] = payload
        selected_layers[source_id] = layer
        overview_authorities[source_id] = (
            overview_receipt.artifact_key.identity,
            overview_receipt.artifact_hash,
        )
        outcomes.append(
            AcceptedSourceOutcomeV1(
                schema_version=1,
                source_id=source_id,
                source_root_key_id=receipt.artifact_key.identity,
                source_root_hash=receipt.artifact_hash,
                outcome="complete",
                debt_manifest_hash=None,
                lower_authority_ids=receipt.artifact_key.dependency_hashes,
            )
        )
    return ResolvedSynthesisParentV1(
        parent_run_id=manifest.run_id,
        parent_manifest_hash=manifest.run_manifest_id,
        source_snapshot_id=manifest.source_snapshot_id,
        partition_manifest_id=manifest.partition_manifest_id,
        selected_layers=selected_layers,
        accepted_sources=tuple(outcomes),
        authority_objects=authority_objects,
        debt_summary_hashes=summaries,
        _context=context,
        _overview_authorities=overview_authorities,
    )


def _target_source_ids(layer_manifest: object, shared_inputs: object) -> tuple[str, ...]:
    selection = getattr(layer_manifest, "selection", None)
    if selection is None or bool(getattr(selection, "all_sources", True)):
        return tuple(
            sorted(source.source_id for source in shared_inputs.workspace_partition.sources)
        )
    return tuple(selection.source_ids)


def _validate_exact_partial_selection(
    sources: tuple[AcceptedSourceOutcomeV1, ...],
    selected: tuple[str, ...],
) -> None:
    if selected != tuple(sorted(set(selected))):
        raise Protocol27AuthorityError(
            "partial acceptance source IDs must be sorted and unique"
        )
    by_id = {item.source_id: item for item in sources}
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise Protocol27AuthorityError(f"unknown partial source: {unknown[0]}")
    complete = sorted(
        source_id for source_id in selected if by_id[source_id].outcome == "complete"
    )
    if complete:
        raise Protocol27AuthorityError(
            f"complete source cannot be accepted as partial: {complete[0]}"
        )
    required = {item.source_id for item in sources if item.outcome == "partial"}
    missing = sorted(required - set(selected))
    if missing:
        raise Protocol27AuthorityError(f"missing partial acceptance: {missing[0]}")


def _validate_overview_catalog(
    parent: ResolvedSynthesisParentV1,
    catalog: AcceptedSourceOverviewCatalogV1,
) -> None:
    expected = {item.source_id: item for item in parent.accepted_sources}
    observed = {item.source_id: item for item in catalog.projections}
    if set(observed) != set(expected):
        raise Protocol27AuthorityError(
            "accepted overview catalog does not exactly cover parent sources"
        )
    for source_id, projection in observed.items():
        source = expected[source_id]
        if (
            projection.source_root_key_id != source.source_root_key_id
            or projection.source_root_hash != source.source_root_hash
        ):
            raise Protocol27AuthorityError(
                f"accepted overview differs from source root: {source_id}"
            )


def _run_directory(workspace_root: Path, from_run: str) -> Path:
    if (
        not isinstance(from_run, str)
        or not from_run
        or from_run in {".", ".."}
        or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in from_run)
    ):
        raise Protocol27AuthorityError(f"unsafe parent run ID: {from_run!r}")
    runs = workspace_root / "runs"
    run_dir = runs / from_run
    try:
        if run_dir.resolve().parent != runs.resolve():
            raise Protocol27AuthorityError("parent run escaped the workspace run root")
    except OSError as exc:
        raise Protocol27AuthorityError(f"cannot resolve parent run: {from_run}") from exc
    if not run_dir.is_dir() or run_dir.is_symlink():
        raise Protocol27AuthorityError(f"parent run does not exist: {from_run}")
    return run_dir


def _default_context_loader(workspace_root: Path, run_dir: Path) -> object:
    # Existing RE v2 context construction remains centralized in the CLI until
    # the protocol-2.7 lifecycle router is installed in Task 12.
    from echelon.cli import _re_v2_context

    return _re_v2_context(workspace_root, run_dir)


def _module_authority_hash(module: object) -> str:
    from harness.re_v2.protocol_22.authorities import implementation_closure_digest

    module_name = str(getattr(module, "__name__", ""))
    module_path = Path(str(getattr(module, "__file__", "")))
    if module_path.suffix == ".pyc" and module_path.with_suffix(".py").is_file():
        module_path = module_path.with_suffix(".py")
    if not module_name or module_path.is_symlink() or not module_path.is_file():
        raise Protocol27AuthorityError("materializer implementation authority is unavailable")
    return implementation_closure_digest(
        {module_name.replace(".", "/") + ".py": module_path.read_bytes()}
    )


__all__ = (
    "Protocol27AuthorityError",
    "ResolvedSynthesisParentV1",
    "freeze_accepted_source_overviews",
    "frozen_overview_payloads",
    "resolve_synthesis_parent",
)
