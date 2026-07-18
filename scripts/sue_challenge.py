#!/usr/bin/env python3
"""SUE challenge script — challenge a specification via Socratic dialogue.

Interrogates a markdown specification through a two-round Socratic dialogue
using two isolated model calls (default ``claude -p``):

- Round 1 asks the challenge model to generate probing questions about the
  specification.
- Round 2 asks a fresh, isolated reading of the same model to answer each
  question using only the specification text.

Questions the text cannot answer (UNANSWERABLE) or answers inconsistently
(CONTRADICTED) become findings in ``socratic-challenge.md``, written beside
the challenged specification. The engine asks, the text testifies, the human
decides.

Standalone contract: standard library only; reads exactly two kinds of input —
its command-line arguments and the challenged specification file (FR-045).
The challenged specification is never written (FR-042).

Privacy: challenged specification content is sent to the model provider via
the model command (NFR-003); see ``--help``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Shared constants — the three-way contract anchor between prompts,
# validators, and stub fixtures (ISS-206; contracts/model-command-contract.md)
# ---------------------------------------------------------------------------

CATEGORIES = (
    "ambiguity",
    "hidden-assumption",
    "contradiction",
    "undefined-term",
    "missing-boundary",
)

VERDICTS = ("ANSWERED", "UNANSWERABLE", "CONTRADICTED")

QUESTION_ID_RE = re.compile(r"^Q[1-9][0-9]*$")

REPORT_FILENAME = "socratic-challenge.md"
DEBUG_DIR_NAME = ".sue-debug"

EXIT_SUCCESS = 0
EXIT_BAD_INPUT = 1
EXIT_MODEL_COMMAND_MISSING = 2
EXIT_UNUSABLE_OUTPUT = 3

DEFAULT_QUESTION_COUNT = 15
DEFAULT_MODEL_COMMAND = "claude"
DEFAULT_TIMEOUT_SECONDS = 300.0

EGRESS_DISCLOSURE = (
    "Privacy disclosure: challenged specification content\n"
    "is sent to the model provider via the model command."
)

ROUND1_PROMPT_TEMPLATE = """\
You are challenging a software specification through Socratic questioning.

The specification, with 1-based line numbers, is:

{numbered_spec}

Generate at most {max_questions} Socratic challenge questions that probe this
specification for weaknesses in exactly these 5 categories: ambiguity,
hidden-assumption, contradiction, undefined-term, missing-boundary.

Reply with a single JSON object, and nothing else, in this schema:

{{
  "questions": [
    {{
      "id": "Q1",
      "question": "<Socratic challenge question text>",
      "target": "<requirement identifier from the specification | general>",
      "lines": [12, 47],
      "category": "<ambiguity | hidden-assumption | contradiction | undefined-term | missing-boundary>"
    }}
  ]
}}

Rules: "id" values are unique and sequential (Q1, Q2, ...); "target" is a
requirement identifier taken from the specification or "general"; "lines"
lists the integer specification line numbers the question interrogates;
"category" is exactly one of the 5 tokens above.
"""

# The round-2 instruction wording deliberately avoids every round-1 category
# token and the words "category"/"target": the round-2 prompt must carry zero
# round-1 elements (FR-022, AC-011).
ROUND2_PROMPT_TEMPLATE = """\
You are answering questions about a software specification using only its
text. Do not use any outside knowledge.

The specification, with 1-based line numbers, is:

{numbered_spec}

The questions are:

{questions_json}

Answer every question using only the specification text above. Assign exactly
one verdict per question:

- ANSWERED: the text answers the question — quote the answering lines.
- UNANSWERABLE: the text cannot answer the question — name the gap.
- CONTRADICTED: the text gives conflicting answers — cite both sides.

Reply with a single JSON object, and nothing else, in this schema:

{{
  "answers": [
    {{
      "id": "Q1",
      "verdict": "<ANSWERED | UNANSWERABLE | CONTRADICTED>",
      "answer": "<answer text | named gap | both conflicting sides>",
      "evidence_lines": [12, 13]
    }}
  ]
}}

