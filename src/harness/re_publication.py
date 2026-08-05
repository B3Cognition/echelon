"""Validation and atomic publication of workspace reverse-engineering artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

from echelon.topology_registry import (
    TopologyRegistryError,
    _load_topology_index_for_configured_sources,
    load_published_topology_from_index,
    load_topology_index,
)
from echelon.workspace_model import (
    WorkspaceSourceDeclarations,
    discover_workspace,
    load_workspace_source_declarations,
    validate_topology_source_declarations,
)

from harness.re_artifacts import (
    ReArtifactCatalogError,
    ReArtifactDescriptor,
    build_re_artifact_catalog,
    classify_re_artifact,
    is_topology_provider_artifact,
    validate_re_artifact_descriptor,
)
from harness.re_architecture import validate_re_architecture_catalog
from harness.publication_transaction import (
    PublicationOperation,
    PublicationTransaction,
    PublicationTransactionError,
    apply_publication_transaction,
    rollback_publication_transaction,
    write_json_atomic,
    write_publication_journal,
)
from harness.re_lock import (
    claim_orphan_publish_recovery,
    claim_stale_publish_recovery,
    RePublishLock,
    RePublishRecoveryRequired,
    recoverable_publish_lock_owner,
)
from harness.re_planner import ReExecutionPlan, RePlanSource
from harness.re_quality_gate import (
    MINIMUM_SOURCE_EVIDENCE,
    ReSpecQualityFailure,
    validate_staged_re_quality,
)
from harness.re_quality_contract import QUALITY_CONTRACT_VERSION
from harness.re_registry import (
    PublishedReIndex,
    PublishedSource,
    ReRegistryError,
    ReRegistryPaths,
    canonical_re_artifacts,
    ensure_re_layout,
    load_published_index,
    published_source_is_usable,
)
from harness.topology_evidence import (
    ProviderArtifactPaths,
    TopologyEvidenceError,
    build_empty_topology_snapshot_candidate,
    build_topology_snapshot_candidate,
    is_historical_codegraph_v1_artifact,
    upgrade_legacy_codegraph_candidate,
)
from harness.topology_publication import (
    TopologyProviderCandidate,
    TopologyPublicationValidationError,
    TopologySnapshotCandidate,
    stage_topology_snapshots,
)
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
class RePublicationError(RuntimeError):
    """Base error for deterministic RE publication."""


class RePublicationValidationError(RePublicationError):
    """Raised when staged RE output is not structurally publishable."""


class RePublicationConflict(RePublicationError):
    """Raised when the pinned generation changed before publication."""


@dataclass(frozen=True)
class RePublicationCandidate:
    run_id: str
    run_dir: Path
    status: Literal["complete", "partial"]
    plan: ReExecutionPlan
    refreshed_sources: tuple[str, ...]
    empty_sources: tuple[str, ...]
    partial_sources: tuple[str, ...]
    removed_sources: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RePublicationResult:
    generation: int
    status: str
    index_path: Path
    changed_sources: tuple[str, ...]
    removed_sources: tuple[str, ...]
    warnings: tuple[str, ...]
    topology_generation: int | None = None


def validate_re_run(
    workspace_root: Path,
    run_dir: Path,
    *,
    allow_partial: bool,
    status_override: Literal["complete", "partial"] | None = None,
) -> RePublicationCandidate:
    """Validate a run without changing the published registry."""
    root = workspace_root.resolve()
    resolved_run = run_dir.resolve()
    if not _inside_run_roots(root, resolved_run):
        raise RePublicationValidationError(f"run directory is outside workspace runs: {run_dir}")
    run_id = resolved_run.name
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise RePublicationValidationError(f"unsafe run ID: {run_id!r}")

    run_re = resolved_run / "re"
    run_state = _read_json(resolved_run / "state.json", required=False)
    re_state = _read_json(run_re / "state.json", required=False)
    observed = run_state.get("golddigger_status") or re_state.get("publication_status")
    if run_state.get("golddigger_status") == "failed" or re_state.get("status") == "failed":
        raise RePublicationValidationError("failed RE output is not publishable")
    if not observed and re_state.get("status") == "done":
        observed = "complete"
    status = status_override or observed

    plan_raw = _read_json(run_re / "re-execution-plan.json")
    try:
        plan = ReExecutionPlan.from_json_dict(plan_raw)
    except ValueError as exc:
        raise RePublicationValidationError(f"invalid RE execution plan: {exc}") from exc
    if not plan.publication_required:
        raise RePublicationValidationError("RE execution plan does not require publication")
    _validate_target_source_available(root, plan)
    partial_sources = _partial_quality_debt_sources(run_re, re_state, plan)
    if status == "complete" and partial_sources:
        if allow_partial and status_override is None:
            status = "partial"
        else:
            raise RePublicationValidationError(
                "complete RE publication cannot contain source quality debt"
            )
    if status == "partial" and not allow_partial:
        raise RePublicationValidationError("partial RE output requires --allow-partial")
    if status not in {"complete", "partial"}:
        raise RePublicationValidationError(f"RE publication status is not publishable: {status!r}")

    _validate_source_index(run_re / "re-source-index.json", plan)
    _validate_workspace_inputs(run_re / "re-workspace-inputs.json", plan)
    current = load_published_index(root)
    if current is not None:
        try:
            canonical_re_artifacts(root, current)
        except ReRegistryError as exc:
            raise RePublicationValidationError(
                f"current RE publication is structurally invalid: {exc}"
            ) from exc
    refreshed: list[str] = []
    empty: list[str] = []
    for source in plan.sources:
        if source.action == "refresh":
            _validate_refreshed_source(run_re / "sources" / source.id, source)
            refreshed.append(source.id)
        elif source.action == "skip-empty":
            empty.append(source.id)
        elif source.action in {"reuse", "missing"}:
            _validate_current_source(source, current)

    quality_report = validate_staged_re_quality(run_re, plan)
    quality_failures = [
        failure
        for failure in quality_report.failures
        if failure.source_id not in partial_sources
    ]
    if quality_failures:
        _raise_quality_failure(quality_failures[0])
    execution_profile = re_state.get("re_execution_profile")
    semantic_audit_mode = (
        execution_profile.get("semantic_audit_mode", "all")
        if isinstance(execution_profile, dict)
        else "all"
    )
    if semantic_audit_mode != "none":
        _validate_semantic_quality_report(run_re, partial_sources=partial_sources)
    try:
        validate_re_architecture_catalog(run_re, plan)
    except ValueError as exc:
        raise RePublicationValidationError(
            f"architecture catalog validation failed: {exc}"
        ) from exc

    for removed_id in plan.removed_sources:
        if current is None or removed_id not in current.sources:
            raise RePublicationValidationError(
                f"removed source is not present in current publication: {removed_id}"
            )

    workspace = run_re / "workspace"
    for name in ("overview.md", "relationships.md", "contracts.md"):
        path = workspace / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise RePublicationValidationError(f"required workspace synthesis missing: {path}")

    warnings = tuple(
        str(item)
        for item in run_state.get("golddigger_notes", [])
        if isinstance(item, str) and item.strip()
    )
    return RePublicationCandidate(
        run_id=run_id,
        run_dir=resolved_run,
        status=status,
        plan=plan,
        refreshed_sources=tuple(sorted(refreshed)),
        empty_sources=tuple(sorted(empty)),
        partial_sources=tuple(sorted(partial_sources)),
        removed_sources=tuple(sorted(plan.removed_sources)),
        warnings=warnings,
    )


def _validate_semantic_quality_report(
    run_re: Path, *, partial_sources: set[str]
) -> None:
    path = run_re / "quality" / "semantic-quality-review.json"
    report = _read_json(path, required=False)
    if report.get("quality_contract_version") != QUALITY_CONTRACT_VERSION:
        raise RePublicationValidationError(
            f"current semantic quality review is required before publication: {path}"
        )
    failures = report.get("failures")
    if report.get("passed") is True and not failures:
        return
    if not isinstance(failures, list) or not failures:
        raise RePublicationValidationError(
            f"semantic quality review has unresolved findings: {path}"
        )
    failure_sources = {
        item.get("source_id")
        for item in failures
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    if not failure_sources or not failure_sources <= partial_sources:
        raise RePublicationValidationError(
            f"semantic quality review has unresolved findings: {path}"
        )


def _partial_quality_debt_sources(
    run_re: Path,
    re_state: dict[str, Any],
    plan: ReExecutionPlan,
) -> set[str]:
    """Return only debt sources proven by controller-owned source reports."""
    source_states = re_state.get("re_source_states")
    if not isinstance(source_states, dict):
        return set()
    refresh_ids = {source.id for source in plan.refresh_sources}
    reports_root = (run_re / "quality" / "sources").resolve()
    partial: set[str] = set()
    for source_id, source_state in source_states.items():
        if source_id not in refresh_ids or not isinstance(source_state, dict):
            continue
        if source_state.get("status") != "partial_quality_debt":
            continue
        report_value = source_state.get("quality_debt_report")
        if not isinstance(report_value, str) or not report_value:
            raise RePublicationValidationError(
                f"partial source has no quality debt report: {source_id}"
            )
        report_path = Path(report_value).resolve()
        if not report_path.is_relative_to(reports_root):
            raise RePublicationValidationError(
                f"partial source quality debt report is outside RE quality output: {source_id}"
            )
        report = _read_json(report_path)
        if (
            report.get("source_id") != source_id
            or report.get("passed") is not False
            or report.get("quality_contract_version") != QUALITY_CONTRACT_VERSION
        ):
            raise RePublicationValidationError(
                f"partial source quality debt report is invalid: {report_path}"
            )
        partial.add(source_id)
    return partial


def publish_re_run(
    workspace_root: Path,
    run_dir: Path,
    *,
    allow_partial: bool = False,
    status_override: Literal["complete", "partial"] | None = None,
    expected_generation: int | None = None,
    allow_same_run_republish: bool = False,
    fault_hook: Callable[[str], None] | None = None,
) -> RePublicationResult:
    """Validate and publish one RE generation as a rollback-capable transaction."""
    root = workspace_root.resolve()
    candidate = validate_re_run(
        root,
        run_dir,
        allow_partial=allow_partial,
        status_override=status_override,
    )
    paths = ensure_re_layout(root)
    with RePublishLock.acquire(root, candidate.run_id, candidate.run_dir):
        current = load_published_index(root)
        current_generation = current.generation if current else 0
        same_run_republish = (
            allow_same_run_republish
            and current is not None
            and current.published_from_run == candidate.run_id
        )
        if (
            expected_generation is not None
            and current_generation != expected_generation
            and not same_run_republish
        ):
            raise RePublicationConflict(
                f"expected generation {expected_generation}, found {current_generation}"
            )
        generation = current_generation + 1
        transaction, topology_generation, declaration_snapshot = _prepare_transaction(
            root, paths, candidate, current, generation
        )
        _apply_transaction(
            transaction,
            paths,
            topology_generation=topology_generation,
            declaration_snapshot=declaration_snapshot,
            fault_hook=fault_hook,
        )
        published = PublishedReIndex.from_path(paths.index)
        if published.generation != generation:
            raise RePublicationError("published RE generation failed post-write validation")

    return RePublicationResult(
        generation=generation,
        status=candidate.status,
        index_path=paths.index,
        changed_sources=tuple(sorted(candidate.refreshed_sources + candidate.empty_sources)),
        removed_sources=candidate.removed_sources,
        warnings=candidate.warnings,
        topology_generation=topology_generation,
    )


def recover_interrupted_publication(
    workspace_root: Path,
    *,
    stale_after_seconds: int = 3600,
) -> bool:
    """Roll back a stale interrupted replacement before removing its lock."""
    root = workspace_root.resolve()
    owner = recoverable_publish_lock_owner(
        root,
        stale_after_seconds=stale_after_seconds,
    )
    recovery_lock = None
    if owner is None:
        recovery_lock = claim_orphan_publish_recovery(root)
        if recovery_lock is None:
            return False
        run_id = recovery_lock.owner_run_id
    else:
        recovery_lock = claim_stale_publish_recovery(
            root,
            stale_after_seconds=stale_after_seconds,
        )
        if recovery_lock is None:
            return False
        run_id = recovery_lock.owner_run_id
    paths = ensure_re_layout(root)
    stage_root = paths.staging / run_id
    journal = stage_root / "rollback-journal.json"
    if not journal.is_file():
        recovery_lock.release()
        return False
    data = _read_json(journal)
    if data.get("status") not in {"replacing", "rolling_back"}:
        recovery_lock.release()
        return True
    try:
        transaction = PublicationTransaction.from_journal(
            workspace_root=paths.root,
            staging_root=stage_root,
            journal=journal,
        )
    except PublicationTransactionError as exc:
        raise RePublishRecoveryRequired(str(exc)) from exc
    rollback_publication_transaction(transaction)
    recovery_lock.release()
    shutil.rmtree(stage_root)
    return True


def _prepare_transaction(
    workspace_root: Path,
    paths: ReRegistryPaths,
    candidate: RePublicationCandidate,
    current: PublishedReIndex | None,
    generation: int,
) -> tuple[
    PublicationTransaction,
    int | None,
    WorkspaceSourceDeclarations | None,
]:
    stage_root = paths.staging / candidate.run_id
    journal = stage_root / "rollback-journal.json"
    if journal.is_file():
        journal_data = _read_json(journal)
        if journal_data.get("status") in {"replacing", "rolling_back"}:
            raise RePublicationError(f"unfinished publication transaction exists: {journal}")
    if stage_root.exists():
        shutil.rmtree(stage_root)
    new_root = stage_root / "new"
    rollback_root = stage_root / "rollback"
    new_root.mkdir(parents=True)
    rollback_root.mkdir(parents=True)

    source_records: dict[str, dict[str, Any]] = {}
    if current:
        source_records.update(
            source_id_to_json(source)
            for source in current.sources.values()
        )

    operations: list[PublicationOperation] = []
    changed_source_ids = set(candidate.refreshed_sources + candidate.empty_sources)
    preserve_reused_sources = bool(
        candidate.plan.policy == "target-only" and candidate.plan.target_source
    )
    if current:
        reused_source_ids = (
            set(current.sources)
            - changed_source_ids
            - set(candidate.removed_sources)
        )
        for source_id in sorted(reused_source_ids):
            source = current.sources[source_id]
            durable_source = new_root / "re" / "sources" / source_id
            shutil.copytree(
                workspace_root / "re" / "sources" / source_id,
                durable_source,
            )
            if preserve_reused_sources:
                continue
            topology_removed = _strip_legacy_topology_artifacts(durable_source)
            if source.manifest_artifact is None or topology_removed:
                manifest_path = durable_source / "manifest.json"
                manifest = _read_json(manifest_path)
                manifest["artifacts"] = [
                    descriptor.to_json_dict()
                    for descriptor in build_re_artifact_catalog(
                        durable_source,
                        published_prefix=PurePosixPath(
                            f"re/sources/{source_id}"
                        ),
                        scope="source",
                        source_id=source_id,
                    )
                ]
                write_json_atomic(manifest_path, manifest)
                source_records[source_id]["manifest_artifact"] = (
                    _manifest_artifact(
                        manifest_path,
                        PurePosixPath(
                            f"re/sources/{source_id}/manifest.json"
                        ),
                        scope="source",
                        source_id=source_id,
                    ).to_json_dict()
                )
                operations.append(
                    _operation(
                        stage_root,
                        f"sources/{source_id}",
                        staged=f"new/re/sources/{source_id}",
                    )
                )

    for source_id in candidate.removed_sources:
        source_records.pop(source_id, None)
        operations.append(
            _operation(stage_root, f"sources/{source_id}", staged=None)
        )

    plan_by_id = {source.id: source for source in candidate.plan.sources}
    for source_id in sorted(candidate.refreshed_sources + candidate.empty_sources):
        source = plan_by_id[source_id]
        durable_source = new_root / "re" / "sources" / source_id
        cache_relative = f".cache/sources/{source_id}/{source.fingerprint.value}"
        domain_manifest = None
        supporting_artifacts = None
        extraction_artifacts: dict[str, str] = {}
        if source_id in candidate.empty_sources:
            durable_source.mkdir(parents=True)
            (durable_source / "overview.md").write_text(
                f"# {source_id}\n\n"
                f"Source path: `{source.path}`\n\n"
                "No analyzable source files were present for this generation.\n",
                encoding="utf-8",
            )
            for name, title in (
                ("architecture.md", "Architecture"),
                ("contracts.md", "Contracts"),
                ("components.md", "Components"),
            ):
                (durable_source / name).write_text(
                    f"# {title}\n\n"
                    f"Source path: `{source.path}`\n\n"
                    "No analyzable source files were present for this generation.\n",
                    encoding="utf-8",
                )
            specs: list[str] = []
            source_status = "empty"
        else:
            staged_source = candidate.run_dir / "re" / "sources" / source_id
            durable_source.mkdir(parents=True)
            shutil.copy2(staged_source / "overview.md", durable_source / "overview.md")
            shutil.copy2(staged_source / "architecture.md", durable_source / "architecture.md")
            shutil.copy2(staged_source / "contracts.md", durable_source / "contracts.md")
            shutil.copy2(staged_source / "components.md", durable_source / "components.md")
            if (staged_source / "adrs").is_dir():
                shutil.copytree(staged_source / "adrs", durable_source / "adrs")
            staged_specs = staged_source / "specs"
            if staged_specs.is_dir():
                shutil.copytree(staged_specs, durable_source / "specs")
            else:
                (durable_source / "specs").mkdir()
            domain_manifest = _copy_optional_source_artifact(
                staged_source,
                durable_source,
                source_id,
                "domain-manifest.json",
            )
            supporting_artifacts = _copy_optional_source_artifact(
                staged_source,
                durable_source,
                source_id,
                "supporting-artifacts.md",
            )
            extraction_artifacts = _copy_optional_source_artifacts(
                staged_source,
                durable_source,
                source_id,
                {
                    "analysis": "analysis.json",
                    "configs": "configs.json",
                    "dependencies": "dependencies.json",
                    "structure": "structure.json",
                },
            )
            specs = [
                f"re/sources/{source_id}/{path.relative_to(durable_source).as_posix()}"
                for path in sorted((durable_source / "specs").glob("*/spec.md"))
            ]
            source_status = (
                "partial" if source_id in candidate.partial_sources else "complete"
            )
            cache_stage = new_root / "re" / cache_relative
            _copy_heavy_source_artifacts(staged_source, cache_stage)
            write_json_atomic(
                cache_stage / "cache-manifest.json",
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "fingerprint": source.fingerprint.value,
                    "profile_hash": source.fingerprint.profile_hash,
                },
            )
            operations.append(
                _operation(stage_root, cache_relative, staged=f"new/re/{cache_relative}")
            )

        manifest = _source_manifest(
            source,
            candidate.plan,
            status=source_status,
            cache_path=f"re/{cache_relative}",
            specs=specs,
            domain_manifest=domain_manifest,
            supporting_artifacts=supporting_artifacts,
            extraction_artifacts=extraction_artifacts,
            artifacts=[
                descriptor.to_json_dict()
                for descriptor in build_re_artifact_catalog(
                    durable_source,
                    published_prefix=PurePosixPath(f"re/sources/{source_id}"),
                    scope="source",
                    source_id=source_id,
                )
            ],
        )
        write_json_atomic(durable_source / "manifest.json", manifest)
        source_records[source_id] = _index_source_record(
            source,
            source_status,
            manifest_artifact=_manifest_artifact(
                durable_source / "manifest.json",
                PurePosixPath(f"re/sources/{source_id}/manifest.json"),
                scope="source",
                source_id=source_id,
            ),
        )
        operations.append(
            _operation(
                stage_root,
                f"sources/{source_id}",
                staged=f"new/re/sources/{source_id}",
            )
        )

    workspace_stage = new_root / "re" / "workspace"
    shutil.copytree(candidate.run_dir / "re" / "workspace", workspace_stage)
    workspace_manifest = {
        "schema_version": 1,
        "generation": generation,
        "sources": [
            {
                "source_id": source_id,
                "fingerprint": record["fingerprint"],
                "profile_hash": record["profile_hash"],
                "status": record["status"],
                "manifest": record["manifest"],
            }
            for source_id, record in sorted(source_records.items())
        ],
        "artifacts": [
            descriptor.to_json_dict()
            for descriptor in build_re_artifact_catalog(
                workspace_stage,
                published_prefix=PurePosixPath("re/workspace"),
                scope="workspace",
            )
        ],
    }
    write_json_atomic(workspace_stage / "manifest.json", workspace_manifest)
    workspace_manifest_artifact = _manifest_artifact(
        workspace_stage / "manifest.json",
        PurePosixPath("re/workspace/manifest.json"),
        scope="workspace",
    )
    operations.append(_operation(stage_root, "workspace", staged="new/re/workspace"))

    controller_state = _read_json(candidate.run_dir / "re" / "state.json")
    execution_profile = controller_state.get("re_execution_profile")
    semantic_audits = controller_state.get("re_semantic_domain_audits")
    index_payload = {
        "schema_version": 1,
        "generation": generation,
        "publication_status": candidate.status,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "published_from_run": candidate.run_id,
        "quality": {
            "semantic_completeness_version": 1,
            "execution_profile": (
                execution_profile.get("name", "legacy")
                if isinstance(execution_profile, dict)
                else "legacy"
            ),
            "semantic_audit_status": (
                "evaluated"
                if isinstance(semantic_audits, dict) and semantic_audits
                else "not-evaluated"
            ),
            "audited_domain_count": (
                len(semantic_audits) if isinstance(semantic_audits, dict) else 0
            ),
            "blocking_findings": 0,
        },
        "sources": dict(sorted(source_records.items())),
        "workspace": {
            "manifest": "re/workspace/manifest.json",
            "manifest_artifact": workspace_manifest_artifact.to_json_dict(),
            "overview": "re/workspace/overview.md",
            "relationships": "re/workspace/relationships.md",
            "contracts": "re/workspace/contracts.md",
        },
        "warnings": list(candidate.warnings),
    }
    staged_index = new_root / "re" / "index.json"
    write_json_atomic(staged_index, index_payload)
    operations.append(_operation(stage_root, "index.json", staged="new/re/index.json"))
    try:
        declarations = load_workspace_source_declarations(workspace_root)
        if preserve_reused_sources:
            declarations = _require_explicit_source_declarations(declarations)
            _validate_targeted_topology_declarations(declarations)
            configured_sources = declarations.source_paths
        else:
            configured_sources = {
                source.id: source.path
                for source in discover_workspace(workspace_root).sources
            }
        configured_ids = set(configured_sources)
        topology_current = load_topology_index(
            workspace_root,
            allow_removed_source_ids=candidate.removed_sources,
        )
        required_topology_sources = tuple(
            sorted(
                configured_ids
                & set(candidate.refreshed_sources + candidate.empty_sources)
            )
        )
        topology_candidates = _topology_candidates(
            candidate,
            configured_ids,
            migrate_legacy=(
                topology_current is None and not preserve_reused_sources
            ),
            workspace_root=workspace_root,
        )
        unavailable_bootstrap = bool(
            topology_current is None and preserve_reused_sources
        )
        if unavailable_bootstrap:
            topology_candidates = _bootstrap_targeted_topology_candidates(
                workspace_root,
                candidate,
                current,
                configured_ids,
                topology_candidates,
            )
        topology = stage_topology_snapshots(
            workspace_root,
            stage_root,
            topology_candidates,
            removed_source_ids=candidate.removed_sources,
            required_source_ids=required_topology_sources,
            allow_unavailable_bootstrap=unavailable_bootstrap,
            configured_sources=configured_sources,
        )
    except (
        TopologyEvidenceError,
        TopologyPublicationValidationError,
        TopologyRegistryError,
    ) as exc:
        raise RePublicationValidationError(f"topology evidence is not publishable: {exc}") from exc
    if topology is not None:
        operations.extend(topology.operations)
    transaction = PublicationTransaction(
        workspace_root=paths.root,
        staging_root=stage_root,
        journal=journal,
        operations=tuple(operations),
        expected_generation=generation,
    )
    try:
        _validate_prepared_publication(new_root)
    except Exception:
        shutil.rmtree(stage_root)
        raise
    write_publication_journal(transaction, "prepared")
    return (
        transaction,
        topology.generation if topology is not None else None,
        declarations if preserve_reused_sources else None,
    )


def _apply_transaction(
    transaction: PublicationTransaction,
    registry: ReRegistryPaths,
    *,
    topology_generation: int | None,
    declaration_snapshot: WorkspaceSourceDeclarations | None,
    fault_hook: Callable[[str], None] | None,
) -> None:
    def hook(point: str) -> None:
        if fault_hook is None:
            return
        if point == "before_operation:index.json":
            fault_hook("before_index_replace")
        elif point == "after_replace:index.json":
            fault_hook("after_index_replace")
        else:
            # Keep the established semantic aliases while exposing the shared
            # transaction's topology operation points to fault-injection tests.
            fault_hook(point)

    if declaration_snapshot is not None:
        try:
            _validate_declaration_snapshot(registry.root.parent, declaration_snapshot)
        except Exception:
            shutil.rmtree(transaction.staging_root)
            raise
    try:
        apply_publication_transaction(transaction, fault_hook=hook)
    except Exception:
        # The transaction applies its normal digest-protected rollback here.
        raise
    try:
        if declaration_snapshot is not None:
            _validate_declaration_snapshot(registry.root.parent, declaration_snapshot)
        published = PublishedReIndex.from_path(registry.index)
        if (
            transaction.expected_generation is not None
            and published.generation != transaction.expected_generation
        ):
            raise RePublicationError(
                "installed RE index generation does not match transaction"
            )
        if topology_generation is not None:
            topology = (
                _load_topology_index_for_configured_sources(
                    registry.root.parent,
                    declaration_snapshot.source_paths,
                )
                if declaration_snapshot is not None
                else load_topology_index(registry.root.parent)
            )
            if topology is None or topology.generation != topology_generation:
                raise RePublicationError(
                    "installed topology generation does not match transaction"
                )
            # Re-hash provider bytes from the already validated immutable index.
            load_published_topology_from_index(registry.root.parent, topology)
    except Exception:
        # This is the narrow post-install validation window. The same fixed
        # claim is still held, every operation is journaled as installed, and
        # only current topology finals may be force-restored from their backups.
        # Ordinary rollback/recovery retains Task 5's strict digest ownership.
        rollback_publication_transaction(
            transaction,
            _active_validation_owned_finals=frozenset(
                operation.final
                for operation in transaction.operations
                if operation.final.parts and operation.final.parts[0] == "topology"
            ),
        )
        raise
    shutil.rmtree(transaction.staging_root)


def _validate_declaration_snapshot(
    workspace_root: Path,
    expected: WorkspaceSourceDeclarations,
) -> None:
    try:
        observed = load_workspace_source_declarations(workspace_root)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise RePublicationValidationError(
            "workspace source declarations changed during publication"
        ) from exc
    if observed != expected:
        raise RePublicationValidationError(
            "workspace source declarations changed during publication"
        )


def _operation(stage_root: Path, final: str, *, staged: str | None) -> PublicationOperation:
    del stage_root
    return PublicationOperation(
        PurePosixPath(final), PurePosixPath(staged) if staged is not None else None
    )


def _validate_prepared_publication(workspace_root: Path) -> None:
    try:
        index = PublishedReIndex.from_path(workspace_root / "re" / "index.json")
    except ReRegistryError as exc:
        raise RePublicationValidationError(
            f"staged RE index is invalid: {exc}"
        ) from exc

    for source_id, source in sorted(index.sources.items()):
        if source.manifest_artifact is None:
            raise RePublicationValidationError(
                f"source manifest_artifact is missing: {source_id}"
            )
        source_dir = workspace_root / "re" / "sources" / source_id
        _validate_artifact_catalog(
            _read_json(source_dir / "manifest.json"),
            directory=source_dir,
            workspace_root=workspace_root,
            published_prefix=PurePosixPath(f"re/sources/{source_id}"),
            scope="source",
            source_id=source_id,
        )

    if index.workspace.manifest_artifact is None:
        raise RePublicationValidationError("workspace manifest_artifact is missing")
    workspace_dir = workspace_root / "re" / "workspace"
    _validate_artifact_catalog(
        _read_json(workspace_dir / "manifest.json"),
        directory=workspace_dir,
        workspace_root=workspace_root,
        published_prefix=PurePosixPath("re/workspace"),
        scope="workspace",
        source_id=None,
    )


def _validate_artifact_catalog(
    manifest: dict[str, Any],
    *,
    directory: Path,
    workspace_root: Path,
    published_prefix: PurePosixPath,
    scope: str,
    source_id: str | None,
) -> None:
    raw_artifacts = manifest.get("artifacts")
    if not isinstance(raw_artifacts, list):
        raise RePublicationValidationError("artifact catalog must be a list")

    paths: list[str] = []
    seen_paths: set[str] = set()
    for raw in raw_artifacts:
        try:
            descriptor = validate_re_artifact_descriptor(
                raw,
                workspace_root=workspace_root,
                owner_scope=scope,
                owner_source_id=source_id,
            )
            expected_kind = classify_re_artifact(
                PurePosixPath(descriptor.path),
                scope=scope,
            )
        except ReArtifactCatalogError as exc:
            raise RePublicationValidationError(str(exc)) from exc
        if descriptor.path in seen_paths:
            raise RePublicationValidationError(
                f"duplicate artifact path: {descriptor.path}"
            )
        if descriptor.kind != expected_kind:
            raise RePublicationValidationError(
                f"artifact kind does not match path: {descriptor.path}"
            )
        seen_paths.add(descriptor.path)
        paths.append(descriptor.path)

    if paths != sorted(paths):
        raise RePublicationValidationError("artifact catalog paths are not sorted")
    expected_paths = {
        (published_prefix / path.relative_to(directory).as_posix()).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() != "manifest.json"
    }
    if seen_paths != expected_paths or len(paths) != len(expected_paths):
        raise RePublicationValidationError(
            "catalog inventory does not match durable files"
        )


def _validate_source_index(path: Path, plan: ReExecutionPlan) -> None:
    data = _read_json(path)
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list):
        raise RePublicationValidationError("re-source-index sources must be a list")
    actual = {
        entry.get("id"): entry
        for entry in raw_sources
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    if len(actual) != len(raw_sources) or set(actual) != {source.id for source in plan.sources}:
        raise RePublicationValidationError("re-source-index source IDs do not match plan")
    for source in plan.sources:
        entry = actual[source.id]
        serialized = source.to_json_dict()
        for key in (
            "path",
            "absolute_path",
            "action",
            "cache_path",
            "dirty",
            "selected",
            "classification",
        ):
            if entry.get(key) != serialized[key]:
                raise RePublicationValidationError(
                    f"re-source-index {key} mismatch for {source.id}"
                )
        if entry.get("fingerprint") != source.fingerprint.to_json_dict():
            raise RePublicationValidationError(
                f"re-source-index fingerprint mismatch for {source.id}"
            )


def _validate_workspace_inputs(path: Path, plan: ReExecutionPlan) -> None:
    data = _read_json(path)
    if data.get("schema_version") != 1:
        raise RePublicationValidationError("unsupported workspace input schema")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list):
        raise RePublicationValidationError("workspace inputs sources must be a list")
    actual = {
        entry.get("id"): entry
        for entry in raw_sources
        if isinstance(entry, dict) and isinstance(entry.get("id"), str)
    }
    expected_ids = {source.id for source in plan.sources} | set(plan.removed_sources)
    if len(actual) != len(raw_sources) or set(actual) != expected_ids:
        raise RePublicationValidationError("workspace input source IDs do not match plan")
    for source in plan.sources:
        entry = actual[source.id]
        if entry.get("decision") != source.classification:
            raise RePublicationValidationError(
                f"workspace input decision mismatch for {source.id}"
            )
        if entry.get("fingerprint") != source.fingerprint.value:
            raise RePublicationValidationError(
                f"workspace input fingerprint mismatch for {source.id}"
            )
        if entry.get("profile_hash") != source.fingerprint.profile_hash:
            raise RePublicationValidationError(
                f"workspace input profile hash mismatch for {source.id}"
            )
        if entry.get("source_path") != source.path:
            raise RePublicationValidationError(
                f"workspace input source path mismatch for {source.id}"
            )
        run_id = path.parent.parent.name
        expected_input = (
            f"runs/{run_id}/re/sources/{source.id}"
            if source.action in {"refresh", "skip-empty"}
            else f"re/sources/{source.id}/manifest.json"
        )
        if entry.get("input_path") != expected_input:
            raise RePublicationValidationError(
                f"workspace input path mismatch for {source.id}"
            )
    for source_id in plan.removed_sources:
        if actual[source_id].get("decision") != "removed":
            raise RePublicationValidationError(
                f"workspace input removal mismatch for {source_id}"
            )


def _validate_refreshed_source(
    source_dir: Path,
    source: RePlanSource,
) -> None:
    if not (source_dir / "analysis.json").is_file():
        raise RePublicationValidationError(
            f"required source analysis missing: {source_dir / 'analysis.json'}"
        )
    if not (source_dir / "overview.md").is_file():
        raise RePublicationValidationError(
            f"required source overview missing: {source_dir / 'overview.md'}"
        )
    for name in ("architecture.md", "contracts.md", "components.md"):
        path = source_dir / name
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise RePublicationValidationError(
                f"required source synthesis missing: {path}"
            )


def _raise_quality_failure(failure: ReSpecQualityFailure) -> None:
    missing = ", ".join(failure.missing_sections) or "none"
    raise RePublicationValidationError(
        "shallow reverse-engineering spec is not publishable: "
        f"{failure.spec_path}; missing sections: {missing}; source evidence: "
        f"{failure.source_evidence_count}/{MINIMUM_SOURCE_EVIDENCE}"
    )


def _validate_current_source(
    source: RePlanSource,
    current: PublishedReIndex | None,
) -> None:
    if current is None or source.id not in current.sources:
        raise RePublicationValidationError(
            f"source {source.id} has no current published result"
        )
    published = current.sources[source.id]
    if (
        published.fingerprint != source.fingerprint.value
        or published.profile_hash != source.fingerprint.profile_hash
    ):
        raise RePublicationValidationError(
            f"current source fingerprint/profile mismatch for {source.id}"
        )


def _validate_target_source_available(
    workspace_root: Path,
    plan: ReExecutionPlan,
) -> None:
    if plan.policy != "target-only" or not plan.target_source:
        return
    planned = next(
        (source for source in plan.sources if source.id == plan.target_source),
        None,
    )
    try:
        declarations = _require_explicit_source_declarations(
            load_workspace_source_declarations(workspace_root)
        )
        _validate_targeted_topology_declarations(declarations)
        declared_path = declarations.source_paths.get(plan.target_source)
    except (OSError, ValueError) as exc:
        raise RePublicationValidationError(
            f"cannot resolve selected source {plan.target_source}: {exc}"
        ) from exc
    if planned is None or declared_path != planned.path:
        raise RePublicationValidationError(
            f"selected source {plan.target_source} is no longer declared"
        )
    source_path = Path(declared_path)
    if not source_path.is_absolute():
        source_path = workspace_root / source_path
    if not source_path.exists():
        raise RePublicationValidationError(
            f"selected source {plan.target_source} is unavailable: {source_path}"
        )


def _require_explicit_source_declarations(
    declarations: WorkspaceSourceDeclarations | None,
) -> WorkspaceSourceDeclarations:
    if declarations is None or declarations.mode != "explicit":
        raise RePublicationValidationError(
            "targeted refresh requires explicitly declared workspace sources; "
            "declare every source in the canonical or legacy workspace config"
        )
    return declarations


def _validate_targeted_topology_declarations(
    declarations: WorkspaceSourceDeclarations,
) -> None:
    try:
        validate_topology_source_declarations(declarations.sources)
    except ValueError as exc:
        raise RePublicationValidationError(str(exc)) from exc


def _bootstrap_targeted_topology_candidates(
    workspace_root: Path,
    candidate: RePublicationCandidate,
    current: PublishedReIndex | None,
    configured_source_ids: set[str],
    selected_candidates: tuple[TopologySnapshotCandidate, ...],
) -> tuple[TopologySnapshotCandidate, ...]:
    """Complete an absent topology authority from durable semantic identities."""
    candidates = {item.source_id: item for item in selected_candidates}
    planned = {source.id: source for source in candidate.plan.sources}
    for source_id in sorted(configured_source_ids - set(candidates)):
        source = planned.get(source_id)
        published = current.sources.get(source_id) if current is not None else None
        if (
            source is None
            or source.action != "reuse"
            or published is None
            or published.source_path != source.path
            or published.fingerprint != source.fingerprint.value
            or published.profile_hash != source.fingerprint.profile_hash
            or published.status not in {"complete", "empty", "partial"}
            or not published_source_is_usable(
                workspace_root,
                current,
                source_id,
            )
        ):
            raise TopologyPublicationValidationError(
                "cannot bootstrap topology without a usable durable semantic "
                f"baseline for sibling source: {source_id}"
            )
        candidates[source_id] = TopologySnapshotCandidate(
            source_id=source_id,
            source_path=source.path,
            source_fingerprint=source.fingerprint,
            analyzed_commit=source.fingerprint.git_head,
            provenance={"kind": "re", "run_id": candidate.run_id},
            providers=(
                TopologyProviderCandidate(
                    provider="codegraph",
                    unavailable_reason={
                        "kind": "bootstrap",
                        "message": (
                            "topology unavailable until this source is explicitly refreshed"
                        ),
                    },
                ),
            ),
        )
    if set(candidates) != configured_source_ids:
        raise TopologyPublicationValidationError(
            "targeted topology bootstrap does not cover every configured source"
        )
    return tuple(candidates[source_id] for source_id in sorted(candidates))


def _topology_candidates(
    candidate: RePublicationCandidate,
    configured_source_ids: set[str],
    *,
    migrate_legacy: bool,
    workspace_root: Path,
) -> tuple[TopologySnapshotCandidate, ...]:
    """Capture only the provider artifacts explicitly emitted for refreshed sources."""
    plan_by_id = {source.id: source for source in candidate.plan.sources}
    provenance = {"kind": "re", "run_id": candidate.run_id}
    snapshots: list[TopologySnapshotCandidate] = []
    for source_id in candidate.refreshed_sources:
        if source_id not in configured_source_ids:
            continue
        source = plan_by_id[source_id]
        output = candidate.run_dir / "re" / "sources" / source_id
        paths = {
            provider: ProviderArtifactPaths(
                owner_dir=output,
                analysis=output / f"{provider}-analysis.json",
                summary=output / f"{provider}-summary.json",
                error=output / f"{provider}-error.json",
            )
            for provider in ("codegraph", "perlgraph")
        }
        try:
            snapshots.append(
                build_topology_snapshot_candidate(
                    source.id,
                    source.path,
                    source.fingerprint,
                    paths,
                    provenance,
                ).candidate
            )
        except TopologyEvidenceError as exc:
            if "no usable provider evidence" in str(exc):
                raise TopologyEvidenceError(
                    f"no usable topology evidence for refreshed source: {source.id}"
                ) from exc
            raise
    for source_id in candidate.empty_sources:
        if source_id not in configured_source_ids:
            continue
        source = plan_by_id[source_id]
        snapshots.append(
            build_empty_topology_snapshot_candidate(
                source.id,
                source.path,
                source.fingerprint,
                provenance,
            ).candidate
        )
    if migrate_legacy:
        for source in candidate.plan.sources:
            if source.action != "reuse" or source.id not in configured_source_ids:
                continue
            output = workspace_root / "re" / "sources" / source.id
            try:
                manifest = _read_json(output / "manifest.json")
            except (OSError, json.JSONDecodeError):
                continue
            if not _legacy_manifest_matches_source(manifest, source):
                continue
            paths = {
                provider: ProviderArtifactPaths(
                    owner_dir=output,
                    analysis=output / f"{provider}-analysis.json",
                    summary=output / f"{provider}-summary.json",
                    error=output / f"{provider}-error.json",
                )
                for provider in ("codegraph", "perlgraph")
            }
            if not any(
                path.is_file()
                for artifact in paths.values()
                for path in (artifact.analysis, artifact.summary)
            ):
                continue
            if is_historical_codegraph_v1_artifact(paths["codegraph"]):
                upgraded = upgrade_legacy_codegraph_candidate(
                    source.id,
                    source.path,
                    source.fingerprint,
                    paths["codegraph"],
                    provenance,
                )
                if upgraded is not None:
                    providers = list(upgraded.candidate.providers)
                    if _provider_schema_version(paths["perlgraph"]) == 2:
                        try:
                            perl_evidence = build_topology_snapshot_candidate(
                                source.id,
                                source.path,
                                source.fingerprint,
                                {"perlgraph": paths["perlgraph"]},
                                provenance,
                            )
                        except TopologyEvidenceError:
                            continue
                        providers.extend(perl_evidence.candidate.providers)
                    snapshots.append(
                        TopologySnapshotCandidate(
                            source_id=upgraded.candidate.source_id,
                            source_path=upgraded.candidate.source_path,
                            source_fingerprint=upgraded.candidate.source_fingerprint,
                            analyzed_commit=upgraded.candidate.analyzed_commit,
                            provenance=upgraded.candidate.provenance,
                            providers=tuple(sorted(providers, key=lambda item: item.provider)),
                        )
                    )
                continue
            if not _all_present_schema_two(paths):
                continue
            try:
                snapshots.append(
                    build_topology_snapshot_candidate(
                        source.id,
                        source.path,
                        source.fingerprint,
                        paths,
                        provenance,
                    ).candidate
                )
            except TopologyEvidenceError:
                # Reused legacy bytes are optional migration evidence. Their
                # corruption cannot invalidate an independently valid semantic RE.
                continue
    return tuple(snapshots)


def _legacy_manifest_matches_source(manifest: object, source: RePlanSource) -> bool:
    """Authenticate old provider bytes against every semantic capture field."""
    if not isinstance(manifest, dict):
        return False
    fingerprint = source.fingerprint
    inferred_kind = "git" if manifest.get("git_head") is not None else "file-tree"
    return (
        manifest.get("source_id") == source.id
        and manifest.get("source_path") == source.path
        and manifest.get("source_fingerprint") == fingerprint.value
        and manifest.get("profile_hash") == fingerprint.profile_hash
        and manifest.get("dirty") is fingerprint.dirty
        and inferred_kind == fingerprint.kind
        and manifest.get("git_head") == fingerprint.git_head
    )


def _all_present_schema_two(paths: dict[str, ProviderArtifactPaths]) -> bool:
    """Schema-1 graph data is intentionally not guessed into exact topology."""
    for artifact in paths.values():
        if not artifact.analysis.is_file() or not artifact.summary.is_file():
            continue
        try:
            data = json.loads(artifact.analysis.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        if isinstance(data, dict) and data.get("schema_version") != 2:
            return False
    return True


def _provider_schema_version(paths: ProviderArtifactPaths) -> int | None:
    if not paths.analysis.is_file() or not paths.summary.is_file():
        return None
    try:
        data = json.loads(paths.analysis.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("schema_version") if isinstance(data, dict) else None


def _strip_legacy_topology_artifacts(source_dir: Path) -> bool:
    """Remove provider files from a semantic source copy before recataloguing it."""
    changed = False
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file() or not is_topology_provider_artifact(
            PurePosixPath(path.relative_to(source_dir).as_posix())
        ):
            continue
        path.unlink()
        changed = True
    if not changed:
        return False
    manifest = _read_json(source_dir / "manifest.json")
    manifest.pop("codegraph_summary", None)
    manifest.pop("codegraph_analysis", None)
    manifest.pop("perlgraph_summary", None)
    manifest.pop("perlgraph_analysis", None)
    write_json_atomic(source_dir / "manifest.json", manifest)
    return True


def _source_manifest(
    source: RePlanSource,
    plan: ReExecutionPlan,
    *,
    status: str,
    cache_path: str,
    specs: list[str],
    artifacts: list[dict[str, str]],
    domain_manifest: str | None = None,
    supporting_artifacts: str | None = None,
    extraction_artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": 1,
        "source_id": source.id,
        "source_path": source.path,
        "source_fingerprint": source.fingerprint.value,
        "git_head": source.fingerprint.git_head,
        "dirty": source.fingerprint.dirty,
        "profile": plan.profile.to_json_dict(),
        "profile_hash": source.fingerprint.profile_hash,
        "quality_contract_version": QUALITY_CONTRACT_VERSION,
        "publication_status": status,
        "cache_path": cache_path,
        "overview": f"re/sources/{source.id}/overview.md",
        "architecture": f"re/sources/{source.id}/architecture.md",
        "contracts": f"re/sources/{source.id}/contracts.md",
        "components": f"re/sources/{source.id}/components.md",
        "specs": specs,
        "artifacts": artifacts,
        "warnings": [],
    }
    if domain_manifest:
        manifest["domain_manifest"] = domain_manifest
    if supporting_artifacts:
        manifest["supporting_artifacts"] = supporting_artifacts
    if extraction_artifacts:
        manifest["extraction_artifacts"] = dict(sorted(extraction_artifacts.items()))
    return manifest


def _index_source_record(
    source: RePlanSource,
    status: str,
    *,
    manifest_artifact: ReArtifactDescriptor,
) -> dict[str, Any]:
    return {
        "path": source.path,
        "published_path": f"re/sources/{source.id}",
        "fingerprint": source.fingerprint.value,
        "profile_hash": source.fingerprint.profile_hash,
        "status": status,
        "manifest": f"re/sources/{source.id}/manifest.json",
        "manifest_artifact": manifest_artifact.to_json_dict(),
    }


def source_id_to_json(source: PublishedSource) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "path": source.source_path,
        "published_path": source.published_path,
        "fingerprint": source.fingerprint,
        "profile_hash": source.profile_hash,
        "status": source.status,
        "manifest": source.manifest,
    }
    if source.manifest_artifact is not None:
        payload["manifest_artifact"] = source.manifest_artifact.to_json_dict()
    return source.source_id, payload


def _manifest_artifact(
    path: Path,
    published_path: PurePosixPath,
    *,
    scope: str,
    source_id: str | None = None,
) -> ReArtifactDescriptor:
    return ReArtifactDescriptor(
        kind=classify_re_artifact(published_path, scope=scope),
        path=published_path.as_posix(),
        sha256="sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        scope=scope,
        source_id=source_id,
    )


def _copy_heavy_source_artifacts(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative.parts[0] == "specs" or relative.as_posix() in {
            "overview.md",
            "architecture.md",
            "contracts.md",
            "components.md",
            "manifest.json",
            "codegraph-analysis.json",
            "codegraph-summary.json",
            "perlgraph-analysis.json",
            "perlgraph-summary.json",
        } or relative.parts[0] == "adrs":
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _copy_optional_source_artifact(
    staged_source: Path,
    durable_source: Path,
    source_id: str,
    filename: str,
) -> str | None:
    source = staged_source / filename
    if not source.is_file():
        return None
    shutil.copy2(source, durable_source / filename)
    return f"re/sources/{source_id}/{filename}"


def _copy_optional_source_artifacts(
    staged_source: Path,
    durable_source: Path,
    source_id: str,
    filenames: dict[str, str],
) -> dict[str, str]:
    return {
        key: path
        for key, filename in filenames.items()
        if (
            path := _copy_optional_source_artifact(
                staged_source,
                durable_source,
                source_id,
                filename,
            )
        )
    }


def _inside_run_roots(workspace_root: Path, run_dir: Path) -> bool:
    return any(
        run_dir.is_relative_to((workspace_root / base).resolve())
        for base in ("runs", "squad")
    )


def _read_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            raise RePublicationValidationError(f"required publication input missing: {path}")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RePublicationValidationError(f"cannot read publication input {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RePublicationValidationError(f"publication input must be an object: {path}")
    return raw
