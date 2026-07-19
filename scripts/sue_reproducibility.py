#!/usr/bin/env python3
"""SUE v3 — semantic-reproducibility instrument over interpretation graphs.

K isolated readers each extract a typed interpretation graph (entities, edges,
assumptions, behavioural assertions — every element line-grounded) from the
challenged specification. Deterministic anchor alignment scores per-requirement
and overall agreement (semantic reproducibility), exhibits grounded divergence
witnesses (same given/when, incompatible then), and attributes divergences to
fracture lines. Reports: semantic-reproducibility.md + .json beside the spec.
Design: docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path


def _load_v1():
    path = Path(__file__).resolve().parent / "sue_challenge.py"
    spec = importlib.util.spec_from_file_location("sue_challenge", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("sue_challenge", module)
    spec.loader.exec_module(module)
    return module


v1 = _load_v1()

REPORT_FILENAME = "semantic-reproducibility.md"
JSON_FILENAME = "semantic-reproducibility.json"

EDGE_TYPES = (
    "performs", "acts_on", "applies_when", "results_in",
    "except_when", "assumes", "requires", "transitions_to",
)

REQ_ID_RE = re.compile(r"\b((?:REQ|FR|AC|NFR|ERR|SC|U|OQ|A)-[0-9]{1,4}[a-z]?)\b")

# v3.1: behavioural unit families scored by default; assumption/decision/open-
# question families (A-, U-, OQ-, SC-) dilute agreement with non-behavioural
# units and are opt-in via --families.
DEFAULT_FAMILIES = ("REQ", "FR", "AC", "NFR", "ERR")

FRAMINGS = (
    ("structural", "Read structurally: map entities, relations and obligations "
     "precisely as written."),
    ("behavioural", "Read behaviourally: focus on triggers, conditions, outcomes "
     "and what blocks them."),
    ("adversarial", "Read literally and skeptically: surface what the text "
     "silently relies on."),
)

_ARTICLES = re.compile(r"^(a|an|the)\s+")
_WS = re.compile(r"[\s_\-]+")

_EXEMPLAR = """\
Label style (follow exactly — one worked example):
For the requirement line "REQ-004: When a raw rule edit is invalid, the system
MUST display an inline error and retain the last valid card rendering.":
{"REQ-004": {"edges": [
  {"s": "system", "type": "performs", "t": "display inline error", "line": 4, "conf": 0.95},
  {"s": "display inline error", "type": "applies_when", "t": "raw rule edit invalid", "line": 4, "conf": 0.9},
  {"s": "system", "type": "performs", "t": "retain last valid card rendering", "line": 4, "conf": 0.9}],
 "assumptions": [{"text": "validity of a raw edit is decidable at edit time", "line": 4}],
 "assertions": [{"given": "a rule open in raw edit mode", "when": "the edit becomes invalid",
                 "then": "an inline error appears and the card keeps the last valid rendering",
                 "lines": [4]}]}}