Rules: include exactly one answer for every question id, and no other ids;
"evidence_lines" lists the integer specification line numbers supporting the
verdict.
"""


# ---------------------------------------------------------------------------
# Dataclasses (data-model.md runtime entities)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunConfig:
    """The validated invocation of one challenge run (FR-001..FR-004, FR-007)."""

    spec_path: Path
    max_questions: int
    model_command: str
    timeout_seconds: float


@dataclass(frozen=True)
class SpecDocument:
    """The challenged specification, read exactly once; never written (FR-042)."""

    path: Path
    lines: list[str]


@dataclass(frozen=True)
class SocraticQuestion:
    """One round-1 output unit after strict validation (FR-016)."""

    id: str
    question: str
    target: str
    lines: list[int]
    category: str


@dataclass(frozen=True)
class Answer:
    """One round-2 output unit after strict validation (FR-024)."""

    id: str
    verdict: str
    answer: str
    evidence_lines: list[int]


@dataclass(frozen=True)
class Finding:
    """An Answer with verdict CONTRADICTED or UNANSWERABLE, joined and ranked."""

    rank: int
    question: SocraticQuestion
    answer: Answer


@dataclass(frozen=True)
class CallOutcome:
    """Typed result of exactly one model subprocess invocation (ADR-006)."""

    kind: str  # "ok" | "timeout" | "launch_missing" | "failed"
    stdout: str
    stderr: str
    duration_seconds: float


@dataclass(frozen=True)
class ParseFailure:
    """Reason value produced when extraction or validation rejects output."""

    reason: str
    is_timeout: bool = False


# ---------------------------------------------------------------------------
# CLI parsing (FR-001..FR-004, FR-007, NFR-003)
# ---------------------------------------------------------------------------


class ArgumentFailure(Exception):
    """An invalid command line — the exit-1 bad-input class (U-007)."""


class _Parser(argparse.ArgumentParser):
    """Argparse subclass that raises instead of exiting with code 2.

    Argument errors funnel to the exit-1 bad-input class; exit 2 is reserved
    for executable-not-found (FR-012, U-007).
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        raise ArgumentFailure(message)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not an integer") from None
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be greater than 0")
    return parsed


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number") from None
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"{value!r} must be a finite number greater than 0")
    return parsed


