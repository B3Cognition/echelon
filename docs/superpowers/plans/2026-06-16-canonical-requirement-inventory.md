# Canonical Requirement Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make verify-spec row identity Python-owned by extracting and persisting a canonical requirement inventory before any LLM fulfillment agents run.

**Architecture:** Add a small deterministic inventory module that extracts stable requirement IDs from spec artifacts and writes `{verify_run_dir}/canonical-requirements.json` plus `.md`. Fulfillment artifact validation will prefer this inventory over LLM-owned `requirement-audit.md`, so invented or dropped report rows fail even when the audit drifts. The verify-spec phase contracts will run the writer before the auditor and instruct agents to preserve the inventory row set.

**Tech Stack:** Python, pytest, markdown table parsing, JSON artifacts, existing `python -m harness` CLI.

---

## File Structure

- Create `src/harness/canonical_requirements.py`
  - Extract requirement IDs from `spec.md`, `plan.md`, `coverage-map.md`, and canonical `tasks.md` `req=` metadata.
  - Write deterministic JSON and markdown inventory artifacts.
  - Validate fulfillment rows against inventory IDs while permitting `TASK-PROGRESS`.
- Modify `src/kernel/fulfillment.py`
  - Add optional `canonical_inventory_path` to `validate_fulfillment_artifacts()`.
- Modify `src/harness/fulfillment_runner.py`
  - Prefer latest `canonical-requirements.json` for row-set validation and cache validation.
- Modify `src/harness/__main__.py`
  - Add `write-canonical-requirements <spec-dir> <verify-run-dir>` command.
- Modify verify-spec phase docs:
  - `extension/workflow/phases/verify-spec-3-audit.md`
  - `extension/workflow/phases/verify-spec-4-map.md`
  - `extension/workflow/phases/verify-spec-5-judge.md`
  - `extension/agents/build/spec-fulfillment-auditor.md`
  - `extension/agents/build/implementation-mapper.md`
  - `extension/agents/build/spec-guard.md`
- Test:
  - Create `tests/unit/test_canonical_requirements.py`
  - Modify `tests/kernel/test_fulfillment.py`
  - Modify `tests/unit/test_fulfillment_runner.py`

## Task 1: Extract and Write Canonical Requirement Inventory

**Files:**
- Create: `src/harness/canonical_requirements.py`
- Create: `tests/unit/test_canonical_requirements.py`

- [ ] **Step 1: Write failing extraction test**

Add `tests/unit/test_canonical_requirements.py`:

```python
from __future__ import annotations

import json

from harness.canonical_requirements import write_canonical_requirements


def test_write_canonical_requirements_extracts_stable_ids_from_spec_inputs(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    verify_run_dir = tmp_path / "runs" / "verify-spec-001-demo-1"
    spec_dir.mkdir(parents=True)
    verify_run_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## Requirements\n\n"
        "- **FR-001**: Users can start a mission.\n"
        "- **NFR-002**: Startup stays below 500ms.\n"
        "### Edge Cases\n"
        "- EDGE-004: Invalid fuel is rejected.\n",
        encoding="utf-8",
    )
    (spec_dir / "plan.md").write_text(
        "## Architecture Decisions\n\n"
        "- AD-001 supports FR-001 but is not a requirement row.\n",
        encoding="utf-8",
    )
    (spec_dir / "coverage-map.md").write_text(
        "| Requirement | Source |\n"
        "| --- | --- |\n"
        "| FR-003 | coverage note |\n",
        encoding="utf-8",
    )
    (spec_dir / "tasks.md").write_text(
        "- [ ] T-001 complexity=standard phase=build req=FR-001,FR-005 depends=none\n",
        encoding="utf-8",
    )

    result = write_canonical_requirements(spec_dir=spec_dir, verify_run_dir=verify_run_dir)

    assert result.count == 5
    payload = json.loads((verify_run_dir / "canonical-requirements.json").read_text())
    assert [row["id"] for row in payload["requirements"]] == [
        "EDGE-004",
        "FR-001",
        "FR-003",
        "FR-005",
        "NFR-002",
    ]
    markdown = (verify_run_dir / "canonical-requirements.md").read_text()
    assert "| FR-005 | task_metadata | tasks.md |" in markdown
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_canonical_requirements.py -q
```

Expected: import failure because `harness.canonical_requirements` does not exist.

- [ ] **Step 3: Implement inventory module**

