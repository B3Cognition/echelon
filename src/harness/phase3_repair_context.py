"""Read-only, content-bound inputs for a selected Phase 3 review."""
from __future__ import annotations

import hashlib
from pathlib import Path

from harness.phase3_repair import RepairContractError


def capture_review_inputs(spec_dir: Path, *, project_root: Path) -> tuple[dict[str, str], str]:
    """Bound architecture/test/task dependencies; never truncate required inputs."""
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


def capture_repair_context(spec_dir: Path, *, project_root: Path) -> str:
    """Current owner handoff cannot depend on optional historical journal rows."""
    _, inputs = capture_review_inputs(spec_dir, project_root=project_root)
    issues = read_repair_issues(spec_dir, project_root=project_root).encode("utf-8")
    if len(issues) + len(inputs.encode()) > 262144:
        raise RepairContractError("required repair context exceeds 262144 bytes")
    return ("\n## Current Phase 3 repair handoff\n"
            "Address the current finding owned by this phase using the checklist below. "
            "Preserve validated requirements and quality gates. Distinguish facts from proposed technical mechanisms; "
            "do not accept an unsupported answer or a protected product decision. "
            "An old repaired selection awaiting review is not an instruction to repeat that repair.\n"
            "### Current issues.md\n" + issues.decode("utf-8") + inputs)


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