def parse_args(argv: list[str]) -> RunConfig:
    """Parse the frozen v1 surface: 1 positional argument, 3 options."""
    parser = _Parser(
        prog="sue_challenge.py",
        description=(
            "Challenge a markdown specification through a two-round Socratic "
            "dialogue using two isolated model calls, and write the challenge "
            "report beside the challenged specification."
        ),
        epilog=EGRESS_DISCLOSURE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "spec_path",
        type=Path,
        help="path of the specification file to challenge (never written)",
    )
    parser.add_argument(
        "--questions",
        type=_positive_int,
        default=DEFAULT_QUESTION_COUNT,
        metavar="N",
        help=f"cap on round-1 questions (default: {DEFAULT_QUESTION_COUNT})",
    )
    parser.add_argument(
        "--claude-cmd",
        default=DEFAULT_MODEL_COMMAND,
        metavar="CMD",
        help=(
            "model command line, split per shell quoting conventions "
            f"(default: {DEFAULT_MODEL_COMMAND})"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=_positive_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help="per-model-call budget in seconds (default: 300)",
    )
    namespace = parser.parse_args(argv)
    try:
        words = shlex.split(namespace.claude_cmd)
    except ValueError as exc:
        raise ArgumentFailure(f"--claude-cmd value is not shell-parseable: {exc}") from None
    if not words:
        raise ArgumentFailure("--claude-cmd value splits to zero words")
    return RunConfig(
        spec_path=namespace.spec_path,
        max_questions=namespace.questions,
        model_command=namespace.claude_cmd,
        timeout_seconds=namespace.timeout,
    )


# ---------------------------------------------------------------------------
# Pre-flight, spec loading, fail() choke point (FR-005/FR-006/FR-012, NFR-005)
# ---------------------------------------------------------------------------


def fail(exit_code: int, message: str) -> int:
    """Single stderr choke point: exactly 1 diagnostic line per non-zero exit."""
    print(message, file=sys.stderr)
    return exit_code


def preflight(config: RunConfig) -> tuple[int, str] | None:
    """Validate the run before any model call; return (exit_code, diagnostic) on failure.

    Frozen order: spec readable (ERR-001) -> spec directory writable (ERR-002)
    -> model executable found (ERR-003). Exactly 0 model calls launch on any
    pre-flight failure.
    """
    spec_path = config.spec_path
    if not spec_path.is_file() or not os.access(spec_path, os.R_OK):
        return (
            EXIT_BAD_INPUT,
            f"bad input: specification path '{spec_path}' is missing or unreadable",
        )
    spec_dir = spec_path.resolve().parent
    if not os.access(spec_dir, os.W_OK):
        return (
            EXIT_BAD_INPUT,
            f"bad input: specification directory '{spec_dir}' is not writable for the report",
        )
    executable = shlex.split(config.model_command)[0]
    if shutil.which(executable) is None:
        return (
            EXIT_MODEL_COMMAND_MISSING,
            (
                f"model command unavailable: executable '{executable}' not found — "
                "install it (default 'claude': https://docs.anthropic.com/en/docs/claude-code) "
                "or pass --claude-cmd naming an available command"
            ),
        )
    return None


def load_spec(path: Path) -> SpecDocument:
    """Read the challenged specification exactly once (UTF-8, errors replaced)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return SpecDocument(path=path, lines=text.splitlines())


# ---------------------------------------------------------------------------
# Prompt assembly (pure — FR-014, FR-015, FR-018, FR-021, FR-022, FR-023)
# ---------------------------------------------------------------------------


def numbered_text(spec: SpecDocument) -> str:
    """Every specification line prefixed 'N: ', 1-based (FR-018)."""
    return "\n".join(f"{number}: {line}" for number, line in enumerate(spec.lines, start=1))


def build_round1_prompt(spec: SpecDocument, max_questions: int) -> str:
    """Numbered spec text plus the question-generation instruction (FR-014/FR-015)."""
    return ROUND1_PROMPT_TEMPLATE.format(
        numbered_spec=numbered_text(spec), max_questions=max_questions
    )


def build_round2_prompt(spec: SpecDocument, id_question_pairs: list[tuple[str, str]]) -> str:
    """Numbered spec text plus bare {id, question} pairs (FR-021/FR-022/FR-023).

    The signature receives only (id, question) pairs, so round-1 categories,
    targets, line references, and reasoning are structurally absent.
    """
    questions_json = json.dumps(
        [{"id": qid, "question": qtext} for qid, qtext in id_question_pairs],
        indent=2,
    )
    return ROUND2_PROMPT_TEMPLATE.format(
        numbered_spec=numbered_text(spec), questions_json=questions_json
    )


# ---------------------------------------------------------------------------
# Isolated subprocess runner (FR-010, FR-011, FR-043; ADR-003/ADR-004/ADR-006)
# ---------------------------------------------------------------------------


def _kill_process_group(process: subprocess.Popen) -> None:
    """Kill the subprocess and every descendant sharing its process group."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()


def run_model_call(config: RunConfig, prompt: str) -> CallOutcome:
    """One model subprocess invocation per the frozen contract shape.

    argv is ``shlex.split(model_command) + ["-p"]``; the prompt travels on
    stdin (never argv, so spec text stays out of process listings); cwd is a
    fresh neutral temp directory created and removed here (FR-010). Never
    raises to callers.
    """
    try:
        argv = shlex.split(config.model_command) + ["-p"]
    except ValueError as exc:
        return CallOutcome(
            kind="failed",
            stdout="",
            stderr=f"model command is not shell-parseable: {exc}",
            duration_seconds=0.0,
        )
    workdir = tempfile.mkdtemp(prefix="sue-challenge-")
    start = time.monotonic()
    try:
        try:
            # start_new_session makes the child a process-group leader so a
            # timeout kill reaches any grandchildren holding the output pipes.
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            return CallOutcome(
                kind="launch_missing",
                stdout="",
                stderr="",
                duration_seconds=time.monotonic() - start,
            )
        except OSError as exc:
            return CallOutcome(
                kind="failed",
                stdout="",
                stderr=str(exc),
                duration_seconds=time.monotonic() - start,
            )
        try:
            stdout, stderr = process.communicate(input=prompt, timeout=config.timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_process_group(process)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # A descendant escaped the process group and still holds the
                # pipes; give up on draining rather than block past the budget.
                stdout, stderr = "", ""
            return CallOutcome(
                kind="timeout",
                stdout=stdout or "",
                stderr=stderr or "",
                duration_seconds=time.monotonic() - start,
            )
        kind = "ok" if process.returncode == 0 and stdout else "failed"
        return CallOutcome(
            kind=kind,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=time.monotonic() - start,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Staged tolerant JSON extraction (pure — FR-026/FR-027, ADR-005)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)


def _try_json(text: str):
    """Parse ``text`` as JSON, returning None on any parse error."""
    try:
        return json.loads(text)
    except ValueError:
        return None


def _balanced_brace_candidates(raw: str):
    """Yield balanced top-level ``{...}`` substrings in one linear pass.

    String literals and escapes are honored inside a candidate; text between
    candidates is skipped without state. Candidates are yielded in opening-
    brace order so the first parseable object wins (FR-026). The scan is a
    single forward pass — the interior of an unparseable or unbalanced
    candidate is not re-scanned, keeping extraction linear even on
    adversarial brace-noise output (a failed extraction lands on the
    corrective-retry path, not in a hang).
    """
    i = 0
    n = len(raw)
    while i < n:
        if raw[i] != "{":
            i += 1
            continue
        depth = 0
        in_string = False
        escaped = False
        end = None
        for position in range(i, n):
            ch = raw[position]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = position
                    break
        if end is None:
            # Braces never rebalance from here to end of input; no later
            # candidate can close either.
            return
        yield raw[i : end + 1]
        i = end + 1


def extract_json_object(raw: str) -> dict | ParseFailure:
    """Extract the first parseable JSON object from raw model output.

    Stages (ADR-005): direct parse -> code-fence strip -> balanced-brace scan.
    Surrounding prose and code fences are tolerated (FR-026); zero extractable
    objects return a ParseFailure, never an exception (FR-027). A JSON array
    (or any non-object value) at top level is not an object and fails.
    """
    direct = _try_json(raw)
    if isinstance(direct, dict):
        return direct
    if direct is not None:
        return ParseFailure(
            reason="top-level JSON value is not an object (arrays are not accepted)"
        )
    for fence_content in _FENCE_RE.findall(raw):
        fenced = _try_json(fence_content)
        if isinstance(fenced, dict):
            return fenced
    for candidate in _balanced_brace_candidates(raw):
        scanned = _try_json(candidate)
        if isinstance(scanned, dict):
            return scanned
    return ParseFailure(reason="no JSON object found in the model output")


# ---------------------------------------------------------------------------
# Strict round validation (pure — FR-016/FR-017/FR-019/FR-020, FR-024/FR-025)
# ---------------------------------------------------------------------------


def _show(value) -> str:
    """Short repr for failure reasons; long output values are truncated."""
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _is_int_list(value) -> bool:
    return isinstance(value, list) and all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    )


def validate_round1(
    obj: dict, max_questions: int
) -> tuple[list[SocraticQuestion], bool] | ParseFailure:
    """Strict round-1 schema validation plus first-N truncation.

    Every violation — including duplicate ids — returns a ParseFailure naming
    the offender (FR-016/FR-017). A list longer than ``max_questions`` keeps
    the first N in returned order with the truncation flag set (FR-019). An
    empty list is valid: the caller completes the run without round 2 (FR-020).
    """
    raw_questions = obj.get("questions")
    if not isinstance(raw_questions, list):
        return ParseFailure(reason='round-1 output is missing the "questions" list')
    questions: list[SocraticQuestion] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_questions):
        label = f"round-1 question {index + 1}"
        if not isinstance(item, dict):
            return ParseFailure(reason=f"{label}: not a JSON object")
        question_id = item.get("id")
        if not isinstance(question_id, str) or not QUESTION_ID_RE.match(question_id):
            return ParseFailure(reason=f"{label}: invalid question id {_show(question_id)}")
        if question_id in seen_ids:
            return ParseFailure(reason=f"{label}: duplicate question id {question_id}")
        seen_ids.add(question_id)
        question_text = item.get("question")
        if not isinstance(question_text, str) or not question_text.strip():
            return ParseFailure(reason=f"{label} ({question_id}): missing or empty question text")
        target = item.get("target")
        if not isinstance(target, str) or not target.strip():
            return ParseFailure(reason=f"{label} ({question_id}): missing or empty target")
        lines = item.get("lines")
        if not _is_int_list(lines):
            return ParseFailure(
                reason=f'{label} ({question_id}): "lines" is not a list of integers'
            )
        category = item.get("category")
        if category not in CATEGORIES:
            return ParseFailure(
                reason=f"{label} ({question_id}): unknown category {_show(category)}"
            )
        questions.append(
            SocraticQuestion(
                id=question_id,
                question=question_text,
                target=target,
                lines=list(lines),
                category=category,
            )
        )
    truncated = len(questions) > max_questions
    if truncated:
        questions = questions[:max_questions]
    return questions, truncated


