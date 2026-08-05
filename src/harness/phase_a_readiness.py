"""Deterministic Phase A readiness validation."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Mapping

from harness.spec_frontmatter import read_canonical_target_entries
from harness.task_targets import analyze_task_targets


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

    if not checked_dirs:
        blockers.append("no Phase A spec directory found")

    return PhaseAReadinessResult(
        ready=False,
        blockers=blockers,
        missing=missing,
        ready_spec_dir=None,
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
    replacement = retarget.get("replacement_targets")
    implementation = state.get("implementation_targets")
    if (
        type(replacement) is not list
        or type(implementation) is not list
        or any(type(item) is not str or not item for item in replacement)
        or any(type(item) is not str or not item for item in implementation)
    ):
        return ["retarget replacement target contract is invalid"]
    authoritative = [
        str(entry["path"])
        for entry in read_canonical_target_entries(spec_dir)
        if isinstance(entry.get("path"), str)
    ]
    blockers: list[str] = []
    if authoritative != implementation or authoritative != replacement:
        blockers.append(
            "retarget replacement targets do not match authoritative targets.yml"
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
            "retarget tasks must declare exactly one target from the replacement target set per canonical task"
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

    Spec-kit constitution files may keep a leading Sync Impact Report comment
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
