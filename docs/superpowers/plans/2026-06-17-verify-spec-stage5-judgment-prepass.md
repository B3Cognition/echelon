# Verify-Spec Stage 5 Judgment Pre-Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce token burn in both full and scoped `verify-spec` runs by mechanically classifying obviously settled fulfillment rows and dispatching SPEC-GUARD only for unresolved requirement IDs.

**Architecture:** Add a small Python-owned judgment pre-pass after `implementation-map.md` is written. The pre-pass emits `judgment-prepass.json`/`.md`, a bounded `fallback_ids` queue, and conservative proposed statuses for rows that are already defensible from deterministic evidence. Update the Stage 5 phase contract so SPEC-GUARD judges only `fallback_ids`, then assemble the final report in Python and keep row-set validation Python-owned.

**Tech Stack:** Python 3.11 harness code, existing fulfillment metadata helpers, markdown-table parsing, existing `python -m harness` CLI conventions, pytest unit/kernel tests.

---

## File Structure

- Create `src/harness/judgment_prepass.py`
  - Parse `canonical-requirements.json`, `requirement-audit.md`, `implementation-map.md`, and `state.json`.
  - Emit `judgment-prepass.json` and `judgment-prepass.md`.
  - Classify conservative mechanical statuses: `MISSING`, `UNVERIFIED`, and `IMPLEMENTED`.
  - Expose helpers to assemble full/scoped fulfillment reports from mechanical and fallback rows.
- Modify `src/harness/__main__.py`
  - Add `write-judgment-prepass <spec-dir> <verify-run-dir>` command.
- Modify `src/kernel/fulfillment.py`
  - Add helpers to read fulfillment rows, render fulfillment rows, and assemble a report from a canonical ID order plus pre-pass/spec-guard rows.
- Modify `extension/workflow/phases/verify-spec-5-judge.md`
  - Pass `judgment-prepass.json` and limit SPEC-GUARD to `fallback_ids`.
- Modify `extension/agents/build/spec-guard.md`
  - Tell SPEC-GUARD to emit rows only for fallback IDs and never restate mechanical rows.
- Modify `tests/unit/test_verify_spec_codegraph_prompt.py`
  - Assert Stage 5 contract references `judgment-prepass` and `fallback_ids`.
- Create `tests/unit/test_judgment_prepass.py`
  - Cover mechanical classification, fallback queue generation, and full/scoped assembly helpers.
- Modify `tests/kernel/test_fulfillment.py`
  - Cover row assembly and row-set validation with pre-pass inputs.

## Task 1: Add Judgment Pre-Pass Artifact Generation

**Files:**
- Create: `src/harness/judgment_prepass.py`
- Modify: `src/harness/__main__.py`
- Test: `tests/unit/test_judgment_prepass.py`

- [ ] **Step 1: Write the failing pre-pass writer test**

Create `tests/unit/test_judgment_prepass.py` with:

```python
from __future__ import annotations

import json

from harness.judgment_prepass import write_judgment_prepass


def test_write_judgment_prepass_emits_rows_and_fallback_summary(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps(
            {
                "requirements": [
                    {"id": "FR-001"},
                    {"id": "NFR-002"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (verify_run_dir / "requirement-audit.md").write_text(
        "# Requirement Audit\n\n"
        "| ID | Category | Source | Requirement | Acceptance Signal |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| FR-001 | functional | spec.md | Start mission | UI flow |\n"
        "| NFR-002 | non_functional | spec.md | Startup under 500ms | measured runtime |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "implementation-map.md").write_text(
        "# Implementation Map\n\n"
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        "| FR-001 | app.py:start | tests/test_app.py::test_start | app.start | source_and_test | strong | false | high | |\n"
        "| NFR-002 | perf.py | tests/test_perf.py::test_budget | perf.metric | assertion_only | strong | true | high | |\n",
        encoding="utf-8",
    )
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    result = write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["mechanical_count"] == 2
    assert payload["summary"]["fallback_count"] == 0
    by_id = {row["id"]: row for row in payload["rows"]}
    assert by_id["FR-001"]["proposed_status"] == "IMPLEMENTED"
    assert by_id["NFR-002"]["proposed_status"] == "UNVERIFIED"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py -q
```

Expected: FAIL with `ModuleNotFoundError` or missing `write_judgment_prepass`.

- [ ] **Step 3: Implement the pre-pass writer**