def validate_round2(
    obj: dict, questions: list[SocraticQuestion]
) -> list[Answer] | ParseFailure:
    """Strict round-2 schema validation plus the identifier bijection.

    Each answer needs exactly 1 known question id, 1 verdict from VERDICTS,
    1 non-empty answer text, and integer evidence lines (FR-024; line range is
    checked at render, not here — ADR-007). The answer ids must map 1:1 onto
    the post-truncation question ids; the ParseFailure reason names every
    offending id (FR-025, AC-018). Valid answers return in round-1 order.
    """
    raw_answers = obj.get("answers")
    if not isinstance(raw_answers, list):
        return ParseFailure(reason='round-2 output is missing the "answers" list')
    answers: list[Answer] = []
    for index, item in enumerate(raw_answers):
        label = f"round-2 answer {index + 1}"
        if not isinstance(item, dict):
            return ParseFailure(reason=f"{label}: not a JSON object")
        answer_id = item.get("id")
        if not isinstance(answer_id, str) or not answer_id:
            return ParseFailure(reason=f"{label}: missing or non-string question id")
        # Round-2 ids are model-controlled and unvalidated at this point:
        # always name them through _show() so failure reasons stay single-line
        # and bounded (FR-028, NFR-005).
        shown_id = _show(answer_id)
        verdict = item.get("verdict")
        if verdict not in VERDICTS:
            return ParseFailure(reason=f"{label} ({shown_id}): unknown verdict {_show(verdict)}")
        answer_text = item.get("answer")
        if not isinstance(answer_text, str) or not answer_text.strip():
            return ParseFailure(reason=f"{label} ({shown_id}): missing or empty answer text")
        evidence_lines = item.get("evidence_lines")
        if not _is_int_list(evidence_lines):
            return ParseFailure(
                reason=f'{label} ({shown_id}): "evidence_lines" is not a list of integers'
            )
        answers.append(
            Answer(
                id=answer_id,
                verdict=verdict,
                answer=answer_text,
                evidence_lines=list(evidence_lines),
            )
        )
    expected_ids = [question.id for question in questions]
    expected_set = set(expected_ids)
    counts: dict[str, int] = {}
    for answer in answers:
        counts[answer.id] = counts.get(answer.id, 0) + 1
    missing = [qid for qid in expected_ids if counts.get(qid, 0) == 0]
    duplicated = [qid for qid, count in counts.items() if count > 1]
    unknown = [qid for qid in counts if qid not in expected_set]
    if missing or duplicated or unknown:
        parts = []
        if missing:
            # Missing ids come from validated round-1 questions, so they are
            # regex-safe; duplicated/unknown ids are model-controlled and go
            # through _show() to keep the reason single-line and bounded.
            parts.append("missing: " + ", ".join(missing))
        if duplicated:
            parts.append("duplicated: " + ", ".join(_show(qid) for qid in duplicated))
        if unknown:
            parts.append("unknown: " + ", ".join(_show(qid) for qid in unknown))
        return ParseFailure(
            reason="round-2 answer ids violate the question bijection — " + "; ".join(parts)
        )
    by_id = {answer.id: answer for answer in answers}
    return [by_id[qid] for qid in expected_ids]


