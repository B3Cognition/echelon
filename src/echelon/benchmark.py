"""Experimental benchmark definitions for EGR-063 artifact-quality evaluation."""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from echelon.commit_messages import EchelonCommitMetadata, build_echelon_commit_message


@dataclass(frozen=True)
class BenchmarkFixture:
    id: str
    name: str
    prompt: str


@dataclass(frozen=True)
class BenchmarkVariant:
    id: str
    label: str
    phases: tuple[str, ...]


@dataclass(frozen=True)
class BenchmarkCommandPlan:
    fixture_id: str
    variant_id: str
    phase_ids: tuple[str, ...]
    commands: tuple[tuple[str, ...], ...]
    artifact_only: bool = False


@dataclass(frozen=True)
class BenchmarkRunRecord:
    variant_id: str
    status: str
    phase_a_dispatches: int = 0
    why_failures: int = 0
    build_dispatches: int = 0
    retries: int = 0
    blocked_states: int = 0
    verification_failures: int = 0
    fulfillment_gaps: int = 0
    elapsed_seconds: float = 0.0
    cost_usd: float = 0.0
    issue_url: str = ""
    run_id: str = ""
    spec_id: str = ""
    delivery_run_id: str = ""
    failure_kind: str = ""

    def score_tuple(self) -> tuple[int, int, int, int, int, int, float]:
        status_penalty = 0 if self.status == "complete" else 1
        return (
            status_penalty,
            self.fulfillment_gaps,
            self.verification_failures,
            self.blocked_states,
            self.retries,
            self.build_dispatches,
            self.elapsed_seconds,
        )


_FIXTURES = (
    BenchmarkFixture(
        id="tiny-notes",
        name="Tiny Notes",
        prompt=(
            "Build a tiny notes app. Users can create, list, and delete notes. "
            "Empty note text is rejected with a clear validation message. The app "
            "shows an empty state when there are no notes, provides local persistence "
            "between reloads, supports keyboard use for the primary create/delete "
            "flow, and includes at least one automated test for validation or "
            "persistence."
        ),
    ),
)

_VARIANTS = (
    BenchmarkVariant("baseline", "Baseline", ()),
    BenchmarkVariant("constitution", "Constitution cleanse", ("phase-exp-constitution-quality",)),
    BenchmarkVariant(
        "constitution-tasks",
        "Constitution and tasks cleanse",
        ("phase-exp-constitution-quality", "phase-exp-tasks-quality"),
    ),
    BenchmarkVariant(
        "constitution-tasks-adrs",
        "Constitution, tasks, and ADR cleanse",
        (
            "phase-exp-constitution-quality",
            "phase-exp-tasks-quality",
            "phase-exp-adr-quality",
        ),
    ),
)


def list_fixtures() -> list[BenchmarkFixture]:
    return list(_FIXTURES)


def list_variants() -> list[BenchmarkVariant]:
    return list(_VARIANTS)


def _fixture(fixture_id: str) -> BenchmarkFixture:
    for fixture in _FIXTURES:
        if fixture.id == fixture_id:
            return fixture
    raise ValueError(f"Unknown benchmark fixture: {fixture_id}")


def _variant(variant_id: str) -> BenchmarkVariant:
    for variant in _VARIANTS:
        if variant.id == variant_id:
            return variant
    raise ValueError(f"Unknown benchmark variant: {variant_id}")


def plan_variant_commands(
    fixture_id: str,
    variant_id: str,
    *,
    artifact_only: bool = False,
) -> BenchmarkCommandPlan:
    fixture = _fixture(fixture_id)
    variant = _variant(variant_id)
    commands: list[tuple[str, ...]] = [
        ("echelon", "spec", "run", "--mode", "banzai", fixture.prompt)
    ]
    commands.extend(
        (
            "echelon",
            "phase",
            "run",
            phase_id,
            "--spec",
            "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
            "--mode",
            "banzai",
        )
        for phase_id in variant.phases
    )
    if not artifact_only:
        commands.append(
            (
                "echelon",
                "delivery",
                "run",
                "RESOLVE_SPEC_ID_FROM_CURRENT_RUN",
                "mode=banzai",
            )
        )
    return BenchmarkCommandPlan(
        fixture_id=fixture.id,
        variant_id=variant.id,
        phase_ids=variant.phases,
        commands=tuple(commands),
        artifact_only=artifact_only,
    )


