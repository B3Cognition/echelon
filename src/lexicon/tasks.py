"""Tasks validator — extraction + within-doc gates (spec-parity)."""
from __future__ import annotations
import re
from dataclasses import dataclass
from lark.exceptions import LarkError
from .tasks_parser import parse
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

def extract_tasks(text: str) -> list[TaskRecord]:
    try:
        tree = parse(text)
    except LarkError:
        return []
    out: list[TaskRecord] = []
    for node in tree.find_data("task"):
        toks = [c for c in node.children]
        tid = str(toks[0])
        line = toks[0].line
        vals = [str(t).strip() for t in toks[1:]]
        # grammar order: PHASE, COMPLEXITY, PARALLEL, REQ, DEPENDS, ACCEPTANCE, TEST
        phase, complexity, parallel, req, depends, acceptance, test = vals
        reqs = [] if req.strip() in ("", "none") else req.split()
        deps = [] if depends.strip() in ("", "none") else depends.replace(",", " ").split()
        out.append(TaskRecord(
            id=tid, phase=phase, complexity=complexity, parallel=(parallel == "yes"),
            reqs=reqs, depends=deps, acceptance=acceptance, test=test, line=line))
    return out


_COMPOUND_RE = re.compile(r"\band\b", re.IGNORECASE)


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