# ---------------------------------------------------------------------------
# Round execution loop (FR-013, FR-028..FR-031; ERR-004/ERR-005)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoundExit:
    """Request to end the run after an unrecoverable round failure (FR-030)."""

    exit_code: int
    diagnostic: str


def build_retry_prompt(original: str, failure: ParseFailure) -> str:
    """The corrective-retry prompt for a round's second attempt (pure).

    Timeout failures re-issue the identical prompt with 0 appended corrective
    text (FR-029). Every other failure appends a corrective instruction naming
    ``failure.reason``, echoing 0 lines of the prior output (FR-028).
    """
    if failure.is_timeout:
        return original
    return (
        original
        + "\n\nYour previous reply was rejected: "
        + failure.reason
        + "\nReply again with a single JSON object in the requested schema, and nothing else."
    )


def _attempt_result(
    outcome: CallOutcome, validator: Callable[[dict], object]
) -> object:
    """Classify one attempt: validated value, or the ParseFailure rejecting it.

    Timeouts classify as parse failures (FR-011/ERR-005); any launch or exit
    problem after a passing pre-flight also takes the parse-failure path
    (U-007 — exit 2 belongs to pre-flight only).
    """
    if outcome.kind == "timeout":
        return ParseFailure(reason="model call timed out", is_timeout=True)
    if outcome.kind == "launch_missing":
        return ParseFailure(reason="model command executable could not be launched")
    if outcome.kind == "failed":
        return ParseFailure(reason="model call failed (non-zero exit status or empty output)")
    extracted = extract_json_object(outcome.stdout)
    if isinstance(extracted, ParseFailure):
        return extracted
    return validator(extracted)


