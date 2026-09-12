"""Fresh reviewed-analysis creation for the ordinary RE knowledge journey.

This is composition over existing immutable boundaries, not a new scheduler.
Discovery, independent review, protocol-2.8 analysis and later synthesis retain
one logical request and one transferred resource account.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
from typing import Callable, Mapping

from harness.config import HarnessConfig
from harness.prosaic_prompt_loader import ProsaicPromptLoader
from harness.re_v2.canonical import canonical_json_bytes, content_digest
from harness.re_v2.knowledge_accounting import (
    KnowledgeDispatchAccount,
    KnowledgeDispatchPolicy,
)
from harness.re_v2.knowledge_acquisition import (
    MAX_DISCOVERY_EXPANSION_ROUNDS,
    DiscoveryAcquisition,
)
from harness.re_v2.knowledge_activation import (
    activate_reviewed_discovery,
    load_reviewed_discovery,
)
from harness.re_v2.knowledge_bootstrap import build_snapshot_bootstrap
from harness.re_v2.knowledge_discovery import DiscoveryBoundary, DiscoveryError
from harness.re_v2.knowledge_dispatch import DiscoveryController
from harness.re_v2.knowledge_evidence import EvidenceSelectorV1
from harness.re_v2.knowledge_review_dispatch import DiscoveryReviewController
from harness.re_v2.ledger import ObjectStore
from harness.re_v2.protocol_22.partition import WorkspacePartitionCatalogV1
from harness.re_v2.protocol_22.provider import (
    DispatchReservationV1,
    canonical_prosaic_agent_bytes,
)
from harness.re_v2.protocol_24.model import SelectionScopeV1
from harness.re_v2.protocol_28.authority import build_l3_target_projections
from harness.re_v2.protocol_28.context import load_protocol_28_run_context
from harness.re_v2.protocol_28.evidence import (
    EvidenceStagingPolicyV1,
    stage_snapshot_evidence,
)
from harness.re_v2.protocol_28.executors import build_l4_executor_catalog
from harness.re_v2.protocol_28.lifecycle import create_or_reuse_protocol_28_child
from harness.re_v2.protocol_28.orchestration import DeepenOrchestrationRequestV1
from harness.re_v2.protocol_28.policies import build_repaired_exhaustive_policy
from harness.re_v2.protocol_28.preparation import (
    ReviewedProtocol28PreparationOptions,
    load_protocol_28_role_bytes,
    prepare_protocol_28_request,
)
from harness.re_v2.run_store import ReV2Paths
from harness.re_v2.snapshot import CapturedSnapshot


_NON_BEHAVIORAL_SUFFIXES = (".gif", ".ico", ".jpeg", ".jpg", ".mp4", ".png")
_DISCOVERY_RESERVATION_TOKENS = 262_144
_DISCOVERY_RESERVATION_ACTIVE_MS = 1_800_000
_DISCOVERY_MAX_REPAIRS = 2
_DISCOVERY_MAX_REVIEW_REVISIONS = 1
_DISCOVERY_MAX_REVIEW_REPAIRS = 2
# One proposal and review per revision epoch, plus every independently bounded
# evidence expansion and repair. The aggregate guard must admit every legal
# bounded path; the narrower guards still prevent non-converging loops.
_DISCOVERY_MAX_SOURCE_TURNS = (
    2 * (1 + _DISCOVERY_MAX_REVIEW_REVISIONS)
    + MAX_DISCOVERY_EXPANSION_ROUNDS
    + _DISCOVERY_MAX_REPAIRS
    + _DISCOVERY_MAX_REVIEW_REPAIRS
)


class KnowledgeCreationError(RuntimeError):
    """Closed fresh-creation diagnostic."""


@dataclass(frozen=True, slots=True)
class ReviewedAnalysisCreationOptions:
    request_run_id: str
    analysis_run_id: str
    created_at: str
    snapshot: CapturedSnapshot
    workspace_partition: WorkspacePartitionCatalogV1
    selection: SelectionScopeV1
    source_depths: tuple[tuple[str, str], ...]
    token_limit: int
    active_ms_limit: int
    config: HarnessConfig | None = None
    backend: object | None = None
    discovery_agent_bytes: bytes | None = None
    review_agent_bytes: bytes | None = None
    analysis_producer_agent_bytes: bytes | None = None
    analysis_verifier_agent_bytes: bytes | None = None
    fault_hook: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.snapshot, CapturedSnapshot)
            or not isinstance(self.workspace_partition, WorkspacePartitionCatalogV1)
            or not isinstance(self.selection, SelectionScopeV1)
            or type(self.token_limit) is not int
            or self.token_limit <= 0
            or type(self.active_ms_limit) is not int
            or self.active_ms_limit <= 0
        ):
            raise KnowledgeCreationError("invalid-reviewed-analysis-options")
        depths = tuple(self.source_depths)
        if depths != tuple(sorted(set(depths))) or any(
            depth not in {"quick", "standard", "deep"}
            for _source, depth in depths
        ):
            raise KnowledgeCreationError("invalid-reviewed-analysis-depths")
        object.__setattr__(self, "source_depths", depths)


@dataclass(frozen=True, slots=True)
class KnowledgeCreationResultV1:
    request_run_id: str
    state: str
    analysis_run_id: str | None
    reason_code: str | None = None


def _creation_intent(options: ReviewedAnalysisCreationOptions) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "reviewed_analysis_creation_intent",
        "request_run_id": options.request_run_id,
        "analysis_run_id": options.analysis_run_id,
        "created_at": options.created_at,
        "snapshot_id": options.snapshot.snapshot_id,
        "workspace_partition_id": options.workspace_partition.identity,
        "selection": asdict(options.selection),
        "source_depths": [list(row) for row in options.source_depths],
        "token_limit": options.token_limit,
        "active_ms_limit": options.active_ms_limit,
    }


def _record_creation_intent(paths: ReV2Paths, options: ReviewedAnalysisCreationOptions) -> None:
    path = paths.root / "knowledge-creation.json"
    expected = canonical_json_bytes(_creation_intent(options))
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise KnowledgeCreationError("unsafe-reviewed-analysis-creation-intent")
        try:
            observed = path.read_bytes()
        except OSError:
            raise KnowledgeCreationError(
                "reviewed-analysis-creation-intent-unavailable"
            ) from None
        if observed != expected:
            raise KnowledgeCreationError("reviewed-analysis-creation-intent-conflict")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(expected)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_reviewed_analysis_creation_intent(run_dir: Path) -> dict[str, object] | None:
    """Load the canonical durable fresh-creation intent, if this is one."""
    path = Path(run_dir).resolve() / "v2" / "knowledge-creation.json"
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise KnowledgeCreationError("unsafe-reviewed-analysis-creation-intent")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise KnowledgeCreationError(
            "invalid-reviewed-analysis-creation-intent"
        ) from None
    if (
        not isinstance(value, dict)
        or canonical_json_bytes(value) != path.read_bytes()
        or value.get("schema_version") != 1
        or value.get("kind") != "reviewed_analysis_creation_intent"
    ):
        raise KnowledgeCreationError("invalid-reviewed-analysis-creation-intent")
    return value


def _role_contract(
    workspace: Path, role_id: str, phase_name: str
) -> tuple[bytes, str]:
    artifact = ProsaicPromptLoader(workspace).load_subagent(role_id)
    if artifact is None:
        raise KnowledgeCreationError("installed-re-knowledge-role-missing")
    phase = workspace / ".echelon" / "runtime" / "workflow" / "phases" / phase_name
    if not phase.is_file() or phase.is_symlink():
        raise KnowledgeCreationError("installed-re-knowledge-phase-missing")
    try:
        phase_body = phase.read_text(encoding="utf-8")
    except OSError:
        raise KnowledgeCreationError("installed-re-knowledge-phase-unavailable") from None
    tier = artifact.frontmatter.get("model_tier")
    if not isinstance(tier, str) or not tier:
        raise KnowledgeCreationError("installed-re-knowledge-model-tier-missing")
    combined = replace(artifact, body=artifact.body.rstrip() + "\n\n" + phase_body)
    return canonical_prosaic_agent_bytes(combined), tier


def _selected_source_ids(
    partition: WorkspacePartitionCatalogV1, selection: SelectionScopeV1
) -> tuple[str, ...]:
    declared = tuple(source.source_id for source in partition.sources)
    selected = declared if selection.all_sources else selection.source_ids
    if not selected or not set(selected).issubset(declared):
        raise KnowledgeCreationError("reviewed-analysis-source-selection-mismatch")
    return tuple(sorted(selected))


def _initial_binding(boundary: DiscoveryBoundary, source) -> str:  # type: ignore[no-untyped-def]
    records = tuple(
        record
        for record in source.files
        if record.object_kind == "regular" and record.text_status == "eligible_utf8"
    )
    # Give root/config entry points priority while retaining deterministic order.
    records = tuple(
        sorted(
            records,
            key=lambda row: (
                "/" in row.source_relative_path,
                row.source_relative_path.encode("utf-8"),
            ),
        )[:64]
    )
    for byte_limit in (8_192, 4_096, 2_048, 1_024, 512, 256):
        selectors = tuple(
            EvidenceSelectorV1(
                source.source_id,
                record.source_relative_path,
                0,
                min(record.byte_count, byte_limit),
            )
            for record in records
        )
        try:
            return boundary.prepare(selectors, schema_version=3)
        except DiscoveryError as exc:
            if str(exc) != "discovery-context-bound":
                raise
    raise KnowledgeCreationError("initial-discovery-context-bound")


def _existing_result(
    workspace: Path, options: ReviewedAnalysisCreationOptions
) -> KnowledgeCreationResultV1 | None:
    manifest = workspace / "runs" / options.analysis_run_id / "v2" / "run.json"
    if not manifest.exists():
        return None
    context = load_protocol_28_run_context(manifest.parents[1])
    from harness.re_v2.knowledge_revision import load_knowledge_revision

    active = load_knowledge_revision(context)
    if (
        (active is not None and active.manifest.logical_run_id != options.request_run_id)
        or context.inputs.manifest.source_snapshot_id != options.snapshot.snapshot_id
        or context.inputs.manifest.selection != options.selection
    ):
        raise KnowledgeCreationError("existing-reviewed-analysis-conflicts")
    if active is None:
        return None
    return KnowledgeCreationResultV1(
        options.request_run_id, "ready", options.analysis_run_id
    )


def create_or_resume_reviewed_analysis(
    workspace_root: Path,
    options: ReviewedAnalysisCreationOptions,
) -> KnowledgeCreationResultV1:
    """Create or recover one reviewed analysis child without legacy RE stages."""

    if not isinstance(options, ReviewedAnalysisCreationOptions):
        raise KnowledgeCreationError("invalid-reviewed-analysis-options")
    workspace = Path(workspace_root).resolve()
    request_dir = workspace / "runs" / options.request_run_id
    paths = ReV2Paths.for_run(request_dir)
    paths.root.mkdir(parents=True, exist_ok=True)
    _record_creation_intent(paths, options)
    existing = _existing_result(workspace, options)
    if existing is not None:
        return existing

    selected_ids = _selected_source_ids(
        options.workspace_partition, options.selection
    )
    depths = dict(options.source_depths)
    if set(depths) != set(selected_ids):
        raise KnowledgeCreationError("reviewed-analysis-depth-closure-mismatch")
    objects = ObjectStore(paths.objects)
    quarantine = ObjectStore(request_dir / "quarantine")

    bootstrap = build_snapshot_bootstrap(
        options.request_run_id,
        options.snapshot,
        options.workspace_partition,
        options.selection,
    )
    l3 = build_l3_target_projections(bootstrap.parent, options.selection)
    evidence = stage_snapshot_evidence(
        options.snapshot,
        options.workspace_partition,
        options.selection,
        EvidenceStagingPolicyV1(1, 65_536, _NON_BEHAVIORAL_SUFFIXES),
        objects,
    )

    phases: list[tuple[DiscoveryAcquisition, DiscoveryBoundary]] = []
    selected_sources = {
        source.source_id: source
        for source in options.workspace_partition.sources
        if source.source_id in set(selected_ids)
    }
    for source_id in selected_ids:
        boundary = DiscoveryBoundary(
            options.snapshot,
            options.workspace_partition,
            source_id,
            depths[source_id],
            content_digest(
                {
                    "kind": "reviewed-source-discovery",
                    "request_run_id": options.request_run_id,
                    "source_id": source_id,
                    "depth": depths[source_id],
                }
            ),
            objects,
            quarantine,
            options.selection.domain_keys or None,
        )
        binding = _initial_binding(boundary, selected_sources[source_id])
        phases.append((DiscoveryAcquisition(paths, boundary, binding), boundary))

    if options.discovery_agent_bytes is None:
        discovery_agent, model_tier = _role_contract(
            workspace,
            "echelon.re-discoverer",
            "re-knowledge-discovery.md",
        )
    else:
        discovery_agent, model_tier = options.discovery_agent_bytes, "strong"
    if options.review_agent_bytes is None:
        review_agent, review_tier = _role_contract(
            workspace,
            "echelon.re-discovery-reviewer",
            "re-knowledge-discovery-review.md",
        )
    else:
        review_agent, review_tier = options.review_agent_bytes, model_tier
    if model_tier != review_tier:
        raise KnowledgeCreationError("discovery-review-model-tier-mismatch")

    backend = options.backend
    if backend is None:
        if options.config is None:
            raise KnowledgeCreationError("configured-provider-required")
        from harness.re_v2.knowledge_llm import KnowledgeLLMBackend

        backend = KnowledgeLLMBackend(
            options.config,
            model_tier=model_tier,
            screen_output=phases[0][1].screen_output,
            max_capture_bytes=262_144,
        )
    contract = getattr(backend, "contract", None)
    if contract is None:
        raise KnowledgeCreationError("invalid-reviewed-analysis-provider")
    authority = phases[0][1].run_authority()
    authority["source_ids"] = list(selected_ids)
    account = KnowledgeDispatchAccount(
        paths,
        KnowledgeDispatchPolicy(
            options.token_limit,
            options.active_ms_limit,
            _DISCOVERY_MAX_SOURCE_TURNS,
            _DISCOVERY_MAX_REPAIRS,
            _DISCOVERY_MAX_REVIEW_REVISIONS,
            _DISCOVERY_MAX_REVIEW_REPAIRS,
        ),
        contract,
        authority,
    )
    reservation = DispatchReservationV1(
        _DISCOVERY_RESERVATION_TOKENS,
        _DISCOVERY_RESERVATION_TOKENS,
        min(_DISCOVERY_RESERVATION_ACTIVE_MS, options.active_ms_limit),
    )
    reviewed = []
    for acquisition, _boundary in phases:
        producer = DiscoveryController(
            acquisition, account, discovery_agent, backend, reservation
        )
        while True:
            while True:
                produced = producer.step()
                if produced.state in {"evidence_ready", "repair_ready"}:
                    continue
                break
            if produced.state != "proposal_ready":
                return KnowledgeCreationResultV1(
                    options.request_run_id,
                    "needs-attention",
                    None,
                    produced.reason_code or produced.state,
                )
            reviewer = DiscoveryReviewController(
                producer, review_agent, backend, reservation
            )
            while True:
                reviewed_result = reviewer.step()
                if reviewed_result.state == "review_repair_ready":
                    continue
                break
            if reviewed_result.state == "revision_required":
                continue
            if reviewed_result.state != "review_ready":
                return KnowledgeCreationResultV1(
                    options.request_run_id,
                    "needs-attention",
                    None,
                    reviewed_result.reason_code or reviewed_result.state,
                )
            break
        root = activate_reviewed_discovery(
            acquisition, account, reviewer, l3, evidence
        )
        reviewed.append(load_reviewed_discovery(root, objects, l3, evidence))

    if options.analysis_producer_agent_bytes is None:
        analysis_producer, analysis_verifier = load_protocol_28_role_bytes(workspace)
    else:
        if options.analysis_verifier_agent_bytes is None:
            raise KnowledgeCreationError("analysis-role-closure-mismatch")
        analysis_producer = options.analysis_producer_agent_bytes
        analysis_verifier = options.analysis_verifier_agent_bytes
    inherited_executor = canonical_json_bytes(
        {
            "schema_version": 1,
            "kind": "reviewed_analysis_configured_provider",
            "provider_contract_id": contract.identity,
        }
    )
    policy = build_repaired_exhaustive_policy(
        producer_contract_hash=content_digest(analysis_producer),
        verifier_contract_hash=content_digest(analysis_verifier),
    )
    executors = build_l4_executor_catalog(
        inherited_executor_contract_hash=content_digest(inherited_executor),
        producer_agent_contract_hash=content_digest(analysis_producer),
        verifier_agent_contract_hash=content_digest(analysis_verifier),
    )
    intent = DeepenOrchestrationRequestV1(
        1,
        bootstrap.parent.run_id,
        bootstrap.parent.manifest_hash,
        bootstrap.parent.terminal_event_hash,
        bootstrap.parent.source_snapshot_id,
        bootstrap.parent.partition_manifest_id,
        options.selection,
        policy.identity,
        executors.identity,
        bootstrap.bootstrap_authority_id,
    )
    preparation = ReviewedProtocol28PreparationOptions(
        run_id=options.analysis_run_id,
        created_at=options.created_at,
        snapshot=options.snapshot,
        workspace_partition=options.workspace_partition,
        inherited_executor_contract_bytes=inherited_executor,
        lineage_root_run_id=bootstrap.parent.run_id,
        lineage_root_manifest_hash=bootstrap.bootstrap_authority_id,
        authority_objects=bootstrap.authority_objects,
        token_limit=options.token_limit,
        active_ms_limit=options.active_ms_limit,
        producer_agent_bytes=analysis_producer,
        verifier_agent_bytes=analysis_verifier,
        reviewed_discoveries=tuple(reviewed),
    )
    inputs = prepare_protocol_28_request(
        workspace, intent, bootstrap.parent, preparation
    )
    child = create_or_reuse_protocol_28_child(workspace, inputs)
    from harness.re_v2.knowledge_revision import activate_knowledge_workflow

    activate_knowledge_workflow(
        load_protocol_28_run_context(child),
        account,
        allow_debt=True,
        fault_hook=options.fault_hook,
    )
    return KnowledgeCreationResultV1(
        options.request_run_id, "ready", options.analysis_run_id
    )


__all__ = (
    "KnowledgeCreationError",
    "KnowledgeCreationResultV1",
    "ReviewedAnalysisCreationOptions",
    "create_or_resume_reviewed_analysis",
    "load_reviewed_analysis_creation_intent",
)