Create `src/harness/canonical_requirements.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

REQ_ID_RE = re.compile(r"\b(?:FR|NFR|EDGE|REQ|AC|US|SC)-[A-Za-z0-9_.:-]+\b")
TASK_REQ_RE = re.compile(r"\breq=(?P<reqs>[A-Za-z0-9_,.:-]+)")
INVENTORY_JSON = "canonical-requirements.json"
INVENTORY_MD = "canonical-requirements.md"


@dataclass(frozen=True)
class CanonicalRequirement:
    id: str
    source_kind: str
    source_file: str
    source_line: int
    source_text: str


@dataclass(frozen=True)
class CanonicalRequirementInventoryResult:
    json_path: Path
    markdown_path: Path
    count: int
    inventory_hash: str


def extract_canonical_requirements(spec_dir: Path) -> list[CanonicalRequirement]:
    rows: dict[str, CanonicalRequirement] = {}
    for filename, source_kind in (
        ("spec.md", "spec"),
        ("plan.md", "plan"),
        ("coverage-map.md", "coverage"),
    ):
        _collect_markdown_ids(spec_dir / filename, source_kind, rows)
    _collect_task_metadata_ids(spec_dir / "tasks.md", rows)
    return [rows[item_id] for item_id in sorted(rows)]


def write_canonical_requirements(
    *, spec_dir: Path, verify_run_dir: Path
) -> CanonicalRequirementInventoryResult:
    requirements = extract_canonical_requirements(spec_dir)
    verify_run_dir.mkdir(parents=True, exist_ok=True)
    inventory_hash = _inventory_hash(requirements)
    json_path = verify_run_dir / INVENTORY_JSON
    markdown_path = verify_run_dir / INVENTORY_MD
    payload = {
        "kind": "echelon.canonical_requirements",
        "version": 1,
        "spec_dir": str(spec_dir),
        "inventory_hash": inventory_hash,
        "requirements": [
            {
                "id": row.id,
                "source_kind": row.source_kind,
                "source_file": row.source_file,
                "source_line": row.source_line,
                "source_text": row.source_text,
            }
            for row in requirements
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(_render_markdown(requirements), encoding="utf-8")
    return CanonicalRequirementInventoryResult(
        json_path=json_path,
        markdown_path=markdown_path,
        count=len(requirements),
        inventory_hash=inventory_hash,
    )


def canonical_requirement_ids(inventory_path: Path) -> set[str]:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    return {
        str(row.get("id", "")).strip()
        for row in data.get("requirements", [])
        if str(row.get("id", "")).strip()
    }


def _collect_markdown_ids(
    path: Path, source_kind: str, rows: dict[str, CanonicalRequirement]
) -> None:
    if not path.is_file():
        return
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        for item_id in REQ_ID_RE.findall(line):
            rows.setdefault(
                item_id,
                CanonicalRequirement(item_id, source_kind, path.name, lineno, line.strip()),
            )


def _collect_task_metadata_ids(path: Path, rows: dict[str, CanonicalRequirement]) -> None:
    if not path.is_file():
        return
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        match = TASK_REQ_RE.search(line)
        if match is None:
            continue
        for item_id in _split_reqs(match.group("reqs")):
            if item_id == "UNMAPPED" or not REQ_ID_RE.fullmatch(item_id):
                continue
            rows.setdefault(
                item_id,
                CanonicalRequirement(item_id, "task_metadata", path.name, lineno, line.strip()),
            )


def _split_reqs(value: str) -> Iterable[str]:
    for item in value.split(","):
        item = item.strip()
        if item:
            yield item


def _inventory_hash(requirements: list[CanonicalRequirement]) -> str:
    digest = hashlib.sha256()
    for row in requirements:
        digest.update(row.id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row.source_kind.encode("utf-8"))
        digest.update(b"\0")
        digest.update(row.source_file.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(row.source_line).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _render_markdown(requirements: list[CanonicalRequirement]) -> str:
    lines = [
        "# Canonical Requirements",
        "",
        "| ID | Source Kind | Source File | Line | Source Text |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in requirements:
        lines.append(
            f"| {row.id} | {row.source_kind} | {row.source_file} | {row.source_line} | {_escape_cell(row.source_text)} |"
        )
    return "\n".join(lines) + "\n"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|")
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_canonical_requirements.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/harness/canonical_requirements.py tests/unit/test_canonical_requirements.py
git commit -m "feat: write canonical requirement inventory"
```

## Task 2: Validate Fulfillment Reports Against Inventory

**Files:**
- Modify: `src/kernel/fulfillment.py`
- Modify: `tests/kernel/test_fulfillment.py`

- [ ] **Step 1: Write failing validation test**

Add to `tests/kernel/test_fulfillment.py`:

```python
def test_validate_fulfillment_artifacts_prefers_canonical_inventory(tmp_path):
    inventory = tmp_path / "canonical-requirements.json"
    inventory.write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
        encoding="utf-8",
    )
    audit = tmp_path / "requirement-audit.md"
    audit.write_text(
        "| ID | Category |\n"
        "| --- | --- |\n"
        "| FR-001 | functional |\n",
        encoding="utf-8",
    )
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status |\n"
        "| --- | --- |\n"
        "| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )

    result = validate_fulfillment_artifacts(
        requirement_audit_path=audit,
        fulfillment_report_path=report,
        canonical_inventory_path=inventory,
    )

    assert result.ok is False
    assert result.audit_count == 2
    assert result.missing_in_report == ("FR-002",)
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/kernel/test_fulfillment.py -k "canonical_inventory" -q
```

Expected: FAIL because `validate_fulfillment_artifacts()` does not accept `canonical_inventory_path`.

- [ ] **Step 3: Implement optional inventory validation**

In `src/kernel/fulfillment.py`, import:

```python
import json
```

Update `validate_fulfillment_artifacts()` signature:

```python
def validate_fulfillment_artifacts(
    *,
    requirement_audit_path: Path,
    fulfillment_report_path: Path,
    canonical_inventory_path: Path | None = None,
) -> FulfillmentArtifactValidation:
```

Replace audit ID extraction with:

```python
    audit_ids = (
        _canonical_inventory_ids(canonical_inventory_path)
        if canonical_inventory_path is not None and canonical_inventory_path.is_file()
        else fulfillment_table_ids(
            requirement_audit_path.read_text(encoding="utf-8", errors="replace")
        )
    )
```

Add helper:

```python
def _canonical_inventory_ids(inventory_path: Path) -> set[str]:
    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    rows = data.get("requirements", [])
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("id", "")).strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
```