def _write_debug_dump(
    spec_dir: Path,
    round_no: int,
    attempts: list[tuple[CallOutcome, ParseFailure]],
    timeout_seconds: float,
) -> Path:
    """Save both failing attempts' raw output under .sue-debug (FR-030).

    Timeout attempts carry a first line naming the exhausted budget (ISS-207).
    """
    debug_dir = spec_dir / DEBUG_DIR_NAME
    debug_dir.mkdir(exist_ok=True)
    for attempt_no, (outcome, failure) in enumerate(attempts, start=1):
        prefix = f"TIMEOUT after {timeout_seconds:g}s\n" if failure.is_timeout else ""
        stem = f"round{round_no}-attempt{attempt_no}"
        (debug_dir / f"{stem}-stdout.txt").write_text(
            prefix + outcome.stdout, encoding="utf-8", errors="replace"
        )
        (debug_dir / f"{stem}-stderr.txt").write_text(
            prefix + outcome.stderr, encoding="utf-8", errors="replace"
        )
    return debug_dir


def execute_round(
    config: RunConfig,
    prompt: str,
    validator: Callable[[dict], object],
    round_no: int,
    spec_dir: Path,
) -> object:
    """Run one round: at most 2 attempts, then dump and request exit 3.

    Returns the validator's success value, or a RoundExit after the second
    failure. Each attempt gets a fresh full timeout budget (FR-013); the first
    failure triggers exactly 1 corrective retry (FR-028/FR-029). Rounds are
    sequential calls in main with no cross-round loop, so a round-2 failure
    never re-runs round 1 (FR-031).
    """
    attempts: list[tuple[CallOutcome, ParseFailure]] = []
    current_prompt = prompt
    for attempt_no in (1, 2):
        outcome = run_model_call(config, current_prompt)
        result = _attempt_result(outcome, validator)
        if not isinstance(result, ParseFailure):
            return result
        attempts.append((outcome, result))
        if attempt_no == 1:
            current_prompt = build_retry_prompt(prompt, result)
    try:
        debug_dir = _write_debug_dump(spec_dir, round_no, attempts, config.timeout_seconds)
        dump_note = f"raw output saved under '{debug_dir}'"
    except OSError as exc:
        # The dump is best-effort diagnostics: the writable pre-flight check
        # can be invalidated mid-run (directory removed, disk full, a file
        # squatting on the .sue-debug name). The exit-3 outcome and its
        # single-line diagnostic must survive regardless (NFR-005).
        dump_note = f"the debug dump could not be written ({exc.__class__.__name__})"
    return RoundExit(
        exit_code=EXIT_UNUSABLE_OUTPUT,
        diagnostic=(
            f"unusable model output: round {round_no} failed after 1 corrective retry "
            f"({attempts[-1][1].reason}); {dump_note}"
        ),
    )


