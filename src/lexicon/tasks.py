"""Tasks validator — extraction + within-doc gates (spec-parity)."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from lark.exceptions import LarkError
from .tasks_parser import parse

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

_FIELD = {"PHASE": "phase", "COMPLEXITY": "complexity", "PARALLEL": "parallel",
          "REQ": "reqs", "DEPENDS": "depends", "ACCEPTANCE": "acceptance", "TEST": "test"}

def extract_tasks(text: str) -> list[TaskRecord]:
    try:
        tree = parse(text)
    except LarkError:
        return []
    out: list[TaskRecord] = []
    for node in tree.find_data("task"):
        toks = [c for c in node.children]
        tid = str(toks[0]); line = toks[0].line
        vals = [str(t).strip() for t in toks[1:]]
        # grammar order: PHASE, COMPLEXITY, PARALLEL, REQ, DEPENDS, ACCEPTANCE, TEST
        phase, complexity, parallel, req, depends, acceptance, test = vals
        reqs = [] if req.strip() in ("", "none") else req.split()
        deps = [] if depends.strip() in ("", "none") else depends.replace(",", " ").split()
        out.append(TaskRecord(
            id=tid, phase=phase, complexity=complexity, parallel=(parallel == "yes"),
            reqs=reqs, depends=deps, acceptance=acceptance, test=test, line=line))
    return out