def summarize_records(records: list[BenchmarkRunRecord]) -> dict:
    if not records:
        return {"best_variant": None, "variants": {}}
    best = min(records, key=lambda record: record.score_tuple())
    return {
        "best_variant": best.variant_id,
        "variants": {record.variant_id: asdict(record) for record in records},
    }


def write_summary(output_dir: Path, records: list[BenchmarkRunRecord]) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_records(records)
    json_path = output_dir / "summary.json"
    md_path = output_dir / "summary.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lines = [
        "# Benchmark Summary",
        "",
        "| Variant | Status | Spec | Delivery | Phase A | WHY Fails | Dispatches | Retries | Blocks | Verify Failures | Fulfillment Gaps | Seconds |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| {record.variant_id} | {record.status} | {record.spec_id or '-'} | "
            f"{record.delivery_run_id or '-'} | {record.phase_a_dispatches} | "
            f"{record.why_failures} | {record.build_dispatches} | {record.retries} | "
            f"{record.blocked_states} | {record.verification_failures} | "
            f"{record.fulfillment_gaps} | {record.elapsed_seconds:.1f} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


CommandRunner = Callable[[tuple[str, ...]], int]


def _default_runner(command: tuple[str, ...]) -> int:
    return subprocess.run(command, check=False).returncode


