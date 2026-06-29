"""Deterministic Phase A readiness validation."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_PHASE_A_BUILD_INPUTS = (
    "spec.md",
    "plan.md",
    "research.md",
    "data-model.md",
    "tasks.md",
    "constitution.md",
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


@dataclass(frozen=True)
class PhaseAReadinessResult:
    ready: bool
    blockers: list[str]
    missing: dict[str, list[Path]]
    ready_spec_dir: Path | None = None


def validate_phase_a_readiness(
    state: dict,
    candidate_spec_dirs: list[Path],
) -> PhaseAReadinessResult:
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
    markers = [
        marker for marker in CONSTITUTION_TEMPLATE_MARKERS
        if marker in text
    ]
    if markers:
        return "constitution.md contains unresolved template markers: " + ", ".join(markers)
    return None
