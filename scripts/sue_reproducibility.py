#!/usr/bin/env python3
"""SUE v3 — semantic-reproducibility instrument over interpretation graphs.

K isolated readers each extract a typed interpretation graph (entities, edges,
assumptions, behavioural assertions — every element line-grounded) from the
challenged specification. Deterministic anchor alignment scores per-requirement
and overall agreement (semantic reproducibility), identifies heuristic
divergence candidates, and attributes divergences to fracture lines. Reports:
semantic-reproducibility.md + .json beside the spec.
Design: docs/superpowers/specs/2026-07-19-sue-v3-reproducibility-design.md
"""
from __future__ import annotations

import importlib.util
import json
import re
import shlex
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

# v3.2: extraction is chunked so per-call output stays bounded — large specs
# timed out producing one giant graph (found live: spec 030, 6/6 attempts at
# 300s with zero bytes). Small specs fit one chunk and behave as before.
CHUNK_SIZE = 20

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
    failed_chunks: int = 0
    provider: str = "claude"
    model_tag: str = "claude"


@dataclass(frozen=True)
class ModelCommand:
    provider: str
    command: str
    model_tag: str

    @property
    def protocol(self) -> str:
        return v1.PROVIDERS.get(
            self.provider, v1.PROVIDERS["claude"]
        )["protocol"]


@dataclass(frozen=True)
class ReaderJob:
    reader_no: int
    framing_name: str
    framing_suffix: str
    model_command: ModelCommand


NEGATION_MARKERS = frozenset(
    "not no never without refuse refused reject rejected block blocked "
    "deny denied fail failed disabled decline declined".split()
)


@dataclass(frozen=True)
class Witness:
    req_id: str
    situation: tuple
    sides: list  # [(reader_no, Assertion), (reader_no, Assertion)]
    kind: str = "candidate"  # "negation-asymmetric" when one side has a marker


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


def parse_model_command(value: str) -> ModelCommand:
    """Parse ``provider=command`` or infer a legacy command's provider."""
    explicit_provider, separator, explicit_command = value.partition("=")
    if separator and explicit_provider in v1.PROVIDERS:
        provider = explicit_provider
        command = explicit_command
    elif (separator and explicit_provider
          and " " not in explicit_provider and "/" not in explicit_provider
          and explicit_provider.isalpha()):
        raise v1.ArgumentFailure(
            f"unsupported model provider prefix {explicit_provider!r}; "
            f"supported: {', '.join(sorted(v1.PROVIDERS))}"
        )
    else:
        command = value
        provider = ""
    if not command.strip():
        raise v1.ArgumentFailure("model command must not be empty")
    try:
        command_words = shlex.split(command)
    except ValueError as exc:
        raise v1.ArgumentFailure(f"model command is not shell-parseable: {exc}") from None
    model_tag = Path(command_words[0]).name
    if not provider:
        provider = model_tag if model_tag in v1.PROVIDERS else "claude"
    if provider == "copilot" and any(
        word == "-p" or word == "--prompt" or word.startswith("--prompt=")
        for word in command_words[1:]
    ):
        raise v1.ArgumentFailure(
            "copilot model command must be specified without -p/--prompt; "
            "SUE supplies the prompt"
        )
    return ModelCommand(
        provider=provider,
        command=command,
        model_tag=model_tag,
    )


def build_reader_jobs(
    model_commands: list[ModelCommand],
    readers_per_model: int,
    framings: tuple,
) -> list[ReaderJob]:
    """Build an unconfounded model × framing reader matrix."""
    jobs: list[ReaderJob] = []
    reader_no = 1
    for model_command in model_commands:
        for offset in range(readers_per_model):
            framing_name, framing_suffix = framings[offset % len(framings)]
            jobs.append(
                ReaderJob(
                    reader_no=reader_no,
                    framing_name=framing_name,
                    framing_suffix=framing_suffix,
                    model_command=model_command,
                )
            )
            reader_no += 1
    return jobs


_BLOCK_HEAD_RE = re.compile(r"^(?:REQ|AC):\s+((?:REQ|AC)-[0-9]{1,4}[a-z]?)\s*$")
_FIELD_RE = re.compile(r"^(GIVEN|WHEN):\s+(.*\S)\s*$")


