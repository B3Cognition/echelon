"""Typed application services for Phase A/spec commands."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn

from echelon.ui import banner
from harness.issue_identity import matching_issue_resolution, record_issue_resolution
from harness.provider_capability import ProviderCapability


def add_input(project_root: Path, *, input_values: Sequence[str]) -> None:
    """Attach declared product evidence to the active Phase A run."""
    from echelon.product_inputs import ProductInputError
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run

    values = [value.strip() for value in input_values]
    if not values:
        print(
            "Usage: echelon spec add-input --input reference:<path> "
            "[--input reference:<path>...]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        result = add_input_to_active_run(project_root, values)
    except (ProductInputError, SpecAddInputError) as exc:
        print(f"✗ echelon spec add-input: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    banner(
        "INPUT ADDED" if result.added_count else "INPUT ALREADY DECLARED",
        [
            ("Run", result.run_dir.name),
            ("Attachment", result.attachment_id),
            ("Added resources", str(result.added_count)),
            ("Duplicate resources", str(result.duplicate_count)),
            ("Original inputs", _format_product_inputs(result.original_declarations)),
            ("Attached inputs", _format_product_inputs(result.attached_declarations)),
            ("Next", result.next_command),
        ],
    )


def _format_product_inputs(declarations: Sequence[Mapping[str, object]]) -> str:
    rendered = [
        f"{item.get('role')}:{item.get('location')}"
        for item in declarations
        if isinstance(item, Mapping)
    ]
    return ", ".join(rendered) if rendered else "(none)"


def resolve_issue(
    project_root: Path,
    *,
    issue_id: str,
    decision: str | None,
    extra_args: Sequence[str] = (),
) -> None:
    """Record one issue decision and prepare its targeted Phase 1 repair."""
    from echelon import cli as shared

    shared._installed_extension_or_exit(project_root)
    shared._require_provider_capability(
        "echelon spec resolve",
        ProviderCapability.ARTIFACT,
        project_dir=project_root,
    )
    decision_parts = ([decision] if decision is not None else []) + list(extra_args)
    _resolve_issue(
        project_root,
        issue_id=issue_id,
        decision=" ".join(decision_parts),
    )


def _resolve_issue(project_root: Path, *, issue_id: str, decision: str) -> None:
    from echelon import cli as shared
    from harness.squad_state import SquadStateStore

    normalized_issue_id = issue_id.strip().upper()
    normalized_decision = decision.strip()
    if not re.fullmatch(r"ISS-\d+", normalized_issue_id) or not normalized_decision:
        print(
            "✗ resolve requires an ISS-<n> id and a non-empty decision",
            file=sys.stderr,
        )
        raise SystemExit(2)
    squad_dir = shared._find_current_run_dir(project_root)
    if squad_dir is None:
        print("✗ No active squad run found.", file=sys.stderr)
        raise SystemExit(1)

    store = SquadStateStore(squad_dir)
    state = store.load()
    requests = shared._issue_resolution_requests(project_root, squad_dir, state)
    matching = next(
        (item for item in requests if item["issue_id"] == normalized_issue_id),
        None,
    )
    if matching is None:
        print(
            f"✗ {normalized_issue_id} is not an unresolved issue in the active run.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    ledger = state.get("issue_resolution_ledger")
    if not isinstance(ledger, dict):
        ledger = {}
    existing = matching_issue_resolution(ledger, matching["issue_fingerprint"])
    if existing:
        existing_status = str(existing.get("status") or "").strip()
        existing_decision = " ".join(str(existing.get("decision") or "").split())
        collapsed_decision = " ".join(normalized_decision.split())
        if existing_status == "validated":
            print(
                f"[squad] {normalized_issue_id} is already validated; "
                "no resolution was changed.",
                flush=True,
            )
            return
        if (
            existing_status in {"selected", "repaired"}
            and existing_decision == collapsed_decision
        ):
            print(
                f"[squad] {normalized_issue_id} is already recorded with this "
                "decision; no resolution was changed.\n"
                "[squad] next: echelon spec continue",
                flush=True,
            )
            return
    unresolved_before = [
        item["issue_id"]
        for item in requests
        if matching_issue_resolution(ledger, item["issue_fingerprint"]).get("status")
        != "validated"
    ]
    if unresolved_before and unresolved_before[0] != normalized_issue_id:
        print(
            f"✗ Resolve {unresolved_before[0]} before {normalized_issue_id}; "
            "issues are handled in SAGE order.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    repair_phase = str(matching.get("repair_phase") or "phase1-what").strip()
    if repair_phase not in {"phase1-discover", "phase1-what"}:
        print(
            f"✗ {normalized_issue_id} has unsupported Phase 1 repair owner "
            f"{repair_phase!r}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    ledger = record_issue_resolution(
        ledger,
        normalized_issue_id,
        {
            **matching,
            "status": "selected",
            "decision": normalized_decision,
            "repair_phase": repair_phase,
        },
    )
    state["issue_resolution_ledger"] = ledger
    state["selected_issue_resolution"] = normalized_issue_id
    state.pop("issue_resolution_revalidation_attempted", None)
    state["issue_resolution_repair_baseline"] = {
        "issue_id": normalized_issue_id,
        "repair_phase": repair_phase,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    state["issue_resolution_recovery"] = {
        "issue_id": normalized_issue_id,
        "from_phase": "phase1-why2",
        "to_phase": repair_phase,
        "reason": "issue_resolution",
    }
    dispatch_counts = state.get("phase_dispatch_counts")
    if isinstance(dispatch_counts, dict):
        reset_phases = {
            "phase1-what",
            "phase1-understanding",
            "phase1-why2",
            "phase1-lexicon-derive",
            "phase1-lexicon",
            "checkpoint-assess",
        }
        if repair_phase == "phase1-discover":
            reset_phases.update(
                {
                    "phase1-discover",
                    "phase1-synthesizer",
                    "phase1-modeler",
                    "phase1-tracker",
                    "phase1-why1",
                    "phase1-constitution",
                }
            )
        state["phase_dispatch_counts"] = {
            phase: count
            for phase, count in dispatch_counts.items()
            if phase not in reset_phases
        }
    state["phase"] = repair_phase
    state["status"] = "running"
    for key in (
        "blocked_reason",
        "escalation_question",
        "escalation_options",
        "blocked_decision",
        "phase_dispatch_limit",
        "phase_dispatch_limit_phase",
    ):
        state.pop(key, None)
    state["phase_dispatch_limit_recovery"] = {
        "phase": repair_phase,
        "resolver": "issue_resolution",
    }
    store.save(state)
    print(
        f"[squad] recorded resolution for {normalized_issue_id}; the controller "
        "will validate and consume the declared WHY2 → WHAT recovery edge.\n"
        "[squad] next: echelon spec continue",
        flush=True,
    )


def drop_target(
    project_root: Path,
    *,
    spec_id: str,
    target: str,
    confirm: bool,
) -> None:
    """Remove one unreferenced target from an active unfinished spec."""
    _drop_target(
        project_root,
        spec_id=spec_id.strip().rstrip("/"),
        target=target.strip().rstrip("/"),
        confirm=confirm,
        mutation_locked=False,
    )


def _drop_target(
    project_root: Path,
    *,
    spec_id: str,
    target: str,
    confirm: bool,
    mutation_locked: bool,
) -> None:
    from echelon import cli as shared

    if not spec_id or not target:
        print("✗ spec id and target must not be empty", file=sys.stderr)
        raise SystemExit(1)
    if confirm and not mutation_locked:
        from echelon.spec_lifecycle import (
            PhaseAExecutionLock,
            SpecLifecycleLocked,
            SpecMutationLock,
        )

        operation_id = f"drop-target-{os.getpid()}"
        try:
            with SpecMutationLock.acquire(project_root, spec_id, operation_id):
                with PhaseAExecutionLock.acquire(project_root, operation_id):
                    return _drop_target(
                        project_root,
                        spec_id=spec_id,
                        target=target,
                        confirm=confirm,
                        mutation_locked=True,
                    )
        except SpecLifecycleLocked as exc:
            print(
                "✗ Cannot drop a target while the spec mutation lease is owned by "
                f"{exc.operation_id}.",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    squad_dir = shared._find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").is_file():
        print("✗ No active squad run found.", file=sys.stderr)
        raise SystemExit(1)

    from harness.spec_frontmatter import write_targets
    from harness.squad_state import SquadStateStore
    from harness.task_targets import analyze_task_targets

    store = SquadStateStore(squad_dir)
    state = store.load()
    active_spec_id = str(state.get("spec_id") or "").strip()
    if active_spec_id != spec_id:
        print(
            f"✗ Active run owns spec {active_spec_id or '(unknown)'!r}, "
            f"not {spec_id!r}.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if str(state.get("status") or "") == "done":
        print(
            "✗ Cannot drop a target from a completed spec. "
            "Start a new spec run instead.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    declared = [
        str(value).strip().rstrip("/")
        for value in state.get("implementation_targets") or []
        if str(value).strip()
    ]
    if target not in declared:
        print(f"✗ Target {target!r} is not declared by the active run.", file=sys.stderr)
        raise SystemExit(1)
    replacement_targets = [value for value in declared if value != target]
    if not replacement_targets:
        print("✗ A spec must retain at least one implementation target.", file=sys.stderr)
        raise SystemExit(1)

    spec_dir, spec_dir_ref = shared._normalize_rewind_spec_dir(project_root, state)
    if spec_dir is None or spec_dir_ref is None:
        print(
            "✗ Could not resolve the active spec directory from state.json.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    tasks_file = spec_dir / "tasks.md"
    if tasks_file.is_file():
        analysis = analyze_task_targets(tasks_file.read_text(encoding="utf-8"))
        owned_tasks = analysis.target_tasks.get(target, ())
        if owned_tasks:
            print(
                f"✗ Cannot drop {target!r}: it owns task(s) "
                f"{', '.join(owned_tasks)}.\n"
                "  Re-author the target decision before changing delivery scope.",
                file=sys.stderr,
            )
            raise SystemExit(1)

    planning_outputs = shared._REWIND_CLEANUP_OUTPUTS["phase3-plan"]
    if not confirm:
        banner(
            "DROP TARGET PREVIEW",
            [
                ("spec", spec_id),
                ("remove", target),
                ("remain", ", ".join(replacement_targets)),
                ("invalidate", ", ".join(planning_outputs)),
                ("next", f"echelon spec drop-target {spec_id} {target} --confirm"),
            ],
            subtitle="No files or run state changed.",
        )
        return

    from echelon.rewind import RewindError

    try:
        updated = shared._reset_rewind_state(state, "phase3-plan", spec_dir_ref)
    except RewindError as exc:
        print(f"✗ Cannot drop target: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    spec_dirs = [spec_dir]
    published_ref = str(state.get("published_spec_dir") or "").strip()
    if published_ref:
        published_dir = Path(published_ref)
        if not published_dir.is_absolute():
            published_dir = project_root / published_dir
        if published_dir.is_dir() and published_dir not in spec_dirs:
            spec_dirs.append(published_dir)
    removed: list[str] = []
    for directory in spec_dirs:
        write_targets(directory, replacement_targets)
        for name in planning_outputs:
            output = directory / name
            if output.exists():
                output.unlink()
                if name not in removed:
                    removed.append(name)
    updated["implementation_targets"] = replacement_targets
    updated["tasks_lexicon_pass"] = None
    updated["target_change"] = {
        "action": "drop-unused-target",
        "removed": target,
        "remaining": replacement_targets,
        "invalidated_outputs": removed,
    }
    store.save(updated)
    banner(
        "TARGET REMOVED",
        [
            ("spec", spec_id),
            ("removed", target),
            ("targets", ", ".join(replacement_targets)),
            ("invalidated", ", ".join(removed) if removed else "(none)"),
            ("next", "echelon spec continue"),
        ],
        subtitle="Task planning will be regenerated for the remaining targets.",
    )


def show_targets(project_root: Path, *, spec_id: str) -> None:
    """Display every canonical task grouped by source target."""
    from harness.spec_frontmatter import find_spec_dir, read_targets
    from harness.task_targets import analyze_task_targets

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        print(f"✗ Spec '{spec_id}' not found (searched from {project_root})", file=sys.stderr)
        raise SystemExit(1)
    tasks_file = spec_dir / "tasks.md"
    if not tasks_file.is_file():
        print(
            f"✗ Spec {spec_dir.name}: canonical tasks file not found: {tasks_file}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    analysis = analyze_task_targets(tasks_file.read_text(encoding="utf-8"))

    def normalize_target(value: str) -> str:
        normalized = str(value).strip().replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.rstrip("/") or "."

    declared_targets = tuple(
        sorted(
            {
                normalize_target(target)
                for target in read_targets(spec_dir)
                if str(target).strip()
            }
        )
    )
    declared_set = set(declared_targets)
    referenced_targets = set(analysis.target_tasks)
    for targets in analysis.cross_target_tasks.values():
        referenced_targets.update(targets)
    missing_targets = tuple(sorted(referenced_targets - declared_set))
    unreferenced_targets = tuple(sorted(declared_set - referenced_targets))

    def task_line(task_id: str, *, target_suffix: str = "") -> str:
        title = analysis.task_titles.get(task_id, "")
        label = f"{task_id}  {title}" if title else task_id
        return f"  {label}{target_suffix}"

    print(f"Spec: {spec_dir.name}")
    print("Declared targets:")
    for target in declared_targets:
        print(f"  {target}")
    if not declared_targets:
        print("  (none)")
    for target, task_ids in analysis.target_tasks.items():
        status = "declared" if target in declared_set else "missing declaration"
        print(f"\n{target} [{status}]")
        for task_id in task_ids:
            print(task_line(task_id))
    if analysis.unowned_tasks:
        print("\nUNOWNED")
        for task_id in analysis.unowned_tasks:
            print(task_line(task_id))
    if analysis.cross_target_tasks:
        print("\nCROSS-TARGET")
        for task_id, targets in analysis.cross_target_tasks.items():
            print(task_line(task_id, target_suffix=f" [{', '.join(targets)}]"))
    non_cross_mismatches = {
        task_id: mismatch
        for task_id, mismatch in analysis.path_target_mismatches.items()
        if task_id not in analysis.cross_target_tasks
    }
    if non_cross_mismatches:
        print("\nTARGET/PATH MISMATCH")
        for task_id, (target, paths) in non_cross_mismatches.items():
            print(f"  mismatch {task_id}: target={target}; paths={', '.join(paths)}")
    if missing_targets:
        print("\nMissing declared targets:")
        for target in missing_targets:
            print(f"  {target}")
    if unreferenced_targets:
        print("\nDeclared but unreferenced targets:")
        for target in unreferenced_targets:
            print(f"  {target}")
    assigned_count = sum(len(task_ids) for task_ids in analysis.target_tasks.values())
    print(
        f"\nTasks: {len(analysis.all_task_ids)} total; {assigned_count} assigned; "
        f"{len(analysis.unowned_tasks)} unowned; "
        f"{len(analysis.cross_target_tasks)} cross-target"
    )
    invalid_reasons: list[str] = []
    if missing_targets:
        invalid_reasons.append(f"{len(missing_targets)} missing declaration(s)")
    if unreferenced_targets:
        invalid_reasons.append(
            f"{len(unreferenced_targets)} unreferenced declaration(s)"
        )
    if analysis.unowned_tasks:
        invalid_reasons.append(f"{len(analysis.unowned_tasks)} unowned task(s)")
    if analysis.cross_target_tasks:
        invalid_reasons.append(f"{len(analysis.cross_target_tasks)} cross-target task(s)")
    if analysis.path_target_mismatches:
        invalid_reasons.append(
            f"{len(analysis.path_target_mismatches)} target/path mismatch(es)"
        )
    if invalid_reasons:
        print("Result: invalid — " + ", ".join(invalid_reasons))
        raise SystemExit(2)
    print("Result: valid")


def write_artifacts(
    project_root: Path,
    *,
    spec_id: str,
    extra_args: Sequence[str] = (),
) -> None:
    """Write the canonical artifact map for one spec."""
    del extra_args
    from echelon.artifact_index import write_artifact_index
    from harness.spec_frontmatter import find_spec_dir

    spec_dir = find_spec_dir(spec_id, project_root)
    if spec_dir is None:
        print(f"✗ Spec not found: {spec_id}", file=sys.stderr)
        raise SystemExit(1)
    path = write_artifact_index(spec_dir)
    print(f"✓ Wrote artifact map: {path}")


def prepare_amendment(
    project_root: Path,
    *,
    spec_id: str,
    description: str,
    input_values: Sequence[str],
    dry_run: bool,
    extra_args: Sequence[str] = (),
) -> None:
    """Prepare, inspect, or abandon a pre-build amendment."""
    from echelon.spec_amendment import (
        abandon_amendment,
        load_amendment_state,
        prepare_amendment as prepare,
    )

    args = [spec_id, description, *extra_args]
    for value in input_values:
        args.extend(("--input", value))
    if dry_run:
        args.append("--dry-run")
    if args[0] == "status":
        if len(args) != 2:
            print(
                "Usage: echelon spec amend status <amendment-id-or-spec-id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        print(json.dumps(load_amendment_state(project_root, args[1]), indent=2))
        return
    if args[0] == "abandon":
        if len(args) != 2:
            print(
                "Usage: echelon spec amend abandon <amendment-id-or-spec-id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        state = abandon_amendment(project_root, args[1])
        print(f"Amendment abandoned: {state['amendment_id']}")
        return
    result = prepare(project_root, args)
    if result.dry_run:
        print(
            f"Amendment dry run: {result.amendment_id}\n"
            f"  baseline: {result.baseline.branch}@{result.baseline.commit}\n"
            "  no worktree or amendment state was created"
        )
        return
    assert result.worktree is not None and result.state_path is not None
    print(
        f"Amendment prepared: {result.amendment_id}\n"
        f"  baseline: {result.baseline.branch}@{result.baseline.commit}\n"
        f"  worktree: {result.worktree.path}\n"
        f"  state: {result.state_path}\n"
        "  No canonical spec, plan, or task artifact has been changed.\n"
        "  Next: inspect change-request.md and impact.md in the amendment worktree."
    )


def reject_target_mutation() -> NoReturn:
    """Reject the retired post-authoring target mutation route."""
    print(
        "✗ echelon spec target no longer mutates generated specifications.\n"
        "  Implementation targets must be declared when authoring begins:\n"
        "    echelon spec run <description> --target <source-path> "
        "[--target <source-path> ...]\n"
        "  Changing targets afterward invalidates target-dependent artifacts; "
        "start a new spec run instead.",
        file=sys.stderr,
    )
    raise SystemExit(2)