- [ ] **Step 4: Run test to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/kernel/test_fulfillment.py -k "canonical_inventory" -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kernel/fulfillment.py tests/kernel/test_fulfillment.py
git commit -m "feat: validate fulfillment against canonical inventory"
```

## Task 3: Wire Inventory Into Fulfillment Runner and CLI

**Files:**
- Modify: `src/harness/__main__.py`
- Modify: `src/harness/fulfillment_runner.py`
- Modify: `tests/unit/test_fulfillment_runner.py`

- [ ] **Step 1: Write failing runner validation test**

Add to `tests/unit/test_fulfillment_runner.py`:

```python
def test_refresh_fails_when_report_drops_canonical_inventory_row(tmp_path, monkeypatch):
    worktree = tmp_path / "repo"
    worktree.mkdir()
    _init_git(worktree)
    spec_dir = worktree / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("- FR-001\n- FR-002\n", encoding="utf-8")
    run_dir = worktree / "runs" / "verify-spec-001-demo-1"
    run_dir.mkdir(parents=True)
    (run_dir / "canonical-requirements.json").write_text(
        '{"requirements":[{"id":"FR-001"},{"id":"FR-002"}]}\n',
        encoding="utf-8",
    )
    (run_dir / "requirement-audit.md").write_text(
        "| ID | Category |\n| --- | --- |\n| FR-001 | functional |\n",
        encoding="utf-8",
    )
    (spec_dir / "fulfillment-report.md").write_text(
        "| ID | Status |\n| --- | --- |\n| FR-001 | IMPLEMENTED |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("harness.fulfillment_runner.find_skill", lambda *_args: Path("skill.md"))
    monkeypatch.setattr("harness.fulfillment_runner.build_skill_prompt", lambda *_args: "prompt")
    executor = _Executor(exit_code=0)
    runner = FulfillmentRunner(executor)

    result = runner.refresh(str(worktree), "001-demo")

    assert result.status == "failed"
    assert result.exit_code == 2
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py -k "canonical_inventory_row" -q
```

Expected: FAIL because runner validates against audit only.

- [ ] **Step 3: Implement runner inventory lookup**

In `src/harness/fulfillment_runner.py`, import:

```python
from harness.canonical_requirements import INVENTORY_JSON
```

Add:

```python
def _latest_canonical_inventory(worktree: Path, spec_id: str) -> Path | None:
    runs = worktree / "runs"
    if not runs.exists():
        return None
    candidates = list(runs.glob(f"verify-spec-{spec_id}-*/{INVENTORY_JSON}"))
    candidates.extend(runs.glob(f"*/verify-spec/{spec_id}/{INVENTORY_JSON}"))
    existing = [path for path in candidates if path.is_file()]
    return sorted(existing, key=lambda path: path.stat().st_mtime)[-1] if existing else None
```

Update `_latest_report_matches_latest_audit()` to call:

```python
    inventory = _latest_canonical_inventory(worktree, spec_id)
```

and pass:

```python
        canonical_inventory_path=inventory,
```

to `validate_fulfillment_artifacts()`.

- [ ] **Step 4: Add CLI command**

In `src/harness/__main__.py`, add `_write_canonical_requirements()`:

```python
def _write_canonical_requirements() -> None:
    if len(sys.argv) < 4:
        print(
            "Usage: python -m harness write-canonical-requirements <spec-dir> <verify-run-dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    from pathlib import Path

    from harness.canonical_requirements import write_canonical_requirements

    result = write_canonical_requirements(
        spec_dir=Path(sys.argv[2]),
        verify_run_dir=Path(sys.argv[3]),
    )
    print(
        "OK: wrote canonical requirements to "
        f"{result.json_path} and {result.markdown_path} "
        f"({result.count} requirements)"
    )
```

Add dispatch in `main()` before `write-codegraph-evidence`:

```python
    elif subcommand == "write-canonical-requirements":
        _write_canonical_requirements()
```

- [ ] **Step 5: Run tests to verify pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py -k "canonical_inventory_row" -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/__main__.py src/harness/fulfillment_runner.py tests/unit/test_fulfillment_runner.py
git commit -m "feat: enforce canonical inventory in fulfillment refresh"
```

## Task 4: Update Verify-Spec Contracts

**Files:**
- Modify: `extension/workflow/phases/verify-spec-3-audit.md`
- Modify: `extension/workflow/phases/verify-spec-4-map.md`
- Modify: `extension/workflow/phases/verify-spec-5-judge.md`
- Modify: `extension/agents/build/spec-fulfillment-auditor.md`
- Modify: `extension/agents/build/implementation-mapper.md`
- Modify: `extension/agents/build/spec-guard.md`
- Test: `tests/kernel/test_prompt_references.py`

- [ ] **Step 1: Add prompt-reference test**

Add assertions in `tests/kernel/test_prompt_references.py` that these files mention `canonical-requirements.json` and `write-canonical-requirements`.

- [ ] **Step 2: Update phase docs**

In `verify-spec-3-audit.md`, add deterministic pre-audit:

```bash
python -m harness write-canonical-requirements "{spec_dir}" "{verify_run_dir}"
```

and require the auditor to preserve `{verify_run_dir}/canonical-requirements.json`.

In `verify-spec-4-map.md` and `verify-spec-5-judge.md`, include both canonical inventory artifacts in context packs and state that rows outside the inventory must be reported as `unmapped_candidate`, not inserted into fulfillment tables.

- [ ] **Step 3: Update agent prompts**

Update auditor/mapper/guard prompts so:

- auditor writes `requirement-audit.md` with exactly the canonical IDs.
- mapper maps only canonical IDs and lists extras separately.
- guard writes fulfillment rows only for canonical IDs plus `TASK-PROGRESS`.

- [ ] **Step 4: Run prompt tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/workflow/phases/verify-spec-3-audit.md extension/workflow/phases/verify-spec-4-map.md extension/workflow/phases/verify-spec-5-judge.md extension/agents/build/spec-fulfillment-auditor.md extension/agents/build/implementation-mapper.md extension/agents/build/spec-guard.md tests/kernel/test_prompt_references.py
git commit -m "docs: require canonical inventory in verify spec"
```

## Task 5: Verify Stage 3

- [ ] **Step 1: Run focused tests**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_canonical_requirements.py tests/kernel/test_fulfillment.py tests/unit/test_fulfillment_runner.py tests/kernel/test_prompt_references.py -q
```

Expected: PASS.

- [ ] **Step 2: Run broader regression suite**

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-stage3-env uv run --extra dev pytest tests/unit/test_fulfillment_runner.py tests/kernel/test_fulfillment.py tests/unit/test_codegraph_evidence_mapper.py tests/unit/test_verify_spec_codegraph_prompt.py tests/unit/test_verify_spec_reconcile_templates.py tests/kernel/test_prompt_references.py tests/unit/test_ralph_outer.py tests/unit/test_ralph_commit_push.py -q
```

Expected: PASS.

## Self-Review

- Spec coverage: This implements Stage 3 row-set ownership and validation. It does not implement Stage 4 scoped rejudgment.
- Placeholder scan: no TBD/TODO/handwave steps remain.
- Type consistency: `canonical-requirements.json`, `canonical_inventory_path`, and `write-canonical-requirements` are used consistently.
