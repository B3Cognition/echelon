# Tasks Grammar + Cross-Document Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Govern `tasks.md` with a `TASKS` controlled grammar + a re-runnable cross-document gate that verifies the `REQ→AC→TASK→TEST` chain, at full parity with the `spec.md` gate, reusing the `lexicon` engine.

**Architecture:** Extend the existing `src/lexicon/` package (Python + lark). A new `TASKS` grammar parses `tasks.md`; a `tasks` validator reuses the spec gate's within-doc modules (`linter`, `resolver`, `completeness`) plus a new atomicity check; a `crossdoc` module checks tasks against `spec.md` (coverage / referential integrity / DAG / test-linkage); a deterministic soft score mirrors `understanding`'s advisory layer. The `lexicon` CLI gains `--type tasks --spec --glossary`.

**Tech Stack:** Python 3.12, `lark>=1.1` (LALR), `typer` CLI, `pytest`. All deterministic — no LLM, no network.

## Global Constraints

- Python ≥ 3.11; depend only on what `pyproject.toml` already declares (`lark>=1.1`, `typer`, `rich`). No new runtime deps.
- Reuse existing `src/lexicon/` modules — do NOT duplicate `Finding`, banned-word, resolver, or completeness logic. Import them.
- All checks deterministic: pure functions / fixed parsing. No LLM, no randomness, no network.
- Tests are TDD: write the failing test first, watch it fail, then implement. Tests live under `tests/unit/`, marked `@pytest.mark.unit`.
- `Finding` is the single result type (from `lexicon.linter`): `Finding(code, message, line, span)`.
- Validation never raises on a malformed document — it returns findings.

---

### Task 1: `TASKS` grammar + parse

**Files:**
- Create: `src/lexicon/grammar_tasks.lark`
- Create: `src/lexicon/tasks_parser.py`
- Test: `tests/unit/test_tasks_parser.py`

**Interfaces:**
- Consumes: `lark` (as `src/lexicon/parser.py` already does — same LALR + `_normalize` trailing-newline pattern).
- Produces: `tasks_parser.parse(text) -> lark.Tree`; `tasks_parser.parse_pass(text) -> bool`.

- [ ] **Step 1: Write the grammar file**

Create `src/lexicon/grammar_tasks.lark`:

```lark
// TASKS controlled grammar (LALR, contextual lexer). One TASK block per task.
start: header task+

header: "ARTIFACT:" TYPE _NL "TITLE:" TEXT _NL
TYPE: "TASKS"

task: "TASK:" ID _NL \
      "PHASE:" TEXT _NL \
      "COMPLEXITY:" COMPLEXITY _NL \
      "PARALLEL:" YESNO _NL \
      "REQ:" TEXT _NL \
      "DEPENDS:" TEXT _NL \
      "ACCEPTANCE:" TEXT _NL \
      "TEST:" TEXT _NL

COMPLEXITY: "trivial" | "standard" | "complex"
YESNO: "yes" | "no"
ID: /[A-Za-z][A-Za-z0-9_-]*/
TEXT: /[^\n]+/
_NL: /(\r?\n[ \t]*)+/

%import common.WS_INLINE
%ignore WS_INLINE
```

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_tasks_parser.py`:

```python
import pytest
from lexicon.tasks_parser import parse_pass

GOOD = """ARTIFACT: TASKS
TITLE: Build the workbench

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001
DEPENDS: none
ACCEPTANCE: the run list renders three rows from three run directories
TEST: integration test asserts three rows for a three-run fixture
"""

MISSING_TEST = """ARTIFACT: TASKS
TITLE: t

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001
DEPENDS: none
ACCEPTANCE: something observable
"""

@pytest.mark.unit
def test_valid_tasks_doc_parses():
    assert parse_pass(GOOD) is True