def parse_controlled_situations(spec) -> dict:
    """Canonical situations from controlled-grammar (lexicon) REQ/AC blocks.

    The lexicon grammar guarantees `REQ:`/`AC:` headers followed by GIVEN/WHEN
    field lines, so a deterministic line scan suffices (stdlib only — FR-045
    forbids importing the lexicon package). Returns
    {unit_id: {"given": str, "when": str, "line": int}} for units carrying both
    fields. Non-lexicon specs return {} and the witness channel reports itself
    as situation-less (sampling-lottery mode, cross-run intersection required).
    """
    situations: dict = {}
    current_id: str | None = None
    fields: dict = {}
    for line_no, line in enumerate(spec.lines, start=1):
        head = _BLOCK_HEAD_RE.match(line.strip())
        if head:
            if current_id and "GIVEN" in fields and "WHEN" in fields:
                situations[current_id] = fields
            current_id = head.group(1)
            fields = {}
            continue
        if current_id is None:
            continue
        field = _FIELD_RE.match(line.strip())
        if field:
            fields[field.group(1)] = field.group(2)
            fields.setdefault("line", line_no)
    if current_id and "GIVEN" in fields and "WHEN" in fields:
        situations[current_id] = fields
    return {
        unit_id: {"given": f["GIVEN"], "when": f["WHEN"], "line": f["line"]}
        for unit_id, f in situations.items()
    }


def chunk_ids(known_ids: set, size: int | None = None) -> list:
    """Deterministic slicing of scored unit ids into extraction chunks.

    `size` defaults to the module's CHUNK_SIZE at call time (not def time),
    so tests and callers can adjust it."""
    if size is None:
        size = CHUNK_SIZE
    ordered = sorted(known_ids)
    return [set(ordered[i:i + size]) for i in range(0, len(ordered), size)]


def build_extraction_prompt(spec, framing_suffix: str, known_ids: set,
                            situations: dict | None = None) -> str:
    ids_hint = ", ".join(sorted(known_ids)[:400])
    situation_block = ""
    relevant = {
        unit_id: s for unit_id, s in (situations or {}).items()
        if unit_id in known_ids
    }
    if relevant:
        listed = "\n".join(
            f"- {unit_id}: given=\"{s['given']}\" when=\"{s['when']}\""
            for unit_id, s in sorted(relevant.items())
        )
        situation_block = (
            "\nCANONICAL SITUATIONS (copy given/when VERBATIM — do not reword): "
            "for each unit below, include exactly 1 assertion whose given and "
            "when are copied verbatim from this list and whose then states the "
            "outcome as YOU understand it from the whole specification, with "
            "cited lines:\n"
            f"{listed}\n"
        )
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
        "requirement that mandates observable behaviour; extract ONLY these "
        f"requirement units and no others: {ids_hint}.\n"
        f"{situation_block}\n"
        "SPECIFICATION (line-numbered):\n"
        f"{v1.numbered_text(spec)}\n\n"
        "Return ONLY a JSON object: {\"requirements\": {\"<REQ-ID>\": {\"edges\": "
        "[{\"s\": str, \"type\": str, \"t\": str, \"line\": int, \"conf\": float}], "
        "\"assumptions\": [{\"text\": str, \"line\": int}], \"assertions\": "
        "[{\"given\": str, \"when\": str, \"then\": str, \"lines\": [int]}]}}}. "
        "No prose, no fences preferred."
    )


def validate_graph(payload: dict, known_ids: set, max_line: int,
                   spec_lines: list | None = None,
                   situations: dict | None = None):
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
        canonical = (situations or {}).get(req_id)
        if canonical is not None:
            expected = (norm(canonical["given"]), norm(canonical["when"]))
            if not any(a.situation == expected and a.lines for a in assertions):
                return v1.ParseFailure(
                    reason=(
                        f"{req_id} is missing the canonical-situation assertion: "
                        f"exactly 1 assertion must copy given=\"{canonical['given']}\" "
                        f"when=\"{canonical['when']}\" verbatim, with cited lines"
                    )
                )
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


