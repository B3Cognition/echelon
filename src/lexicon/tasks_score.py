"""Deterministic soft quality score for tasks.md (advisory, never gates)."""
from __future__ import annotations
import re
from .tasks import extract_tasks

_NUM_UNIT = re.compile(r"\b\d+(\.\d+)?\s*(ms|s|kb|mb|gb|%|rows|requests|seconds|minutes)\b", re.I)
_COMPARATOR = re.compile(r"(<=|>=|<|>|=|at most|at least|within|exactly)", re.I)
_AND = re.compile(r"\band\b", re.I)

def _measurable(s: str) -> float:
    return 1.0 if (_NUM_UNIT.search(s) or _COMPARATOR.search(s)) else 0.4

def task_quality(text: str) -> dict[str, float]:
    tasks = extract_tasks(text)
    if not tasks:
        return {k: 1.0 for k in
                ("acceptance_measurability","test_concreteness","atomicity_ratio","dependency_depth","overall")}
    n = len(tasks)
    acc = sum(_measurable(t.acceptance) for t in tasks) / n
    tst = sum(1.0 if len(t.test.split()) >= 4 else 0.5 for t in tasks) / n
    atom = sum(1.0 if len(_AND.findall(t.acceptance)) < 2 else 0.0 for t in tasks) / n
    max_dep = max((len(t.depends) for t in tasks), default=0)
    depth = 1.0 if max_dep <= 3 else max(0.0, 1.0 - (max_dep - 3) * 0.1)
    overall = round((acc + tst + atom + depth) / 4, 4)
    return {"acceptance_measurability": round(acc, 4), "test_concreteness": round(tst, 4),
            "atomicity_ratio": round(atom, 4), "dependency_depth": round(depth, 4), "overall": overall}