@pytest.mark.unit
def test_task_missing_required_field_fails():
    assert parse_pass(MISSING_TEST) is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_parser.py -q`
Expected: FAIL — `ModuleNotFoundError: lexicon.tasks_parser`.

- [ ] **Step 4: Implement the parser (mirror `src/lexicon/parser.py`)**

Create `src/lexicon/tasks_parser.py`:

```python
"""Parser for the TASKS controlled grammar — computes P(A) for tasks.md."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from lark import Lark, Tree
from lark.exceptions import LarkError

_GRAMMAR_PATH = Path(__file__).with_name("grammar_tasks.lark")

@lru_cache(maxsize=1)
def _parser() -> Lark:
    return Lark(_GRAMMAR_PATH.read_text(encoding="utf-8"), parser="lalr", start="start")

def _normalize(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"

def parse(text: str) -> Tree:
    return _parser().parse(_normalize(text))

def parse_pass(text: str) -> bool:
    try:
        parse(text)
    except LarkError:
        return False
    return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_parser.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/lexicon/grammar_tasks.lark src/lexicon/tasks_parser.py tests/unit/test_tasks_parser.py
git commit -m "feat(lexicon): TASKS grammar + parser"
```

---

### Task 2: Extract task records from the parse tree

**Files:**
- Create: `src/lexicon/tasks.py`
- Test: `tests/unit/test_tasks_extract.py`

**Interfaces:**
- Consumes: `tasks_parser.parse`.
- Produces: `tasks.TaskRecord` dataclass (`id, phase, complexity, parallel, reqs: list[str], depends: list[str], acceptance, test, line`); `tasks.extract_tasks(text) -> list[TaskRecord]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_extract.py`:

```python
import pytest
from lexicon.tasks import extract_tasks

DOC = """ARTIFACT: TASKS
TITLE: t

TASK: T-001
PHASE: foundation
COMPLEXITY: standard
PARALLEL: no
REQ: REQ-001 REQ-002
DEPENDS: none
ACCEPTANCE: the list renders
TEST: a test asserts the list

TASK: T-002
PHASE: foundation
COMPLEXITY: complex
PARALLEL: yes
REQ: INFRA
DEPENDS: T-001
ACCEPTANCE: the store persists
TEST: a test asserts persistence
"""

@pytest.mark.unit
def test_extract_parses_fields_and_lists():
    ts = extract_tasks(DOC)
    assert [t.id for t in ts] == ["T-001", "T-002"]
    assert ts[0].reqs == ["REQ-001", "REQ-002"]
    assert ts[0].depends == []          # "none" -> empty
    assert ts[1].reqs == ["INFRA"]
    assert ts[1].depends == ["T-001"]
    assert ts[1].parallel is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_extract.py -q`
Expected: FAIL — `ImportError: cannot import name 'extract_tasks'`.

- [ ] **Step 3: Implement extraction**

Create `src/lexicon/tasks.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_extract.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/lexicon/tasks.py tests/unit/test_tasks_extract.py
git commit -m "feat(lexicon): extract TaskRecords from TASKS tree"
```

---

### Task 3: Within-doc parity gates (banned-word, terms, no-placeholder, atomicity)

**Files:**
- Modify: `src/lexicon/tasks.py`
- Test: `tests/unit/test_tasks_within_doc.py`

**Interfaces:**
- Consumes: `lexicon.linter.banned_word_findings`, `lexicon.linter.Finding`, `lexicon.resolver.unresolved_terms`, `lexicon.completeness.placeholder_findings`, `tasks.extract_tasks`.
- Produces: `tasks.within_doc_findings(text, glossary: set[str]) -> list[Finding]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_within_doc.py`:

```python
import pytest
from lexicon.tasks import within_doc_findings

def _doc(acceptance, test="a concrete test runs and asserts the result"):
    return ("ARTIFACT: TASKS\nTITLE: t\n\n"
            "TASK: T-001\nPHASE: foundation\nCOMPLEXITY: standard\nPARALLEL: no\n"
            f"REQ: REQ-001\nDEPENDS: none\nACCEPTANCE: {acceptance}\nTEST: {test}\n")

@pytest.mark.unit
def test_banned_word_in_acceptance_flagged():
    f = within_doc_findings(_doc("the system works correctly and is robust"), set())
    assert any(x.code == "banned-word" for x in f)

@pytest.mark.unit
def test_compound_acceptance_not_atomic():
    f = within_doc_findings(_doc("the list renders and the cost panel updates and an email is sent"), set())
    assert any(x.code == "task-not-atomic" for x in f)

@pytest.mark.unit
def test_placeholder_flagged():
    f = within_doc_findings(_doc("renders <TBD> rows"), set())
    assert any(x.code == "incomplete-slot" for x in f)

@pytest.mark.unit
def test_clean_task_has_no_within_doc_findings():
    f = within_doc_findings(_doc("the run list renders one row per discovered run directory"), set())
    assert f == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_within_doc.py -q`
Expected: FAIL — `ImportError: cannot import name 'within_doc_findings'`.

- [ ] **Step 3: Implement the within-doc gates**

Append to `src/lexicon/tasks.py`:

```python
from .linter import Finding, banned_word_findings
from .resolver import unresolved_terms
from .completeness import placeholder_findings

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_within_doc.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/lexicon/tasks.py tests/unit/test_tasks_within_doc.py
git commit -m "feat(lexicon): tasks within-doc parity gates (banned/terms/placeholder/atomicity)"
```

---

### Task 4: Cross-document gate (coverage / referential integrity / DAG / test-linkage)

**Files:**
- Create: `src/lexicon/crossdoc.py`
- Test: `tests/unit/test_tasks_crossdoc.py`

**Interfaces:**
- Consumes: `tasks.extract_tasks`, `tasks.TaskRecord`, `lexicon.linter.Finding`, and from `lexicon.parser`: a way to list spec REQ ids + AC ids. Use `lexicon.parser.parse` then `tree.find_data("req")` / `find_data("ac")` (the spec grammar names them `req`/`ac`, with the id token as `children[0]`).
- Produces: `crossdoc.cross_doc_findings(tasks_text: str, spec_text: str) -> list[Finding]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_crossdoc.py`:

```python
import pytest
from lexicon.crossdoc import cross_doc_findings

SPEC = """ARTIFACT: SPEC
TITLE: t