def aggregate_passes(pass_scores: list, threshold: float = 0.5) -> dict:
    """Cross-pass stability of per-requirement scores (native ≥2-run intersection).

    ``pass_scores`` is a list (one per measurement pass) of ``score_requirements``
    outputs. Returns, per requirement present in every pass, the mean/stdev/
    min/max of its score, and a ``stable_low`` flag set only when the score is
    below ``threshold`` in EVERY pass — the trustworthy fracture set. Also
    returns the global SR mean/stdev across passes and the extraction-noise
    floor = mean over requirements of the per-requirement cross-pass stdev
    (how much a per-requirement score wobbles between identical runs)."""
    import statistics as _st

    common = set(pass_scores[0])
    for scores in pass_scores[1:]:
        common &= set(scores)
    per_req: dict = {}
    for req_id in sorted(common):
        series = [scores[req_id]["score"] for scores in pass_scores]
        stdev = _st.pstdev(series) if len(series) > 1 else 0.0
        per_req[req_id] = {
            "mean": _st.mean(series),
            "stdev": stdev,
            "min": min(series),
            "max": max(series),
            "passes": len(series),
            # Real fracture: low in every pass (the intersection), and even the
            # optimistic bound (mean+stdev) stays under threshold.
            "stable_low": all(s < threshold for s in series),
            "noise_bounded_low": (_st.mean(series) + stdev) < threshold,
        }
    sr_series = [overall_score(scores) for scores in pass_scores]
    stdevs = [v["stdev"] for v in per_req.values()]
    return {
        "passes": len(pass_scores),
        "sr_mean": _st.mean(sr_series),
        "sr_stdev": _st.pstdev(sr_series) if len(sr_series) > 1 else 0.0,
        "sr_series": [round(x, 4) for x in sr_series],
        "extraction_noise_floor": _st.mean(stdevs) if stdevs else 0.0,
        "per_requirement": per_req,
        "stable_low": sorted(r for r, v in per_req.items() if v["stable_low"]),
    }


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
        score = sum(pair_scores) / len(pair_scores) if pair_scores else 1.0
        mean_edges = sum(edge_counts) / len(edge_counts) if edge_counts else 0.0
        result[req_id] = {
            "score": score,
            "readers_covering": len(edge_counts),
            "mean_edges": mean_edges,
            "assumption_load": (
                sum(assumption_counts) / len(assumption_counts) if assumption_counts else 0.0
            ),
            "near_misses": near,
            # "Converged but not trustworthy": high agreement over minimal
            # content — the vagueness failure mode measured live (a vague
            # mutant SCORED HIGHER). Agreement without substance is flagged,
            # never celebrated.
            "thin_consensus": bool(score >= 0.8 and mean_edges <= 1.5
                                   and len(edge_counts) >= 2),
        }
    return result


def overall_score(per_req: dict) -> float:
    if not per_req:
        return 1.0
    return sum(v["score"] for v in per_req.values()) / len(per_req)


# ── Witnesses + localization (pure) ─────────────────────────────────────────


def _then_overlap(a: str, b: str) -> float:
    """Word-set Jaccard of two then-clauses (phrasing-variant detector)."""
    wa, wb = _words(a), _words(b)
    if not wa and not wb:
        return 1.0
    return len(wa & wb) / len(wa | wb)


PHRASING_VARIANT_OVERLAP = 0.34


def find_witnesses(readers: list) -> tuple:
    """Witness CANDIDATES: same (given, when), materially different then.

    Two then-clauses whose word overlap is >= PHRASING_VARIANT_OVERLAP are a
    phrasing variant (same meaning, different words — found live: W1 restated
    one spec line twice), counted but never a witness. True behavioural
    verification (exhibiting the incompatibility) is v4; everything reported
    here is a candidate, and is labelled so. Returns (candidates, variant_count).
    """
    witnesses: list[Witness] = []
    variants = 0
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
            grounded = [(no, a) for no, a in entries if a.lines]
            distinct: dict = {}
            for no, assertion in grounded:
                distinct.setdefault(norm(assertion.then), (no, assertion))
            if len(distinct) < 2:
                continue
            sides = sorted(distinct.values(), key=lambda pair: pair[0])[:2]
            overlap = _then_overlap(sides[0][1].then, sides[1][1].then)
            if overlap >= PHRASING_VARIANT_OVERLAP:
                variants += 1
                continue
            negated = [bool(_words(a.then) & NEGATION_MARKERS) for _, a in sides]
            kind = (
                "negation-asymmetric"
                if negated[0] != negated[1]
                else "candidate"
            )
            witnesses.append(Witness(req_id=req_id, situation=situation,
                                     sides=sides, kind=kind))
    return witnesses, variants


def _evidence_lines(interp: ReqInterpretation | None) -> set[int]:
    if interp is None:
        return set()
    cited = {edge.line for edge in interp.edges}
    for assertion in interp.assertions:
        cited.update(assertion.lines)
    return cited