# ---------------------------------------------------------------------------
# Deterministic assembly (pure — FR-009, FR-032, FR-033)
# ---------------------------------------------------------------------------


def partition_answers(
    questions: list[SocraticQuestion], answers: list[Answer]
) -> tuple[list[Finding], list[tuple[SocraticQuestion, Answer]]]:
    """Partition validated answers into exactly 2 groups (FR-032).

    Findings hold verdicts CONTRADICTED plus UNANSWERABLE; audit entries hold
    ANSWERED. Both groups preserve round-1 question order; Finding ranks stay
    0 until rank_findings assigns the dense 1-based order (FR-033). Pure —
    exactly 0 model calls can occur at or after this stage (FR-009).
    """
    by_id = {answer.id: answer for answer in answers}
    findings: list[Finding] = []
    audit_entries: list[tuple[SocraticQuestion, Answer]] = []
    for question in questions:
        answer = by_id.get(question.id)
        if answer is None:
            # Unreachable after the FR-025 bijection; stay total regardless.
            continue
        if answer.verdict == "ANSWERED":
            audit_entries.append((question, answer))
        else:
            findings.append(Finding(rank=0, question=question, answer=answer))
    return findings, audit_entries


def rank_findings(findings: list[Finding]) -> list[Finding]:
    """Order findings per FR-033 with dense 1-based ranks (pure).

    All CONTRADICTED before all UNANSWERABLE, round-1 question order preserved
    within each class.
    """
    ordered = [f for f in findings if f.answer.verdict == "CONTRADICTED"] + [
        f for f in findings if f.answer.verdict == "UNANSWERABLE"
    ]
    return [replace(finding, rank=position) for position, finding in enumerate(ordered, start=1)]


# ---------------------------------------------------------------------------
# Report and summary rendering (pure — FR-035..FR-039, FR-041, NFR-004)
# ---------------------------------------------------------------------------


def _one_line(text: str) -> str:
    """Collapse model-controlled text for one-line render positions (pure).

    Question text is only validated as non-empty, so embedded newlines could
    otherwise break a markdown heading or a one-line summary entry.
    """
    return " ".join(text.split())


def _quoted_evidence(spec: SpecDocument, line_numbers: list[int]) -> list[str]:
    """Blockquote lines: exactly 1 quoted spec line per cited number (FR-039).

    Out-of-range citations render the deterministic marker instead of failing
    (ADR-007, ISS-202); an empty citation list states so explicitly.
    """
    if not line_numbers:
        return ["  > (0 lines cited)"]
    quoted = []
    for number in line_numbers:
        if 1 <= number <= len(spec.lines):
            quoted.append(f"  > line {number}: {spec.lines[number - 1]}")
        else:
            quoted.append(f"  > line {number}: (not present in the specification)")
    return quoted


def render_report(
    spec: SpecDocument,
    run_date: str,
    questions: list[SocraticQuestion],
    findings: list[Finding],
    audit_entries: list[tuple[SocraticQuestion, Answer]],
    truncated: bool,
) -> str:
    """Render the full ``socratic-challenge.md`` body (contracts/report-format.md).

    Exactly 3 sections in order: header, findings, audit appendix (FR-035).
    Pure — the run date is injected, never read here, so identical validated
    inputs give byte-identical bodies outside the run-date field (NFR-004).
    ``findings`` must already carry the FR-033 ranking from rank_findings.
    """
    lines: list[str] = [
        "# Socratic Challenge Report",
        "",
        f"- **Specification:** {spec.path}",
        f"- **Run date:** {run_date}",
        f"- **Questions:** {len(questions)}",
        f"- **Findings:** {len(findings)}",
    ]
    if truncated:
        lines.append(
            "- **Note:** round 1 returned more questions than the configured "
            f"maximum; truncated to the first {len(questions)}."
        )
    lines += ["", "## Findings", ""]
    if not findings:
        lines += [
            "Exactly 0 findings were produced: the specification text answered "
            "every question asked of it.",
            "",
        ]
    for finding in findings:
        lines += [
            f"### {finding.rank}. [{finding.answer.verdict}] {_one_line(finding.question.question)}",
            "",
            f"- **Target:** {finding.question.target}",
            "- **Evidence:**",
            *_quoted_evidence(spec, finding.answer.evidence_lines),
            "",
            finding.answer.answer,
            "",
        ]
    lines += [
        "## Audit appendix",
        "",
        "<details>",
        f"<summary>Audit appendix — {len(audit_entries)} ANSWERED question(s)</summary>",
        "",
    ]
    for question, answer in audit_entries:
        lines += [
            f"### {question.id} — {_one_line(question.question)}",
            "",
            f"- **Answer:** {answer.answer}",
            "- **Answering lines:**",
            *_quoted_evidence(spec, answer.evidence_lines),
            "",
        ]
    lines += ["</details>", ""]
    return "\n".join(lines)


