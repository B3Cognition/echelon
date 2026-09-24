"""Typed application services for Phase A/spec commands."""

from __future__ import annotations

import json
import os
import re
import hashlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import NoReturn, Optional

from echelon.ui import banner
from echelon.ui import banner as _banner
from harness.banzai_protocol import active_banzai_default_protocol_fingerprint
from harness.issue_identity import (
    issue_fingerprint,
    matching_issue_resolution,
    record_issue_resolution,
)
from harness.provider_capability import ProviderCapability
from harness.phase1_quality import has_current_phase1_quality_prerequisite
from harness.phase_a_readiness import coverage_contract_error, validate_phase_a_readiness
from harness.recovery_instruction import (
    RecoveryInstruction,
    RecoveryInstructionError,
    RecoveryKind,
    retry_phase_recovery,
    validate_recovery_instruction,
)
from harness.squad_state import (
    StateAdvanceError,
    validate_banzai_default_reassessment_record,
    validate_banzai_evidence_reassessment_record,
)
from harness.stacks.errors import StackError
from echelon.stack_selection import StackSelectionError, get_stack_selection

from echelon.cli import (
    _active_versioned_decision,
    _command_display,
    _copy_missing_tree,
    _ensure_runs_gitignore,
    _find_current_run_dir,
    _find_latest_harness_build_state,
    _iter_harness_build_states,
    _load_cli_config,
    _load_stack_definitions_for_project,
    _print_legacy_branchless_recovery_notice,
    _project_echelon_config,
    _repo_relative_or_absolute,
    _require_provider_capability,
    _v2_automatic_decision_is_registered,
    _validated_versioned_decision,
    _workspace_git_preflight,
    _workspace_git_present,
)


LEXICON_TASK_SPEC_REF_PATH = "lexicon_gate.artifacts.tasks.spec_ref"
_SPEC_SUMMARY_COMMAND: ContextVar[str] = ContextVar(
    "echelon_spec_summary_command",
    default="echelon spec run",
)


@dataclass
class _SpecSummaryScope:
    project_root: Path
    command: str
    run_dir: Path | None = None
    mode: str = "semi"
    message: str = ""
    implementation_targets: tuple[str, ...] = ()
    emitted: bool = False
    next_already_printed: bool = False


_SPEC_SUMMARY_SCOPE: ContextVar[_SpecSummaryScope | None] = ContextVar(
    "echelon_spec_summary_scope",
    default=None,
)


@dataclass(frozen=True)
class SpecRunRequest:
    description: str | None = None
    extra_args: tuple[str, ...] = ()
    mode: str | None = None
    reset: bool = False
    perfectionist: bool = False
    init: bool = False
    message: str | None = None
    next_phase: str | None = None
    targets: tuple[str, ...] = ()
    input_values: tuple[str, ...] = ()
    ignore_re: bool = False
    stash: bool = False
    discard: bool = False
    confirm: bool = False


@dataclass(frozen=True)
class SpecRetargetRequest:
    spec_id: str
    targets: tuple[str, ...]
    confirm_count: int = 0


@dataclass(frozen=True)
class SpecRewindRequest:
    phase_id: str
    extra_args: tuple[str, ...] = ()
    checkpoint_commit: str | None = None
    checkpoint_next_phase: str | None = None
    confirm: bool = False


def _append_option(args: list[str], option: str, value: str | None) -> None:
    if value is not None:
        args.extend((option, value))


def run_spec(project_root: Path, request: SpecRunRequest) -> None:
    """Run or resume Phase A spec authoring from typed command values."""
    if os.environ.get("ECHELON_SQUAD_ACTIVE"):
        print(
            "✗ echelon spec run: refusing nested invocation — already inside a squad "
            "agent dispatch (ECHELON_SQUAD_ACTIVE is set).\n"
            "  Squad agents must not call 'echelon spec run'. "
            "Return echelon_result: from your agent instead.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    args = ([request.description] if request.description is not None else [])
    args.extend(request.extra_args)
    _append_option(args, "--mode", request.mode)
    if request.reset:
        args.append("--reset")
    if request.perfectionist:
        args.append("--perfectionist")
    if request.init:
        args.append("--init")
    _append_option(args, "--message", request.message)
    _append_option(args, "--next-phase", request.next_phase)
    for target in request.targets:
        args.extend(("--target", target))
    for value in request.input_values:
        args.extend(("--input", value))
    if request.ignore_re:
        args.append("--ignore-re")
    if request.stash:
        args.append("--stash")
    if request.discard:
        args.append("--discard")
    if request.confirm:
        args.append("--confirm")
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    cfg_file = _project_echelon_config(project_root)
    if not cfg_file.exists():
        print(
            f"✗ Project not initialized — config not found: {cfg_file}\n"
            "  Run: echelon workspace init",
            file=sys.stderr,
        )
        raise SystemExit(1)
    _require_provider_capability(
        "echelon spec run", ProviderCapability.ARTIFACT, project_dir=project_root
    )
    with _spec_summary_session(project_root, "echelon spec run"):
        _cmd_run(args, project_root=project_root, ext_dir=ext_dir)


def retarget_spec(project_root: Path, request: SpecRetargetRequest) -> None:
    """Preview or apply a complete implementation-target replacement."""
    from echelon.spec_retarget import RetargetError
    from echelon.spec_retarget_cli import run_spec_retarget_command

    args = [request.spec_id]
    for target in request.targets:
        args.extend(("--target", target))
    args.extend("--confirm" for _ in range(request.confirm_count))
    try:
        result = run_spec_retarget_command(args, project_root)
    except RetargetError as exc:
        print(f"✗ echelon spec retarget: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not result.applied:
        return
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    run_args = [result.original_user_message, "--mode", result.autonomy_mode]
    for target in result.replacement_targets:
        run_args.extend(("--target", target))
    for source in result.explicit_re_sources:
        run_args.extend(("--re-source", source))
    if result.ignore_re:
        run_args.append("--ignore-re")
    _cmd_run(run_args, project_root=project_root, ext_dir=ext_dir)


def show_status(project_root: Path) -> None:
    _cmd_status(project_root)


def continue_spec(
    project_root: Path,
    *,
    mode: str | None,
    extra_args: Sequence[str] = (),
) -> None:
    args = list(extra_args)
    _append_option(args, "--mode", mode)
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    _require_provider_capability(
        "echelon spec continue", ProviderCapability.ARTIFACT, project_dir=project_root
    )
    token = _SPEC_SUMMARY_COMMAND.set("echelon spec continue")
    try:
        with _spec_summary_session(project_root, "echelon spec continue"):
            _cmd_continue(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        _SPEC_SUMMARY_COMMAND.reset(token)


def resume_spec(
    project_root: Path,
    *,
    answer: str | None,
    extra_args: Sequence[str] = (),
) -> None:
    if os.environ.get("ECHELON_SQUAD_ACTIVE"):
        print(
            "✗ echelon spec resume: refusing nested invocation "
            "(ECHELON_SQUAD_ACTIVE is set).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    args = ([answer] if answer is not None else [])
    args.extend(extra_args)
    ext_dir = _installed_phase_runtime_or_exit(project_root)
    _require_provider_capability(
        "echelon spec resume", ProviderCapability.ARTIFACT, project_dir=project_root
    )
    token = _SPEC_SUMMARY_COMMAND.set("echelon spec resume")
    try:
        with _spec_summary_session(project_root, "echelon spec resume"):
            _cmd_resume(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        _SPEC_SUMMARY_COMMAND.reset(token)


def rewind_spec(project_root: Path, request: SpecRewindRequest) -> None:
    args = [request.phase_id, *request.extra_args]
    _append_option(args, "--commit", request.checkpoint_commit)
    _append_option(args, "--next-phase", request.checkpoint_next_phase)
    if request.confirm:
        args.append("--confirm")
    _cmd_rewind(args, project_root=project_root)


def repair_traceability(project_root: Path, *, confirm: bool) -> None:
    _cmd_repair_traceability(
        ["--confirm"] if confirm else [], project_root=project_root
    )


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
    requests = _issue_resolution_requests(project_root, squad_dir, state)
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

    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
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

    planning_outputs = _REWIND_CLEANUP_OUTPUTS["phase3-plan"]
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
        updated = _reset_rewind_state(state, "phase3-plan", spec_dir_ref)
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


def _workspace_git_preflight_for_squad_run(
    project_root: Path,
    *,
    command_name: str,
    user_message: str,
    reset: bool,
    manual_recovery: bool = False,
) -> None:
    if _workspace_git_present(project_root):
        return
    if reset:
        _workspace_git_preflight(project_root, command_name=command_name)

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir or not (existing_dir / "state.json").exists():
        _workspace_git_preflight(project_root, command_name=command_name)

    try:
        import json as _json

        state = _json.loads((existing_dir / "state.json").read_text(encoding="utf-8"))
    except Exception:
        _workspace_git_preflight(project_root, command_name=command_name)

    # A controller-owned issue recovery, like an explicit phase, must reuse the
    # existing run before new-spec branch/slug machinery sees its empty description.
    recovery = state.get("issue_resolution_recovery")
    manual_recovery = manual_recovery or (
        isinstance(recovery, dict)
        and recovery.get("status") not in {"consumed", "validated"}
    )
    # An explicit phase is an intentional recovery command.  It must reuse the
    # existing run before any new-spec branch/slug machinery sees its empty
    # description, including when the run is waiting on a human escalation.
    if manual_recovery:
        _print_legacy_branchless_recovery_notice(command_name)
        return

    if state.get("status") in ("running", "in_progress") and (
        not user_message or user_message == state.get("user_message", "")
    ):
        _print_legacy_branchless_recovery_notice(command_name)
        return

    _workspace_git_preflight(project_root, command_name=command_name)


_REWIND_CLEANUP_OUTPUTS: dict[str, tuple[str, ...]] = {
    "phase3-sentinel": (
        "test-strategy.md",
        "test-architecture.md",
        "coverage-map.md",
    ),
    "phase3-plan": (
        "tasks.md",
        "critical-path.md",
        "risk-matrix.md",
        "dependencies.md",
    ),
}


@dataclass(frozen=True)
class _RunRecoveryAction:
    kind: str
    reason: str = ""
    phase: str = ""
    command: str = ""
    note: str = ""


@dataclass(frozen=True)
class _RuntimeBundleCompatibility:
    compatible: bool
    command: str = ""
    note: str = ""


def _runtime_bundle_compatibility(
    project_root: Path,
) -> _RuntimeBundleCompatibility:
    """Validate the deployed Echelon runtime needed for safe retry."""
    missing = _runtime_bundle_missing_paths(project_root)
    if missing:
        return _RuntimeBundleCompatibility(
            compatible=False,
            command="echelon workspace migrate-to-prosaic",
            note=(
                "the deployed Echelon runtime is incomplete: "
                + ", ".join(missing)
            ),
        )
    return _RuntimeBundleCompatibility(
        compatible=True,
        note="deployed Prosaic and runtime bundles are available",
    )


def _recovery_action_from_instruction(
    instruction: RecoveryInstruction,
    *,
    run_state: dict,
    project_root: Path | None,
) -> _RunRecoveryAction:
    kind = instruction.kind
    reason = instruction.reason_code
    phase = instruction.phase

    if kind == RecoveryKind.SYNC_RUNTIME_THEN_RETRY:
        compatibility = (
            _runtime_bundle_compatibility(project_root)
            if project_root is not None
            else _RuntimeBundleCompatibility(compatible=True)
        )
        if not compatibility.compatible:
            return _RunRecoveryAction(
                "manual_recovery",
                reason=reason,
                phase=phase,
                command=compatibility.command,
                note=compatibility.note,
            )
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note="runtime contracts are compatible; the blocked phase will retry without rewind",
        )
    if kind in {RecoveryKind.RETRY_PHASE, RecoveryKind.WAIT_FOR_PROVIDER}:
        output_recovery = run_state.get("phase_output_recovery")
        output_detail = ""
        if isinstance(output_recovery, dict) and output_recovery.get("phase") == phase:
            invalid = output_recovery.get("invalid_outputs")
            if isinstance(invalid, list):
                output_detail = "; ".join(
                    f"{item['path']}: {item['reason']}"
                    for item in invalid
                    if isinstance(item, dict) and item.get("path") and item.get("reason")
                )
        is_banzai_consensus_repair = (
            kind == RecoveryKind.RETRY_PHASE
            and instruction.reason_code == "agent_blocked"
            and instruction.phase == "phase3-consensus"
            and run_state.get("autonomy_mode") == "banzai"
        )
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note=(
                "wait for the provider reset, then retry the blocked phase"
                if kind == RecoveryKind.WAIT_FOR_PROVIDER
                else (
                    "will retry Phase 3 consensus; any explicit Banzai-eligible "
                    "SAGE issue will be sealed and routed to its owning repair "
                    "phase automatically"
                    if is_banzai_consensus_repair
                    else "will retry the blocked phase without rewind"
                )
            ) + (f". Repair required: {output_detail}" if output_detail else ""),
        )
    if kind == RecoveryKind.RESOLVE_DECISION:
        return _RunRecoveryAction(
            "resolve_decision",
            reason=reason,
            phase=phase,
            command="echelon spec continue",
            note="the controller will resolve the persisted decision using its sealed autonomy mode",
        )
    if kind == RecoveryKind.AWAIT_HUMAN_ANSWER:
        return _RunRecoveryAction(
            "human_resume",
            reason=reason,
            phase=phase,
            command='echelon spec resume "<your answer>"',
            note=str(run_state.get("escalation_question") or "").strip(),
        )
    if kind == RecoveryKind.RESOLVE_ISSUE:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command='echelon spec resolve ISS-<n> "<project decision>"',
            note="resolve the first unresolved issue before continuing",
        )
    if kind == RecoveryKind.SAFE_REWIND:
        return _RunRecoveryAction(
            "safe_rewind",
            reason=reason,
            phase=phase,
            command=_command_display("echelon spec rewind", [phase]),
            note="safe checkpoint cleanup is required before retry",
        )
    if kind == RecoveryKind.INCREASE_BUDGET:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="increase analysis.token_budget_k, then echelon spec continue",
            note="the run cannot continue until the configured budget is higher",
        )
    if kind == RecoveryKind.MANUAL_REPAIR:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command=_command_display("echelon phase run", [phase]),
            note="run the recorded deterministic repair before continuing",
        )
    if kind == RecoveryKind.MANUAL_DIAGNOSIS:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="inspect echelon spec status, then diagnose the failed decision",
            note=("the issue report contains no explicitly eligible automatic recovery option"
                  if reason == "phase_dispatch_limit_evidence_ineligible"
                  else "the issue report exceeds the bounded recovery option count"
                  if reason == "phase_dispatch_limit_evidence_too_many_candidates"
                  else "the controller could not read valid issue-resolution evidence"
                  if reason.startswith("phase_dispatch_limit_evidence_")
                  else "the controller exhausted automatic decision resolution"),
        )
    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        command="inspect echelon spec status, then choose a recovery action",
        note="the controller recorded that automatic recovery is unsafe",
    )


def _decision_automatic_eligibility_under_current_policy(
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
    graph: object | None = None,
) -> bool:
    """Recalculate registered v2/v3 recommendation eligibility for recovery."""
    if decision.get("schema_version") not in {2, 3} or project_root is None:
        return False
    try:
        from harness.human_input import (
            decision_recommendation_is_automatic_under_policy,
        )

        if graph is None:
            from harness.phase_graph import load_workspace_phase_graph

            graph, _ = load_workspace_phase_graph(project_root)
        registry = graph.human_input_policy_registry()
        policy = registry.lookup(
            str(decision.get("source_kind") or ""),
            str(decision.get("producer_id") or ""),
            str(decision.get("reason_code") or ""),
        )
        return decision_recommendation_is_automatic_under_policy(
            decision,
            policy,
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False


def _automatic_decision_is_eligible(
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
    graph: object | None = None,
) -> bool:
    if (
        decision.get("schema_version") == 3
        and decision.get("automatic_eligible") is True
    ):
        return True
    return _decision_automatic_eligibility_under_current_policy(
        decision,
        project_root=project_root,
        graph=graph,
    )


def _decision_gate_rewind_action(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
) -> _RunRecoveryAction | None:
    if project_root is None:
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    spec_dir, _ = _normalize_rewind_spec_dir(project_root, dict(run_state))
    if spec_dir is None or not source_phase:
        return None
    from harness.phase_checkpoints import load_checkpoint_ledger

    try:
        ledger = load_checkpoint_ledger(spec_dir)
    except (KeyError, OSError, TypeError, ValueError):
        return None
    candidates = [
        checkpoint
        for checkpoint in ledger.checkpoints
        if checkpoint.rewind == "supported"
        and checkpoint.next_phase == source_phase
    ]
    if not candidates:
        return None
    checkpoint = candidates[-1]
    duplicate_phase = sum(
        item.phase == checkpoint.phase for item in ledger.checkpoints
    ) > 1
    command_args = [checkpoint.phase]
    if duplicate_phase:
        command_args.extend(("--commit", checkpoint.commit))
    command_args.extend(("--next-phase", source_phase, "--confirm"))
    return _RunRecoveryAction(
        "safe_rewind",
        reason=str(run_state.get("blocked_reason") or "gate_rejected"),
        phase=checkpoint.phase,
        command=_command_display("echelon spec rewind", command_args),
        note=(
            "rewind the exact checkpoint ledger predecessor before replaying "
            "the human gate"
        ),
    )


def _versioned_decision_recovery_action(
    run_state: Mapping[str, object],
    *,
    project_root: Path | None,
) -> _RunRecoveryAction | None:
    decision = _validated_versioned_decision(run_state)
    if decision is None:
        return None
    status = decision["status"]
    source_kind = decision["source_kind"]
    if (
        status == "resolved"
        and source_kind == "human_gate"
        and str(run_state.get("blocked_reason") or "").strip()
        == "gate_rejected"
    ):
        return _decision_gate_rewind_action(
            run_state,
            decision,
            project_root=project_root,
        )
    if _legacy_banzai_why2_reassessment_is_available(run_state, decision):
        return _RunRecoveryAction(
            "resolve_decision",
            reason=str(decision["reason_code"]),
            phase="phase1-why2",
            command="echelon spec continue",
            note=(
                "will re-evaluate this pre-candidate Banzai WHY2 question "
                "once under the current bounded-default policy"
            ),
        )
    protocol_upgrade_action = _v1_banzai_why2_protocol_upgrade_recovery_action(
        run_state,
        decision,
        project_root=project_root,
    )
    if protocol_upgrade_action is not None:
        return protocol_upgrade_action
    if _banzai_why2_evidence_reassessment_is_available(run_state, decision):
        return _RunRecoveryAction(
            "resolve_decision",
            reason=str(decision["reason_code"]),
            phase="phase1-why2",
            command="echelon spec continue",
            note=(
                "will search canonical evidence for this exact Banzai WHY2 "
                "question before requiring a human answer"
            ),
        )
    if (
        status == "awaiting_human"
        and decision.get("schema_version") == 3
        and decision.get("automatic_eligible") is False
        and source_kind == "provider_escalation"
        and decision.get("autonomy_mode") == "banzai"
        and run_state.get("autonomy_mode") == "banzai"
        and _automatic_decision_is_eligible(
            decision,
            project_root=project_root,
        )
    ):
        return _RunRecoveryAction(
            "resolve_decision",
            reason=str(decision["reason_code"]),
            phase=str(decision["source_phase"]),
            command="echelon spec continue",
            note=(
                "the current Banzai policy accepts this sealed product "
                "recommendation as an autonomous default"
            ),
        )
    if (
        status != "failed"
        or decision.get("autonomy_mode") != "banzai"
        or run_state.get("autonomy_mode") != "banzai"
        or not _automatic_decision_is_eligible(
            decision,
            project_root=project_root,
        )
    ):
        return None
    if source_kind == "human_gate":
        return _decision_gate_rewind_action(
            run_state,
            decision,
            project_root=project_root,
        )
    if source_kind not in {"provider_escalation", "controller_safeguard"}:
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    if not source_phase or project_root is None:
        return None
    try:
        from harness.phase_graph import load_workspace_phase_graph

        graph, _ = load_workspace_phase_graph(project_root)
        if source_phase not in graph.all_phase_ids():
            return None
    except (KeyError, OSError, TypeError, ValueError):
        return None
    reason = str(decision.get("failure_code") or "").strip() or str(
        run_state.get("blocked_reason") or decision.get("reason_code") or ""
    ).strip()
    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        phase=source_phase,
        command=_command_display("echelon phase run", [source_phase]),
        note="replay the exact failed automatic decision source phase",
    )


def _banzai_why2_evidence_reassessment_is_available(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
) -> bool:
    """Expose one controller evidence preflight for each distinct question."""
    if not _is_pre_candidate_banzai_why2_decision(decision):
        return False
    try:
        validate_banzai_default_reassessment_record(
            run_state.get("banzai_default_reassessment")
        )
        record = validate_banzai_evidence_reassessment_record(
            run_state.get("banzai_evidence_reassessment")
        )
    except StateAdvanceError:
        return False
    attempts = record["attempts"] if record is not None else []
    question_sha256 = hashlib.sha256(
        str(decision["question"]).encode("utf-8")
    ).hexdigest()
    return (
        run_state.get("status") == "blocked"
        and run_state.get("phase") == "phase1-why2"
        and run_state.get("autonomy_mode") == "banzai"
        and len(attempts) < 8
        and all(
            attempt["question_sha256"] != question_sha256
            for attempt in attempts
        )
    )


def _retryable_failed_agent_block_phase(run_state: dict) -> str | None:
    """Return the retry phase for a legacy bare-agent-block decision.

    Older controllers treated a bare agent ``BLOCKED`` envelope as material and
    could make a run unrecoverable after COMMANDER's provider retries failed.
    Because this decision records neither an agent reason nor a real question,
    retrying its source phase is safer than asking the operator to invent one.
    The identity check is deliberately narrow so genuine failed decisions remain
    manual-recovery cases.
    """
    raw_decision = run_state.get("blocked_decision")
    if not isinstance(raw_decision, dict):
        return None
    try:
        from harness.blocked_decision import validate_blocked_decision_v2

        decision = validate_blocked_decision_v2(raw_decision)
    except ValueError:
        return None
    if (
        decision["status"] != "failed"
        or decision["source_kind"] != "controller_safeguard"
        or decision["producer_id"] != "agent_blocked"
        or decision["reason_code"] != "agent_blocked"
        or str(run_state.get("blocked_reason") or "").strip() != "agent_blocked"
    ):
        return None
    phase = str(decision["source_phase"] or "").strip()
    return phase if phase and phase != "terminal-blocked" else None


def _discard_retryable_failed_agent_block_decision(state: dict) -> bool:
    """Discard only an obsolete generic-agent-block decision before retrying."""
    if _retryable_failed_agent_block_phase(state) is None:
        return False
    state.pop("blocked_decision", None)
    state.pop("recovery_instruction", None)
    state.pop("escalation_question", None)
    state.pop("escalation_options", None)
    state.pop("escalation_resolved", None)
    return True


def _supersede_quality_guard_decision(state: dict) -> bool:
    """Close the obsolete WHY safeguard when quality remediation supersedes it.

    A certified quality remediation cycle is controller-owned evidence that a
    previous no-progress WHY guard no longer describes the next safe action.
    Preserve that guard as a resolved decision rather than leaving an active
    decision without its recovery instruction.  The narrow identity check
    prevents this path from bypassing ordinary human or provider decisions.
    """
    from harness.blocked_decision import validate_blocked_decision_v2

    remediation = state.get("quality_gate_remediation")
    raw_decision = state.get("blocked_decision")
    ledger = state.get("issue_resolution_ledger")
    if not isinstance(remediation, dict) or not isinstance(raw_decision, dict):
        return False
    if not isinstance(ledger, dict) or not ledger:
        return False
    if not all(
        isinstance(entry, dict) and entry.get("status") == "validated"
        for entry in ledger.values()
    ):
        return False
    try:
        decision = validate_blocked_decision_v2(raw_decision)
    except ValueError:
        return False
    if (
        decision["status"] != "awaiting_human"
        or decision["source_kind"] != "controller_safeguard"
        or decision["producer_id"] not in {
            "consecutive_why_fails",
            "why2_metric_stagnation",
        }
        or decision["reason_code"] != decision["producer_id"]
    ):
        return False

    superseded = {
        **decision,
        "status": "resolved",
        "answer_text": (
            "Superseded by controller quality-gate remediation after all "
            "recorded issue resolutions were validated."
        ),
        "resolved_by": "COMMANDER",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }
    state["blocked_decision"] = validate_blocked_decision_v2(superseded)
    state.pop("recovery_instruction", None)
    return True


def _reset_quality_remediation_dispatch_counts(state: dict) -> None:
    """Start a spec-changing quality remediation with a fresh verification budget."""
    dispatch_counts = state.get("phase_dispatch_counts")
    if not isinstance(dispatch_counts, dict):
        return
    updated_counts = dict(dispatch_counts)
    for phase_id in (
        "phase1-what",
        "phase1-lexicon",
        "phase1-understanding",
        "phase1-why2",
    ):
        updated_counts.pop(phase_id, None)
    state["phase_dispatch_counts"] = updated_counts


def _current_qualitative_findings(state: Mapping[str, object]) -> list[dict[str, object]]:
    """Return current SAGE findings that must survive remediation recovery."""
    finding_routes = state.get("finding_routes")
    findings = (
        finding_routes.get("findings")
        if isinstance(finding_routes, Mapping)
        else None
    )
    return [
        dict(finding)
        for finding in findings
        if isinstance(finding, Mapping)
    ] if isinstance(findings, list) else []


def _render_v2_decision_options(decision: dict[str, object]) -> str:
    options = decision.get("options")
    if not isinstance(options, list) or not options:
        return "Free text"
    return "\n".join(
        f"{option['id']}: {option['label']}"
        for option in options
        if isinstance(option, dict)
    )


def _v2_decision_recommendation(decision: dict[str, object]) -> str:
    options = decision.get("options")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, dict) and option.get("recommended") is True:
                return f"{option['id']}: {option['label']}"
    return str(decision.get("recommended_answer") or "(none)")


def _decision_option_display(
    decision: Mapping[str, object],
    option_id: object,
) -> str:
    identifier = str(option_id or "").strip()
    if not identifier:
        return "(none)"
    options = decision.get("options")
    if isinstance(options, list):
        for option in options:
            if isinstance(option, Mapping) and option.get("id") == identifier:
                label = str(option.get("label") or "").strip()
                return f"{identifier}: {label}" if label else identifier
    return identifier


