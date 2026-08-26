#!/usr/bin/env python3
"""SUE Auto — autonomic pipeline orchestrator over the five SUE tools.

One command runs a named profile of tiers (v1 challenge, v2 consensus, v3
reproducibility measurement, auto-selected dialectic drills, j-graph), then
writes a single consolidated dossier beside the spec with a fix-ready summary.
Diagnose only: it never edits specs and never dispatches echelon.

Model policy (measured 2026-07-20): dialogue tiers default to Sonnet 5;
the v3 measurement defaults to the CLI's default model — Sonnet is not
measurement-grade for graph extraction (SR 0.163 vs 0.454 on identical text).

Design: docs/superpowers/specs/2026-07-20-sue-auto-orchestrator-design.md
"""
from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _load(name: str):
    path = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module


v1 = _load("sue_challenge")
v2 = _load("sue_consensus")
v3 = _load("sue_reproducibility")
dial = _load("sue_dialectic")
jg = _load("sue_jgraph")

REPORT_FILENAME = "sue-dossier.md"
JSON_FILENAME = "sue-dossier.json"

DIALOGUE_MODEL_CMD = "claude --model claude-sonnet-5"

V3_PASSES = 2
READERS = 3
DRILL_TURN_BUDGET = 7
V3_CHUNK = 20


@dataclass(frozen=True)
class Profile:
    tiers: tuple
    drill_cap: int


@dataclass(frozen=True)
class CallBudget:
    logical_calls: int
    max_provider_attempts: int


PROFILES = {
    "lite": Profile(tiers=("v1",), drill_cap=0),
    "deep": Profile(tiers=("v2", "v3", "drills"), drill_cap=3),
    "forensic": Profile(tiers=("v2", "v3", "jgraph", "drills"), drill_cap=8),
}


def plan_calls(
    profile_name: str, unit_count: int, drill_cap: int | None = None
) -> int:
    """Maximum logical calls before corrective retries."""
    profile = PROFILES[profile_name]
    calls = 0
    for tier in profile.tiers:
        if tier == "v1":
            calls += 2
        elif tier == "v2":
            calls += READERS * 2 + 2
        elif tier == "v3":
            calls += READERS * max(1, math.ceil(unit_count / V3_CHUNK)) * V3_PASSES
        elif tier == "jgraph":
            calls += READERS
        elif tier == "drills":
            effective_cap = profile.drill_cap if drill_cap is None else drill_cap
            calls += effective_cap * DRILL_TURN_BUDGET
    return calls


def plan_budget(
    profile_name: str, unit_count: int, drill_cap: int | None = None
) -> CallBudget:
    """Bound both logical calls and physical provider attempts.

    Every SUE logical call permits at most one corrective retry, so the
    provider-attempt bound is exactly twice the logical-call plan.
    """
    logical = plan_calls(profile_name, unit_count, drill_cap=drill_cap)
    return CallBudget(
        logical_calls=logical,
        max_provider_attempts=logical * 2,
    )


# ── Drill selection (pure; zero model calls) ─────────────────────────────────

_EUTHYPHRO_KEYS = ("what does", "what is", "define", "mean")
_MENO_KEYS = ("verify", "recognize", "criterion")
_PHILEBUS_KEYS = ("how many", "how long", "at most", "limit", "bound")
_REPUBLIC_KEYS = ("who ", "role", "permitted")


def choose_lens(verdict: str, question: str) -> str:
    """Defect class -> lens, per the measured lens/defect table."""
    if verdict == "CONTRADICTED":
        return "parmenides"
    q = question.lower()
    if any(k in q for k in _EUTHYPHRO_KEYS):
        return "euthyphro"
    if any(k in q for k in _MENO_KEYS):
        return "meno"
    if any(k in q for k in _PHILEBUS_KEYS):
        return "philebus"
    if any(k in q for k in _REPUBLIC_KEYS):
        return "republic"
    return "theaetetus"


_UNIT_FAMILY_LENS = {"NFR": "philebus", "ERR": "sophist", "AC": "theaetetus"}


def lens_for_unit(unit_id: str) -> str:
    family = unit_id.rsplit("-", 1)[0]
    return _UNIT_FAMILY_LENS.get(family, "euthyphro")