Create `src/harness/judgment_prepass.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class JudgmentPrepassResult:
    json_path: Path
    markdown_path: Path
    mechanical_count: int
    fallback_count: int


def write_judgment_prepass(*, spec_dir: Path, verify_run_dir: Path) -> JudgmentPrepassResult:
    rows = build_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
    payload = {
        "rows": [row.to_dict() for row in rows],
        "summary": {
            "mechanical_count": sum(1 for row in rows if row.mechanical),
            "fallback_count": sum(1 for row in rows if not row.mechanical),
            "fallback_ids": [row.id for row in rows if not row.mechanical],
        },
    }
    json_path = verify_run_dir / "judgment-prepass.json"
    markdown_path = verify_run_dir / "judgment-prepass.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_judgment_prepass_markdown(rows), encoding="utf-8")
    return JudgmentPrepassResult(
        json_path=json_path,
        markdown_path=markdown_path,
        mechanical_count=payload["summary"]["mechanical_count"],
        fallback_count=payload["summary"]["fallback_count"],
    )
```

Also add the CLI hook in `src/harness/__main__.py` following the existing
`write-canonical-requirements` command pattern:

```python
elif command == "write-judgment-prepass":
    if len(argv) != 4:
        raise SystemExit(
            "Usage: python -m harness write-judgment-prepass <spec-dir> <verify-run-dir>"
        )
    from harness.judgment_prepass import write_judgment_prepass

    result = write_judgment_prepass(
        spec_dir=Path(argv[2]).resolve(),
        verify_run_dir=Path(argv[3]).resolve(),
    )
    print(
        f"OK: wrote judgment pre-pass to {result.json_path} "
        f"(mechanical={result.mechanical_count}, fallback={result.fallback_count})"
    )
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/judgment_prepass.py src/harness/__main__.py tests/unit/test_judgment_prepass.py
git commit -m "feat: add verify-spec judgment pre-pass writer"
```

## Task 2: Add Conservative Mechanical Classification Rules

**Files:**
- Modify: `src/harness/judgment_prepass.py`
- Test: `tests/unit/test_judgment_prepass.py`

- [ ] **Step 1: Write failing classification tests**

Extend `tests/unit/test_judgment_prepass.py` with:

```python
def test_prepass_marks_blank_evidence_rows_missing(tmp_path):
    rows = _build_rows(
        tmp_path,
        implementation_row="| FR-010 |  |  |  | source_only | weak | false | none | |",
        requirement_id="FR-010",
    )
    assert rows[0].proposed_status == "MISSING"
    assert rows[0].mechanical is True


def test_prepass_falls_back_when_notes_signal_partial_or_ambiguous(tmp_path):
    rows = _build_rows(
        tmp_path,
        implementation_row="| FR-011 | app.py:run | tests/test_app.py::test_run | app.run | source_and_test | strong | false | high | partial coverage remains |",
        requirement_id="FR-011",
    )
    assert rows[0].mechanical is False
    assert rows[0].fallback_reason == "notes_require_judgment"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py -q
```

Expected: FAIL because blank-evidence rows are not yet classified and partial
notes are not routed to fallback.

- [ ] **Step 3: Implement conservative classification**

In `src/harness/judgment_prepass.py`, add a conservative classifier:

```python
def classify_row(row: ImplementationRow) -> JudgmentRow:
    if row.runtime_threshold and row.evidence_kind == "assertion_only":
        return JudgmentRow.mechanical(row.id, "UNVERIFIED", "threshold_assertion_only")
    if (
        not row.implementation_evidence.strip()
        and not row.test_evidence.strip()
        and row.confidence == "none"
    ):
        return JudgmentRow.mechanical(row.id, "MISSING", "no_evidence")
    if _notes_require_judgment(row.notes):
        return JudgmentRow.fallback(row.id, "notes_require_judgment")
    if (
        not row.runtime_threshold
        and row.confidence == "high"
        and row.evidence_strength == "strong"
        and row.implementation_evidence.strip()
        and row.test_evidence.strip()
    ):
        return JudgmentRow.mechanical(row.id, "IMPLEMENTED", "source_and_test_strong")
    return JudgmentRow.fallback(row.id, "confidence_or_semantics_require_judgment")
```

Use a note screen like:

```python
def _notes_require_judgment(notes: str) -> bool:
    lowered = notes.lower()
    return any(
        token in lowered
        for token in ("partial", "ambiguous", "deviat", "obsolete", "missing acceptance")
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/judgment_prepass.py tests/unit/test_judgment_prepass.py
git commit -m "feat: classify deterministic verify-spec judgments"
```

## Task 3: Narrow Stage 5 Prompt Contract to `fallback_ids`