def _decision_audit_fields(
    decision: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Render recommendation and resolution audit from a validated decision."""
    fields: list[tuple[str, str]] = [
        ("Decision ID", str(decision["id"])),
        ("Decision status", str(decision["status"])),
        ("Decision mode", str(decision["autonomy_mode"])),
        ("Classification", str(decision["classification"])),
        ("Question", str(decision["question"])),
        ("Options", _render_v2_decision_options(dict(decision))),
    ]
    if decision.get("schema_version") == 3:
        recommended_option = decision.get("recommended_option_id")
        recommended_answer = str(
            decision.get("recommended_answer") or ""
        ).strip()
        evidence = decision.get("recommendation_evidence")
        controller_owned_banzai_default = (
            recommended_option is None
            and not recommended_answer
            and isinstance(evidence, list)
            and len(evidence) == 1
            and isinstance(evidence[0], Mapping)
            and evidence[0].get("kind") == "banzai_default_candidate"
        )
        recommendation_target = (
            "Controller-owned Banzai default"
            if controller_owned_banzai_default
            else _decision_option_display(decision, recommended_option)
            if recommended_option is not None
            else recommended_answer or "(human action only)"
        )
        fields.extend(
            [
                ("Recommendation", f"Recommended: {recommendation_target}"),
                (
                    "Recommendation rationale",
                    str(decision["recommendation_rationale"]),
                ),
                (
                    "Recommendation confidence",
                    str(decision["recommendation_confidence"]),
                ),
            ]
        )
        recommended_action = str(
            decision.get("recommended_action") or ""
        ).strip()
        if recommended_action:
            fields.append(("Recommended action", recommended_action))
    else:
        fields.append(
            (
                "Recommendation",
                f"Recommended: {_v2_decision_recommendation(dict(decision))}",
            )
        )
    fields.append(("Risk", str(decision.get("risk_level") or "(none)")))

    selected_option = decision.get("selected_option_id")
    answer_text = str(decision.get("answer_text") or "").strip()
    if selected_option is not None or answer_text:
        fields.append(
            (
                "Answer",
                _decision_option_display(decision, selected_option)
                if selected_option is not None
                else answer_text,
            )
        )
    resolved_by = str(decision.get("resolved_by") or "").strip()
    if resolved_by:
        fields.append(("Resolved by", resolved_by))
    if decision.get("schema_version") == 3 and decision.get("status") == "resolved":
        followed = decision.get("recommendation_followed")
        resolution = (
            "Followed recommendation"
            if followed is True
            else "Overrode recommendation"
            if followed is False
            else "Recommendation action required human judgment"
        )
        fields.append(("Resolution", resolution))
        resolution_rationale = str(
            decision.get("resolution_rationale") or ""
        ).strip()
        resolution_confidence = str(
            decision.get("resolution_confidence") or ""
        ).strip()
        override_reason = str(decision.get("override_reason") or "").strip()
        if resolution_rationale:
            fields.append(("Resolution rationale", resolution_rationale))
        if resolution_confidence:
            fields.append(("Resolution confidence", resolution_confidence))
        if override_reason:
            fields.append(("Override reason", override_reason))
    return fields


def _proportional_quality_decision_fields(
    state: Mapping[str, object],
    decision: Mapping[str, object],
) -> list[tuple[str, str]]:
    """Render sealed proportional budget evidence without inferring choices."""
    if decision.get("resolution_handler") != "proportional_quality_debt":
        return []
    fields: list[tuple[str, str]] = []
    repair = state.get("phase1_quality_repair")
    if isinstance(repair, Mapping):
        automatic = repair.get("automatic_consumed")
        automatic_limit = repair.get("automatic_limit")
        extension = repair.get("extension_consumed")
        extension_limit = repair.get("extension_limit")
        extension_authorized = repair.get("extension_authorized")
        if type(automatic) is int and type(automatic_limit) is int:
            fields.append(
                (
                    "Automatic repairs",
                    f"{automatic} of {automatic_limit} consumed "
                    f"({max(0, automatic_limit - automatic)} remaining)",
                )
            )
        if type(extension) is int and type(extension_limit) is int:
            authorization = (
                f"; {extension_authorized} authorized"
                if type(extension_authorized) is int
                else ""
            )
            fields.append(
                (
                    "Extension repairs",
                    f"{extension} of {extension_limit} consumed "
                    f"({max(0, extension_limit - extension)} remaining"
                    f"{authorization})",
                )
            )
    evidence = state.get("proportional_quality_candidate_evidence")
    if isinstance(evidence, Mapping):
        candidate = str(evidence.get("selected_candidate_id") or "").strip()
        if candidate:
            fields.append(("Selected candidate", candidate))
        failed_gates: list[str] = []
        raw_gates = evidence.get("failed_gates")
        if isinstance(raw_gates, list):
            for gate in raw_gates[:8]:
                if not isinstance(gate, Mapping):
                    continue
                name = str(gate.get("name") or "").strip()
                score = gate.get("score")
                threshold = gate.get("threshold")
                if (
                    name
                    and type(score) in {int, float}
                    and type(threshold) in {int, float}
                ):
                    failed_gates.append(
                        f"{name} {float(score):.2f} < {float(threshold):.2f}"
                    )
        if failed_gates:
            fields.append(("Residual gate evidence", ", ".join(failed_gates)))
        sage_findings: list[str] = []
        raw_findings = evidence.get("sage_finding_routes")
        if isinstance(raw_findings, list):
            for finding in raw_findings[:5]:
                if not isinstance(finding, Mapping):
                    continue
                issue_id = str(finding.get("issue_id") or "").strip()
                severity = str(finding.get("severity") or "").strip()
                issue_type = str(finding.get("type") or "").strip()
                rationale = str(finding.get("rationale") or "").strip()
                identity = issue_id or "SAGE finding"
                classification = "/".join(
                    value for value in (severity, issue_type) if value
                )
                rendered = (
                    f"{identity} [{classification}]" if classification else identity
                )
                if rationale:
                    rendered += f": {rationale[:240]}"
                sage_findings.append(rendered)
        if sage_findings:
            fields.append(("Material SAGE findings", "\n".join(sage_findings)))
        recommendation_evidence = evidence.get("recommendation_evidence")
        if isinstance(recommendation_evidence, Mapping):
            baseline_candidate = str(
                recommendation_evidence.get("baseline_candidate_id") or ""
            ).strip()
            current_candidate = str(
                recommendation_evidence.get("current_candidate_id") or ""
            ).strip()
            if baseline_candidate and current_candidate:
                fields.append(
                    (
                        "Growth comparison",
                        f"{baseline_candidate} → {current_candidate}",
                    )
                )
            comparison_previous = str(
                recommendation_evidence.get(
                    "comparison_previous_candidate_id"
                ) or ""
            ).strip()[:128]
            comparison_current = str(
                recommendation_evidence.get(
                    "comparison_current_candidate_id"
                ) or ""
            ).strip()[:128]
            if comparison_previous and comparison_current:
                fields.append(
                    (
                        "Repair comparison",
                        f"{comparison_previous} → {comparison_current}",
                    )
                )
            baseline_statements = recommendation_evidence.get(
                "baseline_formal_statement_count"
            )
            statements = recommendation_evidence.get("formal_statement_count")
            statement_growth = recommendation_evidence.get(
                "formal_statement_growth"
            )
            if all(
                type(value) is int
                for value in (baseline_statements, statements, statement_growth)
            ):
                fields.append(
                    (
                        "Formal statements",
                        f"{baseline_statements:,} → {statements:,} "
                        f"({statement_growth:+,})",
                    )
                )
            baseline_bytes = recommendation_evidence.get("baseline_byte_count")
            byte_count = recommendation_evidence.get("byte_count")
            byte_growth = recommendation_evidence.get("byte_growth")
            if all(
                type(value) is int
                for value in (baseline_bytes, byte_count, byte_growth)
            ):
                fields.append(
                    (
                        "Specification bytes",
                        f"{baseline_bytes:,} → {byte_count:,} "
                        f"({byte_growth:+,} bytes)",
                    )
                )
            score_history_lines: list[str] = []
            raw_score_history = recommendation_evidence.get("score_history")
            if isinstance(raw_score_history, list):
                for entry in raw_score_history[:5]:
                    if not isinstance(entry, Mapping):
                        continue
                    repair_number = entry.get("repair_number")
                    candidate_id = str(
                        entry.get("candidate_id") or ""
                    ).strip()[:128]
                    scores = entry.get("scores")
                    if (
                        type(repair_number) is not int
                        or repair_number < 0
                        or not candidate_id
                        or not isinstance(scores, list)
                    ):
                        continue
                    rendered_scores: list[str] = []
                    for score_entry in scores[:8]:
                        if not isinstance(score_entry, Mapping):
                            continue
                        name = str(
                            score_entry.get("name") or ""
                        ).strip()[:80]
                        score = score_entry.get("score")
                        threshold = score_entry.get("threshold")
                        if (
                            name
                            and type(score) in {int, float}
                            and type(threshold) in {int, float}
                        ):
                            rendered_scores.append(
                                f"{name} {float(score):.2f}/{float(threshold):.2f}"
                            )
                    if rendered_scores:
                        score_history_lines.append(
                            f"repair {repair_number} {candidate_id}: "
                            + ", ".join(rendered_scores)
                        )
            if score_history_lines:
                fields.append(("Score history", "\n".join(score_history_lines)))
            delta_lines: list[str] = []
            raw_deltas = recommendation_evidence.get("per_repair_deltas")
            if isinstance(raw_deltas, list):
                for entry in raw_deltas[:4]:
                    if not isinstance(entry, Mapping):
                        continue
                    repair_number = entry.get("repair_number")
                    statement_delta = entry.get("formal_statement_delta")
                    byte_delta = entry.get("byte_delta")
                    score_deltas = entry.get("score_deltas")
                    if (
                        type(repair_number) is not int
                        or repair_number < 0
                        or type(statement_delta) is not int
                        or type(byte_delta) is not int
                        or not isinstance(score_deltas, list)
                    ):
                        continue
                    rendered_deltas: list[str] = []
                    for score_delta in score_deltas[:8]:
                        if not isinstance(score_delta, Mapping):
                            continue
                        name = str(
                            score_delta.get("name") or ""
                        ).strip()[:80]
                        delta = score_delta.get("delta")
                        if name and type(delta) in {int, float}:
                            rendered_deltas.append(
                                f"{name} {float(delta):+.2f}"
                            )
                    if rendered_deltas:
                        delta_lines.append(
                            f"repair {repair_number}: "
                            + ", ".join(rendered_deltas)
                            + f"; statements {statement_delta:+d}"
                            + f"; bytes {byte_delta:+d}"
                        )
            if delta_lines:
                fields.append(("Per-repair deltas", "\n".join(delta_lines)))
            rationale = str(
                recommendation_evidence.get("rationale") or ""
            ).strip()
            if rationale:
                fields.append(("Recommendation rationale", rationale[:500]))
    options = decision.get("options")
    if isinstance(options, list):
        recommended = next(
            (
                option
                for option in options
                if isinstance(option, Mapping)
                and option.get("recommended") is True
            ),
            None,
        )
        if isinstance(recommended, Mapping):
            fields.append(
                (
                    "Quality recommendation",
                    f"{recommended.get('id')} ({recommended.get('label')})",
                )
            )
        choice_commands = [
            f'echelon spec resume "{option.get("id")}"'
            for option in options
            if isinstance(option, Mapping)
            and isinstance(option.get("id"), str)
            and option.get("id")
        ]
        if choice_commands:
            fields.append(("Choice syntax", "\n".join(choice_commands)))
    return fields


def _current_quality_debt_cli_facts(
    state: Mapping[str, object],
    project_root: Path,
) -> dict[str, object] | None:
    """Return bounded display facts only for Task 6-verified live authority."""
    authorization = state.get("spec_quality_debt_authorization")
    if not isinstance(authorization, Mapping):
        return None
    from harness.phase1_quality_debt import (
        has_current_quality_debt_authorization,
    )

    if not has_current_quality_debt_authorization(
        state,
        project_root=project_root,
    ):
        return None
    if authorization.get("status") != "accepted_with_debt":
        return None
    failed_gates: list[str] = []
    raw_gates = authorization.get("failed_gates")
    if isinstance(raw_gates, list):
        for gate in raw_gates[:8]:
            if not isinstance(gate, Mapping):
                continue
            name = str(gate.get("name") or "").strip()
            score = gate.get("score")
            threshold = gate.get("threshold")
            if name and type(score) in {int, float} and type(threshold) in {int, float}:
                failed_gates.append(
                    f"{name} {float(score):.2f} < {float(threshold):.2f}"
                )
    qualitative_issues: list[str] = []
    raw_qualitative = authorization.get("qualitative_debt")
    if isinstance(raw_qualitative, list):
        for finding in raw_qualitative[:8]:
            if not isinstance(finding, Mapping):
                continue
            issue_id = str(finding.get("issue_id") or "").strip()
            title = str(finding.get("title") or "").strip()
            if issue_id and title:
                qualitative_issues.append(
                    f"{issue_id[:80]}: {title[:120]}"
                )
            elif issue_id:
                qualitative_issues.append(issue_id[:80])
    return {
        "status": "accepted_with_debt",
        "artifact": str(authorization.get("debt_artifact") or "").strip(),
        "resolved_by": str(authorization.get("resolved_by") or "").strip(),
        "failed_gates": tuple(failed_gates),
        "qualitative_issues": tuple(qualitative_issues),
    }


def _persisted_or_legacy_recovery_instruction(
    run_state: dict,
) -> RecoveryInstruction | None:
    reason = str(run_state.get("blocked_reason") or "").strip()
    phase_output_recovery = run_state.get("phase_output_recovery")
    phase_output_instruction: RecoveryInstruction | None = None
    if (
        reason in {"missing_phase_outputs", "invalid_phase_outputs", "invalid_evidence_inventory"}
        and isinstance(phase_output_recovery, dict)
    ):
        recovery_phase = str(
            phase_output_recovery.get("phase") or ""
        ).strip()
        missing_outputs = phase_output_recovery.get("missing_outputs")
        invalid_outputs = phase_output_recovery.get("invalid_outputs")
        has_recovery_evidence = (
            isinstance(missing_outputs, list) and bool(missing_outputs)
        ) or (
            isinstance(invalid_outputs, list) and bool(invalid_outputs)
        )
        if recovery_phase and has_recovery_evidence:
            phase_output_instruction = retry_phase_recovery(
                recovery_phase,
                reason,
            )

    raw_instruction = run_state.get("recovery_instruction")
    if raw_instruction is not None:
        instruction = validate_recovery_instruction(raw_instruction)
        if reason and instruction.reason_code != reason:
            if phase_output_instruction is not None:
                return phase_output_instruction
            raise RecoveryInstructionError(
                "recovery instruction does not match blocked reason"
            )
        return instruction

    if phase_output_instruction is not None:
        return phase_output_instruction
    return None


def _legacy_banzai_why2_reassessment_is_available(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
) -> bool:
    """Presentation-only view of the controller's narrow legacy retry gate."""
    return (
        run_state.get("status") == "blocked"
        and run_state.get("phase") == "phase1-why2"
        and run_state.get("autonomy_mode") == "banzai"
        and run_state.get("banzai_default_candidate_protocol_version") is None
        and run_state.get("banzai_default_reassessment") is None
        and _is_pre_candidate_banzai_why2_decision(decision)
    )


def _v1_banzai_why2_protocol_upgrade_is_available(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
) -> bool:
    """Identify the one valid legacy marker eligible for an upgrade retry."""
    try:
        reassessment = validate_banzai_default_reassessment_record(
            run_state.get("banzai_default_reassessment")
        )
    except StateAdvanceError:
        return False
    return (
        run_state.get("status") == "blocked"
        and run_state.get("phase") == "phase1-why2"
        and run_state.get("autonomy_mode") == "banzai"
        and run_state.get("banzai_default_candidate_protocol_version") is None
        and reassessment is not None
        and reassessment["schema_version"] == 1
        and _is_pre_candidate_banzai_why2_decision(decision)
    )


def _v1_banzai_why2_protocol_upgrade_recovery_action(
    run_state: Mapping[str, object],
    decision: Mapping[str, object],
    *,
    project_root: Path | None,
) -> _RunRecoveryAction | None:
    """Present the bounded retry only when the active deployed bundle is safe."""
    if not _v1_banzai_why2_protocol_upgrade_is_available(run_state, decision):
        return None
    if project_root is None:
        return None
    fingerprint = active_banzai_default_protocol_fingerprint(project_root)
    if fingerprint.fingerprint is None:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=str(decision["reason_code"]),
            phase="phase1-why2",
            command="echelon workspace migrate-to-prosaic",
            note=(
                "the deployed candidate-protocol bundle cannot be verified: "
                + fingerprint.diagnostic
            ),
        )
    return _RunRecoveryAction(
        "resolve_decision",
        reason=str(decision["reason_code"]),
        phase="phase1-why2",
        command="echelon spec continue",
        note=(
            "will re-evaluate this legacy Banzai WHY2 question once using the "
            "refreshed candidate-protocol bundle"
        ),
    )


def _is_pre_candidate_banzai_why2_decision(
    decision: Mapping[str, object],
) -> bool:
    """Identify the only historic decision eligible for protocol reassessment."""
    return (
        decision.get("schema_version") == 3
        and decision.get("status") == "awaiting_human"
        and decision.get("autonomy_mode") == "banzai"
        and decision.get("source_kind") == "provider_escalation"
        and decision.get("producer_id") == "phase1-why2"
        and decision.get("source_phase") == "phase1-why2"
        and decision.get("reason_code") == "human_clarification_required"
        and decision.get("classification") == "material"
        and decision.get("resolution_handler") == "clarification_resume"
        and decision.get("automatic_eligible") is False
        and decision.get("options") == []
        and decision.get("recommended_answer") is None
        and decision.get("recommended_option_id") is None
        and decision.get("risk_level") is None
        and decision.get("recommendation_authority") == "workflow_policy"
        and decision.get("recommendation_evidence") == []
        and decision.get("attempts") == 0
        and decision.get("failure_code") is None
    )


def _restore_interrupted_legacy_banzai_why2_reassessment(
    state: dict[str, object],
) -> bool:
    """Repair the exact transient state emitted by the retired retry path."""
    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or state.get("status") != "running"
        or state.get("phase") != "phase1-why2"
        or state.get("autonomy_mode") != "banzai"
        or state.get("blocked_reason") is not None
        or state.get("recovery_instruction") is not None
        or state.get("escalation_question") is not None
        or state.get("escalation_options") is not None
        or state.get("banzai_default_candidate_protocol_version") is not None
        or state.get("banzai_default_reassessment") is not None
    ):
        return False
    try:
        from harness.blocked_decision import validate_blocked_decision

        decision = validate_blocked_decision(raw_decision)
    except ValueError:
        return False
    if not _is_pre_candidate_banzai_why2_decision(decision):
        return False
    state["status"] = "blocked"
    state["blocked_reason"] = decision["reason_code"]
    state["recovery_instruction"] = RecoveryInstruction(
        kind=RecoveryKind.AWAIT_HUMAN_ANSWER,
        reason_code=str(decision["reason_code"]),
        phase="phase1-why2",
        requires_human_input=True,
        schema_version=2,
        decision_id=str(decision["id"]),
    ).to_dict()
    state["escalation_question"] = decision["question"]
    state["escalation_options"] = []
    return True


def _render_escalation_options(options: object) -> str:
    """Render the same selectable choices that ``spec resume`` accepts.

    Choice escalations are persisted separately from the prose question so the
    resume command can route deterministically.  They must be displayed with
    that question; otherwise users cannot know which positional answer maps to
    which route.
    """
    if not isinstance(options, list):
        return ""

    rendered: list[str] = []
    letters: list[str] = []
    for index, raw in enumerate(options):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or raw.get("id") or "").strip()
        if not label:
            continue
        letter = chr(ord("A") + index)
        letters.append(letter)
        rendered.append(f"{letter}: {label}")

    if not rendered:
        return ""
    choices = "/".join(letters)
    rendered.append(f"Answer with {choices}, the option id, or the option label.")
    return "\n".join(rendered)


def _phase_dispatch_limit_phase(run_state: dict) -> str | None:
    """Find the phase whose retry window was exhausted.

    New runs persist the phase explicitly.  The question fallback keeps runs
    created by older Echelon versions recoverable without state-file surgery.
    """
    phase = str(run_state.get("phase_dispatch_limit_phase") or "").strip()
    if phase:
        return phase

    question = str(run_state.get("escalation_question") or "")
    match = re.search(r"Phase ['\"]([^'\"]+)['\"] has been dispatched", question)
    return match.group(1) if match else None


def _is_retryable_dispatch_block_reason(reason: str) -> bool:
    reason = reason.strip()
    return (
        reason in {
            "missing_phase_outputs",
            "invalid_phase_outputs",
            "missing_echelon_result",
            "agent_timeout",
            "agent_blocked",
        }
        or reason.startswith("agent_exit_code_")
    )


def _last_incomplete_dispatch_phase(run_state: dict) -> str | None:
    last_dispatch = run_state.get("last_dispatch") or {}
    phase_id = str(last_dispatch.get("phase_id") or "").strip()
    if not phase_id or phase_id == "terminal-blocked":
        return None

    return phase_id


def _blocked_non_escalation_recovery_command(
    run_state: dict,
    *,
    project_root: Path | None = None,
) -> str | None:
    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    phase_id = _last_incomplete_dispatch_phase(run_state)
    if not _is_retryable_dispatch_block_reason(blocked_reason) or not phase_id:
        return None
    if project_root is None:
        return None
    spec_dir, _ = _normalize_rewind_spec_dir(project_root, run_state)
    if spec_dir is None:
        return None
    from harness.phase_checkpoints import load_checkpoint_ledger, resolve_checkpoint

    try:
        resolve_checkpoint(load_checkpoint_ledger(spec_dir), phase_id)
    except (KeyError, OSError, ValueError, TypeError):
        return None
    return _command_display("echelon spec rewind", [phase_id])


def _blocked_failed_dispatch_phase(run_state: dict) -> str | None:
    """Return the incomplete phase that caused a deterministic dispatch block."""

    blocked_reason = str(run_state.get("blocked_reason") or "").strip()
    if run_state.get("escalation_question"):
        return None

    phase_id = _last_incomplete_dispatch_phase(run_state)
    if not phase_id:
        return None
    completed = run_state.get("completed_phases")
    completed_phases = {str(phase) for phase in completed} if isinstance(completed, list) else set()
    if phase_id in completed_phases and not _is_retryable_dispatch_block_reason(blocked_reason):
        return None
    if blocked_reason in {"token_budget_exhausted"} or "invalid next_phase" in blocked_reason:
        return None

    return phase_id


def _phase_a_readiness_traceability_blockers(run_state: dict) -> list[str]:
    """Return product-input mapping blockers preserved by Phase A finalization."""
    blockers = run_state.get("phase_a_readiness_blockers")
    if not isinstance(blockers, list):
        return []
    markers = (
        "product input traceability",
        "included requirement has no specification IDs",
        "included requirement has no task IDs",
        "does not reference the mapped specification IDs",
        "is not target-owned by a declared implementation target",
    )
    return [
        str(blocker)
        for blocker in blockers
        if isinstance(blocker, str) and any(marker in blocker for marker in markers)
    ]


def _interrupted_retry_phase(run_state: dict) -> str | None:
    phase_id = str(run_state.get("interrupted_phase") or run_state.get("phase") or "").strip()
    if phase_id and phase_id not in {"DONE", "terminal-blocked"}:
        return phase_id
    return _last_incomplete_dispatch_phase(run_state)


def _spec_markdown_sha256_for_state(run_state: dict, project_root: Path) -> str | None:
    """Return the active run's canonical spec digest, if it is available."""
    spec_dir_ref = str(run_state.get("spec_dir") or "").strip()
    if not spec_dir_ref:
        return None
    spec_dir = Path(spec_dir_ref)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    try:
        return hashlib.sha256((spec_dir / "spec.md").read_bytes()).hexdigest()
    except OSError:
        return None


def _active_dispatch_cap_evidence_exists(
    run_state: dict,
    project_root: Path | None,
) -> bool:
    """Whether the active run has recoverable dispatch-cap evidence."""
    if project_root is None:
        return False
    spec_ref = str(run_state.get("spec_dir") or "").strip()
    spec_dir: Path | None = None
    try:
        if spec_ref:
            spec_dir = Path(spec_ref)
            if not spec_dir.is_absolute():
                spec_dir = project_root / spec_dir
            if (spec_dir / "issues.md").is_file():
                return True
            if (spec_dir / "spec.md").is_file():
                return False

        staging_ref = str(run_state.get("staging_dir") or "").strip()
        if not staging_ref:
            return False
        staging_dir = Path(staging_ref)
        if not staging_dir.is_absolute():
            staging_dir = project_root / staging_dir
        return (staging_dir / "issues.md").is_file()
    except OSError:
        return False


def _classify_run_recovery(
    run_state: dict,
    *,
    project_root: Path | None = None,
) -> _RunRecoveryAction:
    status = str(run_state.get("status") or "").strip()
    reason = str(run_state.get("blocked_reason") or "").strip()

    if status in {"running", "in_progress"}:
        return _RunRecoveryAction("continue_running")

    if status == "interrupted":
        retry_phase = _interrupted_retry_phase(run_state)
        if retry_phase:
            return _RunRecoveryAction(
                "retry_phase",
                reason="interrupted",
                phase=retry_phase,
                command="echelon spec continue",
                note="will retry the interrupted phase",
            )
        return _RunRecoveryAction(
            "manual_recovery",
            reason="interrupted",
            command="echelon spec run --next-phase <phase-id>",
            note="interrupted run does not record a retryable phase",
        )

    if status != "blocked":
        return _RunRecoveryAction("advance")

    if reason in {"repair_no_progress", "repair_action_unclassified", "repair_review_stale",
                  "repair_review_missing", "repair_context_incomplete", "repair_budget_exhausted",
                  "repair_external_prerequisite", "repair_human_decision"}:
        selected = run_state.get("selected_issue_resolution")
        entry = (run_state.get("issue_resolution_ledger") or {}).get(selected) or {}
        pending = run_state.get("phase3_pending_action") or {}
        receipt = (run_state.get("phase3_issue_reviews") or {}).get(entry.get("last_review_dispatch_id")) or {}
        owner = entry.get("repair_phase") or (pending.get("assessment") or {}).get("owner_phase") or "phase3-consensus"
        issue = selected or pending.get("issue_id") or "current Phase 3 finding"
        action = (entry.get("repair_action") or pending.get("assessment") or {}).get("action") or entry.get("decision") or "classify or revalidate the current repair"
        detail = receipt.get("rationale") or (run_state.get("phase3_last_blocker") or {}).get("detail") or "Inspect current issues and assessment evidence."
        action_label = "proposed" if pending else "submitted"
        prerequisite = "Resolve the stated evidence/authority prerequisite before continuing; existing repair limits are retained."
        if reason == "repair_budget_exhausted":
            prerequisite = (
                f"Iteration budget exhausted ({run_state.get('iteration', '?')}/{run_state.get('max_iterations', '?')}); "
                "the next repair was not dispatched. Additional repair budget requires explicit authorization; no limit was reset."
            )
        return _RunRecoveryAction("manual_recovery", reason=reason, phase=owner,
            command="echelon spec status",
            note=f"{issue}; owner {owner}; {action_label}: {str(action)[:400]}. {str(detail)[:800]} {prerequisite}")

    try:
        decision_recovery = _versioned_decision_recovery_action(
            run_state,
            project_root=project_root,
        )
    except (RecoveryInstructionError, ValueError) as exc:
        return _RunRecoveryAction(
            "manual_recovery",
            reason="invalid_decision_authority",
            note=(
                f"invalid persisted decision authority: {exc}; restore or repair "
                "the exact decision and recovery pair before retrying"
            ),
        )
    if decision_recovery is not None:
        return decision_recovery

    if reason == "proportional_quality_debt_declined":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command=(
                "inspect the retained quality evidence, then start a new or "
                "amended specification run"
            ),
            note=(
                "The exhausted proportional repair loop was explicitly stopped. "
                "Ordinary continue cannot reopen it; deliberately amend the request "
                "or quality policy and start a new run."
            ),
        )

    retryable_agent_block_phase = _retryable_failed_agent_block_phase(run_state)
    if retryable_agent_block_phase:
        return _RunRecoveryAction(
            "retry_phase",
            reason="agent_blocked",
            phase=retryable_agent_block_phase,
            command="echelon spec continue",
            note=(
                "will retry a generic agent block; no material ambiguity was "
                "recorded"
            ),
        )

    ledger = run_state.get("issue_resolution_ledger")
    ledger_entries = (
        [entry for entry in ledger.values() if isinstance(entry, dict)]
        if isinstance(ledger, dict)
        else []
    )
    all_ledger_entries_validated = bool(ledger_entries) and all(
        entry.get("status") == "validated" for entry in ledger_entries
    )

    selected_issue = str(
        run_state.get("selected_issue_resolution") or ""
    ).strip()
    selected_entry = (
        ledger.get(selected_issue)
        if selected_issue and isinstance(ledger, dict)
        else None
    )
    if (
        reason == "proportional_quality_candidate_integrity_failed"
        and run_state.get("why2_repair_phase") == "phase1-discover"
        and str((run_state.get("last_dispatch") or {}).get("phase_id") or "")
        == "phase1-why2"
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="discovery_artifact_repair",
            phase="phase1-why2",
            command="echelon spec continue",
            note=(
                "Retry WHY2 so its controller-owned discovery-artifact route "
                "can run before proportional specification repair."
            ),
        )
    if (
        reason == "proportional_quality_candidate_integrity_failed"
        and isinstance(selected_entry, dict)
        and selected_entry.get("status") == "repaired"
        and str((run_state.get("last_dispatch") or {}).get("phase_id") or "")
        == "phase1-why2"
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="issue_resolution_revalidation",
            phase="phase1-why2",
            command="echelon spec continue",
            note=(
                "Retry the completed named repair against current authoritative "
                "SAGE and Understanding evidence. Any unrelated integrity "
                "failure remains blocking."
            ),
        )

    if reason == "issue_resolution_next":
        if all_ledger_entries_validated:
            return _RunRecoveryAction(
                "retry_phase",
                reason="quality_gate_remediation",
                phase="phase1-what",
                command="echelon spec continue",
                note=(
                    "All recorded issue resolutions are complete, but the certified "
                    "quality gates still fail. Starting a fresh specification quality "
                    "remediation cycle; no further `spec resolve` command applies."
                ),
            )
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command='echelon spec resolve ISS-<n> "<project decision>"',
            note=(
                "The previous issue repair was validated. Resolve the next "
                "unresolved SAGE issue; Echelon will retain the issue ledger "
                "and run only that issue's targeted repair."
            ),
        )

    # Once every controller-recorded issue decision is validated, a stale WHY
    # guard must not send the operator back to `spec resolve`. Resume the
    # normal quality remediation path instead. With an outstanding selected
    # repair, leave recovery handling below in charge of its declared edge.
    if reason == "consecutive_why_fails" and all_ledger_entries_validated:
        return _RunRecoveryAction(
            "retry_phase",
            reason="quality_gate_remediation",
            phase="phase1-what",
            command="echelon spec continue",
            note=(
                "All recorded issue resolutions are complete, but the certified "
                "quality gates still fail. Starting a fresh specification quality "
                "remediation cycle; no further `spec resolve` command applies."
            ),
        )

    if reason == "quality_gates_failed_after_resolutions":
        return _RunRecoveryAction(
            "human_resume",
            reason=reason,
            command='echelon spec resume "<quality-gate decision>"',
            note=(
                "All recorded issue resolutions are complete, but the certified "
                "quality gates still fail. No further `spec resolve` command applies."
            ),
        )

    if reason == "quality_gate_remediation_no_artifact_progress":
        return _RunRecoveryAction(
            "retry_phase",
            reason="quality_gate_remediation",
            phase="phase1-what",
            command="echelon spec continue",
            note=(
                "The prior quality remediation did not modify spec.md. Retrying "
                "CARTOGRAPHER with the controller's mandatory atomic-requirement "
                "repair contract; no `spec resolve` command applies."
            ),
        )

    if reason == "phase_dispatch_limit_option_contract_failed":
        phase = str(run_state.get("phase") or "").strip()
        if phase and phase != "terminal-blocked":
            return _RunRecoveryAction(
                "retry_phase",
                reason="phase_dispatch_limit_option_contract_retry",
                phase=phase,
                command="echelon spec continue",
                note=(
                    "Retry the sealed dispatch-cap option preparation against "
                    "the installed controller contract without resetting the cap."
                ),
            )

    if (
        reason == "phase_dispatch_limit_evidence_missing"
        and _active_dispatch_cap_evidence_exists(run_state, project_root)
    ):
        phase = str(run_state.get("phase") or "").strip()
        if phase and phase != "terminal-blocked":
            return _RunRecoveryAction(
                "retry_phase",
                reason="phase_dispatch_limit_evidence_retry",
                phase=phase,
                command="echelon spec continue",
                note=(
                    "The active run contains issues.md; retrying the capped phase "
                    "after bypassing a stale published-spec lookup."
                ),
            )

    phase = str(run_state.get("phase") or "").strip()
    certificate = run_state.get("spec_quality_certificate")
    certificate_source_sha256 = (
        str(certificate.get("source_sha256") or "").strip()
        if isinstance(certificate, Mapping)
        else ""
    )
    epoch_recovery = run_state.get(
        "phase_dispatch_limit_certification_epoch_recovery"
    )
    epoch_already_recovered = (
        isinstance(epoch_recovery, Mapping)
        and epoch_recovery.get("phase") == phase
        and epoch_recovery.get("source_sha256") == certificate_source_sha256
    )
    if (
        reason.startswith("phase_dispatch_limit_evidence_")
        and phase
        in {
            "phase1-lexicon-derive",
            "phase1-lexicon",
            "checkpoint-assess",
        }
        and project_root is not None
        and re.fullmatch(r"[0-9a-f]{64}", certificate_source_sha256) is not None
        and not epoch_already_recovered
        and has_current_phase1_quality_prerequisite(
            run_state,
            project_root=project_root,
        )
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="phase_dispatch_limit_certification_epoch",
            phase=phase,
            command="echelon spec continue",
            note=(
                "The capped downstream phase now has a current Phase 1 "
                "quality certificate. Retry it in that certification epoch "
                "instead of interpreting PASS issues.md as repair evidence."
            ),
        )
    if (
        reason.startswith("phase_dispatch_limit_evidence_")
        and phase
        in {
            "phase3-tasks-lexicon",
            "phase3-consensus-tasks-lexicon",
        }
    ):
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=phase,
            command=_command_display("echelon phase run", [phase]),
            note=(
                "Re-run the capped deterministic task gate after repairing "
                "tasks.md from tasks-lexicon-report.json or updating the "
                "validator. The gate will route any remaining findings back "
                "to planning without another automatic dispatch-cap decision."
            ),
        )

    try:
        instruction = _persisted_or_legacy_recovery_instruction(run_state)
    except RecoveryInstructionError as exc:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason or "invalid_recovery_instruction",
            command="inspect echelon spec status, then repair the run state",
            note=f"persisted recovery instruction is invalid: {exc}",
        )
    if instruction is not None:
        return _recovery_action_from_instruction(
            instruction,
            run_state=run_state,
            project_root=project_root,
        )

    recovery = run_state.get("issue_resolution_recovery")
    if (
        isinstance(recovery, dict)
        and recovery.get("status") not in {"consumed", "validated"}
        and str(recovery.get("issue_id") or "").strip()
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="issue_resolution",
            phase=str(recovery.get("to_phase") or "").strip(),
            command="echelon spec continue",
            note="will validate and consume the declared issue-repair workflow edge",
        )

    # A prior version could finish the selected WHAT repair, then let SAGE
    # re-list that same issue from stale generic reasoning.  Give the repaired
    # issue one focused WHY2 validation pass before asking the operator to
    # re-enter a decision they have already supplied.
    selected_issue = str(run_state.get("selected_issue_resolution") or "").strip()
    ledger = run_state.get("issue_resolution_ledger")
    retried_issue = str(
        run_state.get("issue_resolution_revalidation_attempted") or ""
    ).strip()
    if (
        selected_issue
        and selected_issue != retried_issue
        and isinstance(ledger, dict)
        and isinstance(ledger.get(selected_issue), dict)
        and ledger[selected_issue].get("status") == "repaired"
        and reason in {"consecutive_why_fails", "why2_metric_stagnation"}
    ):
        return _RunRecoveryAction(
            "retry_phase",
            reason="issue_resolution_revalidation",
            phase="phase1-understanding",
            command="echelon spec continue",
            note=(
                f"will revalidate the already-repaired {selected_issue} against "
                "its recorded decision before requesting another resolution"
            ),
        )

    if reason == "selected_issue_repair_no_artifact_progress":
        baseline = run_state.get("issue_resolution_repair_baseline")
        repair_phase = (
            str(baseline.get("repair_phase") or "").strip()
            if isinstance(baseline, dict)
            else ""
        )
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=repair_phase or "phase1-what",
            command="echelon spec continue",
            note="will retry the selected repair; it may not advance without spec.md progress",
        )

    if run_state.get("escalation_question"):
        if reason == "phase_dispatch_limit":
            phase = _phase_dispatch_limit_phase(run_state)
            if phase:
                return _RunRecoveryAction(
                    "manual_recovery",
                    reason=reason,
                    phase=phase,
                    command='echelon spec resolve ISS-<n> "<project decision>"',
                    note=(
                        f"{run_state.get('escalation_question', '').strip()}\n\n"
                        "No retry has been authorized. Resolve the first unresolved issue "
                        "with a project decision; Echelon will run only that issue's "
                        "targeted repair and retain the remaining issue ledger."
                    ),
                )
        return _RunRecoveryAction(
            "human_resume",
            reason=reason or "human answer required",
            command='echelon spec resume "<your answer>"',
            note=str(run_state.get("escalation_question") or "").strip(),
        )

    if reason == "token_budget_exhausted":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="increase analysis.token_budget_k, then echelon spec continue",
            note="the run cannot continue until the configured budget is higher",
        )

    last_dispatch = run_state.get("last_dispatch")
    last_dispatch_phase = (
        str(last_dispatch.get("phase_id") or "").strip()
        if isinstance(last_dispatch, dict)
        else ""
    )
    tasks_lexicon_block = reason == "tasks_lexicon_gate_exhausted" or (
        reason == "lexicon_gate_exhausted"
        and last_dispatch_phase
        in {"phase3-tasks-lexicon", "phase3-consensus-tasks-lexicon"}
    )
    if tasks_lexicon_block:
        return _RunRecoveryAction(
            "retry_phase",
            reason="tasks_lexicon_gate_exhausted",
            phase=(
                last_dispatch_phase
                if last_dispatch_phase
                in {"phase3-tasks-lexicon", "phase3-consensus-tasks-lexicon"}
                else "phase3-tasks-lexicon"
            ),
            command="echelon spec continue",
            note=(
                "Retry the deterministic Tasks Lexicon gate before requesting "
                "another planning pass. If the validator still finds debt, it "
                "will retain the evidence and block without dispatching a provider."
            ),
        )

    if reason == "lexicon_gate_exhausted":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase="phase1-lexicon-derive",
            command=(
                "echelon phase run phase1-lexicon-derive"
            ),
            note=(
                "The hard spec Lexicon gate failed. Dispatch the dedicated "
                "derivation node to repair requirements.lexicon.md "
                "from spec-lexicon-report.json. Certify with the deterministic "
                "Lexicon gate only after the repair pass changes the artifact."
            ),
        )

    if reason == "lexicon_repair_no_artifact_progress":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase="phase1-lexicon-derive",
            command=(
                "echelon phase run phase1-lexicon-derive"
            ),
            note=(
                "The derivation repair pass did not change the derived Lexicon "
                "artifact. Re-run the repair node to repair requirements.lexicon.md "
                "with the controller-injected "
                "spec-lexicon-report.json context; re-running certification "
                "will only repeat the same findings until requirements.lexicon.md changes."
            ),
        )

    if reason == "provider_session_limit":
        provider_message = str(run_state.get("provider_limit_message") or "").strip()
        note = "wait for the provider reset, then retry the blocked phase"
        if provider_message:
            note += f": {provider_message}"
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=_last_incomplete_dispatch_phase(run_state) or "",
            command="echelon spec continue",
            note=note,
        )

    if reason == "phase_a_readiness_failed":
        readiness_blockers = run_state.get("phase_a_readiness_blockers")
        if isinstance(readiness_blockers, list) and any(
            isinstance(blocker, str)
            and blocker.startswith("coverage-map.md invalid:")
            for blocker in readiness_blockers
        ):
            return _RunRecoveryAction(
                "retry_phase",
                reason=reason,
                phase="phase3-sentinel",
                command="echelon spec continue",
                note=(
                    "will send the recorded coverage-map contract finding to "
                    "SENTINEL and validate its replacement before advancing"
                ),
            )
        traceability_blockers = _phase_a_readiness_traceability_blockers(run_state)
        if traceability_blockers:
            return _RunRecoveryAction(
                "manual_recovery",
                reason=reason,
                command="echelon spec repair-traceability",
                note=(
                    "Preview a deterministic repair that removes contextual task references "
                    "while preserving direct requirement mappings; it resumes finalization without "
                    "re-running PLAN when safe. "
                    f"{len(traceability_blockers)} traceability blocker(s) were recorded; "
                    "each listed task must have a req= value that intersects its mapped spec_ids."
                ),
            )

    if "invalid next_phase" in reason:
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            command="echelon spec run --next-phase <phase-id>",
            note="choose a valid phase from echelon spec status output",
        )

    # Schema rejection happens after an agent dispatch but before its result is
    # committed.  The last dispatch is therefore incomplete even when an older
    # successful pass appears in completed_phases; retrying it is safe and does
    # not require deleting its planning artifacts.
    if reason.startswith("echelon_result validation failed:"):
        phase = _last_incomplete_dispatch_phase(run_state)
        if phase:
            return _RunRecoveryAction(
                "retry_phase",
                reason=reason,
                phase=phase,
                command="echelon spec continue",
                note="will retry the phase with the rejected result; no rewind is required",
            )

    rewind = _blocked_non_escalation_recovery_command(
        run_state,
        project_root=project_root,
    )
    if rewind:
        phase = str((run_state.get("last_dispatch") or {}).get("phase_id") or "").strip()
        return _RunRecoveryAction(
            "safe_rewind",
            reason=reason,
            phase=phase,
            command=rewind,
            note="safe checkpoint cleanup is required before retry",
        )

    if reason == "controller_state_contract_validation_failed":
        return _RunRecoveryAction(
            "manual_recovery",
            reason=reason,
            phase=str(run_state.get("phase") or "").strip(),
            command="inspect echelon spec status, then choose a recovery action",
            note="no runtime-sync recovery instruction was recorded",
        )

    retry_phase = _blocked_failed_dispatch_phase(run_state)
    if retry_phase:
        return _RunRecoveryAction(
            "retry_phase",
            reason=reason,
            phase=retry_phase,
            command="echelon spec continue",
            note="will retry the blocked phase; it was not marked complete",
        )

    if not reason:
        return _RunRecoveryAction("advance")

    return _RunRecoveryAction(
        "manual_recovery",
        reason=reason,
        command="inspect echelon spec status, then choose a recovery action",
        note="no human question, safe rewind target, or incomplete phase was recorded",
    )


