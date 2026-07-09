"""CLI entry point for python -m harness.

Subcommands:
  run     — run the ralph-loop for a spec (reads HARNESS_* env vars)
  resume  — resume a blocked loop with an answer (reads HARNESS_* env vars)
  gitops  — GitOps operations (find-branch, create-worktree, commit-push, open-pr, merge-pr, local-merge)
  validate-tasks — validate canonical tasks.md rows
  validate-task-progress — reconcile canonical tasks.md progress with state.json
  mark-task-progress — update one canonical tasks.md row and status
  write-progress-integrity — write deterministic progress integrity artifacts
  write-judgment-prepass — write deterministic verify-spec judgment pre-pass artifacts
  assemble-fulfillment-report — assemble final fulfillment report from pre-pass and fallback rows
  apply-task-requirement-mapping — apply deterministic req= metadata mappings
  write-progress-reconciliation-candidates — generate deterministic progress reconciliation candidates
  apply-progress-reconciliation — apply verify-spec task-progress reconciliation
  plan-reopen-gaps — plan deterministic reopen work from fulfillment gaps
  init-verify-spec-run — create verify-spec runtime directory and state.json
  write-codegraph-evidence — write verify-spec CodeGraph evidence artifacts
  write-codegraph-evidence-map — write deterministic requirement-to-CodeGraph map
  write-requirement-audit — write deterministic requirement audit from canonical inventory
  validate-fulfillment-artifacts — validate fulfillment report row-set integrity
  inspect-fulfillment-report — print deterministic fulfillment report metadata JSON
  verify-docs — write deterministic README/CHANGELOG verification report
  migrate-tasks — migrate legacy tasks.md markers to canonical rows
  validate-plan — validate canonical plan.md sections
  migrate-plan — migrate legacy plan.md files to canonical sections

Environment variables for `run`:
  HARNESS_SPEC          required  spec ID (e.g., "012")
  HARNESS_MODE          optional  banzai | semi | guided  (default: semi)
  HARNESS_MAX_OUTER     optional  integer  (default: 5)
  HARNESS_MAX_INNER     optional  integer  (default: 3)
  HARNESS_STRATEGIES    optional  comma-separated strategy IDs  (default: default)
  HARNESS_AUTO_MERGE    optional  true | false  (default: false)
  HARNESS_KILL_LOSERS   optional  true | false  (default: false)
  HARNESS_TOKEN_BUDGET  optional  integer token cap  (default: unlimited)

Environment variables for `resume`:
  HARNESS_SPEC      required  spec ID
  HARNESS_STRATEGY  optional  strategy ID  (default: default)
  HARNESS_ANSWER    required  answer text for the escalation question
"""

from __future__ import annotations

import os
import sys


def _bool_env(key: str, default: bool = False) -> bool:
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


def _run() -> None:
    spec_id = os.environ.get("HARNESS_SPEC", "").strip()
    if not spec_id:
        print("HARNESS_SPEC is required.", file=sys.stderr)
        sys.exit(1)

    mode = os.environ.get("HARNESS_MODE", "semi").strip()
    max_outer = int(os.environ.get("HARNESS_MAX_OUTER", "5"))
    max_inner = int(os.environ.get("HARNESS_MAX_INNER", "3"))
    strategies_csv = os.environ.get("HARNESS_STRATEGIES", "default").strip()
    auto_merge = _bool_env("HARNESS_AUTO_MERGE")
    kill_losers = _bool_env("HARNESS_KILL_LOSERS")
    token_budget_raw = os.environ.get("HARNESS_TOKEN_BUDGET", "").strip()

    # Build a message string that parse_intent can consume.
    parts = [f"spec {spec_id}", f"{mode} mode",
             f"max {max_outer} outer iterations",
             f"max {max_inner} inner iterations"]
    if strategies_csv != "default":
        parts.append(f"strategies={strategies_csv}")
    if auto_merge:
        parts.append("auto_merge")
    if kill_losers:
        parts.append("kill_losers")
    if token_budget_raw:
        parts.append(f"token_budget={token_budget_raw}")
    user_message = " ".join(parts)

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.run_skill import run

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=config.container_cli,
    )

    run(user_message, provider, gitops)


