"""Read-only, content-bound inputs for a selected Phase 3 review."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from harness.phase3_repair import RepairContractError


def planner_handoff_context(state: Mapping, manifest: Mapping[str, str]) -> str:
    """Carry current planner diagnostics into SAGE without granting authority."""
    handoff = state.get("phase3_last_blocker")
    if (not isinstance(handoff, Mapping) or handoff.get("producer") != "PLAN"
            or handoff.get("input_manifest") != dict(manifest)):
        return ""
    summary = {key: handoff[key] for key in ("issue_id", "owner_phase", "detail", "next_action")
               if isinstance(handoff.get(key), str) and 0 < len(handoff[key]) <= 2000}
    if not summary:
        return ""
    return ("\n## Planner dependency handoff (advisory)\n"
            "The planner stopped before consensus because of the diagnostic below. "
            "Independently review the selected submission and investigate remaining findings against current inputs. "
            "A planner-suggested owner or action is not an approved decision, evidence of closure, or a gate waiver. "
            "Keep genuine human decisions and external prerequisites explicit in the issue register.\n"
            + json.dumps(summary, sort_keys=True) + "\n")


def review_input_paths(spec_dir: Path, *, project_root: Path) -> list[Path]:
    """Enumerate safe candidate dependencies independently of rendering limits."""
    root = spec_dir.resolve(strict=True)
    if not root.is_relative_to(project_root.resolve()) or spec_dir.is_symlink():
        raise RepairContractError("review spec root is outside the project")
    paths = [root / name for name in (
        "spec.md", "plan.md", "architecture.md", "research.md", "data-model.md",
        "tasks.md", "test-strategy.md", "test-architecture.md", "coverage-map.md",
        "critical-path.md", "risk-matrix.md", "dependencies.md",
    ) if (root / name).exists()]
    for directory in (root / "contracts", root / "adr"):
        if directory.is_symlink():
            raise RepairContractError("review dependency directory is a symlink")
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise RepairContractError("review contract tree contains a symlink")
            if path.is_file() and path.suffix == ".md":
                paths.append(path)
    if not (root / "spec.md").is_file():
        raise RepairContractError("required review input spec.md is missing")
    for path in paths:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise RepairContractError("review artifact escapes spec root")
    return paths


def capture_review_inputs(spec_dir: Path, *, project_root: Path) -> tuple[dict[str, str], str]:
    """Bound architecture/test/task dependencies; never truncate required inputs."""
    paths = review_input_paths(spec_dir, project_root=project_root)
    root = spec_dir.resolve(strict=True)
    manifest, sections = {}, []
    size = 0
    for path in paths:
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(root):
            raise RepairContractError("review artifact escapes spec root")
        with path.open("rb") as stream:
            data = stream.read(262145)
        size += len(data)
        if size > 262144:
            raise RepairContractError("required review inputs exceed 262144 bytes")
        name = path.relative_to(root).as_posix()
        manifest[name] = hashlib.sha256(data).hexdigest()
        sections.append(f"\n### Review input: {name}\n{data.decode('utf-8')}")
    return manifest, "\n".join(sections)


def capture_repair_context(spec_dir: Path, *, project_root: Path, require_implementability: bool = False) -> str:
    """Current owner handoff cannot depend on optional historical journal rows."""
    _, inputs = capture_review_inputs(spec_dir, project_root=project_root)
    issues = read_repair_issues(spec_dir, project_root=project_root).encode("utf-8")
    feasibility = ""
    if require_implementability:
        path = spec_dir / "implementability-report.md"
        if not path.is_file() or path.is_symlink():
            raise RepairContractError("required implementability report is missing or unsafe")
        with path.open("rb") as stream:
            data = stream.read(262145)
        feasibility = ("\n### Current implementability-report.md (ASSESS2 rejection)\n"
            "This independent gate remains rejected even when WHY3 closes another issue. "
            "Repair its concrete findings without weakening requirements; fresh ASSESS2 must reassess them.\n"
            + data.decode("utf-8"))
    if len(issues) + len(inputs.encode()) + len(feasibility.encode()) > 262144:
        raise RepairContractError("required repair context exceeds 262144 bytes")
    return ("\n## Current Phase 3 repair handoff\n"
            "Address the current finding owned by this phase using the checklist below. "
            "Preserve validated requirements and quality gates. Distinguish facts from proposed technical mechanisms; "
            "do not accept an unsupported answer or a protected product decision. "
            "An old repaired selection awaiting review is not an instruction to repeat that repair.\n"
            "### Current issues.md\n" + issues.decode("utf-8") + feasibility + inputs)


def read_repair_issues(spec_dir: Path, *, project_root: Path) -> str:
    root = spec_dir.resolve(strict=True)
    if spec_dir.is_symlink() or not root.is_relative_to(project_root.resolve()):
        raise RepairContractError("repair spec root is outside the project")
    path = root / "issues.md"
    if not path.is_file() or path.is_symlink():
        raise RepairContractError("required repair input issues.md is missing or unsafe")
    with path.open("rb") as stream:
        issues = stream.read(262145)
    if len(issues) > 262144:
        raise RepairContractError("required repair context exceeds 262144 bytes")
    return issues.decode("utf-8")