def _format_phase_a_elapsed(state: dict) -> str:
    created = str(state.get("created_at") or "").strip()
    updated = str(state.get("updated_at") or "").strip()
    if not created or not updated:
        return ""
    try:
        from datetime import datetime

        start = datetime.fromisoformat(created.replace("Z", "+00:00"))
        end = datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        return ""
    seconds = max(0, int((end - start).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _format_completed_phases(state: dict) -> str:
    completed = state.get("completed_phases")
    phases = [str(phase) for phase in completed] if isinstance(completed, list) else []
    if not phases:
        return "(none recorded)"
    shown = phases[-8:]
    prefix = f"{len(phases)} phase{'s' if len(phases) != 1 else ''} completed"
    if len(phases) > len(shown):
        return f"{prefix}: ... -> " + " -> ".join(shown)
    return f"{prefix}: " + " -> ".join(shown)


def _phase_a_current_phase(state: dict, result_phase: str) -> str:
    phase = str(state.get("phase") or result_phase or "unknown").strip()
    retry_phase = _last_incomplete_dispatch_phase(state)
    if phase == "terminal-blocked" and retry_phase:
        return f"{retry_phase} (terminal-blocked)"
    return phase or "unknown"


def _phase_a_result_line(status: str, state: dict) -> str:
    status_label = {
        "done": "done",
        "blocked": "blocked",
        "interrupted": "interrupted",
        "budget_exhausted": "budget exhausted",
    }.get(status, status or "unknown")
    parts = [status_label]
    elapsed = _format_phase_a_elapsed(state)
    if elapsed:
        parts.append(elapsed)
    try:
        cost = float(state.get("cost_usd") or 0)
    except (TypeError, ValueError):
        cost = 0.0
    if cost:
        parts.append(f"${cost:.4f}")
    try:
        token_usage = int(state.get("token_usage") or 0)
    except (TypeError, ValueError):
        token_usage = 0
    if token_usage:
        parts.append(f"{token_usage:,} tokens")
    return "  ·  ".join(parts)


def _issue_explicitly_resolved(title: str, body: str) -> bool:
    """Recognize resolution markers, not ordinary mentions of resolved evidence."""
    return bool(
        re.search(r"(?:[✓✔]\s*RESOLVED|\[RESOLVED\]|\(RESOLVED\))\s*$", title, re.IGNORECASE)
        or re.search(r"\*\*Status(?::)?\*\*\s*:?[^\n]*\bRESOLVED\b", body, re.IGNORECASE)
        or re.search(r"(?m)^[ \t]*(?:-[ \t]*)?No action required\.?[ \t]*$", body, re.IGNORECASE)
    )


def _current_issues_recap(
    project_root: Path,
    squad_dir: Path,
    state: dict,
) -> tuple[str, str] | None:
    """Return a compact recap and absolute path for the current run's issues."""
    candidates: list[Path] = []
    for key in ("published_spec_dir", "spec_dir"):
        spec_ref = str(state.get(key) or "").strip()
        if not spec_ref:
            continue
        spec_dir = Path(spec_ref)
        if not spec_dir.is_absolute():
            spec_dir = project_root / spec_dir
        candidates.append(spec_dir / "issues.md")
    candidates.append(_run_artifact_dir(project_root, squad_dir) / "issues.md")

    seen: set[Path] = set()
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    for candidate in candidates:
        issues_path = candidate.resolve()
        if issues_path in seen:
            continue
        seen.add(issues_path)
        if not issues_path.is_file():
            continue
        try:
            issues_md = issues_path.read_text(errors="replace")
        except OSError:
            continue

        issue_blocks = re.findall(
            r"^### (ISS-\d+:\s*[^\n]+)\n(.*?)(?=^### ISS-\d+:|\Z)",
            issues_md,
            re.MULTILINE | re.DOTALL,
        )
        issues: list[str] = []
        severity_counts: dict[str, int] = {}
        for title, body in issue_blocks:
            if (
                matching_issue_resolution(
                    ledger, issue_fingerprint(title, body)
                ).get("status") == "validated"
                or _issue_explicitly_resolved(title, body)
            ):
                continue
            severity = re.search(r"\*\*Severity(?::)?\*\*\s*:?\s*(\w+)", body)
            label = severity.group(1).upper() if severity else "ISSUE"
            short_title = re.sub(r"^ISS-\d+:\s*", "", title).strip()
            issues.append(f"[{label}] {short_title}")
            severity_counts[label] = severity_counts.get(label, 0) + 1
        counts = [
            f"{severity} {severity_counts[severity]}"
            for severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
            if severity_counts.get(severity)
        ]
        recap = " · ".join(counts) if counts else "Issues recorded"
        if issues:
            recap += "\n" + "\n".join(f"- {issue}" for issue in issues)
        return recap, str(issues_path)
    return None


def _issue_resolution_requests(project_root: Path, squad_dir: Path, state: dict) -> list[dict[str, str]]:
    """Extract user-decidable issue guidance from the canonical SAGE report."""
    recap = _current_issues_recap(project_root, squad_dir, state)
    requests: list[dict[str, str]] = []
    issues_md = ""
    if recap is not None:
        _summary, issues_path_text = recap
        try:
            issues_md = Path(issues_path_text).read_text(errors="replace")
        except OSError:
            pass
    issue_blocks = re.findall(
        r"^### (ISS-\d+:\s*[^\n]+)\n(.*?)(?=^### ISS-\d+:|\Z)",
        issues_md,
        re.MULTILINE | re.DOTALL,
    )
    for title, body in issue_blocks:
        issue_id_match = re.match(r"^(ISS-\d+):\s*(.+)$", title.strip())
        if not issue_id_match:
            continue
        if _issue_explicitly_resolved(title, body):
            continue
        action = re.search(r"\*\*Action Required:\*\*\s*(.+)", body)
        amendment = re.search(r"\*\*Required Amendment\*\*:\s*(.+)", body)
        recommendation = re.search(r"\*\*Recommendation:\*\s*(.+)", body)
        severity = re.search(r"\*\*Severity(?::)?\*\*\s*:?\s*(\w+)", body)
        resolution_guidance = re.search(
            r"### Resolution Guidance\n(.*?)(?=^### |\Z)", body, re.DOTALL
        )
        guidance_text = resolution_guidance.group(1) if resolution_guidance else ""
        def guidance_field(name: str) -> str:
            match = re.search(
                rf"- \*\*{re.escape(name)}:\*\*\s*(.+)", guidance_text
            )
            return match.group(1).strip() if match else ""
        guidance = (
            action.group(1).strip()
            if action
            else amendment.group(1).strip()
            if amendment
            else recommendation.group(1).strip()
            if recommendation
            else "Provide a project-specific decision for this issue."
        )
        if guidance.lower().startswith("none"):
            continue
        request = {
            "issue_id": issue_id_match.group(1),
            "issue_fingerprint": issue_fingerprint(title, body),
            "title": issue_id_match.group(2),
            "severity": severity.group(1).upper() if severity else "ISSUE",
            "guidance": guidance,
        }
        for key, label in (
            ("suggested_option", "Suggested option"),
            ("evidence_basis", "Evidence basis"),
            ("values_not_inferable", "Values not inferable"),
            ("banzai_eligible", "Banzai eligible"),
        ):
            value = guidance_field(label)
            if value:
                request[key] = value.lower() if key == "banzai_eligible" else value
        requests.append(request)
    represented_fingerprints = {
        request["issue_fingerprint"] for request in requests
    }
    ledger = state.get("issue_resolution_ledger")
    if isinstance(ledger, dict):
        for issue_id, entry in ledger.items():
            if not isinstance(entry, dict) or entry.get("status") != "pending":
                continue
            fingerprint = str(entry.get("issue_fingerprint") or "").strip()
            if not fingerprint or fingerprint in represented_fingerprints:
                continue
            request = {
                "issue_id": str(entry.get("issue_id") or issue_id),
                "issue_fingerprint": fingerprint,
                "title": str(entry.get("title") or issue_id),
                "severity": str(entry.get("severity") or "ISSUE"),
                "guidance": str(
                    entry.get("guidance")
                    or "Apply the preserved issue resolution."
                ),
                "repair_phase": str(
                    entry.get("repair_phase") or "phase1-what"
                ),
            }
            decision = str(entry.get("decision") or "").strip()
            if decision:
                request["suggested_option"] = decision
            evidence = str(entry.get("rationale") or "").strip()
            if evidence:
                request["evidence_basis"] = evidence
            requests.append(request)
            represented_fingerprints.add(fingerprint)
    return requests


def _issue_resolution_guidance_recap(
    project_root: Path, squad_dir: Path, state: dict
) -> str:
    """Render every unresolved issue's next decision without truncation."""
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    lines: list[str] = []
    for request in _issue_resolution_requests(project_root, squad_dir, state):
        entry = matching_issue_resolution(ledger, request["issue_fingerprint"])
        if entry.get("status") == "validated":
            continue
        lines.append(
            f"- {request['issue_id']} [{request['severity']}]: {request['guidance']}"
        )
    return "\n".join(lines)


def _issue_resolution_screen_guidance(
    project_root: Path, squad_dir: Path, state: dict
) -> list[tuple[str, str]]:
    """Return all actionable issue details for CLI banners without hidden files."""
    recap = _current_issues_recap(project_root, squad_dir, state)
    if recap is None:
        return []
    _summary, issues_path_text = recap
    issues_path = Path(issues_path_text)
    ledger = state.get("issue_resolution_ledger")
    ledger = ledger if isinstance(ledger, dict) else {}
    fields: list[tuple[str, str]] = [
        ("issues file", str(issues_path)),
        ("open issues", issues_path.as_uri()),
    ]
    unresolved_requests = [
        request
        for request in _issue_resolution_requests(project_root, squad_dir, state)
        if not (
            matching_issue_resolution(
                ledger, request["issue_fingerprint"]
            ).get("status") == "validated"
        )
    ]
    for index, request in enumerate(unresolved_requests):
        lines = [
            f"{request['title']} [{request['severity']}]",
            f"action: {request['guidance']}",
        ]
        suggested = request.get("suggested_option", "")
        if suggested and suggested.lower() != "none":
            lines.append(f"suggested: {suggested}")
            lines.append(
                f"accept: echelon spec resolve {request['issue_id']} {shlex.quote(suggested)}"
            )
        else:
            lines.append(
                f"resolve: echelon spec resolve {request['issue_id']} '<decision>'"
            )
        evidence = request.get("evidence_basis", "")
        if evidence and evidence.lower() != "none":
            lines.append(f"evidence: {evidence}")
        unknown = request.get("values_not_inferable", "")
        if unknown and unknown.lower() != "none":
            lines.append(f"user decides: {unknown}")
        rendered = "\n".join(lines)
        if index == 0:
            fields.append(("next issue", rendered))
        fields.append((request["issue_id"], rendered))
    return fields


def _is_issue_resolution_recovery(action: _RunRecoveryAction) -> bool:
    """Return whether one classified action authorizes issue-resolution CLI."""
    return action.command.startswith("echelon spec resolve ")


def _register_spec_summary_run(
    project_root: Path,
    squad_dir: Path,
    *,
    mode: object,
    message: object,
    implementation_targets: object = (),
) -> None:
    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is None:
        return
    scope.run_dir = Path(squad_dir)
    scope.mode = str(mode or "semi")
    scope.message = str(message or "")
    if isinstance(implementation_targets, (list, tuple)):
        scope.implementation_targets = tuple(
            str(value) for value in implementation_targets if str(value).strip()
        )


def _note_spec_summary_next_printed() -> None:
    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is not None:
        scope.next_already_printed = True


@contextmanager
def _spec_summary_session(project_root: Path, command: str):
    active = _SPEC_SUMMARY_SCOPE.get()
    if active is not None:
        yield active
        return
    scope = _SpecSummaryScope(
        project_root=Path(project_root).resolve(),
        command=command,
    )
    token = _SPEC_SUMMARY_SCOPE.set(scope)
    try:
        yield scope
    finally:
        try:
            if scope.run_dir is not None and not scope.emitted:
                state_file = scope.run_dir / "state.json"
                state = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(state, dict) and state:
                    persisted_targets = state.get("implementation_targets")
                    fallback_targets = (
                        tuple(
                            str(value)
                            for value in persisted_targets
                            if str(value).strip()
                        )
                        if isinstance(persisted_targets, list)
                        else ()
                    )
                    _print_squad_summary(
                        scope.project_root,
                        scope.run_dir,
                        object(),
                        mode=scope.mode,
                        message=scope.message
                        or str(state.get("user_message") or ""),
                        implementation_targets=list(
                            scope.implementation_targets
                            or fallback_targets
                        ),
                        command=scope.command,
                        include_next=not scope.next_already_printed,
                    )
        except BaseException:
            pass
        finally:
            _SPEC_SUMMARY_SCOPE.reset(token)


def _phase_a_summary_facts(
    state: Mapping[str, object],
    *,
    spec_dir: str,
    stopped: str,
    publication_verified: bool = False,
):
    from harness.run_summary import (
        SummaryFact,
        SummaryFactCategory,
        SummaryFactImportance,
    )

    facts: list[SummaryFact] = []
    if spec_dir and publication_verified:
        facts.append(
            SummaryFact(
                SummaryFactCategory.WORK,
                SummaryFactImportance.HIGH,
                f"Published the specification at {spec_dir}.",
                len(facts),
            )
        )
    completed = tuple(
        str(value).strip()
        for value in state.get("completed_phases", ())
        if str(value).strip()
    )
    repair_state = state.get("phase1_quality_repair")
    certificate = state.get("spec_quality_certificate")
    if isinstance(repair_state, Mapping) and isinstance(certificate, Mapping):
        consumed = int(repair_state.get("automatic_consumed", 0) or 0)
        if (
            repair_state.get("authoring_mode") == "proportional"
            and certificate.get("status") == "passed"
        ):
            if consumed == 1:
                quality_text = (
                    "One proportional quality repair produced a passing "
                    "specification quality certificate."
                )
            elif consumed > 1:
                quality_text = (
                    f"{consumed} proportional quality repairs produced a passing "
                    "specification quality certificate."
                )
            else:
                quality_text = (
                    "The proportional quality review produced a passing "
                    "specification quality certificate."
                )
            facts.append(
                SummaryFact(
                    SummaryFactCategory.VERIFICATION,
                    SummaryFactImportance.HIGH,
                    quality_text,
                    len(facts),
                )
            )
    if completed:
        facts.append(
            SummaryFact(
                SummaryFactCategory.HANDOFF,
                SummaryFactImportance.NORMAL,
                f"Completed {len(completed)} specification phases and preserved "
                "durable state.",
                len(facts),
            )
        )
    if stopped and stopped != "completed":
        facts.append(
            SummaryFact(
                SummaryFactCategory.BLOCKER,
                SummaryFactImportance.CRITICAL,
                f"Specification work stopped because {stopped}.",
                len(facts),
            )
        )
    counts = state.get("phase_dispatch_counts")
    if isinstance(counts, Mapping) and counts and all(type(value) is int and value >= 0 for value in counts.values()):
        facts.append(SummaryFact(
            SummaryFactCategory.HANDOFF, SummaryFactImportance.NORMAL,
            f"Current dispatch counters record {sum(counts.values())} phase executions; completed-phase totals count distinct phases, not executions.",
            len(facts),
        ))
    return tuple(facts)


def _print_squad_summary(
    project_root: Path,
    squad_dir: Path,
    result: object,
    *,
    mode: str,
    message: str,
    implementation_targets: list[str] | None = None,
    command: str = "echelon spec run",
    include_next: bool = True,
) -> None:
    """Render a delivery-style Phase A/spec authoring summary."""
    import json as _json

    scope = _SPEC_SUMMARY_SCOPE.get()
    if scope is not None:
        if scope.emitted:
            return

    state: dict = {}
    state_file = squad_dir / "state.json"
    if state_file.exists():
        try:
            state = _json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    status = str(getattr(result, "status", "") or state.get("status") or "unknown")
    result_phase = str(getattr(result, "phase", "") or "")
    action = (
        _classify_run_recovery(state, project_root=project_root)
        if state
        else _RunRecoveryAction("advance")
    )
    spec_id = str(state.get("spec_id") or "").strip()
    spec_dir = str(state.get("published_spec_dir") or state.get("spec_dir") or "").strip()
    if not spec_id and spec_dir:
        spec_id = Path(spec_dir).name

    icon = {
        "done": "✓",
        "blocked": "✗",
        "interrupted": "◐",
        "budget_exhausted": "✗",
    }.get(status, "•")
    status_text = {
        "done": "DONE",
        "blocked": "BLOCKED",
        "interrupted": "INTERRUPTED",
        "budget_exhausted": "BUDGET EXHAUSTED",
    }.get(status, status.upper() if status else "UNKNOWN")

    fields: list[tuple[str, str]] = []
    if spec_id:
        fields.append(("spec", spec_id))
    fields.append(("mode", mode))
    if implementation_targets:
        fields.append(("targets", ", ".join(implementation_targets)))
    if message:
        fields.append(("task", message))

    current_phase = _phase_a_current_phase(state, result_phase)
    fields.append(("current", current_phase))
    if spec_dir:
        fields.append(("spec dir", spec_dir))
    fields.append(("artifacts", str(squad_dir)))
    fields.append(("done", _format_completed_phases(state)))

    stopped = ""
    if status == "blocked":
        stopped = action.reason or str(state.get("blocked_reason") or "").strip() or "blocked"
    elif status == "interrupted":
        stopped = action.reason or "interrupted"
    elif status == "budget_exhausted":
        stopped = "token budget exhausted"
    elif status == "done":
        stopped = "completed"
    if stopped:
        fields.append(("stopped", stopped))
    provider_message = str(state.get("provider_limit_message") or "").strip()
    if provider_message:
        fields.append(("provider limit", provider_message))

    debt_facts = _current_quality_debt_cli_facts(state, project_root)
    if debt_facts is not None:
        fields.append(("specification quality", "accepted with quality debt"))
        debt_gates = debt_facts["failed_gates"]
        if debt_gates:
            fields.append(("residual gates", ", ".join(debt_gates)))
        debt_issues = debt_facts["qualitative_issues"]
        if debt_issues:
            fields.append(("residual SAGE", ", ".join(debt_issues)))
        if debt_facts["resolved_by"]:
            fields.append(("debt resolver", str(debt_facts["resolved_by"])))
        if debt_facts["artifact"]:
            fields.append(("debt evidence", str(debt_facts["artifact"])))

    if status in {"blocked", "interrupted", "budget_exhausted"}:
        if action.note:
            fields.append(("note", action.note))
        if status == "blocked" and _is_issue_resolution_recovery(action):
            issues_recap = _current_issues_recap(project_root, squad_dir, state)
            if issues_recap:
                recap, issues_path = issues_recap
                fields.append(("issues", recap))
                guidance = _issue_resolution_guidance_recap(project_root, squad_dir, state)
                if guidance:
                    fields.append(("decisions", guidance))
                fields.extend(
                    _issue_resolution_screen_guidance(project_root, squad_dir, state)
                )
    try:
        summary_decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError):
        summary_decision = None
    if summary_decision is not None:
        fields.extend(_decision_audit_fields(summary_decision))
        fields.extend(
            _proportional_quality_decision_fields(state, summary_decision)
        )
    result_line = _phase_a_result_line(status, state)
    fields.append(("result", result_line))
    next_step = ""
    if status == "done" and spec_id:
        next_step = f"echelon delivery run {spec_id}"
    elif status in {"blocked", "interrupted", "budget_exhausted"}:
        next_step = action.command

    from harness.run_summary import RunSummaryContext, summarize_run_for_cli

    published = state.get("published_spec_dir")
    published_path = Path(str(published)) if published else None
    if published_path is not None and not published_path.is_absolute():
        published_path = project_root / published_path
    publication_verified = bool(published_path is not None and (published_path / "spec.md").is_file())
    facts = _phase_a_summary_facts(state, spec_dir=spec_dir, stopped=stopped, publication_verified=publication_verified)
    worked_on = summarize_run_for_cli(
        RunSummaryContext(
            project_root=project_root,
            command=command,
            task=message,
            status=status,
            facts=facts,
            next_step=next_step,
            quality_debt_status=(
                str(debt_facts["status"]) if debt_facts is not None else ""
            ),
            quality_debt_artifact=(
                str(debt_facts["artifact"]) if debt_facts is not None else ""
            ),
            quality_debt_failed_gates=(
                tuple(debt_facts["failed_gates"])
                if debt_facts is not None
                else ()
            ),
            quality_debt_qualitative_issues=(
                tuple(debt_facts["qualitative_issues"])
                if debt_facts is not None
                else ()
            ),
            quality_debt_resolved_by=(
                str(debt_facts["resolved_by"])
                if debt_facts is not None
                else ""
            ),
            provider_limit_message=provider_message,
        )
    )
    fields.append(("worked on", worked_on))
    if next_step and include_next:
        fields.append(("next", next_step))
    _banner("SQUAD SUMMARY", fields, subtitle=f"{icon} {status_text}")
    if scope is not None:
        scope.emitted = True


def _normalize_rewind_spec_dir(project_root: Path, state: dict) -> tuple[Path | None, str | None]:
    retarget = state.get("retarget")
    published_ref = str(state.get("published_spec_dir") or "").strip()
    if isinstance(retarget, dict) and published_ref:
        published = Path(published_ref)
        if published.is_absolute():
            try:
                relative_published = published.relative_to(project_root)
            except ValueError:
                relative_published = None
        else:
            relative_published = published
            published = project_root / published
        if (
            relative_published is not None
            and relative_published.parts[:1] == ("specs",)
            and published.is_dir()
            and not published.is_symlink()
            and published.name == state.get("spec_id")
        ):
            return published, str(relative_published)
    ref = str(state.get("spec_dir") or "").strip()
    if ref:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        try:
            rel_candidate = candidate.relative_to(project_root)
            if rel_candidate.parts and rel_candidate.parts[0] == "runs":
                if candidate.exists():
                    return candidate, str(rel_candidate)
        except ValueError:
            pass
        parts = candidate.parts
        if "specs" in parts:
            idx = parts.index("specs")
            suffix = Path(*parts[idx:])
            project_candidate = project_root / suffix
            if project_candidate.exists():
                return project_candidate, str(suffix)
        if candidate.exists():
            try:
                return candidate, str(candidate.relative_to(project_root))
            except ValueError:
                return candidate, str(candidate)
    return None, None


def _cleanup_rewind_outputs(spec_dir: Path, phase: str, run_dir: Path | None = None) -> list[str]:
    removed: list[str] = []
    roots = [spec_dir]
    if run_dir is not None:
        run_shadow = run_dir / spec_dir.parent.name / spec_dir.name
        if run_shadow not in roots:
            roots.append(run_shadow)
    for rel in _REWIND_CLEANUP_OUTPUTS.get(phase, ()):
        removed_here = False
        for root in roots:
            path = root / rel
            if path.exists():
                path.unlink()
                removed_here = True
        if removed_here:
            removed.append(rel)
    return removed


def _reset_rewind_state(
    state: dict,
    phase: str,
    spec_dir_ref: str,
    *,
    checkpoint_phases_before_target: set[str] | None = None,
    boundary_completion_id: str = "",
    preserve_resolved_gate_rejection: bool = False,
    preserve_resolved_coverage_map_repair: bool = False,
    preserve_failed_human_gate_for_cas: bool = False,
) -> dict:
    rewound = dict(state)
    rewound["phase"] = phase
    rewound["status"] = "running"
    rewound["iteration"] = 0
    rewound["spec_dir"] = spec_dir_ref
    rewound["blocked_reason"] = None
    decision: Mapping[str, object] | None = None
    try:
        decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        from echelon.rewind import RewindError

        raise RewindError(f"versioned decision authority is invalid: {exc}") from exc
    if decision is not None:
        resolved_gate_rejection = (
            preserve_resolved_gate_rejection
            and decision["status"] == "resolved"
            and decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("blocked_reason") == "gate_rejected"
        )
        resolved_coverage_map_repair = (
            preserve_resolved_coverage_map_repair
            and decision["status"] == "resolved"
            and decision["source_kind"] == "human_gate"
        )
        failed_human_gate = (
            preserve_failed_human_gate_for_cas
            and decision["status"] == "failed"
            and decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("phase") == decision.get("source_phase")
        )
        if not (
            resolved_gate_rejection
            or resolved_coverage_map_repair
            or failed_human_gate
        ):
            from echelon.rewind import RewindError

            raise RewindError(
                "versioned decision authority requires its source-specific recovery"
            )
    else:
        rewound["escalation_question"] = None
        rewound["escalation_resolved"] = False
        rewound["escalation_resolver"] = None
    rewound.pop("phase_a_readiness_blockers", None)
    # A rewind reopens the target phase's owned repair loop.  Retaining an
    # exhausted Lexicon certificate makes CARTOGRAPHER/ORCHESTRATOR conclude
    # that they have no repair budget before they inspect the restored files.
    # Reset only the gates whose owning phase is being revisited.
    try:
        phase_index = _ROADMAP_PHASES.index(phase)
    except ValueError:
        phase_index = len(_ROADMAP_PHASES)
    # Issues, selected resolutions, and WHY failure counters are valid only
    # for the artifact epoch that produced them. Rewinding before WHY2 must not
    # let a stale spec review steer discovery or assumption validation.
    if phase_index <= _ROADMAP_PHASES.index("phase1-why2"):
        rewound.pop("spec_quality_certificate", None)
        for key in (
            "issue_resolution_ledger",
            "selected_issue_resolution",
            "issue_resolution_recovery",
            "issue_resolution_repair_baseline",
            "phase_dispatch_limit_recovery",
            "issues_log",
            "why_failure_baseline",
        ):
            rewound.pop(key, None)
        rewound["why_fail_count"] = 0
        rewound["why2_metric_stagnation_count"] = 0
    if phase_index <= _ROADMAP_PHASES.index("phase1-lexicon"):
        rewound.pop("lexicon_pass", None)
        rewound["lexicon_attempts"] = 0
        rewound.pop("lexicon_findings", None)
        rewound.pop("lexicon_report", None)
        rewound.pop("lexicon_warning_waiver", None)
        rewound["lexicon_evaluation"] = "pending"
        rewound.pop("lexicon_gate_exhausted", None)
    if phase_index <= _ROADMAP_PHASES.index("phase3-plan"):
        rewound["tasks_lexicon_pass"] = None
        rewound["tasks_lexicon_attempts"] = 0
        rewound.pop("tasks_lexicon_gate_exhausted", None)
    if rewound.get("checkpoint_policy_version") == 2:
        from echelon.rewind import RewindError

        outcomes = rewound.get("phase_completion_outcomes")
        if type(outcomes) is not list or not boundary_completion_id:
            raise RewindError("versioned checkpoint boundary is missing")
        matches = [
            index
            for index, outcome in enumerate(outcomes)
            if type(outcome) is dict
            and outcome.get("completion_id") == boundary_completion_id
            and outcome.get("phase") == phase
            and outcome.get("outcome") == "executed"
        ]
        if len(matches) != 1:
            raise RewindError("versioned checkpoint boundary is invalid")
        retained_outcomes = outcomes[: matches[0]]
        rewound["phase_completion_outcomes"] = retained_outcomes
        completed: list[str] = []
        for outcome in retained_outcomes:
            if type(outcome) is not dict or outcome.get("outcome") != "executed":
                continue
            completed_phase = outcome.get("phase")
            if isinstance(completed_phase, str) and completed_phase not in completed:
                completed.append(completed_phase)
        rewound["completed_phases"] = completed
        counts = rewound.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            rewound["phase_dispatch_counts"] = {
                key: value for key, value in counts.items() if key in completed
            }
    elif checkpoint_phases_before_target is not None:
        completed = rewound.get("completed_phases")
        primary_predecessors: list[str] = []
        if phase in _ROADMAP_PHASES:
            primary_predecessors = _ROADMAP_PHASES[:_ROADMAP_PHASES.index(phase)]
        if isinstance(completed, list):
            # Checkpoints are deliberately sparse: the roadmap's primary
            # predecessors are known complete when rewinding to a later phase,
            # even if no individual checkpoint was emitted for them.  Preserve
            # any additional checkpointed branch phases after that backbone.
            retained = [
                item
                for item in completed
                if item in checkpoint_phases_before_target and item not in _ROADMAP_PHASES
            ]
            rewound["completed_phases"] = primary_predecessors + [
                item for item in retained if item not in primary_predecessors
            ]
        counts = rewound.get("phase_dispatch_counts")
        if isinstance(counts, dict):
            rewound["phase_dispatch_counts"] = {
                key: value
                for key, value in counts.items()
                if key in rewound.get("completed_phases", [])
            }
    return rewound


def _iter_run_dirs(project_root: Path) -> list[Path]:
    """Return all spec run dirs under runs/, sorted newest-first."""
    dirs: list[Path] = []
    base = project_root / "runs"
    if base.exists():
        for d in base.iterdir():
            if _is_squad_run_dir(d):
                dirs.append(d)
    dirs.sort(key=lambda d: d.name, reverse=True)
    return dirs


def _is_squad_run_dir(path: Path, *, require_state: bool = True) -> bool:
    """Whether ``path`` is a resumable Phase-A squad run.

    Verify-spec audits also persist a ``state.json`` under ``runs/``.  Their
    lifecycle is intentionally bounded and read-only, so they must never be
    selected by generic planning commands such as ``echelon spec continue``.
    """
    if not path.is_dir() or (require_state and not (path / "state.json").is_file()):
        return False
    return not path.name.startswith("verify-spec-")


def _has_tracked_checkout_changes(project_root: Path) -> bool:
    import subprocess as _subprocess

    try:
        result = _subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return False
    return bool(result.stdout.strip())


def _constitution_template_markers(text: str) -> list[str]:
    import re as _re

    explicit_markers = (
        "[PROJECT_NAME]",
        "[CONSTITUTION_VERSION]",
        "[RATIFICATION_DATE]",
        "[LAST_AMENDED_DATE]",
    )
    markers = [marker for marker in explicit_markers if marker in text]
    markers.extend(sorted(set(_re.findall(r"\[PRINCIPLE_[0-9]+_NAME\]", text))))
    return markers


_HARNESS_CHECKPOINT_REASONS = {"build_incomplete", "publish_failed", "checkpoint_outer_cap"}


def _phase_a_buildable(result_status: str, blockers: list) -> bool:
    """Single readiness predicate for Phase-A surfaces.

    A run is buildable only when there are no outstanding blockers AND the run
    is not in a blocked/interrupted lifecycle state. A blocked run with an empty
    blocker list (e.g. it halted before the spec/HOW/tasks checks could flag
    anything) must NOT be reported as ready — that was the false "READY TO BUILD"
    bug (docs/findings/2026-06-20-blocked-run-reports-ready-to-build.md).
    """
    return not blockers and result_status not in ("blocked", "interrupted")


def _canonical_delivery_lifecycle(
    project_root: Path,
) -> tuple[str, str, Path] | None:
    """Resolve terminal lifecycle state from the published default-branch tree."""
    import json as _json

    run_dir = _find_current_run_dir(project_root)
    state: dict = {}
    if run_dir is not None and (run_dir / "state.json").is_file():
        try:
            loaded = _json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            loaded = {}
        if isinstance(loaded, dict):
            state = loaded

    if (
        state
        and str(state.get("status") or "") != "done"
        and (project_root / "runs" / ".current").is_file()
    ):
        return None

    spec_id = str(state.get("spec_id") or "").strip()
    candidate = _published_continue_spec_dir(project_root, state)
    if candidate is None and not spec_id:
        candidate = _single_project_spec_dir(project_root)
        spec_id = candidate.name if candidate is not None else ""
    if candidate is None:
        return None

    try:
        from harness.spec_frontmatter import read_frontmatter

        working_status = str(read_frontmatter(candidate).get("status") or "").strip()
    except (OSError, ValueError, TypeError):
        return None

    try:
        import yaml as _yaml
        from echelon.phase_a_git import resolve_phase_a_default_branch
        from harness.config import get_full_resolved_config

        resolved = get_full_resolved_config(project_root)
        configured = resolved.get("target_default_branch", "")
        if not configured and isinstance(resolved.get("harness"), dict):
            configured = resolved["harness"].get("target_default_branch", "")
        default_branch, _default_commit = resolve_phase_a_default_branch(
            project_root,
            str(configured or ""),
        )
        relpath = f"specs/{candidate.name}/spec.md"
        published = subprocess.run(
            ["git", "show", f"{default_branch}:{relpath}"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        published_status = ""
        if published.returncode == 0:
            match = re.match(
                r"^---\n(.*?)\n---(?:\n|$)",
                published.stdout,
                re.DOTALL,
            )
            metadata = _yaml.safe_load(match.group(1)) if match else {}
            if isinstance(metadata, dict):
                published_status = str(metadata.get("status") or "").strip()
    except Exception:
        published_status = ""

    if published_status == "landed" and working_status == "landed":
        return "landed", spec_id or candidate.name, candidate
    if working_status == "landed":
        return "pending_publication", spec_id or candidate.name, candidate
    return None


def _print_terminal_delivery_lifecycle(project_root: Path) -> bool:
    lifecycle = _canonical_delivery_lifecycle(project_root)
    if lifecycle is None:
        return False
    status, spec_id, spec_dir = lifecycle
    if status == "landed":
        _banner(
            "NEXT STEP",
            [
                ("spec", spec_id),
                ("status", "landed"),
                ("spec directory", str(spec_dir)),
                ("next", "No action required; delivery is already landed."),
            ],
            subtitle="LANDED",
        )
    else:
        _banner(
            "NEXT STEP",
            [
                ("spec", spec_id),
                ("status", "landing finalization pending"),
                ("spec directory", str(spec_dir)),
                ("next", f"echelon delivery land {spec_id}"),
            ],
            subtitle="FINALIZATION PENDING",
        )
    return True


def _print_next_steps(project_root: Path, result_status: str) -> None:
    """Print actionable next-step guidance after a run completes or blocks.

    Checks build readiness (constitution, quality gates, HOW phase, tasks) and
    surfaces either 'ready to build' or a prioritised list of blockers. Silent
    when the run is still in progress (status not in done/blocked/interrupted).
    """
    import json as _json
    import re as _re

    if result_status not in ("done", "blocked", "interrupted"):
        return

    if _print_terminal_delivery_lifecycle(project_root):
        return

    # ── Latest harness build owns next-step guidance when present ───────────
    harness_state = _find_latest_harness_build_state(project_root)
    if harness_state:
        spec_id = str(harness_state.get("spec_id") or "")
        pr_url = harness_state.get("pr_url")
        harness_status = str(harness_state.get("status") or "unknown")
        termination_reason = str(harness_state.get("termination_reason") or "")
        fields: list[tuple[str, str]] = [("spec", spec_id)] if spec_id else []
        if harness_status == "converged":
            if pr_url:
                fields.append(("PR", pr_url))
                fields.append(("next", f"echelon delivery land {spec_id}"))
            else:
                fields.append(("next", f"echelon delivery land {spec_id}"))
            _banner("NEXT STEP", fields, subtitle="Harness build converged — ready to land")
            return
        fields.append(("harness status", harness_status))
        if termination_reason:
            fields.append(("reason", termination_reason))
        build_status = str(harness_state.get("build_status") or "")
        build_reason = str(harness_state.get("build_reason") or "")
        if build_status:
            fields.append(("build status", build_status))
        if build_reason and build_reason != "None":
            fields.append(("build reason", build_reason))
        provider_reset_hint = str(harness_state.get("provider_reset_hint") or "")
        provider_limit_message = str(harness_state.get("provider_limit_message") or "")
        if provider_limit_message:
            fields.append(("provider", provider_limit_message))
        if provider_reset_hint:
            fields.append(("reset", provider_reset_hint))
        tokens_used = harness_state.get("tokens_used")
        if build_status == "provider_session_limit":
            fields.append(("token accounting", f"{int(tokens_used or 0):,} tokens recorded before provider stop"))
        salvage_commit = str(harness_state.get("salvage_commit") or "")
        salvage_branch = str(harness_state.get("salvage_branch") or "")
        salvage_verified = str(harness_state.get("salvage_verified") or "")
        if salvage_commit:
            fields.append(("salvage commit", salvage_commit[:12]))
        if salvage_branch:
            fields.append(("salvage branch", salvage_branch))
        if salvage_verified:
            fields.append(("salvage verified", salvage_verified))
        is_checkpoint = termination_reason in _HARNESS_CHECKPOINT_REASONS
        coverage_map_planning_defect = _coverage_map_planning_defect_for_spec(
            project_root,
            spec_id,
        )
        if build_status == "provider_session_limit":
            fields.append(("next", f"wait for provider reset, then echelon delivery continue {spec_id}"))
            subtitle = "HARNESS PROVIDER SESSION LIMIT"
        elif termination_reason == "build_blocked":
            if coverage_map_planning_defect:
                fields.append(
                    (
                        "next",
                        "echelon spec rewind phase3-sentinel\n"
                        "  then echelon spec rewind phase3-sentinel --confirm\n"
                        "  then echelon spec continue",
                    )
                )
            else:
                fields.append(("next", f"resolve the reported blocker, then echelon spec reopen {spec_id}"))
            subtitle = "HARNESS BUILD BLOCKED"
        elif is_checkpoint:
            if _has_tracked_checkout_changes(project_root):
                fields.append(
                    (
                        "blocked by",
                        "tracked checkout changes block harness recovery",
                    )
                )
                fields.append(
                    (
                        "next",
                        f"commit or stash tracked changes, then echelon delivery continue {spec_id}",
                    )
                )
            else:
                fields.append(("next", f"echelon delivery continue {spec_id}"))
        elif termination_reason == "docker_unavailable":
            fields.append(("fix", "start the configured container runtime and wait until it reports running"))
            fields.append(("next", f"echelon delivery continue {spec_id}"))
            subtitle = "HARNESS BUILD BLOCKED"
        elif harness_status in {"running", "in_progress"}:
            fields.append(("next", "echelon spec status"))
            subtitle = "HARNESS BUILD IN PROGRESS"
        else:
            fields.append(("next", f"echelon delivery run {spec_id} --reset"))
            subtitle = "HARNESS BUILD BLOCKED"
        if is_checkpoint and build_status != "provider_session_limit":
            subtitle = "HARNESS BUILD CHECKPOINTED"
        _banner("NEXT STEP", fields, subtitle=subtitle)
        return

    # ── Gather signals ──────────────────────────────────────────────────────
    blockers: list[str] = []
    warnings: list[str] = []
    ready_items: list[str] = []
    current_state: dict = {}
    run_dir = _find_current_run_dir(project_root)
    if run_dir and (run_dir / "state.json").exists():
        try:
            current_state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            current_state = {}

    if result_status in {"blocked", "interrupted"}:
        action = _classify_run_recovery(current_state, project_root=project_root)
        if action.kind == "human_resume":
            question = action.note
            if run_dir is not None:
                from harness.squad import _checkpoint_context

                phase = str(current_state.get("phase") or "")
                label = {
                    "checkpoint-assess": "Phase 1 Checkpoint",
                    "checkpoint-plan": "Plan Checkpoint",
                }.get(phase, phase)
                question += _checkpoint_context(
                    current_state,
                    node_id=phase,
                    node_label=label,
                    journal_path=run_dir / "reasoning-journal.jsonl",
                )
            fields = [
                ("reason", action.reason),
                ("question", question),
            ]
            rendered_options = _render_escalation_options(
                current_state.get("escalation_options")
            )
            if rendered_options:
                fields.append(("options", rendered_options))
            fields.append(("next", action.command))
            _banner("NEXT STEP", fields, subtitle="RUN BLOCKED — answer required")
            return
        if action.kind == "safe_rewind":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase or "?"),
                ("next", action.command),
            ]
            _banner("NEXT STEP", fields, subtitle="RUN BLOCKED")
            return
        if action.kind == "retry_phase":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase),
                ("next", action.command),
                ("note", action.note),
            ]
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN INTERRUPTED" if result_status == "interrupted" else "RUN BLOCKED",
            )
            return
        if action.kind == "resolve_decision":
            fields = [
                ("reason", action.reason),
                ("phase", action.phase),
                ("next", action.command),
                ("note", action.note),
            ]
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN BLOCKED — controller-owned decision resolution pending",
            )
            return
        if action.kind == "manual_recovery":
            fields = [
                ("reason", action.reason),
                ("note", action.note),
            ]
            if action.command:
                fields.insert(1, ("next", action.command))
            if run_dir is not None and _is_issue_resolution_recovery(action):
                fields.extend(
                    _issue_resolution_screen_guidance(project_root, run_dir, current_state)
                )
            _banner(
                "NEXT STEP",
                fields,
                subtitle="RUN INTERRUPTED — manual recovery required"
                if result_status == "interrupted"
                else "RUN BLOCKED — manual recovery required",
            )
            return

    # 1. Constitution — phase provenance first, artifact integrity second
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if current_state and "phase1-constitution" not in completed_phases:
        blockers.append(
            "phase1-constitution has not completed in this run\n"
            "     → echelon spec continue\n"
            "       (CHIEF will author the constitution and record provenance)"
        )
    elif not const_path.exists():
        blockers.append(
            "constitution.md absent\n"
            "     → echelon spec continue\n"
            "       (CHIEF will author the constitution)"
        )
    else:
        markers = _constitution_template_markers(const_path.read_text(errors="replace"))
        if markers:
            blockers.append(
                "unresolved constitution template markers remain: "
                + ", ".join(markers)
                + "\n"
                "     → echelon spec continue\n"
                "       (CHIEF will repair constitution.md before continuing)"
            )
        else:
            ready_items.append("constitution.md ✓")

    # 2. Quality gates — prefer the active run spec root. Published specs/ is
    # the build-harness target, not the source of truth for an in-progress squad.
    specs_root = project_root / "specs"
    active_spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    published_spec_dir: Path | None = None
    if result_status == "done":
        published_spec_dir = _published_continue_spec_dir(project_root, current_state)
        if published_spec_dir and (published_spec_dir / "tasks.md").exists():
            active_spec_dir = published_spec_dir

    # Pre-check: if tasks.md already exists, the run completed all phases past quality gates.
    # Also capture newest_spec_id here so the build command always has the actual spec name.
    tasks_exist_in_spec = False
    newest_spec_id = str(current_state.get("spec_id") or "").strip()
    if active_spec_dir is not None:
        newest_spec_id = newest_spec_id or active_spec_dir.name
        tasks_exist_in_spec = (active_spec_dir / "tasks.md").exists()

    quality_gates_file: Optional[Path] = None
    if active_spec_dir is not None:
        qg = active_spec_dir / "quality-gates.md"
        if qg.exists():
            quality_gates_file = qg

    # Blocked runs may not have finalized to specs/ yet — load state once for reuse
    run_dir = _find_current_run_dir(project_root)
    run_state: dict = {}
    if run_dir:
        try:
            run_state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            pass
    if not newest_spec_id:
        newest_spec_id = str(run_state.get("spec_id") or "").strip()

    if quality_gates_file is None and run_state:
        staging_dir = Path(run_state.get("staging_dir") or str(run_dir / "staging"))
        staging_qg = staging_dir / "quality-gates.md"
        if staging_qg.exists():
            quality_gates_file = staging_qg

    hard_fails: list[str] = []
    borderline: list[str] = []
    fail_scores: dict[str, tuple[str, str]] = {}  # gate -> (score, threshold)
    qg_verdict = ""

    if quality_gates_file:
        qg_text = quality_gates_file.read_text(errors="replace")

        verdict_m = _re.search(r"^##\s+Verdict:\s+(PASS|FAIL|BLOCKED)", qg_text, _re.MULTILINE)
        qg_verdict = verdict_m.group(1) if verdict_m else ""

        # Parse gate rows: | Gate | score | threshold | PASS/FAIL | note |
        # Matches plain FAIL and bold **FAIL** (NEVER rule in sage.md enforces plain text)
        gate_pattern = _re.compile(
            r"\|\s*(Overall|Structure|Testability|Semantic|Cognitive|Readability|Behavioral|Depth)"
            r"\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|\s*\*{0,2}FAIL\*{0,2}\s*\|([^|]*)\|",
        )
        for m in gate_pattern.finditer(qg_text):
            gate, score, threshold, note = (
                m.group(1), m.group(2).strip(), m.group(3).strip(), m.group(4)
            )
            fail_scores[gate] = (score, threshold)
            note_lower = note.lower()
            if "borderline" in note_lower and "not borderline" not in note_lower:
                borderline.append(gate)
            else:
                hard_fails.append(gate)

        if hard_fails:
            fail_detail = ", ".join(
                f"{g} {fail_scores[g][0]} (need {fail_scores[g][1]})"
                if g in fail_scores else g
                for g in hard_fails
            )
            if tasks_exist_in_spec:
                # Run already completed all phases past quality gates — quality debt, not a blocker
                warnings.append(
                    f"Quality debt: WHY gates FAIL: {fail_detail}\n"
                    f"  (run converged past gates — amendment improves future estimates)"
                )
            else:
                blockers.append(
                    f"WHY2 quality gates FAIL: {fail_detail}\n"
                    f"     → echelon spec continue\n"
                    f"       (CARTOGRAPHER amendment pass, then WHY2 re-validates)"
                )
        if borderline:
            warnings.append(
                f"WHY2 borderline: {', '.join(borderline)} — monitor after CARTOGRAPHER amendment"
            )
        # Verdict FAIL/BLOCKED with no numeric rows = SAGE ran in BLOCKED mode (spec.md absent)
        if qg_verdict in ("FAIL", "BLOCKED") and not hard_fails and not borderline:
            if not tasks_exist_in_spec:
                blockers.append(
                    "WHY2 BLOCKED — spec.md absent: CARTOGRAPHER has not written it yet\n"
                    "     → echelon spec continue\n"
                    "       (CARTOGRAPHER will write spec.md, then WHY2 re-validates)"
                )
        if not hard_fails and not borderline and qg_verdict not in ("FAIL", "BLOCKED"):
            ready_items.append("WHY2 quality gates ✓")
    else:
        warnings.append("WHY2 not yet run — spec validation pending")

    # 3. HOW phase artifacts — only surface when quality gates have passed
    # (if gates are hard-failing, HOW/tasks missing is expected and not actionable yet)
    # Borderline-only quality gates still allow Phase 3 to proceed.
    # Skip HOW check entirely when tasks.md already exists — the run completed,
    # so HOW was done (possibly with different artifact names for this workflow).
    why2_passed = tasks_exist_in_spec or (
        quality_gates_file is not None
        and not hard_fails  # borderline-only is fine — only hard fails block Phase 3
    )
    how_present = 0
    how_missing = []
    if why2_passed and not tasks_exist_in_spec and active_spec_dir is not None:
        for fname in ("plan.md", "research.md", "data-model.md"):
            if (active_spec_dir / fname).exists():
                how_present += 1
            else:
                how_missing.append(fname)

    if how_missing:
        missing_str = ", ".join(dict.fromkeys(how_missing))  # dedup, preserve order
        blockers.append(
            f"HOW phase not run — {missing_str} absent\n"
            f"     → echelon spec continue\n"
            f"       (ARCHITECT commits stack, data-model, contracts)"
        )
    elif why2_passed:
        ready_items.append("HOW artifacts ✓")

    # 4. tasks.md — only surface when quality gates have passed
    tasks_present = False
    if why2_passed and active_spec_dir is not None and (active_spec_dir / "tasks.md").exists():
        tasks_present = True
        ready_items.append("tasks.md ✓")

    if why2_passed and not tasks_present:
        blockers.append(
            "tasks.md absent — ORCHESTRATOR (phase3-plan) has not run\n"
            "     → echelon spec continue"
        )

    readiness_state = dict(run_state or current_state)
    readiness_state["status"] = result_status
    if run_state.get("blocked_reason"):
        readiness_state["blocked_reason"] = run_state.get("blocked_reason")
    readiness = validate_phase_a_readiness(
        readiness_state,
        _phase_a_readiness_candidate_dirs(
            project_root,
            readiness_state,
            run_dir,
            active_spec_dir=active_spec_dir,
            published_spec_dir=published_spec_dir,
        ),
    )
    for blocker in readiness.blockers:
        if blocker not in blockers:
            blockers.append(blocker)

    # 5. Blocked run — surface escalation context and improvement recommendations
    if result_status == "blocked":
        blocked_reason = run_state.get("blocked_reason") or ""
        escalation_q = run_state.get("escalation_question") or ""

        # Extract improvement recommendations from quality-gates.md
        improvement_lines: list[str] = []
        if quality_gates_file:
            try:
                qg_for_tips = quality_gates_file.read_text(errors="replace")
                in_section = False
                for line in qg_for_tips.splitlines():
                    if _re.match(r"^##\s+(Metric Improvement|Action Required)", line):
                        in_section = True
                        continue
                    if in_section:
                        if line.startswith("## ") or line.startswith("# "):
                            break
                        stripped = line.strip()
                        if stripped and not stripped.startswith("<!--"):
                            improvement_lines.append(stripped)
                            if len(improvement_lines) >= 8:
                                break
            except Exception:
                pass

        if blocked_reason == "consecutive_why_fails":
            msg_lines = ["Run blocked: 2+ consecutive WHY FAILs — spec is not improving"]
            if improvement_lines:
                msg_lines.append("  Recommended fixes (from quality-gates.md):")
                for il in improvement_lines[:6]:
                    msg_lines.append(f"    {il}")
            msg_lines.append(
                "  → echelon spec resume \"<tell CARTOGRAPHER what to fix>\"\n"
                "    e.g. \"Fix structure: split compound FRs, add numeric thresholds\""
            )
            warnings.append("\n".join(msg_lines))
        elif escalation_q:
            warnings.append(
                f"Run blocked: {escalation_q}\n"
                "     → echelon spec resume \"<your answer>\""
            )
        else:
            warnings.append(
                "Run blocked\n"
                "     → echelon spec resume \"<your answer>\""
            )

    # ── Print ──────────────────────────────────────────────────────────────
    # Single readiness predicate: a blocked/interrupted run is never "READY TO
    # BUILD", even when no explicit blocker was collected.
    fields: list[tuple[str, str]] = []
    if _phase_a_buildable(result_status, blockers):
        if ready_items:
            fields.append(("ready", "\n".join(f"✓ {item}" for item in ready_items)))
        harness_cmd = f"echelon delivery run {newest_spec_id}" if newest_spec_id else "echelon delivery run <spec-id>"
        fields.append(("next", harness_cmd))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
        subtitle = "READY TO BUILD"
    else:
        if blockers:
            fields.append(("blockers", "\n".join(f"{i}. {b}" for i, b in enumerate(blockers, 1))))
        if warnings:
            fields.append(("warnings", "\n".join(f"⚠ {w}" for w in warnings)))
        if ready_items:
            fields.append(("already done", ", ".join(ready_items)))
        if result_status == "blocked":
            subtitle = "RUN BLOCKED — resolve before building"
        elif blockers:
            subtitle = "PHASE A INCOMPLETE — continue authoring before build"
        else:
            subtitle = "RUN BLOCKED — resolve the block before building"

    _banner("NEXT STEP", fields, subtitle=subtitle)