def _resume() -> None:
    spec_id = os.environ.get("HARNESS_SPEC", "").strip()
    strategy_id = os.environ.get("HARNESS_STRATEGY", "default").strip()
    answer = os.environ.get("HARNESS_ANSWER", "").strip()

    if not spec_id:
        print("HARNESS_SPEC is required.", file=sys.stderr)
        sys.exit(1)
    if not answer:
        print("HARNESS_ANSWER is required.", file=sys.stderr)
        sys.exit(1)

    user_message = f"spec {spec_id} strategy {strategy_id} answer: {answer}"

    from harness.config import load_config
    from harness.docker_provider import DockerWorktreeProvider
    from harness.gitops import GitOpsManager
    from harness.skills.resume_skill import resume

    config = load_config()
    gitops = GitOpsManager(config)
    provider = DockerWorktreeProvider(
        buffer_limit_bytes=config.buffer_limit_bytes,
        container_cli=config.container_cli,
    )

    resume(user_message, provider, gitops)


def _validate_tasks() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness validate-tasks <tasks.md>", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.task_validation import TaskValidationError, validate_tasks_file

    tasks_path = Path(sys.argv[2])
    try:
        result = validate_tasks_file(tasks_path)
    except TaskValidationError as e:
        print(f"invalid tasks.md: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: {result.task_count} canonical tasks")


def _validate_task_progress() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python -m harness validate-task-progress <tasks.md> [state.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    import json
    from pathlib import Path

    from harness.task_progress import summarize_task_progress

    tasks_path = Path(sys.argv[2])
    build_state = {}
    if len(sys.argv) >= 4:
        state = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
        if isinstance(state.get("build"), dict):
            build_state = state["build"]

    summary = summarize_task_progress(
        tasks_path.read_text(encoding="utf-8", errors="replace"),
        build_state,
    )
    if not summary.valid:
        print(f"invalid task progress: {'; '.join(summary.errors)}", file=sys.stderr)
        sys.exit(1)

    print(
        f"OK: {summary.completed_tasks}/{summary.total_tasks} tasks complete "
        f"({summary.tasks_completed_pct}%)"
    )


def _mark_task_progress() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness mark-task-progress <tasks.md> <task-id> <status>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.task_progress import TaskProgressError, update_task_progress_markdown

    tasks_path = Path(sys.argv[2])
    task_id = sys.argv[3]
    status = sys.argv[4]

    try:
        updated = update_task_progress_markdown(
            tasks_path.read_text(encoding="utf-8", errors="replace"),
            task_id,
            status,
        )
    except TaskProgressError as exc:
        print(f"could not mark task progress: {exc}", file=sys.stderr)
        sys.exit(1)

    tasks_path.write_text(updated, encoding="utf-8")
    print(f"OK: marked {task_id} as {status.upper()}")


def _write_progress_integrity() -> None:
    if len(sys.argv) < 6:
        print(
            "Usage: python -m harness write-progress-integrity <tasks.md> <state.json> <out.json> <out.md>",
            file=sys.stderr,
        )
        sys.exit(1)

    import json
    from pathlib import Path

    from harness.task_progress import summarize_task_progress

    tasks_path = Path(sys.argv[2])
    state_path = Path(sys.argv[3])
    out_json = Path(sys.argv[4])
    out_md = Path(sys.argv[5])

    state = json.loads(state_path.read_text(encoding="utf-8"))
    build_state = state.get("build") if isinstance(state.get("build"), dict) else {}
    summary = summarize_task_progress(
        tasks_path.read_text(encoding="utf-8", errors="replace"),
        build_state,
    )
    if not summary.valid:
        print(f"invalid task progress: {'; '.join(summary.errors)}", file=sys.stderr)
        sys.exit(1)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "valid": summary.valid,
        "total_tasks": summary.total_tasks,
        "completed_tasks": summary.completed_tasks,
        "tasks_completed_pct": summary.tasks_completed_pct,
        "task_statuses": summary.task_statuses,
        "errors": summary.errors,
    }
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    out_md.write_text(_progress_integrity_markdown(payload), encoding="utf-8")
    print(f"OK: wrote progress integrity to {out_json} and {out_md}")


