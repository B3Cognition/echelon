"""Validation and atomic publication of workspace reverse-engineering artifacts."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Literal

from harness.re_architecture import validate_re_architecture_catalog
from harness.re_lock import (
    RePublishLock,
    RePublishRecoveryRequired,
    recover_stale_publish_lock,
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
        if expected_generation is not None and current_generation != expected_generation:
            raise RePublicationConflict(
                f"expected generation {expected_generation}, found {current_generation}"
            )
        generation = current_generation + 1
        transaction = _prepare_transaction(root, paths, candidate, current, generation)
        _apply_transaction(transaction, paths, fault_hook=fault_hook)
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
    if owner is None:
        return False
    run_id = str(owner["run_id"])
    paths = ensure_re_layout(root)
    stage_root = paths.staging / run_id
    journal = stage_root / "rollback-journal.json"
    data = _read_json(journal)
    if data.get("status") != "replacing":
        return recover_stale_publish_lock(
            root,
            stale_after_seconds=stale_after_seconds,
        )
    operations = _validated_journal_operations(data.get("operations"))
    transaction = _Transaction(root=stage_root, journal=journal, operations=operations)
    _rollback_transaction(transaction, paths.root)
    if not recover_stale_publish_lock(root, stale_after_seconds=stale_after_seconds):
        raise RePublishRecoveryRequired("stale publication lock could not be released")
    shutil.rmtree(stage_root)
    return True


@dataclass
class _Transaction:
    root: Path
    journal: Path
    operations: list[dict[str, Any]]
    expected_generation: int | None = None


def _prepare_transaction(
    workspace_root: Path,
    paths: ReRegistryPaths,
    candidate: RePublicationCandidate,
    current: PublishedReIndex | None,
    generation: int,
) -> _Transaction:
    stage_root = paths.staging / candidate.run_id
    journal = stage_root / "rollback-journal.json"
    if journal.is_file():
        journal_data = _read_json(journal)
        if journal_data.get("status") == "replacing":
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

    operations: list[dict[str, Any]] = []
    for source_id in candidate.removed_sources:
        source_records.pop(source_id, None)
        operations.append(
            _operation(stage_root, f"sources/{source_id}", staged=None)
        )

    plan_by_id = {source.id: source for source in candidate.plan.sources}
    for source_id in sorted(candidate.refreshed_sources + candidate.empty_sources):
        source = plan_by_id[source_id]
        durable_source = new_root / "sources" / source_id
        cache_relative = f".cache/sources/{source_id}/{source.fingerprint.value}"
        if source_id in candidate.empty_sources:
            durable_source.mkdir(parents=True)
            (durable_source / "overview.md").write_text(
                f"# {source_id}\n\n"
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
            shutil.copytree(staged_source / "specs", durable_source / "specs")
            specs = [
                f"re/sources/{source_id}/{path.relative_to(durable_source).as_posix()}"
                for path in sorted((durable_source / "specs").glob("*/spec.md"))
            ]
            source_status = (
                "partial" if source_id in candidate.partial_sources else "complete"
            )
            cache_stage = new_root / cache_relative
            _copy_heavy_source_artifacts(staged_source, cache_stage)
            _write_json_atomic(
                cache_stage / "cache-manifest.json",
                {
                    "schema_version": 1,
                    "source_id": source_id,
                    "fingerprint": source.fingerprint.value,
                    "profile_hash": source.fingerprint.profile_hash,
                },
            )
            operations.append(
                _operation(stage_root, cache_relative, staged=f"new/{cache_relative}")
            )

        manifest = _source_manifest(
            source,
            candidate.plan,
            status=source_status,
            cache_path=f"re/{cache_relative}",
            specs=specs,
        )
        _write_json_atomic(durable_source / "manifest.json", manifest)
        source_records[source_id] = _index_source_record(source, source_status)
        operations.append(
            _operation(
                stage_root,
                f"sources/{source_id}",
                staged=f"new/sources/{source_id}",
            )
        )

    workspace_stage = new_root / "workspace"
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
    }
    _write_json_atomic(workspace_stage / "manifest.json", workspace_manifest)
    operations.append(_operation(stage_root, "workspace", staged="new/workspace"))

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
            "overview": "re/workspace/overview.md",
            "relationships": "re/workspace/relationships.md",
            "contracts": "re/workspace/contracts.md",
        },
        "warnings": list(candidate.warnings),
    }
    _write_json_atomic(new_root / "index.json", index_payload)
    operations.append(_operation(stage_root, "index.json", staged="new/index.json"))
    transaction = _Transaction(
        root=stage_root,
        journal=journal,
        operations=operations,
        expected_generation=generation,
    )
    _write_journal(transaction, "prepared")
    return transaction


def _apply_transaction(
    transaction: _Transaction,
    registry: ReRegistryPaths,
    *,
    fault_hook: Callable[[str], None] | None,
) -> None:
    _write_journal(transaction, "replacing")
    try:
        for operation in transaction.operations[:-1]:
            _apply_operation(transaction, registry.root, operation)
        if fault_hook:
            fault_hook("before_index_replace")
        _apply_operation(transaction, registry.root, transaction.operations[-1])
        if fault_hook:
            fault_hook("after_index_replace")
        published = PublishedReIndex.from_path(registry.index)
        if (
            transaction.expected_generation is not None
            and published.generation != transaction.expected_generation
        ):
            raise RePublicationError(
                "installed RE index generation does not match transaction"
            )
        _write_journal(transaction, "complete")
    except Exception:
        _rollback_transaction(transaction, registry.root)
        raise
    shutil.rmtree(transaction.root)


def _apply_operation(
    transaction: _Transaction,
    registry_root: Path,
    operation: dict[str, Any],
) -> None:
    final = registry_root / operation["final"]
    backup = transaction.root / operation["backup"]
    staged_value = operation.get("staged")
    staged = transaction.root / staged_value if staged_value else None
    if final.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(final, backup)
        operation["backed_up"] = True
        _write_journal(transaction, "replacing")
    if staged is not None:
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged, final)
        operation["installed"] = True
        _write_journal(transaction, "replacing")


def _rollback_transaction(transaction: _Transaction, registry_root: Path) -> None:
    for operation in reversed(transaction.operations):
        final = registry_root / operation["final"]
        backup = transaction.root / operation["backup"]
        if operation.get("installed") and final.exists():
            _remove_path(final)
        if operation.get("backed_up") and backup.exists():
            final.parent.mkdir(parents=True, exist_ok=True)
            os.replace(backup, final)
    _write_journal(transaction, "rolled_back")


def _operation(stage_root: Path, final: str, *, staged: str | None) -> dict[str, Any]:
    del stage_root
    return {
        "final": final,
        "staged": staged,
        "backup": f"rollback/{final}",
        "backed_up": False,
        "installed": False,
    }


def _write_journal(transaction: _Transaction, status: str) -> None:
    _write_json_atomic(
        transaction.journal,
        {
            "schema_version": 1,
            "status": status,
            "operations": transaction.operations,
        },
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


def _source_manifest(
    source: RePlanSource,
    plan: ReExecutionPlan,
    *,
    status: str,
    cache_path: str,
    specs: list[str],
) -> dict[str, Any]:
    return {
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
        "specs": specs,
        "warnings": [],
    }


def _index_source_record(source: RePlanSource, status: str) -> dict[str, Any]:
    return {
        "path": source.path,
        "published_path": f"re/sources/{source.id}",
        "fingerprint": source.fingerprint.value,
        "profile_hash": source.fingerprint.profile_hash,
        "status": status,
        "manifest": f"re/sources/{source.id}/manifest.json",
    }


def source_id_to_json(source: PublishedSource) -> tuple[str, dict[str, Any]]:
    return (
        source.source_id,
        {
            "path": source.source_path,
            "published_path": source.published_path,
            "fingerprint": source.fingerprint,
            "profile_hash": source.profile_hash,
            "status": source.status,
            "manifest": source.manifest,
        },
    )


def _copy_heavy_source_artifacts(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if relative.parts[0] == "specs" or relative.as_posix() in {
            "overview.md",
            "manifest.json",
        }:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        Path(temporary).replace(path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _validated_journal_operations(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise RePublishRecoveryRequired("rollback journal operations must be a list")
    operations: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise RePublishRecoveryRequired("rollback journal operation must be an object")
        final = _safe_transaction_path(entry.get("final"), "final")
        backup = _safe_transaction_path(entry.get("backup"), "backup")
        staged_raw = entry.get("staged")
        staged = (
            _safe_transaction_path(staged_raw, "staged")
            if staged_raw is not None
            else None
        )
        backed_up = entry.get("backed_up")
        installed = entry.get("installed")
        if not isinstance(backed_up, bool) or not isinstance(installed, bool):
            raise RePublishRecoveryRequired(
                "rollback journal operation flags must be booleans"
            )
        operations.append(
            {
                "final": final,
                "backup": backup,
                "staged": staged,
                "backed_up": backed_up,
                "installed": installed,
            }
        )
    return operations


def _safe_transaction_path(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise RePublishRecoveryRequired(f"rollback journal {field} path is malformed")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise RePublishRecoveryRequired(f"rollback journal {field} path is unsafe")
    return path.as_posix()