def _coverage_map_planning_defect_for_spec(project_root: Path, spec_id: str) -> bool:
    """Whether the latest exact-spec delivery blocked on a stale coverage map."""
    harness_state = _find_latest_harness_build_state(project_root)
    if (
        harness_state is None
        or str(harness_state.get("spec_id") or "") != spec_id
        or str(harness_state.get("termination_reason") or "") != "build_blocked"
    ):
        return False
    verification = harness_state.get("last_verify_result")
    raw_failures = verification.get("failures", []) if isinstance(verification, dict) else []
    if not isinstance(raw_failures, list):
        return False
    return any(
        isinstance(failure, dict)
        and "coverage-observer-map-incomplete"
        in f"{failure.get('id') or ''} {failure.get('error') or ''}".lower()
        for failure in raw_failures
    )


def _run_artifact_dir(project_root: Path, run_dir: Path) -> Path:
    """Return the canonical artifact root for a run, with pre-WHAT fallback."""
    state_path = run_dir / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            spec_ref = str(state.get("spec_dir") or "").strip()
            if spec_ref:
                spec_dir = Path(spec_ref)
                if not spec_dir.is_absolute():
                    spec_dir = project_root / spec_dir
                if spec_dir.is_dir():
                    return spec_dir
        except (OSError, ValueError, TypeError):
            pass
    return run_dir / "staging"


def _print_staging_artifacts(
    project_root: Path,
    exclude_dir: Optional[Path] = None,
    run_status: str = "",
) -> None:
    """Print a compact manifest of artifacts from the most recent prior run.

    Skips squad-internal files (issues.md, assumption-review.md, *-endorsement.md)
    so the list reflects substantive domain artifacts the squad can build on.
    Once WHAT establishes ``state.spec_dir``, that directory is authoritative;
    staging is only the pre-WHAT fallback. Silent when no prior run has content, or when the run is done (the
    NEXT STEP section already surfaces readiness in that case).
    """
    if run_status == "done":
        return

    candidates = [
        (d, _run_artifact_dir(project_root, d))
        for d in _iter_run_dirs(project_root)
        if d != exclude_dir
    ]
    candidates = [(run_dir, artifact_dir) for run_dir, artifact_dir in candidates if artifact_dir.exists()]
    if not candidates:
        return

    run_dir, artifact_dir = candidates[0]

    _SKIP_NAMES = {"issues.md", "assumption-review.md", "escalation-request.md",
                   "user-clarifications.md"}
    _SKIP_SUFFIXES = ("-halt-endorsement.md", "-endorsement.md")

    names = sorted(
        f.stem for f in artifact_dir.glob("*.md")
        if f.name not in _SKIP_NAMES
        and not any(f.name.endswith(s) for s in _SKIP_SUFFIXES)
    )
    if not names:
        return

    # Two-column layout; strip .md already done via .stem
    col_w = 28
    pairs = [names[i:i + 2] for i in range(0, len(names), 2)]
    files_list = "\n".join("  ".join(n.ljust(col_w) for n in pair).rstrip() for pair in pairs)
    _banner(
        "PRIOR RUN ARTIFACTS",
        [("artifacts", files_list)],
        subtitle=f"{len(names)} files · {run_dir.name}",
    )