def _init_verify_spec_run() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness init-verify-spec-run "
            "<project-root> <spec-id> <spec-dir> "
            "[--scope full|scoped] [--scoped-ids ID,ID] "
            "[--base-full-verify-commit SHA] [--strict] [--reconcile] "
            "[--dry-run] [--timestamp YYYYMMDD-HHMMSS]",
            file=sys.stderr,
        )
        sys.exit(1)

    import json
    from pathlib import Path

    from harness.verify_spec_run import init_verify_spec_run

    project_root = Path(sys.argv[2])
    spec_id = sys.argv[3]
    spec_dir = Path(sys.argv[4])
    args = sys.argv[5:]
    verify_scope = "full"
    scoped_ids: list[str] = []
    base_full_verify_commit = ""
    strict = False
    reconcile = False
    dry_run = False
    timestamp = None

    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--scope":
            index += 1
            if index >= len(args):
                print("--scope requires a value", file=sys.stderr)
                sys.exit(1)
            verify_scope = args[index]
        elif arg == "--scoped-ids":
            index += 1
            if index >= len(args):
                print("--scoped-ids requires a value", file=sys.stderr)
                sys.exit(1)
            scoped_ids = args[index].split(",")
        elif arg == "--base-full-verify-commit":
            index += 1
            if index >= len(args):
                print("--base-full-verify-commit requires a value", file=sys.stderr)
                sys.exit(1)
            base_full_verify_commit = args[index]
        elif arg == "--strict":
            strict = True
        elif arg == "--reconcile":
            reconcile = True
        elif arg == "--dry-run":
            dry_run = True
        elif arg == "--timestamp":
            index += 1
            if index >= len(args):
                print("--timestamp requires a value", file=sys.stderr)
                sys.exit(1)
            timestamp = args[index]
        else:
            print(f"unknown init-verify-spec-run option: {arg}", file=sys.stderr)
            sys.exit(1)
        index += 1

    result = init_verify_spec_run(
        project_root=project_root,
        spec_id=spec_id,
        spec_dir=spec_dir,
        verify_scope=verify_scope,
        scoped_ids=scoped_ids,
        base_full_verify_commit=base_full_verify_commit,
        strict=strict,
        reconcile=reconcile,
        dry_run=dry_run,
        timestamp=timestamp,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


def _write_judgment_prepass() -> None:
    if len(sys.argv) != 4:
        print(
            "Usage: python -m harness write-judgment-prepass <spec-dir> <verify-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.judgment_prepass import write_judgment_prepass

    verify_run_dir = Path(sys.argv[3]).resolve()
    _require_inputs(
        [
            verify_run_dir / "canonical-requirements.json",
            verify_run_dir / "implementation-map.md",
        ]
    )
    result = write_judgment_prepass(
        spec_dir=Path(sys.argv[2]).resolve(),
        verify_run_dir=verify_run_dir,
    )
    print(
        f"OK: wrote judgment pre-pass to {result.json_path} "
        f"(mechanical={result.mechanical_count}, fallback={result.fallback_count})"
    )


def _assemble_fulfillment_report() -> None:
    if len(sys.argv) not in {6, 7}:
        print(
            "Usage: python -m harness assemble-fulfillment-report "
            "<canonical-requirements.json> <judgment-prepass.json> "
            "<fallback-report.md> <out-report.md> [state.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.judgment_prepass import assemble_fulfillment_report

    state_path = Path(sys.argv[6]).resolve() if len(sys.argv) == 7 else None
    _require_inputs(
        [
            Path(sys.argv[2]).resolve(),
            Path(sys.argv[3]).resolve(),
            Path(sys.argv[4]).resolve(),
        ]
    )
    assemble_fulfillment_report(
        canonical_inventory_path=Path(sys.argv[2]).resolve(),
        judgment_prepass_path=Path(sys.argv[3]).resolve(),
        fallback_report_path=Path(sys.argv[4]).resolve(),
        output_report_path=Path(sys.argv[5]).resolve(),
        state_path=state_path,
    )
    print(f"OK: assembled fulfillment report at {Path(sys.argv[5]).resolve()}")


def _validate_fulfillment_artifacts() -> None:
    if len(sys.argv) not in {4, 5}:
        print(
            "Usage: python -m harness validate-fulfillment-artifacts "
            "<requirement-audit.md> <fulfillment-report.md> "
            "[canonical-requirements.json]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from kernel.fulfillment import validate_fulfillment_artifacts

    result = validate_fulfillment_artifacts(
        requirement_audit_path=Path(sys.argv[2]),
        fulfillment_report_path=Path(sys.argv[3]),
        canonical_inventory_path=Path(sys.argv[4]) if len(sys.argv) == 5 else None,
    )
    if result.ok:
        print(
            "OK: fulfillment artifact row set is valid "
            f"(audit={result.audit_count}, report={result.report_count})"
        )
        return
    if result.missing_in_report:
        print(
            "missing_in_report: " + ", ".join(result.missing_in_report),
            file=sys.stderr,
        )
    if result.extra_in_report:
        print(
            "extra_in_report: " + ", ".join(result.extra_in_report),
            file=sys.stderr,
        )
    sys.exit(1)


def _progress_integrity_markdown(payload: dict[str, object]) -> str:
    statuses = payload.get("task_statuses")
    rows = []
    if isinstance(statuses, dict):
        for task_id, status in sorted(statuses.items()):
            rows.append(f"| {task_id} | {status} |")
    rows_text = "\n".join(rows) if rows else "| (none) | (none) |"
    return (
        "# Progress Integrity\n\n"
        f"Valid: {payload['valid']}\n\n"
        f"Completed: {payload['completed_tasks']}/{payload['total_tasks']} "
        f"({payload['tasks_completed_pct']}%)\n\n"
        "| Task | Status |\n"
        "| --- | --- |\n"
        f"{rows_text}\n"
    )


def _apply_progress_reconciliation() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness apply-progress-reconciliation <tasks.md> <candidate.json> <out-dir> [--dry-run]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.progress_reconciliation import reconcile_progress

    tasks_path = Path(sys.argv[2])
    candidate_path = Path(sys.argv[3])
    out_dir = Path(sys.argv[4])
    dry_run = "--dry-run" in sys.argv[5:]
    unknown = [arg for arg in sys.argv[5:] if arg != "--dry-run"]
    if unknown:
        print(f"Unknown apply-progress-reconciliation option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    result = reconcile_progress(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "progress-reconciliation-plan.json",
        out_plan_md=out_dir / "progress-reconciliation-plan.md",
        out_applied_json=None
        if dry_run
        else out_dir / "progress-reconciliation-applied.json",
        out_applied_md=None
        if dry_run
        else out_dir / "progress-reconciliation-applied.md",
        dry_run=dry_run,
    )
    if dry_run:
        print(
            "OK: progress reconciliation dry-run wrote "
            f"{out_dir / 'progress-reconciliation-plan.md'}"
        )
        return
    print(f"OK: progress reconciliation applied {result.applied_count} task updates")


def _write_progress_reconciliation_candidates() -> None:
    if len(sys.argv) != 6:
        print(
            "Usage: python -m harness write-progress-reconciliation-candidates "
            "<tasks.md> <fulfillment-report.md> <fulfillment-gaps.md> <out.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.progress_reconciliation import write_progress_reconciliation_candidates

    payload = write_progress_reconciliation_candidates(
        tasks_path=Path(sys.argv[2]),
        fulfillment_report_path=Path(sys.argv[3]),
        fulfillment_gaps_path=Path(sys.argv[4]),
        out_path=Path(sys.argv[5]),
    )
    print(
        "OK: wrote progress reconciliation candidates "
        f"({len(payload['safe_task_updates'])} safe, "
        f"{len(payload['ambiguous_task_matches'])} ambiguous)"
    )


def _apply_task_requirement_mapping() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness apply-task-requirement-mapping <tasks.md> <candidate.json> <out-dir> [--dry-run]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.task_requirement_mapping import apply_task_requirement_mapping

    tasks_path = Path(sys.argv[2])
    candidate_path = Path(sys.argv[3])
    out_dir = Path(sys.argv[4])
    dry_run = "--dry-run" in sys.argv[5:]
    unknown = [arg for arg in sys.argv[5:] if arg != "--dry-run"]
    if unknown:
        print(f"Unknown apply-task-requirement-mapping option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    result = apply_task_requirement_mapping(
        tasks_path=tasks_path,
        candidate_path=candidate_path,
        out_plan_json=out_dir / "task-requirement-map-plan.json",
        out_plan_md=out_dir / "task-requirement-map-plan.md",
        out_applied_json=None if dry_run else out_dir / "task-requirement-map-applied.json",
        out_applied_md=None if dry_run else out_dir / "task-requirement-map-applied.md",
        dry_run=dry_run,
    )
    if dry_run:
        print(
            "OK: task requirement mapping dry-run wrote "
            f"{out_dir / 'task-requirement-map-plan.md'}"
        )
        return
    print(f"OK: applied {result.applied_count} task requirement mappings")


def _plan_reopen_gaps() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness plan-reopen-gaps <fulfillment-gaps.md> <tasks.md> <out-dir> [reopen-*.md ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.reopen_planner import plan_reopen_gaps

    gaps_path = Path(sys.argv[2])
    tasks_path = Path(sys.argv[3])
    out_dir = Path(sys.argv[4])
    existing_reopen_paths = [Path(arg) for arg in sys.argv[5:]]

    result = plan_reopen_gaps(
        gaps_path=gaps_path,
        tasks_path=tasks_path,
        existing_reopen_paths=existing_reopen_paths,
        out_plan_json=out_dir / "reopen-plan.json",
        out_plan_md=out_dir / "reopen-plan.md",
    )
    print(
        "OK: reopen gap plan wrote "
        f"{out_dir / 'reopen-plan.md'} "
        f"({result.status}, {len(result.clusters)} clusters)"
    )


def _write_codegraph_evidence() -> None:
    if len(sys.argv) < 5:
        print(
            "Usage: python -m harness write-codegraph-evidence <project-root> <verify-run-dir> <spec-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.codegraph_evidence import (
        CodeGraphEvidenceError,
        write_codegraph_evidence,
    )

    verify_run_dir = Path(sys.argv[3])
    try:
        result = write_codegraph_evidence(
            project_root=Path(sys.argv[2]),
            verify_run_dir=verify_run_dir,
            spec_dir=Path(sys.argv[4]),
        )
    except CodeGraphEvidenceError as exc:
        _stamp_verify_spec_state(verify_run_dir, {"structural_evidence": "degraded"})
        print(f"CodeGraph evidence degraded; see {exc}", file=sys.stderr)
        sys.exit(1)

    _stamp_verify_spec_state(verify_run_dir, {"structural_evidence": "ready"})
    print(f"OK: wrote CodeGraph evidence to {result.analysis_path}")


def _stamp_verify_spec_state(verify_run_dir: "Path", updates: dict[str, object]) -> None:
    import json

    state_path = verify_run_dir / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.update(updates)
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_canonical_requirements() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python -m harness write-canonical-requirements <spec-dir> <verify-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.canonical_requirements import write_canonical_requirements

    result = write_canonical_requirements(
        spec_dir=Path(sys.argv[2]),
        verify_run_dir=Path(sys.argv[3]),
    )
    print(
        "OK: wrote canonical requirements to "
        f"{result.json_path} and {result.markdown_path} "
        f"({result.count} requirements)"
    )


def _write_requirement_audit() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python -m harness write-requirement-audit <verify-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.canonical_requirements import write_requirement_audit

    result = write_requirement_audit(verify_run_dir=Path(sys.argv[2]))
    print(
        "OK: wrote requirement audit to "
        f"{result.audit_path} ({result.count} requirements)"
    )


def _write_codegraph_evidence_map() -> None:
    if len(sys.argv) < 7:
        print(
            "Usage: python -m harness write-codegraph-evidence-map "
            "<requirement-audit.md> <codegraph-analysis.json> <tasks.md> "
            "<out.json> <out.md> [coverage-map.md]",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.codegraph_evidence_mapper import write_codegraph_evidence_map

    analysis_path = Path(sys.argv[3])
    out_json_path = Path(sys.argv[5])
    out_md_path = Path(sys.argv[6])
    verify_run_dir = out_json_path.parent
    if not analysis_path.is_file() and _verify_spec_state_value(
        verify_run_dir, "structural_evidence"
    ) == "degraded":
        _write_skipped_codegraph_evidence_map(
            out_json_path=out_json_path,
            out_md_path=out_md_path,
            analysis_path=analysis_path,
        )
        _stamp_verify_spec_state(
            verify_run_dir,
            {"codegraph_evidence_map": "skipped_degraded_codegraph"},
        )
        print(
            "OK: skipped degraded CodeGraph evidence map "
            f"({out_json_path} and {out_md_path})"
        )
        return

    _require_inputs(
        [
            Path(sys.argv[2]),
            analysis_path,
            Path(sys.argv[4]),
        ]
    )
    result = write_codegraph_evidence_map(
        requirement_audit_path=Path(sys.argv[2]),
        codegraph_analysis_path=analysis_path,
        tasks_path=Path(sys.argv[4]),
        out_json_path=out_json_path,
        out_md_path=out_md_path,
        coverage_map_path=Path(sys.argv[7]) if len(sys.argv) >= 8 else None,
    )
    print(
        "OK: wrote CodeGraph evidence map to "
        f"{result.out_json_path} and {result.out_md_path} "
        f"({result.total_requirements} requirements)"
    )


def _verify_spec_state_value(verify_run_dir: "Path", key: str) -> str | None:
    import json

    try:
        state = json.loads((verify_run_dir / "state.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(state, dict):
        return None
    value = state.get(key)
    return str(value) if value is not None else None


def _write_skipped_codegraph_evidence_map(
    *,
    out_json_path: "Path",
    out_md_path: "Path",
    analysis_path: "Path",
) -> None:
    import json

    payload = {
        "schema_version": 1,
        "status": "skipped_degraded_codegraph",
        "reason": "CodeGraph evidence was degraded and codegraph-analysis.json is absent.",
        "source_files": {
            "codegraph_analysis": str(analysis_path),
        },
        "summary": {
            "total_requirements": 0,
            "fallback_requirement_ids": [],
        },
        "requirements": [],
    }
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    out_md_path.write_text(
        "# CodeGraph Evidence Map\n\n"
        "CodeGraph evidence was degraded and `codegraph-analysis.json` is absent.\n",
        encoding="utf-8",
    )


def _verify_docs() -> None:
    if len(sys.argv) != 4:
        print(
            "Usage: python -m harness verify-docs <worktree-path> <spec-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.docs_verifier import write_docs_verification_report

    result = write_docs_verification_report(
        worktree_path=Path(sys.argv[2]).resolve(),
        spec_dir=Path(sys.argv[3]).resolve(),
    )
    message = (
        f"docs verification {result.verdict}: wrote {result.report_path} "
        f"({result.blocking_findings} blocking finding(s))"
    )
    if result.verdict == "PASS":
        print(f"OK: {message}")
        return
    print(message, file=sys.stderr)
    sys.exit(1)


def _require_inputs(paths: list[Path]) -> None:
    missing = [path for path in paths if not path.is_file()]
    if missing:
        print(f"missing required input: {missing[0]}", file=sys.stderr)
        sys.exit(2)


def _migrate_tasks() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness migrate-tasks <tasks.md> [--write]", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.task_migration import migrate_tasks_markdown
    from kernel.task_contract import validate_tasks_markdown

    tasks_path = Path(sys.argv[2])
    write = "--write" in sys.argv[3:]
    unknown = [arg for arg in sys.argv[3:] if arg != "--write"]
    if unknown:
        print(f"Unknown migrate-tasks option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    migrated = migrate_tasks_markdown(
        tasks_path.read_text(encoding="utf-8", errors="replace")
    )
    result = validate_tasks_markdown(migrated)
    if not result.valid:
        print(f"invalid migrated tasks.md: {'; '.join(result.errors)}", file=sys.stderr)
        sys.exit(1)

    if write:
        tasks_path.write_text(migrated, encoding="utf-8")
        print(f"OK: migrated {result.task_count} canonical tasks")
        return

    print(migrated, end="")


def _validate_plan() -> None:
    usage = "Usage: python -m harness validate-plan <plan.md>"
    if len(sys.argv) < 3:
        print(usage, file=sys.stderr)
        sys.exit(1)
    if sys.argv[2] in {"-h", "--help"}:
        print(usage)
        sys.exit(0)

    from pathlib import Path

    from harness.plan_validation import PlanValidationError, validate_plan_file

    plan_path = Path(sys.argv[2])
    try:
        validate_plan_file(plan_path)
    except PlanValidationError as e:
        print(f"invalid plan.md: {e}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"invalid plan.md: cannot read {plan_path}: {e}", file=sys.stderr)
        sys.exit(1)

    print("OK: canonical plan.md")


def _migrate_plan() -> None:
    if len(sys.argv) < 3:
        print("Usage: python -m harness migrate-plan <plan.md> [--write]", file=sys.stderr)
        sys.exit(1)

    from pathlib import Path

    from harness.plan_migration import migrate_plan_markdown
    from kernel.plan_contract import validate_plan_markdown

    plan_path = Path(sys.argv[2])
    write = "--write" in sys.argv[3:]
    unknown = [arg for arg in sys.argv[3:] if arg != "--write"]
    if unknown:
        print(f"Unknown migrate-plan option: {unknown[0]!r}", file=sys.stderr)
        sys.exit(1)

    migrated = migrate_plan_markdown(
        plan_path.read_text(encoding="utf-8", errors="replace")
    )
    result = validate_plan_markdown(migrated)
    if not result.valid:
        print(f"invalid migrated plan.md: {'; '.join(result.errors)}", file=sys.stderr)
        sys.exit(1)

    if write:
        plan_path.write_text(migrated, encoding="utf-8")
        print("OK: migrated canonical plan.md")
        return

    print(migrated, end="")


def _inspect_fulfillment_report() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python -m harness inspect-fulfillment-report <spec-dir> [current-commit]",
            file=sys.stderr,
        )
        sys.exit(1)

    import json
    from pathlib import Path

    from kernel.fulfillment import (
        fulfillment_has_blocking_gaps,
        fulfillment_report_is_current,
        latest_fulfillment_report,
        read_fulfillment_metadata,
    )

    spec_dir = Path(sys.argv[2])
    current_commit = sys.argv[3].strip() if len(sys.argv) >= 4 else ""
    report = latest_fulfillment_report(spec_dir)
    if report is None:
        payload = {
            "exists": False,
            "report_path": None,
            "metadata": {},
            "verified_commit": None,
            "verified_at": None,
            "verify_scope": None,
            "current_commit": current_commit or None,
            "is_current": False if current_commit else None,
            "has_blocking_gaps": None,
            "has_strict_blocking_gaps": None,
        }
        print(json.dumps(payload, sort_keys=True))
        return

    metadata = _json_safe(read_fulfillment_metadata(report))
    verified_commit = metadata.get("verified_commit")
    verify_scope = metadata.get("verify_scope")
    verified_at = metadata.get("verified_at")
    payload = {
        "exists": True,
        "report_path": str(report),
        "metadata": metadata,
        "verified_commit": verified_commit if isinstance(verified_commit, str) else None,
        "verified_at": str(verified_at) if verified_at is not None else None,
        "verify_scope": verify_scope if isinstance(verify_scope, str) else None,
        "current_commit": current_commit or None,
        "is_current": fulfillment_report_is_current(report, current_commit=current_commit)
        if current_commit
        else None,
        "has_blocking_gaps": fulfillment_has_blocking_gaps(report),
        "has_strict_blocking_gaps": fulfillment_has_blocking_gaps(report, strict=True),
    }
    print(json.dumps(payload, sort_keys=True))


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)

    subcommand = sys.argv[1]

    if subcommand == "run":
        _run()
    elif subcommand == "resume":
        _resume()
    elif subcommand == "gitops":
        from harness.skills.gitops_skill import main as gitops_main
        sys.exit(gitops_main(sys.argv[2:]))
    elif subcommand == "validate-tasks":
        _validate_tasks()
    elif subcommand == "validate-task-progress":
        _validate_task_progress()
    elif subcommand == "mark-task-progress":
        _mark_task_progress()
    elif subcommand == "write-progress-integrity":
        _write_progress_integrity()
    elif subcommand == "apply-task-requirement-mapping":
        _apply_task_requirement_mapping()
    elif subcommand == "write-progress-reconciliation-candidates":
        _write_progress_reconciliation_candidates()
    elif subcommand == "apply-progress-reconciliation":
        _apply_progress_reconciliation()
    elif subcommand == "plan-reopen-gaps":
        _plan_reopen_gaps()
    elif subcommand == "init-verify-spec-run":
        _init_verify_spec_run()
    elif subcommand == "write-canonical-requirements":
        _write_canonical_requirements()
    elif subcommand == "write-requirement-audit":
        _write_requirement_audit()
    elif subcommand == "write-judgment-prepass":
        _write_judgment_prepass()
    elif subcommand == "assemble-fulfillment-report":
        _assemble_fulfillment_report()
    elif subcommand == "validate-fulfillment-artifacts":
        _validate_fulfillment_artifacts()
    elif subcommand == "write-codegraph-evidence":
        _write_codegraph_evidence()
    elif subcommand == "write-codegraph-evidence-map":
        _write_codegraph_evidence_map()
    elif subcommand == "inspect-fulfillment-report":
        _inspect_fulfillment_report()
    elif subcommand == "verify-docs":
        _verify_docs()
    elif subcommand == "migrate-tasks":
        _migrate_tasks()
    elif subcommand == "validate-plan":
        _validate_plan()
    elif subcommand == "migrate-plan":
        _migrate_plan()
    else:
        print(
            f"Unknown subcommand: {subcommand!r}. Use 'run', 'resume', 'gitops', "
            "'validate-tasks', 'validate-task-progress', 'mark-task-progress', "
            "'write-progress-integrity', 'apply-task-requirement-mapping', "
            "'write-progress-reconciliation-candidates', "
            "'apply-progress-reconciliation', 'plan-reopen-gaps', "
            "'init-verify-spec-run', 'write-canonical-requirements', "
            "'write-requirement-audit', 'write-judgment-prepass', "
            "'assemble-fulfillment-report', 'validate-fulfillment-artifacts', "
            "'write-codegraph-evidence', "
            "'write-codegraph-evidence-map', 'inspect-fulfillment-report', "
            "'verify-docs', 'migrate-tasks', 'validate-plan', or 'migrate-plan'.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
