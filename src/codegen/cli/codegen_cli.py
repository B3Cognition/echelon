"""
codegen_cli.py — CLI entry point for codegen toolchain.
Spec 018 F3 T-014, F4 T-018.

Commands:
  extract-constitution [path] [--force]
  anchor <path>                           -- F4: extract + inject anchoring constraints
  gate --phase GATE --language python --files ...  -- SOAR phase gate decision
  run [--intent ...] [--target ...] [--resume]     -- full pipeline run
  status [--state-file ...]               -- show current pipeline state
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

try:
    from codegen.extract.constitution_extractor import (
        ConstitutionExtractor,
        ExtractionFailedError,
    )
    from codegen.extract.constitution_writer import ConstitutionWriter
    from codegen.epmem.recorder import Tier0GateRecorder
    from codegen.anchor.anchor_extractor import AnchorExtractor
    from codegen.bridge.soar_bridge import SOARBridge, SOARBridgeModel
    from codegen.pipeline.phase_gate import PhaseGateRunner
    from codegen.pipeline.pipeline_engine import PipelineEngine
    from codegen.memory.mempalace_reader import MemPalaceReader
    from codegen.memory.mempalace_writer import MemPalaceWriter
except ImportError:
    from src.codegen.extract.constitution_extractor import (  # type: ignore[no-redef]
        ConstitutionExtractor,
        ExtractionFailedError,
    )
    from src.codegen.extract.constitution_writer import ConstitutionWriter  # type: ignore[no-redef]
    from src.codegen.epmem.recorder import Tier0GateRecorder  # type: ignore[no-redef]
    from src.codegen.anchor.anchor_extractor import AnchorExtractor  # type: ignore[no-redef]
    from src.codegen.bridge.soar_bridge import SOARBridge, SOARBridgeModel  # type: ignore[no-redef]
    from src.codegen.pipeline.phase_gate import PhaseGateRunner  # type: ignore[no-redef]
    from src.codegen.pipeline.pipeline_engine import PipelineEngine  # type: ignore[no-redef]
    from src.codegen.memory.mempalace_reader import MemPalaceReader  # type: ignore[no-redef]
    from src.codegen.memory.mempalace_writer import MemPalaceWriter  # type: ignore[no-redef]

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> None:
    """
    Main entry point for the codegen CLI.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when None).
    """
    parser = argparse.ArgumentParser(prog="codegen")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show SOAR engine messages and pipeline logging on stderr",
    )
    parser.add_argument(
        "--anchor",
        metavar="PATH",
        default=None,
        help="Anchor path for style extraction (F4 Anchoring Mode)",
    )
    sub = parser.add_subparsers(dest="command")

    # --extract-constitution command
    ec = sub.add_parser(
        "extract-constitution",
        help="Auto-extract constitution from a codebase",
    )
    ec.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Target codebase path (default: current directory)",
    )
    ec.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing constitution.md (shows diff, writes backup)",
    )

    # anchor subcommand (F4 T-018)
    anc = sub.add_parser(
        "anchor",
        help="Extract anchor style constraints and inject into SOAR WM state",
    )
    anc.add_argument(
        "path",
        help="Anchor codebase path to analyze for style conventions",
    )
    anc.add_argument(
        "--state-file",
        metavar="PATH",
        default="codegen-state.json",
        help="Path to codegen-state.json for writing anchoring_constraints (default: codegen-state.json)",
    )

    # gate subcommand — SOAR phase gate decision
    gate_cmd = sub.add_parser(
        "gate",
        help="Run SOAR phase gate at a phase transition (outputs JSON GateDecision)",
    )
    gate_cmd.add_argument(
        "--phase",
        required=True,
        help="Current pipeline phase (RE|DECOMPOSE|IMPLEMENT|GATE|TEST|DELIVER)",
    )
    gate_cmd.add_argument(
        "--language",
        required=True,
        help="Detected source language (python|typescript|javascript|go|java)",
    )
    gate_cmd.add_argument(
        "--files",
        nargs="*",
        default=[],
        metavar="FILE",
        help="Source files produced in this phase",
    )
    gate_cmd.add_argument(
        "--state-file",
        metavar="PATH",
        default="codegen-state.json",
        help="Path to codegen-state.json (default: codegen-state.json)",
    )
    gate_cmd.add_argument(
        "--task-id",
        metavar="ID",
        default=None,
        help="Optional task identifier for EPMEM",
    )
    gate_cmd.add_argument(
        "--epmem-file",
        metavar="PATH",
        default=None,
        help="Append SOAR audit record to this file after the gate call (optional)",
    )

    # run subcommand — full pipeline run
    run_cmd = sub.add_parser(
        "run",
        help="Start or resume full pipeline run",
    )
    run_cmd.add_argument(
        "--intent",
        metavar="TEXT",
        default=None,
        help="Pipeline intent description (required when not resuming)",
    )
    run_cmd.add_argument(
        "--target",
        metavar="PATH",
        default=None,
        help="Target path for brownfield RE",
    )
    run_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing codegen-state.json",
    )
    run_cmd.add_argument(
        "--language",
        metavar="LANG",
        default="python",
        help="Source language (default: python)",
    )
    run_cmd.add_argument(
        "--wing",
        metavar="WING",
        default=None,
        help="MemPalace wing (project name) — enables RE phase requirement lookup",
    )
    run_cmd.add_argument(
        "--state-file",
        metavar="PATH",
        default="codegen-state.json",
        help="Path to codegen-state.json (default: codegen-state.json)",
    )

    # status subcommand — show pipeline state
    status_cmd = sub.add_parser(
        "status",
        help="Show current pipeline state",
    )
    status_cmd.add_argument(
        "--state-file",
        metavar="PATH",
        default="codegen-state.json",
        help="Path to codegen-state.json (default: codegen-state.json)",
    )

    # requirements subcommand group (Spec 025 FR-RM)
    req_cmd = sub.add_parser("requirements", help="Requirements memory management")
    req_sub = req_cmd.add_subparsers(dest="requirements_command")

    req_mine = req_sub.add_parser("mine", help="Mine requirements from a source into MemPalace")
    req_mine.add_argument(
        "source",
        metavar="SOURCE",
        help="Path to a markdown spec file or directory to mine",
    )
    req_mine.add_argument(
        "--wing",
        metavar="WING",
        default=None,
        help="MemPalace wing (project name). Defaults to source directory name.",
    )
    req_mine.add_argument(
        "--glob",
        metavar="PATTERN",
        default="**/*.md",
        help="Glob pattern for directory mining (default: **/*.md)",
    )

    req_search = req_sub.add_parser("search", help="Search mined requirements in MemPalace")
    req_search.add_argument("query", metavar="QUERY", help="Search query")
    req_search.add_argument("--wing", metavar="WING", required=True, help="MemPalace wing to search")
    req_search.add_argument("--room", metavar="ROOM", default=None, help="Optional room filter")
    req_search.add_argument("--n", metavar="N", type=int, default=5, help="Number of results")

    req_mark = req_sub.add_parser(
        "mark-delivered",
        help="Mark a functional requirement as delivered in MemPalace (FR-003)",
    )
    req_mark.add_argument(
        "requirement_id",
        metavar="REQ_ID",
        help="Requirement ID to mark (e.g. FR-NEL-003)",
    )
    req_mark.add_argument(
        "--wing",
        metavar="WING",
        required=True,
        help="MemPalace wing scoping the lookup",
    )
    req_mark.add_argument(
        "--status",
        metavar="STATUS",
        default="delivered",
        help="Status to set (default: delivered)",
    )

    # memory subcommand group (T-032, T-035)
    mem_cmd = sub.add_parser("memory", help="Memory store management")
    mem_sub = mem_cmd.add_subparsers(dest="memory_command")

    # memory status (T-032 / FR-OBS-002)
    mem_status = mem_sub.add_parser("status", help="Show memory store statistics")
    mem_status.add_argument(
        "--state-file",
        metavar="PATH",
        default="codegen-state.json",
        help="Path to codegen-state.json (default: codegen-state.json)",
    )
    mem_status.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to memory-config.yml",
    )

    # memory repair (T-035 / NFR-MIG-007)
    mem_repair = mem_sub.add_parser("repair", help="Repair a corrupt memory store")
    mem_repair.add_argument(
        "--store",
        choices=["epmem", "smem"],
        required=True,
        help="Which store to repair: epmem or smem",
    )
    mem_repair.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to memory-config.yml",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
        stream=sys.stderr,
    )

    # Global --anchor flag: run anchor extraction in addition to any subcommand
    if args.anchor is not None and args.command != "anchor":
        _run_anchor(args.anchor, state_file="codegen-state.json")

    if args.command == "extract-constitution":
        _run_extract_constitution(args.path, args.force)
    elif args.command == "anchor":
        _run_anchor(args.path, state_file=args.state_file)
    elif args.command == "gate":
        _run_gate(args)
    elif args.command == "run":
        _run_pipeline(args)
    elif args.command == "status":
        _run_status(args)
    elif args.command == "requirements":
        _run_requirements(args)
    elif args.command == "memory":
        _run_memory(args)
    else:
        if args.anchor is None:
            parser.print_help()


def _run_anchor(path: str, state_file: str = "codegen-state.json") -> None:
    """
    Execute the anchor extraction + WME injection pipeline step (F4 T-018).

    Args:
        path: Anchor codebase path to analyze.
        state_file: Path to codegen-state.json to write anchoring_constraints.
    """
    extractor = AnchorExtractor()
    constraints = extractor.analyze(path)

    if not constraints:
        logger.warning("[anchor] No constraints extracted from '%s' — skipping injection.", path)
        print(f"WARNING: No anchoring constraints extracted from '{path}'.")
        return

    # Inject into SOAR WM state (Model B)
    bridge = SOARBridge(
        wm_state_file=Path(state_file),
        model=SOARBridgeModel.B,
    )
    bridge.inject_anchoring_constraint_wmes(constraints)

    # Also write directly to codegen-state.json anchoring_constraints field
    state_path = Path(state_file)
    state: dict = {}
    if state_path.exists():
        try:
            import json as _json
            state = _json.loads(state_path.read_text())
        except Exception:  # noqa: BLE001
            pass
    state["anchoring_constraints"] = [
        {
            "constraint_id": c.constraint_id,
            "dimension": c.dimension,
            "constraint_text": c.constraint_text,
            "source_path": c.source_path,
            "run_id": c.run_id,
        }
        for c in constraints
    ]
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2))
    except OSError as exc:
        logger.warning("[anchor] Could not write state to %s: %s", state_file, exc)

    # Record EPMEM event (INV-004)
    recorder = Tier0GateRecorder()
    event = recorder.record_anchoring_constraints_injected(constraints, anchor_path=path)

    print(
        f"Anchoring constraints extracted: {len(constraints)} constraints from '{path}', "
        f"event_id={event.event_id}"
    )


def _run_extract_constitution(path: str, force: bool) -> None:
    """
    Execute the extract-constitution pipeline step.

    Args:
        path:  Target codebase path.
        force: Whether to overwrite existing constitution.md.
    """
    start = time.monotonic()
    extractor = ConstitutionExtractor()
    try:
        draft = extractor.run(path, force=force)
    except ExtractionFailedError as exc:
        print(f"ERROR: Extraction failed: {exc}")
        return

    elapsed = time.monotonic() - start
    if elapsed > 60.0:
        print("ERROR: Extraction exceeded 60-second budget. No file written.")
        return

    writer = ConstitutionWriter()
    try:
        writer.write(draft, force=force)
    except FileExistsError as exc:
        print(f"ERROR: {exc}")
        return

    recorder = Tier0GateRecorder()
    event = recorder.record_constitution_extracted(draft)
    print(
        f"Constitution extracted: {len(draft.rules)} rules, "
        f"confidence={draft.overall_confidence:.2f}, "
        f"event_id={event.event_id}"
    )


def _append_epmem(epmem_path: Path, gate: "PhaseGateRunner", runner: "PhaseGateRunner") -> None:  # type: ignore[name-defined]
    """Append one gate audit record to the EPMEM log file (creates if absent)."""
    bridge = runner._bridge
    audit = bridge.export_audit_record() if bridge else {}
    record = {
        "gate_ts": gate.timestamp_ms,
        "phase": gate.phase,
        "decision": gate.decision,
        "operator": gate.operator,
        "psi_score": gate.psi_score,
        "psi_weighted": gate.psi_weighted,
        "violations_blocked": gate.violations_blocked,
        "violations": [
            {"cq_isc_id": v.get("cq_isc_id") if isinstance(v, dict) else getattr(v, "cq_isc_id", str(v)),
             "message": v.get("message") if isinstance(v, dict) else getattr(v, "message", ""),
             "file": v.get("file") if isinstance(v, dict) else getattr(v, "file", ""),
             "line": v.get("line") if isinstance(v, dict) else getattr(v, "line", 0)}
            for v in (gate.violations or [])
        ],
        "soar_model": gate.soar_model,
        "soar_pid": gate.soar_pid,
        "wme_log": audit.get("wme_log", []),
        "epmem_records": audit.get("records", []),
    }
    try:
        if epmem_path.exists():
            existing = json.loads(epmem_path.read_text())
            if not isinstance(existing, list):
                existing = [existing]
        else:
            existing = []
        existing.append(record)
        epmem_path.write_text(json.dumps(existing, indent=2))
        logger.info("[EPMEM] Appended gate record to %s (%d total)", epmem_path, len(existing))
    except OSError as exc:
        logger.warning("[EPMEM] Could not write %s: %s", epmem_path, exc)


def _run_gate(args: argparse.Namespace) -> None:
    """
    Execute a SOAR phase gate decision.

    Outputs JSON GateDecision to stdout.
    Exit codes:
      0 = ADVANCE or DELIVER
      1 = RETRY
      2 = ESCALATE

    Args:
        args: Parsed CLI arguments with phase, language, files, state_file, task_id.
    """
    state_file = Path(args.state_file)
    files = [Path(f) for f in (args.files or [])]

    runner = PhaseGateRunner(state_file=state_file, verbose=args.verbose)
    try:
        gate = runner.run_gate(
            phase=args.phase,
            files=files,
            language=args.language,
            task_id=getattr(args, "task_id", None),
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(2)

    # Print SOAR model header
    soar_label = (
        f"SOAR Model A | PID {gate.soar_pid}"
        if gate.soar_model == "A" and gate.soar_pid
        else "SOAR Model B"
    )
    print(
        f"[{soar_label}] Phase: {gate.phase} -> decision: {gate.decision} "
        f"| Psi={gate.psi_score:.2f} | violations_blocked={gate.violations_blocked}",
        file=sys.stderr,
    )

    # JSON output to stdout
    print(gate.to_json())

    # Append EPMEM audit record only when --epmem-file is explicitly passed
    if getattr(args, "epmem_file", None):
        _append_epmem(Path(args.epmem_file), gate, runner)

    # Exit code by decision
    if gate.decision in ("ADVANCE", "DELIVER"):
        sys.exit(0)
    elif gate.decision == "RETRY":
        sys.exit(1)
    else:
        # ESCALATE
        sys.exit(2)


def _run_pipeline(args: argparse.Namespace) -> None:
    """
    Start or resume a full pipeline run.

    Args:
        args: Parsed CLI arguments with intent, target, resume, language, state_file.
    """
    state_file = Path(args.state_file)
    engine = PipelineEngine(state_file=state_file, verbose=args.verbose)

    if args.resume:
        try:
            state = engine.resume()
            print(f"[codegen run] Resuming pipeline_id={state.pipeline_id} at phase={state.current_phase}")
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        if not args.intent:
            print("ERROR: --intent is required when starting a new pipeline.", file=sys.stderr)
            sys.exit(1)
        mode = "brownfield" if args.target else "greenfield"
        state = engine.initialize(
            intent=args.intent,
            mode=mode,
            target_path=args.target,
        )
        print(
            f"[codegen run] Initialized pipeline_id={state.pipeline_id} "
            f"mode={mode} soar_model={state.soar_model}"
        )

    # RE phase — search MemPalace for relevant requirements (if wing provided)
    wing = getattr(args, "wing", None)
    if wing and state.current_phase == "RE" and not args.resume:
        print(f"[codegen RE] Searching MemPalace for requirements — wing={wing}...")
        re_context = engine.run_re_phase(intent=args.intent or "", wing=wing)
        if re_context:
            print(re_context)
        else:
            print(f"[codegen RE] No requirements found in MemPalace for wing={wing}.")
            print(f"[codegen RE] Run: codegen requirements mine <spec> --wing {wing}")

    print(f"[codegen run] Current phase: {state.current_phase}")
    print(f"[codegen run] Phases completed: {state.phases_completed}")
    print(f"[codegen run] Psi score: {state.psi_score:.3f} | tier1_gate: {state.tier1_gate}")
    print("[codegen run] Use `codegen gate --phase <PHASE> ...` at each phase transition.")


def _run_status(args: argparse.Namespace) -> None:
    """
    Show current pipeline state summary.

    Args:
        args: Parsed CLI arguments with state_file.
    """
    state_file = Path(args.state_file)
    if not state_file.exists():
        print(f"No pipeline state found at {state_file}.")
        print("Run `codegen run --intent <intent>` to start a pipeline.")
        return

    engine = PipelineEngine(state_file=state_file)
    try:
        state = engine.get_state()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Could not read state: {exc}", file=sys.stderr)
        sys.exit(1)

    soar_label = (
        f"Model A (PID {state.soar_pid})"
        if state.soar_model == "A" and state.soar_pid
        else f"Model {state.soar_model}"
    )

    print("=" * 56)
    print(" CODEGEN — Pipeline Status")
    print("=" * 56)
    print(f" Pipeline ID  : {state.pipeline_id}")
    print(f" Mode         : {state.mode}")
    print(f" Intent       : {state.intent}")
    print(f" Current phase: {state.current_phase}")
    print(f" Phases done  : {', '.join(state.phases_completed) or 'none'}")
    print("-" * 56)
    print(f" Psi score    : {state.psi_score:.3f} (threshold 0.70)")
    print(f" tier1 gate   : {state.tier1_gate}")
    print(f" Violations   : {state.violations_blocked} blocked")
    print(f" Imasses      : {state.impasse_count}")
    print(f" SOAR         : {soar_label}")
    print(f" Updated      : {state.updated_at}")
    print("=" * 56)


# ---------------------------------------------------------------------------
# T-032, T-035: memory subcommand group
# ---------------------------------------------------------------------------

def _run_requirements(args: argparse.Namespace) -> None:
    """Dispatch requirements subcommands (Spec 025 FR-RM)."""
    cmd = getattr(args, "requirements_command", None)
    if cmd == "mine":
        _run_requirements_mine(args)
    elif cmd == "search":
        _run_requirements_search(args)
    elif cmd == "mark-delivered":
        _run_requirements_mark_delivered(args)
    else:
        print("Usage: codegen requirements mine <source> [--wing WING] [--glob PATTERN]")
        print("       codegen requirements search <query> --wing WING [--room ROOM] [--n N]")
        print("       codegen requirements mark-delivered <REQ_ID> --wing WING [--status STATUS]")


def _run_requirements_mine(args: argparse.Namespace) -> None:
    """
    Mine requirements from a markdown file or directory into MemPalace.

    FR-RM-001: Parse by requirement ID.
    FR-RM-002: Write each requirement as a MemPalace drawer.
    FR-RM-003: Print MineResult summary.
    """
    try:
        from codegen.memory.requirements_miner import RequirementsMiner
    except ImportError:
        from src.codegen.memory.requirements_miner import RequirementsMiner  # type: ignore

    source = Path(args.source)
    if not source.exists():
        print(f"ERROR: Source not found: {source}", file=sys.stderr)
        sys.exit(1)

    wing = args.wing or (source.stem if source.is_file() else source.name)
    miner = RequirementsMiner(wing=wing)

    print(f"[codegen] Mining requirements from: {source}")
    print(f"[codegen] MemPalace wing: {wing}")

    if source.is_file():
        result = miner.mine_file(source)
    else:
        result = miner.mine_directory(source, glob=args.glob)

    print()
    print("=" * 52)
    print(" Requirements Mine — Complete")
    print("=" * 52)
    print(f"  Source   : {source}")
    print(f"  Wing     : {wing}")
    print(f"  Total    : {result.total} requirements found")
    print(f"  Written  : {result.written} drawers written to MemPalace")
    print(f"  Skipped  : {result.skipped} (MemPalace write returned None)")
    print(f"  Failed   : {result.failed}")
    if result.errors:
        print()
        print("  Errors:")
        for err in result.errors[:5]:
            print(f"    - {err}")
    print("=" * 52)
    print()
    print("  Next step:")
    print(f"    codegen run --intent \"your intent\" --wing {wing}")
    print("    # Pipeline will retrieve relevant requirements at RE phase")

    sys.exit(0 if result.failed == 0 else 1)


def _run_requirements_search(args: argparse.Namespace) -> None:
    """
    Search mined requirements in MemPalace.
    FR-RM-005: Search by semantic query filtered by wing/room.
    """
    reader = MemPalaceReader(wing=args.wing)
    result = reader.search(query=args.query, room=args.room, n_results=args.n)

    if not result.available:
        print("ERROR: MemPalace not available. Run: bash scripts/install.sh", file=sys.stderr)
        sys.exit(1)

    print(f"[codegen] Searching MemPalace — wing={args.wing} room={args.room or 'all'}")
    print(f"          Query: {args.query!r}")
    print(f"          Found: {len(result.drawers)} results")
    print()

    if not result.drawers:
        print("  (No matching requirements found)")
        return

    for i, drawer in enumerate(result.drawers, 1):
        req_label = drawer.req_id or drawer.drawer_id
        print(f"  {i}. [{req_label}] (room: {drawer.room}, dist: {drawer.distance:.3f})")
        print(f"     {drawer.content[:200]}")
        print()


def _run_requirements_mark_delivered(args: argparse.Namespace) -> None:
    """
    Mark a functional requirement as delivered in MemPalace.
    FR-003, FR-004, FR-005.
    """
    import uuid as _uuid

    req_id = args.requirement_id
    wing = args.wing
    status = getattr(args, "status", "delivered")
    room = "functional-requirements"

    reader = MemPalaceReader(wing=wing)
    drawer = reader.lookup_drawer_by_req_id(req_id, room=room)

    if drawer is None:
        print(
            f"ERROR: {req_id} not found in wing={wing} / room={room}",
            file=sys.stderr,
        )
        sys.exit(1)

    writer = MemPalaceWriter(wing=wing, run_id=str(_uuid.uuid4()))
    updated = writer.backfill_status(drawer_ids=[drawer.drawer_id], status=status)

    if updated == 0:
        print(
            f"ERROR: Failed to update status for {req_id} (drawer_id={drawer.drawer_id})",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[codegen] {req_id} marked {status!r}")
    print(f"  drawer_id : {drawer.drawer_id}")
    print(f"  wing      : {wing}")
    print(f"  room      : {room}")


def _run_memory(args: argparse.Namespace) -> None:
    """Dispatch memory subcommands."""
    if not hasattr(args, "memory_command") or args.memory_command is None:
        print("Usage: codegen memory {status,repair}")
        print("  memory status  — show memory store statistics")
        print("  memory repair  — repair a corrupt memory store")
        return

    if args.memory_command == "status":
        _run_memory_status(args)
    elif args.memory_command == "repair":
        _run_memory_repair(args)


def _run_memory_status(args: argparse.Namespace) -> None:
    """
    T-032: `codegen memory status` — display memory store statistics.

    Shows EPMEM episode count, SMEM accumulated pattern count, embedding model,
    and last memory_stats from the most recent codegen-state.json.

    FR-OBS-002, FR-OBS-008, AC-F6-003
    """
    try:
        from codegen.memory.config import MemoryConfigLoader
    except ImportError:
        from src.codegen.memory.config import MemoryConfigLoader  # type: ignore

    config_path = Path(args.config) if getattr(args, "config", None) else None
    cfg = MemoryConfigLoader.load(config_path)

    # Read last memory_stats from state file if available
    state_file = Path(getattr(args, "state_file", "codegen-state.json"))
    memory_stats = {}
    if state_file.exists():
        try:
            import json
            raw = json.loads(state_file.read_text())
            memory_stats = raw.get("memory_stats", {})
        except Exception:
            pass

    # Count EPMEM episodes
    epmem_count = memory_stats.get("epmem_episodes_total", 0)
    if epmem_count == 0 and cfg.epmem_db_path.exists():
        try:
            import sqlite3
            with sqlite3.connect(str(cfg.epmem_db_path)) as conn:
                row = conn.execute("SELECT COUNT(*) FROM epmem_episodes").fetchone()
                epmem_count = row[0] if row else 0
        except Exception:
            epmem_count = "error"

    # Count SMEM accumulated patterns (non-CQ-ISC, i.e. patterns written by SmemPatternWriter)
    smem_count = memory_stats.get("smem_patterns_accumulated", "n/a")

    # MemPalace drawer count
    mempalace_count = memory_stats.get("mempalace_drawers_written", "n/a")

    # Last reindex date
    last_reindex = memory_stats.get("last_reindex_date", "never")

    print("=" * 56)
    print(" CODEGEN — Memory Status")
    print("=" * 56)
    print(f" EPMEM episodes          : {epmem_count}")
    print(f"   db path               : {cfg.epmem_db_path}")
    print(f"   ceiling               : {cfg.max_epmem_episodes}")
    print(f" SMEM accumulated        : {smem_count}")
    print(f"   db path               : {cfg.smem_db_path}")
    print(f" MemPalace drawers       : {mempalace_count}")
    print(f" Embedding model         : {cfg.embedding_model_tag}")
    print(f" Last reindex            : {last_reindex}")
    print(f" Write failures          : {memory_stats.get('mempalace_write_failures', 0)}")
    print("=" * 56)


def _run_memory_repair(args: argparse.Namespace) -> None:
    """
    T-035: `codegen memory repair --store <epmem|smem>` — repair corrupt store.

    Attempts WAL replay, runs PRAGMA integrity_check. If corrupt and .bak
    exists, restores from backup.

    NFR-MIG-007, NFR-REL-005, NFR-REL-006
    """
    try:
        from codegen.memory.config import MemoryConfigLoader
        from codegen.memory.repair import repair_store
    except ImportError:
        from src.codegen.memory.config import MemoryConfigLoader  # type: ignore
        from src.codegen.memory.repair import repair_store  # type: ignore

    config_path = Path(args.config) if getattr(args, "config", None) else None
    cfg = MemoryConfigLoader.load(config_path)

    db_path = cfg.epmem_db_path if args.store == "epmem" else cfg.smem_db_path
    ok, message = repair_store(db_path, store_name=args.store)
    print(message)
    sys.exit(0 if ok else 1)
