#!/usr/bin/env python3
"""SUE Dialectic — adaptive Socratic examination of a specification (arm C).

One dialogue = a state machine over generic dialectic operators; Platonic lens
names are ONLY question-selection policies (deterministic transition tables).
Questions are deterministic templates; the model sits solely in the answering
seat, answering from the specification text alone with cited lines. APORIA is
a terminal state, never an operator. The turn limit is a safety bound, never
evidence of convergence.

Experimental status: this is arm C of the pre-registered reasoning-layer
experiment (docs/superpowers/specs/2026-07-19-sue-dialectic-design-draft.md).
It emits NO understanding score and performs NO spec edits.

Outputs beside the spec: socratic-dialogue.md + socratic-dialogue.json.
"""
from __future__ import annotations

import importlib.util
import json
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

REPORT_FILENAME = "socratic-dialogue.md"
JSON_FILENAME = "socratic-dialogue.json"

OPERATORS = (
    "DEFINE", "DISTINGUISH", "CAUSE_OR_CRITERION", "COUNTEREXAMPLE",
    "FOLLOW_CONSEQUENCE", "TEST_OPPOSITE", "DIVIDE", "REVISE",
)

TURN_VERDICTS = ("SUPPORTED", "PARTIAL", "SILENT", "CONTRADICTED")

ANSWER_TYPES = (
    "definition", "example", "criterion", "consequence", "distinction",
    "case-split", "revision", "none",
)

TERMINALS = (
    "RESOLVED",
    "APORIA_UNDEFINED",
    "APORIA_CONTRADICTED",
    "APORIA_UNDERDETERMINED",
    "BOUNDED_STOP",
)

MAX_REVISIONS = 1


# ── Question templates (deterministic; the only stochastic layer is the answer) ──


def build_question(operator: str, focus: str, claim: str, failure: str) -> str:
    templates = {
        "DEFINE": (
            f'What exactly does the specification define "{focus}" to be? '
            "State the definition the text commits to, citing its lines. If "
            "the text gives only examples or usages, say so."
        ),
        "DISTINGUISH": (
            f'What distinction does the text itself draw between a definition '
            f'of "{focus}" and mere examples or related notions — and where?'
        ),
        "CAUSE_OR_CRITERION": (
            f'By what criterion in the text would one recognize or verify '
            f'"{focus}"? Cite the lines that establish the criterion.'
        ),
        "COUNTEREXAMPLE": (
            "Construct, from the specification text alone, a case that "
            f"satisfies the text's own words yet violates the current "
            f"understanding: {claim}. If the text supports no such case, "
            "say so."
        ),
        "FOLLOW_CONSEQUENCE": (
            f"Assume the current understanding holds: {claim}. What "
            "consequences does the specification text then commit to? Cite "
            "lines; note any consequence the text elsewhere denies."
        ),
        "TEST_OPPOSITE": (
            f"Assume the opposite of the current understanding: NOT ({claim}). "
            "Which lines of the text would then be violated, if any? If the "
            "text tolerates the opposite reading, say so."
        ),
        "DIVIDE": (
            f'Split "{focus}" into the distinct cases the text itself treats '
            "differently. Enumerate the cases with their lines."
        ),
        "REVISE": (
            f"The current understanding failed: {failure}. Can the text "
            f'itself supply a corrected understanding of "{focus}"? State the '
            "revision with cited lines, or say the text cannot."
        ),
    }
    return templates[operator]


# ── Lens policies: (operator, verdict) -> next operator or terminal ──────────

_SHARED_POLICY = {
    ("COUNTEREXAMPLE", "SUPPORTED"): "REVISE",       # counterexample found
    ("COUNTEREXAMPLE", "PARTIAL"): "DIVIDE",
    ("COUNTEREXAMPLE", "SILENT"): "FOLLOW_CONSEQUENCE",  # claim survives
    ("COUNTEREXAMPLE", "CONTRADICTED"): "APORIA_CONTRADICTED",
    ("FOLLOW_CONSEQUENCE", "SUPPORTED"): "RESOLVED",
    ("FOLLOW_CONSEQUENCE", "PARTIAL"): "DIVIDE",
    ("FOLLOW_CONSEQUENCE", "SILENT"): "RESOLVED",
    ("FOLLOW_CONSEQUENCE", "CONTRADICTED"): "REVISE",
    ("DIVIDE", "SUPPORTED"): "COUNTEREXAMPLE",
    ("DIVIDE", "PARTIAL"): "APORIA_UNDERDETERMINED",
    ("DIVIDE", "SILENT"): "APORIA_UNDERDETERMINED",
    ("DIVIDE", "CONTRADICTED"): "APORIA_CONTRADICTED",
    ("REVISE", "SUPPORTED"): "COUNTEREXAMPLE",        # test the revision
    ("REVISE", "PARTIAL"): "COUNTEREXAMPLE",
    ("REVISE", "SILENT"): "APORIA_CONTRADICTED",      # text cannot repair
    ("REVISE", "CONTRADICTED"): "APORIA_CONTRADICTED",
}