def evidence_metrics(readers: list) -> dict:
    """Requirement-local evidence overlap and citation coverage.

    This compares where parallel readers found evidence. It does not measure
    temporal critical-fact retention, which requires dialectic rounds.
    """
    requirement_ids = sorted(
        {req_id for reader in readers for req_id in reader.requirements}
    )
    per_requirement: dict = {}
    nonempty_cells = 0
    overlaps: list[float] = []
    for req_id in requirement_ids:
        per_reader = [
            _evidence_lines(reader.requirements.get(req_id))
            for reader in readers
        ]
        nonempty = sum(bool(lines) for lines in per_reader)
        nonempty_cells += nonempty
        union = set().union(*per_reader) if per_reader else set()
        if union:
            intersection = set(per_reader[0])
            for cited in per_reader[1:]:
                intersection &= cited
            overlap: float | None = len(intersection) / len(union)
            overlaps.append(overlap)
        else:
            overlap = None
        per_requirement[req_id] = {
            "overlap": overlap,
            "reader_coverage": nonempty / len(readers) if readers else 0.0,
            "union_lines": len(union),
        }
    total_cells = len(requirement_ids) * len(readers)
    return {
        "mean_overlap": sum(overlaps) / len(overlaps) if overlaps else None,
        "coverage": nonempty_cells / total_cells if total_cells else 0.0,
        "per_requirement": per_requirement,
    }


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
                  run_date: str, dropped: list,
                  phrasing_variants: int = 0,
                  evidence: dict | None = None,
                  stability: dict | None = None) -> str:
    lines: list[str] = []
    lines.append("# Semantic Reproducibility Report")
    lines.append("")
    lines.append(f"- **Specification:** {spec_path}")
    lines.append(f"- **Run date:** {run_date}")
    lines.append(
        f"- **Readers:** {len(readers)} completed"
        + (f" ({len(dropped)} dropped: {', '.join(dropped)})" if dropped else "")
    )
    thin = sorted(r for r, v in per_req.items() if v.get("thin_consensus"))
    mean_load = (
        sum(v["assumption_load"] for v in per_req.values()) / len(per_req)
        if per_req else 0.0
    )
    lines.append("- **Measurement vector** (no single number tells this story):")
    lines.append(f"  - semantic convergence: {sr:.3f} — {_grade(sr)}")
    lines.append(f"  - witness candidates (unverified): {len(witnesses)}"
                 f" · phrasing variants filtered: {phrasing_variants}")
    lines.append(f"  - assumption load (mean/req): {mean_load:.2f}")
    lines.append(f"  - untrusted convergence (thin consensus): {len(thin)}"
                 + (f" — {', '.join(thin[:8])}" if thin else ""))
    evidence = evidence or {
        "mean_overlap": None,
        "coverage": 0.0,
        "per_requirement": {},
    }
    overlap_text = (
        "N/A"
        if evidence["mean_overlap"] is None
        else f"{evidence['mean_overlap']:.2f}"
    )
    lines.append(
        f"  - evidence overlap (mean/requirement): {overlap_text}"
    )
    lines.append(f"  - evidence coverage: {evidence['coverage']:.2f}")
    lines.append(f"  - requirements measured: {len(per_req)}")
    ungrounded = ", ".join(f"R{r.reader_no}={r.ungrounded_edges}" for r in readers)
    lines.append(f"- **Ungrounded edges dropped:** {ungrounded}")
    if any(r.failed_chunks for r in readers):
        chunk_note = ", ".join(
            f"R{r.reader_no}={r.failed_chunks}" for r in readers if r.failed_chunks
        )
        lines.append(f"- **Failed extraction chunks (coverage gaps):** {chunk_note}")
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
    lines.append("## Divergence witness candidates "
                 "(heuristic — behavioural verification is v4)")
    lines.append("")
    if not witnesses:
        lines.append("None — no materially divergent grounded then-clauses found.")
        lines.append("")
    ordered = sorted(witnesses, key=lambda w: per_req.get(w.req_id, {}).get("score", 1.0))
    for index, witness in enumerate(ordered, start=1):
        (no_a, a), (no_b, b) = witness.sides
        lines.append(
            f"### W{index}. [{witness.kind}] {witness.req_id} — "
            f"given \"{a.given}\", when \"{a.when}\""
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
    if stability is not None:
        lines.append("")
        lines.append("## Cross-pass stability "
                     f"({stability['passes']} passes — trustworthy scores)")
        lines.append("")
        lines.append(
            f"- **SR mean:** {stability['sr_mean']:.3f} "
            f"± {stability['sr_stdev']:.3f} (across passes: "
            f"{stability['sr_series']})")
        lines.append(
            f"- **Extraction-noise floor:** {stability['extraction_noise_floor']:.3f} "
            "(mean per-requirement score wobble between identical runs — "
            "differences below this are noise, not signal)")
        stable_low = stability["stable_low"]
        lines.append(
            f"- **Stable-low requirements ({len(stable_low)}):** "
            + (", ".join(stable_low) if stable_low else "none")
            + " — low in EVERY pass; the real fracture set")
        lines.append("")
        lines.append("| Requirement | mean | ±stdev | min–max | stable-low |")
        lines.append("|---|---|---|---|---|")
        for req_id, v in sorted(stability["per_requirement"].items(),
                                key=lambda kv: kv[1]["mean"]):
            flag = "✓" if v["stable_low"] else ""
            lines.append(
                f"| {req_id} | {v['mean']:.2f} | {v['stdev']:.2f} "
                f"| {v['min']:.2f}–{v['max']:.2f} | {flag} |")
        lines.append("")
    return "\n".join(lines)


def build_sidecar(spec_path: Path, readers: list, per_req: dict, sr: float,
                  witnesses: list, fractures: dict, run_date: str,
                  evidence: dict | None = None,
                  stability: dict | None = None) -> dict:
    sidecar_stability = stability
    return {
        "specification": str(spec_path),
        "run_date": run_date,
        "stability": sidecar_stability,
        "readers": [
            {
                "reader": r.reader_no,
                "framing": r.framing,
                "provider": r.provider,
                "model_tag": r.model_tag,
                "ungrounded_edges": r.ungrounded_edges,
                # v4 layer separation: understanding (what the text asserts)
                # vs proto-justification (what the reading relies on / implies).
                # The full Justification Graph arrives via dialectic traces.
                "requirements": {
                    req_id: {
                        "understanding": {
                            "edges": [
                                {"s": e.s, "type": e.type, "t": e.t,
                                 "line": e.line, "conf": e.conf}
                                for e in interp.edges
                            ],
                        },
                        "proto_justification": {
                            "assumptions": interp.assumptions,
                            "assertions": [
                                {"given": a.given, "when": a.when,
                                 "then": a.then, "lines": a.lines}
                                for a in interp.assertions
                            ],
                        },
                    }
                    for req_id, interp in r.requirements.items()
                },
            }
            for r in readers
        ],
        "per_requirement": per_req,
        "semantic_reproducibility": sr,
        "thin_consensus": sorted(
            r for r, v in per_req.items() if v.get("thin_consensus")
        ),
        "evidence": evidence or {
            "mean_overlap": None,
            "coverage": 0.0,
            "per_requirement": {},
        },
        "witnesses": [
            {
                "requirement": w.req_id,
                "kind": w.kind,
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
    parser.add_argument(
        "--readers",
        type=v1._positive_int,
        default=3,
        help="readers PER MODEL command (total readers = models × this value; "
             "cost scales accordingly); framings repeat in a fixed cycle",
    )
    parser.add_argument("--families", default=",".join(DEFAULT_FAMILIES))
    parser.add_argument(
        "--passes", type=v1._positive_int, default=1,
        help="repeat the whole measurement N times; report per-requirement "
             "mean/stdev + the extraction-noise floor, and the stable-low set "
             "(low in EVERY pass) — makes per-requirement scores trustworthy",
    )
    parser.add_argument(
        "--model-cmd",
        "--claude-cmd",
        dest="model_commands",
        action="append",
        default=None,
        help="repeatable PROVIDER=COMMAND; each model receives every reader framing",
    )
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)
    commands = [
        parse_model_command(value)
        # Environment resolution supplies exactly ONE provider (never a second
        # family into a v3 run); explicit --model-cmd overrides everything.
        for value in (options.model_commands
                      or [v1.resolve_model_command(None)[0]])
    ]
    return commands, options


def main(argv: list | None = None) -> int:
    try:
        model_commands, options = parse_args(
            list(sys.argv[1:]) if argv is None else list(argv)
        )
    except v1.ArgumentFailure as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: {exc}")
    configs = {
        model_command: v1.RunConfig(
            spec_path=options.spec_path,
            max_questions=1,
            model_command=model_command.command,
            timeout_seconds=options.timeout,
            model_protocol=model_command.protocol,
        )
        for model_command in model_commands
    }
    # Duplicate --model-cmd entries intentionally collapse to one RunConfig
    # here (dict key dedupe): their ReaderJobs still run separately and share
    # the config — identical readers, one preflight. Not a bug.
    config = configs[model_commands[0]]
    for candidate in configs.values():
        failure = v1.preflight(candidate)
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

    # Canonical situations from the controlled grammar (lexicon GIVEN/WHEN
    # fields): every reader answers the SAME situations, so witness-channel
    # collisions are guaranteed by construction instead of sampled by luck
    # (the 27-vs-0 A/B instability). Empty for non-lexicon specs.
    situations = parse_controlled_situations(spec)
    chunks = chunk_ids(known_ids)
    jobs = build_reader_jobs(model_commands, options.readers, FRAMINGS)

    def _run_pass(pass_offset: int):
        """One full K-reader measurement. Returns (readers, dropped)."""
        readers: list[ReaderGraph] = []
        dropped: list[str] = []
        for job in jobs:
            reader_config = configs[job.model_command]
            merged: dict = {}
            ungrounded_total = 0
            failed_chunks = 0
            for chunk_no, chunk in enumerate(chunks, start=1):
                outcome = v1.execute_round(
                    reader_config,
                    build_extraction_prompt(spec, job.framing_suffix, chunk,
                                            situations=situations),
                    lambda payload, _chunk=chunk: validate_graph(
                        payload, _chunk, len(spec.lines), spec_lines=spec.lines,
                        situations=situations,
                    ),
                    round_no=pass_offset * 10000 + job.reader_no * 100 + chunk_no,
                    spec_dir=spec_dir,
                )
                if isinstance(outcome, v1.RoundExit):
                    failed_chunks += 1
                    continue
                requirements, ungrounded = outcome
                merged.update(requirements)
                ungrounded_total += ungrounded
            if failed_chunks * 2 > len(chunks):
                dropped_label = job.framing_name
                if len(model_commands) > 1:
                    dropped_label += f"/{job.model_command.model_tag}"
                dropped.append(f"R{job.reader_no}({dropped_label})")
                continue
            readers.append(ReaderGraph(
                reader_no=job.reader_no, framing=job.framing_name,
                provider=job.model_command.provider,
                model_tag=job.model_command.model_tag,
                requirements=merged, ungrounded_edges=ungrounded_total,
                failed_chunks=failed_chunks,
            ))
        return readers, dropped

    pass_scores: list[dict] = []
    readers: list[ReaderGraph] = []
    dropped: list[str] = []
    for pass_no in range(1, options.passes + 1):
        readers, dropped = _run_pass(pass_no)
        if len(readers) < 2:
            return v1.fail(
                v1.EXIT_UNUSABLE_OUTPUT,
                f"unusable model output: pass {pass_no} completed fewer than 2 "
                f"readers ({len(readers)} of {len(jobs)}; dropped: "
                f"{', '.join(dropped) or 'none'})",
            )
        pass_scores.append(score_requirements(readers))

    # The full rich report (witnesses, fractures, evidence) uses the last pass;
    # stability (per-requirement mean/stdev + noise floor) aggregates all passes.
    per_req = pass_scores[-1]
    sr = overall_score(per_req)
    stability = aggregate_passes(pass_scores) if options.passes > 1 else None
    witnesses, phrasing_variants = find_witnesses(readers)
    fractures = fracture_lines(readers, per_req, witnesses)
    evidence = evidence_metrics(readers)
    run_date = datetime.now().strftime("%Y-%m-%d")

    report = render_report(spec, config.spec_path, readers, per_req, sr,
                           witnesses, fractures, run_date, dropped,
                           phrasing_variants=phrasing_variants,
                           evidence=evidence, stability=stability)
    sidecar = build_sidecar(config.spec_path, readers, per_req, sr, witnesses,
                            fractures, run_date,
                            evidence=evidence, stability=stability)
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
    if stability is not None:
        print(
            f"Stability ({stability['passes']} passes): "
            f"SR {stability['sr_mean']:.3f} ±{stability['sr_stdev']:.3f}; "
            f"noise floor {stability['extraction_noise_floor']:.3f}; "
            f"stable-low: {', '.join(stability['stable_low']) or 'none'}"
        )
    worst = sorted(per_req.items(), key=lambda kv: kv[1]["score"])[:3]
    for req_id, values in worst:
        print(f"  lowest: {req_id} = {values['score']:.2f}")
    if options.json:
        print(json.dumps(sidecar, indent=1))
    return v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