def render_summary(findings: list[Finding]) -> str:
    """Terminal summary (pure): per-verdict-class counts plus the top 3 (FR-040).

    Human-oriented output with no machine-parsing contract (A-011).
    """
    contradicted = sum(1 for f in findings if f.answer.verdict == "CONTRADICTED")
    unanswerable = sum(1 for f in findings if f.answer.verdict == "UNANSWERABLE")
    lines = [f"Findings — CONTRADICTED: {contradicted}, UNANSWERABLE: {unanswerable}"]
    if findings:
        lines.append("Top findings:")
        for finding in findings[:3]:
            lines.append(
                f"  {finding.rank}. [{finding.answer.verdict}] "
                f"{_one_line(finding.question.question)}"
            )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point (exit-code spine — ADR-006, NFR-005)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Full pipeline; returns the exit code and never calls sys.exit itself."""
    try:
        config = parse_args(sys.argv[1:] if argv is None else argv)
    except ArgumentFailure as exc:
        return fail(EXIT_BAD_INPUT, f"bad input: {exc}")
    except SystemExit as exc:
        # argparse --help prints and exits 0; keep main() import-safe for
        # in-process tests (ADR-008).
        return int(exc.code or 0)

    failure = preflight(config)
    if failure is not None:
        return fail(*failure)

    try:
        spec = load_spec(config.spec_path)
    except OSError as exc:
        # The file can vanish or become unreadable between preflight and read.
        return fail(
            EXIT_BAD_INPUT,
            f"bad input: cannot read specification '{config.spec_path}': {exc}",
        )
    spec_dir = config.spec_path.resolve().parent

    # Exactly 2 logical model calls per run (FR-008): the rounds are two
    # sequential execute_round calls with no cross-round loop, so a round-2
    # failure can never re-run round 1 (FR-031).
    round1 = execute_round(
        config,
        build_round1_prompt(spec, config.max_questions),
        lambda obj: validate_round1(obj, config.max_questions),
        1,
        spec_dir,
    )
    if isinstance(round1, RoundExit):
        return fail(round1.exit_code, round1.diagnostic)
    questions, truncated = round1

    answers: list[Answer] = []
    if questions:
        round2 = execute_round(
            config,
            build_round2_prompt(spec, [(q.id, q.question) for q in questions]),
            lambda obj: validate_round2(obj, questions),
            2,
            spec_dir,
        )
        if isinstance(round2, RoundExit):
            return fail(round2.exit_code, round2.diagnostic)
        answers = round2
    # else: a valid empty round-1 list skips round 2 entirely (FR-020, AC-006).

    findings, audit_entries = partition_answers(questions, answers)
    ranked = rank_findings(findings)
    report = render_report(
        spec, date.today().isoformat(), questions, ranked, audit_entries, truncated
    )
    report_path = spec_dir / REPORT_FILENAME
    try:
        # Plain overwrite keeping 0 historical copies (FR-034, U-010).
        report_path.write_text(report, encoding="utf-8")
    except OSError as exc:
        # Writability was pre-flighted but can be invalidated mid-run.
        return fail(EXIT_BAD_INPUT, f"bad input: cannot write report '{report_path}': {exc}")
    print(f"Report: {report_path}")
    print(render_summary(ranked))
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
