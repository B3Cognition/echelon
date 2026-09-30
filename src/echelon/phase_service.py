"""Application services for workflow phase inspection and manual replay."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from echelon.strict_json import loads_strict_json
from echelon.spec_service import (
    classify_run_recovery,
    command_display,
    enforce_project_config_compatibility,
    failed_automatic_phase_replay,
    find_current_run_dir,
    phase_context_resolution_rows,
    phase_state_updates_for_target,
    resolve_phase_target_spec_dir,
    workspace_git_preflight,
)
from echelon.ui import banner
from harness.phase_graph import PhaseGraph, load_workspace_phase_graph
from harness.recovery_instruction import RecoveryInstructionError
from harness.squad_state import SquadStateStore, StateAdvanceError
from harness.workflow_validator import validate_deployed_phase_runtime


@dataclass(frozen=True)
class PhaseSummary:
    phase_id: str
    label: str
    phase_type: str


def _load_phase_graph(project_root: Path) -> tuple[PhaseGraph, Path]:
    """Load and validate the deployed Phase A runtime for a workspace."""
    runtime = project_root / ".echelon" / "runtime"
    prose = project_root / ".echelon" / "prosaic" / "subagents"
    definition = runtime / "workflow" / "definition.yaml"
    if not definition.is_file() or not prose.is_dir():
        print(
            "✗ Echelon runtime not installed.\n"
            "  Run: echelon workspace migrate-to-prosaic\n"
            "  Or, for a new workspace: echelon workspace init",
            file=sys.stderr,
        )
        raise SystemExit(1)

    report = validate_deployed_phase_runtime(definition_path=definition)
    if not report.ok:
        print(
            "✗ Echelon Phase A runtime is incompatible with this controller.\n"
            f"{report.format()}\n"
            "  Run: echelon workspace migrate-to-prosaic",
            file=sys.stderr,
        )
        raise SystemExit(1)

    config = project_root / ".echelon" / "config.yml"
    if not config.exists():
        print(
            f"✗ Project not initialized — config not found: {config}\n"
            "  Run: echelon workspace init",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return load_workspace_phase_graph(project_root)


def list_phases(project_root: Path) -> tuple[PhaseSummary, ...]:
    """Return workflow phases available for manual replay."""
    graph, _runtime = _load_phase_graph(project_root)
    return tuple(
        PhaseSummary(
            phase_id=phase_id,
            label=graph.get(phase_id).label or "-",
            phase_type=graph.get(phase_id).type,
        )
        for phase_id in graph.all_phase_ids()
    )


def run_phase(
    project_root: Path,
    phase_id: str,
    *,
    spec_id: str | None = None,
    mode: str | None = None,
    message: str | None = None,
) -> None:
    """Run one explicit workflow phase through the Phase A controller."""
    graph, runtime = _load_phase_graph(project_root)
    known_phases = graph.all_phase_ids()
    if phase_id not in known_phases:
        print(f"✗ Unknown phase id: {phase_id}", file=sys.stderr)
        print("Available phases:", file=sys.stderr)
        for known in known_phases:
            print(f"  - {known}", file=sys.stderr)
        raise SystemExit(1)

    selected_mode = mode or "semi"
    if selected_mode not in {"semi", "banzai", "guided"}:
        print(
            f"✗ echelon phase run: invalid mode {selected_mode!r}; "
            "expected semi, banzai, or guided",
            file=sys.stderr,
        )
        raise SystemExit(1)

    from harness.config import get_full_resolved_config, load_config
    from harness.squad import SquadController
    from harness.squad_provider import SquadCliProvider

    if phase_id in {
        "phase3-plan",
        "phase3-tasks-lexicon",
        "phase3-consensus",
        "phase3-consensus-tasks-lexicon",
    }:
        enforce_project_config_compatibility(project_root)

    workspace_git_preflight(project_root, command_name="echelon phase run")

    run_dir = find_current_run_dir(project_root)
    if run_dir is None:
        print(
            "✗ echelon phase run requires an active spec run. "
            "Start one with: echelon spec run <description>",
            file=sys.stderr,
        )
        raise SystemExit(1)

    state_path = run_dir / "state.json"
    if state_path.exists():
        try:
            current_state = loads_strict_json(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            print(f"✗ Could not read active run state: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
    else:
        current_state = {}
    if not isinstance(current_state, dict):
        print("✗ Active run state must be a JSON object.", file=sys.stderr)
        raise SystemExit(1)

    spec_arg = spec_id or ""
    try:
        failed_replay = failed_automatic_phase_replay(
            current_state,
            phase_id=phase_id,
            spec_arg=spec_arg,
            project_root=project_root,
            run_dir=run_dir,
            graph=graph,
        )
    except (RecoveryInstructionError, ValueError, TypeError) as exc:
        print(f"✗ Invalid failed decision replay authority: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    state_store = SquadStateStore(run_dir)
    loaded_state = state_store.load()
    if failed_replay is not None and loaded_state != current_state:
        print(
            "✗ Failed decision replay authority changed before target setup.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    current_state = loaded_state
    target_spec_dir = resolve_phase_target_spec_dir(
        project_root,
        current_state,
        run_dir,
        spec_arg,
    )
    if spec_arg and target_spec_dir is None:
        print(f"✗ Spec not found for --spec {spec_arg!r}", file=sys.stderr)
        raise SystemExit(1)
    if (
        failed_replay is not None
        and (
            target_spec_dir is None
            or target_spec_dir.resolve() != failed_replay.spec_dir.resolve()
        )
    ):
        print(
            "✗ Failed decision replay target does not match the active spec identity.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    initial_updates = phase_state_updates_for_target(
        project_root,
        current_state,
        target_spec_dir,
        materialize=failed_replay is None,
    )
    if failed_replay is not None:
        initial_updates["spec_id"] = failed_replay.spec_id
        initial_updates["spec_dir"] = failed_replay.spec_dir_ref
        initial_updates["phase_run_source_spec_dir"] = failed_replay.spec_dir_ref
    if initial_updates:
        initial_updates["manual_phase_run"] = True

    node = graph.get(phase_id)
    context_rows = phase_context_resolution_rows(
        node,
        project_root,
        {**current_state, **initial_updates},
        target_spec_dir,
    )
    resolved_count = sum(1 for _, resolved in context_rows if resolved != "missing")
    banner(
        "PHASE RUN",
        [
            ("phase", phase_id),
            ("run", run_dir.name),
            ("mode", selected_mode),
            ("target", str(target_spec_dir) if target_spec_dir else "(none resolved)"),
            (
                "context",
                f"{resolved_count}/{len(context_rows)} resolved"
                if context_rows
                else "(none)",
            ),
        ],
        subtitle="Manual single-phase replay",
    )

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
        state_store=state_store,
        phase_graph=graph,
        ext_dir=runtime,
        project_root=project_root,
        token_budget=token_budget,
        max_iterations=max_iterations,
        squad_dir=run_dir,
    )

    if failed_replay is not None:
        try:
            authorized = state_store.authorize_failed_automatic_decision_for_manual_phase_replay(
                phase_id,
                decision_id=str(failed_replay.decision["id"]),
                expected_state_revision=failed_replay.state_revision,
                v2_automatic_eligible=failed_replay.v2_automatic_eligible,
                expected_spec_id=failed_replay.spec_id,
                expected_spec_dir=failed_replay.spec_dir_ref,
                initial_state_updates=initial_updates,
            )
        except (StateAdvanceError, ValueError, TypeError) as exc:
            print(f"✗ Failed decision replay authority changed: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if not authorized:
            source_phase = str(failed_replay.decision.get("source_phase") or "").strip()
            replay_command = command_display("echelon phase run", [source_phase])
            print(
                "✗ Failed automatic decision can only be retired by its exact "
                f"source replay: {replay_command}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        print(
            "[squad] authorized failed automatic Banzai decision replay: "
            f"{phase_id}",
            flush=True,
        )

    user_message = message or current_state.get("user_message", "")
    try:
        result = controller.run_single_phase(
            phase_id,
            user_message=user_message,
            mode=selected_mode,
            initial_state_updates=initial_updates,
        )
    except StateAdvanceError as exc:
        if failed_replay is None:
            raise
        print(
            f"✗ Failed decision replay authority changed before dispatch: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    finally:
        state_store.clear_failed_automatic_decision_for_manual_phase_replay()

    next_action = (
        "echelon phase run phase1-lexicon"
        if phase_id == "phase1-lexicon-derive" and result.status in {"running", "done"}
        else "echelon spec continue"
    )
    recovery_note = ""
    final_state = state_store.load()
    if result.status == "blocked":
        recovery = classify_run_recovery(final_state, project_root=project_root)
        if recovery.kind in {"manual_recovery", "human_resume", "safe_rewind"} and recovery.command:
            next_action = recovery.command
            recovery_note = recovery.note
    fields = [
        ("phase", result.phase),
        ("artifacts", str(target_spec_dir or run_dir)),
        ("next", next_action),
    ]
    if recovery_note:
        fields.append(("note", recovery_note))

    status_icon = "✓" if result.status in {"running", "done"} else "✗"
    banner(f"{status_icon}  PHASE RUN {result.status.upper()}", fields)
