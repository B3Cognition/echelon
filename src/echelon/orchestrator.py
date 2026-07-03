"""Multi-target orchestrator: run 'echelon harness run' in parallel across sub-repos."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Mapping, Optional


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
            "  Fix: run 'echelon spec target <spec_id> <repo>'.",
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
) -> int:
    """Run 'echelon harness run <spec_id> [extra_args]' in each target in parallel.

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

    results: dict[str, int] = {}
    lock = threading.Lock()

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
        cmd = [echelon_bin, "harness", "run", spec_id] + extra_args
        env = os.environ.copy()
        env["ECHELON_POLYREPO_ROOT"] = str(target_workspace_root)
        env["ECHELON_TARGET_REPO_PATH"] = str(target_resolved)
        env["ECHELON_TARGET_REPO_NAME"] = name
        env["ECHELON_WORKSPACE_ROOT"] = str(target_workspace_root)
        env["ECHELON_WORKSPACE_GIT_ROLE"] = target_workspace_git_role
        env["ECHELON_SOURCE_ROOT"] = str(target_resolved)
        env["ECHELON_SOURCE_ID"] = source_id
        env["ECHELON_SOURCE_GIT_ROLE"] = source_git_role
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

    threads = [threading.Thread(target=_run_one, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print()
    all_ok = True
    for name in sorted(results):
        rc = results[name]
        status = "✓" if rc == 0 else "✗"
        print(f"{status} [{name}]: exit {rc}")
        if rc != 0:
            all_ok = False

    return 0 if all_ok else 1
