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
import sys
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


PROFILES = {
    "lite": Profile(tiers=("v1",), drill_cap=0),
    "deep": Profile(tiers=("v2", "v3", "drills"), drill_cap=3),
    "forensic": Profile(tiers=("v2", "v3", "jgraph", "drills"), drill_cap=8),
}


def plan_calls(profile_name: str, unit_count: int) -> int:
    """Upper-bound call estimate for the plan line (not a hard limit)."""
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
            calls += profile.drill_cap * DRILL_TURN_BUDGET
    return calls


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
    """v2 stable findings first, then v3 stable-low fill; no duplicate targets."""
    drills: list = []
    targeted: set = set()
    for finding in stable_findings:
        if len(drills) >= cap:
            break
        target = finding["target"]
        if target in targeted:
            continue
        targeted.add(target)
        drills.append({
            "lens": choose_lens(finding["verdict"], finding["question"]),
            "seed": finding["question"],
            "target": target,
            "source": "v2-stable",
        })
    for unit in stable_low:
        if len(drills) >= cap:
            break
        if unit in targeted:
            continue
        targeted.add(unit)
        drills.append({
            "lens": lens_for_unit(unit),
            "seed": f"the exact meaning and obligations of {unit}",
            "target": unit,
            "source": "v3-stable-low",
        })
    return drills


# ── v2 report parsing (anchored to sue_consensus.render_report's format) ─────

_STABLE_HEAD_RE = re.compile(
    r"^### \d+\. \[(CONTRADICTED|UNANSWERABLE)\] \(support (\d+)\) (.*\S)\s*$"
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
                "verdict": head.group(1),
                "support": int(head.group(2)),
                "question": head.group(3),
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
    lines.append("")
    lines.append("## Tier outcomes")
    lines.append("")
    for tier in ctx["tiers"]:
        status = tier["status"]
        suffix = f" (exit {tier['exit_code']})" if status == "failed" else ""
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
                f"{drill['seed']} (socratic-dialogue.md)"
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
    if measurement:
        lines.append("## v3 measurement")
        lines.append("")
        lines.append(
            f"- SR mean {measurement.get('sr_mean', 0):.3f} "
            f"± {measurement.get('sr_stdev', 0):.3f} · noise floor "
            f"{measurement.get('extraction_noise_floor', 0):.3f} · "
            f"stable-low {len(ctx.get('stable_low') or [])} unit(s)"
        )
        lines.append("")
    if ctx.get("drills"):
        lines.append("## Dialectic drills")
        lines.append("")
        lines.append("| Lens | Target | Terminal | Turns | Source |")
        lines.append("|---|---|---|---|---|")
        for drill in ctx["drills"]:
            lines.append(
                f"| {drill['lens']} | {drill['target']} "
                f"| {drill.get('terminal_state', '?')} "
                f"| {drill.get('turns', '?')} | {drill.get('source', '')} |"
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
    parser.add_argument("--max-drills", type=v1._positive_int, default=None)
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
    unit_count = len(v3.scan_requirement_ids(spec))
    timeout_args = ["--timeout", str(options.timeout)]
    print(
        f"Profile: {options.profile} — tiers: {' → '.join(profile.tiers)} · "
        f"{unit_count} unit(s) · est. ≤{plan_calls(options.profile, unit_count)} "
        "calls"
    )

    tiers: list = []
    stable_findings: list = []
    measurement = None
    stable_low: list = []
    jgraph_summary = None
    drill_results: list = []

    def record(tier: str, rc: int):
        tiers.append(
            {"tier": tier, "status": "ok" if rc == 0 else "failed",
             **({} if rc == 0 else {"exit_code": rc})}
        )
        return rc == 0

    for tier in profile.tiers:
        if tier == "v1":
            rc = v1.main([str(spec_path), "--model-cmd", options.model_cmd,
                          *timeout_args])
            record("v1", rc)
        elif tier == "v2":
            rc = v2.main([str(spec_path), "--readers", str(READERS),
                          "--model-cmd", options.model_cmd, *timeout_args])
            if record("v2", rc):
                try:
                    stable_findings = parse_stable_findings(
                        (spec_dir / v2.REPORT_FILENAME).read_text(
                            encoding="utf-8")
                    )
                except OSError:
                    stable_findings = []
        elif tier == "v3":
            v3_argv = [str(spec_path), "--passes", str(V3_PASSES),
                       *timeout_args]
            if options.measure_model_cmd:
                v3_argv += ["--model-cmd", options.measure_model_cmd]
            rc = v3.main(v3_argv)
            if record("v3", rc):
                sidecar = _read_json(spec_dir / v3.JSON_FILENAME) or {}
                measurement = sidecar.get("stability") or {}
                stable_low = list(measurement.get("stable_low") or [])
        elif tier == "jgraph":
            rc = jg.main([str(spec_path), "--readers", str(READERS),
                          "--model-cmd", options.model_cmd, *timeout_args])
            if record("jgraph", rc):
                sidecar = _read_json(spec_dir / jg.JSON_FILENAME) or {}
                jgraph_summary = sidecar.get("convergence")
        elif tier == "drills":
            drills = select_drills(stable_findings, stable_low, drill_cap)
            failures = 0
            for drill in drills:
                rc = dial.main([
                    str(spec_path), "--lens", drill["lens"],
                    "--seed", drill["seed"], "--target", drill["target"],
                    "--model-cmd", options.model_cmd, *timeout_args,
                ])
                if rc != 0:
                    failures += 1
                    continue
                trace = _read_json(spec_dir / dial.JSON_FILENAME) or {}
                drill_results.append({
                    **drill,
                    "terminal_state": trace.get("terminal_state"),
                    "turns": len(trace.get("turns") or []),
                })
            if drills:
                record("drills", 0 if failures < len(drills) else 3)

    ctx = {
        "spec_path": str(spec_path),
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "profile": options.profile,
        "models": {
            "dialogue": options.model_cmd,
            "measure": options.measure_model_cmd or "(cli default)",
        },
        "tiers": tiers,
        "stable_findings": stable_findings,
        "measurement": measurement,
        "stable_low": stable_low,
        "drills": drill_results,
        "jgraph": jgraph_summary,
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
        f"{len(stable_low)} stable-low unit(s) · {aporias} drill aporia(s) · "
        f"{len(failed)} tier failure(s)"
    )
    if options.json:
        print(json.dumps(ctx, indent=1))
    if succeeded:
        return v1.EXIT_SUCCESS
    return failed[0]["exit_code"] if failed else v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
