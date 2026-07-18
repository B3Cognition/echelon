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
from dataclasses import dataclass
from pathlib import Path

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
    del spec

    # Rounds, deterministic assembly, and the report write are wired by later
    # tasks (T-006..T-012); the pre-flight exit-code spine ends here.
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