def _git(
    project_root: Path,
    *args: str,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=project_root,
        check=False,
        text=True,
        capture_output=capture_output,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _current_squad_state(project_root: Path) -> tuple[Path | None, dict[str, Any]]:
    current = project_root / "runs" / ".current"
    if not current.exists():
        return None, {}
    run_id = current.read_text(encoding="utf-8", errors="replace").strip()
    if not run_id:
        return None, {}
    run_dir = project_root / "runs" / run_id
    return run_dir, _read_json(run_dir / "state.json")


def _delivery_state(project_root: Path, spec_id: str) -> tuple[Path | None, dict[str, Any]]:
    if not spec_id:
        return None, {}
    marker = project_root / "runs" / f".current-build-{spec_id}"
    if not marker.exists():
        return None, {}
    build_id = marker.read_text(encoding="utf-8", errors="replace").strip()
    if not build_id:
        return None, {}
    state_dir = project_root / "runs" / build_id / "state"
    state_file = state_dir / "default.json"
    if not state_file.exists():
        candidates = sorted(state_dir.glob("*.json"))
        state_file = candidates[0] if candidates else state_file
    return project_root / "runs" / build_id, _read_json(state_file)


def _count_why_failures(squad_state: dict[str, Any]) -> int:
    scores = squad_state.get("quality_scores")
    if not isinstance(scores, list):
        return 0
    return sum(1 for item in scores if isinstance(item, dict) and item.get("pass") is False)


def _phase_a_dispatches(squad_state: dict[str, Any]) -> int:
    counts = squad_state.get("phase_dispatch_counts")
    if not isinstance(counts, dict):
        return 0
    return sum(value for value in counts.values() if isinstance(value, int))


def _verification_failures(delivery_state: dict[str, Any]) -> int:
    last_verify = delivery_state.get("last_verify_result")
    if isinstance(last_verify, dict):
        explicit = last_verify.get("verification_failures")
        if isinstance(explicit, int):
            return explicit

    failures = 0
    iteration_log = delivery_state.get("iteration_log")
    if isinstance(iteration_log, list):
        for item in iteration_log:
            if not isinstance(item, dict):
                continue
            verify = item.get("verify") or item.get("verify_result") or item.get("last_verify_result")
            if isinstance(verify, dict) and str(verify.get("status") or "").lower() in {"failed", "fail"}:
                failures += 1
    return failures


def _fulfillment_gaps(delivery_state: dict[str, Any]) -> int:
    last_verify = delivery_state.get("last_verify_result")
    if isinstance(last_verify, dict):
        explicit = last_verify.get("fulfillment_gaps")
        if isinstance(explicit, int):
            return explicit
    explicit = delivery_state.get("fulfillment_gaps")
    return explicit if isinstance(explicit, int) else 0


def collect_benchmark_record(
    project_root: Path,
    variant_id: str,
    *,
    status: str,
    retries: int = 0,
    elapsed_seconds: float = 0.0,
    failure_kind: str = "",
) -> BenchmarkRunRecord:
    _squad_dir, squad_state = _current_squad_state(project_root)
    spec_id = str(squad_state.get("spec_id") or "")
    _build_dir, delivery_state = _delivery_state(project_root, spec_id)

    squad_blocked = str(squad_state.get("status") or "").lower() == "blocked"
    delivery_blocked = str(delivery_state.get("status") or "").lower() == "blocked"
    blocked_states = int(status == "failed") + int(squad_blocked) + int(delivery_blocked)

    return BenchmarkRunRecord(
        variant_id=variant_id,
        status=status,
        phase_a_dispatches=_phase_a_dispatches(squad_state),
        why_failures=_count_why_failures(squad_state),
        build_dispatches=int(delivery_state.get("outer_iter") or 0),
        retries=retries,
        blocked_states=blocked_states,
        verification_failures=_verification_failures(delivery_state),
        fulfillment_gaps=_fulfillment_gaps(delivery_state),
        elapsed_seconds=elapsed_seconds,
        cost_usd=float(squad_state.get("cost_usd") or 0.0),
        run_id=str(squad_state.get("run_id") or ""),
        spec_id=spec_id,
        delivery_run_id=str(delivery_state.get("run_id") or ""),
        failure_kind=failure_kind,
    )


def latest_summary_path(project_root: Path) -> Path | None:
    summaries = sorted((project_root / "runs" / "benchmarks").glob("*/*/summary.json"))
    return summaries[-1] if summaries else None


def load_summary(path: Path) -> dict[str, Any]:
    summary_path = path / "summary.json" if path.is_dir() else path
    return _read_json(summary_path)


def _mapping_score_tuple(record: dict[str, Any]) -> tuple[int, int, int, int, int, int, float]:
    status_penalty = 0 if record.get("status") == "complete" else 1
    return (
        status_penalty,
        int(record.get("fulfillment_gaps") or 0),
        int(record.get("verification_failures") or 0),
        int(record.get("blocked_states") or 0),
        int(record.get("retries") or 0),
        int(record.get("build_dispatches") or 0),
        float(record.get("elapsed_seconds") or 0.0),
    )


def load_saved_scorecard(project_root: Path) -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = {}
    summaries = sorted((project_root / "runs" / "benchmarks").glob("*/*/summary.json"))
    for summary_path in summaries:
        summary = load_summary(summary_path)
        summary_variants = summary.get("variants")
        if not isinstance(summary_variants, dict):
            continue
        for variant_id, record in summary_variants.items():
            if not isinstance(record, dict):
                continue
            enriched = dict(record)
            enriched["summary_path"] = str(summary_path)
            variants[variant_id] = enriched

    if not variants:
        return {"best_variant": None, "variants": {}}

    best_variant = min(variants, key=lambda variant_id: _mapping_score_tuple(variants[variant_id]))
    return {"best_variant": best_variant, "variants": variants}


def baseline_reset_commands(baseline_ref: str) -> tuple[tuple[str, ...], ...]:
    return (
        ("git", "reset", "--hard", baseline_ref),
        ("git", "clean", "-fd", "-e", "runs/benchmarks/"),
    )


def baseline_snapshot_commands() -> tuple[tuple[str, ...], ...]:
    return (
        (
            "git",
            "add",
            "-u",
            "--",
            ".",
            ":(exclude)runs",
            ":(exclude).harness-build-status.json",
        ),
        (
            "git",
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "|",
            "git",
            "add",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
        ),
        ("git", "commit", "-m", "chore: snapshot workspace before benchmark"),
    )


def _is_benchmark_snapshot_excluded(path: str) -> bool:
    normalized = path.strip("/")
    return (
        normalized == "runs"
        or normalized.startswith("runs/")
        or normalized == ".harness-build-status.json"
    )


def _stage_benchmark_baseline(project_root: Path) -> bool:
    tracked_files = _git(project_root, "ls-files", "-z", capture_output=True)
    if tracked_files.returncode != 0:
        return False
    if tracked_files.stdout:
        tracked = _git(
            project_root,
            "add",
            "-u",
            "--",
            ".",
            ":(exclude)runs",
            ":(exclude).harness-build-status.json",
        )
        if tracked.returncode != 0:
            return False

    untracked = _git(
        project_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        capture_output=True,
    )
    if untracked.returncode != 0:
        return False
    paths = [
        path
        for path in untracked.stdout.split("\0")
        if path and not _is_benchmark_snapshot_excluded(path)
    ]
    if not paths:
        return True

    added = _git(project_root, "add", "--", *paths)
    return added.returncode == 0


def snapshot_benchmark_baseline(project_root: Path) -> str:
    inside = _git(project_root, "rev-parse", "--is-inside-work-tree", capture_output=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise RuntimeError("benchmark requires a Git workspace before it can snapshot a baseline")

    if not _stage_benchmark_baseline(project_root):
        raise RuntimeError("could not stage benchmark baseline snapshot")

    has_head = _git(project_root, "rev-parse", "--verify", "HEAD", capture_output=True).returncode == 0
    has_staged_changes = _git(project_root, "diff", "--cached", "--quiet").returncode != 0
    if not has_head or has_staged_changes:
        message = build_echelon_commit_message(
            "chore: snapshot workspace before benchmark",
            EchelonCommitMetadata(origin="benchmark", action="baseline-snapshot"),
        )
        commit = _git(
            project_root,
            "-c",
            "user.name=Echelon Benchmark",
            "-c",
            "user.email=echelon-benchmark@example.invalid",
            "commit",
            "-m",
            message,
        )
        if commit.returncode != 0:
            raise RuntimeError("could not commit benchmark baseline snapshot")

    ref = _git(project_root, "rev-parse", "--verify", "HEAD", capture_output=True)
    if ref.returncode != 0:
        raise RuntimeError("could not resolve benchmark baseline snapshot")
    return ref.stdout.strip()


def variant_execution_commands(
    plan: BenchmarkCommandPlan,
    baseline_ref: str,
) -> tuple[tuple[str, ...], ...]:
    reset_commands = baseline_reset_commands(baseline_ref)
    return reset_commands + plan.commands + reset_commands


def run_benchmark_variant(
    project_root: Path,
    fixture_id: str,
    variant_id: str,
    *,
    baseline_ref: str | None = None,
    runner: CommandRunner | None = None,
    timestamp: str | None = None,
    artifact_only: bool = False,
) -> Path:
    plan = plan_variant_commands(fixture_id, variant_id, artifact_only=artifact_only)
    run = runner or _default_runner
    resolved_baseline_ref = baseline_ref or snapshot_benchmark_baseline(project_root)

    status = "complete"
    retries = 0
    failure_kind = ""
    started = time.monotonic()
    output_dir = project_root / "runs" / "benchmarks" / f"{timestamp or _timestamp()}-{fixture_id}" / variant_id
    output_dir.mkdir(parents=True, exist_ok=True)

    def run_one(command: tuple[str, ...], kind: str) -> bool:
        nonlocal status, retries, failure_kind
        exit_code = run(command)
        if exit_code != 0:
            status = "failed"
            retries += 1
            failure_kind = kind
            return False
        return True

    for reset_command in baseline_reset_commands(resolved_baseline_ref):
        if not run_one(reset_command, "baseline_reset"):
            break

    if status == "complete" and not run_one(plan.commands[0], "spec_run"):
        pass

    _squad_dir, squad_state = _current_squad_state(project_root)
    spec_id = str(squad_state.get("spec_id") or "")
    if status == "complete" and str(squad_state.get("status") or "").lower() == "blocked":
        status = "failed"
        retries += 1
        failure_kind = "spec_run_blocked"
    if status == "complete" and not spec_id:
        status = "failed"
        retries += 1
        failure_kind = "spec_id_missing"

    if status == "complete":
        phase_commands = plan.commands[1:] if artifact_only else plan.commands[1:-1]
        for phase_command in phase_commands:
            command = tuple(spec_id if part == "RESOLVE_SPEC_ID_FROM_CURRENT_RUN" else part for part in phase_command)
            if not run_one(command, "cleanse_phase"):
                break

    if status == "complete" and not artifact_only:
        delivery_command = tuple(
            spec_id if part == "RESOLVE_SPEC_ID_FROM_CURRENT_RUN" else part for part in plan.commands[-1]
        )
        run_one(delivery_command, "delivery_run")

    elapsed = time.monotonic() - started

    for reset_command in baseline_reset_commands(resolved_baseline_ref):
        run(reset_command)

    record = collect_benchmark_record(
        project_root,
        variant_id,
        status=status,
        retries=retries,
        elapsed_seconds=elapsed,
        failure_kind=failure_kind,
    )
    write_summary(output_dir, [record])
    return output_dir