Labels: lowercase, singular, spec vocabulary, no leading articles, short phrases."""


# ── Data model ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Edge:
    s: str
    type: str
    t: str
    line: int
    conf: float

    @property
    def triple(self) -> tuple:
        return (norm(self.s), self.type, norm(self.t))


@dataclass(frozen=True)
class Assertion:
    given: str
    when: str
    then: str
    lines: list

    @property
    def situation(self) -> tuple:
        return (norm(self.given), norm(self.when))


@dataclass(frozen=True)
class ReqInterpretation:
    edges: list
    assumptions: list  # list[dict text/line]
    assertions: list


@dataclass(frozen=True)
class ReaderGraph:
    reader_no: int
    framing: str
    requirements: dict  # req_id -> ReqInterpretation
    ungrounded_edges: int


@dataclass(frozen=True)
class Witness:
    req_id: str
    situation: tuple
    sides: list  # [(reader_no, Assertion), (reader_no, Assertion)]


# ── Normalization + requirement scan (pure) ──────────────────────────────────


def norm(label: str) -> str:
    text = _WS.sub(" ", str(label).strip().lower())
    text = _ARTICLES.sub("", text)
    words = []
    for word in text.split(" "):
        if len(word) > 4 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
            word = word[:-1]
        words.append(word)
    return " ".join(words)


def scan_requirement_ids(spec, families: tuple = DEFAULT_FAMILIES) -> set:
    """Deterministic set of requirement-unit ids present in the spec text,
    restricted to the given id families (v3.1 unit-scope rule)."""
    found: set[str] = set()
    for line in spec.lines:
        found.update(REQ_ID_RE.findall(line))
    return {rid for rid in found if rid.rsplit("-", 1)[0] in families}


def _singular(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _words(text: str) -> set:
    """Punctuation-insensitive normalized word set.

    Tokenize on non-alphanumerics FIRST, then singularize — running
    normalization before punctuation stripping lets trailing punctuation
    shield a token from singularization ("commands," vs "commands"), which
    falsely fails legal labels (found live: 1-in-234 comparator error killed
    a fully compliant reader)."""
    return {
        _singular(token)
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in ("a", "an", "the")
    }


def _label_grounded(label: str, line_text: str) -> bool:
    """v3.1 vocabulary anchor: every word of the normalized label must appear
    in the normalized text of the cited line (labels reuse spec words)."""
    return _words(label) <= _words(line_text)


# ── Extraction prompt + validation ───────────────────────────────────────────


def build_extraction_prompt(spec, framing_suffix: str, known_ids: set) -> str:
    ids_hint = ", ".join(sorted(known_ids)[:400])
    return (
        "You are one isolated reader in a semantic-reproducibility measurement. "
        "Read the line-numbered specification below and extract your complete "
        "interpretation as a typed graph, per requirement unit.\n\n"
        f"{framing_suffix}\n\n"
        f"Edge types (closed set): {', '.join(EDGE_TYPES)}.\n"
        f"{_EXEMPLAR}\n\n"
        "Rules: every edge and assumption carries the source line number it is "
        "grounded in; every word of an edge's s/t label MUST appear verbatim in "
        "the cited line (reuse the specification's own words — never paraphrase "
        "node labels); 1-3 behavioural assertions (given/when/then, line-cited) per "
        "requirement that mandates observable behaviour; use ONLY requirement ids "
        f"that appear in the specification (they include: {ids_hint}).\n\n"
        "SPECIFICATION (line-numbered):\n"
        f"{v1.numbered_text(spec)}\n\n"
        "Return ONLY a JSON object: {\"requirements\": {\"<REQ-ID>\": {\"edges\": "
        "[{\"s\": str, \"type\": str, \"t\": str, \"line\": int, \"conf\": float}], "
        "\"assumptions\": [{\"text\": str, \"line\": int}], \"assertions\": "
        "[{\"given\": str, \"when\": str, \"then\": str, \"lines\": [int]}]}}}. "
        "No prose, no fences preferred."
    )


def validate_graph(payload: dict, known_ids: set, max_line: int,
                   spec_lines: list | None = None):
    """Strict graph validation. Returns (dict req->ReqInterpretation, ungrounded)
    or v1.ParseFailure. With spec_lines, enforces the v3.1 vocabulary anchor:
    edge labels must reuse words of the cited line."""
    reqs = payload.get("requirements")
    if not isinstance(reqs, dict) or not reqs:
        return v1.ParseFailure(reason="requirements must be a non-empty object")
    out: dict = {}
    ungrounded = 0
    for req_id, body in reqs.items():
        if req_id not in known_ids:
            return v1.ParseFailure(
                reason=f"unknown requirement id {req_id!r} (not present in the specification)"
            )
        if not isinstance(body, dict):
            return v1.ParseFailure(reason=f"{req_id} body must be an object")
        edges: list[Edge] = []
        for i, raw in enumerate(body.get("edges", []) or []):
            if not isinstance(raw, dict):
                return v1.ParseFailure(reason=f"{req_id}.edges[{i}] must be an object")
            etype = raw.get("type")
            if etype not in EDGE_TYPES:
                return v1.ParseFailure(
                    reason=f"{req_id}.edges[{i}].type {etype!r} not in the closed set"
                )
            s, t = raw.get("s"), raw.get("t")
            if not (isinstance(s, str) and s.strip() and isinstance(t, str) and t.strip()):
                return v1.ParseFailure(reason=f"{req_id}.edges[{i}] s/t must be non-empty strings")
            line = raw.get("line")
            if not isinstance(line, int) or isinstance(line, bool):
                return v1.ParseFailure(reason=f"{req_id}.edges[{i}].line must be an integer")
            conf = raw.get("conf", 1.0)
            if not isinstance(conf, (int, float)) or isinstance(conf, bool):
                conf = 1.0
            if not (1 <= line <= max_line):
                ungrounded += 1
                continue  # dropped from scoring, counted as diagnostic
            if spec_lines is not None:
                cited = spec_lines[line - 1]
                for label in (s, t):
                    if not _label_grounded(label, cited):
                        return v1.ParseFailure(
                            reason=(
                                f"{req_id}.edges[{i}] label {label!r} uses words "
                                f"not present in cited line {line} — node labels "
                                "must reuse the specification's own words from "
                                "the cited line"
                            )
                        )
            edges.append(Edge(s=s.strip(), type=etype, t=t.strip(),
                              line=line, conf=float(conf)))
        assumptions = []
        for i, raw in enumerate(body.get("assumptions", []) or []):
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                return v1.ParseFailure(reason=f"{req_id}.assumptions[{i}] must carry text")
            assumptions.append({"text": raw["text"].strip(),
                                "line": raw.get("line") if isinstance(raw.get("line"), int) else None})
        assertions: list[Assertion] = []
        for i, raw in enumerate(body.get("assertions", []) or []):
            if not isinstance(raw, dict):
                return v1.ParseFailure(reason=f"{req_id}.assertions[{i}] must be an object")
            g, w, t_ = raw.get("given"), raw.get("when"), raw.get("then")
            if not all(isinstance(x, str) and x.strip() for x in (g, w, t_)):
                return v1.ParseFailure(
                    reason=f"{req_id}.assertions[{i}] given/when/then must be non-empty strings"
                )
            lines = raw.get("lines")
            if not isinstance(lines, list) or not all(
                isinstance(n, int) and not isinstance(n, bool) for n in lines
            ):
                return v1.ParseFailure(reason=f"{req_id}.assertions[{i}].lines must be integers")
            assertions.append(Assertion(given=g.strip(), when=w.strip(),
                                        then=t_.strip(), lines=list(lines)))
        out[req_id] = ReqInterpretation(edges=edges, assumptions=assumptions,
                                        assertions=assertions)
    return out, ungrounded


# ── Scoring (pure) ───────────────────────────────────────────────────────────


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _near_misses(a: set, b: set) -> int:
    """Triples failing exact match but sharing type + one endpoint (diagnostic)."""
    count = 0
    for s1, t1, o1 in a - b:
        for s2, t2, o2 in b - a:
            if t1 == t2 and (s1 == s2 or o1 == o2):
                count += 1
                break
    return count


def score_requirements(readers: list) -> dict:
    """Per-requirement pairwise agreement over all surviving readers.

    Returns req_id -> {score, pairs, edge_count, assumption_load, near_misses}.
    """
    all_reqs: set[str] = set()
    for reader in readers:
        all_reqs.update(reader.requirements)
    result: dict = {}
    for req_id in sorted(all_reqs):
        pair_scores: list[float] = []
        near = 0
        for ri, rj in combinations(readers, 2):
            a = {e.triple for e in ri.requirements.get(req_id, ReqInterpretation([], [], [])).edges}
            b = {e.triple for e in rj.requirements.get(req_id, ReqInterpretation([], [], [])).edges}
            pair_scores.append(_jaccard(a, b))
            near += _near_misses(a, b)
        edge_counts = [len(r.requirements[req_id].edges) for r in readers if req_id in r.requirements]
        assumption_counts = [len(r.requirements[req_id].assumptions) for r in readers if req_id in r.requirements]
        result[req_id] = {
            "score": sum(pair_scores) / len(pair_scores) if pair_scores else 1.0,
            "readers_covering": len(edge_counts),
            "mean_edges": sum(edge_counts) / len(edge_counts) if edge_counts else 0.0,
            "assumption_load": (
                sum(assumption_counts) / len(assumption_counts) if assumption_counts else 0.0
            ),
            "near_misses": near,
        }
    return result


def overall_score(per_req: dict) -> float:
    if not per_req:
        return 1.0
    return sum(v["score"] for v in per_req.values()) / len(per_req)


# ── Witnesses + localization (pure) ─────────────────────────────────────────


def find_witnesses(readers: list) -> list:
    """Grounded behavioural incompatibilities: same (given, when), different then."""
    witnesses: list[Witness] = []
    all_reqs = sorted({r for reader in readers for r in reader.requirements})
    for req_id in all_reqs:
        situations: dict = {}
        for reader in readers:
            interp = reader.requirements.get(req_id)
            if interp is None:
                continue
            for assertion in interp.assertions:
                situations.setdefault(assertion.situation, []).append(
                    (reader.reader_no, assertion)
                )
        for situation, entries in situations.items():
            thens = {norm(a.then) for _, a in entries}
            if len(thens) < 2:
                continue
            grounded = [(no, a) for no, a in entries if a.lines]
            distinct: dict = {}
            for no, assertion in grounded:
                distinct.setdefault(norm(assertion.then), (no, assertion))
            if len(distinct) >= 2:
                sides = sorted(distinct.values(), key=lambda pair: pair[0])[:2]
                witnesses.append(Witness(req_id=req_id, situation=situation,
                                         sides=sides))
    return witnesses


def fracture_lines(readers: list, per_req: dict, witnesses: list,
                   threshold: float = 0.5) -> dict:
    """req_id -> ranked [(line, citations)] attributed to divergent elements."""
    result: dict = {}
    low_reqs = {r for r, v in per_req.items() if v["score"] < threshold}
    witness_reqs = {w.req_id for w in witnesses}
    for req_id in sorted(low_reqs | witness_reqs):
        counts: dict = {}
        triple_owners: dict = {}
        for reader in readers:
            interp = reader.requirements.get(req_id)
            if interp is None:
                continue
            for edge in interp.edges:
                triple_owners.setdefault(edge.triple, []).append((reader.reader_no, edge.line))
        covering = sum(1 for r in readers if req_id in r.requirements)
        for triple, owners in triple_owners.items():
            if len({no for no, _ in owners}) < covering:  # not shared by all → divergent
                for _, line in owners:
                    counts[line] = counts.get(line, 0) + 1
        for witness in witnesses:
            if witness.req_id != req_id:
                continue
            for _, assertion in witness.sides:
                for line in assertion.lines:
                    counts[line] = counts.get(line, 0) + 1
        if counts:
            result[req_id] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    return result


# ── Rendering ────────────────────────────────────────────────────────────────


def _grade(score: float) -> str:
    if score >= 0.8:
        return "reproducible"
    if score >= 0.5:
        return "partially reproducible"
    return "fractured"


def render_report(spec, spec_path: Path, readers: list, per_req: dict,
                  sr: float, witnesses: list, fractures: dict,
                  run_date: str, dropped: list) -> str:
    lines: list[str] = []
    lines.append("# Semantic Reproducibility Report")
    lines.append("")
    lines.append(f"- **Specification:** {spec_path}")
    lines.append(f"- **Run date:** {run_date}")
    lines.append(
        f"- **Readers:** {len(readers)} completed"
        + (f" ({len(dropped)} dropped: {', '.join(dropped)})" if dropped else "")
    )
    lines.append(f"- **Semantic reproducibility:** {sr:.3f} — {_grade(sr)}")
    lines.append(f"- **Witnesses (behavioural incompatibilities):** {len(witnesses)}")
    ungrounded = ", ".join(f"R{r.reader_no}={r.ungrounded_edges}" for r in readers)
    lines.append(f"- **Ungrounded edges dropped:** {ungrounded}")
    lines.append("")
    lines.append("## Per-requirement agreement (worst first)")
    lines.append("")
    lines.append("| Requirement | Score | Readers | Mean edges | Assumption load | Near-misses |")
    lines.append("|---|---|---|---|---|---|")
    for req_id, values in sorted(per_req.items(), key=lambda kv: kv[1]["score"]):
        lines.append(
            f"| {req_id} | {values['score']:.2f} | {values['readers_covering']} "
            f"| {values['mean_edges']:.1f} | {values['assumption_load']:.1f} "
            f"| {values['near_misses']} |"
        )
    lines.append("")
    lines.append("## Divergence witnesses")
    lines.append("")
    if not witnesses:
        lines.append("None — no grounded behavioural incompatibility was exhibited.")
        lines.append("")
    ordered = sorted(witnesses, key=lambda w: per_req.get(w.req_id, {}).get("score", 1.0))
    for index, witness in enumerate(ordered, start=1):
        (no_a, a), (no_b, b) = witness.sides
        lines.append(
            f"### W{index}. {witness.req_id} — given \"{a.given}\", when \"{a.when}\""
        )
        lines.append("")
        lines.append(f"- **Reader R{no_a} then:** {a.then}")
        lines.extend(v1._quoted_evidence(spec, a.lines))
        lines.append(f"- **Reader R{no_b} then:** {b.then}")
        lines.extend(v1._quoted_evidence(spec, b.lines))
        lines.append("")
    lines.append("## Fracture lines (attributed, not verified — v3.1 adds counterfactual check)")
    lines.append("")
    if not fractures:
        lines.append("None.")
    for req_id, ranked in fractures.items():
        lines.append(f"- **{req_id}:**")
        for line_no, citations in ranked:
            quoted = v1._quoted_evidence(spec, [line_no])[0].strip()
            lines.append(f"  - ({citations}×) {quoted}")
    lines.append("")
    return "\n".join(lines)


def build_sidecar(spec_path: Path, readers: list, per_req: dict, sr: float,
                  witnesses: list, fractures: dict, run_date: str) -> dict:
    return {
        "specification": str(spec_path),
        "run_date": run_date,
        "readers": [
            {
                "reader": r.reader_no,
                "framing": r.framing,
                "ungrounded_edges": r.ungrounded_edges,
                "requirements": {
                    req_id: {
                        "edges": [
                            {"s": e.s, "type": e.type, "t": e.t, "line": e.line,
                             "conf": e.conf} for e in interp.edges
                        ],
                        "assumptions": interp.assumptions,
                        "assertions": [
                            {"given": a.given, "when": a.when, "then": a.then,
                             "lines": a.lines} for a in interp.assertions
                        ],
                    }
                    for req_id, interp in r.requirements.items()
                },
            }
            for r in readers
        ],
        "per_requirement": per_req,
        "semantic_reproducibility": sr,
        "witnesses": [
            {
                "requirement": w.req_id,
                "given": w.sides[0][1].given,
                "when": w.sides[0][1].when,
                "sides": [
                    {"reader": no, "then": a.then, "lines": a.lines}
                    for no, a in w.sides
                ],
            }
            for w in witnesses
        ],
        "fracture_lines": {
            req_id: [{"line": line, "citations": count} for line, count in ranked]
            for req_id, ranked in fractures.items()
        },
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list) -> tuple:
    parser = v1._Parser(
        prog="sue_reproducibility.py",
        description=(
            "SUE v3: measure semantic reproducibility of a specification via K "
            f"isolated interpretation-graph readers. {v1.EGRESS_DISCLOSURE}"
        ),
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--readers", type=v1._positive_int, default=3)
    parser.add_argument("--families", default=",".join(DEFAULT_FAMILIES))
    parser.add_argument("--claude-cmd", default=v1.DEFAULT_MODEL_COMMAND)
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    config = v1.RunConfig(
        spec_path=options.spec_path,
        max_questions=1,
        model_command=options.claude_cmd,
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
            f"bad input: challenged file '{config.spec_path}' is a v3 report "
            "path — rename it to challenge it",
        )
    spec = v1.load_spec(config.spec_path)
    if not any(line.strip() for line in spec.lines):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{config.spec_path}' is empty or "
            "whitespace-only — nothing to measure",
        )
    families = tuple(
        f.strip().upper() for f in options.families.split(",") if f.strip()
    )
    known_ids = scan_requirement_ids(spec, families)
    if not known_ids:
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{config.spec_path}' contains no "
            f"recognizable requirement ids in families {', '.join(families)}",
        )

    readers: list[ReaderGraph] = []
    dropped: list[str] = []
    for reader_no in range(1, options.readers + 1):
        name, suffix = FRAMINGS[(reader_no - 1) % len(FRAMINGS)]
        outcome = v1.execute_round(
            config,
            build_extraction_prompt(spec, suffix, known_ids),
            lambda payload: validate_graph(payload, known_ids, len(spec.lines),
                                           spec_lines=spec.lines),
            round_no=reader_no,
            spec_dir=spec_dir,
        )
        if isinstance(outcome, v1.RoundExit):
            dropped.append(f"R{reader_no}({name})")
            continue
        requirements, ungrounded = outcome
        readers.append(ReaderGraph(reader_no=reader_no, framing=name,
                                   requirements=requirements,
                                   ungrounded_edges=ungrounded))
    if len(readers) < 2:
        return v1.fail(
            v1.EXIT_UNUSABLE_OUTPUT,
            "unusable model output: fewer than 2 readers completed "
            f"({len(readers)} of {options.readers}; dropped: "
            f"{', '.join(dropped) or 'none'})",
        )

    per_req = score_requirements(readers)
    sr = overall_score(per_req)
    witnesses = find_witnesses(readers)
    fractures = fracture_lines(readers, per_req, witnesses)
    run_date = datetime.now().strftime("%Y-%m-%d")

    report = render_report(spec, config.spec_path, readers, per_req, sr,
                           witnesses, fractures, run_date, dropped)
    sidecar = build_sidecar(config.spec_path, readers, per_req, sr, witnesses,
                            fractures, run_date)
    try:
        (spec_dir / REPORT_FILENAME).write_text(report, encoding="utf-8")
        (spec_dir / JSON_FILENAME).write_text(
            json.dumps(sidecar, indent=1), encoding="utf-8"
        )
    except OSError as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: cannot write report: {exc}")
    print(f"Report: {spec_dir / REPORT_FILENAME}")
    print(
        f"Semantic reproducibility: {sr:.3f} ({_grade(sr)}) over "
        f"{len(per_req)} requirement(s); witnesses: {len(witnesses)}; "
        f"fracture sites: {len(fractures)}"
    )
    worst = sorted(per_req.items(), key=lambda kv: kv[1]["score"])[:3]
    for req_id, values in worst:
        print(f"  lowest: {req_id} = {values['score']:.2f}")
    if options.json:
        print(json.dumps(sidecar, indent=1))
    return v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
