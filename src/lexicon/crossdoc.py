"""Cross-document gate: tasks.md against spec.md (REQ->AC->TASK->TEST)."""
from __future__ import annotations
import re
from lark.exceptions import LarkError
from .linter import Finding
from .parser import parse as parse_spec
from .tasks import extract_tasks

# DEPENDS values are comma/space-separated REQ IDs (or 'none').
_DEP_SPLIT = re.compile(r"[,\s]+")

def _spec_ids(spec_text: str):
    """Return (req_ids set, {req_id: [ac ids it EXAMPLE-links]}, ac_ids set)."""
    try:
        tree = parse_spec(spec_text)
    except LarkError:
        return set(), {}, set()
    req_ids, req_examples = set(), {}
    for req in tree.find_data("req"):
        rid = str(req.children[0]); req_ids.add(rid)
        refs = [str(c.children[0]).strip() for c in req.children
                if getattr(c, "data", None) == "example"]
        req_examples[rid] = refs
    ac_ids = {str(n.children[0]) for n in tree.find_data("ac")}
    return req_ids, req_examples, ac_ids

def _has_cycle(graph: dict[str, list[str]]) -> bool:
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    def visit(n):
        color[n] = GREY
        for m in graph.get(n, []):
            if color.get(m, WHITE) == GREY:
                return True
            if color.get(m, WHITE) == WHITE and visit(m):
                return True
        color[n] = BLACK
        return False
    return any(color[n] == WHITE and visit(n) for n in graph)

def spec_depends_findings(spec_text: str) -> list[Finding]:
    """Referential-integrity gate for the REQ ``DEPENDS`` field.

    Within a single spec: every DEPENDS target must be a REQ defined in the
    same spec (``dep-missing``), a REQ may not depend on itself (``dep-self``),
    and the DEPENDS graph must be acyclic (``dep-cycle``). ``DEPENDS: none`` and
    an omitted field declare no dependency and are clean. Returns [] when the
    spec does not parse — the parse-error is reported by the parser gate.
    """
    try:
        tree = parse_spec(spec_text)
    except LarkError:
        return []

    reqs: list[tuple[str, list[str], int]] = []
    defined: set[str] = set()
    for req in tree.find_data("req"):
        rid = str(req.children[0])
        line = getattr(req.children[0], "line", 0) or 0
        deps: list[str] = []
        for c in req.children:
            if getattr(c, "data", None) == "depends":
                val = str(c.children[0]).strip()
                if val.lower() != "none":
                    deps = [t for t in _DEP_SPLIT.split(val) if t]
        defined.add(rid)
        reqs.append((rid, deps, line))

    findings: list[Finding] = []
    for rid, deps, line in reqs:
        for d in deps:
            if d == rid:
                findings.append(Finding("dep-self", f"REQ {rid} DEPENDS on itself", line, rid))
            elif d not in defined:
                findings.append(Finding(
                    "dep-missing",
                    f"REQ {rid} DEPENDS on undefined requirement {d}", line, rid))

    graph = {rid: [d for d in deps if d in defined] for rid, deps, _ in reqs}
    if _has_cycle(graph):
        findings.append(Finding("dep-cycle", "REQ DEPENDS graph contains a cycle", 0, ""))
    return findings


def cross_doc_findings(tasks_text: str, spec_text: str) -> list[Finding]:
    findings: list[Finding] = []
    req_ids, req_examples, ac_ids = _spec_ids(spec_text)
    tasks = extract_tasks(tasks_text)
    task_ids = {t.id for t in tasks}
    covered = set()

    for t in tasks:
        for r in t.reqs:
            if r == "INFRA":
                continue
            if r not in req_ids:
                findings.append(Finding("task-orphan-req",
                    f"TASK {t.id} REQ {r!r} matches no requirement in spec.md", t.line, t.id))
            else:
                covered.add(r)
        for d in t.depends:
            if d not in task_ids:
                findings.append(Finding("dep-missing",
                    f"TASK {t.id} DEPENDS on {d!r} which is not a defined task", t.line, t.id))
        if not t.test.strip():
            findings.append(Finding("task-no-test", f"TASK {t.id} has no TEST", t.line, t.id))

    for rid in sorted(req_ids - covered):
        findings.append(Finding("req-uncovered",
            f"REQ {rid} is covered by no task", 0, rid))

    graph = {t.id: t.depends for t in tasks}
    if _has_cycle(graph):
        findings.append(Finding("dep-cycle", "task DEPENDS graph contains a cycle", 0, ""))

    return findings