REQ: REQ-001
GIVEN: g
WHEN: w
THEN: the system MUST act
OUTPUT: a result
EXAMPLE: AC-001

REQ: REQ-002
GIVEN: g
WHEN: w
THEN: the system MUST persist
OUTPUT: stored
EXAMPLE: AC-002

AC: AC-001
GIVEN: g
WHEN: w
THEN: visible

AC: AC-002
GIVEN: g
WHEN: w
THEN: persisted
"""

def _tasks(*rows):
    body = "".join(rows)
    return f"ARTIFACT: TASKS\nTITLE: t\n\n{body}"

def _task(tid, req, depends="none", test="a test asserts it"):
    return (f"TASK: {tid}\nPHASE: p\nCOMPLEXITY: standard\nPARALLEL: no\n"
            f"REQ: {req}\nDEPENDS: {depends}\nACCEPTANCE: x is observable\nTEST: {test}\n\n")

@pytest.mark.unit
def test_uncovered_req_flagged():
    # only REQ-001 covered; REQ-002 has no task
    f = cross_doc_findings(_tasks(_task("T-001", "REQ-001")), SPEC)
    assert any(x.code == "req-uncovered" and x.span == "REQ-002" for x in f)

@pytest.mark.unit
def test_orphan_task_req_flagged():
    f = cross_doc_findings(_tasks(_task("T-001","REQ-001"), _task("T-002","REQ-999")), SPEC)
    assert any(x.code == "task-orphan-req" and "REQ-999" in x.message for x in f)

@pytest.mark.unit
def test_dependency_cycle_flagged():
    f = cross_doc_findings(_tasks(_task("T-001","REQ-001","T-002"), _task("T-002","REQ-002","T-001")), SPEC)
    assert any(x.code == "dep-cycle" for x in f)

@pytest.mark.unit
def test_full_coverage_acyclic_passes():
    f = cross_doc_findings(_tasks(_task("T-001","REQ-001"), _task("T-002","REQ-002","T-001")), SPEC)
    assert f == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_crossdoc.py -q`
Expected: FAIL — `ModuleNotFoundError: lexicon.crossdoc`.

- [ ] **Step 3: Implement the cross-doc checks**

Create `src/lexicon/crossdoc.py`:

```python
"""Cross-document gate: tasks.md against spec.md (REQ->AC->TASK->TEST)."""
from __future__ import annotations
from lark.exceptions import LarkError
from .linter import Finding
from .parser import parse as parse_spec
from .tasks import extract_tasks

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_crossdoc.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add src/lexicon/crossdoc.py tests/unit/test_tasks_crossdoc.py
git commit -m "feat(lexicon): cross-doc gate (coverage/refint/DAG/test-linkage)"
```

---

### Task 5: Tasks validity aggregator (`Valid_tasks`)

**Files:**
- Modify: `src/lexicon/tasks.py`
- Test: `tests/unit/test_tasks_validity.py`

**Interfaces:**
- Consumes: `tasks_parser.parse`, `tasks.within_doc_findings`, `crossdoc.cross_doc_findings`, `lexicon.linter.Finding`.
- Produces: `tasks.TasksReport` dataclass (`ok: bool, parse_pass: bool, findings: list[Finding]`); `tasks.validate_tasks(text, glossary=None, spec_text=None) -> TasksReport`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_validity.py`:

```python
import pytest
from lexicon.tasks import validate_tasks

SPEC = ("ARTIFACT: SPEC\nTITLE: t\n\nREQ: REQ-001\nGIVEN: g\nWHEN: w\n"
        "THEN: the system MUST act\nOUTPUT: r\nEXAMPLE: AC-001\n\n"
        "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: visible\n")
TASKS_OK = ("ARTIFACT: TASKS\nTITLE: t\n\nTASK: T-001\nPHASE: p\nCOMPLEXITY: standard\n"
            "PARALLEL: no\nREQ: REQ-001\nDEPENDS: none\n"
            "ACCEPTANCE: the run list renders one row\nTEST: a test asserts one row\n")

@pytest.mark.unit
def test_clean_tasks_valid():
    r = validate_tasks(TASKS_OK, glossary=set(), spec_text=SPEC)
    assert r.ok is True and r.parse_pass is True and r.findings == []

@pytest.mark.unit
def test_uncovered_req_makes_invalid():
    tasks = TASKS_OK.replace("REQ: REQ-001", "REQ: INFRA")  # REQ-001 now uncovered
    r = validate_tasks(tasks, glossary=set(), spec_text=SPEC)
    assert r.ok is False
    assert any(f.code == "req-uncovered" for f in r.findings)

@pytest.mark.unit
def test_parse_error_makes_invalid():
    r = validate_tasks("not a tasks doc", glossary=set(), spec_text=SPEC)
    assert r.ok is False and r.parse_pass is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_validity.py -q`
Expected: FAIL — `ImportError: cannot import name 'validate_tasks'`.

- [ ] **Step 3: Implement the aggregator**

Append to `src/lexicon/tasks.py`:

```python
from lark.exceptions import LarkError as _LarkError
from .crossdoc import cross_doc_findings

@dataclass
class TasksReport:
    ok: bool
    parse_pass: bool
    findings: list = field(default_factory=list)

def validate_tasks(text: str, glossary: set[str] | None = None,
                   spec_text: str | None = None) -> TasksReport:
    glossary = glossary or set()
    findings: list = []
    try:
        parse(text)
        parse_pass = True
    except _LarkError as exc:
        parse_pass = False
        findings.append(Finding("parse-error",
            f"does not parse under the TASKS grammar: {exc.__class__.__name__}",
            getattr(exc, "line", 0) or 0, ""))
    findings.extend(within_doc_findings(text, glossary))
    if spec_text is not None:
        findings.extend(cross_doc_findings(text, spec_text))
    return TasksReport(ok=not findings, parse_pass=parse_pass, findings=findings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_validity.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/lexicon/tasks.py tests/unit/test_tasks_validity.py
git commit -m "feat(lexicon): Valid_tasks aggregator"
```

---

### Task 6: Deterministic soft score (Unit 3b — understanding parity)

**Files:**
- Create: `src/lexicon/tasks_score.py`
- Test: `tests/unit/test_tasks_score.py`

**Interfaces:**
- Consumes: `tasks.extract_tasks`, `tasks.TaskRecord`.
- Produces: `tasks_score.task_quality(text) -> dict[str, float]` with keys `acceptance_measurability`, `test_concreteness`, `atomicity_ratio`, `dependency_depth`, `overall` (all 0..1, deterministic).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_score.py`:

```python
import pytest
from lexicon.tasks_score import task_quality

MEASURABLE = ("ARTIFACT: TASKS\nTITLE: t\n\nTASK: T-001\nPHASE: p\nCOMPLEXITY: standard\n"
              "PARALLEL: no\nREQ: REQ-001\nDEPENDS: none\n"
              "ACCEPTANCE: the list renders within 200 ms for 100 rows\n"
              "TEST: a test asserts latency under 200 ms\n")
VAGUE = ("ARTIFACT: TASKS\nTITLE: t\n\nTASK: T-001\nPHASE: p\nCOMPLEXITY: standard\n"
         "PARALLEL: no\nREQ: REQ-001\nDEPENDS: none\n"
         "ACCEPTANCE: the list renders\nTEST: it is tested\n")

@pytest.mark.unit
def test_score_is_deterministic():
    assert task_quality(MEASURABLE) == task_quality(MEASURABLE)

@pytest.mark.unit
def test_measurable_scores_higher_than_vague():
    assert task_quality(MEASURABLE)["overall"] > task_quality(VAGUE)["overall"]

@pytest.mark.unit
def test_keys_present_and_bounded():
    q = task_quality(MEASURABLE)
    for k in ("acceptance_measurability","test_concreteness","atomicity_ratio","dependency_depth","overall"):
        assert 0.0 <= q[k] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_score.py -q`
Expected: FAIL — `ModuleNotFoundError: lexicon.tasks_score`.

- [ ] **Step 3: Implement the soft score**

Create `src/lexicon/tasks_score.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_score.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add src/lexicon/tasks_score.py tests/unit/test_tasks_score.py
git commit -m "feat(lexicon): deterministic tasks soft-quality score"
```

---

### Task 7: CLI — `lexicon validate --type tasks --spec --glossary`

**Files:**
- Modify: `src/lexicon/cli.py`
- Test: `tests/unit/test_tasks_cli.py`

**Interfaces:**
- Consumes: `tasks.validate_tasks`, `tasks_score.task_quality`, existing `cli._load_glossary`.
- Produces: CLI behavior — when `--type tasks`, dispatch to `validate_tasks(text, glossary, spec_text)`; exit 0 iff `ok`; `--json` includes findings + `task_quality`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_cli.py`:

```python
import pytest
from typer.testing import CliRunner
from lexicon.cli import app

runner = CliRunner()
SPEC = ("ARTIFACT: SPEC\nTITLE: t\n\nREQ: REQ-001\nGIVEN: g\nWHEN: w\n"
        "THEN: the system MUST act\nOUTPUT: r\nEXAMPLE: AC-001\n\n"
        "AC: AC-001\nGIVEN: g\nWHEN: w\nTHEN: visible\n")
TASKS_OK = ("ARTIFACT: TASKS\nTITLE: t\n\nTASK: T-001\nPHASE: p\nCOMPLEXITY: standard\n"
            "PARALLEL: no\nREQ: REQ-001\nDEPENDS: none\n"
            "ACCEPTANCE: the run list renders one row\nTEST: a test asserts one row\n")

def _w(tmp, name, body):
    p = tmp / name; p.write_text(body, encoding="utf-8"); return str(p)

@pytest.mark.unit
def test_valid_tasks_exits_zero(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK); s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 0

@pytest.mark.unit
def test_uncovered_req_exits_one(tmp_path):
    t = _w(tmp_path, "tasks.md", TASKS_OK.replace("REQ: REQ-001", "REQ: INFRA"))
    s = _w(tmp_path, "spec.md", SPEC)
    res = runner.invoke(app, ["validate", t, "--type", "tasks", "--spec-ref", s])
    assert res.exit_code == 1
    assert "req-uncovered" in res.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_cli.py -q`
Expected: FAIL — `--type tasks` not handled (exit 1 for the valid case, or no `req-uncovered` branch).

- [ ] **Step 3a: Add the `--spec-ref` option to `validate`**

The current `validate` signature (`src/lexicon/cli.py:71-81`) has positional `spec: Path` (the
file under validation), plus `artifact_type` (`--type`), `glossary` (`--glossary`), `as_json`
(`--json`). The cross-doc reference can NOT be `--spec` (collides with the positional `spec`),
so add `spec_ref` as a new option in the signature, after `glossary`:

```python
    spec_ref: Optional[Path] = typer.Option(
        None, "--spec-ref", exists=True, readable=True,
        help="spec.md for cross-document checks (used with --type tasks)."),
```

- [ ] **Step 3b: Add the tasks branch immediately after `text = spec.read_text(...)` (line 83)**

Insert this block right after `text = spec.read_text(encoding="utf-8")` and before the existing
`report = _validate(...)` call. It uses the real names from the current CLI (`spec`, `glossary`,
`as_json`, `_json`, `_load_glossary`):

```python
    if (artifact_type or "").lower() == "tasks":
        from .tasks import validate_tasks
        from .tasks_score import task_quality
        spec_text = spec_ref.read_text(encoding="utf-8") if spec_ref else None
        report = validate_tasks(text, glossary=_load_glossary(glossary), spec_text=spec_text)
        if as_json:
            typer.echo(_json.dumps({
                "file": str(spec),
                "ok": report.ok,
                "parse_pass": report.parse_pass,
                "soft_score": task_quality(text),
                "findings": [
                    {"code": f.code, "message": f.message, "line": f.line, "span": f.span}
                    for f in report.findings
                ],
            }, indent=2))
        elif report.ok:
            typer.echo(f"✓ {spec}: valid [TASKS] (soft={task_quality(text)['overall']:.2f})")
        else:
            typer.echo(f"✗ {spec}: invalid")
            for f in report.findings:
                typer.echo(f"  {spec}:{f.line}  [{f.code}] {f.message}")
        raise typer.Exit(code=0 if report.ok else 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_cli.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full lexicon suite (regression)**

Run: `python3 -m pytest tests/unit/test_lexicon_*.py tests/unit/test_tasks_*.py -q`
Expected: PASS (all green).

- [ ] **Step 6: Commit**

```bash
git add src/lexicon/cli.py tests/unit/test_tasks_cli.py
git commit -m "feat(lexicon): CLI validate --type tasks --spec --glossary"
```

---

### Task 8: Config — `lexicon_gate.artifacts.tasks`

**Files:**
- Modify: `extension/echelon-config.yml`
- Test: `tests/unit/test_tasks_config.py`

**Interfaces:**
- Produces: `lexicon_gate.artifacts.tasks = {enabled, type, spec_ref}` readable by the harness/agents.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_tasks_config.py`:

```python
import pytest, yaml

@pytest.mark.unit
def test_lexicon_gate_has_tasks_artifact():
    cfg = yaml.safe_load(open("extension/echelon-config.yml"))
    g = cfg["lexicon_gate"]
    assert g["artifacts"]["tasks"]["enabled"] is True
    assert g["artifacts"]["tasks"]["type"] == "tasks"
    assert g["artifacts"]["tasks"]["spec_ref"] == "spec.md"
    # spec entry still present (back-compat)
    assert g["artifacts"]["spec"]["type"] == "spec"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_config.py -q`
Expected: FAIL — current `lexicon_gate` has no `artifacts` key.

- [ ] **Step 3: Restructure the `lexicon_gate` block**

In `extension/echelon-config.yml`, replace the current `lexicon_gate:` block body with:

```yaml
lexicon_gate:
  enabled: true
  artifacts:
    spec:  { enabled: true, type: spec }
    tasks: { enabled: true, type: tasks, spec_ref: spec.md }
  glossary_file: glossary.md
  max_repair_attempts: 3
  on_exhausted: warn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_config.py -q`
Expected: PASS.

- [ ] **Step 5: Verify the existing spec self-read still resolves**

Run (sanity — the cartographer self-read path tolerates the new shape):
```bash
python3 -c "import yaml; g=yaml.safe_load(open('extension/echelon-config.yml'))['lexicon_gate']; print('spec on:', g['artifacts']['spec']['enabled'], '| tasks on:', g['artifacts']['tasks']['enabled'])"
```
Expected: `spec on: True | tasks on: True`

- [ ] **Step 6: Commit**

```bash
git add extension/echelon-config.yml tests/unit/test_tasks_config.py
git commit -m "feat(lexicon): config lexicon_gate.artifacts.tasks (+spec, back-compat)"
```

---

### Task 9: Wire ORCHESTRATOR Tasks Gate Mode + `phase3-plan` re-dispatch + persist pass flag

**Files:**
- Modify: `extension/agents/solution/orchestrator.md`
- Modify: `extension/workflow/phases/phase3-plan.md`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/unit/test_tasks_wiring.py`

**Interfaces:**
- Produces: ORCHESTRATOR authors `tasks.md` in the `TASKS` grammar, self-validates with `lexicon validate --type tasks --spec spec.md`, emits `tasks_lexicon_pass`; COMMANDER re-dispatches `phase3-plan` on `NOT tasks_lexicon_pass`.

- [ ] **Step 1: Write the failing test (wiring assertions)**

Create `tests/unit/test_tasks_wiring.py`:

```python
import pytest, yaml, pathlib

@pytest.mark.unit
def test_orchestrator_has_tasks_gate_mode():
    txt = pathlib.Path("extension/agents/solution/orchestrator.md").read_text()
    assert "Tasks Gate Mode" in txt
    assert "lexicon validate" in txt and "--type tasks" in txt
    assert "tasks_lexicon_pass" in txt

@pytest.mark.unit
def test_phase3_plan_redispatch_transition():
    d = yaml.safe_load(pathlib.Path("extension/workflow/definition.yaml").read_text())
    node = next(n for n in d["phases"] if n["id"] == "phase3-plan")
    conds = " ".join(t.get("condition","") for t in node["transitions"])
    assert "tasks_lexicon_pass" in conds and "NOT tasks_lexicon_pass" in conds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_wiring.py -q`
Expected: FAIL — strings/transition not present yet.

- [ ] **Step 3: Add "Tasks Gate Mode" to `orchestrator.md`**

Append this section to `extension/agents/solution/orchestrator.md` (mirror of CARTOGRAPHER's Lexicon Gate Mode):

```markdown
## Tasks Gate Mode (when `lexicon_gate.artifacts.tasks.enabled`)

**Activation — read the flag yourself.** Before authoring `tasks.md`, run:

\`\`\`bash
python3 -c "import yaml; g=(yaml.safe_load(open('.specify/extensions/echelon/echelon-config.yml')) or {}).get('lexicon_gate') or {}; a=(g.get('artifacts') or {}).get('tasks') or {}; print('TASKS_GATE=on' if (g.get('enabled') and a.get('enabled')) else 'TASKS_GATE=off'); print('spec_ref='+str(a.get('spec_ref','spec.md'))); print('max_repair='+str(g.get('max_repair_attempts',3)))" 2>/dev/null || echo "TASKS_GATE=off"
\`\`\`

If `TASKS_GATE=on`, author `tasks.md` in the TASKS controlled grammar (`ARTIFACT: TASKS`,
one `TASK` block per task with `PHASE/COMPLEXITY/PARALLEL/REQ/DEPENDS/ACCEPTANCE/TEST`),
then run the self-validation repair loop:

\`\`\`bash
LEXICON="lexicon"; command -v lexicon >/dev/null 2>&1 || LEXICON="python3 -m lexicon.cli"
$LEXICON validate "{spec_dir}/tasks.md" --type tasks --spec "{spec_dir}/spec.md" --glossary "{spec_dir}/glossary.md" --json
\`\`\`

Parse the JSON; if `ok` is false, apply the localized fix per finding code (`req-uncovered` →
add a TASK for the REQ; `task-orphan-req` → fix `REQ=`; `task-not-atomic` → split; `banned-word`
→ make measurable; `dep-cycle`/`dep-missing` → fix `DEPENDS`; `task-no-test` → add `TEST`;
`incomplete-slot` → fill). Re-run, up to `max_repair_attempts`. Emit in `echelon_result.state_updates`:

\`\`\`yaml
echelon_result:
  state_updates:
    tasks_lexicon_pass: true   # authoritative final validator verdict
    tasks_lexicon_attempts: <int>
\`\`\`

ALWAYS treat the `lexicon validate --type tasks` verdict as authoritative.
NEVER report `tasks_lexicon_pass: true` without a final run that returned `ok: true`.
```

- [ ] **Step 4: Add the `phase3-plan` re-dispatch transition in `definition.yaml`**

Find the `phase3-plan` node's `transitions:` and make the first transition:

```yaml
    transitions:
      - to: phase3-plan
        condition: "lexicon_gate.enabled AND lexicon_gate.artifacts.tasks.enabled AND NOT tasks_lexicon_pass AND iteration < max_iterations"
        action: increment_iteration
      - to: phase3-consensus
        condition: always
```

Add `tasks_lexicon_pass → state.json` to that node's `outputs:` list. Also add a one-line note in
`extension/workflow/phases/phase3-plan.md` §routing: *"When `lexicon_gate.artifacts.tasks.enabled`,
ORCHESTRATOR self-validates `tasks.md` and returns `tasks_lexicon_pass`; COMMANDER persists it to
state.json and re-dispatches `phase3-plan` on a false outcome (capped by max_iterations); soft
`understanding`/consensus runs only after it passes."*

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/unit/test_tasks_wiring.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Verify definition.yaml still parses + dry-run wiring**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('extension/workflow/definition.yaml')); print('definition.yaml OK')"
```
Expected: `definition.yaml OK`

- [ ] **Step 7: Commit**

```bash
git add extension/agents/solution/orchestrator.md extension/workflow/phases/phase3-plan.md extension/workflow/definition.yaml tests/unit/test_tasks_wiring.py
git commit -m "feat(lexicon): wire ORCHESTRATOR tasks gate + phase3-plan re-dispatch + persist tasks_lexicon_pass"
```

---

### Task 10: End-to-end validation on the real 029 artifacts

**Files:**
- (No new source) — validates against `specs/029-builder-spec-workbench/`.
- Test: `tests/unit/test_tasks_e2e_fixture.py`

**Interfaces:**
- Consumes: a committed fixture pair (a known-good TASKS doc + spec) under `tests/fixtures/lexicon/`.

- [ ] **Step 1: Create a committed fixture pair**

Author a minimal, gate-clean `tests/fixtures/lexicon/tasks_ok.md` (TASKS grammar) + `tests/fixtures/lexicon/spec_ok.md` (SPEC grammar) where every REQ is covered and acyclic. (Use the `TASKS_OK`/`SPEC` strings from Task 5, written to files.)

- [ ] **Step 2: Write the failing test**

Create `tests/unit/test_tasks_e2e_fixture.py`:

```python
import pytest, pathlib
from lexicon.tasks import validate_tasks

FX = pathlib.Path("tests/fixtures/lexicon")

@pytest.mark.unit
def test_fixture_pair_is_valid_end_to_end():
    tasks = (FX / "tasks_ok.md").read_text()
    spec = (FX / "spec_ok.md").read_text()
    r = validate_tasks(tasks, glossary=set(), spec_text=spec)
    assert r.ok is True, [f.code for f in r.findings]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m pytest tests/unit/test_tasks_e2e_fixture.py -q`
Expected: FAIL — fixtures absent (`FileNotFoundError`).

- [ ] **Step 4: Add the fixtures, run to pass**

Write the two fixture files (Step 1), then:
Run: `python3 -m pytest tests/unit/test_tasks_e2e_fixture.py -q`
Expected: PASS.

- [ ] **Step 5: Manual smoke against installed CLI + real 029**

Run:
```bash
~/.echelon/venv/bin/python -m pip install -e . --no-deps -q
~/.echelon/venv/bin/lexicon validate specs/029-builder-spec-workbench/tasks.md --type tasks --spec-ref specs/029-builder-spec-workbench/spec.md --glossary specs/029-builder-spec-workbench/glossary.md --json | python3 -c "import sys,json;d=json.load(sys.stdin);print('ok',d['ok']);print('soft',d['soft_score']['overall']);print('findings',[f['code'] for f in d['findings']][:10])"
```
Expected: prints `ok`, a soft score, and any real findings (029's `tasks.md` is row-format today, so expect `parse-error` — that's correct; it documents the migration ORCHESTRATOR must make to block-format under the gate).

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/lexicon/tasks_ok.md tests/fixtures/lexicon/spec_ok.md tests/unit/test_tasks_e2e_fixture.py
git commit -m "test(lexicon): end-to-end tasks fixture validation"
```

---

## Self-Review

**Spec coverage:** Unit 1→Task 1 (grammar); Unit 2→Tasks 2–3 (extract + within-doc parity gates); Unit 3→Task 4 (cross-doc); Valid_tasks→Task 5; Unit 3b soft score→Task 6; Unit 4 CLI→Task 7; config→Task 8; Units 5–7 wiring (ORCHESTRATOR gate mode, phase3-plan re-dispatch, persist flag)→Task 9; E2E→Task 10. All design units covered.

**Placeholder scan:** none. Task 7 uses the real `cli.py` names verified from source (positional `spec`, `glossary`, `as_json`, `_json`, `_load_glossary`); the cross-doc reference is `--spec-ref` (the positional `spec` already occupies `--spec`). Every code step shows complete, runnable code.

**Type consistency:** `Finding(code, message, line, span)` used uniformly (imported from `lexicon.linter`). `TaskRecord` fields are referenced consistently across Tasks 2–6. `validate_tasks(text, glossary, spec_text) -> TasksReport(ok, parse_pass, findings)` consistent across Tasks 5, 7, 10. `task_quality(text) -> dict` keys consistent across Tasks 6, 7.
