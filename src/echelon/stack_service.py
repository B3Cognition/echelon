"""Typed application services for Echelon stack commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from harness.stacks import (
    ProvisioningStatus,
    ResolvedStacks,
    StackDetectionReport,
    StackPreflightResult,
    detect_stacks,
    detection_report_from_file,
    load_stack_definitions,
    provisioning_statuses,
    render_provisioner,
    resolve_stacks,
    run_stack_preflight,
    write_detection_report,
)
from harness import config as harness_config
from harness.stacks.detection import WrittenDetectionReport
from harness.stacks.paths import find_stack_extension_root
from harness.stacks.schema import StackDefinition
from echelon.stack_selection import (
    StackSelection,
    change_stack_selection,
    get_stack_selection,
)


@dataclass(frozen=True)
class StackDetectionOutcome:
    report: StackDetectionReport
    written: WrittenDetectionReport | None


@dataclass(frozen=True)
class StackPreflightOutcome:
    resolved: ResolvedStacks | None
    result: StackPreflightResult | None
    message: str | None = None


@dataclass(frozen=True)
class StackProvisionOutcome:
    target_root: Path
    resolved: ResolvedStacks | None
    generated: list[Path]
    statuses: list[ProvisioningStatus]
    message: str | None = None


def load_stack_catalog(project_root: Path) -> dict[str, StackDefinition]:
    """Load bundled and project-local stack definitions for one workspace."""
    return load_stack_definitions(
        extension_root=find_stack_extension_root(project_root),
        project_root=project_root,
    )


def detect_stack_candidates(
    project_root: Path,
    *,
    target: Path,
    artifact_roots: list[Path],
    write_report: bool,
) -> StackDetectionOutcome:
    """Detect stack evidence and optionally persist its report."""
    report = detect_stacks(
        target=target,
        artifact_roots=artifact_roots,
        stack_definitions=load_stack_catalog(project_root),
    )
    written = (
        write_detection_report(report, project_root=project_root)
        if write_report
        else None
    )
    return StackDetectionOutcome(report=report, written=written)


def preflight_stacks(
    project_root: Path,
    *,
    selected: list[str],
    target_archetypes: list[str],
    from_detection: Path | None,
    target_root: Path | None,
    probe_tools: bool,
    environment: Mapping[str, str],
) -> StackPreflightOutcome:
    """Resolve and preflight the requested stack selection."""
    selected = list(selected)
    target_archetypes = list(target_archetypes)
    if from_detection is not None:
        detected = detection_report_from_file(from_detection)
        detected_selected, detected_archetypes = _selection_from_detection(detected)
        selected = _append_unique(detected_selected, selected)
        target_archetypes = _append_unique(detected_archetypes, target_archetypes)
    elif not selected:
        config = harness_config.load_config(project_root, squad_only=True)
        selected = list(config.stacks.selected)
        target_archetypes = target_archetypes or list(config.stacks.target_archetypes)

    if not selected:
        message = (
            "No adoptable stacks in detection report."
            if from_detection is not None
            else "No Echelon stacks selected. Use --stack <id> or configure stacks.selected."
        )
        return StackPreflightOutcome(resolved=None, result=None, message=message)

    resolved = resolve_stacks(
        selected,
        load_stack_catalog(project_root),
        target_archetypes=set(target_archetypes) or None,
    )
    result = run_stack_preflight(
        resolved,
        probe_tools=probe_tools,
        target_root=target_root or project_root,
        environment=environment,
    )
    return StackPreflightOutcome(resolved=resolved, result=result)


def provision_stacks(
    project_root: Path,
    *,
    selected: list[str],
    target_root: Path,
    force: bool,
    environment: Mapping[str, str],
) -> StackProvisionOutcome:
    """Resolve selected stacks and render missing verification provisioners."""
    selected = list(selected)
    if not selected:
        selected = list(
            harness_config.load_config(project_root, squad_only=True).stacks.selected
        )
    if not selected:
        return StackProvisionOutcome(
            target_root=target_root,
            resolved=None,
            generated=[],
            statuses=[],
            message=(
                "No Echelon stacks selected. Use --stack <id> or configure "
                "stacks.selected."
            ),
        )

    resolved = resolve_stacks(selected, load_stack_catalog(project_root))
    statuses = provisioning_statuses(resolved, target_root, environment)
    generated = _render_missing_provisioners(
        resolved,
        statuses,
        target_root=target_root,
        force=force,
    )
    statuses = provisioning_statuses(resolved, target_root, environment)
    return StackProvisionOutcome(
        target_root=target_root,
        resolved=resolved,
        generated=generated,
        statuses=statuses,
    )


def change_selected_stacks(
    project_root: Path,
    stack_ids: list[str],
    *,
    operation: str,
    dry_run: bool,
) -> StackSelection:
    """Validate and optionally persist one explicit stack-selection change."""
    return change_stack_selection(
        project_root,
        stack_ids,
        load_stack_catalog(project_root),
        operation=operation,
        dry_run=dry_run,
    )


def read_selected_stacks(project_root: Path) -> StackSelection:
    """Return explicit, effective, and resolved stack selection."""
    return get_stack_selection(project_root, load_stack_catalog(project_root))


def _render_missing_provisioners(
    resolved: ResolvedStacks,
    statuses: list[ProvisioningStatus],
    *,
    target_root: Path,
    force: bool,
) -> list[Path]:
    generated: list[Path] = []
    rendered_ids: set[str] = set()
    for item, status in zip(resolved.provisioners, statuses):
        if status.provisioner_id in rendered_ids:
            continue
        if status.state == "ready" or (status.state == "prepared" and not force):
            continue
        generated.extend(render_provisioner(item, target_root, force=force))
        rendered_ids.add(status.provisioner_id)
    return generated


def _selection_from_detection(
    report: StackDetectionReport,
) -> tuple[list[str], list[str]]:
    config = report.suggested_config or {}
    stacks = config.get("stacks", {}) if isinstance(config, dict) else {}
    selected = stacks.get("selected", []) if isinstance(stacks, dict) else []
    target_archetypes = (
        stacks.get("target_archetypes", []) if isinstance(stacks, dict) else []
    )
    return _string_values(selected), _string_values(target_archetypes)


def _string_values(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _append_unique(first: list[str], second: list[str]) -> list[str]:
    result = list(first)
    for value in second:
        if value not in result:
            result.append(value)
    return result


def stack_definition_to_dict(stack: StackDefinition) -> dict[str, Any]:
    """Return the stable machine-readable representation used by the CLI."""
    return {
        "id": stack.id,
        "name": stack.name,
        "version": stack.version,
        "kind": stack.kind,
        "owner": stack.owner,
        "description": stack.description,
        "applies_to_archetypes": stack.applies_to_archetypes,
        "provides": stack.provides,
        "implies": stack.implies,
        "requirements": {
            "commands": stack.requires_commands,
            "registries": stack.requires_registries,
        },
        "detection": stack.detection.to_dict(),
        "tools": sorted(stack.tools),
        "provisioners": [
            {
                "id": provisioner.id,
                "scope": provisioner.scope,
                "services": provisioner.services,
                "environment": {"required": provisioner.required_environment},
                "readiness": {"command": provisioner.readiness_command},
                "satisfiers": [
                    {
                        "kind": satisfier.kind,
                        "variable": satisfier.variable,
                        "output": satisfier.output,
                        "env_example": satisfier.env_example,
                    }
                    for satisfier in provisioner.satisfiers
                ],
            }
            for provisioner in stack.provisioners
        ],
    }