def _print_cost_summary(project_root: Path) -> None:
    """Print cumulative cost across all runs if cost data has been recorded.

    Reads cost_usd from each run's state.json. Silent when no run has cost data
    (i.e. all values are 0 — means tracking hasn't started yet or non-claude CLI).
    """
    import json as _json

    runs: list[tuple[str, float]] = []
    for run_dir in _iter_run_dirs(project_root):
        sf = run_dir / "state.json"
        if not sf.exists():
            continue
        try:
            state = _json.loads(sf.read_text())
            cost = float(state.get("cost_usd") or 0)
            if cost > 0:
                runs.append((run_dir.name, cost))
        except Exception:
            pass

    if not runs:
        return

    total = sum(c for _, c in runs)
    fields: list[tuple[str, str]] = [(name, f"${cost:.4f}") for name, cost in runs[-5:]]
    if len(runs) > 5:
        omitted = len(runs) - 5
        earlier = sum(c for _, c in runs[:-5])
        fields.append((f"… {omitted} earlier", f"${earlier:.4f}"))
    fields.append(("total", f"${total:.4f}"))
    _banner("COST", fields, subtitle=f"{len(runs)} runs tracked")


def _print_prior_knowledge(project_root: Path) -> None:
    """Print a brief summary of accumulated knowledge-base content at run start.

    Covers sage-decisions.yaml (calibration history + last resolution) and any
    other KB files present (patterns, pitfalls, calibration-profile, agent-scores).
    Silent when knowledge-base/ is absent or empty.
    """
    kb_dir = project_root / "knowledge-base"
    if not kb_dir.exists():
        return

    lines: list[str] = []

    # ── sage-decisions.yaml ─────────────────────────────────────────────────
    sage_path = kb_dir / "sage-decisions.yaml"
    if sage_path.exists():
        try:
            import yaml as _yaml
            data = _yaml.safe_load(sage_path.read_text(errors="replace")) or {}
            entries = data.get("entries", [])
            if entries:
                total = len(entries)
                overturned = sum(1 for e in entries if e.get("was_correct") is False)
                calibration = "well-calibrated" if overturned == 0 else f"{overturned} overturned"
                blocked_streak = sum(
                    1 for e in reversed(entries) if e.get("outcome") == "blocked"
                )
                # First substantive sentence of last resolution, capped at 110 chars
                last_res = (entries[-1].get("resolution") or "").replace("\n", " ").strip()
                dot = last_res.find(". ")
                # Skip trivial lead-ins like "Pending." or "Same as prior."
                if 0 < dot < 20:
                    tail = last_res[dot + 2:]
                    dot2 = tail.find(". ")
                    last_res = tail
                    dot = dot2
                snippet = last_res[:dot + 1] if 0 < dot < 110 else last_res[:110]
                if len(last_res) > len(snippet):
                    snippet = snippet.rstrip(".") + "…"

                lines.append(
                    f"SAGE decisions: {total} · {overturned} overturned ({calibration})"
                )
                if blocked_streak >= 2:
                    lines.append(
                        f"Blocker pattern: {blocked_streak} consecutive FAILs"
                        f" on same root cause — human input required"
                    )
                if snippet:
                    lines.append(f"Last resolution: {snippet}")
        except Exception:
            import re as _re
            size_kb = sage_path.stat().st_size // 1024
            try:
                raw = sage_path.read_text(errors="replace")
                # Entries are indented list items: "  - run_id: ..."
                entry_est = len(_re.findall(r"^\s+- run_id:", raw, _re.MULTILINE))
            except Exception:
                entry_est = 0
            note = f"~{entry_est} entries · {size_kb}KB" if entry_est else f"{size_kb}KB"
            lines.append(f"SAGE decisions: {note} (could not parse YAML)")

    # ── other KB files ──────────────────────────────────────────────────────
    _KB_FILES = [
        ("calibration-profile.yaml", "Calibration profile"),
        ("agent-scores.yaml",        "Agent scores"),
        ("patterns.yaml",            "Patterns"),
        ("pitfalls.yaml",            "Pitfalls"),
        ("estimates-log.yaml",       "Estimates log"),
    ]
    for fname, label in _KB_FILES:
        fpath = kb_dir / fname
        if not fpath.exists():
            continue
        try:
            import yaml as _yaml
            data = _yaml.safe_load(fpath.read_text(errors="replace")) or {}
            entries = data.get("entries", data if isinstance(data, list) else [])
            count = len(entries) if isinstance(entries, (list, dict)) else "?"
            lines.append(f"{label}: {count} entries")
        except Exception:
            lines.append(f"{label}: present")

    if not lines:
        return

    _banner(
        "PRIOR KNOWLEDGE",
        [("summary", "\n".join(lines))],
        subtitle=str(kb_dir.relative_to(project_root)),
    )


def _print_open_issues(project_root: Path, exclude_dir: Optional[Path] = None) -> None:
    """Print a formatted summary of open issues from the most recent prior run.

    Reads issues.md from the latest run's canonical artifact root (excluding the
    current run). Before WHAT establishes ``state.spec_dir``, staging is used.
    Shows CRITICAL issue titles and user-gated HIGH issues. Silent when nothing
    to show — no output if no issues.md exists or all issues are LOW/MEDIUM.
    """
    import re as _re

    # Find most recent run dir with issues.md, skipping the current run.
    candidates = [
        (d, _run_artifact_dir(project_root, d) / "issues.md")
        for d in _iter_run_dirs(project_root)
        if d != exclude_dir
    ]
    candidates = [(run_dir, issues_path) for run_dir, issues_path in candidates if issues_path.exists()]
    if not candidates:
        return

    run_dir, issues_path = candidates[0]
    issues_md = issues_path.read_text(errors="replace")

    # Extract severity counts from the Summary block
    counts: dict[str, int] = {}
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        m = _re.search(rf"\*\*{sev}:\*\*\s*(\d+)", issues_md)
        if m:
            counts[sev] = int(m.group(1))

    if not counts.get("CRITICAL", 0) and not counts.get("HIGH", 0):
        return

    # Extract issue entries: title, severity, responsible agent
    issue_blocks = _re.findall(
        r"### (ISS-\d+:[^\n]+)\n(.*?)(?=\n### |\Z)",
        issues_md,
        _re.DOTALL,
    )

    criticals: list[str] = []
    user_gated: list[str] = []

    for title, body in issue_blocks:
        sev_match = _re.search(r"\*\*Severity:\*\*\s*(\w+)", body)
        sev = sev_match.group(1).upper() if sev_match else ""
        is_user = bool(_re.search(r"(?i)responsible agent[^:]*:.*\buser\b", body))

        if sev == "CRITICAL":
            # Strip "ISS-NNN: " prefix for display, keep it compact
            short = _re.sub(r"^ISS-\d+:\s*", "", title).strip()
            criticals.append(short)
        elif sev == "HIGH" and is_user:
            short = _re.sub(r"^ISS-\d+:\s*", "", title).strip()
            user_gated.append(short)

    # Build banner fields
    run_label = run_dir.name
    fields: list[tuple[str, str]] = []

    if criticals:
        tree = "\n".join(
            f"{'└' if i == len(criticals) - 1 else '├'} {t}"
            for i, t in enumerate(criticals)
        )
        fields.append((f"CRITICAL ({counts.get('CRITICAL', len(criticals))})", tree))

    if user_gated:
        tree = "\n".join(
            f"{'└' if i == len(user_gated) - 1 else '├'} {t}"
            for i, t in enumerate(user_gated)
        )
        fields.append((f"HIGH — needs your input ({len(user_gated)})", tree))

    other_high = counts.get("HIGH", 0) - len(user_gated)
    if other_high > 0:
        fields.append(("HIGH — squad-solvable", str(other_high)))

    fields.append(("details", str(issues_path)))
    if user_gated:
        fields.append(("answer", "echelon spec resume \"<your answers>\""))

    _banner("OPEN ISSUES", fields, subtitle=f"from {run_label}")