**Files:**
- Modify: `extension/workflow/phases/verify-spec-5-judge.md`
- Modify: `extension/agents/build/spec-guard.md`
- Modify: `tests/unit/test_verify_spec_codegraph_prompt.py`

- [ ] **Step 1: Write failing prompt-contract tests**

Extend `tests/unit/test_verify_spec_codegraph_prompt.py` with:

```python
def test_verify_spec_stage5_references_judgment_prepass():
    text = (PHASE_DIR / "verify-spec-5-judge.md").read_text(encoding="utf-8")
    assert "judgment-prepass.json" in text
    assert "fallback_ids" in text


def test_spec_guard_prompt_forbids_restatement_of_mechanical_rows():
    text = (AGENT_DIR / "spec-guard.md").read_text(encoding="utf-8")
    assert "judge only IDs listed in `fallback_ids`" in text
    assert "must not emit rows for mechanically decided IDs" in text
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/unit/test_verify_spec_codegraph_prompt.py -q
```

Expected: FAIL because Stage 5 and SPEC-GUARD do not yet mention
`judgment-prepass.json` or `fallback_ids`.

- [ ] **Step 3: Update the phase and agent contracts**

In `extension/workflow/phases/verify-spec-5-judge.md`, add to the context pack:

```md
- `{verify_run_dir}/judgment-prepass.json`
- `{verify_run_dir}/judgment-prepass.md`
```

Replace the scoped/full dispatch paragraph with:

```md
Python owns mechanical judgments and the final report row set. SPEC-GUARD must
judge only IDs listed in `fallback_ids` from `judgment-prepass.json`.
SPEC-GUARD must not emit rows for mechanically decided IDs.
```

In `extension/agents/build/spec-guard.md`, add an ALWAYS / NEVER rule:

```md
ALWAYS judge only IDs listed in `fallback_ids` when `judgment-prepass.json` is present.
NEVER emit rows for mechanically decided IDs or restate preserved scoped rows.
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest tests/unit/test_verify_spec_codegraph_prompt.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/phases/verify-spec-5-judge.md extension/agents/build/spec-guard.md tests/unit/test_verify_spec_codegraph_prompt.py
git commit -m "feat: narrow stage 5 judgment prompt to fallback ids"
```

## Task 4: Assemble Full and Scoped Reports in Python

**Files:**
- Modify: `src/harness/judgment_prepass.py`
- Modify: `src/kernel/fulfillment.py`
- Test: `tests/unit/test_judgment_prepass.py`
- Test: `tests/kernel/test_fulfillment.py`

- [ ] **Step 1: Write failing assembly tests**

Add to `tests/unit/test_judgment_prepass.py`:

```python
def test_assemble_full_report_preserves_canonical_order(tmp_path):
    report = assemble_full_report(
        canonical_ids=["FR-001", "FR-002"],
        mechanical_rows={"FR-001": "| FR-001 | IMPLEMENTED | impl |"},
        fallback_rows={"FR-002": "| FR-002 | PARTIAL | needs judgment |"},
        task_progress_row="| TASK-PROGRESS | PARTIAL | mismatch |",
    )
    assert report.splitlines()[0] == "# Fulfillment Report"
    assert report.index("| FR-001 |") < report.index("| FR-002 |")
    assert "| TASK-PROGRESS | PARTIAL | mismatch |" in report
```

Add to `tests/kernel/test_fulfillment.py`:

```python
def test_validate_fulfillment_artifacts_accepts_python_assembled_report(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "# Fulfillment Report\n\n"
        "| ID | Status | Evidence |\n"
        "| --- | --- | --- |\n"
        "| FR-001 | IMPLEMENTED | impl |\n"
        "| FR-002 | MISSING | |\n",
        encoding="utf-8",
    )
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}',
        encoding="utf-8",
    )
    result = validate_fulfillment_artifacts(
        report_path=report,
        canonical_inventory_path=inventory,
    )
    assert result.valid is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py tests/kernel/test_fulfillment.py -q
```

Expected: FAIL because report assembly helpers do not exist.

- [ ] **Step 3: Implement Python-owned assembly**

In `src/harness/judgment_prepass.py`, add:

```python
def assemble_full_report(
    *,
    canonical_ids: list[str],
    mechanical_rows: dict[str, str],
    fallback_rows: dict[str, str],
    task_progress_row: str | None = None,
) -> str:
    lines = [
        "# Fulfillment Report",
        "",
        "| ID | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for item_id in canonical_ids:
        row = mechanical_rows.get(item_id) or fallback_rows.get(item_id)
        if row is None:
            raise ValueError(f"missing fulfillment row for {item_id}")
        lines.append(row)
    if task_progress_row:
        lines.append(task_progress_row)
    return "\n".join(lines) + "\n"
```

