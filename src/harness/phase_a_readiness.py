"""Deterministic Phase A readiness validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from harness.canonical_requirements import extract_canonical_requirements
from harness.coverage_contract import CoverageContractError
from harness.coverage_evidence import (
    active_unmapped_coverage_requirement_ids,
    parse_coverage_map_obligations,
    task_owned_coverage_case_ids,
    published_browser_gates,
)
from harness.deferred_scope import DeferredScopeError, active_entries
from harness.spec_frontmatter import read_canonical_target_entries
from harness.task_targets import analyze_task_targets, task_declares_file, validate_task_targets
from harness.runnability_contract import CONTRACT_PATH as RUNNABILITY_CONTRACT_PATH
from harness.runnability_disposition import RunnabilityDispositionError, read_runnability_disposition
from kernel.task_contract import parse_task_rows

REQUIRED_PHASE_A_BUILD_INPUTS = (
    "00-overview.md",
    "requirements-overview.md",
    "spec.md",
    "plan.md",
    "plan-conformance.md",
    "plan-conformance.json",
    "research.md",
    "data-model.md",
    "tasks.md",
    "constitution.md",
    "test-strategy.md",
    "test-architecture.md",
    "coverage-map.md",
)

CONSTITUTION_TEMPLATE_MARKERS = (
    "[PROJECT_NAME]",
    "[CONSTITUTION_VERSION]",
    "[RATIFICATION_DATE]",
    "[LAST_AMENDED_DATE]",
    "[PRINCIPLE_1_NAME]",
    "[PRINCIPLE_2_NAME]",
    "[PRINCIPLE_3_NAME]",
    "[PRINCIPLE_4_NAME]",
    "[PRINCIPLE_5_NAME]",
)

_SYNC_IMPACT_REPORT_RE = re.compile(
    r"\A\s*<!--\s*Sync Impact Report\b.*?-->\s*",
    re.DOTALL,
)


@dataclass(frozen=True)
class PhaseAReadinessResult:
    ready: bool
    blockers: list[str]
    missing: dict[str, list[Path]]
    ready_spec_dir: Path | None = None


def validate_phase_a_readiness(
    state: dict,
    candidate_spec_dirs: list[Path],
    *,
    allow_pending_retarget_finalization: bool = False,
) -> PhaseAReadinessResult:
    retarget = state.get("retarget")
    if isinstance(retarget, Mapping):
        status = str(retarget.get("status") or "")
        if status not in {"complete", "recovered"} and not (
            allow_pending_retarget_finalization and status == "finalizing"
        ):
            return PhaseAReadinessResult(
                ready=False,
                blockers=[
                    f"retarget revision {retarget.get('revision_id')} is {status}"
                ],
                missing={},
                ready_spec_dir=None,
            )
    status = str(state.get("status") or "").strip()
    blocked_reason = str(state.get("blocked_reason") or "").strip()
    if status in {"blocked", "interrupted"}:
        suffix = f": {blocked_reason}" if blocked_reason else ""
        return PhaseAReadinessResult(
            ready=False,
            blockers=[f"run status is {status}{suffix}"],
            missing={},
            ready_spec_dir=None,
        )

    normalized_dirs = _dedupe_existing_or_referenced_dirs(candidate_spec_dirs)
    for spec_dir in normalized_dirs:
        if all((spec_dir / name).exists() for name in REQUIRED_PHASE_A_BUILD_INPUTS):
            retarget_blockers = _retarget_contract_blockers(state, spec_dir)
            if retarget_blockers:
                continue
            conformance_blocker = _plan_conformance_blocker(
                spec_dir / "plan-conformance.json"
            )
            if conformance_blocker is not None:
                continue
            constitution_blocker = _constitution_blocker(spec_dir / "constitution.md")
            if constitution_blocker is not None:
                continue
            coverage_blocker = _coverage_contract_blocker(spec_dir)
            if coverage_blocker is not None:
                continue
            return PhaseAReadinessResult(
                ready=True,
                blockers=[],
                missing={},
                ready_spec_dir=spec_dir,
            )

    missing: dict[str, list[Path]] = {}
    blockers: list[str] = []
    checked_dirs = normalized_dirs or candidate_spec_dirs
    for name in REQUIRED_PHASE_A_BUILD_INPUTS:
        missing_dirs = [
            spec_dir for spec_dir in checked_dirs
            if not (spec_dir / name).exists()
        ]
        if missing_dirs and len(missing_dirs) == len(checked_dirs):
            missing[name] = missing_dirs
            blockers.append(f"{name} absent")

    for spec_dir in checked_dirs:
        for blocker in _retarget_contract_blockers(state, spec_dir):
            if blocker not in blockers:
                blockers.append(blocker)
        conformance_blocker = _plan_conformance_blocker(
            spec_dir / "plan-conformance.json"
        )
        if conformance_blocker is not None and conformance_blocker not in blockers:
            blockers.append(conformance_blocker)
        constitution_blocker = _constitution_blocker(spec_dir / "constitution.md")
        if constitution_blocker is not None and constitution_blocker not in blockers:
            blockers.append(constitution_blocker)
        coverage_blocker = _coverage_contract_blocker(spec_dir)
        if coverage_blocker is not None and coverage_blocker not in blockers:
            blockers.append(coverage_blocker)

    if not checked_dirs:
        blockers.append("no Phase A spec directory found")

    return PhaseAReadinessResult(
        ready=False,
        blockers=blockers,
        missing=missing,
        ready_spec_dir=None,
    )


def validate_phase_a_build_readiness(
    state: dict, candidate_spec_dirs: list[Path], *, project_root: Path,
    visual_execution_available: bool | Callable[[Path], bool],
    allow_pending_retarget_finalization: bool = False,
) -> PhaseAReadinessResult:
    """Structural readiness plus current authoritative verification capability."""
    structural = validate_phase_a_readiness(
        state, candidate_spec_dirs,
        allow_pending_retarget_finalization=allow_pending_retarget_finalization,
    )
    if not structural.ready:
        return structural
    blockers = verification_capability_blockers(
        structural.ready_spec_dir, project_root=project_root,
        visual_execution_available=visual_execution_available,
    )
    return PhaseAReadinessResult(
        ready=not blockers, blockers=blockers, missing=structural.missing,
        ready_spec_dir=None if blockers else structural.ready_spec_dir,
    )


def verification_capability_blockers(
    spec_dir: Path, *, project_root: Path,
    visual_execution_available: bool | Callable[[Path], bool],
) -> list[str]:
    """Evaluate each owner's static contract, without host execution or writes."""
    from harness.stacks.errors import StackError
    from harness.stacks.preflight import verification_capability_findings
    from harness.verification_stack_runtime import resolve_verification_stacks

    if not isinstance(project_root, Path) or not project_root.is_absolute():
        return ["verification_context_required: authoritative absolute project root is required"]
    error = coverage_contract_error(spec_dir)
    if error:
        return [f"coverage-map.md invalid: {error}"]
    try:
        canonical_ids = {item.id for item in extract_canonical_requirements(spec_dir)}
        deferred_ids = {item for entry in active_entries(spec_dir) for item in entry.selected_ids}
        obligations = [item for row in parse_coverage_map_obligations(
            spec_dir / "coverage-map.md", canonical_ids,
        ) for item in row if item.requirement_id not in deferred_ids]
        entries = read_canonical_target_entries(spec_dir, strict=True)
        targets = [entry["path"] for entry in entries]
        if not targets and (spec_dir / "targets.yml").exists():
            return ["verification_ownership_unresolved: targets.yml has no valid targets"]
        markdown = (spec_dir / "tasks.md").read_text(encoding="utf-8")
        canonical_task_ids = {row.task_id for row in parse_task_rows(markdown)}
        task_cases = task_owned_coverage_case_ids(spec_dir / "tasks.md")
        if targets:
            ownership = validate_task_targets(
                markdown, declared_targets=targets, allow_legacy_single_target=False,
            )
            if not ownership.valid:
                return ["verification_ownership_unresolved: tasks must declare exactly one canonical target"]
            target_tasks = ownership.target_tasks
            owned = {case for tasks in target_tasks.values() for task in tasks for case in task_cases.get(task, ())}
            unowned = {item.test_case_id for item in obligations} - owned
            if unowned:
                return ["verification_ownership_unresolved: unowned coverage cases: " + ", ".join(sorted(unowned))]
        else:
            analysis = analyze_task_targets(markdown)
            if analysis.target_tasks or analysis.cross_target_tasks:
                return ["verification_ownership_unresolved: task targets are absent from canonical spec targets"]
            targets = ["."]
            target_tasks = {".": tuple(task_cases)}

        gates = published_browser_gates(spec_dir)
        gate_targets: dict[str, set[str]] = {}
        for gate in ("playwright e2e critical journeys", "visual validation task"):
            if gate not in gates:
                continue
            if len(targets) == 1:
                gate_targets[gate] = set(targets)
                continue
            refs = set(re.findall(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b", gates[gate]))
            task_refs = {ref for ref in refs if ref.startswith("T-")}
            case_refs = refs - task_refs
            if task_refs - set(task_cases) or case_refs - {case for cases in task_cases.values() for case in cases}:
                return [f"verification_ownership_unresolved: {gate} references unknown task/case owners"]
            owners = {target for target, tasks in target_tasks.items() if any(
                task in task_refs or case_refs.intersection(task_cases.get(task, ())) for task in tasks
            )}
            if not owners:
                return [f"verification_ownership_unresolved: {gate} must reference its task/case owners"]
            gate_targets[gate] = owners

        blockers: list[str] = []
        deferred_target: str | None = None
        disposition_checked = False
        for target in targets:
            try:
                resolved = resolve_verification_stacks(project_root, project_root / target)
                if resolved.runnability.policy == "required":
                    if not disposition_checked:
                        disposition = read_runnability_disposition(spec_dir)
                        disposition_checked = True
                        if disposition is not None and disposition.status == "deferred":
                            matches = []
                            for item in targets:
                                aliases = {item, (project_root / item).name}
                                if item == ".":
                                    aliases.add("workspace")
                                if disposition.target in aliases:
                                    matches.append(item)
                            if len(matches) == 1:
                                deferred_target = matches[0]
                    if deferred_target != target:
                        contract = (Path(target) / RUNNABILITY_CONTRACT_PATH).as_posix()
                        owner_scope = canonical_task_ids if not entries else target_tasks.get(target, ())
                        owners = [task_id for task_id in owner_scope
                                  if task_id in canonical_task_ids
                                  if task_declares_file(markdown, task_id, contract)]
                        if not owners:
                            blockers.append(f"{target}: runnability_contract_owner_required: "
                                            f"one task must declare `{contract}` in Files")
                        elif len(owners) > 1:
                            blockers.append(f"{target}: runnability_contract_owner_ambiguous: "
                                            f"{', '.join(owners)} declare `{contract}` in Files")
                cases = {case for task in target_tasks.get(target, ()) for case in task_cases.get(task, ())}
                types = {item.test_type for item in obligations if not entries or item.test_case_id in cases}
                visual = target in gate_targets.get("visual validation task", ())
                browser = visual or target in gate_targets.get("playwright e2e critical journeys", ()) or any(
                    item.observer.required and item.observer.adapter == "playwright-json"
                    and types.intersection(item.observer.test_types) for item in resolved.coverage_observers
                )
                findings = verification_capability_findings(
                    resolved, coverage_test_types=types, browser_required=browser,
                    semantic_visual_required=visual, visual_execution_available=(
                        visual_execution_available(project_root / target)
                        if visual and callable(visual_execution_available) else bool(visual_execution_available)
                    ),
                )
                blockers.extend(f"{target}: {item.code}: {item.message}" for item in findings if item.severity == "error")
            except RunnabilityDispositionError as exc:
                blockers.append(f"{target}: runnability_disposition_invalid: {exc}")
            except (StackError, ValueError) as exc:
                blockers.append(f"{target}: verification_stack_invalid: {exc}")
        return blockers
    except (CoverageContractError, DeferredScopeError, OSError, ValueError) as exc:
        return [f"verification_contract_invalid: {exc}"]


def validate_configured_phase_a_build_readiness(
    state: dict, candidate_spec_dirs: list[Path], *, project_root: Path,
    allow_pending_retarget_finalization: bool = False,
    execution_config=None,
) -> PhaseAReadinessResult:
    """Production entry: resolve visual executor availability only for its owners."""
    from harness.semantic_visual_validator import semantic_visual_execution_available

    return validate_phase_a_build_readiness(
        state, candidate_spec_dirs, project_root=project_root,
        visual_execution_available=lambda target: semantic_visual_execution_available(
            project_root, config=execution_config,
        ),
        allow_pending_retarget_finalization=allow_pending_retarget_finalization,
    )


def _retarget_contract_blockers(state: Mapping[str, object], spec_dir: Path) -> list[str]:
    """Validate the public replacement contract only for terminal retargets."""

    retarget = state.get("retarget")
    if not isinstance(retarget, Mapping) or retarget.get("status") not in {
        "finalizing",
        "complete",
        "recovered",
    }:
        return []
    retarget_status = retarget.get("status")
    target_field = (
        "old_targets" if retarget_status == "recovered" else "replacement_targets"
    )
    target_label = (
        "old targets" if retarget_status == "recovered" else "replacement targets"
    )
    replacement = retarget.get(target_field)
    implementation = state.get("implementation_targets")
    if (
        type(replacement) is not list
        or type(implementation) is not list
        or any(type(item) is not str or not item for item in replacement)
        or any(type(item) is not str or not item for item in implementation)
    ):
        return [f"retarget {target_label} contract is invalid"]
    authoritative = [
        str(entry["path"])
        for entry in read_canonical_target_entries(spec_dir)
        if isinstance(entry.get("path"), str)
    ]
    blockers: list[str] = []
    if authoritative != implementation or authoritative != replacement:
        blockers.append(
            f"retarget {target_label} do not match authoritative targets.yml"
        )
    try:
        analysis = analyze_task_targets(
            (spec_dir / "tasks.md").read_text(encoding="utf-8")
        )
    except OSError:
        return blockers
    replacement_set = set(replacement)
    assigned = {
        target: task_ids
        for target, task_ids in analysis.target_tasks.items()
        if target in replacement_set
    }
    if (
        analysis.unowned_tasks
        or analysis.cross_target_tasks
        or analysis.path_target_mismatches
        or set(analysis.target_tasks) != replacement_set
        or set(task_id for task_ids in assigned.values() for task_id in task_ids)
        != set(analysis.all_task_ids)
    ):
        blockers.append(
            "retarget tasks must declare exactly one target from the "
            f"{target_label} set per canonical task"
        )
    return blockers


def _dedupe_existing_or_referenced_dirs(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _constitution_blocker(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    markers = unresolved_constitution_template_markers(text)
    if markers:
        return "constitution.md contains unresolved template markers: " + ", ".join(markers)
    return None


def coverage_contract_error(spec_dir: Path, *, check_task_ownership: bool = True) -> str | None:
    """Validate coverage; only pre-planning callers may omit task consistency."""
    path = spec_dir / "coverage-map.md"
    if not path.is_file():
        return None
    try:
        canonical_ids = {
            requirement.id for requirement in extract_canonical_requirements(spec_dir)
        }
        obligations = parse_coverage_map_obligations(path, canonical_ids)
        deferred_ids = {
            requirement_id
            for entry in active_entries(spec_dir)
            for requirement_id in entry.selected_ids
            if not requirement_id.startswith("T-")
        }
        unmapped = active_unmapped_coverage_requirement_ids(
            canonical_ids=canonical_ids,
            obligations=(
                obligation for row in obligations for obligation in row
            ),
            deferred_ids=deferred_ids,
        )
        if unmapped:
            return (
                "canonical requirements have no planned test obligation: "
                + ", ".join(unmapped[:20])
            )
        if not check_task_ownership:
            return None
        planned_case_ids = {
            obligation.test_case_id
            for row in obligations
            for obligation in row
        }
        task_owned = task_owned_coverage_case_ids(spec_dir / "tasks.md")
        missing_owned = sorted(
            {
                case_id
                for case_ids in task_owned.values()
                for case_id in case_ids
            }
            - planned_case_ids
        )
        if missing_owned:
            return (
                "task-owned test cases are absent from coverage-map.md: "
                + ", ".join(missing_owned[:20])
            )
    except (CoverageContractError, DeferredScopeError, OSError) as exc:
        return str(exc)
    return None


def _coverage_contract_blocker(spec_dir: Path) -> str | None:
    error = coverage_contract_error(spec_dir)
    return f"coverage-map.md invalid: {error}" if error is not None else None


def _plan_conformance_blocker(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"plan-conformance.json invalid: {exc}"

    if not isinstance(payload, dict):
        return "plan-conformance.json invalid: root must be an object"

    allowed = {"status", "findings", "sources"}
    extra = sorted(set(payload) - allowed)
    if extra:
        return "plan-conformance.json invalid: unexpected keys: " + ", ".join(extra)

    missing = sorted(allowed - set(payload))
    if missing:
        return "plan-conformance.json invalid: missing keys: " + ", ".join(missing)

    status = payload.get("status")
    if status not in {"pass", "needs_repair"}:
        return "plan-conformance.json invalid: status must be pass or needs_repair"

    findings = payload.get("findings")
    if not isinstance(findings, list):
        return "plan-conformance.json invalid: findings must be an array"
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            return f"plan-conformance.json invalid: findings[{index}] must be an object"
        required_finding = {"id", "severity", "artifact", "description"}
        missing_finding = sorted(required_finding - set(finding))
        if missing_finding:
            return (
                f"plan-conformance.json invalid: findings[{index}] missing keys: "
                + ", ".join(missing_finding)
            )
        severity = finding.get("severity")
        if severity not in {"info", "warning", "repair_required"}:
            return (
                f"plan-conformance.json invalid: findings[{index}].severity "
                "must be info, warning, or repair_required"
            )
        allowed_finding = required_finding | {"required_repair"}
        extra_finding = sorted(set(finding) - allowed_finding)
        if extra_finding:
            return (
                f"plan-conformance.json invalid: findings[{index}] unexpected keys: "
                + ", ".join(extra_finding)
            )

    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        return "plan-conformance.json invalid: sources must be a non-empty array"
    if not all(isinstance(source, str) and source.strip() for source in sources):
        return "plan-conformance.json invalid: sources must contain non-empty strings"

    if status == "pass" and any(
        isinstance(finding, dict)
        and finding.get("severity") == "repair_required"
        for finding in findings
    ):
        return (
            "plan-conformance.json invalid: pass status cannot include "
            "repair_required findings"
        )

    return None


def unresolved_constitution_template_markers(text: str) -> list[str]:
    """Return unresolved constitution template markers in executable content.

    Migrated constitution files may keep a leading Sync Impact Report comment
    that maps old placeholder slots to concrete principle names. Those historical
    mapping entries are not live template placeholders. The constitution body
    after the report remains authoritative for readiness checks.
    """
    effective_text = _SYNC_IMPACT_REPORT_RE.sub("", text, count=1)
    markers = [
        marker for marker in CONSTITUTION_TEMPLATE_MARKERS
        if marker in effective_text
    ]
    return markers