def select_drills(stable_findings: list, stable_low: list, cap: int) -> list:
    """Select findings, preserving distinct questions on the same target."""
    drills: list = []
    v2_targets: set = set()
    for index, finding in enumerate(stable_findings, start=1):
        if len(drills) >= cap:
            break
        target = finding["target"]
        source_id = finding.get("id") or f"V2-F{index:03d}"
        v2_targets.add(target)
        drills.append({
            "lens": choose_lens(finding["verdict"], finding["question"]),
            "seed": finding["question"],
            "target": target,
            "source": "v2-stable",
            "source_id": source_id,
        })
    for unit in stable_low:
        if len(drills) >= cap:
            break
        if unit in v2_targets:
            continue
        drills.append({
            "lens": lens_for_unit(unit),
            "seed": f"the exact meaning and obligations of {unit}",
            "target": unit,
            "source": "v3-stable-low",
            "source_id": f"V3-{unit}",
        })
    return drills


# ── v2 report parsing (anchored to sue_consensus.render_report's format) ─────

_STABLE_HEAD_RE = re.compile(
    r"^### (\d+)\. \[(CONTRADICTED|UNANSWERABLE)\] \(support (\d+)\) (.*\S)\s*$"
)
_TARGET_RE = re.compile(r"^- \*\*Target:\*\* (.*\S)\s*$")


def parse_stable_findings(report_text: str) -> list:
    findings: list = []
    in_stable = False
    current: dict | None = None
    for line in report_text.splitlines():
        if line.startswith("## "):
            in_stable = line.strip() == "## Stable findings"
            continue
        if not in_stable:
            continue
        head = _STABLE_HEAD_RE.match(line)
        if head:
            current = {
                "id": f"V2-F{int(head.group(1)):03d}",
                "verdict": head.group(2),
                "support": int(head.group(3)),
                "question": head.group(4),
                "target": "",
            }
            findings.append(current)
            continue
        if current is not None:
            target = _TARGET_RE.match(line)
            if target:
                current["target"] = target.group(1)
    return findings


# ── Dossier rendering ────────────────────────────────────────────────────────


def render_dossier(ctx: dict) -> str:
    lines: list = []
    lines.append("# SUE Dossier")
    lines.append("")
    lines.append(f"- **Specification:** {ctx['spec_path']}")
    lines.append(f"- **Run date:** {ctx['run_date']}")
    lines.append(f"- **Profile:** {ctx['profile']}")
    lines.append(f"- **Dialogue model:** {ctx['models']['dialogue']}")
    lines.append(f"- **Measurement model:** {ctx['models']['measure']}")
    if ctx["models"].get("requested"):
        lines.append(f"- **Requested model:** {ctx['models']['requested']}")
    if ctx["models"].get("reasoning_effort"):
        lines.append(
            f"- **Reasoning effort:** {ctx['models']['reasoning_effort']}"
        )
    lines.append("")
    lines.append("## Tier outcomes")
    lines.append("")
    for tier in ctx["tiers"]:
        status = tier["status"]
        suffix = f" (exit {tier['exit_code']})" if status == "failed" else ""
        if status == "not_run":
            suffix = f" ({tier.get('reason', 'not run')})"
        lines.append(f"- {tier['tier']}: {status}{suffix}")
    lines.append("")

    # Fix-ready summary FIRST: severity-ranked, pasteable into
    # `echelon spec change` descriptions.
    lines.append("## Fix-ready summary")
    lines.append("")
    fixed_targets: set = set()
    entries = 0
    for drill in ctx.get("drills") or []:
        terminal = drill.get("terminal_state") or ""
        if terminal.startswith("APORIA"):
            lines.append(
                f"- {terminal} — {drill['lens']} drill on {drill['target']}: "
                f"{drill['seed']} ({drill.get('artifact_markdown') or drill.get('artifact_json')})"
            )
            fixed_targets.add(drill["target"])
            entries += 1
    for verdict in ("CONTRADICTED", "UNANSWERABLE"):
        for finding in ctx.get("stable_findings") or []:
            if finding["verdict"] != verdict:
                continue
            lines.append(
                f"- [{verdict}] {finding['target']} "
                f"(support {finding['support']}): {finding['question']} "
                "(socratic-consensus.md)"
            )
            fixed_targets.add(finding["target"])
            entries += 1
    for unit in ctx.get("stable_low") or []:
        if unit in fixed_targets:
            continue
        lines.append(
            f"- stable-low unit {unit} — interpretations reliably diverge "
            "(semantic-reproducibility.md fracture lines)"
        )
        entries += 1
    if not entries:
        lines.append("Nothing above the severity floor.")
    lines.append("")

    if ctx.get("stable_findings"):
        lines.append("## v2 stable findings")
        lines.append("")
        lines.append("| Target | Verdict | Support | Question |")
        lines.append("|---|---|---|---|")
        for finding in ctx["stable_findings"]:
            lines.append(
                f"| {finding['target']} | {finding['verdict']} "
                f"| {finding['support']} | {finding['question']} |"
            )
        lines.append("")
    measurement = ctx.get("measurement")
    measurement_status = ctx.get("measurement_status", "not_run")
    if measurement_status == "available" and measurement:
        lines.append("## v3 measurement")
        lines.append("")
        lines.append(
            f"- SR mean {measurement.get('sr_mean', 0):.3f} "
            f"± {measurement.get('sr_stdev', 0):.3f} · noise floor "
            f"{measurement.get('extraction_noise_floor', 0):.3f} · "
            f"stable-low {len(ctx.get('stable_low') or [])} unit(s)"
        )
        lines.append("")
    elif any(tier["tier"] == "v3" for tier in ctx["tiers"]):
        lines.append("## v3 measurement")
        lines.append("")
        lines.append(
            f"- **V3 measurement unavailable:** {measurement_status}; no "
            "stable-low count or semantic-reproducibility score is claimed."
        )
        lines.append("")
    if ctx.get("drills"):
        lines.append("## Dialectic drills")
        lines.append("")
        lines.append("| Finding | Lens | Target | Terminal | Turns | Artifact |")
        lines.append("|---|---|---|---|---|---|")
        for drill in ctx["drills"]:
            lines.append(
                f"| {drill.get('source_id', '')} | {drill['lens']} | {drill['target']} "
                f"| {drill.get('terminal_state', '?')} "
                f"| {drill.get('turns', '?')} "
                f"| {drill.get('artifact_markdown') or drill.get('artifact_json', '')} |"
            )
        lines.append("")
    jgraph = ctx.get("jgraph")
    if jgraph:
        lines.append("## Justification-graph convergence")
        lines.append("")
        lines.append(
            f"- consensus conflicts {jgraph.get('consensus_conflicts', 0)}"
            f"/{jgraph.get('distinct_conflicts', 0)} · unanimous "
            f"{jgraph.get('unanimous_conflicts', 0)} · evidence completeness "
            f"{jgraph.get('mean_evidence_completeness', 0):.2f}"
        )
        lines.append("")
    lines.append(
        "_Diagnose-only dossier: individual tool reports sit beside the spec; "
        "nothing was edited or dispatched._"
    )
    lines.append("")
    return "\n".join(lines)