If `src/kernel/fulfillment.py` needs a shared row parser, add a helper shaped
like:

```python
def fulfillment_row_ids(report_text: str) -> list[str]:
    ids: list[str] = []
    for line in report_text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] not in {"ID", "---"}:
            ids.append(cells[0])
    return ids
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py tests/kernel/test_fulfillment.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/judgment_prepass.py src/kernel/fulfillment.py tests/unit/test_judgment_prepass.py tests/kernel/test_fulfillment.py
git commit -m "feat: assemble fulfillment reports from prepass and fallback rows"
```

## Task 5: Add End-to-End Regression Coverage for Large Deterministic Maps

**Files:**
- Modify: `tests/unit/test_judgment_prepass.py`

- [ ] **Step 1: Write the regression test**

Add:

```python
def test_large_map_produces_small_fallback_queue(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)

    requirement_rows = [{"id": f"FR-{i:03d}"} for i in range(1, 21)]
    (verify_run_dir / "canonical-requirements.json").write_text(
        json.dumps({"requirements": requirement_rows}),
        encoding="utf-8",
    )
    (verify_run_dir / "requirement-audit.md").write_text(_audit_markdown([row["id"] for row in requirement_rows]), encoding="utf-8")
    lines = [
        "# Implementation Map",
        "",
        "| ID | Implementation Evidence | Test Evidence | CodeGraph Evidence | Evidence Kind | Evidence Strength | Runtime Threshold | Confidence | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in requirement_rows[:18]:
        lines.append(
            f"| {row['id']} | app.py:{row['id']} | tests/test_app.py::{row['id']} | app.{row['id']} | source_and_test | strong | false | high | |"
        )
    lines.append("| FR-019 | perf.py |  | perf.metric | source_only | medium | false | medium | ambiguous |")
    lines.append("| FR-020 |  |  |  | source_only | weak | false | none | |")
    (verify_run_dir / "implementation-map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (verify_run_dir / "state.json").write_text("{}", encoding="utf-8")

    result = write_judgment_prepass(spec_dir=spec_dir, verify_run_dir=verify_run_dir)
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))

    assert payload["summary"]["mechanical_count"] == 19
    assert payload["summary"]["fallback_ids"] == ["FR-019"]
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py -q
```

Expected: FAIL until the mechanical/fallback queue accounting is correct for
mixed large inputs.

- [ ] **Step 3: Adjust helpers until regression passes**

Keep the implementation conservative:

```python
# expected outcome
# FR-001..FR-018 -> mechanical IMPLEMENTED
# FR-019 -> fallback because notes contain "ambiguous"
# FR-020 -> mechanical MISSING
```

Do not broaden the mechanical `IMPLEMENTED` rule beyond:

```python
row.confidence == "high"
and row.evidence_strength == "strong"
and row.implementation_evidence.strip()
and row.test_evidence.strip()
and not row.runtime_threshold
```

- [ ] **Step 4: Run focused suite to verify pass**

Run:

```bash
python -m pytest tests/unit/test_judgment_prepass.py tests/unit/test_verify_spec_codegraph_prompt.py tests/kernel/test_fulfillment.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_judgment_prepass.py
git commit -m "test: add stage 5 judgment pre-pass regression coverage"
```

## Task 6: Run Final Verification

**Files:**
- No production changes expected.

- [ ] **Step 1: Run the full focused verification suite**

Run:

```bash
python -m pytest \
  tests/unit/test_judgment_prepass.py \
  tests/unit/test_verify_spec_codegraph_prompt.py \
  tests/kernel/test_fulfillment.py \
  tests/unit/test_fulfillment_runner.py \
  tests/unit/test_ralph_outer.py -q
```

Expected: PASS with 0 failures.

- [ ] **Step 2: Check git diff**

Run:

```bash
git status --short
```

Expected: only the planned Stage 5 files are modified.

- [ ] **Step 3: Commit the verification-stable slice**

```bash
git add src/harness/judgment_prepass.py src/harness/__main__.py src/kernel/fulfillment.py extension/workflow/phases/verify-spec-5-judge.md extension/agents/build/spec-guard.md tests/unit/test_judgment_prepass.py tests/unit/test_verify_spec_codegraph_prompt.py tests/kernel/test_fulfillment.py
git commit -m "feat: add verify-spec stage 5 judgment pre-pass"
```
