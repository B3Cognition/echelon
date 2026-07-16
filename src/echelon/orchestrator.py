"""Multi-target orchestrator for target-scoped workspace delivery."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Mapping, Optional

from harness.spec_frontmatter import find_spec_dir
from harness.task_targets import analyze_task_targets
from kernel.task_contract import parse_task_rows


_ECHELON_YML_REL = ".echelon/config.yml"


def validate_targets(
    targets_rel: List[str],
    polyrepo_root: Path,
) -> List[Path]:
    """Resolve and validate target sub-repo paths.

    Args:
        targets_rel: List of target names/paths relative to polyrepo_root.
        polyrepo_root: Root directory of the polyrepo.

    Returns:
        List of resolved absolute target paths.

    Raises:
        SystemExit(1) with a descriptive message on the first validation failure.
    """
    resolved: List[Path] = []
    for rel in targets_rel:
        target = (polyrepo_root / rel).resolve()
        if not target.exists():
            print(
                f"✗ Target '{rel}' not found at {target}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not (target / ".git").exists():
            print(
                f"✗ {rel}: target exists but is not a git repo.\n"
                "  Polyrepo harness targets must be initialized git repositories.",
                file=sys.stderr,
            )
            sys.exit(1)
        resolved.append(target)
    return resolved


def validate_single_target(targets_rel: List[str], polyrepo_root: Path) -> Path:
    """Validate that a normal implementation spec has exactly one target repo."""
    if not targets_rel:
        print(
            "✗ No implementation target configured.\n"
            "  Delivery will not infer one. Regenerate the spec with "
            "'echelon spec run <description> --target <source-path>'.",
            file=sys.stderr,
        )
        sys.exit(1)
    if len(targets_rel) > 1:
        print(
            "✗ Multiple targets configured for single-target harness build.\n"
            "  Fix: keep exactly one target in spec frontmatter, or use explicit multi-target mode.",
            file=sys.stderr,
        )
        sys.exit(1)
    return validate_targets(targets_rel, polyrepo_root)[0]


def run_multi_target(
    spec_id: str,
    targets: List[Path],
    extra_args: List[str],
    echelon_bin: Optional[str] = None,
    workspace_root: Optional[Path] = None,
    workspace_git_role: Optional[str] = None,
    source_ids: Optional[Mapping[str, str]] = None,
    source_git_roles: Optional[Mapping[str, str]] = None,
    command: str = "run",
) -> int:
    """Run 'echelon delivery <command> <spec_id> [extra_args]' per target.

    Streams each target's stdout/stderr prefixed with [target-name].
    Returns 0 if all targets succeed, 1 if any fail.

    Args:
        spec_id: Spec ID to pass to each harness run.
        targets: List of resolved absolute target paths.
        extra_args: Additional CLI args to forward (e.g. ["strategy=codegen"]).
        echelon_bin: Path to echelon binary (resolved from PATH if None).
    """
    if echelon_bin is None:
        echelon_bin = shutil.which("echelon") or sys.argv[0]
    resolved_workspace_root = workspace_root.resolve() if workspace_root else None
    source_ids = source_ids or {}
    source_git_roles = source_git_roles or {}

    def _implementation_target(target: Path) -> str:
        target_resolved = target.resolve()
        if resolved_workspace_root is not None:
            try:
                return target_resolved.relative_to(resolved_workspace_root).as_posix() or "."
            except ValueError:
                pass
        return source_ids.get(str(target_resolved), target.name)

    declared_targets = [_implementation_target(target) for target in targets]

    results: dict[str, int] = {}
    lock = threading.Lock()
    ordered_targets, task_ids_by_target = _target_execution_plan(
        spec_id=spec_id,
        targets=targets,
        workspace_root=resolved_workspace_root,
        command=command,
    )

    def _run_one(target: Path) -> None:
        name = target.name
        target_resolved = target.resolve()
        target_key = str(target_resolved)
        target_workspace_root = resolved_workspace_root or target_resolved.parent
        source_id = source_ids.get(target_key, name)
        target_workspace_git_role = (
            workspace_git_role
            or ("source" if target_workspace_root == target_resolved and source_id == "." else "orchestration")
        )
        source_git_role = source_git_roles.get(target_key, "source")
        cmd = [echelon_bin, "harness", command, spec_id] + extra_args
        env = os.environ.copy()
        env["ECHELON_POLYREPO_ROOT"] = str(target_workspace_root)
        env["ECHELON_TARGET_REPO_PATH"] = str(target_resolved)
        env["ECHELON_TARGET_REPO_NAME"] = name
        env["ECHELON_WORKSPACE_ROOT"] = str(target_workspace_root)
        env["ECHELON_WORKSPACE_GIT_ROLE"] = target_workspace_git_role
        env["ECHELON_SOURCE_ROOT"] = str(target_resolved)
        env["ECHELON_SOURCE_ID"] = source_id
        env["ECHELON_SOURCE_GIT_ROLE"] = source_git_role
        env["ECHELON_IMPLEMENTATION_TARGET"] = _implementation_target(target)
        env["ECHELON_DECLARED_TARGETS"] = ",".join(declared_targets)
        target_task_ids = task_ids_by_target.get(target_key)
        if target_task_ids:
            env["ECHELON_TARGET_TASK_IDS"] = ",".join(target_task_ids)
        proc = subprocess.Popen(
            cmd,
            cwd=str(target),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            with lock:
                sys.stdout.write(f"[{name}] {line}")
                sys.stdout.flush()
        proc.wait()
        with lock:
            results[name] = proc.returncode

    if task_ids_by_target and len(ordered_targets) > 1:
        # Target builds share the canonical tasks.md progress ledger. Execute in
        # dependency order so each subprocess can update it without write races.
        for target in ordered_targets:
            _run_one(target)
            if results.get(target.name, 1) != 0:
                break
    else:
        threads = [threading.Thread(target=_run_one, args=(t,)) for t in ordered_targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    print()
    all_ok = True
    for name in sorted(results):
        rc = results[name]
        status = "✓" if rc == 0 else "✗"
        print(f"{status} [{name}]: exit {rc}")
        if rc != 0:
            all_ok = False

    return 0 if all_ok else 1


def _target_execution_plan(
    *,
    spec_id: str,
    targets: List[Path],
    workspace_root: Path | None,
    command: str,
) -> tuple[List[Path], dict[str, tuple[str, ...]]]:
    """Return dependency-ordered targets and their canonical task IDs."""
    if (
        len(targets) <= 1
        or command not in {"run", "resume", "continue"}
        or workspace_root is None
    ):
        return targets, {}
    spec_dir = find_spec_dir(spec_id, workspace_root)
    tasks_path = spec_dir / "tasks.md" if spec_dir is not None else None
    if tasks_path is None or not tasks_path.is_file():
        return targets, {}

    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    analysis = analyze_task_targets(markdown)
    target_by_rel: dict[str, Path] = {}
    for target in targets:
        try:
            rel = target.resolve().relative_to(workspace_root).as_posix()
        except ValueError:
            return targets, {}
        target_by_rel[rel] = target
    if set(target_by_rel) != set(analysis.target_tasks):
        return targets, {}
    if analysis.unowned_tasks or analysis.cross_target_tasks:
        return targets, {}

    owner_by_task = {
        task_id: target
        for target, task_ids in analysis.target_tasks.items()
        for task_id in task_ids
    }
    dependencies: dict[str, set[str]] = {target: set() for target in target_by_rel}
    for task in parse_task_rows(markdown):
        owner = owner_by_task.get(task.task_id)
        if owner is None:
            continue
        for dependency_id in task.dependencies:
            dependency_owner = owner_by_task.get(dependency_id)
            if dependency_owner is not None and dependency_owner != owner:
                dependencies[owner].add(dependency_owner)

    ordered_rel: list[str] = []
    remaining = {target: set(required) for target, required in dependencies.items()}
    while remaining:
        ready = sorted(target for target, required in remaining.items() if not required)
        if not ready:
            # A cross-target dependency cycle cannot be serialized safely.
            return targets, {}
        for target in ready:
            ordered_rel.append(target)
            remaining.pop(target)
        for required in remaining.values():
            required.difference_update(ready)

    return (
        [target_by_rel[target] for target in ordered_rel],
        {
            str(target_by_rel[target].resolve()): analysis.target_tasks[target]
            for target in ordered_rel
        },
    )