# ── CLI + orchestration ──────────────────────────────────────────────────────


def parse_args(argv: list):
    parser = v1._Parser(
        prog="sue_auto.py",
        description=(
            "SUE Auto: run a full SUE diagnosis profile against one "
            f"specification and write a consolidated dossier. "
            f"{v1.EGRESS_DISCLOSURE}"
        ),
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="deep")
    parser.add_argument(
        "--model-cmd", dest="model_cmd", default=DIALOGUE_MODEL_CMD,
        help="model command for the dialogue tiers "
             f"(default: {DIALOGUE_MODEL_CMD!r})",
    )
    parser.add_argument(
        "--measure-model-cmd", dest="measure_model_cmd", default=None,
        help="model command for the v3 measurement readers "
             "(default: the CLI's default model — Sonnet is not "
             "measurement-grade)",
    )
    v1.add_codex_profile_arguments(parser)
    parser.add_argument("--max-drills", type=v1._positive_int, default=None)
    parser.add_argument(
        "--max-provider-attempts",
        type=v1._positive_int,
        default=None,
        help="hard preflight ceiling for physical provider attempts, including retries",
    )
    parser.add_argument(
        "--continue-on-tier-failure",
        action="store_true",
        help="continue later tiers after a failed tier; final status still fails",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="return success when at least one tier succeeds despite failures",
    )
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    profile = PROFILES[options.profile]
    commands_to_validate = []
    if any(tier in profile.tiers for tier in ("v1", "v2", "jgraph", "drills")):
        commands_to_validate.append(options.model_cmd)
    if "v3" in profile.tiers:
        commands_to_validate.append(options.measure_model_cmd)
    for model_command in commands_to_validate:
        _command, protocol = v1.resolve_model_command(model_command)
        v1.resolve_codex_profile(
            protocol, options.model, options.reasoning_effort
        )
    return options


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _artifact_ref(spec_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(spec_dir))
    except ValueError:
        return str(path.resolve())


