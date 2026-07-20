#!/usr/bin/env python3
"""SUE v2 — multi-reader consensus + bounded Socratic elenchus over sue_challenge.

K isolated readers each run SUE v1's two-round challenge with a distinct framing;
findings are clustered deterministically (target + category + evidence overlap —
no LLM merging), and stable clusters (reader support >= min-support) receive one
follow-up round whose questions must be premised on the parent's verdict and
quoted evidence (structurally validated). Report: socratic-consensus.md beside
the challenged spec. Design: docs/superpowers/specs/2026-07-19-sue-v2-consensus-design.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


def _load_v1():
    """Load sue_challenge.py from this script's directory (import-safe module)."""
    path = Path(__file__).resolve().parent / "sue_challenge.py"
    spec = importlib.util.spec_from_file_location("sue_challenge", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("sue_challenge", module)
    spec.loader.exec_module(module)
    return module


v1 = _load_v1()

REPORT_FILENAME = "socratic-consensus.md"
FOLLOWUP_ID_RE = __import__("re").compile(r"^F[1-9][0-9]*$")

FRAMINGS = (
    (
        "structural",
        "Framing: map the entities, relations and obligations of each requirement "
        "precisely as written; challenge structural gaps.",
    ),
    (
        "behavioural",
        "Framing: focus on observable behaviour each requirement mandates — "
        "triggers, conditions, outcomes, and what blocks them; challenge "
        "behavioural gaps.",
    ),
    (
        "adversarial",
        "Framing: read literally and look for what the text silently relies on; "
        "challenge hidden assumptions and exploitable ambiguity.",
    ),
)


@dataclass(frozen=True)
class ReaderResult:
    """One reader's completed v1 challenge."""

    reader_no: int
    framing: str
    findings: list  # list[v1.Finding]
    answered_count: int


@dataclass
class Cluster:
    """Findings from distinct readers judged to expose the same gap."""

    cluster_id: str
    target: str
    category: str
    members: list = field(default_factory=list)  # list[tuple[int, v1.Finding]]

    @property
    def support(self) -> int:
        return len({reader_no for reader_no, _ in self.members})

    @property
    def representative(self):
        """Deterministic representative: the lowest-numbered reader's finding."""
        return min(self.members, key=lambda pair: pair[0])[1]

    @property
    def worst_verdict(self) -> str:
        verdicts = {finding.answer.verdict for _, finding in self.members}
        return "CONTRADICTED" if "CONTRADICTED" in verdicts else "UNANSWERABLE"


@dataclass(frozen=True)
class FollowUp:
    """One validated elenchus follow-up question."""

    id: str
    parent: str
    question: str
    premise_lines: list


# ── Consensus clustering (pure, deterministic) ──────────────────────────────


def _lines_overlap(a: list, b: list) -> bool:
    """Anchor rule: shared evidence line, or both citing none."""
    if not a and not b:
        return True
    return bool(set(a) & set(b))


def cluster_findings(readers: list) -> list:
    """Cluster findings across readers by (target, category, evidence overlap).

    Deterministic, order-stable: readers ascending, findings in rank order.
    A finding joins the first cluster with matching target+category and
    evidence-line overlap against ANY existing member; else starts a new one.
    """
    clusters: list[Cluster] = []
    for reader in sorted(readers, key=lambda r: r.reader_no):
        for finding in reader.findings:
            question = finding.question
            evidence = finding.answer.evidence_lines
            home = None
            for cluster in clusters:
                if cluster.target != question.target:
                    continue
                if cluster.category != question.category:
                    continue
                if any(
                    _lines_overlap(evidence, member.answer.evidence_lines)
                    for _, member in cluster.members
                ):
                    home = cluster
                    break
            if home is None:
                home = Cluster(
                    cluster_id=f"C{len(clusters) + 1}",
                    target=question.target,
                    category=question.category,
                )
                clusters.append(home)
            home.members.append((reader.reader_no, finding))
    return clusters


def split_stable(clusters: list, min_support: int) -> tuple[list, list]:
    """Stable (support >= min_support) vs sampling-noise clusters, rank-ordered."""

    def sort_key(cluster: Cluster):
        verdict_rank = 0 if cluster.worst_verdict == "CONTRADICTED" else 1
        return (verdict_rank, -cluster.support, cluster.cluster_id)

    stable = sorted(
        (c for c in clusters if c.support >= min_support), key=sort_key
    )
    noise = sorted(
        (c for c in clusters if c.support < min_support), key=sort_key
    )
    return stable, noise


# ── Elenchus round (follow-up generation + fresh answering) ─────────────────


def build_followup_prompt(spec, stable: list) -> str:
    """Prompt for the follow-up generator: parents with verdicts + evidence."""
    blocks = []
    for cluster in stable:
        finding = cluster.representative
        quoted = "\n".join(
            v1._quoted_evidence(spec, finding.answer.evidence_lines)
        )
        blocks.append(
            f"CLUSTER {cluster.cluster_id} (target {cluster.target}, "
            f"verdict {cluster.worst_verdict}):\n"
            f"Parent question: {finding.question.question}\n"
            f"Answer given from the specification text alone: {finding.answer.answer}\n"
            f"Evidence lines cited:\n{quoted}"
        )
    parents = "\n\n".join(blocks)
    return (
        "You are continuing a Socratic examination of a specification. For each "
        "cluster below, the parent question could not be answered (or exposed a "
        "contradiction) from the specification text. Produce EXACTLY ONE follow-up "
        "question per cluster that takes the parent's answer and evidence as its "
        "premise and drills toward the minimal missing decision that would close "
        "the gap. Each follow-up MUST reference at least one of the parent's cited "
        "evidence lines in premise_lines (empty only if the parent cited none).\n\n"
        f"{parents}\n\n"
        "Return ONLY a JSON object:\n"
        '{"followups": [{"id": "F1", "parent": "<cluster id>", '
        '"question": "<text>", "premise_lines": [<int>, ...]}]}\n'
        "Use sequential ids F1, F2, ... in cluster order. No other keys, no prose."
    )


def validate_followups(payload: dict, stable: list):
    """Strict chain validation: parent exists, premise cites parent evidence.

    Returns list[FollowUp] or v1.ParseFailure.
    """
    by_id = {cluster.cluster_id: cluster for cluster in stable}
    raw = payload.get("followups")
    if not isinstance(raw, list) or not raw:
        return v1.ParseFailure(reason="followups must be a non-empty list")
    followups: list[FollowUp] = []
    seen_parents: set[str] = set()
    for index, item in enumerate(raw):
        label = f"followups[{index}]"
        if not isinstance(item, dict):
            return v1.ParseFailure(reason=f"{label} must be an object")
        fid = item.get("id")
        if not isinstance(fid, str) or not FOLLOWUP_ID_RE.match(fid):
            return v1.ParseFailure(reason=f"{label}.id must match F1..Fn")
        parent = item.get("parent")
        cluster = by_id.get(parent) if isinstance(parent, str) else None
        if cluster is None:
            return v1.ParseFailure(
                reason=f"{label}.parent {parent!r} names no stable cluster"
            )
        if parent in seen_parents:
            return v1.ParseFailure(reason=f"{label}: duplicate parent {parent}")
        seen_parents.add(parent)
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            return v1.ParseFailure(reason=f"{label}.question must be non-empty")
        premise = item.get("premise_lines")
        if not isinstance(premise, list) or not all(
            isinstance(n, int) and not isinstance(n, bool) for n in premise
        ):
            return v1.ParseFailure(
                reason=f"{label}.premise_lines must be a list of integers"
            )
        parent_lines = set(
            cluster.representative.answer.evidence_lines
        )
        if parent_lines and not (set(premise) & parent_lines):
            return v1.ParseFailure(
                reason=(
                    f"{label} breaks the chain: premise_lines cite none of the "
                    f"parent's evidence lines {sorted(parent_lines)}"
                )
            )
        if not parent_lines and premise:
            # Parent cited nothing; premise lines are tolerated but not required.
            pass
        followups.append(
            FollowUp(
                id=fid, parent=parent, question=question.strip(),
                premise_lines=list(premise),
            )
        )
    missing = set(by_id) - seen_parents
    if missing:
        return v1.ParseFailure(
            reason=f"no follow-up produced for cluster(s) {sorted(missing)}"
        )
    return followups


def retention_flag(parent_finding, followup_answer) -> bool:
    """Evidence-retention guard: flag when a chain answer abandons the parent's
    evidence entirely while claiming the question is ANSWERED."""
    parent_lines = set(parent_finding.answer.evidence_lines)
    child_lines = set(followup_answer.evidence_lines)
    return (
        followup_answer.verdict == "ANSWERED"
        and bool(parent_lines)
        and not (child_lines & parent_lines)
    )


# ── Report rendering (pure) ──────────────────────────────────────────────────


def render_report(
    spec,
    spec_path: Path,
    readers: list,
    stable: list,
    noise: list,
    chain: dict,
    retention: dict,
    run_date: str,
    dropped_readers: list,
    elenchus_note: str,
) -> str:
    lines: list[str] = []
    lines.append("# Socratic Consensus Report")
    lines.append("")
    lines.append(f"- **Specification:** {spec_path}")
    lines.append(f"- **Run date:** {run_date}")
    lines.append(
        f"- **Readers:** {len(readers)} completed"
        + (f" ({len(dropped_readers)} dropped: {', '.join(dropped_readers)})"
           if dropped_readers else "")
    )
    per_reader = ", ".join(
        f"R{r.reader_no}({r.framing})={len(r.findings)}" for r in readers
    )
    lines.append(f"- **Per-reader findings:** {per_reader}")
    lines.append(
        f"- **Stable findings:** {len(stable)} · sampling noise: {len(noise)}"
    )
    if elenchus_note:
        lines.append(f"- **Elenchus:** {elenchus_note}")
    lines.append("")
    lines.append("## Stable findings")
    lines.append("")
    if not stable:
        lines.append("None — no gap was reproduced by 2 or more readers.")
        lines.append("")
    for rank, cluster in enumerate(stable, start=1):
        rep = cluster.representative
        lines.append(
            f"### {rank}. [{cluster.worst_verdict}] "
            f"(support {cluster.support}) {rep.question.question}"
        )
        lines.append("")
        lines.append(f"- **Target:** {cluster.target}")
        lines.append(f"- **Category:** {cluster.category}")
        variants = [
            f"R{reader_no}: {finding.question.question}"
            for reader_no, finding in sorted(
                cluster.members, key=lambda pair: pair[0]
            )
            if finding is not rep
        ]
        if variants:
            lines.append("- **Reader variants:**")
            for variant in variants:
                lines.append(f"  - {variant}")
        lines.append("- **Evidence:**")
        lines.extend(v1._quoted_evidence(spec, rep.answer.evidence_lines))
        lines.append("")
        lines.append(rep.answer.answer)
        lines.append("")
        pair = chain.get(cluster.cluster_id)
        if pair is not None:
            followup, answer = pair
            flag = " ⚠ RETENTION-CHECK" if retention.get(cluster.cluster_id) else ""
            lines.append(
                f"**Elenchus [{answer.verdict}]{flag}:** {followup.question}"
            )
            lines.append("")
            lines.extend(v1._quoted_evidence(spec, answer.evidence_lines))
            lines.append("")
            lines.append(answer.answer)
            lines.append("")
    lines.append("## Sampling appendix (support below threshold)")
    lines.append("")
    if not noise:
        lines.append("Empty.")
    for cluster in noise:
        rep = cluster.representative
        lines.append(
            f"- [{cluster.worst_verdict}] (R{cluster.members[0][0]}, "
            f"{cluster.target}) {rep.question.question}"
        )
    lines.append("")
    total_audit = sum(r.answered_count for r in readers)
    lines.append(
        f"_Audit: {total_audit} question(s) across all readers were ANSWERED "
        "by the specification text and discarded; see per-reader runs for detail._"
    )
    lines.append("")
    return "\n".join(lines)


# ── Orchestration ────────────────────────────────────────────────────────────


def run_reader(config, spec, spec_dir: Path, reader_no: int, framing) -> object:
    """One isolated reader: v1 round 1 (framed) + round 2. ReaderResult or RoundExit."""
    name, suffix = framing
    round1_prompt = (
        v1.build_round1_prompt(spec, config.max_questions) + "\n\n" + suffix
    )
    result1 = v1.execute_round(
        config,
        round1_prompt,
        lambda payload: v1.validate_round1(payload, config.max_questions),
        round_no=1,
        spec_dir=spec_dir,
    )
    if isinstance(result1, v1.RoundExit):
        return result1
    questions, _truncated = result1
    pairs = [(q.id, q.question) for q in questions]
    result2 = v1.execute_round(
        config,
        v1.build_round2_prompt(spec, pairs),
        lambda payload: v1.validate_round2(payload, questions),
        round_no=2,
        spec_dir=spec_dir,
    )
    if isinstance(result2, v1.RoundExit):
        return result2
    findings, audit = v1.partition_answers(questions, result2)
    return ReaderResult(
        reader_no=reader_no,
        framing=name,
        findings=v1.rank_findings(findings),
        answered_count=len(audit),
    )


def run_elenchus(config, spec, spec_dir: Path, stable: list):
    """Follow-up generation + fresh answering. Returns (chain, retention, note)."""
    result_f = v1.execute_round(
        config,
        build_followup_prompt(spec, stable),
        lambda payload: validate_followups(payload, stable),
        round_no=3,
        spec_dir=spec_dir,
    )
    if isinstance(result_f, v1.RoundExit):
        return {}, {}, "skipped — follow-up generation failed after retry"
    followups = result_f
    as_questions = [
        v1.SocraticQuestion(
            id=f"Q{i + 1}",
            question=f.question,
            target=next(c.target for c in stable if c.cluster_id == f.parent),
            lines=list(f.premise_lines),
            category="follow-up",
        )
        for i, f in enumerate(followups)
    ]
    pairs = [(q.id, q.question) for q in as_questions]
    result_a = v1.execute_round(
        config,
        v1.build_round2_prompt(spec, pairs),
        lambda payload: v1.validate_round2(payload, as_questions),
        round_no=4,
        spec_dir=spec_dir,
    )
    if isinstance(result_a, v1.RoundExit):
        return {}, {}, "skipped — follow-up answering failed after retry"
    answers_by_id = {a.id: a for a in result_a}
    chain: dict = {}
    retention: dict = {}
    parent_by_cluster = {c.cluster_id: c.representative for c in stable}
    for i, followup in enumerate(followups):
        answer = answers_by_id.get(f"Q{i + 1}")
        if answer is None:
            continue
        chain[followup.parent] = (followup, answer)
        retention[followup.parent] = retention_flag(
            parent_by_cluster[followup.parent], answer
        )
    return chain, retention, f"{len(chain)} follow-up chain(s) completed"


def parse_args(argv: list) -> tuple:
    parser = v1._Parser(
        prog="sue_consensus.py",
        description=(
            "SUE v2: K isolated Socratic readers, deterministic consensus, and a "
            "bounded elenchus round on stable findings. "
            f"{v1.EGRESS_DISCLOSURE}"
        ),
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--readers", type=v1._positive_int, default=3)
    parser.add_argument("--min-support", type=v1._positive_int, default=2)
    parser.add_argument("--questions", type=v1._positive_int, default=15)
    parser.add_argument("--model-cmd", "--claude-cmd", dest="claude_cmd",
                        default=None,
                        help="PROVIDER=COMMAND or bare command; resolves from "
                             "ECHELON_LLM/markers when omitted")
    parser.add_argument(
        "--timeout", type=v1._positive_float, default=v1.DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument("--no-elenchus", action="store_true")
    options = parser.parse_args(argv)
    command, protocol = v1.resolve_model_command(options.claude_cmd)
    config = v1.RunConfig(
        spec_path=options.spec_path,
        max_questions=options.questions,
        model_command=command,
        model_protocol=protocol,
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
    if config.spec_path.resolve() == spec_dir / REPORT_FILENAME:
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: challenged file '{config.spec_path}' is the consensus "
            "report path itself — rename it to challenge it",
        )
    spec = v1.load_spec(config.spec_path)
    if not any(line.strip() for line in spec.lines):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{config.spec_path}' is empty or "
            "whitespace-only — nothing to challenge",
        )

    readers: list[ReaderResult] = []
    dropped: list[str] = []
    for reader_no in range(1, options.readers + 1):
        framing = FRAMINGS[(reader_no - 1) % len(FRAMINGS)]
        outcome = run_reader(config, spec, spec_dir, reader_no, framing)
        if isinstance(outcome, v1.RoundExit):
            dropped.append(f"R{reader_no}({framing[0]})")
            continue
        readers.append(outcome)
    if len(readers) < 2:
        return v1.fail(
            v1.EXIT_UNUSABLE_OUTPUT,
            "unusable model output: fewer than 2 readers completed "
            f"({len(readers)} of {options.readers}; dropped: "
            f"{', '.join(dropped) or 'none'})",
        )

    clusters = cluster_findings(readers)
    stable, noise = split_stable(clusters, options.min_support)

    chain: dict = {}
    retention: dict = {}
    if options.no_elenchus:
        elenchus_note = "disabled (--no-elenchus)"
    elif not stable:
        elenchus_note = "skipped — no stable findings"
    else:
        chain, retention, elenchus_note = run_elenchus(
            config, spec, spec_dir, stable
        )

    report = render_report(
        spec,
        config.spec_path,
        readers,
        stable,
        noise,
        chain,
        retention,
        datetime.now().strftime("%Y-%m-%d"),
        dropped,
        elenchus_note,
    )
    report_path = spec_dir / REPORT_FILENAME
    try:
        report_path.write_text(report, encoding="utf-8")
    except OSError as exc:
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: cannot write report '{report_path}': {exc}",
        )
    print(f"Report: {report_path}")
    contradicted = sum(1 for c in stable if c.worst_verdict == "CONTRADICTED")
    print(
        f"Stable findings — CONTRADICTED: {contradicted}, "
        f"UNANSWERABLE: {len(stable) - contradicted}; "
        f"sampling noise: {len(noise)}; {elenchus_note}"
    )
    for rank, cluster in enumerate(stable[:3], start=1):
        rep = cluster.representative
        print(
            f"  {rank}. [{cluster.worst_verdict}] (support {cluster.support}) "
            f"{rep.question.question}"
        )
    return v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
