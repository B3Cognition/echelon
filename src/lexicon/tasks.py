"""Tasks validator — extraction + within-doc gates over canonical task rows."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from kernel.task_contract import parse_task_rows, validate_tasks_markdown, TASK_ID_PATTERN
from .linter import Finding, banned_word_findings
from .resolver import unresolved_terms
from .completeness import placeholder_findings


@dataclass
class TaskRecord:
    id: str
    phase: str
    complexity: str
    parallel: bool
    reqs: list[str]
    depends: list[str]
    acceptance: str
    test: str
    line: int


_COMPOUND_RE = re.compile(r"\band\b", re.IGNORECASE)

_ROW_START = re.compile(rf"^- \[[ xX]\]\s+(?P<id>{TASK_ID_PATTERN})\b")
_TEST_RE = re.compile(r"^\s*\*\*Test:\*\*\s*(?P<v>.+?)\s*$")
_ACC_HDR = re.compile(r"^\s*\*\*Acceptance Criteria:\*\*\s*$")
_ACC_ITEM = re.compile(r"^\s*- \[[ xX]\]\s*(?P<v>.+?)\s*$")


def _row_start_lines(lines: list[str]) -> list[int]:
    """1-based line numbers of canonical row starts, skipping fenced blocks
    (matches parse_task_rows' fence handling so the two stay aligned)."""
    starts, in_fence = [], False
    for i, line in enumerate(lines):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _ROW_START.match(line.rstrip()):
            starts.append(i + 1)
    return starts


def extract_tasks(text: str) -> list[TaskRecord]:
    """Parse canonical task rows (via kernel) + their nested Test/Acceptance."""
    rows = parse_task_rows(text)
    lines = text.splitlines()
    starts = _row_start_lines(lines)
    out: list[TaskRecord] = []
    for idx, row in enumerate(rows):
        line_no = starts[idx] if idx < len(starts) else 0
        end = (starts[idx + 1] - 1) if idx + 1 < len(starts) else len(lines)
        block = lines[line_no:end]  # lines AFTER the row line, up to next row
        test, acc, in_acc = "", [], False
        for bl in block:
            mt = _TEST_RE.match(bl)
            if mt:
                test = mt.group("v")
                continue
            if _ACC_HDR.match(bl):
                in_acc = True
                continue
            ma = _ACC_ITEM.match(bl)
            if ma and in_acc:
                acc.append(ma.group("v"))
        out.append(TaskRecord(
            id=row.task_id, phase=row.phase, complexity=row.complexity,
            parallel=row.parallel, reqs=list(row.requirements), depends=list(row.dependencies),
            acceptance="\n".join(acc), test=test, line=line_no))
    return out


def within_doc_findings(text: str, glossary: set[str]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(banned_word_findings(text))      # vague terms in any field
    findings.extend(unresolved_terms(text, glossary))  # T: terms bind to glossary
    findings.extend(placeholder_findings(text))      # C: no <placeholder>/TBD/TODO
    for t in extract_tasks(text):                    # atomicity: one deliverable
        if len(_COMPOUND_RE.findall(t.acceptance)) >= 2:
            findings.append(Finding(
                code="task-not-atomic",
                message=f"TASK {t.id} ACCEPTANCE bundles multiple obligations; split into atomic tasks",
                line=t.line, span=t.id))
    return findings


@dataclass
class TasksReport:
    ok: bool
    parse_pass: bool
    findings: list = field(default_factory=list)


def validate_tasks(text: str, glossary: set[str] | None = None,
                   spec_text: str | None = None) -> TasksReport:
    from .crossdoc import cross_doc_findings
    glossary = glossary or set()
    findings: list = []
    result = validate_tasks_markdown(text)
    parse_pass = result.valid
    if not parse_pass:
        for err in result.errors:
            findings.append(Finding("parse-error", f"tasks.md not canonical: {err}", 0, ""))
    findings.extend(within_doc_findings(text, glossary))
    if spec_text is not None:
        findings.extend(cross_doc_findings(text, spec_text))
    return TasksReport(ok=not findings, parse_pass=parse_pass, findings=findings)
