"""Build prompt-ready run-local context files for squad Phase A."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import json
import re

from echelon.context_metadata import (
    FeatureMetadata,
    LIFECYCLE_STATUSES,
    RequirementMetadata,
    UseCaseMetadata,
    read_feature_metadata,
)
from echelon.context_reconciliation import reconcile_drawers

MAX_CONTEXT_SNIPPET_CHARS = 3000
CONTEXT_OUTPUT_NAMES = (
    "prior-spec-context.md",
    "current-feature-context.md",
    "feature-registry.snapshot.json",
    "mempalace-reconciliation.json",
    "stale-memory-report.md",
)


@dataclass(frozen=True)
class ContextBuildResult:
    context_dir: Path
    prior_context: Path
    current_context: Path
    feature_registry: Path
    reconciliation_json: Path
    stale_report: Path


def build_run_context(
    project_root: Path,
    run_dir: Path,
    user_request: str = "",
    drawers: Sequence[Any] = (),
    *,
    output_dir: Path | None = None,
) -> ContextBuildResult:
    context_dir = output_dir if output_dir is not None else run_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    canonical_metadata = _canonical_metadata(project_root)
    wip_metadata = _wip_metadata(run_dir)
    reconciliation = reconcile_drawers(drawers, project_root)

    (
        prior_context,
        current_context,
        feature_registry,
        reconciliation_json,
        stale_report,
    ) = (context_dir / name for name in CONTEXT_OUTPUT_NAMES)

    prior_context.write_text(_render_prior(canonical_metadata, reconciliation.accepted), encoding="utf-8")
    current_context.write_text(_render_current(wip_metadata, project_root, run_dir), encoding="utf-8")
    feature_registry.write_text(
        json.dumps(
            {
                "user_request": user_request,
                "features": [m.to_dict() for m in canonical_metadata],
                "wip_features": [m.to_dict() for m in wip_metadata],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    reconciliation_json.write_text(json.dumps(reconciliation.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stale_report.write_text(_render_stale_report(reconciliation.rejected), encoding="utf-8")

    return ContextBuildResult(
        context_dir=context_dir,
        prior_context=prior_context,
        current_context=current_context,
        feature_registry=feature_registry,
        reconciliation_json=reconciliation_json,
        stale_report=stale_report,
    )


def _canonical_metadata(project_root: Path) -> list[FeatureMetadata]:
    result: list[FeatureMetadata] = []
    specs_dir = project_root / "specs"
    for spec_dir in sorted(specs_dir.glob("[0-9][0-9][0-9]-*")):
        if not (spec_dir / "spec.md").exists():
            continue
        metadata = FeatureMetadata.from_spec_dir(spec_dir)
        merged = _merge_existing_metadata(metadata, read_feature_metadata(spec_dir))
        result.append(merged)
    return result


def _wip_metadata(run_dir: Path) -> list[FeatureMetadata]:
    result: list[FeatureMetadata] = []
    specs_dir = run_dir / "specs"
    for spec_dir in sorted(specs_dir.glob("[0-9][0-9][0-9]-*")):
        if not (spec_dir / "spec.md").exists():
            continue
        result.append(FeatureMetadata.from_spec_dir(spec_dir, run_id=run_dir.name))
    return result


def _render_prior(metadata: list[FeatureMetadata], drawers: Sequence[Any]) -> str:
    lines = ["# Prior Spec Context", ""]
    for feature in metadata:
        lines.append(f"## {feature.feature_id}")
        lines.append(f"Status: {feature.status}")
        if feature.use_cases:
            lines.append("### Use Cases")
            for use_case in feature.use_cases:
                lines.append(f"- {use_case.id} ({use_case.status}): {use_case.title}")
            lines.append("")
        if feature.requirements:
            lines.append("### Requirements")
        for req in feature.requirements:
            lines.append(f"- {req.id} ({req.status}) from `{req.artifact_path}`")
        lines.append("")
    if drawers:
        lines.append("## Reconciled MemPalace Results")
        for drawer in drawers:
            label = getattr(drawer, "drawer_id", "unknown")
            content = getattr(drawer, "content", "")
            lines.append(f"- {label}: {content[:300]}")
    return "\n".join(lines).rstrip() + "\n"


def _render_current(metadata: list[FeatureMetadata], project_root: Path, run_dir: Path) -> str:
    lines = ["# Current Feature Context", "", f"Run: `{run_dir.name}`", ""]
    for feature in metadata:
        lines.append(f"## {feature.feature_id}")
        if feature.requirements:
            lines.append("### Requirements")
            for req in feature.requirements:
                lines.append(f"- {req.id} ({req.status})")
                lines.append(_render_staged_content(_requirement_blurb(feature, req.id, project_root), MAX_CONTEXT_SNIPPET_CHARS))
                lines.append("")
        else:
            lines.append("- No requirements extracted from run-local spec.")
    staging = run_dir / "staging"
    if staging.exists():
        lines.append("## Staging Artifacts")
        for path in sorted(staging.glob("*.md")):
            lines.append(f"### {path.name}")
            lines.append(_render_staged_content(_read_text_preview(path), MAX_CONTEXT_SNIPPET_CHARS))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_stale_report(rejected: list[dict[str, str]]) -> str:
    lines = ["# Stale Memory Report", ""]
    if not rejected:
        lines.append("No stale MemPalace drawers were rejected.")
    else:
        for item in rejected:
            lines.append(f"- {item.get('drawer_id', 'unknown')}: {item.get('reason', 'unknown')}")
    return "\n".join(lines).rstrip() + "\n"


def _requirement_blurb(feature: FeatureMetadata, requirement_id: str, project_root: Path) -> str:
    req = next((r for r in feature.requirements if r.id == requirement_id), None)
    if req is None:
        return f"Requirement {requirement_id} was not found in this feature metadata."

    spec_path = Path(req.artifact_path)
    if not spec_path.is_absolute():
        spec_path = project_root / spec_path

    if not spec_path.exists():
        return f"Requirement {requirement_id} is not linked to any run-local spec file."

    return _extract_lines_with(requirement_id, spec_path.read_text(errors="replace"))


def _extract_lines_with(requirement_id: str, text: str) -> str:
    pattern = re.compile(rf"\b{re.escape(requirement_id)}\b")
    matches = [line for line in text.splitlines() if pattern.search(line)]
    if not matches:
        return f"No matching requirement line found for `{requirement_id}`."
    return "\n".join(matches)


def _read_text_preview(path: Path) -> str:
    if not path.exists():
        return f"File `{path.name}` is missing."
    try:
        return path.read_text(errors="replace")
    except OSError:
        return f"Could not read `{path.name}`."


def _render_staged_content(text: str, max_chars: int) -> str:
    trimmed = text if len(text) <= max_chars else text[:max_chars]
    return "\n".join(trimmed.splitlines())


def _merge_existing_metadata(
    current: FeatureMetadata,
    existing: FeatureMetadata | None,
) -> FeatureMetadata:
    if existing is None:
        return current

    current_requirement_ids = {requirement.id for requirement in current.requirements}
    existing_requirements = {requirement.id: requirement for requirement in existing.requirements}
    merged_requirements = [
        _merge_requirement_metadata(requirement, existing_requirements.get(requirement.id))
        for requirement in current.requirements
    ]
    merged_requirements.extend(
        requirement
        for requirement in existing.requirements
        if requirement.id not in current_requirement_ids
        and _has_valid_lifecycle_status(requirement.status)
    )

    current_use_case_ids = {use_case.id for use_case in current.use_cases}
    existing_use_cases = {use_case.id: use_case for use_case in existing.use_cases}
    merged_use_cases = [
        _merge_use_case_metadata(use_case, existing_use_cases.get(use_case.id))
        for use_case in current.use_cases
    ]
    merged_use_cases.extend(
        use_case
        for use_case in existing.use_cases
        if use_case.id not in current_use_case_ids
        and _has_valid_lifecycle_status(use_case.status)
    )

    return FeatureMetadata(
        schema_version=current.schema_version,
        feature_id=current.feature_id,
        spec_id=current.spec_id,
        slug=current.slug,
        status=_preserved_status(existing.status, current.status),
        created_in_run=existing.created_in_run if existing.created_in_run is not None else current.created_in_run,
        last_changed_in_run=existing.last_changed_in_run
        if existing.last_changed_in_run is not None
        else current.last_changed_in_run,
        supersedes=list(existing.supersedes),
        superseded_by=list(existing.superseded_by),
        related_features=list(existing.related_features),
        use_cases=merged_use_cases,
        requirements=merged_requirements,
    )


def _merge_requirement_metadata(
    current: RequirementMetadata,
    existing: RequirementMetadata | None,
) -> RequirementMetadata:
    if existing is None:
        return current
    return RequirementMetadata(
        id=current.id,
        status=_preserved_status(existing.status, current.status),
        artifact_path=current.artifact_path,
        artifact_hash=current.artifact_hash,
        use_cases=list(current.use_cases),
    )


def _merge_use_case_metadata(
    current: UseCaseMetadata,
    existing: UseCaseMetadata | None,
) -> UseCaseMetadata:
    if existing is None:
        return current
    return UseCaseMetadata(
        id=current.id,
        title=current.title,
        status=_preserved_status(existing.status, current.status),
        source_requirements=list(current.source_requirements),
        supersedes=list(existing.supersedes),
        superseded_by=list(existing.superseded_by),
    )


def _preserved_status(existing_status: str, generated_status: str) -> str:
    return existing_status if existing_status in LIFECYCLE_STATUSES else generated_status


def _has_valid_lifecycle_status(status: str) -> bool:
    return status in LIFECYCLE_STATUSES