def _select_squad_dir(
    project_root: Path,
    user_message: str,
    reset: bool = False,
    *,
    manual_recovery: bool = False,
    configured_default_branch: str = "",
    dirty_action: str = "refuse",
    confirm_discard: bool = False,
) -> tuple[Path, bool]:
    """Return (squad_dir, is_fresh_start).

    is_fresh_start=True  → caller should initialize state (new run).
    is_fresh_start=False → caller should resume (existing run dir, same task).
    """
    import json as _json
    from harness.paths import make_spec_run_id

    def start_fresh() -> tuple[Path, bool]:
        from echelon.phase_a_start import PhaseAStartError, start_phase_a_spec

        run_id = make_spec_run_id()
        runs_gitignore = project_root / "runs" / ".gitignore"
        runs_gitignore.parent.mkdir(exist_ok=True)
        _ensure_runs_gitignore(runs_gitignore)
        try:
            outcome = start_phase_a_spec(
                project_root,
                run_id,
                user_message,
                configured_default_branch=configured_default_branch,
                dirty_action=dirty_action,
                confirm_discard=confirm_discard,
            )
        except PhaseAStartError as exc:
            print(f"✗ echelon spec run: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return outcome.run_dir, True

    def choose_active_run() -> bool:
        """Return whether an interactive user chose to continue the active run."""
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return False

        active_message = str(state.get("user_message") or "").strip()
        branch = str(state.get("feature_branch") or "current branch").strip()
        answer = input(
            f"Active spec {existing_dir.name} on {branch}.\n"
            f"  Current task: {active_message or '(not recorded)'}\n"
            "Continue current spec/branch or start a new spec? [c/N] "
        ).strip().lower()
        return answer in {"c", "continue"}

    if reset:
        return start_fresh()

    existing_dir = _find_current_run_dir(project_root)
    if not existing_dir:
        return start_fresh()

    try:
        state = _json.loads((existing_dir / "state.json").read_text())
    except Exception:
        return start_fresh()

    if state.get("status") == "preparing" and user_message == state.get("user_message"):
        return existing_dir, True

    status = state.get("status")
    recovery = state.get("issue_resolution_recovery")
    manual_recovery = manual_recovery or (
        isinstance(recovery, dict)
        and recovery.get("status") not in {"consumed", "validated"}
    )
    if manual_recovery and status == "blocked":
        return existing_dir, False
    if status not in ("running", "in_progress"):
        return start_fresh()

    # Different task → new run dir (preserves old one, doesn't overwrite)
    if user_message and user_message != state.get("user_message", ""):
        if choose_active_run():
            print(
                f"[squad] continuing {existing_dir.name}; keeping its current task",
                flush=True,
            )
            return existing_dir, False
        return start_fresh()

    # Same task, resumable status → resume in existing dir
    return existing_dir, False


def _runtime_bundle_missing_paths(project_root: Path) -> list[str]:
    """Return the deployed runtime contracts absent from a workspace."""
    required = (
        (
            project_root / ".echelon" / "runtime" / "workflow" / "definition.yaml",
            ".echelon/runtime/workflow/definition.yaml",
        ),
        (project_root / ".echelon" / "prosaic" / "commands", ".echelon/prosaic/commands"),
        (project_root / ".echelon" / "prosaic" / "subagents", ".echelon/prosaic/subagents"),
    )
    return [display_path for path, display_path in required if not path.exists()]


def _print_runtime_bundle_status(project_root: Path) -> None:
    """Show whether the workspace has the deployed Echelon runtime contracts."""
    missing = _runtime_bundle_missing_paths(project_root)
    fields = [
        ("prose", ".echelon/prosaic"),
        ("runtime", ".echelon/runtime"),
        (
            "status",
            "ready"
            if not missing
            else "incomplete; run echelon workspace migrate-to-prosaic",
        ),
    ]
    if missing:
        fields.append(("missing", ", ".join(missing)))
    _banner(
        "ECHELON RUNTIME",
        fields,
    )


@dataclass(frozen=True)
class ProjectConfigCompatibilityIssue:
    title: str
    path: str
    current: str
    expected: str
    config_file: Path


def _project_config_compatibility_issues(
    project_root: Path,
) -> list[ProjectConfigCompatibilityIssue]:
    """Detect project config values incompatible with current deterministic flows."""
    cfg_file = _project_echelon_config(project_root)
    if not cfg_file.exists():
        return []

    try:
        import yaml
        raw = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []

    lexicon_gate = raw.get("lexicon_gate") or {}
    if not isinstance(lexicon_gate, dict) or not lexicon_gate.get("enabled", False):
        return []
    artifacts = lexicon_gate.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        return []
    spec_artifact = artifacts.get("spec") or {}
    tasks_artifact = artifacts.get("tasks") or {}
    if not isinstance(spec_artifact, dict) or not isinstance(tasks_artifact, dict):
        return []
    if not tasks_artifact.get("enabled", False):
        return []

    expected = str(spec_artifact.get("path") or "requirements.lexicon.md").strip()
    current = str(tasks_artifact.get("spec_ref") or expected).strip()
    if current == expected:
        return []
    return [
        ProjectConfigCompatibilityIssue(
            title="Stale Lexicon tasks spec_ref",
            path=LEXICON_TASK_SPEC_REF_PATH,
            current=current,
            expected=expected,
            config_file=cfg_file,
        )
    ]


def _print_project_config_compatibility_warning(project_root: Path) -> None:
    issues = _project_config_compatibility_issues(project_root)
    if not issues:
        return

    fields: list[tuple[str, str]] = []
    for issue in issues:
        fields.extend(
            [
                ("problem", issue.title),
                ("config", _repo_relative_or_absolute(issue.config_file, project_root)),
                ("key", issue.path),
                ("current", issue.current or "(empty)"),
                ("expected", issue.expected),
                ("fix", f"set {issue.path}: {issue.expected}"),
            ]
        )
    _banner(
        "CONFIG COMPATIBILITY",
        fields,
        subtitle="Project config is stale for the current Echelon workflow",
    )


def _enforce_project_config_compatibility(project_root: Path) -> None:
    issues = _project_config_compatibility_issues(project_root)
    if not issues:
        return

    issue = issues[0]
    _banner(
        "CONFIG BLOCKED",
        [
            ("problem", issue.title),
            ("config", _repo_relative_or_absolute(issue.config_file, project_root)),
            ("key", issue.path),
            ("current", issue.current or "(empty)"),
            ("expected", issue.expected),
            ("why", "Tasks Lexicon validation must read the derived requirements artifact."),
            ("fix", f"edit config and set {issue.path}: {issue.expected}"),
            ("then", "echelon spec run \"<task>\" or echelon spec continue"),
        ],
        subtitle="Refusing to dispatch agents with stale Lexicon task config",
        file=sys.stderr,
    )
    sys.exit(1)


_AUTONOMY_MODES = {"semi", "banzai", "guided"}


def _consume_mode_arg(
    args: list[str],
    index: int,
    *,
    command_name: str,
) -> tuple[str | None, int]:
    token = args[index]
    if token == "--mode":
        if index + 1 >= len(args):
            print(
                f"✗ {command_name}: --mode requires one of: semi, banzai, guided",
                file=sys.stderr,
            )
            sys.exit(1)
        mode = args[index + 1]
        next_index = index + 2
    elif token.startswith("--mode="):
        mode = token.split("=", 1)[1]
        next_index = index + 1
    else:
        return None, index

    if mode not in _AUTONOMY_MODES:
        print(
            f"✗ {command_name}: invalid mode {mode!r}; expected semi, banzai, or guided",
            file=sys.stderr,
        )
        sys.exit(1)
    return mode, next_index


def _resolve_spec_run_implementation_targets(
    project_root: Path,
    requested_targets: list[str],
    *,
    allow_missing: bool,
) -> list[str]:
    """Resolve Phase A implementation targets before any agent dispatch."""
    from echelon.workspace_model import discover_workspace

    root = project_root.resolve()
    manifest = discover_workspace(root)
    if not requested_targets:
        if len(manifest.sources) > 1:
            print(
                "✗ echelon spec run: multiple source repositories were discovered.\n"
                "  Declare every implementation destination with repeatable "
                "--target <source-id-or-path> options.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if len(manifest.sources) == 1:
            return [manifest.sources[0].path]
        print(
            "✗ echelon spec run: no implementation target was resolved.\n"
            "  Declare a source root or pass --target <source-id-or-path>.\n"
            "  The orchestration workspace is not an implementation target.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    resolved: list[str] = []
    by_id = {source.id: source.path for source in manifest.sources}
    by_path = {source.path: source.path for source in manifest.sources}
    for raw_target in requested_targets:
        raw = raw_target.strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_absolute():
            try:
                normalized = path.resolve().relative_to(root).as_posix()
            except ValueError:
                normalized = path.resolve().as_posix()
        else:
            normalized = path.as_posix().rstrip("/") or "."
        target = by_id.get(raw) or by_path.get(normalized) or normalized
        target_path = Path(target).expanduser()
        if not target_path.is_absolute():
            target_path = root if target == "." else root / target
        if not allow_missing and not target_path.is_dir():
            print(
                f"✗ echelon spec run: implementation target not found: {raw}\n"
                f"  Use --init to create it, or choose a configured workspace source.",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if target not in resolved:
            resolved.append(target)
    if not resolved:
        print("✗ echelon spec run: --target requires a source id or path", file=sys.stderr)
        raise SystemExit(1)
    return resolved


def _fresh_stack_contract_or_exit(project_root: Path) -> dict[str, object]:
    """Freeze selected-stack guidance before a fresh controller run starts."""
    from harness.stack_contract import StackContractError, build_stack_contract

    try:
        definitions = _load_stack_definitions_for_project(project_root)
        selection = get_stack_selection(project_root, definitions)
        return build_stack_contract(selection, definitions)
    except (StackError, StackContractError, StackSelectionError) as exc:
        print(f"✗ echelon spec run: selected stack contract is invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def _cmd_run(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Drive the pre-code squad run via deterministic Python harness."""
    from harness.config import load_config
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore
    from harness.phase_a_state_version import (
        UnsupportedPhaseAStateError,
        require_current_phase_a_state,
    )
    from echelon.spec_authoring import (
        SpecAuthoringModeError,
        resolve_spec_authoring_mode,
    )

    _enforce_project_config_compatibility(project_root)
    _workspace_git_preflight(project_root, command_name="echelon spec run")

    # Parse optional flags
    mode = "semi"
    reset = False
    perfectionist_requested = False
    next_phase = ""
    implementation_targets = [
        value.strip()
        for value in os.environ.get("ECHELON_IMPLEMENTATION_TARGETS", "").split(",")
        if value.strip()
    ]
    product_input_values: list[str] = []
    re_sources: list[str] = []
    init_target = False
    ignore_re = False
    dirty_action = "refuse"
    confirm_discard = False
    message_parts: list[str] = []
    i = 0
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon spec run")
        if parsed_mode is not None:
            mode = parsed_mode
            i = next_i
        elif args[i] == "--message" and i + 1 < len(args):
            message_parts.append(args[i + 1])
            i += 2
        elif args[i] == "--reset":
            reset = True
            i += 1
        elif args[i] == "--perfectionist":
            perfectionist_requested = True
            i += 1
        elif args[i] == "--init":
            init_target = True
            i += 1
        elif args[i] == "--next-phase" and i + 1 < len(args):
            next_phase = args[i + 1]
            i += 2
        elif args[i] == "--target":
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --target requires a source id or path",
                    file=sys.stderr,
                )
                sys.exit(1)
            implementation_targets.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--target="):
            implementation_targets.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--re-source":
            if i + 1 >= len(args):
                print(
                    "✗ echelon spec run: --re-source requires a published source id or re/sources path",
                    file=sys.stderr,
                )
                sys.exit(1)
            re_sources.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--re-source="):
            re_sources.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--input":
            if i + 1 >= len(args):
                print("✗ echelon spec run: --input requires role:path", file=sys.stderr)
                sys.exit(1)
            product_input_values.append(args[i + 1].strip())
            i += 2
        elif args[i].startswith("--input="):
            product_input_values.append(args[i].split("=", 1)[1].strip())
            i += 1
        elif args[i] == "--ignore-re":
            ignore_re = True
            i += 1
        elif args[i] == "--stash":
            if dirty_action != "refuse":
                print("✗ echelon spec run: choose only --stash or --discard", file=sys.stderr)
                raise SystemExit(2)
            dirty_action = "stash"
            i += 1
        elif args[i] == "--discard":
            if dirty_action != "refuse":
                print("✗ echelon spec run: choose only --stash or --discard", file=sys.stderr)
                raise SystemExit(2)
            dirty_action = "discard"
            i += 1
        elif args[i] == "--confirm":
            confirm_discard = True
            i += 1
        elif args[i] in {"--re-policy", "--re-max-inner"}:
            moved = args[i]
            print(
                f"✗ echelon spec run: {moved} moved to 'echelon re run'.\n"
                "  Run reverse engineering explicitly, then start the spec run.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif args[i].startswith("--re-policy=") or args[i].startswith("--re-max-inner="):
            moved = args[i].split("=", 1)[0]
            print(
                f"✗ echelon spec run: {moved} moved to 'echelon re run'.\n"
                "  Run reverse engineering explicitly, then start the spec run.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        elif args[i].startswith("--"):
            option = args[i].split("=", 1)[0]
            replacement = " use --target <source-id-or-path>." if option == "--source" else ""
            print(
                f"✗ echelon spec run: unknown option {option!r}.{replacement}",
                file=sys.stderr,
            )
            raise SystemExit(2)
        else:
            message_parts.append(args[i])
            i += 1
    message = " ".join(message_parts)
    if init_target and not implementation_targets:
        print(
            "✗ echelon spec run: --init requires --target <source id or path>",
            file=sys.stderr,
        )
        sys.exit(1)
    implementation_targets = _resolve_spec_run_implementation_targets(
        project_root,
        implementation_targets,
        allow_missing=init_target,
    )
    prev_dir = _find_current_run_dir(project_root)
    active_versioned_decision = False
    if prev_dir is not None:
        try:
            previous_state = json.loads(
                (prev_dir / "state.json").read_text(encoding="utf-8")
            )
            previous_decision = (
                previous_state.get("blocked_decision")
                if isinstance(previous_state, dict)
                else None
            )
            same_task = (
                isinstance(previous_state, dict)
                and message == previous_state.get("user_message", "")
            )
            candidate_is_active = (
                not reset
                and isinstance(previous_decision, dict)
                and previous_decision.get("schema_version") in {2, 3}
                and previous_decision.get("status") != "resolved"
                and same_task
            )
            if candidate_is_active:
                active_versioned_decision = (
                    _active_versioned_decision(previous_state) is not None
                )
        except (RecoveryInstructionError, ValueError, TypeError) as exc:
            print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        except OSError:
            pass
    _workspace_git_preflight_for_squad_run(
        project_root,
        command_name=_command_display("echelon spec run", args),
        user_message=message,
        reset=reset,
        manual_recovery=bool(next_phase) or active_versioned_decision,
    )

    config = load_config(project_root, squad_only=True)
    squad_dir, is_fresh = _select_squad_dir(
        project_root,
        message,
        reset=reset,
        manual_recovery=bool(next_phase) or active_versioned_decision,
        configured_default_branch=str(getattr(config, "target_default_branch", "") or ""),
        dirty_action=dirty_action,
        confirm_discard=confirm_discard,
    )
    if reset:
        print("[squad] state reset — starting fresh", flush=True)
    elif is_fresh and prev_dir is not None and prev_dir != squad_dir:
        print(
            f"[squad] new task — starting fresh in {squad_dir.name} "
            f"(previous run preserved at {prev_dir.name})",
            flush=True,
        )

    if init_target:
        from echelon.workspace_sources import ensure_source_config_entry
        added_sources: list[str] = []
        for implementation_target in implementation_targets:
            init_messages = _prepare_spec_target_repo(
                project_root,
                squad_dir,
                implementation_target,
            )
            source_added = ensure_source_config_entry(project_root, implementation_target)
            for init_message in init_messages:
                print(init_message)
            if source_added:
                added_sources.append(implementation_target)
        if added_sources:
            _commit_initialized_workspace_sources(
                project_root,
                run_id=squad_dir.name,
                retry_command=_command_display("echelon spec run", args),
            )
            for implementation_target in added_sources:
                print(f"Added workspace source: {implementation_target}")

    state_store = SquadStateStore(squad_dir)
    product_inputs = None
    existing_state = state_store.load()
    if not is_fresh:
        try:
            require_current_phase_a_state(existing_state)
        except UnsupportedPhaseAStateError as exc:
            print(f"✗ echelon spec run: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
    try:
        spec_authoring_mode = resolve_spec_authoring_mode(
            existing_state,
            is_fresh=is_fresh,
            perfectionist_requested=perfectionist_requested,
        )
    except SpecAuthoringModeError as exc:
        print(f"✗ echelon spec run: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    run_message = message
    if not is_fresh:
        existing_message = str(existing_state.get("user_message") or "").strip()
        if existing_message:
            run_message = existing_message
    _register_spec_summary_run(
        project_root,
        squad_dir,
        mode=mode,
        message=run_message,
        implementation_targets=implementation_targets,
    )
    existing_inputs = existing_state.get("product_inputs") if existing_state else None
    if existing_inputs and not reset:
        declared_before = existing_inputs.get("declarations") if isinstance(existing_inputs, dict) else None
        declared_now: list[dict[str, str]] = []
        if product_input_values:
            from echelon.product_inputs import ProductInputError, parse_input_declaration
            try:
                declared_now = [
                    {"role": value.role, "location": value.location}
                    for value in (parse_input_declaration(raw) for raw in product_input_values)
                ]
            except ProductInputError as exc:
                print(f"✗ echelon spec run: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
        if declared_now and declared_now != declared_before:
            print(
                "✗ echelon spec run: product inputs are immutable for an active run. "
                "Start a new run with --reset to change --input declarations.",
                file=sys.stderr,
            )
            raise SystemExit(1)
    elif product_input_values:
        from echelon.product_inputs import ProductInputError, parse_input_declaration, resolve_product_inputs
        try:
            product_inputs = resolve_product_inputs(
                project_root,
                squad_dir,
                [parse_input_declaration(raw) for raw in product_input_values],
            )
        except ProductInputError as exc:
            print(f"✗ echelon spec run: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    stack_contract: dict[str, object] | None = None
    if is_fresh:
        stack_contract = _fresh_stack_contract_or_exit(project_root)
    else:
        persisted_stack_contract = existing_state.get("stack_contract")
        if isinstance(persisted_stack_contract, dict):
            stack_contract = dict(persisted_stack_contract)
    provider = SquadCliProvider(config)
    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    # token_budget_k lives under analysis: in echelon-config.yml.
    # Use get_full_resolved_config so the 4-level cascade (ConfigManager →
    # echelon-config.yml → local-config.yml → env vars) is respected.
    from harness.config import get_full_resolved_config
    token_budget = 0
    max_iterations = 5  # matches analysis.max_iterations default in config-template.yml
    try:
        _full = get_full_resolved_config(project_root)
        _analysis = _full.get("analysis") or {}
        _k = int(_analysis.get("token_budget_k") or 0)
        token_budget = _k * 1000 if _k else 0
        max_iterations = int(_analysis.get("max_iterations") or 5)
    except Exception:
        pass

    controller = SquadController(
        provider=provider,
        state_store=state_store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=ignore_re,
        implementation_targets=implementation_targets,
        re_sources=re_sources,
        product_inputs=product_inputs,
        stack_contract=stack_contract,
    )

    _print_cost_summary(project_root)
    _print_prior_knowledge(project_root)
    _print_staging_artifacts(project_root, exclude_dir=squad_dir)
    _print_open_issues(project_root, exclude_dir=squad_dir)

    _state = state_store.load()
    run_id = (_state.get("run_id") if _state else None) or squad_dir.name
    _banner("SQUAD RUN", [
        ("Run ID", run_id),
        ("Mode", mode),
        ("Spec authoring", spec_authoring_mode),
        ("Task", (run_message[:80] + "…") if len(run_message) > 80 else run_message),
        ("Dir", str(squad_dir.name)),
        ("Implementation targets", ", ".join(implementation_targets)),
        ("Published RE sources", ", ".join(re_sources) if re_sources else "auto"),
        ("Published RE", "ignored" if ignore_re else "latest"),
    ])

    result = controller.run(user_message=run_message, mode=mode, next_phase_override=next_phase)

    _print_squad_summary(
        project_root,
        squad_dir,
        result,
        mode=mode,
        message=run_message,
        implementation_targets=implementation_targets,
        command=_SPEC_SUMMARY_COMMAND.get(),
    )
    if result.status != "done":
        sys.exit(1)


def _spec_id_from_ref(ref: str) -> str:
    value = (ref or "").strip()
    if not value:
        return ""
    parts = Path(value).parts
    if "specs" in parts:
        idx = parts.index("specs")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    name = Path(value).name
    return name if name and name != "specs" else ""


def _single_project_spec_dir(project_root: Path) -> Path | None:
    specs_root = project_root / "specs"
    if not specs_root.exists():
        return None
    specs = sorted(d for d in specs_root.iterdir() if d.is_dir())
    return specs[0] if len(specs) == 1 else None


def _ensure_active_continue_spec_context(
    project_root: Path,
    run_dir: Path,
    state: dict,
    *,
    sync_missing: bool,
) -> tuple[dict, Path | None]:
    """Resolve the active run-local spec dir for squad continue.

    Squad phases operate from the active run directory. The published
    project-root specs/<id> directory remains the build-harness target and is
    mirrored into the run-local copy only for missing files.
    """
    # ``specify_feature_directory`` is the original spec-kit allocation.  It
    # carries the full ``NNN-slug`` name and is therefore more specific than a
    # legacy ``spec_id: NNN`` / ``specs/NNN`` alias created by an interrupted
    # run.  Prefer it whenever it still resolves to a directory; otherwise a
    # resume can fork a shadow ``specs/NNN`` artifact tree and validate the
    # wrong copy.
    specified_ref = str(state.get("specify_feature_directory") or "").strip()
    specified_dir: Path | None = None
    if specified_ref:
        candidate = Path(specified_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.is_dir():
            specified_dir = candidate

    spec_id = specified_dir.name if specified_dir is not None else str(state.get("spec_id") or "").strip()
    spec_ref = str(state.get("spec_dir") or "").strip()
    published_ref = str(state.get("published_spec_dir") or "").strip()

    spec_id = spec_id or _spec_id_from_ref(spec_ref) or _spec_id_from_ref(published_ref)
    if not spec_id:
        only_spec = _single_project_spec_dir(project_root)
        if only_spec is None:
            return state, None
        spec_id = only_spec.name

    active_spec_dir = run_dir / "specs" / spec_id
    is_project_published_spec = False
    if specified_dir is not None:
        try:
            specified_dir.relative_to(project_root / "specs")
            is_project_published_spec = True
        except ValueError:
            pass
    published_spec_dir = (
        specified_dir
        if is_project_published_spec and specified_dir is not None
        else project_root / "specs" / spec_id
    )

    source_dirs: list[Path] = []
    if published_spec_dir.exists():
        source_dirs.append(published_spec_dir)
    if spec_ref:
        candidate = Path(spec_ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.exists() and candidate != active_spec_dir and candidate not in source_dirs:
            source_dirs.append(candidate)

    if sync_missing:
        active_spec_dir.mkdir(parents=True, exist_ok=True)
        for source in source_dirs:
            _copy_missing_tree(source, active_spec_dir)

    updated = dict(state)
    updated["spec_id"] = spec_id
    updated["spec_dir"] = _repo_relative_or_absolute(active_spec_dir, project_root)
    if published_spec_dir.exists() or published_ref:
        updated["published_spec_dir"] = _repo_relative_or_absolute(published_spec_dir, project_root)
    return updated, active_spec_dir


def _active_continue_spec_dir(project_root: Path, current_state: dict, run_dir: Path | None) -> Path | None:
    if run_dir is None:
        only_spec = _single_project_spec_dir(project_root)
        return only_spec
    _, active_spec_dir = _ensure_active_continue_spec_context(
        project_root,
        run_dir,
        current_state,
        sync_missing=False,
    )
    return active_spec_dir


def _published_continue_spec_dir(project_root: Path, current_state: dict) -> Path | None:
    """Return the project-root spec dir for completed/build-ready squad output."""
    spec_id = str(current_state.get("spec_id") or "").strip()
    spec_ref = str(current_state.get("spec_dir") or "").strip()
    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    spec_id = spec_id or _spec_id_from_ref(spec_ref) or _spec_id_from_ref(published_ref)

    candidates: list[Path] = []
    if spec_id:
        candidates.append(project_root / "specs" / spec_id)
    for ref in (published_ref, spec_ref):
        if not ref:
            continue
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _build_target_continue_spec_dir(project_root: Path, current_state: dict) -> Path | None:
    """Return the project-visible spec dir that harness/build commands resolve."""
    from harness.spec_frontmatter import find_spec_dir

    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    if published_ref:
        candidate = Path(published_ref)
        return candidate if candidate.is_absolute() else project_root / candidate

    spec_id = str(current_state.get("spec_id") or "").strip()
    if not spec_id:
        spec_ref = str(current_state.get("spec_dir") or "").strip()
        spec_id = _spec_id_from_ref(spec_ref) or ""
    if not spec_id:
        return _single_project_spec_dir(project_root)

    existing = find_spec_dir(spec_id, project_root)
    if existing is not None:
        return existing
    exact = project_root / "specs" / spec_id
    if exact.exists():
        return exact
    return None


def _resolve_phase_target_spec_dir(
    project_root: Path,
    current_state: dict,
    run_dir: Path,
    spec_arg: str = "",
) -> Path | None:
    """Resolve the run-local spec dir for a manual phase replay.

    Manual replays are repairs to the active Phase A worktree.  They must never
    dispatch an agent against the project-visible published spec directory.
    """
    from harness.spec_frontmatter import find_spec_dir

    selected: Path | None = None
    value = spec_arg.strip()
    if value:
        candidate = Path(value)
        if candidate.exists() and candidate.is_dir():
            selected = candidate if candidate.is_absolute() else project_root / candidate
        else:
            selected = find_spec_dir(value, project_root)
    else:
        selected = _build_target_continue_spec_dir(project_root, current_state)
        if selected is None:
            selected = _single_project_spec_dir(project_root)

    spec_id = str(current_state.get("spec_id") or "").strip()
    if selected is not None:
        spec_id = selected.name
    if not spec_id:
        return None
    return run_dir / "specs" / spec_id


@dataclass(frozen=True)
class _FailedAutomaticPhaseReplay:
    decision: Mapping[str, object]
    state_revision: int
    v2_automatic_eligible: bool
    spec_id: str
    spec_dir_ref: str
    spec_dir: Path


def _phase_a_readiness_candidate_dirs(
    project_root: Path,
    current_state: dict,
    run_dir: Path | None,
    active_spec_dir: Path | None = None,
    published_spec_dir: Path | None = None,
) -> list[Path]:
    """Return deterministic spec-dir candidates for Phase A build inputs."""
    candidates: list[Path] = []

    def add(candidate: Path | None) -> None:
        if candidate is None:
            return
        path = candidate if candidate.is_absolute() else project_root / candidate
        if path not in candidates:
            candidates.append(path)

    add(active_spec_dir)
    add(published_spec_dir)

    # A complete spec-kit name is authoritative.  A legacy ``spec_id: 004``
    # must not cause a second ``specs/004`` artifact tree to be inspected once
    # state already identifies ``004-feature-name``.
    canonical_spec_id = ""
    for key in ("specify_feature_directory", "spec_dir", "published_spec_dir"):
        candidate_id = _spec_id_from_ref(str(current_state.get(key) or ""))
        if re.fullmatch(r"\d{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*", candidate_id):
            canonical_spec_id = candidate_id
            break

    spec_id = canonical_spec_id or str(current_state.get("spec_id") or "").strip()
    if spec_id:
        add(project_root / "specs" / spec_id)
        if run_dir is not None:
            add(run_dir / "specs" / spec_id)

    for key in ("published_spec_dir", "spec_dir"):
        ref = str(current_state.get(key) or "").strip()
        if not ref:
            continue
        add(Path(ref))

    specified_ref = str(current_state.get("specify_feature_directory") or "").strip()
    if specified_ref:
        add(Path(specified_ref))

    staging_ref = str(current_state.get("staging_dir") or "").strip()
    if staging_ref:
        add(Path(staging_ref))
    elif run_dir is not None:
        add(run_dir / "staging")

    return candidates


def _next_continue_phase(project_root: Path) -> Optional[str]:
    """Return the phase ID to continue from, or None when build is ready.

    Runs the same blockers analysis as _print_next_steps and maps each blocker
    to the entry phase that resolves it. Returns the first (highest-priority)
    actionable phase, or None if everything is clear.
    """
    import json as _json
    import re as _re

    run_dir = _find_current_run_dir(project_root)
    current_state: dict = {}
    if run_dir and (run_dir / "state.json").exists():
        try:
            current_state = _json.loads((run_dir / "state.json").read_text())
            recommended = current_state.get("phase_recommendation")
            if (
                recommended
                and (
                    current_state.get("convergence_forced")
                    or current_state.get("convergence_detected")
                )
            ):
                completed = current_state.get("completed_phases")
                next_solution_phase = _next_incomplete_solution_phase(
                    completed if isinstance(completed, list) else []
                )
                if next_solution_phase is not None:
                    return next_solution_phase
                if _phase_a_ready_to_build(project_root, current_state):
                    return None
                if current_state.get("status") == "done":
                    return _done_phase_a_repair_phase(project_root, current_state)
                return recommended
        except Exception:
            current_state = {}
    active_spec_dir = _active_continue_spec_dir(project_root, current_state, run_dir)
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    next_solution_phase = _next_incomplete_solution_phase(completed_phases)
    if next_solution_phase is not None:
        return next_solution_phase

    if current_state.get("status") == "done" and _phase_a_ready_to_build(project_root, current_state):
        if _explicit_run_local_spec_needs_publication(
            project_root,
            current_state,
            active_spec_dir,
            _published_continue_spec_dir(project_root, current_state),
        ):
            return "phase4-document"
        return None

    action = _classify_run_recovery(current_state, project_root=project_root)
    if action.kind == "retry_phase":
        return action.phase
    if action.kind in {"human_resume", "safe_rewind"}:
        return None
    if action.kind == "manual_recovery" and current_state.get("status") == "interrupted":
        return None

    # 0. Constitution phase provenance first, artifact integrity second.
    if "phase1-constitution" not in completed_phases:
        return "phase1-constitution"
    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if not const_path.exists():
        return "phase1-constitution"
    const_text = const_path.read_text(errors="replace")
    if _constitution_template_markers(const_text):
        return "phase1-constitution"

    # 1. WHY2 failures — fix spec first, so CARTOGRAPHER runs before HOW
    quality_gates_file: Optional[Path] = None
    if active_spec_dir is not None:
        qg = active_spec_dir / "quality-gates.md"
        if qg.exists():
            quality_gates_file = qg

    # Also check staging/ for mid-run blocked states (same as _print_next_steps)
    if quality_gates_file is None:
        if run_dir:
            try:
                state = _json.loads((run_dir / "state.json").read_text())
                staging_dir = Path(state.get("staging_dir") or str(run_dir / "staging"))
                staging_qg = staging_dir / "quality-gates.md"
                if staging_qg.exists():
                    quality_gates_file = staging_qg
            except Exception:
                pass

    if quality_gates_file:
        qg_text = quality_gates_file.read_text(errors="replace")
        verdict_m = _re.search(r"^##\s+Verdict:\s+(FAIL|BLOCKED)", qg_text, _re.MULTILINE)
        if verdict_m:
            return "phase1-what"  # top-level FAIL or BLOCKED → CARTOGRAPHER amendment
        gate_pattern = _re.compile(
            r"\|\s*(Overall|Structure|Testability|Semantic|Cognitive|"
            r"Readability|Behavioral|Depth)\s*\|[^|]+\|[^|]+\|\s*\*{0,2}FAIL\*{0,2}\s*\|([^|]*)\|"
        )
        for m in gate_pattern.finditer(qg_text):
            note = m.group(2).lower()
            if "borderline" not in note or "not borderline" in note:
                return "phase1-what"  # hard gate fail → CARTOGRAPHER amendment

    if _needs_phase3_specialists_recovery(active_spec_dir, completed_phases):
        return "phase3-specialists"

    # 2. HOW artifacts missing
    if active_spec_dir is not None:
        if not all((active_spec_dir / f).exists() for f in ("plan.md", "research.md", "data-model.md")):
            return "phase3-how"

    # 3. tasks.md missing
    if active_spec_dir is not None and not (active_spec_dir / "tasks.md").exists():
        return "phase3-plan"

    # WS1 invariant: a run with no resolvable spec directory has not produced the
    # build inputs (spec.md/tasks.md), so it is not ready. Route back to authoring
    # instead of falling through to a false "Build is ready — nothing left to do".
    if active_spec_dir is None:
        return "phase1-what"

    if current_state.get("status") == "done" and not _phase_a_ready_to_build(project_root, current_state):
        return _done_phase_a_repair_phase(project_root, current_state)

    readiness = validate_phase_a_readiness(
        current_state,
        _phase_a_readiness_candidate_dirs(
            project_root,
            current_state,
            run_dir,
            active_spec_dir=active_spec_dir,
            published_spec_dir=_published_continue_spec_dir(project_root, current_state),
        ),
    )
    if not readiness.ready:
        if any(
            blocker.startswith("coverage-map.md invalid:")
            for blocker in readiness.blockers
        ):
            return "phase3-sentinel"
        if "spec.md" in readiness.missing:
            return "phase1-what"
        if any(name in readiness.missing for name in ("plan.md", "research.md", "data-model.md")):
            return "phase3-how"
        if "tasks.md" in readiness.missing:
            return "phase3-plan"
        return "phase1-what"

    return None


def _done_phase_a_repair_phase(project_root: Path, state: dict) -> str:
    """Route a completed run to the owner of its invalid build artifact."""
    spec_dir = _build_target_continue_spec_dir(project_root, state)
    if spec_dir is not None:
        readiness = validate_phase_a_readiness({"status": "done"}, [spec_dir])
        if any(
            blocker.startswith("coverage-map.md invalid:")
            for blocker in readiness.blockers
        ):
            return "phase3-sentinel"
    return "phase4-document"


def _explicit_run_local_spec_needs_publication(
    project_root: Path,
    current_state: dict,
    active_spec_dir: Path | None,
    published_spec_dir: Path | None,
) -> bool:
    spec_ref = str(current_state.get("spec_dir") or "").strip()
    if not spec_ref or active_spec_dir is None or published_spec_dir is None:
        return False
    explicit_spec_dir = Path(spec_ref)
    if not explicit_spec_dir.is_absolute():
        explicit_spec_dir = project_root / explicit_spec_dir
    if not explicit_spec_dir.exists() or not published_spec_dir.exists():
        return False
    try:
        if explicit_spec_dir.resolve() == published_spec_dir.resolve():
            return False
    except OSError:
        return False
    try:
        explicit_spec_dir.relative_to(project_root / "runs")
    except ValueError:
        return False
    if not validate_phase_a_readiness(current_state, [explicit_spec_dir]).ready:
        return False
    return _spec_tree_differs(explicit_spec_dir, published_spec_dir)


def _spec_tree_differs(source: Path, destination: Path) -> bool:
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(source)
        except ValueError:
            continue
        target = destination / rel
        if not target.exists() or not target.is_file():
            return True
        try:
            if path.read_bytes() != target.read_bytes():
                return True
        except OSError:
            return True
    return False


def _needs_phase3_specialists_recovery(
    active_spec_dir: Path | None,
    completed_phases: list,
) -> bool:
    """Detect old bad state that skipped specialists after tracker alignment."""

    if active_spec_dir is None:
        return False
    if "phase2-tracker-alignment" not in completed_phases:
        return False
    if "phase3-specialists" in completed_phases:
        return False
    if not (active_spec_dir / "intent-alignment-check.md").exists():
        return False
    return (active_spec_dir / "spec.md").exists()


def _next_incomplete_solution_phase(completed_phases: list) -> str | None:
    """Return the next required solution phase after tracker alignment.

    Older interrupted runs can have stale plan/task artifacts from a previous
    attempt. Once tracker alignment has completed, phase history is a stronger
    signal than file existence: missing recorded solution phases mean those
    artifacts have not been freshly regenerated for this run.
    """

    if "phase2-tracker-alignment" not in completed_phases:
        return None
    for phase_id in (
        "phase3-specialists",
        "phase3-how",
        "phase3-sentinel",
        "phase3-plan",
        "phase3-consensus",
    ):
        if phase_id not in completed_phases:
            return phase_id
    return None


def _phase_a_ready_to_build(project_root: Path, current_state: dict) -> bool:
    """Return True when Phase A already produced enough artifacts for harness run."""
    completed = current_state.get("completed_phases")
    completed_phases = completed if isinstance(completed, list) else []
    if current_state and "phase1-constitution" not in completed_phases:
        return False

    from echelon.constitution import canonical_constitution_path

    const_path = canonical_constitution_path(project_root)
    if not const_path.exists():
        return False
    if _constitution_template_markers(const_path.read_text(errors="replace")):
        return False

    published_spec_dir = _build_target_continue_spec_dir(project_root, current_state)
    if published_spec_dir is None:
        return False
    return validate_phase_a_readiness(
        current_state,
        [published_spec_dir],
    ).ready


_FALLBACK_ROADMAP_PHASES = [
    "init", "phase1-discover", "phase1-synthesizer", "phase1-modeler",
    "phase1-tracker", "phase1-why1", "phase1-constitution", "phase1-what",
    "phase1-understanding", "phase1-why2", "phase1-lexicon-derive",
    "phase1-lexicon",
    "checkpoint-assess", "phase2-decide",
    "phase2-strategic-overview", "phase2-tracker-alignment",
    "phase3-specialists", "phase3-how", "phase3-sentinel", "phase3-plan",
    "phase3-tasks-lexicon", "phase3-understanding", "phase3-consensus",
    "phase3-consensus-tasks-lexicon", "checkpoint-plan", "phase4-document", "done",
]


def _derive_roadmap_phases(workflow_path: Path) -> list[str]:
    """Return the primary forward squad path from workflow/definition.yaml."""
    try:
        import yaml as _yaml

        raw = _yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return list(_FALLBACK_ROADMAP_PHASES)

    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list):
        return list(_FALLBACK_ROADMAP_PHASES)
    phases = {
        str(phase.get("id")): phase
        for phase in phases_raw
        if isinstance(phase, dict) and phase.get("id")
    }

    def longest_path_to_done(current: str, seen: frozenset[str]) -> list[str]:
        if current == "done":
            return ["done"]
        if current not in phases or current in seen:
            return []

        next_seen = seen | {current}
        candidates: list[list[str]] = []
        transitions = phases[current].get("transitions") or []
        if isinstance(transitions, list):
            for transition in transitions:
                if not isinstance(transition, dict):
                    continue
                candidate = str(transition.get("to") or "")
                if (
                    not candidate
                    or candidate == current
                    or candidate in {"escalate", "terminal-blocked"}
                    or candidate in next_seen
                ):
                    continue
                suffix = longest_path_to_done(candidate, next_seen)
                if suffix:
                    candidates.append([current, *suffix])
        return max(candidates, key=len, default=[])

    path = longest_path_to_done("init", frozenset())
    if not path or path[-1] != "done":
        return list(_FALLBACK_ROADMAP_PHASES)
    return path


_ROADMAP_PHASES = _derive_roadmap_phases(
    Path(__file__).resolve().parents[2] / "runtime/workflow/definition.yaml"
)


def _print_roadmap(state: dict, workflow_path: Path | None = None) -> None:
    """Render the pipeline as a checkbox roadmap from the run's state.json:
    [✓] completed · [▶] in progress · [ ] pending. A (×N) marks a re-dispatched
    phase — the early signal of a non-converging loop."""
    roadmap_phases = (
        _derive_roadmap_phases(workflow_path)
        if workflow_path is not None
        else list(_ROADMAP_PHASES)
    )
    completed = state.get("completed_phases")
    completed = completed if isinstance(completed, list) else []
    completed_set = {str(phase) for phase in completed}
    counts = state.get("phase_dispatch_counts")
    counts = counts if isinstance(counts, dict) else {}
    current = state.get("current_phase") or state.get("phase")
    ld = state.get("last_dispatch")
    if not current and isinstance(ld, dict):
        current = ld.get("phase_id") or ld.get("phase")

    # A finished run marks every phase complete, even if `completed_phases`
    # never recorded the terminal nodes (phase4-document / done).
    run_done = state.get("status") == "done"

    fields: list[tuple[str, str]] = []
    done_n = 0
    for ph in roadmap_phases:
        if run_done:
            box = "[✓]"
            done_n += 1
            suffix = ""
        elif ph == current:
            box = "[▶]"
            done_n += 1 if ph in completed_set else 0
            suffix = "  ← in progress"
        elif ph in completed_set:
            box = "[✓]"
            done_n += 1
            suffix = ""
        else:
            box = "[ ]"
            suffix = ""
        n = counts.get(ph, 0)
        rerun = f"  (×{n} — re-dispatched)" if isinstance(n, int) and n > 1 else ""
        fields.append((box, f"{ph}{rerun}{suffix}"))

    pct = int(100 * done_n / len(roadmap_phases)) if roadmap_phases else 0
    _banner("ROADMAP", fields, subtitle=f"{done_n}/{len(roadmap_phases)} phases complete ({pct}%)")


def _print_active_spec_status(project_root: Path) -> None:
    """Render the deterministic Phase A authoring selection, when one exists."""
    from echelon.spec_lifecycle import (
        SpecLifecycleError,
        SpecRunNotFound,
        discover_spec_runs,
        resolve_active_spec_run,
    )
    from echelon.spec_switch import SpecSwitchError, validate_spec_checkpoint

    try:
        active = resolve_active_spec_run(project_root)
    except SpecRunNotFound:
        return

    fields: list[tuple[str, str]] = [
        ("Run", active.run_dir_name),
        ("Spec", active.spec_id),
        ("Branch", active.feature_branch),
    ]
    try:
        checkpoint = validate_spec_checkpoint(project_root, active)
        fields.append(("Checkpoint", f"{checkpoint.checkpoint_id} ({checkpoint.phase})"))
    except SpecSwitchError as exc:
        if str(exc).startswith("no checkpoint for run "):
            fields.append(("Checkpoint", "not yet created"))
        else:
            fields.append(("Checkpoint", f"unavailable: {exc}"))
    except Exception as exc:
        # Status is diagnostic: invalid Git/checkpoint state must not suppress
        # the rest of the operator's orientation report.
        fields.append(("Checkpoint", f"unavailable: {exc}"))

    try:
        state = json.loads((active.run_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {}
    managed_stash = state.get("phase_a_stash") if isinstance(state, dict) else None
    if isinstance(managed_stash, dict):
        stash_commit = managed_stash.get("commit")
        if isinstance(stash_commit, str) and stash_commit.strip():
            fields.append(("Managed stash", stash_commit.strip()))
        else:
            fields.append(("Managed stash", "recorded but malformed"))

    try:
        others = [
            f"{run.spec_id} ({run.run_dir_name})"
            for run in discover_spec_runs(project_root)
            if run.run_dir != active.run_dir
        ]
    except SpecLifecycleError as exc:
        fields.append(("Switchable", f"unavailable: {exc}"))
    else:
        if others:
            fields.append(("Switchable", ", ".join(others)))

    _banner("ACTIVE SPEC", fields)


def _cmd_status(project_root: Path) -> None:
    """Print a concise orientation summary for the current project state.

    Shows: active run state (phase, status, task), staging artifacts,
    open issues, cost summary, prior knowledge, and what to do next.
    Designed to re-orient after a break without reading files manually.
    """
    import json as _json
    from datetime import datetime, timezone

    print(flush=True)
    _banner("ECHELON STATUS", [("Project", str(project_root))])
    _print_runtime_bundle_status(project_root)
    _print_project_config_compatibility_warning(project_root)
    _print_active_spec_status(project_root)

    # ── Run state ───────────────────────────────────────────────────────────
    run_dir = _find_current_run_dir(project_root)
    state: dict = {}
    if run_dir and (run_dir / "state.json").exists():
        try:
            state = _json.loads((run_dir / "state.json").read_text())
        except Exception:
            pass

    # Landing clears the authoring pointer. A historical fallback must not
    # revive its old blocked/running guidance over a published terminal spec.
    if (
        not (project_root / "runs" / ".current").is_file()
        and _canonical_delivery_lifecycle(project_root) is not None
    ):
        fields = [("Status", "No active run found")]
        if run_dir is not None:
            fields.append(("Prior run", str(run_dir)))
        _banner("RUN STATE", fields)
        _print_terminal_delivery_lifecycle(project_root)
        return

    if not run_dir or not state:
        _banner("RUN STATE", [
            ("Status", "No active run found"),
            ("Next",   'echelon spec run "<task description>"'),
        ])
    else:
        run_status = state.get("status", "unknown")
        _ld = state.get("current_phase") or state.get("phase") or state.get("last_dispatch")
        if isinstance(_ld, dict):
            _ld = _ld.get("phase_id") or _ld.get("phase") or str(_ld)
        current_phase = _ld or "—"
        task_msg = state.get("user_message", "")
        run_id = run_dir.name

        started_at = state.get("started_at", "")
        elapsed = ""
        if started_at:
            try:
                t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - t
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m = rem // 60
                elapsed = f"{h}h {m}m ago" if h else f"{m}m ago"
            except Exception:
                pass

        status_icon = {"done": "✓", "blocked": "⚠", "running": "▶",
                       "in_progress": "▶", "interrupted": "✗"}.get(run_status, "·")

        fields: list[tuple[str, str]] = [
            ("Run",    run_id),
            ("Status", f"{status_icon}  {run_status}"),
            ("Phase",  current_phase),
        ]
        spec_ref = str(state.get("spec_dir") or state.get("spec_id") or "").strip()
        if spec_ref:
            fields.insert(1, ("Spec", spec_ref))
        if task_msg:
            snippet = task_msg[:72] + ("…" if len(task_msg) > 72 else "")
            fields.append(("Task", snippet))
        if elapsed:
            fields.append(("Started", elapsed))
        debt_facts = _current_quality_debt_cli_facts(state, project_root)
        if debt_facts is not None:
            fields.append(("Specification quality", "accepted with quality debt"))
            failed_gates = debt_facts["failed_gates"]
            if failed_gates:
                fields.append(("Residual gates", ", ".join(failed_gates)))
            qualitative_issues = debt_facts["qualitative_issues"]
            if qualitative_issues:
                fields.append(
                    ("Residual SAGE", ", ".join(qualitative_issues))
                )
            if debt_facts["resolved_by"]:
                fields.append(("Debt resolver", str(debt_facts["resolved_by"])))
            if debt_facts["artifact"]:
                fields.append(("Debt evidence", str(debt_facts["artifact"])))
        provider_limit_message = str(
            state.get("provider_limit_message") or ""
        ).strip()
        if provider_limit_message:
            fields.append(("Provider limit", provider_limit_message))
        action = _RunRecoveryAction("advance")
        if run_status in ("running", "in_progress"):
            from echelon.spec_lifecycle import (
                active_phase_a_execution_owner,
                active_spec_run_execution_owner,
            )

            execution_owner = (
                active_spec_run_execution_owner(run_dir)
                or active_phase_a_execution_owner(project_root)
            )
            if execution_owner is not None:
                fields.append(("Execution", f"active ({execution_owner})"))
                fields.append(
                    (
                        "Next",
                        "Wait for the active run to finish; do not start a second continuation.",
                    )
                )
            else:
                fields.append(("Execution", "inactive (running state may be stale)"))
                fields.append(("Next", "echelon spec continue"))
        elif run_status == "blocked":
            action = _classify_run_recovery(state, project_root=project_root)
            if action.reason == "phase_dispatch_limit":
                guidance = _issue_resolution_guidance_recap(project_root, run_dir, state)
                if guidance:
                    fields.append(("Issue guidance", guidance))

        try:
            decision = _validated_versioned_decision(state)
        except (RecoveryInstructionError, ValueError):
            pass
        else:
            if decision is not None:
                fields.extend(_decision_audit_fields(decision))
                fields.extend(
                    _proportional_quality_decision_fields(state, decision)
                )

        _banner("RUN STATE", fields)

        # ── Pipeline roadmap ────────────────────────────────────────────────
        _print_roadmap(
            state,
            project_root / ".echelon" / "runtime" / "workflow" / "definition.yaml",
        )

    # ── Staging artifacts ───────────────────────────────────────────────────
    _print_staging_artifacts(project_root, run_status=state.get("status", ""))

    # ── Open issues ─────────────────────────────────────────────────────────
    _print_open_issues(project_root)

    # ── Prior knowledge ─────────────────────────────────────────────────────
    _print_prior_knowledge(project_root)

    # ── Cost summary ────────────────────────────────────────────────────────
    _print_cost_summary(project_root)

    # ── Build readiness (only meaningful when run is done/blocked) ──────────
    run_status = state.get("status", "")
    if run_status in ("done", "blocked", "interrupted") or not run_dir:
        _print_next_steps(project_root, run_status or "done")


def _format_squad_timestamp(timestamp: datetime) -> str:
    """Render a concise, local-time boundary timestamp for CLI transcripts."""
    return timestamp.astimezone().isoformat(timespec="seconds")


def _cmd_continue(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Run `spec continue` with explicit transcript timing boundaries."""
    started_at = datetime.now(timezone.utc)
    print(f"[squad] start: {_format_squad_timestamp(started_at)}", flush=True)
    try:
        _cmd_continue_impl(args, project_root=project_root, ext_dir=ext_dir)
    finally:
        ended_at = datetime.now(timezone.utc)
        print(f"[squad] end:   {_format_squad_timestamp(ended_at)}", flush=True)


def _cmd_continue_impl(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Resume or advance a squad run without requiring the user to know phase names.

    Behaviour by current run status:
    - running / in_progress: re-invokes echelon spec run with the same message (resumes)
    - blocked:               prints echelon spec resume guidance and exits
    - done / interrupted:    determines the next actionable phase from the build-
                             readiness analysis and starts a new run there, reusing
                             the original task message and mode from state.json
    - nothing found:         prints guidance to start a fresh echelon spec run
    """
    import json as _json

    # Optionally accept --mode override
    mode_override = ""
    i = 0
    while i < len(args):
        parsed_mode, next_i = _consume_mode_arg(args, i, command_name="echelon spec continue")
        if parsed_mode is not None:
            mode_override = parsed_mode
            i = next_i
        elif args[i] == "--re-max-inner" or args[i].startswith("--re-max-inner="):
            print(
                "✗ echelon spec continue: --re-max-inner moved to "
                "'echelon re continue'.",
                file=sys.stderr,
            )
            raise SystemExit(2)
        else:
            i += 1

    # ``continue`` is a mutating operation.  Unlike status/reporting paths it
    # must never infer an active run from historical directories: a workspace
    # can retain many completed specs and bounded verify-spec audits.
    current_pointer = project_root / "runs" / ".current"
    squad_dir = _find_current_run_dir(project_root) if current_pointer.is_file() else None
    if not squad_dir or not (squad_dir / "state.json").exists():
        _workspace_git_preflight(
            project_root,
            command_name=_command_display("echelon spec continue", args),
        )
        print(
            "No active spec run found in this project.\n"
            "Start a new run:  echelon spec run \"<task description>\"",
            flush=True,
        )
        return

    state = _json.loads((squad_dir / "state.json").read_text())
    if (
        _restore_interrupted_legacy_banzai_why2_reassessment(state)
        or _supersede_quality_guard_decision(state)
    ):
        (squad_dir / "state.json").write_text(
            _json.dumps(state, indent=2, ensure_ascii=False)
        )
    user_message = state.get("user_message", "")
    mode = mode_override or state.get("autonomy_mode") or state.get("mode", "semi")
    _register_spec_summary_run(
        project_root,
        squad_dir,
        mode=mode,
        message=user_message,
        implementation_targets=state.get("implementation_targets") or (),
    )
    try:
        decision = _active_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if decision is not None:
        # A sealed decision owns its autonomy policy.  A continue-time flag may
        # still apply to legacy runs, but cannot reclassify this decision.
        mode = str(decision["autonomy_mode"])
    status = state.get("status", "")
    cur_phase = state.get("phase", "")
    if not _workspace_git_present(project_root):
        if status in ("running", "in_progress"):
            _print_legacy_branchless_recovery_notice(
                _command_display("echelon spec continue", args)
            )
        else:
            _workspace_git_preflight(
                project_root,
                command_name=_command_display("echelon spec continue", args),
            )

    action = _classify_run_recovery(state, project_root=project_root)
    if (
        decision is not None
        and action.kind == "retry_phase"
        and _discard_retryable_failed_agent_block_decision(state)
    ):
        (squad_dir / "state.json").write_text(
            _json.dumps(state, indent=2, ensure_ascii=False)
        )
        decision = None
        print(
            "[squad] discarding obsolete generic-agent-block decision; retrying the phase.",
            flush=True,
        )
    if decision is not None:
        if action.kind == "resolve_decision":
            run_args = [user_message, "--mode", mode]
            targets = state.get("implementation_targets")
            if isinstance(targets, list):
                for target in targets:
                    target = str(target).strip()
                    if target:
                        run_args.extend(["--target", target])
            print(
                "[squad] continuing through the controller-owned decision resolver.",
                flush=True,
            )
            _cmd_run(run_args, project_root=project_root, ext_dir=ext_dir)
            return
        if action.kind == "human_resume":
            fields = [
                ("decision id", str(decision["id"])),
                ("decision needed", action.note or str(decision["question"])),
            ]
            fields.append(("options", _render_v2_decision_options(decision)))
            fields.append(("resume with", action.command))
            _note_spec_summary_next_printed()
            _banner("CHECKPOINT", fields, subtitle="Run paused. Human decision required.")
            return
        if action.kind == "manual_recovery":
            _note_spec_summary_next_printed()
            _banner(
                "CHECKPOINT",
                [
                    ("blocked by", action.reason),
                    ("next", action.command),
                    ("note", action.note),
                ],
                subtitle="Run paused. Manual recovery required.",
            )
            return

    prepared_state, _ = _ensure_active_continue_spec_context(
        project_root,
        squad_dir,
        state,
        sync_missing=True,
    )
    if prepared_state != state:
        state = prepared_state
        (squad_dir / "state.json").write_text(_json.dumps(state, indent=2, ensure_ascii=False))

    phase_labels = {
        "phase1-discover":     "SCOUT (retry failed discovery dispatch)",
        "phase1-constitution": "CHIEF → constitution protocol (creates constitution.md)",
        "phase1-what":         "CARTOGRAPHER (spec authoring or amendment)",
        "phase1-lexicon-derive": "LEXICON DERIVER (derived artifact repair)",
        "phase1-lexicon":      "Deterministic spec Lexicon gate",
        "phase1-understanding": "Deterministic Understanding gate",
        "phase3-how":          "ARCHITECT (architecture, data-model, contracts)",
        "phase3-plan":         "ORCHESTRATOR (task breakdown)",
        "phase3-consensus":    "Consensus gate (WHY3 + ASSESS2 + PLAN2)",
    }

    def resume_run_args() -> list[str]:
        """Reconstruct the original execution scope from controller-owned state."""
        targets = state.get("implementation_targets")
        stored_targets = (
            [str(value).strip() for value in targets if str(value).strip()]
            if isinstance(targets, list)
            else []
        )
        run_args = [user_message, "--mode", mode]
        for target in stored_targets:
            run_args.extend(["--target", target])
        return run_args

    def start_phase(next_phase: str, *, verb: str, clear_recovery: bool = False) -> None:
        nonlocal state
        state, _ = _ensure_active_continue_spec_context(
            project_root,
            squad_dir,
            state,
            sync_missing=True,
        )
        state["phase"] = next_phase
        state["status"] = "running"
        if next_phase == "phase3-sentinel":
            spec_dir = _resolve_phase_target_spec_dir(project_root, state, squad_dir)
            coverage_error = (
                coverage_contract_error(
                    spec_dir, check_task_ownership=(spec_dir / "tasks.md").exists()
                )
                if spec_dir is not None
                else None
            )
            if coverage_error is not None:
                state["phase_output_recovery"] = {
                    "phase": "phase3-sentinel",
                    "invalid_outputs": [{
                        "path": "coverage-map.md",
                        "reason": coverage_error,
                    }],
                    "prior_state_updates": {},
                }
            elif spec_dir is not None and (spec_dir / "coverage-map.md").is_file():
                recovery = state.get("phase_output_recovery")
                if isinstance(recovery, dict) and recovery.get("phase") == next_phase:
                    # Revalidation supersedes obsolete errors (including the
                    # legacy pre-planning tasks.md dependency), not missing files.
                    recovery["invalid_outputs"] = [
                        item for item in recovery.get("invalid_outputs", [])
                        if item.get("path") != "coverage-map.md"
                    ]
        if clear_recovery:
            state["blocked_reason"] = None
            state["escalation_question"] = None
            state["escalation_options"] = None
            state.pop("recovery_instruction", None)
        (squad_dir / "state.json").write_text(_json.dumps(state, indent=2, ensure_ascii=False))
        label = phase_labels.get(next_phase, next_phase)
        print(
            f"[squad] {verb} {next_phase} — {label}\n"
            f"[squad] Task:  {(user_message[:80] + '…') if len(user_message) > 80 else user_message}\n"
            f"[squad] Mode:  {mode}",
            flush=True,
        )
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)

    issue_recovery = state.get("issue_resolution_recovery")
    if (
        isinstance(issue_recovery, dict)
        and issue_recovery.get("status") != "consumed"
        and str(issue_recovery.get("issue_id") or "").strip()
        and action.reason == "issue_resolution"
    ):
        print(
            "[squad] continuing via controller-owned issue-repair workflow edge; "
            "the controller will validate it before dispatch.",
            flush=True,
        )
        # ``_cmd_run`` preserves a terminal-blocked state verbatim.  In semi
        # mode that makes the controller immediately return the same
        # escalation rather than dispatching the requested repair.  Promote
        # the controller-owned recovery edge back to its target phase first;
        # keep its issue ledger/recovery payload so WHY2 can validate it.
        repair_phase = str(issue_recovery.get("to_phase") or "phase1-what").strip()
        start_phase(
            repair_phase or "phase1-what",
            verb="Continuing selected issue repair",
            clear_recovery=True,
        )
        return

    if action.reason == "issue_resolution_revalidation":
        selected_issue = str(state.get("selected_issue_resolution") or "").strip()
        state["issue_resolution_revalidation_attempted"] = selected_issue
        state["why_fail_count"] = 0
        state["why2_metric_stagnation_count"] = 0
        state.pop("why_failure_baseline", None)
        start_phase(
            "phase1-understanding",
            verb="Revalidating selected issue repair",
            clear_recovery=True,
        )
        return

    if action.reason == "quality_gate_remediation":
        state["iteration"] = 0
        state["why_fail_count"] = 0
        state["why2_metric_stagnation_count"] = 0
        state.pop("why_failure_baseline", None)
        # A certified remediation is a new, spec-changing lifecycle cycle.
        # Keep unrelated phase counters for observability, but reset every
        # authoring/quality phase that must run to verify this new artifact.
        _reset_quality_remediation_dispatch_counts(state)
        qualitative_findings = _current_qualitative_findings(state)
        state["quality_gate_remediation"] = {
            "evidence": state.get("understanding_evidence"),
            "baseline_spec_sha256": _spec_markdown_sha256_for_state(
                state, project_root
            ),
            "attempt": int(
                (state.get("quality_gate_remediation") or {}).get("attempt", 0)
            ) + 1 if isinstance(state.get("quality_gate_remediation"), dict) else 1,
            "reason": (
                "All named issue resolutions are complete, but certified quality "
                "review still fails. Begin a fresh remediation cycle."
            ),
            **(
                {"qualitative_findings": qualitative_findings}
                if qualitative_findings
                else {}
            ),
        }
        _supersede_quality_guard_decision(state)
        start_phase(
            "phase1-what",
            verb="Starting quality-gate remediation",
            clear_recovery=True,
        )
        return

    # Echelon versions before the banzai-routing fix persisted a COMMANDER
    # ``next_phase`` as inert metadata, then incorrectly entered Phase-A
    # finalization from ``terminal-blocked``.  Recover that exact historic
    # state without treating the readiness failure as a reason to rewind.
    persisted_banzai_phase = str(state.get("next_phase") or "").strip()
    if (
        state.get("status") == "blocked"
        and state.get("phase") == "terminal-blocked"
        and state.get("blocked_reason") == "phase_a_readiness_failed"
        and state.get("escalation_resolver") == "COMMANDER-banzai"
        and state.get("escalation_resolved") is True
        and persisted_banzai_phase in _ROADMAP_PHASES
    ):
        state.pop("next_phase", None)
        print(
            "[squad] Recovering the persisted banzai COMMANDER route before finalization.",
            flush=True,
        )
        start_phase(
            persisted_banzai_phase,
            verb="Continuing from accepted banzai judgment",
            clear_recovery=True,
        )
        return

    if action.kind == "safe_rewind":
        fields = [("blocked by", action.reason)]
        if action.note:
            fields.append(("why", action.note))
        fields.extend([
            ("recover with", action.command),
            ("then", "echelon spec continue"),
        ])
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Deterministic recovery required.",
        )
        return
    if action.reason == "phase_dispatch_limit_option_contract_retry":
        start_phase(
            action.phase,
            verb="Retrying dispatch-cap option preparation",
            clear_recovery=True,
        )
        return
    if action.reason in {
        "phase_dispatch_limit_evidence_retry",
        "phase_dispatch_limit_certification_epoch",
    }:
        if action.reason == "phase_dispatch_limit_certification_epoch":
            certificate = state.get("spec_quality_certificate")
            source_sha256 = (
                str(certificate.get("source_sha256") or "").strip()
                if isinstance(certificate, dict)
                else ""
            )
            state["phase_dispatch_limit_certification_epoch_recovery"] = {
                "schema_version": 1,
                "phase": action.phase,
                "source_sha256": source_sha256,
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            }
        dispatch_counts = state.get("phase_dispatch_counts")
        if isinstance(dispatch_counts, dict):
            dispatch_counts = dict(dispatch_counts)
            dispatch_counts.pop(action.phase, None)
            state["phase_dispatch_counts"] = dispatch_counts
        start_phase(
            action.phase,
            verb="Retrying phase after active-spec evidence recovery",
            clear_recovery=True,
        )
        return
    if action.kind == "retry_phase":
        start_phase(action.phase, verb="Retrying incomplete phase", clear_recovery=True)
        return
    if action.kind == "resolve_decision":
        print(
            "[squad] continuing through the controller-owned decision resolver.",
            flush=True,
        )
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)
        return
    if action.kind == "human_resume":
        fields = [
            ("decision needed", action.note or "(no escalation question recorded)"),
        ]
        rendered_options = _render_escalation_options(
            state.get("escalation_options")
        )
        if rendered_options:
            fields.append(("options", rendered_options))
        fields.append(("resume with", action.command))
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Human decision required.",
        )
        return
    if action.kind == "manual_recovery":
        fields = [
            ("blocked by", action.reason),
            ("next", action.command),
            ("note", action.note),
        ]
        fields.extend(_issue_resolution_screen_guidance(project_root, squad_dir, state))
        _note_spec_summary_next_printed()
        _banner(
            "CHECKPOINT",
            fields,
            subtitle="Run paused. Manual recovery required.",
        )
        return

    # terminal-blocked: the consecutive-fail guard fired. echelon spec resume recorded the
    # user's answer but left phase=terminal-blocked (a TERMINAL_PHASE). The controller
    # would exit immediately from that phase, so we repair state here — advance the
    # phase to the next runnable one — before resuming in the SAME squad dir.
    if cur_phase == "terminal-blocked":
        next_phase = _next_continue_phase(project_root)
        if next_phase is None:
            _note_spec_summary_next_printed()
            print(
                "Build is ready — nothing left to do in Phase A.\n\n"
                "  echelon delivery run <spec-id>",
                flush=True,
            )
            return
        start_phase(next_phase, verb="Continuing from")
        return

    if status in ("running", "in_progress"):
        # Live run — let echelon spec run pick it up (same message → same dir → resume)
        print(f"[squad] Resuming active run in {squad_dir.name}…", flush=True)
        _cmd_run(resume_run_args(), project_root=project_root, ext_dir=ext_dir)
        return

    # Determine the next phase automatically
    next_phase = _next_continue_phase(project_root)
    if next_phase is None:
        _note_spec_summary_next_printed()
        print(
            "Build is ready — nothing left to do in Phase A.\n\n"
            "  echelon delivery run <spec-id>",
            flush=True,
        )
        return

    start_phase(next_phase, verb="Continuing from")


@dataclass(frozen=True)
class _FailedGateRewindAuthority:
    decision_id: str
    state_revision: int
    source_phase: str
    v2_automatic_eligible: bool


def _resolve_rewind_checkpoint(
    ledger: object,
    target: str,
    *,
    commit: str,
    next_phase: str,
) -> object:
    """Resolve the same recovery-specific ledger candidate rendered by status."""
    from harness.phase_checkpoints import resolve_rewind_checkpoint

    return resolve_rewind_checkpoint(
        ledger,
        target,
        commit=commit,
        next_phase=next_phase,
    )


def _failed_gate_rewind_authority(
    state: Mapping[str, object],
    checkpoint: object,
    *,
    project_root: Path,
) -> _FailedGateRewindAuthority | None:
    """Authorize a failed gate rewind before any Git or ledger mutation."""
    from echelon.rewind import RewindError

    if (
        str(getattr(checkpoint, "phase", "") or "") == "phase3-sentinel"
        and _coverage_map_planning_defect_for_spec(
            project_root,
            str(state.get("spec_id") or ""),
        )
    ):
        # Delivery has authoritatively established that Phase A's test plan is
        # stale. Replaying SENTINEL preserves resolved product decisions and
        # regenerates only its dependent planning artifacts.
        return None

    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    try:
        decision = _validated_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        raise RewindError(f"versioned decision authority is invalid: {exc}") from exc
    assert decision is not None
    if decision["status"] == "resolved":
        source_phase = str(decision.get("source_phase") or "").strip()
        if (
            decision["source_kind"] == "human_gate"
            and state.get("status") == "blocked"
            and state.get("blocked_reason") == "gate_rejected"
            and str(getattr(checkpoint, "next_phase", "") or "").strip()
            == source_phase
        ):
            return None
        raise RewindError(
            "resolved decision authority is not an exact gate-rejected rewind"
        )
    if decision["status"] != "failed":
        raise RewindError("unresolved decision authority does not permit rewind")
    source_phase = str(decision.get("source_phase") or "").strip()
    predecessor = str(getattr(checkpoint, "phase", "") or "").strip()
    checkpoint_next = str(
        getattr(checkpoint, "next_phase", "") or ""
    ).strip()
    revision = state.get("state_revision")
    v2_eligible = _v2_automatic_decision_is_registered(
        decision,
        project_root=project_root,
    )
    eligible = (
        decision.get("automatic_eligible") is True
        if decision["schema_version"] == 3
        else v2_eligible
    )
    if (
        decision["source_kind"] != "human_gate"
        or decision["autonomy_mode"] != "banzai"
        or state.get("autonomy_mode") != "banzai"
        or state.get("status") != "blocked"
        or state.get("phase") != source_phase
        or not eligible
        or checkpoint_next != source_phase
        or not predecessor
        or type(revision) is not int
        or revision < 0
    ):
        raise RewindError(
            "failed decision does not match the exact Banzai human-gate "
            "rewind authority and checkpoint predecessor"
        )
    return _FailedGateRewindAuthority(
        decision_id=str(decision["id"]),
        state_revision=revision,
        source_phase=source_phase,
        v2_automatic_eligible=v2_eligible,
    )


def _cmd_rewind(
    args: list[str],
    project_root: Path,
) -> None:
    confirm = False
    checkpoint_commit = ""
    checkpoint_next_phase = ""
    commit_seen = False
    next_phase_seen = False
    target = ""
    invalid = False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--confirm":
            if confirm:
                invalid = True
                break
            confirm = True
            index += 1
            continue
        if arg == "--commit":
            if (
                commit_seen
                or index + 1 >= len(args)
                or args[index + 1].startswith("--")
            ):
                invalid = True
                break
            commit_seen = True
            checkpoint_commit = args[index + 1].strip()
            if not checkpoint_commit:
                invalid = True
                break
            index += 2
            continue
        if arg == "--next-phase":
            if (
                next_phase_seen
                or index + 1 >= len(args)
                or args[index + 1].startswith("--")
            ):
                invalid = True
                break
            next_phase_seen = True
            checkpoint_next_phase = args[index + 1].strip()
            if not checkpoint_next_phase:
                invalid = True
                break
            index += 2
            continue
        if arg.startswith("--") or target:
            invalid = True
            break
        target = arg.strip()
        index += 1
    if invalid or not target:
        print(
            "Usage: echelon spec rewind <checkpoint-phase-or-id> "
            "[--commit <sha>] [--next-phase <phase-id>] [--confirm]\n"
            "Run `echelon spec checkpoint list` to see active-ledger targets.",
            file=sys.stderr,
        )
        sys.exit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").exists():
        print(
            "✗ No active squad run found.\n"
            "  Start or resume a run before rewinding.",
            file=sys.stderr,
        )
        sys.exit(1)

    from harness.squad_state import SquadStateStore

    from harness.element_identity_legacy_guard import (
        LEGACY_IDENTITY_EXECUTION_BLOCKED,
        require_legacy_identity_execution,
        require_legacy_identity_spec,
    )
    from harness.element_identity_store import IdentityStoreError
    from harness.squad_state import StateAdvanceError

    store = SquadStateStore(squad_dir)
    invalid_managed_state = False
    try:
        state = store.load()
    except StateAdvanceError as exc:
        if exc.validator != "managed_identity":
            raise
        invalid_managed_state = True
    if invalid_managed_state:
        print(f"✗ Cannot rewind to {target}.\n  {LEGACY_IDENTITY_EXECUTION_BLOCKED}", file=sys.stderr)
        raise SystemExit(1)
    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
    if spec_dir is None or spec_dir_ref is None:
        print(
            f"✗ Cannot rewind to {target}.\n"
            "  Could not resolve the canonical spec directory from state.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    from echelon.rewind import RewindError, prepare_rewind
    from harness.phase_checkpoints import (
        load_checkpoint_ledger,
        rewindable_checkpoint_targets,
        write_checkpoint_ledger,
    )

    ledger = load_checkpoint_ledger(spec_dir)
    try:
        checkpoint = _resolve_rewind_checkpoint(
            ledger,
            target,
            commit=checkpoint_commit,
            next_phase=checkpoint_next_phase,
        )
    except (KeyError, ValueError) as exc:
        available = rewindable_checkpoint_targets(ledger)
        reason = str(exc.args[0]) if exc.args else (
            f"checkpoint not found for spec {ledger.spec_id}: {target}"
        )
        detail = (
            f"{reason}\n"
            + (
                f"Available checkpoints: {', '.join(available)}"
                if available
                else "No checkpoints are recorded for this spec."
            )
        )
        print(f"✗ Cannot rewind to {target}.\n  {detail}", file=sys.stderr)
        sys.exit(1)
    if checkpoint.rewind != "supported":
        print(
            f"✗ Cannot rewind to {target}.\n"
            f"  Checkpoint does not support rewind: {checkpoint.rewind_reason}",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        _failed_gate_rewind_authority(
            state,
            checkpoint,
            project_root=project_root,
        )
    except RewindError as exc:
        print(f"✗ Cannot rewind to {target}.\n  {exc}", file=sys.stderr)
        sys.exit(1)

    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecMutationLock,
        SpecRunExecutionLock,
    )

    operation_id = f"rewind-{os.getpid()}"
    expected_spec_id = spec_dir.name
    try:
        with (
            SpecMutationLock.acquire(project_root, spec_dir.name, operation_id)
            if confirm
            else nullcontext()
        ):
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                locked_squad_dir = _find_current_run_dir(project_root)
                if locked_squad_dir != squad_dir:
                    print(
                        "✗ Cannot rewind because the active run changed before "
                        "the mutation lease was acquired. Retry against the new active run.",
                        file=sys.stderr,
                    )
                    raise SystemExit(1)
                with SpecRunExecutionLock.acquire(locked_squad_dir, operation_id):
                    if _find_current_run_dir(project_root) != locked_squad_dir:
                        print(
                            "✗ Cannot rewind because the active run changed while "
                            "the execution lease was being acquired. Retry.",
                            file=sys.stderr,
                        )
                        raise SystemExit(1)

                    store = SquadStateStore(locked_squad_dir)
                    invalid_managed_state = False
                    try:
                        state = store.load()
                    except StateAdvanceError as exc:
                        if exc.validator != "managed_identity":
                            raise
                        invalid_managed_state = True
                    if invalid_managed_state:
                        raise RewindError(LEGACY_IDENTITY_EXECUTION_BLOCKED)
                    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(
                        project_root,
                        state,
                    )
                    if spec_dir is None or spec_dir_ref is None:
                        raise RewindError(
                            "could not resolve the canonical spec directory from "
                            "the locked state.json snapshot"
                        )
                    if spec_dir.name != expected_spec_id:
                        print(
                            "✗ Cannot rewind because the active spec identity changed "
                            "before the mutation lease was acquired. Retry.",
                            file=sys.stderr,
                        )
                        raise SystemExit(1)
                    admitted = False
                    try:
                        require_legacy_identity_spec(
                            project_root=project_root, spec_id=spec_dir.name,
                        )
                        require_legacy_identity_execution(
                            project_root=project_root, run_dir=locked_squad_dir, state=state,
                        )
                        admitted = True
                    except IdentityStoreError:
                        pass
                    if not admitted:
                        raise RewindError(LEGACY_IDENTITY_EXECUTION_BLOCKED)
                    ledger = load_checkpoint_ledger(spec_dir)
                    try:
                        checkpoint = _resolve_rewind_checkpoint(
                            ledger,
                            target,
                            commit=checkpoint_commit,
                            next_phase=checkpoint_next_phase,
                        )
                    except (KeyError, ValueError) as exc:
                        available = rewindable_checkpoint_targets(ledger)
                        reason = str(exc.args[0]) if exc.args else (
                            f"checkpoint not found for spec {ledger.spec_id}: {target}"
                        )
                        suffix = (
                            f"\nAvailable checkpoints: {', '.join(available)}"
                            if available
                            else "\nNo checkpoints are recorded for this spec."
                        )
                        raise RewindError(reason + suffix) from exc
                    if checkpoint.rewind != "supported":
                        raise RewindError(
                            "checkpoint does not support rewind: "
                            f"{checkpoint.rewind_reason}"
                        )
                    failed_gate_authority = _failed_gate_rewind_authority(
                        state,
                        checkpoint,
                        project_root=project_root,
                    )
                    replacement_state = deepcopy(state)

                    coverage_map_recovery = (
                        str(getattr(checkpoint, "phase", "") or "")
                        == "phase3-sentinel"
                        and _coverage_map_planning_defect_for_spec(
                            project_root,
                            str(state.get("spec_id") or ""),
                        )
                    )
                    recovery_dirty_paths = (
                        frozenset(
                            {
                                "spec.md",
                                "tasks.md",
                                "harness-run-history.json",
                            }
                        )
                        if coverage_map_recovery
                        else frozenset()
                    )
                    if checkpoint.source == "retarget-preflight":
                        from echelon.spec_retarget_recovery import (
                            RetargetRecoveryError,
                            require_legacy_retarget_recovery,
                            resume_committed_retarget_recovery,
                            retarget_recovery_dirty_paths,
                            verified_committed_retarget_recovery,
                        )

                        identity_blocked = False
                        try:
                            require_legacy_retarget_recovery(
                                project_root, checkpoint, replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            if str(exc) != LEGACY_IDENTITY_EXECUTION_BLOCKED:
                                raise RewindError(str(exc)) from exc
                            identity_blocked = True
                        if identity_blocked:
                            raise RewindError(LEGACY_IDENTITY_EXECUTION_BLOCKED)
                        try:
                            recovery_commit = verified_committed_retarget_recovery(
                                project_root,
                                checkpoint,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                        if recovery_commit is not None and not confirm:
                            print(
                                "Retarget recovery is already committed. No changes "
                                "were made.\n"
                                f"  echelon spec rewind checkpoint:{checkpoint.id} "
                                "--confirm"
                            )
                            return
                        if recovery_commit is not None:
                            try:
                                resumed = resume_committed_retarget_recovery(
                                    project_root,
                                    checkpoint,
                                    replacement_state,
                                )
                            except RetargetRecoveryError as exc:
                                raise RewindError(str(exc)) from exc
                            if resumed is None:
                                raise RewindError(
                                    "verified retarget recovery commit became unavailable"
                                )
                            print(
                                "Retarget recovery was already committed; "
                                "state and active-run publication are complete."
                            )
                            return
                        try:
                            recovery_dirty_paths = retarget_recovery_dirty_paths(
                                project_root,
                                spec_dir,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                    if coverage_map_recovery:
                        # Validate the only state transition unique to this
                        # recovery before prepare_rewind mutates Git or removes
                        # recovery-owned files. The post-rewind call below
                        # still writes the exact rewind state after cleanup.
                        _reset_rewind_state(
                            state,
                            checkpoint.phase,
                            spec_dir_ref,
                            boundary_completion_id=(
                                checkpoint.boundary_completion_id
                            ),
                            preserve_resolved_coverage_map_repair=True,
                        )
                    result = prepare_rewind(
                        project_root=project_root,
                        spec=spec_dir.name,
                        spec_dir=spec_dir,
                        dirty_spec_dir=(
                            project_root / "specs" / spec_dir.name
                            if (project_root / "specs" / spec_dir.name).is_dir()
                            else spec_dir
                        ),
                        target=target,
                        confirm=confirm,
                        checkpoint_commit=checkpoint_commit,
                        checkpoint_next_phase=checkpoint_next_phase,
                        discard_active_spec_dirty_paths=recovery_dirty_paths,
                    )
                    if not result.applied:
                        print(result.message)
                        return

                    target_index = ledger.checkpoints.index(checkpoint)
                    retained_ledger = type(ledger)(
                        spec_id=ledger.spec_id,
                        checkpoints=ledger.checkpoints[: target_index + 1],
                    )
                    write_checkpoint_ledger(spec_dir, retained_ledger)
                    if checkpoint.source == "retarget-preflight":
                        from echelon.spec_retarget_recovery import (
                            RetargetRecoveryError,
                            recover_retarget_checkpoint,
                        )

                        try:
                            recover_retarget_checkpoint(
                                project_root,
                                checkpoint,
                                replacement_state,
                            )
                        except RetargetRecoveryError as exc:
                            raise RewindError(str(exc)) from exc
                        removed = ()
                    else:
                        checkpoint_phases_before_target = {
                            item.phase for item in ledger.checkpoints[:target_index]
                        }
                        removed = _cleanup_rewind_outputs(
                            spec_dir,
                            checkpoint.phase,
                            squad_dir,
                        )
                        rewound = _reset_rewind_state(
                            state,
                            checkpoint.phase,
                            spec_dir_ref,
                            checkpoint_phases_before_target=(
                                checkpoint_phases_before_target
                            ),
                            boundary_completion_id=(
                                checkpoint.boundary_completion_id
                            ),
                            preserve_resolved_gate_rejection=(
                                failed_gate_authority is None
                                and isinstance(state.get("blocked_decision"), Mapping)
                                and state["blocked_decision"].get("status") == "resolved"
                            ),
                            preserve_resolved_coverage_map_repair=(
                                coverage_map_recovery
                            ),
                            preserve_failed_human_gate_for_cas=(
                                failed_gate_authority is not None
                            ),
                        )
                        if failed_gate_authority is None:
                            store.save(rewound)
                        else:
                            from harness.squad_state import StateAdvanceError

                            try:
                                store.rewind_failed_banzai_human_gate(
                                    failed_gate_authority.decision_id,
                                    expected_state_revision=(
                                        failed_gate_authority.state_revision
                                    ),
                                    source_phase=(
                                        failed_gate_authority.source_phase
                                    ),
                                    predecessor_phase=checkpoint.phase,
                                    rewound_state=rewound,
                                    v2_automatic_eligible=(
                                        failed_gate_authority.v2_automatic_eligible
                                    ),
                                )
                            except StateAdvanceError as exc:
                                raise RewindError(str(exc)) from exc
    except SpecLifecycleLocked as exc:
        print(
            "✗ Cannot rewind while the active spec run is still running.\n"
            f"  Execution or spec mutation lease owner: {exc.operation_id}.\n"
            "  Interrupt it and wait for `echelon spec status` to show INTERRUPTED, then retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    except RewindError as exc:
        print(f"✗ Cannot rewind to {target}.\n  {exc}", file=sys.stderr)
        sys.exit(1)

    _banner(
        "REWIND COMPLETE",
        [
            ("spec", result.spec_id),
            ("checkpoint", result.checkpoint_id),
            ("from", result.from_commit[:7]),
            ("to", result.to_commit[:7]),
            ("backup", result.backup_ref or "(none)"),
            ("cleaned", ", ".join(removed) if removed else "(none)"),
            ("next", "echelon spec continue"),
        ],
    )


def _cmd_repair_traceability(args: list[str], project_root: Path) -> None:
    """Safely remove contextual task references from active product-input evidence."""
    confirm = "--confirm" in args
    if any(arg != "--confirm" for arg in args):
        print("Usage: echelon spec repair-traceability [--confirm]", file=sys.stderr)
        raise SystemExit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None or not (squad_dir / "state.json").is_file():
        print("✗ No active squad run found.", file=sys.stderr)
        raise SystemExit(1)

    if confirm:
        from threading import get_ident
        from uuid import uuid4

        from echelon.spec_lifecycle import (
            PhaseAExecutionLock,
            SpecLifecycleLocked,
            SpecRunExecutionLock,
        )

        operation_id = f"repair-traceability-{os.getpid()}-{get_ident()}-{uuid4().hex}"
        try:
            with PhaseAExecutionLock.acquire(project_root, operation_id):
                with SpecRunExecutionLock.acquire(squad_dir, operation_id):
                    _cmd_repair_traceability_locked(project_root, squad_dir, confirm=True)
                    return
        except SpecLifecycleLocked as exc:
            print(
                "✗ Cannot repair traceability while execution is active.\n"
                f"  Lease owner: {exc.operation_id}",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc
    _cmd_repair_traceability_locked(project_root, squad_dir, confirm=False)


def _cmd_repair_traceability_locked(
    project_root: Path,
    squad_dir: Path,
    *,
    confirm: bool,
) -> None:
    """Preview or transactionally commit an authenticated package repair."""
    from uuid import uuid4

    from echelon.product_input_transaction import (
        ProductInputMutationError,
        add_complete_product_input_publication,
        authenticate_pending_product_input_mutation,
        authenticate_product_input_contract,
        build_product_input_mutation,
        product_input_tree_identity,
        require_product_input_mutation_postimage,
        restore_product_input_directory_modes,
    )
    from echelon.product_inputs import (
        immutable_product_input_tree_digest,
        repair_product_input_traceability,
    )
    from echelon.spec_add_input import SpecAddInputError, _recover_pending_mutation
    from harness.squad_publication import SquadPublicationTransaction
    from harness.squad_state import SquadStateStore

    store = SquadStateStore(squad_dir)
    if confirm:
        try:
            recovered = _recover_pending_mutation(project_root, store)
        except SpecAddInputError as exc:
            print(f"✗ Traceability repair recovery failed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if recovered is not None and recovered.get("kind") == "traceability_repair":
            _banner(
                "TRACEABILITY REPAIRED",
                [("next", "echelon spec continue")],
                subtitle="Recovered the authenticated repair publication.",
            )
            return
    state = store.load()
    if str(state.get("blocked_reason") or "") != "phase_a_readiness_failed":
        print("✗ Traceability repair is available only for a Phase A readiness block.", file=sys.stderr)
        raise SystemExit(1)
    spec_dir, spec_dir_ref = _normalize_rewind_spec_dir(project_root, state)
    inputs = state.get("product_inputs")
    traceability_ref = str(inputs.get("traceability") or "").strip() if isinstance(inputs, dict) else ""
    inputs_ref = str(inputs.get("inputs_dir") or "").strip() if isinstance(inputs, dict) else ""
    if spec_dir is None or spec_dir_ref is None or not traceability_ref or not inputs_ref:
        print("✗ Active run lacks the spec or product-input evidence needed for repair.", file=sys.stderr)
        raise SystemExit(1)
    inputs_dir = Path(inputs_ref)
    if not inputs_dir.is_absolute():
        inputs_dir = project_root / inputs_dir
    inputs_dir = inputs_dir.resolve()
    if inputs_dir != (squad_dir / "inputs").resolve():
        print("✗ Active run Product Input Contract is not run-local.", file=sys.stderr)
        raise SystemExit(1)
    traceability_path = Path(traceability_ref)
    if not traceability_path.is_absolute():
        traceability_path = project_root / traceability_path
    if traceability_path.resolve() != inputs_dir / "traceability.json":
        print("✗ Product-input traceability pointer is not canonical.", file=sys.stderr)
        raise SystemExit(1)
    targets = [str(value).strip() for value in state.get("implementation_targets", []) if str(value).strip()]
    try:
        old_tree_hash = authenticate_product_input_contract(
            project_root,
            inputs,
            inputs_dir,
        )
    except ProductInputMutationError as exc:
        print(f"✗ Product-input package authentication failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if not confirm:
        repair = repair_product_input_traceability(
            traceability_path,
            spec_dir / "tasks.md",
            targets,
            apply=False,
        )
    else:
        snapshot = store.capture_routing_snapshot(
            expected_phase=str(state.get("phase") or "")
        )
        transaction = SquadPublicationTransaction.begin(
            project_root,
            squad_dir,
            uuid4().hex,
        )
        staged_old_inputs = transaction.build_path("work/product-inputs-old")
        staged_inputs = transaction.build_path("work/product-inputs")
        prepared = None
        try:
            source_identity = product_input_tree_identity(inputs_dir)
            shutil.copytree(
                inputs_dir,
                staged_old_inputs,
                symlinks=True,
                copy_function=shutil.copy2,
            )
            if (
                authenticate_product_input_contract(
                    project_root,
                    inputs,
                    inputs_dir,
                )
                != old_tree_hash
                or product_input_tree_identity(inputs_dir) != source_identity
                or immutable_product_input_tree_digest(staged_old_inputs)
                != old_tree_hash
            ):
                raise ProductInputMutationError(
                    "product input package changed during repair staging"
                )
            shutil.copytree(
                staged_old_inputs,
                staged_inputs,
                symlinks=True,
                copy_function=shutil.copy2,
            )
            if immutable_product_input_tree_digest(staged_inputs) != old_tree_hash:
                raise ProductInputMutationError(
                    "staged product input preimage changed during repair staging"
                )
            repair = repair_product_input_traceability(
                staged_inputs / "traceability.json",
                spec_dir / "tasks.md",
                targets,
                apply=True,
            )
            restore_product_input_directory_modes(
                staged_old_inputs,
                staged_inputs,
            )
            if repair.blockers or not repair.removed:
                transaction.seal().discard()
                prepared = False
            else:
                owned_paths = add_complete_product_input_publication(
                    transaction,
                    project_root,
                    inputs_dir,
                    staged_inputs,
                )
                new_tree_hash = immutable_product_input_tree_digest(staged_inputs)
                prepared = transaction.seal()
                marker = prepared.marker.to_dict()
                mutation = build_product_input_mutation(
                    kind="traceability_repair",
                    marker=marker,
                    inputs_dir=inputs_ref,
                    old_tree_hash=old_tree_hash,
                    new_tree_hash=new_tree_hash,
                    owned_paths=owned_paths,
                )
        except Exception as exc:
            if prepared is None:
                try:
                    transaction.seal().discard()
                except Exception:
                    pass
            print(f"✗ Cannot stage traceability repair: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc

    if repair.blockers:
        print("✗ Traceability cannot be repaired safely:", file=sys.stderr)
        for blocker in repair.blockers:
            print(f"  - {blocker}", file=sys.stderr)
        print("  Re-plan with: echelon spec rewind phase3-plan", file=sys.stderr)
        raise SystemExit(1)
    if not repair.removed:
        print("✗ No contextual task references were available to repair.", file=sys.stderr)
        raise SystemExit(1)

    rows = [("remove", f"{unit_id} → {task_id}") for unit_id, task_id in repair.removed]
    if not confirm:
        rows.append(("next", "echelon spec repair-traceability --confirm"))
        _banner("TRACEABILITY REPAIR PREVIEW", rows, subtitle="No evidence or run state changed.")
        return

    repaired = _reset_rewind_state(state, "phase4-document", spec_dir_ref)
    repaired_inputs = dict(inputs)
    repaired_inputs["tree_hash"] = new_tree_hash
    repaired["product_inputs"] = repaired_inputs
    try:
        store.begin_traceability_repair_publication(
            marker,
            mutation,
            snapshot=snapshot,
            desired_state=repaired,
        )
    except Exception as exc:
        try:
            prepared.discard()
        except Exception:
            pass
        print(f"✗ Cannot persist traceability repair intent: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    try:
        durable = store.confirm_durable_state(store.load())
        authenticate_pending_product_input_mutation(
            project_root,
            durable,
            marker,
            prepared._manifest["operations"],
            staged_inputs=staged_inputs,
        )
        prepared.publish()
        verified_hash = require_product_input_mutation_postimage(
            project_root,
            store.load(),
            marker,
        )
        store.complete_external_publication(
            marker,
            verified_product_input_tree_hash=verified_hash,
        )
        store.confirm_durable_state(store.load())
        prepared.discard()
    except Exception as exc:
        print(
            f"✗ Traceability repair remains pending with evidence retained: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    rows.append(("next", "echelon spec continue"))
    _banner("TRACEABILITY REPAIRED", rows, subtitle="Direct mappings preserved; finalization can resume.")


def _resume_versioned_human_input(
    *,
    answer: str,
    project_root: Path,
    ext_dir: Path,
    squad_dir: Path,
    store,
    state: dict,
) -> None:
    from harness.config import get_full_resolved_config, load_config
    from harness.human_input import HumanInputPolicyError
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider

    try:
        decision = _active_versioned_decision(state)
    except (RecoveryInstructionError, ValueError) as exc:
        print(f"✗ Invalid persisted decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if decision is None:
        print("✗ Active versioned decision is missing.", file=sys.stderr)
        raise SystemExit(1)

    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    token_budget = 0
    max_iterations = 5
    try:
        full_config = get_full_resolved_config(project_root)
        analysis = full_config.get("analysis") or {}
        token_budget_k = int(analysis.get("token_budget_k") or 0)
        token_budget = token_budget_k * 1000 if token_budget_k else 0
        max_iterations = int(analysis.get("max_iterations") or 5)
    except Exception:
        pass
    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=(state.get("published_re_context") or {}).get("status") == "ignored",
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
    )
    try:
        controller.resume_with_human_input(answer)
    except HumanInputPolicyError as exc:
        print(f"✗ Cannot resume decision: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    current = store.load()
    _note_spec_summary_next_printed()
    _banner(
        "HUMAN DECISION SUBMITTED",
        [
            ("Run ID", current.get("run_id", squad_dir.name)),
            ("Decision ID", decision["id"]),
            ("Answer", answer),
            ("Next", "echelon spec continue"),
        ],
    )


def _cmd_resume(
    args: list[str],
    project_root: Path,
    ext_dir: Path,
) -> None:
    """Provide user answers to an escalation-blocked squad run and continue it."""
    from harness.config import get_full_resolved_config, load_config
    from harness.blocked_decision import (
        ensure_blocked_decision,
        mark_blocked_decision_resolved,
    )
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider
    from harness.squad_state import SquadStateStore
    from echelon.spec_lifecycle import (
        PhaseAExecutionLock,
        SpecLifecycleLocked,
        SpecRunExecutionLock,
    )
    from threading import get_ident
    from uuid import uuid4

    answer = " ".join(args).strip()
    if not answer:
        print(
            "Usage: echelon spec resume \"<your answers>\"\n"
            "  Answer the escalation questions shown when the run was blocked.\n"
            "  Example: echelon spec resume \"Q1: yes, I own the IP  Q2: 13+  Q3: short missions\"",
            file=sys.stderr,
        )
        sys.exit(1)

    squad_dir = _find_current_run_dir(project_root)
    if squad_dir is None:
        print("✗ No active squad run found.", file=sys.stderr)
        print("  Start a run with: echelon spec run \"<task>\"", file=sys.stderr)
        sys.exit(1)

    store = SquadStateStore(squad_dir)
    operation_id = f"resume-{os.getpid()}-{get_ident()}-{uuid4().hex}"
    try:
        with PhaseAExecutionLock.acquire(project_root, operation_id):
            with SpecRunExecutionLock.acquire(squad_dir, operation_id):
                state = store.load()
                _register_spec_summary_run(
                    project_root,
                    squad_dir,
                    mode=state.get("autonomy_mode") or state.get("mode", "semi"),
                    message=state.get("user_message", ""),
                    implementation_targets=state.get("implementation_targets") or (),
                )
                raw_decision = state.get("blocked_decision")
                if (
                    isinstance(raw_decision, dict)
                    and raw_decision.get("schema_version") in {2, 3}
                ):
                    if state.get("status") != "blocked":
                        print(
                            "✗ Run is not blocked "
                            f"(status: {state.get('status', 'unknown')}).",
                            file=sys.stderr,
                        )
                        print("  Nothing to resume.", file=sys.stderr)
                        raise SystemExit(1)
                    _resume_versioned_human_input(
                        answer=answer,
                        project_root=project_root,
                        ext_dir=ext_dir,
                        squad_dir=squad_dir,
                        store=store,
                        state=state,
                    )
                    return
    except SpecLifecycleLocked as exc:
        print(
            f"✗ Cannot resume while execution lease is owned by {exc.operation_id}.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    if state.get("status") != "blocked":
        print(
            f"✗ Run is not blocked (status: {state.get('status', 'unknown')}).",
            file=sys.stderr,
        )
        print("  Nothing to resume.", file=sys.stderr)
        sys.exit(1)

    # A cap is not an ordinary clarification gate.  Do not record a free-text
    # answer as though it authorised progress: a concrete issue decision must
    # become controller-owned state first.
    if str(state.get("blocked_reason") or "") == "phase_dispatch_limit" and _phase_dispatch_limit_phase(state):
        print(
            "✗ A phase-dispatch cap cannot be cleared by a free-text resume answer.\n"
            "  Resolve the first unresolved issue instead:\n"
            '  echelon spec resolve ISS-<n> "<project decision>"',
            file=sys.stderr,
        )
        sys.exit(1)

    escalation_q = state.get("escalation_question")
    if not escalation_q:
        print(
            "✗ Run is blocked but no escalation question found.\n"
            "  Use: echelon spec run --next-phase <phase-id>  to recover manually",
            file=sys.stderr,
        )
        sys.exit(1)
    ensure_blocked_decision(state)
    _enforce_project_config_compatibility(project_root)

    _banner("RESUMING SQUAD RUN", [
        ("Run ID", state.get("run_id", "?")),
        ("Phase", state.get("phase", "?")),
        ("Reason", state.get("blocked_reason", "?")),
        ("Question", escalation_q.strip()),
        ("Your answer", answer),
    ])

    _preserve_active_spec_context(project_root, state)

    # Capture blocked state before clearing — needed to decide resume path and
    # to reopen the retry window after an explicitly authorized cap recovery.
    blocked_phase = state.get("phase", "")
    blocked_reason = str(state.get("blocked_reason") or "").strip()
    capped_phase = _phase_dispatch_limit_phase(state)

    # Write user's answer to staging so the re-dispatched phase can read it.
    staging_dir = Path(state.get("staging_dir", str(squad_dir / "staging")))
    clarifications_file = staging_dir / "user-clarifications.md"
    clarifications_file.write_text(
        f"# User Clarifications\n\n"
        f"> Provided via `echelon spec resume` in response to the escalation block.\n\n"
        f"## Questions asked\n\n"
        f"{escalation_q}\n\n"
        f"## User answers\n\n"
        f"{answer}\n"
    )

    # A clarification is authoritative control-plane input, not merely prompt
    # prose. Persist its generated, immutable policy before any resumed agent
    # dispatch and route stale Phase A artifacts through a narrow WHAT repair.
    from echelon.feature_policy import (
        derive_feature_policy,
        persist_feature_policy,
        reconcile_feature_artifacts,
    )

    blocked_decision = state.get("blocked_decision")
    decision_id = (
        str(blocked_decision.get("id") or "").strip()
        if isinstance(blocked_decision, dict)
        else ""
    ) or f"clarification-{state.get('run_id') or squad_dir.name}"
    feature_policy = derive_feature_policy(answer, decision_id=decision_id)
    persist_feature_policy(staging_dir, feature_policy)
    state["feature_policy"] = feature_policy
    policy_spec_ref = str(state.get("spec_dir") or "").strip()
    policy_spec_dir = Path(policy_spec_ref) if policy_spec_ref else None
    if policy_spec_dir is not None and not policy_spec_dir.is_absolute():
        policy_spec_dir = project_root / policy_spec_dir
    if policy_spec_dir is not None:
        try:
            policy_spec_dir = policy_spec_dir.resolve()
            policy_spec_dir.relative_to(project_root.resolve())
        except ValueError:
            policy_spec_dir = None
    if policy_spec_dir is not None and policy_spec_dir.is_dir():
        reconciliation = reconcile_feature_artifacts(policy_spec_dir, feature_policy)
        state["feature_policy_reconciliation"] = reconciliation
        if reconciliation["requires_repair"]:
            state["phase"] = "phase1-what"

    from echelon.context_builder import build_run_context
    context_result = build_run_context(project_root, squad_dir, user_request=str(state.get("user_message") or ""))
    state["context_dir"] = str(context_result.context_dir)

    from harness.phase_graph import load_workspace_phase_graph
    graph, ext_dir = load_workspace_phase_graph(project_root)
    raw_options = state.get("escalation_options")
    has_structured_options = isinstance(raw_options, list) and bool(raw_options)
    selected_option = None
    if has_structured_options:
        selected_option = _resolve_escalation_option(answer, raw_options)
        if selected_option is None:
            print(
                "✗ Your answer does not match any executable escalation option.\n"
                "  Answer with A/B/C, the option id, or the option label shown in the escalation.",
                file=sys.stderr,
            )
            sys.exit(1)
    if selected_option:
        next_phase = str(selected_option.get("next_phase") or "").strip()
        if next_phase:
            valid_phases = set(graph.all_phase_ids())
            if next_phase not in valid_phases:
                print(
                    f"✗ Escalation option {selected_option.get('id') or selected_option.get('label')!r} "
                    f"routes to {next_phase!r}, which is not an executable phase.",
                    file=sys.stderr,
                )
                sys.exit(1)
            state["phase"] = next_phase
        option_id = str(selected_option.get("id") or selected_option.get("label") or "").strip()
        if option_id:
            state["escalation_selected_option"] = option_id

    resumed_phase = str(state.get("phase", "")).strip()
    mark_blocked_decision_resolved(
        state,
        answer=answer,
        selected_option=selected_option,
        resumed_phase=resumed_phase,
    )

    # Clear the blocked state.
    state["escalation_question"] = None
    state["escalation_resolved"] = True
    state["escalation_resolver"] = "user"
    state["blocked_reason"] = None
    state["status"] = "running"
    store.save(state)

    # terminal-blocked is a TERMINAL_PHASE in the squad controller — running the
    # controller from there is always a silent no-op that returns "done" immediately.
    # Instead, record the answer and tell the user to run `echelon spec continue`.
    if blocked_phase == "terminal-blocked":
        _banner("SQUAD RESUMED", [
            ("answer", (answer[:60] + "…") if len(answer) > 60 else answer),
            ("status", "unblocked — answer recorded"),
            ("next", "continuing"),
            ("note", "delegating to echelon spec continue"),
            ("artifacts", str(squad_dir)),
        ])
        _cmd_continue([], project_root=project_root, ext_dir=ext_dir)
        return

    # Re-run from the current phase (same mode, same task).
    config = load_config(project_root, squad_only=True)
    provider = SquadCliProvider(config)
    token_budget = 0
    max_iterations = 5
    try:
        _full = get_full_resolved_config(project_root)
        _analysis = _full.get("analysis") or {}
        _k = int(_analysis.get("token_budget_k") or 0)
        token_budget = _k * 1000 if _k else 0
        max_iterations = int(_analysis.get("max_iterations") or 5)
    except Exception:
        pass

    controller = SquadController(
        provider=provider,
        state_store=store,
        phase_graph=graph,
        ext_dir=ext_dir,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=squad_dir,
        ignore_re=(state.get("published_re_context") or {}).get("status") == "ignored",
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
    )
    result = controller.run(
        user_message=state.get("user_message", ""),
        mode=state.get("autonomy_mode") or state.get("mode", "semi"),
    )

    _print_squad_summary(
        project_root,
        squad_dir,
        result,
        mode=state.get("autonomy_mode") or state.get("mode", "semi"),
        message=state.get("user_message", ""),
        implementation_targets=[
            str(value)
            for value in (state.get("implementation_targets") or [])
            if str(value).strip()
        ],
        command="echelon spec resume",
    )


def _resolve_escalation_option(answer: str, options: object) -> dict | None:
    """Resolve a user resume answer against structured escalation options.

    Supports A/B/C positional answers, exact option ids, and exact labels.
    Missing or text-only escalations are rejected by _cmd_resume before this helper.
    """
    if not isinstance(options, list) or not options:
        return None

    normalized = answer.strip().lower()
    if not normalized:
        return None

    first_token = normalized.split(maxsplit=1)[0].strip(").:-—–")
    positional: dict[str, dict] = {}
    by_id_or_label: dict[str, dict] = {}

    for index, raw in enumerate(options):
        if not isinstance(raw, dict):
            continue
        letter = chr(ord("a") + index)
        positional[letter] = raw
        option_id = str(raw.get("id") or "").strip().lower()
        label = str(raw.get("label") or "").strip().lower()
        if option_id:
            by_id_or_label[option_id] = raw
        if label:
            by_id_or_label[label] = raw

    return positional.get(first_token) or by_id_or_label.get(normalized)


def _preserve_active_spec_context(project_root: Path, state: dict) -> None:
    """Record the current spec branch/dir before resume re-dispatch.

    CARTOGRAPHER may be re-dispatched after a human escalation. Resume must
    continue using the same Echelon-owned branch and full spec directory.
    """
    if state.get("phase") != "phase1-what":
        return

    # Phase A bootstrap reserves a run-local target path before CARTOGRAPHER
    # authors the first spec. A directory alone is therefore not evidence of
    # an existing spec; the resume flag is set only once spec.md exists.
    state.pop("cartographer_resume_existing_spec", None)

    spec_dir = state.get("spec_dir")
    if spec_dir:
        candidate = Path(spec_dir)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if (candidate / "spec.md").is_file():
            state["cartographer_resume_existing_spec"] = True
            return

    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return

    branch = result.stdout.strip()
    if not branch or not _is_spec_feature_branch(branch):
        return

    candidate = project_root / "specs" / branch
    if not (candidate / "spec.md").is_file():
        return

    state["spec_id"] = state.get("spec_id") or branch
    state["spec_dir"] = str(candidate.relative_to(project_root))
    state["feature_branch"] = state.get("feature_branch") or branch
    state["cartographer_resume_existing_spec"] = True


def _is_spec_feature_branch(branch: str) -> bool:
    import re
    return re.match(r"^[0-9]{3,4}-[A-Za-z0-9][A-Za-z0-9._-]*$", branch) is not None


def _capability_label(capability: ProviderCapability) -> str:
    if capability == ProviderCapability.ARTIFACT:
        return "artifact"
    if capability == ProviderCapability.BUILD:
        return "build"
    return str(capability)


def _capability_article(capability: ProviderCapability) -> str:
    return "an" if capability == ProviderCapability.ARTIFACT else "a"


def _supported_capability_label(capabilities: frozenset[ProviderCapability]) -> str:
    if capabilities == frozenset({ProviderCapability.ARTIFACT}):
        return "artifact work only"
    if capabilities == frozenset({ProviderCapability.BUILD}):
        return "build work only"
    if capabilities == frozenset({ProviderCapability.ARTIFACT, ProviderCapability.BUILD}):
        return "artifact and build work"
    if not capabilities:
        return "no Echelon work"
    values = ", ".join(sorted(_capability_label(item) for item in capabilities))
    return f"{values} work"


def _installed_phase_runtime_or_exit(project_root: Path) -> Path:
    """Return the complete deployed Prosaic runtime for Phase A."""
    runtime = project_root / ".echelon" / "runtime"
    prose = project_root / ".echelon" / "prosaic" / "subagents"
    if (runtime / "workflow" / "definition.yaml").is_file() and prose.is_dir():
        from harness.workflow_validator import validate_deployed_phase_runtime

        report = validate_deployed_phase_runtime(
            definition_path=runtime / "workflow" / "definition.yaml"
        )
        if report.ok:
            return runtime
        print(
            "✗ Echelon Phase A runtime is incompatible with this controller.\n"
            f"{report.format()}\n"
            "  Run: echelon workspace migrate-to-prosaic",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        "✗ Echelon runtime not installed.\n"
        "  Run: echelon workspace migrate-to-prosaic\n"
            "  Or, for a new workspace: echelon workspace init",
        file=sys.stderr,
    )
    sys.exit(1)


def _run_spec_target_git(
    repo: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _is_git_repo(path: Path) -> bool:
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def _git_has_head_commit(repo: Path) -> bool:
    result = _run_spec_target_git(repo, ["rev-parse", "--verify", "HEAD"], check=False)
    return result.returncode == 0


def _git_branch_exists(repo: Path, branch: str) -> bool:
    result = _run_spec_target_git(
        repo, ["rev-parse", "--verify", f"refs/heads/{branch}"], check=False
    )
    return result.returncode == 0


def _prepare_spec_target_repo(workspace_root: Path, spec_dir: Path, repo: str) -> list[str]:
    target = Path(repo).expanduser()
    if not target.is_absolute():
        target = workspace_root / target

    messages: list[str] = []
    try:
        if target.exists() and not target.is_dir():
            raise RuntimeError(f"target path exists but is not a directory: {target}")

        if not target.exists():
            target.mkdir(parents=True)
            messages.append(f"Created target directory: {repo}")

        if not _is_git_repo(target):
            init = subprocess.run(
                ["git", "init", "-b", "main", str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            if init.returncode != 0:
                subprocess.run(
                    ["git", "init", str(target)],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                _run_spec_target_git(target, ["branch", "-M", "main"])
            messages.append(f"Initialized target repo: {repo}")

        if not _git_has_head_commit(target):
            _run_spec_target_git(target, ["symbolic-ref", "HEAD", "refs/heads/main"])
            _run_spec_target_git(
                target,
                [
                    "-c",
                    "user.name=Echelon",
                    "-c",
                    "user.email=echelon@example.invalid",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "chore: initialize target repository",
                ],
            )
            messages.append(
                "Created initial target commit: chore: initialize target repository"
            )

        feature_branch = spec_dir.name
        if _git_branch_exists(target, feature_branch):
            messages.append(f"Feature branch already exists: {feature_branch}")
        else:
            _run_spec_target_git(target, ["branch", feature_branch])
            messages.append(f"Created feature branch: {feature_branch}")
    except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        print(
            f"✗ Could not initialize target repo {repo!r}.\n"
            f"  Error: {detail}",
            file=sys.stderr,
        )
        sys.exit(1)

    return messages


def _commit_initialized_workspace_sources(
    workspace_root: Path,
    *,
    run_id: str,
    retry_command: str,
) -> str:
    """Commit the exact source-registry mutation before squad dispatch."""
    from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message

    config_path = ".echelon/config.yml"
    message = build_echelon_commit_message(
        "chore: register workspace sources",
        EchelonCommitMetadata(
            origin="workspace",
            action="source-register",
            run_id=run_id,
        ),
    )
    try:
        tracked_status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        changed_paths = {
            line[3:].split(" -> ")[-1]
            for line in tracked_status
            if len(line) >= 4
        }
        if changed_paths != {config_path}:
            observed = ", ".join(sorted(changed_paths)) or "none"
            raise RuntimeError(
                "source registration did not own the exact tracked change set; "
                f"observed: {observed}"
            )
        subprocess.run(
            ["git", "add", "--", config_path],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Echelon",
                "-c",
                "user.email=echelon-workspace@example.invalid",
                "commit",
                "--only",
                "-m",
                message,
                "--",
                config_path,
            ],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD^{commit}"],
            cwd=workspace_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        else:
            detail = str(exc)
        print(
            "✗ Could not commit the initialized workspace source registry.\n"
            f"  Error: {detail}\n"
            "  Fix: git add .echelon/config.yml && "
            "git commit -m 'chore: register workspace sources'\n"
            f"  Then: {retry_command}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(f"Committed workspace source registry: {commit[:12]}")
    return commit




def _phase_state_updates_for_target(
    project_root: Path,
    current_state: dict,
    target_spec_dir: Path | None,
    *,
    materialize: bool = True,
) -> dict:
    """Build state fields that make phase context/output target the spec dir."""
    if target_spec_dir is None:
        return {}

    if materialize:
        target_spec_dir.mkdir(parents=True, exist_ok=True)

    source_refs = [
        str(current_state.get("phase_run_source_spec_dir") or "").strip(),
        str(current_state.get("spec_dir") or "").strip(),
        str(current_state.get("published_spec_dir") or "").strip(),
        f"specs/{target_spec_dir.name}",
    ]
    for source_ref in source_refs:
        if not source_ref:
            continue
        source = Path(source_ref)
        if not source.is_absolute():
            source = project_root / source
        if (
            materialize
            and source.exists()
            and source.is_dir()
            and source.resolve() != target_spec_dir.resolve()
        ):
            _copy_missing_tree(source, target_spec_dir)
            break

    published_ref = str(current_state.get("published_spec_dir") or "").strip()
    if not published_ref:
        published_ref = f"specs/{target_spec_dir.name}"
    target_ref = _repo_relative_or_absolute(target_spec_dir, project_root)

    updates: dict[str, str] = {
        "spec_id": target_spec_dir.name,
        "spec_dir": target_ref,
        "published_spec_dir": published_ref,
        "phase_run_source_spec_dir": target_ref,
    }
    return updates


def _failed_automatic_phase_replay(
    state: Mapping[str, object],
    *,
    phase_id: str,
    spec_arg: str,
    project_root: Path,
    run_dir: Path,
    graph: object,
) -> _FailedAutomaticPhaseReplay | None:
    """Validate failed replay authority before resolving or materializing a target."""
    raw_decision = state.get("blocked_decision")
    if (
        not isinstance(raw_decision, Mapping)
        or raw_decision.get("schema_version") not in {2, 3}
    ):
        return None
    decision = _validated_versioned_decision(state)
    if decision is None or decision["status"] != "failed":
        return None
    source_phase = str(decision.get("source_phase") or "").strip()
    revision = state.get("state_revision")
    v2_eligible = _v2_automatic_decision_is_registered(
        decision,
        project_root=project_root,
        graph=graph,
    )
    eligible = (
        decision.get("automatic_eligible") is True
        if decision["schema_version"] == 3
        else v2_eligible
    )
    if decision["source_kind"] not in {
        "provider_escalation",
        "controller_safeguard",
    }:
        raise ValueError(
            "failed human-gate authority requires its ledger-derived confirmed rewind command"
        )
    if (
        decision["autonomy_mode"] != "banzai"
        or state.get("autonomy_mode") != "banzai"
        or state.get("status") != "blocked"
        or state.get("phase") != source_phase
        or phase_id != source_phase
        or not eligible
        or type(revision) is not int
        or revision < 0
    ):
        replay_command = _command_display(
            "echelon phase run",
            [source_phase],
        )
        raise ValueError(
            "failed automatic decision can only be retired by its exact "
            f"source replay: {replay_command}"
        )
    spec_id = str(state.get("spec_id") or "").strip()
    spec_dir_ref = str(state.get("spec_dir") or "").strip()
    if not spec_id or not spec_dir_ref:
        raise ValueError("failed decision replay has no exact active spec identity")
    spec_dir = Path(spec_dir_ref)
    if not spec_dir.is_absolute():
        spec_dir = project_root / spec_dir
    expected_run_spec_dir = run_dir / "specs" / spec_id
    if (
        not spec_dir.is_dir()
        or spec_dir.resolve() != expected_run_spec_dir.resolve()
        or spec_dir.name != spec_id
    ):
        raise ValueError(
            "failed decision replay is not bound to the active run-local spec"
        )
    selector = spec_arg.strip()
    if selector:
        candidate = Path(selector)
        path_selector = candidate.is_absolute() or len(candidate.parts) > 1
        if path_selector:
            if not candidate.is_absolute():
                candidate = project_root / candidate
            selector_matches = (
                candidate.is_dir()
                and candidate.resolve() == spec_dir.resolve()
            )
        else:
            selector_matches = selector == spec_id
        if not selector_matches:
            raise ValueError(
                f"failed decision replay is bound to active spec {spec_id!r}; "
                f"--spec {selector!r} selects a different target"
            )
    return _FailedAutomaticPhaseReplay(
        decision=decision,
        state_revision=revision,
        v2_automatic_eligible=v2_eligible,
        spec_id=spec_id,
        spec_dir_ref=spec_dir_ref,
        spec_dir=spec_dir,
    )


def _phase_context_resolution_rows(
    node: object,
    project_root: Path,
    state: dict,
    target_spec_dir: Path | None,
) -> list[tuple[str, str]]:
    """Return compact context-pack resolution rows for phase-run UX."""
    staging_ref = str(state.get("staging_dir") or "").strip()
    staging = Path(staging_ref) if staging_ref else None
    if staging is not None and not staging.is_absolute():
        staging = project_root / staging

    bases: list[Path] = []
    if target_spec_dir is not None:
        bases.append(target_spec_dir)
    source_ref = str(state.get("spec_dir") or "").strip()
    if source_ref:
        source = Path(source_ref)
        if not source.is_absolute():
            source = project_root / source
        if source not in bases:
            bases.append(source)
    if staging is not None:
        bases.append(staging)
    bases.append(project_root)

    rows: list[tuple[str, str]] = []
    for raw_item in getattr(node, "context_pack", []) or []:
        file_ref = str(raw_item).split(" ")[0].split("(")[0].rstrip()
        if not file_ref or file_ref.startswith("#"):
            continue
        resolved_ref = file_ref
        if staging is not None:
            resolved_ref = resolved_ref.replace("{staging_dir}", str(staging))
        if target_spec_dir is not None:
            resolved_ref = resolved_ref.replace("{spec_dir}", str(target_spec_dir))
        if resolved_ref.startswith("/"):
            candidates = [Path(resolved_ref)]
        else:
            candidates = [base / resolved_ref for base in bases]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        rows.append((file_ref, str(found) if found is not None else "missing"))
    return rows


# Public recovery helpers shared with the manual phase service.
find_current_run_dir = _find_current_run_dir
failed_automatic_phase_replay = _failed_automatic_phase_replay
resolve_phase_target_spec_dir = _resolve_phase_target_spec_dir
phase_state_updates_for_target = _phase_state_updates_for_target
phase_context_resolution_rows = _phase_context_resolution_rows
classify_run_recovery = _classify_run_recovery
enforce_project_config_compatibility = _enforce_project_config_compatibility
workspace_git_preflight = _workspace_git_preflight
command_display = _command_display