LENSES = {
    # Euthyphro — definition, essence, examples-vs-definition, circularity.
    "euthyphro": {
        "start": "DEFINE",
        "policy": {
            ("DEFINE", "SUPPORTED"): "COUNTEREXAMPLE",
            ("DEFINE", "PARTIAL"): "DISTINGUISH",
            ("DEFINE", "SILENT"): "CAUSE_OR_CRITERION",
            ("DEFINE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DISTINGUISH", "SUPPORTED"): "COUNTEREXAMPLE",
            ("DISTINGUISH", "PARTIAL"): "CAUSE_OR_CRITERION",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Meno — criterion of recognition and verifiability.
    "meno": {
        "start": "CAUSE_OR_CRITERION",
        "policy": {
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "DEFINE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DEFINE", "SUPPORTED"): "COUNTEREXAMPLE",
            ("DEFINE", "PARTIAL"): "DISTINGUISH",
            ("DEFINE", "SILENT"): "APORIA_UNDEFINED",
            ("DEFINE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DISTINGUISH", "SUPPORTED"): "COUNTEREXAMPLE",
            ("DISTINGUISH", "PARTIAL"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Parmenides — consequences of the claim and of its negation.
    "parmenides": {
        "start": "FOLLOW_CONSEQUENCE",
        "policy": {
            ("FOLLOW_CONSEQUENCE", "SUPPORTED"): "TEST_OPPOSITE",
            ("FOLLOW_CONSEQUENCE", "PARTIAL"): "DIVIDE",
            ("FOLLOW_CONSEQUENCE", "SILENT"): "TEST_OPPOSITE",
            ("FOLLOW_CONSEQUENCE", "CONTRADICTED"): "REVISE",
            ("TEST_OPPOSITE", "SUPPORTED"): "RESOLVED",   # negation violates text
            ("TEST_OPPOSITE", "PARTIAL"): "DIVIDE",
            ("TEST_OPPOSITE", "SILENT"): "APORIA_UNDERDETERMINED",
            ("TEST_OPPOSITE", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Cratylus — names, synonymy, lexical stability.
    "cratylus": {
        "start": "DISTINGUISH",
        "policy": {
            ("DISTINGUISH", "SUPPORTED"): "DEFINE",
            ("DISTINGUISH", "PARTIAL"): "DIVIDE",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDERDETERMINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DEFINE", "SUPPORTED"): "TEST_OPPOSITE",
            ("DEFINE", "PARTIAL"): "DIVIDE",
            ("DEFINE", "SILENT"): "APORIA_UNDEFINED",
            ("DEFINE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("TEST_OPPOSITE", "SUPPORTED"): "RESOLVED",
            ("TEST_OPPOSITE", "PARTIAL"): "DIVIDE",
            ("TEST_OPPOSITE", "SILENT"): "APORIA_UNDERDETERMINED",
            ("TEST_OPPOSITE", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Theaetetus — knowledge as justified account; drills claims whose
    # justification the text cannot supply (evidence-link gaps). Unlike meno
    # (criterion -> hunt counterexample), a supported justification is tested
    # by whether it actually entails what is claimed.
    "theaetetus": {
        "start": "CAUSE_OR_CRITERION",
        "policy": {
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "FOLLOW_CONSEQUENCE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "DEFINE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DEFINE", "SUPPORTED"): "FOLLOW_CONSEQUENCE",
            ("DEFINE", "PARTIAL"): "DIVIDE",
            ("DEFINE", "SILENT"): "APORIA_UNDEFINED",
            ("DEFINE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            # DEFINE is reachable, so the examples-are-not-a-definition
            # refinement can route here; the machine must stay closed.
            ("DISTINGUISH", "SUPPORTED"): "FOLLOW_CONSEQUENCE",
            ("DISTINGUISH", "PARTIAL"): "CAUSE_OR_CRITERION",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Sophist — method of division, look-alikes, non-being; drills missing
    # boundaries and exceptions (M3-shaped). Division separates the cases,
    # distinction separates the look-alikes, and the excluded case is tested:
    # a tolerated "excluded" case means the boundary is missing.
    "sophist": {
        "start": "DIVIDE",
        "policy": {
            ("DIVIDE", "SUPPORTED"): "DISTINGUISH",
            ("DIVIDE", "PARTIAL"): "TEST_OPPOSITE",
            ("DIVIDE", "SILENT"): "APORIA_UNDERDETERMINED",
            ("DIVIDE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("DISTINGUISH", "SUPPORTED"): "TEST_OPPOSITE",
            ("DISTINGUISH", "PARTIAL"): "TEST_OPPOSITE",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDERDETERMINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("TEST_OPPOSITE", "SUPPORTED"): "RESOLVED",
            ("TEST_OPPOSITE", "PARTIAL"): "DIVIDE",
            ("TEST_OPPOSITE", "SILENT"): "APORIA_UNDERDETERMINED",
            ("TEST_OPPOSITE", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Gorgias — rhetoric vs substance; drills persuasive-but-thin text (the
    # thin_consensus failure mode). A claim whose consequences the text is
    # SILENT on is rhetoric without commitments — never RESOLVED (overrides
    # the shared FOLLOW_CONSEQUENCE/SILENT -> RESOLVED).
    "gorgias": {
        "start": "FOLLOW_CONSEQUENCE",
        "policy": {
            ("FOLLOW_CONSEQUENCE", "SUPPORTED"): "CAUSE_OR_CRITERION",
            ("FOLLOW_CONSEQUENCE", "PARTIAL"): "DIVIDE",
            ("FOLLOW_CONSEQUENCE", "SILENT"): "APORIA_UNDEFINED",
            ("FOLLOW_CONSEQUENCE", "CONTRADICTED"): "REVISE",
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Republic — each actor doing its own role; drills permission/actor
    # defects (the FR-001 class). Roles are distinguished, the permission
    # criterion is extracted, then a cross-role counterexample is hunted.
    "republic": {
        "start": "DISTINGUISH",
        "policy": {
            ("DISTINGUISH", "SUPPORTED"): "DIVIDE",
            ("DISTINGUISH", "PARTIAL"): "CAUSE_OR_CRITERION",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
    # Philebus — measure and mixture; drills unquantified constraints
    # ("fast", "large", no bound). No stated measure is the unlimited:
    # APORIA_UNDEFINED. A stated bound is tested by what would violate it.
    "philebus": {
        "start": "DEFINE",
        "policy": {
            ("DEFINE", "SUPPORTED"): "TEST_OPPOSITE",
            ("DEFINE", "PARTIAL"): "CAUSE_OR_CRITERION",
            ("DEFINE", "SILENT"): "APORIA_UNDEFINED",
            ("DEFINE", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("CAUSE_OR_CRITERION", "SUPPORTED"): "TEST_OPPOSITE",
            ("CAUSE_OR_CRITERION", "PARTIAL"): "COUNTEREXAMPLE",
            ("CAUSE_OR_CRITERION", "SILENT"): "APORIA_UNDEFINED",
            ("CAUSE_OR_CRITERION", "CONTRADICTED"): "APORIA_CONTRADICTED",
            # DEFINE is the start, so the refinement can route here.
            ("DISTINGUISH", "SUPPORTED"): "TEST_OPPOSITE",
            ("DISTINGUISH", "PARTIAL"): "DIVIDE",
            ("DISTINGUISH", "SILENT"): "APORIA_UNDEFINED",
            ("DISTINGUISH", "CONTRADICTED"): "APORIA_CONTRADICTED",
            ("TEST_OPPOSITE", "SUPPORTED"): "RESOLVED",
            ("TEST_OPPOSITE", "PARTIAL"): "DIVIDE",
            ("TEST_OPPOSITE", "SILENT"): "APORIA_UNDERDETERMINED",
            ("TEST_OPPOSITE", "CONTRADICTED"): "APORIA_CONTRADICTED",
        },
    },
}


def next_step(lens: str, operator: str, verdict: str, answer_type: str,
              revisions_used: int) -> str:
    """Deterministic next operator or terminal state.

    Refinement: a DEFINE answered only with examples goes to DISTINGUISH even
    when SUPPORTED (the Euthyphro move: examples are not a definition). The
    REVISE budget converts a would-be second revision into aporia.
    """
    if operator == "DEFINE" and verdict == "SUPPORTED" and answer_type == "example":
        return "DISTINGUISH"
    lens_policy = LENSES[lens]["policy"]
    step = lens_policy.get((operator, verdict))
    if step is None:
        step = _SHARED_POLICY[(operator, verdict)]
    if step == "REVISE" and revisions_used >= MAX_REVISIONS:
        return "APORIA_CONTRADICTED"
    return step


# ── Turn answer validation ───────────────────────────────────────────────────


@dataclass(frozen=True)
class Turn:
    turn_no: int
    operator: str
    question: str
    answer: str
    verdict: str
    answer_type: str
    evidence_lines: list
    claim: str | None
    retention_violation: bool


def validate_turn(payload: dict, operator: str, max_line: int):
    """Strict per-turn validation; returns dict or v1.ParseFailure."""
    if not isinstance(payload, dict):
        return v1.ParseFailure(reason="turn payload must be an object")
    answer = payload.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return v1.ParseFailure(reason="answer must be a non-empty string")
    verdict = payload.get("verdict")
    if verdict not in TURN_VERDICTS:
        return v1.ParseFailure(reason=f"verdict {verdict!r} not in {TURN_VERDICTS}")
    answer_type = payload.get("answer_type")
    if answer_type not in ANSWER_TYPES:
        return v1.ParseFailure(
            reason=f"answer_type {answer_type!r} not in {ANSWER_TYPES}"
        )
    lines = payload.get("evidence_lines")
    if not isinstance(lines, list) or not all(
        isinstance(n, int) and not isinstance(n, bool) for n in lines
    ):
        return v1.ParseFailure(reason="evidence_lines must be a list of integers")
    in_range = [n for n in lines if 1 <= n <= max_line]
    if verdict == "SILENT":
        if in_range:
            return v1.ParseFailure(
                reason="SILENT verdict must cite no in-range evidence lines"
            )
    elif not in_range:
        return v1.ParseFailure(
            reason=f"verdict {verdict} requires at least 1 in-range evidence line"
        )
    claim = payload.get("claim")
    if operator in ("DEFINE", "REVISE") and verdict in ("SUPPORTED", "PARTIAL"):
        if not isinstance(claim, str) or not claim.strip():
            return v1.ParseFailure(
                reason=f"{operator} with verdict {verdict} must state a claim"
            )
    return {
        "answer": answer.strip(),
        "verdict": verdict,
        "answer_type": answer_type,
        "evidence_lines": in_range,
        "claim": claim.strip() if isinstance(claim, str) and claim.strip() else None,
    }


def build_turn_prompt(spec, operator: str, question: str) -> str:
    return (
        "You are the answering voice of a specification under Socratic "
        "examination. Answer the question using ONLY the specification text "
        "below — no outside knowledge.\n\n"
        "SPECIFICATION (line-numbered):\n"
        f"{v1.numbered_text(spec)}\n\n"
        f"QUESTION ({operator}):\n{question}\n\n"
        "Return ONLY a JSON object:\n"
        '{"answer": str, "verdict": "SUPPORTED|PARTIAL|SILENT|CONTRADICTED", '
        '"answer_type": "definition|example|criterion|consequence|distinction|'
        'case-split|revision|none", "evidence_lines": [int], '
        '"claim": str}\n\n'
        "Verdict semantics: SUPPORTED = the text fully answers (cite lines); "
        "PARTIAL = the text answers part (cite lines); SILENT = the text does "
        "not answer (evidence_lines empty); CONTRADICTED = the text supports "
        "incompatible answers (cite both sides' lines). \"claim\" is required "
        "when the question asks you to state or revise an understanding and "
        "the text supports one."
    )


# ── Dialogue engine ──────────────────────────────────────────────────────────


def run_dialogue(config, spec, spec_dir: Path, lens: str, seed: str,
                 max_turns: int):
    """Execute one dialectic dialogue. Returns (turns, terminal, reason)."""
    turns: list[Turn] = []
    operator = LENSES[lens]["start"]
    claim = seed
    focus = seed
    failure = ""
    revisions_used = 0
    cumulative_evidence: set[int] = set()
    for turn_no in range(1, max_turns + 1):
        question = build_question(operator, focus, claim, failure)
        outcome = v1.execute_round(
            config,
            build_turn_prompt(spec, operator, question),
            lambda payload, _op=operator: validate_turn(
                payload, _op, len(spec.lines)
            ),
            round_no=turn_no,
            spec_dir=spec_dir,
        )
        if isinstance(outcome, v1.RoundExit):
            return turns, None, outcome
        retention_violation = False
        if (operator == "REVISE"
                and outcome["verdict"] in ("SUPPORTED", "PARTIAL")
                and cumulative_evidence
                and not (set(outcome["evidence_lines"]) & cumulative_evidence)):
            # Deliberative-Illusion guard: a revision that abandons every
            # previously cited line is flagged, never silently accepted.
            retention_violation = True
        turns.append(Turn(
            turn_no=turn_no,
            operator=operator,
            question=question,
            answer=outcome["answer"],
            verdict=outcome["verdict"],
            answer_type=outcome["answer_type"],
            evidence_lines=outcome["evidence_lines"],
            claim=outcome["claim"],
            retention_violation=retention_violation,
        ))
        cumulative_evidence.update(outcome["evidence_lines"])
        if outcome["claim"]:
            claim = outcome["claim"]
        if operator == "COUNTEREXAMPLE" and outcome["verdict"] == "SUPPORTED":
            failure = f"a text-supported counterexample: {outcome['answer'][:160]}"
        if operator == "FOLLOW_CONSEQUENCE" and outcome["verdict"] == "CONTRADICTED":
            failure = f"a denied consequence: {outcome['answer'][:160]}"
        step = next_step(lens, operator, outcome["verdict"],
                         outcome["answer_type"], revisions_used)
        if step == "REVISE":
            revisions_used += 1
        if step in TERMINALS:
            return turns, step, None
        operator = step
    return turns, "BOUNDED_STOP", None


# ── Rendering ────────────────────────────────────────────────────────────────

_TERMINAL_MEANING = {
    "RESOLVED": "the understanding survived counterexample and consequence "
                "tests — sharpened, not refuted",
    "APORIA_UNDEFINED": "no stable definition or criterion can be built from "
                        "the text",
    "APORIA_CONTRADICTED": "the text supports incompatible answers and cannot "
                           "repair them",
    "APORIA_UNDERDETERMINED": "more than one equally valid reading remains",
    "BOUNDED_STOP": "turn limit reached without a verdict — a safety bound, "
                    "not convergence",
}


def render_report(spec, spec_path: Path, lens: str, seed: str, target: str,
                  turns: list, terminal: str, run_date: str) -> str:
    lines: list[str] = []
    lines.append("# Socratic Dialogue Report")
    lines.append("")
    lines.append(f"- **Specification:** {spec_path}")
    lines.append(f"- **Run date:** {run_date}")
    lines.append(f"- **Lens:** {lens}")
    if target:
        lines.append(f"- **Target:** {target}")
    lines.append(f"- **Seed:** {seed}")
    retention_flags = sum(1 for t in turns if t.retention_violation)
    lines.append(f"- **Turns:** {len(turns)} · retention flags: {retention_flags}")
    lines.append(
        f"- **Terminal state:** {terminal} — {_TERMINAL_MEANING[terminal]}"
    )
    lines.append("")
    for turn in turns:
        flag = " ⚠ RETENTION" if turn.retention_violation else ""
        lines.append(
            f"## Turn {turn.turn_no} — {turn.operator} "
            f"[{turn.verdict}/{turn.answer_type}]{flag}"
        )
        lines.append("")
        lines.append(f"**Q:** {turn.question}")
        lines.append("")
        lines.append(f"**A:** {turn.answer}")
        lines.extend(v1._quoted_evidence(spec, turn.evidence_lines))
        if turn.claim:
            lines.append(f"**Claim now:** {turn.claim}")
        lines.append("")
    lines.append(
        "_This dialogue emits no understanding score; it is an auditable "
        "trace (arm C of the reasoning-layer experiment)._"
    )
    lines.append("")
    return "\n".join(lines)


def build_trace(spec_path: Path, lens: str, seed: str, target: str,
                turns: list, terminal: str, run_date: str) -> dict:
    return {
        "specification": str(spec_path),
        "run_date": run_date,
        "lens": lens,
        "seed": seed,
        "target": target or None,
        "terminal_state": terminal,
        "turns": [
            {
                "turn": t.turn_no,
                "operator": t.operator,
                "question": t.question,
                "answer": t.answer,
                "verdict": t.verdict,
                "answer_type": t.answer_type,
                "evidence_lines": t.evidence_lines,
                "claim": t.claim,
                "retention_violation": t.retention_violation,
            }
            for t in turns
        ],
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list):
    parser = v1._Parser(
        prog="sue_dialectic.py",
        description=(
            "SUE Dialectic: adaptive Socratic examination of one seed claim "
            "against a specification, through a Platonic lens. "
            f"{v1.EGRESS_DISCLOSURE}"
        ),
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("--lens", choices=sorted(LENSES), default="euthyphro")
    parser.add_argument("--seed", required=True,
                        help="the claim or term under examination")
    parser.add_argument("--target", default="",
                        help="optional requirement id label for the report")
    parser.add_argument("--max-turns", type=v1._positive_int, default=7)
    parser.add_argument("--model-cmd", "--claude-cmd", dest="claude_cmd",
                        default=None,
                        help="PROVIDER=COMMAND or bare command; resolves from "
                             "ECHELON_LLM/markers when omitted")
    parser.add_argument("--timeout", type=v1._positive_float,
                        default=v1.DEFAULT_TIMEOUT_SECONDS)
    options = parser.parse_args(argv)
    command, protocol = v1.resolve_model_command(options.claude_cmd)
    config = v1.RunConfig(
        spec_path=options.spec_path,
        max_questions=1,
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
    # Tool-specific input guards run BEFORE preflight: a report-path collision is
    # a bad-input error detectable without a model, so it must not be masked by
    # preflight's "model executable not found" (exit 2) when no CLI is installed
    # (e.g. CI). preflight still owns spec-readable / dir-writable / model checks.
    spec_dir = config.spec_path.resolve().parent
    if config.spec_path.resolve() in (
        spec_dir / REPORT_FILENAME, spec_dir / JSON_FILENAME
    ):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: challenged file '{config.spec_path}' is a dialogue "
            "report path — rename it to challenge it",
        )
    failure = v1.preflight(config)
    if failure is not None:
        return v1.fail(*failure)
    spec = v1.load_spec(config.spec_path)
    if not any(line.strip() for line in spec.lines):
        return v1.fail(
            v1.EXIT_BAD_INPUT,
            f"bad input: specification '{config.spec_path}' is empty or "
            "whitespace-only — nothing to examine",
        )

    turns, terminal, round_exit = run_dialogue(
        config, spec, spec_dir, options.lens, options.seed, options.max_turns
    )
    if terminal is None:
        return v1.fail(round_exit.exit_code, round_exit.diagnostic)

    run_date = datetime.now().strftime("%Y-%m-%d")
    report = render_report(spec, config.spec_path, options.lens, options.seed,
                           options.target, turns, terminal, run_date)
    trace = build_trace(config.spec_path, options.lens, options.seed,
                        options.target, turns, terminal, run_date)
    try:
        (spec_dir / REPORT_FILENAME).write_text(report, encoding="utf-8")
        (spec_dir / JSON_FILENAME).write_text(
            json.dumps(trace, indent=1), encoding="utf-8"
        )
    except OSError as exc:
        return v1.fail(v1.EXIT_BAD_INPUT, f"bad input: cannot write report: {exc}")
    print(f"Report: {spec_dir / REPORT_FILENAME}")
    retention_flags = sum(1 for t in turns if t.retention_violation)
    print(
        f"Dialogue [{options.lens}] — {len(turns)} turn(s) → {terminal}"
        + (f" · {retention_flags} retention flag(s)" if retention_flags else "")
    )
    for turn in turns:
        print(f"  T{turn.turn_no} {turn.operator}: {turn.verdict}/{turn.answer_type}")
    return v1.EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