def _safe_artifact_label(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return label[:80] or "finding"


def archive_drill_artifacts(
    spec_dir: Path, run_dir: Path, index: int, drill: dict
) -> dict:
    """Copy one completed dialogue before the next drill overwrites aliases."""
    finding_dir = run_dir / (
        f"{index:02d}-{_safe_artifact_label(drill['source_id'])}-"
        f"{_safe_artifact_label(drill['lens'])}"
    )
    finding_dir.mkdir(parents=True, exist_ok=False)
    source_json = spec_dir / dial.JSON_FILENAME
    if not source_json.is_file():
        raise OSError(f"dialectic JSON artifact is missing: {source_json}")
    artifact_json = finding_dir / "dialogue.json"
    shutil.copy2(source_json, artifact_json)
    result = {"artifact_json": _artifact_ref(spec_dir, artifact_json)}
    source_markdown = spec_dir / dial.REPORT_FILENAME
    if source_markdown.is_file():
        artifact_markdown = finding_dir / "dialogue.md"
        shutil.copy2(source_markdown, artifact_markdown)
        result["artifact_markdown"] = _artifact_ref(spec_dir, artifact_markdown)
    return result


def main(argv: list | None = None) -> int:
    try:
        options = parse_args(list(sys.argv[1:]) if argv is None else list(argv))
    except v1.ArgumentFailure as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: {exc}")
    spec_path = options.spec_path
    spec_dir = spec_path.resolve().parent
    if spec_path.resolve() in (spec_dir / REPORT_FILENAME,
                               spec_dir / JSON_FILENAME):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: challenged file '{spec_path}' is a dossier path — "
            "rename it to challenge it",
        )
    try:
        spec = v1.load_spec(spec_path)
    except OSError as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: {exc}")
    if not any(line.strip() for line in spec.lines):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{spec_path}' is empty or "
            "whitespace-only — nothing to diagnose",
        )

    profile = PROFILES[options.profile]
    drill_cap = (options.max_drills if options.max_drills is not None
                 else profile.drill_cap)
    try:
        _source_bundle, requirement_ids = v3.load_requirement_scope(spec_path)
    except v3.source.SUESourceError as exc:
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{spec_path}' cannot be represented "
            f"as source units: {exc}",
        )
    unit_count = len(requirement_ids)
    budget = plan_budget(options.profile, unit_count, drill_cap=drill_cap)
    if (options.max_provider_attempts is not None
            and budget.max_provider_attempts > options.max_provider_attempts):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: profile '{options.profile}' requires up to "
            f"{budget.max_provider_attempts} provider attempts for {unit_count} "
            f"unit(s), exceeding --max-provider-attempts "
            f"{options.max_provider_attempts}",
        )
    timeout_args = ["--timeout", str(options.timeout)]
    profile_args = []
    if options.model is not None:
        profile_args += ["--model", options.model]
    if options.reasoning_effort is not None:
        profile_args += ["--reasoning-effort", options.reasoning_effort]
    print(
        f"Profile: {options.profile} — tiers: {' → '.join(profile.tiers)} · "
        f"{unit_count} unit(s) · plan: {budget.logical_calls} logical calls · "
        f"≤{budget.max_provider_attempts} provider attempts including retries"
    )

    tiers: list = []
    stable_findings: list = []
    measurement = None
    measurement_status = "not_run"
    stable_low: list = []
    jgraph_summary = None
    drill_results: list = []
    drill_run_dir: Path | None = None

    def record(tier: str, rc: int):
        tiers.append(
            {"tier": tier, "status": "ok" if rc == 0 else "failed",
             **({} if rc == 0 else {"exit_code": rc})}
        )
        return rc == 0

    for tier in profile.tiers:
        rc = v1.EXIT_SUCCESS
        if tier == "v1":
            rc = v1.main([str(spec_path), "--model-cmd", options.model_cmd,
                          *profile_args, *timeout_args])
            record("v1", rc)
        elif tier == "v2":
            rc = v2.main([str(spec_path), "--readers", str(READERS),
                          "--model-cmd", options.model_cmd,
                          *profile_args, *timeout_args])
            if record("v2", rc):
                try:
                    stable_findings = parse_stable_findings(
                        (spec_dir / v2.REPORT_FILENAME).read_text(
                            encoding="utf-8")
                    )
                except OSError:
                    stable_findings = []
        elif tier == "v3":
            measurement_status = "unavailable"
            v3_argv = [str(spec_path), "--passes", str(V3_PASSES),
                       *profile_args, *timeout_args]
            if options.measure_model_cmd:
                v3_argv += ["--model-cmd", options.measure_model_cmd]
            rc = v3.main(v3_argv)
            if record("v3", rc):
                sidecar = _read_json(spec_dir / v3.JSON_FILENAME) or {}
                measurement = sidecar.get("stability") or {}
                stable_low = list(measurement.get("stable_low") or [])
                measurement_status = "available"
        elif tier == "jgraph":
            rc = jg.main([str(spec_path), "--readers", str(READERS),
                          "--model-cmd", options.model_cmd,
                          *profile_args, *timeout_args])
            if record("jgraph", rc):
                sidecar = _read_json(spec_dir / jg.JSON_FILENAME) or {}
                jgraph_summary = sidecar.get("convergence")
        elif tier == "drills":
            drills = select_drills(stable_findings, stable_low, drill_cap)
            failures = 0
            if drills:
                drill_run_dir = (
                    spec_dir / "sue-drills" / f"auto-{uuid.uuid4().hex}"
                )
                try:
                    drill_run_dir.mkdir(parents=True, exist_ok=False)
                except OSError:
                    failures = len(drills)
            for drill_index, drill in enumerate(drills, start=1):
                if drill_run_dir is None:
                    break
                rc = dial.main([
                    str(spec_path), "--lens", drill["lens"],
                    "--seed", drill["seed"], "--target", drill["target"],
                    "--model-cmd", options.model_cmd,
                    *profile_args, *timeout_args,
                ])
                if rc != 0:
                    failures += 1
                    continue
                trace = _read_json(spec_dir / dial.JSON_FILENAME) or {}
                try:
                    artifacts = archive_drill_artifacts(
                        spec_dir, drill_run_dir, drill_index, drill
                    )
                except OSError:
                    failures += 1
                    continue
                drill_results.append({
                    **drill, **artifacts,
                    "terminal_state": trace.get("terminal_state"),
                    "turns": len(trace.get("turns") or []),
                })
            rc = 0 if failures == 0 else v1.EXIT_UNUSABLE_OUTPUT
            record("drills", rc)

        if rc != 0 and not options.continue_on_tier_failure:
            break

    completed_tiers = {tier["tier"] for tier in tiers}
    for tier in profile.tiers:
        if tier not in completed_tiers:
            tiers.append({
                "tier": tier,
                "status": "not_run",
                "reason": "stopped after prior tier failure",
            })

    ctx = {
        "spec_path": str(spec_path),
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "profile": options.profile,
        "models": {
            "dialogue": options.model_cmd,
            "measure": options.measure_model_cmd or "(cli default)",
            "requested": options.model,
            "reasoning_effort": options.reasoning_effort,
        },
        "tiers": tiers,
        "stable_findings": stable_findings,
        "measurement": measurement,
        "measurement_status": measurement_status,
        "stable_low": stable_low,
        "drills": drill_results,
        "jgraph": jgraph_summary,
        "call_budget": {
            "logical_calls": budget.logical_calls,
            "max_provider_attempts": budget.max_provider_attempts,
            "configured_max_provider_attempts": options.max_provider_attempts,
        },
    }
    report = render_dossier(ctx)
    try:
        (spec_dir / REPORT_FILENAME).write_text(report, encoding="utf-8")
        (spec_dir / JSON_FILENAME).write_text(
            json.dumps(ctx, indent=1), encoding="utf-8"
        )
    except OSError as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: cannot write dossier: {exc}")

    succeeded = [t for t in tiers if t["status"] == "ok"]
    failed = [t for t in tiers if t["status"] == "failed"]
    print(f"Dossier: {spec_dir / REPORT_FILENAME}")
    aporias = sum(1 for d in drill_results
                  if (d.get("terminal_state") or "").startswith("APORIA"))
    print(
        f"{len(stable_findings)} stable finding(s) · "
        + (
            f"{len(stable_low)} stable-low unit(s)"
            if measurement_status == "available"
            else "stable-low N/A"
        )
        + f" · {aporias} drill aporia(s) · "
        f"{len(failed)} tier failure(s)"
    )
    if options.json:
        print(json.dumps(ctx, indent=1))
    if failed and not (options.allow_partial and succeeded):
        return failed[0]["exit_code"]
    if succeeded:
        return v1.EXIT_SUCCESS
    return failed[0]["exit_code"] if failed else v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
