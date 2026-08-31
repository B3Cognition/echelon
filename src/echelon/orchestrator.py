"""Multi-target orchestrator for target-scoped workspace delivery."""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import List, Mapping, Optional

from harness.spec_frontmatter import find_spec_dir, read_canonical_target_entries
from harness.task_targets import analyze_task_targets
from kernel.task_contract import parse_task_rows


_ECHELON_YML_REL = ".echelon/config.yml"


def _serialize_target_contract(value: object, *, location: str) -> str:
    """Return deterministic JSON after rejecting values JSON cannot preserve."""

    def _validate(item: object, item_location: str) -> None:
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if math.isfinite(item):
                return
            raise ValueError(f"{item_location} contains a non-finite number")
        if isinstance(item, list):
            for index, child in enumerate(item):
                _validate(child, f"{item_location}[{index}]")
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise TypeError(
                        f"{item_location} contains a non-string key "
                        f"of type {type(key).__name__}"
                    )
                _validate(child, f"{item_location}.{key}")
            return
        raise TypeError(
            f"{item_location} contains unsupported {type(item).__name__} value"
        )

    _validate(value, location)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
    aggregate_summary = (
        resolved_workspace_root is not None
        and command in {"run", "continue", "resume"}
    )
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
    target_contracts: list[dict[str, object]] = []
    if resolved_workspace_root is not None:
        contract_spec_dir = find_spec_dir(spec_id, resolved_workspace_root)
        if contract_spec_dir is not None:
            target_contracts = [
                dict(entry)
                for entry in read_canonical_target_entries(contract_spec_dir)
            ]
    contract_by_path = {
        str(entry.get("path") or ""): entry
        for entry in target_contracts
        if str(entry.get("path") or "")
    }
    try:
        target_contracts_json = _serialize_target_contract(
            target_contracts,
            location="canonical targets",
        )
        contract_json_by_path = {
            path: _serialize_target_contract(
                entry,
                location=f"canonical target {path!r}",
            )
            for path, entry in contract_by_path.items()
        }
    except (TypeError, ValueError) as exc:
        print(
            "✗ Cannot dispatch delivery: canonical target contract is not "
            f"JSON-safe.\n  Error: {exc}",
            file=sys.stderr,
        )
        return 1

    results: dict[int, int] = {}
    lock = threading.Lock()
    (
        ordered_targets,
        task_ids_by_target,
        dependencies_by_target,
    ) = _target_execution_plan(
        spec_id=spec_id,
        targets=targets,
        workspace_root=resolved_workspace_root,
        command=command,
    )

    basename_counts = Counter(target.name for target in ordered_targets)
    label_candidates: list[str] = []
    for target in ordered_targets:
        label = target.name
        if basename_counts[label] > 1:
            target_resolved = target.resolve()
            if resolved_workspace_root is not None:
                try:
                    label = target_resolved.relative_to(
                        resolved_workspace_root
                    ).as_posix()
                except ValueError:
                    label = str(target_resolved)
            else:
                label = str(target_resolved)
        label_candidates.append(label)
    label_counts = Counter(label_candidates)
    label_occurrences: Counter[str] = Counter()
    display_labels: list[str] = []
    for label in label_candidates:
        label_occurrences[label] += 1
        display_labels.append(
            f"{label}#{label_occurrences[label]}"
            if label_counts[label] > 1
            else label
        )
    target_runs = list(enumerate(zip(ordered_targets, display_labels)))

    def _run_one(result_id: int, target: Path, display_label: str) -> None:
        name = target.name
        try:
            target_resolved = target.resolve()
            target_key = str(target_resolved)
            target_workspace_root = resolved_workspace_root or target_resolved.parent
            source_id = source_ids.get(target_key, name)
            target_workspace_git_role = (
                workspace_git_role
                or (
                    "source"
                    if target_workspace_root == target_resolved and source_id == "."
                    else "orchestration"
                )
            )
            source_git_role = source_git_roles.get(target_key, "source")
            cmd = [echelon_bin, "delivery", command, spec_id] + extra_args
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
            if aggregate_summary:
                env["ECHELON_SUPPRESS_RUN_SUMMARY"] = "1"
            expected_contract_json = contract_json_by_path.get(
                env["ECHELON_IMPLEMENTATION_TARGET"]
            )
            if expected_contract_json is not None:
                env["ECHELON_TARGET_CONTRACT_JSON"] = expected_contract_json
                env["ECHELON_TARGETS_CONTRACT_JSON"] = target_contracts_json
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
            reported_blocked = False
            for line in proc.stdout:
                if "HARNESS — BLOCKED" in line or "✗ BLOCKED" in line:
                    reported_blocked = True
                with lock:
                    sys.stdout.write(f"[{display_label}] {line}")
                    sys.stdout.flush()
            proc.wait()
            returncode = proc.returncode or (1 if reported_blocked else 0)
        except Exception as exc:
            with lock:
                print(
                    f"✗ [{display_label}]: delivery worker failed: {exc}",
                    file=sys.stderr,
                )
                results[result_id] = 1
            return
        with lock:
            results[result_id] = returncode

    if task_ids_by_target and len(ordered_targets) > 1:
        # Target builds share the canonical tasks.md progress ledger. Execute in
        # dependency order so each subprocess can update it without write races.
        # A failed target blocks only its dependency descendants; unrelated
        # targets must still receive their own delivery attempt.
        failed_targets: set[str] = set()
        for result_id, (target, display_label) in target_runs:
            target_key = str(target.resolve())
            failed_dependencies = [
                dependency
                for dependency in dependencies_by_target.get(target_key, ())
                if dependency in failed_targets
            ]
            if failed_dependencies:
                results[result_id] = 1
                failed_targets.add(target_key)
                dependency_labels = ", ".join(
                    Path(dependency).name for dependency in failed_dependencies
                )
                print(
                    f"✗ [{display_label}]: skipped because dependency target(s) "
                    f"failed: {dependency_labels}",
                    file=sys.stderr,
                )
                continue
            _run_one(result_id, target, display_label)
            if results.get(result_id, 1) != 0:
                failed_targets.add(target_key)
    else:
        threads = [
            threading.Thread(
                target=_run_one,
                args=(result_id, target, display_label),
            )
            for result_id, (target, display_label) in target_runs
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    print()
    all_ok = True
    for result_id, (_target, display_label) in sorted(
        target_runs,
        key=lambda target_run: (target_run[1][1], target_run[0]),
    ):
        rc = results.get(result_id, 1)
        status = "✓" if rc == 0 else "✗"
        print(f"{status} [{display_label}]: exit {rc}")
        if rc != 0:
            all_ok = False

    if aggregate_summary:
        _print_multi_target_summary(
            spec_id=spec_id,
            command=command,
            workspace_root=resolved_workspace_root,
            target_runs=target_runs,
            results=results,
            all_ok=all_ok,
        )

    return 0 if all_ok else 1


def _print_multi_target_summary(
    *,
    spec_id: str,
    command: str,
    workspace_root: Path,
    target_runs: list[tuple[int, tuple[Path, str]]],
    results: Mapping[int, int],
    all_ok: bool,
) -> None:
    """Render one narrative for the parent multi-target CLI invocation."""
    from echelon.ui import banner
    from harness.run_summary import (
        RunSummaryContext,
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
        summarize_run_for_cli,
    )

    target_facts = tuple(
        SummaryFact(
            SummaryFactCategory.OUTCOME,
            (
                SummaryFactImportance.HIGH
                if results.get(result_id, 1) == 0
                else SummaryFactImportance.CRITICAL
            ),
            (
                f"Target {label} completed successfully."
                if results.get(result_id, 1) == 0
                else f"Target {label} returned exit {results.get(result_id, 1)}."
            ),
            order,
        )
        for order, (result_id, (_target, label)) in enumerate(target_runs)
    )
    next_step = (
        "Review the target delivery results above before choosing the next command."
    )
    worked_on = summarize_run_for_cli(
        RunSummaryContext(
            project_root=workspace_root,
            command=f"echelon delivery {command}",
            task=f"Deliver spec {spec_id} across its declared workspace targets.",
            status="returned",
            facts=target_facts,
            next_step=next_step,
        )
    )
    banner(
        "DELIVERY SUMMARY",
        [
            ("targets", f"{len(target_runs)} total"),
            ("worked on", worked_on),
            ("next", next_step),
        ],
        subtitle=("Target workers returned." if all_ok else "A target worker failed."),
    )


def _target_execution_plan(
    *,
    spec_id: str,
    targets: List[Path],
    workspace_root: Path | None,
    command: str,
) -> tuple[
    List[Path],
    dict[str, tuple[str, ...]],
    dict[str, tuple[str, ...]],
]:
    """Return ordered targets, owned task IDs, and target dependencies."""
    if command not in {"run", "resume", "continue"} or workspace_root is None:
        return targets, {}, {}
    spec_dir = find_spec_dir(spec_id, workspace_root)
    tasks_path = spec_dir / "tasks.md" if spec_dir is not None else None
    if tasks_path is None or not tasks_path.is_file():
        return targets, {}, {}

    markdown = tasks_path.read_text(encoding="utf-8", errors="replace")
    analysis = analyze_task_targets(markdown)
    target_by_rel: dict[str, Path] = {}
    for target in targets:
        try:
            rel = target.resolve().relative_to(workspace_root).as_posix()
        except ValueError:
            return targets, {}, {}
        target_by_rel[rel] = target
    if set(target_by_rel) != set(analysis.target_tasks):
        return targets, {}, {}
    if analysis.unowned_tasks or analysis.cross_target_tasks:
        return targets, {}, {}

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
            return targets, {}, {}
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
        {
            str(target_by_rel[target].resolve()): tuple(
                str(target_by_rel[dependency].resolve())
                for dependency in sorted(dependencies[target])
            )
            for target in ordered_rel
        },
    )
