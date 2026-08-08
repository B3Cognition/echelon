"""Deterministic human-readable map of spec artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from harness.spec_frontmatter import read_frontmatter


@dataclass(frozen=True)
class ArtifactDefinition:
    path: str
    title: str
    purpose: str
    phase: str
    owner: str
    updated_when: str
    audience: str
    required_stage: str | None = None


class RetargetDisposition(str, Enum):
    """Public disposition for a spec-local artifact during a retarget."""

    PRESERVE = "preserve"
    INVALIDATE = "invalidate"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class RetargetArtifactPlan:
    """Read-only, mutually exclusive retarget disposition for one spec root."""

    preserve: tuple[str, ...]
    invalidate: tuple[str, ...]
    not_applicable: tuple[str, ...]


STAGE_ORDER = {"phase_a": 1, "build": 2, "verified": 3, "landed": 4}

_BUILD_MARKERS = (
    "progress-report.md",
    "spec-compliance-report.md",
    "code-review-report.md",
    "test-quality-report.md",
    "integration-report.md",
    "run-history.json",
)

_ARTIFACTS = (
    ArtifactDefinition(
        "targets.yml",
        "Target contract",
        "Canonical implementation target entries for the specification.",
        "Phase A",
        "Squad controller",
        "Written when Phase A publishes the target contract.",
        "Controllers and implementers",
        "phase_a",
    ),
    ArtifactDefinition(
        "00-overview.md",
        "Final overview",
        "Final PM/developer brief generated after planning conformance passes.",
        "Phase A",
        "Finalizer",
        "Generated at Phase A finalization after plan/task conformance.",
        "Implementers and decision makers",
        "phase_a",
    ),
    ArtifactDefinition(
        "requirements-overview.md",
        "Requirements orientation",
        "Phase 1 orientation generated with the requirements contract.",
        "Phase A",
        "Cartographer",
        "Generated with spec.md during requirements authoring.",
        "Spec readers",
        "phase_a",
    ),
    ArtifactDefinition(
        "spec.md",
        "Feature contract",
        "Defines the requested behavior and acceptance boundaries.",
        "Phase A",
        "Spec author",
        "Updated during specification.",
        "Implementers and reviewers",
        "phase_a",
    ),
    ArtifactDefinition(
        "requirements.lexicon.md",
        "Derived requirements index",
        "Compiled from `spec.md` for deterministic Lexicon validation.",
        "Phase A",
        "Cartographer",
        "Regenerated when requirements in spec.md change.",
        "Validators and task planners",
    ),
    ArtifactDefinition(
        "plan.md",
        "Implementation plan",
        "Outlines the implementation approach and sequencing.",
        "Phase A",
        "Planner",
        "Updated before task execution.",
        "Implementers",
        "phase_a",
    ),
    ArtifactDefinition(
        "plan-conformance.md",
        "Plan conformance report",
        "Checks that plan.md and tasks.md conform to the spec and scope artifacts.",
        "Phase A",
        "Finalizer",
        "Generated after PLAN/PLAN2 and before build readiness.",
        "Implementers and reviewers",
        "phase_a",
    ),
    ArtifactDefinition(
        "plan-conformance.json",
        "Plan conformance data",
        "Machine-readable conformance result for final overview and build readiness.",
        "Phase A",
        "Finalizer",
        "Generated with plan-conformance.md.",
        "Automation and reviewers",
        "phase_a",
    ),
    ArtifactDefinition(
        "tasks.md",
        "Task ledger",
        "Tracks executable work items and progress.",
        "Phase A",
        "Planner",
        "Updated as tasks change.",
        "Implementers and coordinators",
        "phase_a",
    ),
    ArtifactDefinition(
        "inputs",
        "Product input evidence",
        "Immutable input manifest, snapshots, and requirement traceability ledger.",
        "Phase A",
        "Squad controller",
        "Published from the immutable run-local input snapshot at Phase A finalization.",
        "Spec authors, implementers, and auditors",
        "phase_a",
    ),
    ArtifactDefinition(
        "inputs.yml",
        "Product input index",
        "Canonical index for preserved product input evidence.",
        "Phase A",
        "Squad controller",
        "Published with product input evidence.",
        "Controllers and auditors",
    ),
    ArtifactDefinition(
        "retarget-history.json",
        "Retarget history",
        "Immutable audit history of prior approved spec retargets.",
        "Lifecycle",
        "Retarget controller",
        "Appended only after a retarget completes.",
        "Auditors and controllers",
    ),
    ArtifactDefinition(
        "memory-receipts.json",
        "Memory receipts",
        "Generated receipts connecting Phase A outputs to memory evidence.",
        "Phase A",
        "Memory miner",
        "Regenerated when Phase A evidence changes.",
        "Auditors and spec authors",
    ),
    ArtifactDefinition(
        "graph-receipts.json",
        "Graph receipts",
        "Generated receipts connecting Phase A outputs to graph evidence.",
        "Phase A",
        "Graph controller",
        "Regenerated when Phase A evidence changes.",
        "Auditors and spec authors",
    ),
    ArtifactDefinition(
        "research.md",
        "Research notes",
        "Captures discovery notes and external context.",
        "Phase A",
        "Researcher",
        "Updated during discovery.",
        "Spec readers",
    ),
    ArtifactDefinition(
        "data-model.md",
        "Data model",
        "Describes entities, relationships, and storage choices.",
        "Phase A",
        "Architect",
        "Updated during design.",
        "Implementers",
    ),
    ArtifactDefinition(
        "contracts",
        "Contracts",
        "Holds API and integration contracts.",
        "Phase A",
        "Architect",
        "Updated when interfaces change.",
        "Implementers and integrators",
    ),
    ArtifactDefinition(
        "checklists",
        "Checklists",
        "Holds review and execution checklists.",
        "Phase A",
        "Coordinator",
        "Updated as gates evolve.",
        "Implementers and reviewers",
    ),
    ArtifactDefinition(
        "constitution.md",
        "Constitution snapshot",
        "Published read-only snapshot of `.echelon/constitution.md`.",
        "Phase A",
        "CHIEF",
        "Republished after CHIEF/spec-kit constitution creation or amendment.",
        "Spec readers",
    ),
    ArtifactDefinition(
        "strategic-overview.md",
        "Strategic overview",
        "Summarizes goals and strategic fit.",
        "Phase A",
        "Strategist",
        "Updated during planning.",
        "Decision makers",
    ),
    ArtifactDefinition(
        "feasibility.md",
        "Feasibility report",
        "Assesses whether the work is practical.",
        "Phase A",
        "Realist",
        "Updated during feasibility review.",
        "Decision makers and implementers",
    ),
    ArtifactDefinition(
        "prioritization.md",
        "Prioritization",
        "Ranks work by value and urgency.",
        "Phase A",
        "Product planner",
        "Updated during scoping.",
        "Decision makers",
    ),
    ArtifactDefinition(
        "estimates.md",
        "Estimates",
        "Captures effort and timing estimates.",
        "Phase A",
        "Planner",
        "Updated during planning.",
        "Coordinators",
    ),
    ArtifactDefinition(
        "mvp-scope.md",
        "MVP scope",
        "Defines the smallest useful delivery scope.",
        "Phase A",
        "Product planner",
        "Updated during scope decisions.",
        "Implementers and decision makers",
    ),
    ArtifactDefinition(
        "risk-matrix.md",
        "Risk matrix",
        "Tracks risks, impact, and mitigations.",
        "Phase A",
        "Realist",
        "Updated when risks change.",
        "Reviewers and coordinators",
    ),
    ArtifactDefinition(
        "dependencies.md",
        "Dependencies",
        "Lists upstream and downstream dependencies.",
        "Phase A",
        "Architect",
        "Updated during dependency review.",
        "Implementers",
    ),
    ArtifactDefinition(
        "critical-path.md",
        "Critical path",
        "Identifies sequencing constraints and blockers.",
        "Phase A",
        "Planner",
        "Updated during planning.",
        "Coordinators",
    ),
    ArtifactDefinition(
        "implementability-report.md",
        "Implementability report",
        "Assesses readiness for implementation.",
        "Phase A",
        "Implementability reviewer",
        "Updated before build starts.",
        "Implementers and reviewers",
    ),
    ArtifactDefinition(
        "test-strategy.md",
        "Test strategy",
        "Defines the validation approach.",
        "Phase A",
        "Test strategist",
        "Updated during test planning.",
        "Implementers and QA",
    ),
    ArtifactDefinition(
        "test-architecture.md",
        "Test architecture",
        "Describes test layers and supporting structure.",
        "Phase A",
        "Test architect",
        "Updated during test planning.",
        "Implementers and QA",
    ),
    ArtifactDefinition(
        "coverage-map.md",
        "Coverage map",
        "Maps requirements to expected validation.",
        "Phase A",
        "Test strategist",
        "Updated as coverage changes.",
        "Reviewers and QA",
    ),
    ArtifactDefinition(
        "quality-gates.md",
        "Quality gates",
        "Defines quality checks required for delivery.",
        "Phase A",
        "Quality reviewer",
        "Updated during quality planning.",
        "Implementers and reviewers",
    ),
    ArtifactDefinition(
        "issues.md",
        "Issues",
        "Tracks known issues and follow-ups.",
        "Phase A",
        "Coordinator",
        "Updated when issues are found.",
        "Implementers and reviewers",
    ),
    ArtifactDefinition(
        "spec-diagram.svg",
        "Spec diagram SVG",
        "Provides an editable visual model of the spec.",
        "Phase A",
        "Architect",
        "Updated when the model changes.",
        "Spec readers",
    ),
    ArtifactDefinition(
        "spec-diagram.png",
        "Spec diagram PNG",
        "Provides a rendered visual model of the spec.",
        "Phase A",
        "Architect",
        "Updated when the model changes.",
        "Spec readers",
    ),
    ArtifactDefinition(
        "progress-report.md",
        "Progress report",
        "Summarizes build progress.",
        "Build",
        "Implementer",
        "Updated during build execution.",
        "Coordinators",
        "build",
    ),
    ArtifactDefinition(
        "spec-compliance-report.md",
        "Spec compliance report",
        "Checks implementation against the spec.",
        "Build",
        "Reviewer",
        "Updated during build review.",
        "Reviewers",
        "build",
    ),
    ArtifactDefinition(
        "code-review-report.md",
        "Code review report",
        "Captures code review findings.",
        "Build",
        "Code reviewer",
        "Updated during build review.",
        "Implementers and reviewers",
        "build",
    ),
    ArtifactDefinition(
        "test-quality-report.md",
        "Test quality report",
        "Assesses test strength and gaps.",
        "Build",
        "Test reviewer",
        "Updated during test review.",
        "QA and reviewers",
        "build",
    ),
    ArtifactDefinition(
        "integration-report.md",
        "Integration report",
        "Summarizes integration status and issues.",
        "Build",
        "Integrator",
        "Updated during integration.",
        "Implementers and reviewers",
        "build",
    ),
    ArtifactDefinition(
        "gap-report.md",
        "Gap report",
        "Lists remaining requirement gaps.",
        "Verification",
        "Verifier",
        "Updated during verification.",
        "Implementers and reviewers",
        "verified",
    ),
    ArtifactDefinition(
        "excess-report.md",
        "Excess report",
        "Lists implementation beyond the requested scope.",
        "Verification",
        "Verifier",
        "Updated during verification.",
        "Reviewers",
    ),
    ArtifactDefinition(
        "traceability-matrix.md",
        "Traceability matrix",
        "Maps requirements to evidence.",
        "Verification",
        "Verifier",
        "Updated during verification.",
        "Reviewers and auditors",
        "verified",
    ),
    ArtifactDefinition(
        "verification-summary.md",
        "Verification summary",
        "Summarizes final verification results.",
        "Verification",
        "Verifier",
        "Updated after verification.",
        "Reviewers and coordinators",
        "verified",
    ),
    ArtifactDefinition(
        "fulfillment-report.md",
        "Fulfillment report",
        "Summarizes requirement fulfillment.",
        "Verification",
        "Verifier",
        "Updated after verification.",
        "Reviewers and coordinators",
        "verified",
    ),
    ArtifactDefinition(
        "run-history.json",
        "Run history",
        "Records machine-readable execution history.",
        "Build",
        "Harness",
        "Updated as runs complete.",
        "Automation and reviewers",
        "build",
    ),
    ArtifactDefinition(
        "harness-run-history.json",
        "Harness delivery history",
        "Records Phase B delivery-run summaries.",
        "Build",
        "Harness",
        "Updated after each delivery run.",
        "Automation and reviewers",
        "build",
    ),
    ArtifactDefinition(
        "squad-report.md",
        "Phase A squad report",
        "Generated Phase A completion and handoff summary.",
        "Phase A",
        "Squad controller",
        "Generated when Phase A finalizes.",
        "Implementers and decision makers",
    ),
    ArtifactDefinition(
        "feature-metadata.yml",
        "Feature metadata",
        "Generated Phase A publication metadata.",
        "Phase A",
        "Squad controller",
        "Generated when Phase A finalizes.",
        "Controllers and tooling",
    ),
    ArtifactDefinition(
        "re-context.json",
        "Published RE context",
        "Generated canonical reference to the run-local published RE snapshot.",
        "Phase A",
        "Squad controller",
        "Generated when Phase A finalizes.",
        "Spec authors and implementers",
    ),
    ArtifactDefinition(
        "ARTIFACTS.md",
        "Artifact map",
        "Generated inventory of the spec-local artifact registry.",
        "Phase A",
        "Artifact index",
        "Regenerated when the artifact map is requested.",
        "Spec readers and controllers",
    ),
)


_RETARGET_PRESERVE_ROOTS = frozenset(
    {
        ".echelon",
        "amendments",
        "inputs",
        "inputs.yml",
        "retarget-history.json",
        "run-history.json",
    }
)


def artifact_definitions() -> tuple[ArtifactDefinition, ...]:
    """Return the immutable public artifact registry without exposing its storage."""

    return _ARTIFACTS


def plan_retarget_artifacts(spec_dir: Path) -> RetargetArtifactPlan:
    """Classify every spec-local root without reading or changing external state."""

    existing = tuple(sorted(path.name for path in spec_dir.iterdir()))
    preserve = tuple(name for name in existing if name in _RETARGET_PRESERVE_ROOTS)
    invalidate = tuple(name for name in existing if name not in _RETARGET_PRESERVE_ROOTS)
    declared = tuple(definition.path for definition in artifact_definitions())
    not_applicable = tuple(name for name in declared if not (spec_dir / name).exists())
    return RetargetArtifactPlan(preserve, invalidate, not_applicable)


def infer_lifecycle_stage(spec_dir: Path) -> str:
    try:
        status = read_frontmatter(spec_dir).get("status", "")
    except Exception:
        status = ""
    if str(status).lower() == "landed":
        return "landed"
    if str(status).lower() == "ready_to_land":
        return "verified"
    if (spec_dir / "verification-summary.md").exists() or (
        spec_dir / "fulfillment-report.md"
    ).exists():
        return "verified"
    if any((spec_dir / marker).exists() for marker in _BUILD_MARKERS):
        return "build"
    return "phase_a"


def render_artifact_index(
    spec_dir: Path, generated_at: datetime | None = None
) -> str:
    generated_at = generated_at or datetime.now(timezone.utc)
    lifecycle_stage = infer_lifecycle_stage(spec_dir)
    rows = [
        (artifact, _status_for(spec_dir, artifact, lifecycle_stage))
        for artifact in _ARTIFACTS
    ]
    missing_required = [artifact for artifact, status in rows if status == "Missing"]
    unclassified = _unclassified_paths(spec_dir)

    lines = [
        "# Artifact Map",
        (
            "> This file is generated by Echelon. Regenerate it with "
            "`echelon spec artifacts <spec_id>`; do not hand-edit it."
        ),
        "",
        "## Start Here",
        "Begin with `spec.md`, then `plan.md`, then `tasks.md`.",
        "",
        "## Current State",
        f"Lifecycle stage: {lifecycle_stage}",
        "",
        "## Artifact Table",
        "| Artifact | Status | Title | Purpose | Phase | Owner | Updated When | Audience |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for artifact, status in rows:
        lines.append(
            f"| `{artifact.path}` | {status} | {artifact.title} | {artifact.purpose} | "
            f"{artifact.phase} | {artifact.owner} | {artifact.updated_when} | {artifact.audience} |"
        )

    lines.extend(["", "## Missing Expected Files"])
    if missing_required:
        lines.extend(
            f"- `{artifact.path}` - {artifact.title}" for artifact in missing_required
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Unclassified Files"])
    if unclassified:
        lines.extend(f"- `{path}`" for path in unclassified)
    else:
        lines.append("- None")

    lines.extend(["", "## Generated", f"Generated at: {generated_at.isoformat()}", ""])
    return "\n".join(lines)


def write_artifact_index(
    spec_dir: Path, generated_at: datetime | None = None
) -> Path:
    path = spec_dir / "ARTIFACTS.md"
    path.write_text(render_artifact_index(spec_dir, generated_at), encoding="utf-8")
    return path


def _status_for(
    spec_dir: Path, artifact: ArtifactDefinition, lifecycle_stage: str
) -> str:
    if (spec_dir / artifact.path).exists():
        return "Present"
    required_stage = artifact.required_stage
    if (
        required_stage is not None
        and STAGE_ORDER[required_stage] <= STAGE_ORDER[lifecycle_stage]
    ):
        return "Missing"
    return "Optional missing"


def _unclassified_paths(spec_dir: Path) -> list[str]:
    registry_paths = {artifact.path for artifact in _ARTIFACTS}
    return [
        path.name
        for path in sorted(spec_dir.iterdir(), key=lambda item: item.name)
        if path.name not in registry_paths and path.name != "ARTIFACTS.md"
    ]
