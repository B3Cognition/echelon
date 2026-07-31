#!/usr/bin/env python3
"""SUE J-Graph — one-shot justification-graph extraction (experiment arm D).

The cheap control for the reasoning-layer experiment: each of K isolated
readers emits, in ONE model call, a claims/evidence/conflict graph for the
whole specification. If this matches the dialectic's contradiction findings at
a fraction of the cost, the Justification Graph should be built this way
(decision-rule outcome 2). No score, no spec edits.

Outputs beside the spec: justification-graph.json + justification-graph.md.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


def _load_v1():
    path = Path(__file__).resolve().parent / "sue_challenge.py"
    spec = importlib.util.spec_from_file_location("sue_challenge", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("sue_challenge", module)
    spec.loader.exec_module(module)
    return module


v1 = _load_v1()

REPORT_FILENAME = "justification-graph.md"
JSON_FILENAME = "justification-graph.json"

CLAIM_ID_RE = re.compile(r"^C[1-9][0-9]*$")
INFERENCE_KINDS = ("stated", "derived")


@dataclass(frozen=True)
class Claim:
    id: str
    claim: str
    evidence_lines: list
    assumptions: list
    inference: str
    conflicts_with: list


def build_prompt(spec, focus_hint: str) -> str:
    return (
        "You are one isolated reader building a justification graph of a "
        "specification in a single pass. Read the line-numbered text and emit "
        "the claims the text commits to about the focus area, each with its "
        "evidence, assumptions, and conflicts.\n\n"
        f"Focus area: {focus_hint or 'the whole specification'}.\n\n"
        "SPECIFICATION (line-numbered):\n"
        f"{v1.numbered_text(spec)}\n\n"
        "Return ONLY a JSON object:\n"
        '{"claims": [{"id": "C1", "claim": str, "evidence_lines": [int], '
        '"assumptions": [str], "inference": "stated|derived", '
        '"conflicts_with": ["C2"]}]}\n\n'
        "Rules: ids sequential C1..Cn; \"stated\" claims MUST cite evidence "
        "lines; \"derived\" claims list the assumptions the derivation needs; "
        "conflicts_with names OTHER claim ids this claim cannot hold with — "
        "record every contradiction the text supports, citing both sides' "
        "lines in the two claims. 5-25 claims."
    )


def validate_graph(payload: dict, max_line: int):
    """Strict validation. Returns list[Claim] or v1.ParseFailure."""
    raw = payload.get("claims")
    if not isinstance(raw, list) or not raw:
        return v1.ParseFailure(reason="claims must be a non-empty list")
    ids: set[str] = set()
    claims: list[Claim] = []
    for index, item in enumerate(raw):
        label = f"claims[{index}]"
        if not isinstance(item, dict):
            return v1.ParseFailure(reason=f"{label} must be an object")
        cid = item.get("id")
        if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
            return v1.ParseFailure(reason=f"{label}.id must match C1..Cn")
        if cid in ids:
            return v1.ParseFailure(reason=f"duplicate claim id {cid}")
        ids.add(cid)
        text = item.get("claim")
        if not isinstance(text, str) or not text.strip():
            return v1.ParseFailure(reason=f"{label}.claim must be non-empty")
        lines = item.get("evidence_lines", [])
        if not isinstance(lines, list) or not all(
            isinstance(n, int) and not isinstance(n, bool) for n in lines
        ):
            return v1.ParseFailure(reason=f"{label}.evidence_lines must be integers")
        in_range = [n for n in lines if 1 <= n <= max_line]
        inference = item.get("inference")
        if inference not in INFERENCE_KINDS:
            return v1.ParseFailure(
                reason=f"{label}.inference must be one of {INFERENCE_KINDS}"
            )
        if inference == "stated" and not in_range:
            return v1.ParseFailure(
                reason=f"{label}: stated claims require in-range evidence lines"
            )
        assumptions = item.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(a, str) for a in assumptions
        ):
            return v1.ParseFailure(reason=f"{label}.assumptions must be strings")
        conflicts = item.get("conflicts_with", [])
        if not isinstance(conflicts, list) or not all(
            isinstance(c, str) for c in conflicts
        ):
            return v1.ParseFailure(reason=f"{label}.conflicts_with must be ids")
        claims.append(Claim(
            id=cid, claim=text.strip(), evidence_lines=in_range,
            assumptions=[a.strip() for a in assumptions if a.strip()],
            inference=inference,
            conflicts_with=[c for c in conflicts],
        ))
    for claim in claims:
        for ref in claim.conflicts_with:
            if ref not in ids:
                return v1.ParseFailure(
                    reason=f"{claim.id}.conflicts_with names unknown id {ref!r}"
                )
    return claims


def _overlap(a: frozenset, b: frozenset) -> bool:
    """Anchor rule (same discipline as v3): share ≥1 evidence line, or both
    empty."""
    if not a and not b:
        return True
    return bool(a & b)


def consensus_conflicts(readers: dict) -> list:
    """Cross-reader Justification-Graph convergence on contradictions.

    Each reader's conflict pair is anchored by the evidence-line sets of its
    two claims. Two readers report the SAME conflict when both connect the same
    two line regions (each side shares a line with a corresponding side, either
    orientation). Returns clusters sorted by reader support (desc) — a conflict
    found by ≥2 independent readers is a converged, trustworthy contradiction.
    This is graph-only contradiction detection: no dialogue, no text re-reading.
    """
    edges: list[dict] = []
    for reader_no, claims in readers.items():
        by_id = {c.id: c for c in claims}
        seen: set = set()
        for claim in claims:
            for ref in claim.conflicts_with:
                other = by_id.get(ref)
                if other is None:
                    continue
                key = tuple(sorted((claim.id, ref)))
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "reader": reader_no,
                    "a": frozenset(claim.evidence_lines),
                    "b": frozenset(other.evidence_lines),
                    "text_a": claim.claim,
                    "text_b": other.claim,
                    "lines_a": sorted(claim.evidence_lines),
                    "lines_b": sorted(other.evidence_lines),
                })
    clusters: list[dict] = []
    for edge in edges:
        home = None
        for cluster in clusters:
            for member in cluster["edges"]:
                if ((_overlap(edge["a"], member["a"]) and _overlap(edge["b"], member["b"]))
                        or (_overlap(edge["a"], member["b"]) and _overlap(edge["b"], member["a"]))):
                    home = cluster
                    break
            if home:
                break
        if home is None:
            home = {"readers": set(), "edges": []}
            clusters.append(home)
        home["readers"].add(edge["reader"])
        home["edges"].append(edge)
    clusters.sort(key=lambda c: (-len(c["readers"]), min(c["readers"])))
    return clusters


def convergence_metrics(readers: dict, clusters: list) -> dict:
    """H-D2 numbers: does the one-shot graph converge across readers?"""
    import statistics as _st

    n_readers = len(readers)
    consensus = [c for c in clusters if len(c["readers"]) >= 2]
    unanimous = [c for c in clusters if len(c["readers"]) == n_readers]
    completeness = [
        sum(1 for cl in claims if cl.evidence_lines) / len(claims)
        if claims else 0.0
        for claims in readers.values()
    ]
    return {
        "readers": n_readers,
        "distinct_conflicts": len(clusters),
        "consensus_conflicts": len(consensus),
        "unanimous_conflicts": len(unanimous),
        "conflict_convergence": (
            len(consensus) / len(clusters) if clusters else 0.0
        ),
        "mean_evidence_completeness": _st.mean(completeness) if completeness else 0.0,
    }


def graph_metrics(readers: dict) -> dict:
    """Per-reader completeness + conflict pairs (deterministic)."""
    metrics: dict = {}
    for reader_no, claims in readers.items():
        with_evidence = sum(1 for c in claims if c.evidence_lines)
        pairs = sorted({
            tuple(sorted((c.id, ref)))
            for c in claims for ref in c.conflicts_with
        })
        metrics[reader_no] = {
            "claims": len(claims),
            "evidence_completeness": with_evidence / len(claims) if claims else 0.0,
            "conflict_pairs": [list(p) for p in pairs],
            "assumption_count": sum(len(c.assumptions) for c in claims),
        }
    return metrics


def render_report(spec, spec_path: Path, readers: dict, metrics: dict,
                  run_date: str, focus_hint: str,
                  clusters: list | None = None,
                  convergence: dict | None = None) -> str:
    lines: list[str] = []
    lines.append("# Justification Graph Report (one-shot)")
    lines.append("")
    lines.append(f"- **Specification:** {spec_path}")
    lines.append(f"- **Run date:** {run_date}")
    if focus_hint:
        lines.append(f"- **Focus:** {focus_hint}")
    lines.append(f"- **Readers:** {len(readers)}")
    if convergence is not None:
        lines.append(
            f"- **Conflict convergence:** {convergence['consensus_conflicts']}"
            f"/{convergence['distinct_conflicts']} distinct conflicts found by "
            f"≥2 readers ({convergence['conflict_convergence']:.0%}); "
            f"{convergence['unanimous_conflicts']} unanimous")
        lines.append(
            f"- **Mean evidence completeness:** "
            f"{convergence['mean_evidence_completeness']:.2f}")
    if clusters is not None:
        consensus = [c for c in clusters if len(c["readers"]) >= 2]
        lines.append("")
        lines.append("## Consensus conflicts (found by ≥2 independent readers)")
        lines.append("")
        if not consensus:
            lines.append("None — no contradiction was independently reproduced.")
        for idx, cluster in enumerate(consensus, start=1):
            rep = cluster["edges"][0]
            support = len(cluster["readers"])
            lines.append(
                f"### CC{idx}. (support {support}/{convergence['readers']}) "
                f"conflict")
            lines.append(f"- **Claim A:** {rep['text_a']}")
            lines.extend(v1._quoted_evidence(spec, rep["lines_a"]))
            lines.append(f"- **Claim B:** {rep['text_b']}")
            lines.extend(v1._quoted_evidence(spec, rep["lines_b"]))
            lines.append("")
    lines.append("")
    lines.append("## Per-reader graphs")
    lines.append("")
    for reader_no in sorted(readers):
        m = metrics[reader_no]
        lines.append(
            f"## Reader R{reader_no} — {m['claims']} claims, "
            f"evidence completeness {m['evidence_completeness']:.2f}, "
            f"{len(m['conflict_pairs'])} conflict pair(s)"
        )
        lines.append("")
        for claim in readers[reader_no]:
            conflict = (
                f"  ⚡ conflicts: {', '.join(claim.conflicts_with)}"
                if claim.conflicts_with else ""
            )
            lines.append(f"- **{claim.id}** [{claim.inference}]{conflict} "
                         f"{claim.claim}")
            lines.extend(v1._quoted_evidence(spec, claim.evidence_lines))
            for assumption in claim.assumptions:
                lines.append(f"  - assumes: {assumption}")
        lines.append("")
    lines.append(
        "_One-shot Justification Graph (the chosen automated reasoning-layer "
        "source); consensus conflicts converge across independent readers._"
    )
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: list):
    parser = v1._Parser(
        prog="sue_jgraph.py",
        description=(
            "SUE J-Graph: one-shot justification-graph extraction by K "
            f"isolated readers (experiment arm D). {v1.EGRESS_DISCLOSURE}"
        ),
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--readers", type=v1._positive_int, default=3)
    parser.add_argument("--focus", default="",
                        help="optional focus-area hint shared by all readers")
    parser.add_argument("--model-cmd", "--claude-cmd", dest="claude_cmd",
                        default=None,
                        help="PROVIDER=COMMAND or bare command; resolves from "
                             "ECHELON_LLM/markers when omitted")
    v1.add_codex_profile_arguments(parser)
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    options = parser.parse_args(argv)
    command, protocol = v1.resolve_model_command(options.claude_cmd)
    model, reasoning_effort = v1.resolve_codex_profile(
        protocol, options.model, options.reasoning_effort
    )
    config = v1.RunConfig(
        spec_path=options.spec_path,
        max_questions=1,
        model_command=command,
        model_protocol=protocol,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=options.timeout,
    )
    return config, options


def main(argv: list | None = None) -> int:
    try:
        config, options = parse_args(
            list(sys.argv[1:]) if argv is None else list(argv)
        )
    except v1.ArgumentFailure as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: {exc}")
    failure = v1.preflight(config)
    if failure is not None:
        return v1.fail(*failure)
    spec_dir = config.spec_path.resolve().parent
    if config.spec_path.resolve() in (
        spec_dir / REPORT_FILENAME, spec_dir / JSON_FILENAME
    ):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: challenged file '{config.spec_path}' is a J-graph "
            "report path — rename it to challenge it",
        )
    spec = v1.load_spec(config.spec_path)
    if not any(line.strip() for line in spec.lines):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{config.spec_path}' is empty or "
            "whitespace-only — nothing to extract",
        )

    readers: dict = {}
    dropped: list[int] = []
    for reader_no in range(1, options.readers + 1):
        outcome = v1.execute_round(
            config,
            build_prompt(spec, options.focus),
            lambda payload: validate_graph(payload, len(spec.lines)),
            round_no=reader_no,
            spec_dir=spec_dir,
        )
        if isinstance(outcome, v1.RoundExit):
            dropped.append(reader_no)
            continue
        readers[reader_no] = outcome
    if not readers:
        return v1.fail(
            v1.EXIT_UNUSABLE_OUTPUT,
            f"unusable model output: all {options.readers} reader(s) failed",
        )

    metrics = graph_metrics(readers)
    clusters = consensus_conflicts(readers)
    convergence = convergence_metrics(readers, clusters)
    run_date = datetime.now().strftime("%Y-%m-%d")
    report = render_report(spec, config.spec_path, readers, metrics, run_date,
                           options.focus, clusters=clusters,
                           convergence=convergence)
    sidecar = {
        "specification": str(config.spec_path),
        "run_date": run_date,
        "focus": options.focus or None,
        "dropped_readers": dropped,
        "metrics": metrics,
        "convergence": convergence,
        "consensus_conflicts": [
            {
                "support": len(c["readers"]),
                "readers": sorted(c["readers"]),
                "text_a": c["edges"][0]["text_a"],
                "lines_a": c["edges"][0]["lines_a"],
                "text_b": c["edges"][0]["text_b"],
                "lines_b": c["edges"][0]["lines_b"],
            }
            for c in clusters if len(c["readers"]) >= 2
        ],
        "readers": {
            str(reader_no): [
                {"id": c.id, "claim": c.claim,
                 "evidence_lines": c.evidence_lines,
                 "assumptions": c.assumptions, "inference": c.inference,
                 "conflicts_with": c.conflicts_with}
                for c in claims
            ]
            for reader_no, claims in readers.items()
        },
    }
    try:
        (spec_dir / REPORT_FILENAME).write_text(report, encoding="utf-8")
        (spec_dir / JSON_FILENAME).write_text(
            json.dumps(sidecar, indent=1), encoding="utf-8"
        )
    except OSError as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: cannot write report: {exc}")
    print(f"Report: {spec_dir / REPORT_FILENAME}")
    total_pairs = sum(len(m["conflict_pairs"]) for m in metrics.values())
    print(
        f"J-Graph — readers: {len(readers)}"
        + (f" ({len(dropped)} dropped)" if dropped else "")
        + f"; conflict pairs total: {total_pairs}"
    )
    print(
        f"Convergence: {convergence['consensus_conflicts']}"
        f"/{convergence['distinct_conflicts']} conflicts found by ≥2 readers "
        f"({convergence['conflict_convergence']:.0%}); "
        f"{convergence['unanimous_conflicts']} unanimous; "
        f"evidence completeness {convergence['mean_evidence_completeness']:.2f}"
    )
    for reader_no in sorted(metrics):
        m = metrics[reader_no]
        print(f"  R{reader_no}: {m['claims']} claims, "
              f"completeness {m['evidence_completeness']:.2f}, "
              f"conflicts {len(m['conflict_pairs'])}")
    return v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
