# Spec Fulfillment Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `echelon verify-spec` and `echelon reopen` so users can audit whether a completed spec is actually implemented, then reopen missing coverage into harness-ready tasks.

**Architecture:** `verify-spec` is read-only except for report artifacts in the spec directory and verification runtime artifacts under `runs/`. It refreshes CodeGraph every run, maps spec requirements to source/test evidence, writes `fulfillment-report.md` and optional `fulfillment-gaps.md`, and never changes application code or spec status. `reopen` is the explicit mutating command that converts gaps into `FG-T*` tasks and marks the spec back to `In Progress`.

**Tech Stack:** Python CLI/kernel helpers, spec-kit extension markdown commands/agents/workflow phases, existing CodeGraph bridge shell/Node scripts, pytest, shell integration tests.

---

## File Structure

- Create `src/kernel/fulfillment.py`: pure helpers for fulfillment status parsing, blocking-gap detection, and verification run directory resolution.
- Create `tests/kernel/test_fulfillment.py`: unit tests for helper behavior.
- Modify `src/echelon/cli.py`: add `verify-spec` and `reopen` to CLI usage and `SKILL_MAP`.
- Create `extension/commands/echelon.verify-spec.md`: read-only command wrapper.
- Create `extension/commands/echelon.reopen.md`: mutating command wrapper.
- Modify `extension/workflow/definition.yaml`: add verify-spec and reopen workflow nodes.
- Create `extension/workflow/phases/verify-spec-1-init.md`: locate spec and create verification run directory.
- Create `extension/workflow/phases/verify-spec-2-codegraph.md`: refresh CodeGraph into `runs/`.
- Create `extension/workflow/phases/verify-spec-3-audit.md`: dispatch fulfillment auditor.
- Create `extension/workflow/phases/verify-spec-4-map.md`: dispatch implementation mapper.
- Create `extension/workflow/phases/verify-spec-5-judge.md`: dispatch spec guard in fulfillment mode and write reports.
- Create `extension/workflow/phases/reopen-1-apply-gaps.md`: convert `fulfillment-gaps.md` into tasks/status updates.
- Create `extension/agents/build/spec-fulfillment-auditor.md`: extract canonical checklist from spec.
- Create `extension/agents/build/implementation-mapper.md`: map checklist to code/test/CodeGraph evidence.
- Modify `extension/agents/build/spec-guard.md`: add fulfillment-report judging mode, or create a small appendix if prompt size is a concern.
- Modify `extension/commands/echelon.harness-run.md`: read `fulfillment-gaps.md` as mandatory implementation context.
- Modify `src/harness/land.py`: parse latest fulfillment report and warn/block based on unresolved statuses.
- Modify `tests/unit/test_land.py`: add land warning/block behavior tests.
- Modify docs: `README.md`, `docs/re-overview.md` only if command table/user flow needs updating.

---

### Task 1: Fulfillment Kernel Helpers

**Files:**
- Create: `src/kernel/fulfillment.py`
- Create: `tests/kernel/test_fulfillment.py`

- [ ] **Step 1: Write failing tests**

Create `tests/kernel/test_fulfillment.py`:

```python
from pathlib import Path

from kernel.fulfillment import (
    blocking_statuses,
    fulfillment_has_blocking_gaps,
    latest_fulfillment_report,
    make_verify_spec_run_dir,
)


def test_make_verify_spec_run_dir_uses_active_run(tmp_path):
    run_dir = tmp_path / "runs" / "spec-20260602"
    run_dir.mkdir(parents=True)
    (tmp_path / "runs" / ".current").write_text("spec-20260602")

    result = make_verify_spec_run_dir(tmp_path, "001")

    assert result == run_dir / "verify-spec" / "001"


def test_make_verify_spec_run_dir_creates_standalone_verify_run(tmp_path):
    result = make_verify_spec_run_dir(tmp_path, "001", timestamp="20260602-120000")

    assert result == tmp_path / "runs" / "verify-spec-001-20260602-120000"


def test_latest_fulfillment_report_returns_newest(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    older = spec_dir / "fulfillment-report.md"
    newer = spec_dir / "fulfillment-report-2.md"
    older.write_text("old")
    newer.write_text("new")

    assert latest_fulfillment_report(spec_dir) == newer


def test_fulfillment_has_blocking_gaps_detects_missing_partial_deviated(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | IMPLEMENTED | src/a.py | high | ok |\n"
        "| FR-002 | MISSING | none | high | absent |\n"
    )

    assert fulfillment_has_blocking_gaps(report) is True


def test_fulfillment_has_blocking_gaps_strict_treats_unverified_as_blocking(tmp_path):
    report = tmp_path / "fulfillment-report.md"
    report.write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | UNVERIFIED | src/a.py | medium | no test |\n"
    )

    assert fulfillment_has_blocking_gaps(report, strict=True) is True
    assert fulfillment_has_blocking_gaps(report, strict=False) is False


def test_blocking_statuses():
    assert blocking_statuses(strict=False) == {"MISSING", "PARTIAL", "DEVIATED"}
    assert blocking_statuses(strict=True) == {
        "MISSING",
        "PARTIAL",
        "DEVIATED",
        "UNVERIFIED",
    }
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_fulfillment.py
```

Expected: import failure for `kernel.fulfillment`.

- [ ] **Step 3: Implement helpers**

Create `src/kernel/fulfillment.py`:

```python
"""Fulfillment verification helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re


NON_STRICT_BLOCKING = {"MISSING", "PARTIAL", "DEVIATED"}
STRICT_BLOCKING = NON_STRICT_BLOCKING | {"UNVERIFIED"}


def blocking_statuses(strict: bool = False) -> set[str]:
    return set(STRICT_BLOCKING if strict else NON_STRICT_BLOCKING)


def make_verify_spec_run_dir(
    project_root: Path,
    spec_id: str,
    timestamp: str | None = None,
) -> Path:
    runs = project_root / "runs"
    current = runs / ".current"
    if current.exists():
        run_id = current.read_text().strip()
        active = runs / run_id
        if run_id and active.exists():
            return active / "verify-spec" / spec_id

    stamp = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    return runs / f"verify-spec-{spec_id}-{stamp}"


def latest_fulfillment_report(spec_dir: Path) -> Path | None:
    reports = sorted(
        spec_dir.glob("fulfillment-report*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return reports[0] if reports else None


def _statuses_in_report(report_path: Path) -> set[str]:
    text = report_path.read_text()
    statuses: set[str] = set()
    for match in re.finditer(
        r"\|\s*(?:FR|AC|US|NFR|REQ|EDGE)-[^|]+\|\s*([A-Z_]+)\s*\|",
        text,
    ):
        statuses.add(match.group(1))
    return statuses


def fulfillment_has_blocking_gaps(report_path: Path, strict: bool = False) -> bool:
    if not report_path.exists():
        return False
    return bool(_statuses_in_report(report_path) & blocking_statuses(strict))
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_fulfillment.py
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/kernel/fulfillment.py tests/kernel/test_fulfillment.py
git commit -m "feat: add fulfillment verification helpers"
```

---

### Task 2: CLI Command Registration

**Files:**
- Modify: `src/echelon/cli.py`
- Test: `tests/unit/test_cli_fulfillment_commands.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_cli_fulfillment_commands.py`:

```python
from echelon import cli


def test_verify_spec_command_registered():
    assert cli.SKILL_MAP["verify-spec"] == "echelon.verify-spec"
    assert "verify-spec <spec_id>" in cli.USAGE


def test_reopen_command_registered():
    assert cli.SKILL_MAP["reopen"] == "echelon.reopen"
    assert "reopen  <spec_id>" in cli.USAGE
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_fulfillment_commands.py
```

Expected: missing `SKILL_MAP` keys.

- [ ] **Step 3: Add CLI entries**

Modify `src/echelon/cli.py`:

```python
SKILL_MAP = {
    "bugfix":  "echelon.bugfix",
    "build":   "echelon.build",
    "review":  "echelon.review",
    "change":  "echelon.change",
    "codegen": "echelon.codegen",
    "cicd":    "echelon.cicd",
    "verify-spec": "echelon.verify-spec",
    "reopen": "echelon.reopen",
}
```

Add usage lines near `bugfix`:

```text
  verify-spec <spec_id> [strict=true]        Audit whether implementation fulfills spec
  reopen  <spec_id> [from=<report>]          Reopen spec from fulfillment gaps
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_cli_fulfillment_commands.py
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/echelon/cli.py tests/unit/test_cli_fulfillment_commands.py
git commit -m "feat: register fulfillment verification commands"
```

---

### Task 3: Verify-Spec Command and Workflow Skeleton

**Files:**
- Create: `extension/commands/echelon.verify-spec.md`
- Create: `extension/workflow/phases/verify-spec-1-init.md`
- Create: `extension/workflow/phases/verify-spec-2-codegraph.md`
- Create: `extension/workflow/phases/verify-spec-3-audit.md`
- Create: `extension/workflow/phases/verify-spec-4-map.md`
- Create: `extension/workflow/phases/verify-spec-5-judge.md`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/kernel/test_prompt_references.py`

- [ ] **Step 1: Add prompt reference test expectations**

Extend `tests/kernel/test_prompt_references.py` with:

```python
def test_verify_spec_command_and_phases_exist():
    assert (EXTENSION_ROOT / "commands" / "echelon.verify-spec.md").exists()
    for phase in [
        "verify-spec-1-init.md",
        "verify-spec-2-codegraph.md",
        "verify-spec-3-audit.md",
        "verify-spec-4-map.md",
        "verify-spec-5-judge.md",
    ]:
        assert (EXTENSION_ROOT / "workflow" / "phases" / phase).exists()
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -k verify_spec
```

Expected: missing files.

- [ ] **Step 3: Create command file**

Create `extension/commands/echelon.verify-spec.md`:

```markdown
---
name: speckit.echelon.verify-spec
description: "Read-only audit: verify whether current implementation fulfills a spec"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER executing a read-only spec fulfillment audit.

Read `agents/control/commander.md` first. Then read `workflow/definition.yaml`
`verify_spec:` section. Start at `verify-spec-1-init`.

ALWAYS treat this command as read-only for application source files.
NEVER modify source code, spec status, or tasks.md.

Allowed writes:
- `specs/<spec-id>-*/fulfillment-report.md`
- `specs/<spec-id>-*/fulfillment-gaps.md`
- `runs/spec-20260602-120000/verify-spec/001/codegraph-summary.json`
- `runs/verify-spec-001-20260602-120000/codegraph-summary.json`

## User Input

$ARGUMENTS
```

- [ ] **Step 4: Create workflow phases**

Create the five phase files with concise contracts:

`verify-spec-1-init.md`:

```markdown
# Phase: verify-spec-1-init

Parse `spec_id` and optional `strict=true`. Locate `specs/{spec_id}-*/`.
Create verification runtime directory:
- active run: `runs/<run-id>/verify-spec/{spec_id}/`
- no active run: `runs/verify-spec-{spec_id}-{timestamp}/`

Write `state.json` in that directory with:
- spec_id
- spec_dir
- strict
- verify_run_dir
- status: in_progress
```

`verify-spec-2-codegraph.md`:

```markdown
# Phase: verify-spec-2-codegraph

Run the existing RE CodeGraph bridge against the current source tree.
Write:
- `{verify_run_dir}/codegraph-analysis.json`
- `{verify_run_dir}/codegraph-summary.json`

If CodeGraph fails, write `{verify_run_dir}/codegraph-error.txt` and continue
with `structural_evidence: degraded`.
```

`verify-spec-3-audit.md`:

```markdown
# Phase: verify-spec-3-audit

Dispatch `speckit-echelon-spec-fulfillment-auditor`.
Context:
- spec.md
- tasks.md
- coverage-map.md if present

Output:
- checklist items with IDs, source text, category, acceptance signal
```

`verify-spec-4-map.md`:

```markdown
# Phase: verify-spec-4-map

Dispatch `speckit-echelon-implementation-mapper`.
Context:
- fulfillment checklist
- source tree
- tests
- `{verify_run_dir}/codegraph-summary.json`
- `{verify_run_dir}/codegraph-analysis.json` only if needed

Output:
- evidence map per requirement
```

`verify-spec-5-judge.md`:

```markdown
# Phase: verify-spec-5-judge

Dispatch `speckit-echelon-spec-guard` in fulfillment mode.
Write:
- `specs/{spec_id}-*/fulfillment-report.md`
- `specs/{spec_id}-*/fulfillment-gaps.md` only when actionable gaps exist

Return summary and recommended action.
```

- [ ] **Step 5: Add workflow definition section**

Add to `extension/workflow/definition.yaml`:

```yaml
verify_spec:
  state_file: "{verify_run_dir}/state.json"
  phases:
    - id: verify-spec-1-init
      spec_file: workflow/phases/verify-spec-1-init.md
      type: commander_internal
      transitions:
        - to: verify-spec-2-codegraph
          condition: always
    - id: verify-spec-2-codegraph
      spec_file: workflow/phases/verify-spec-2-codegraph.md
      type: commander_internal
      transitions:
        - to: verify-spec-3-audit
          condition: always
    - id: verify-spec-3-audit
      spec_file: workflow/phases/verify-spec-3-audit.md
      type: agent
      agent: speckit-echelon-spec-fulfillment-auditor
      transitions:
        - to: verify-spec-4-map
          condition: always
    - id: verify-spec-4-map
      spec_file: workflow/phases/verify-spec-4-map.md
      type: agent
      agent: speckit-echelon-implementation-mapper
      transitions:
        - to: verify-spec-5-judge
          condition: always
    - id: verify-spec-5-judge
      spec_file: workflow/phases/verify-spec-5-judge.md
      type: agent
      agent: speckit-echelon-spec-guard
      transitions:
        - to: DONE
          condition: always
```

- [ ] **Step 6: Run tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py tests/kernel/test_phase_graph.py
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add extension/commands/echelon.verify-spec.md extension/workflow/phases/verify-spec-*.md extension/workflow/definition.yaml tests/kernel/test_prompt_references.py
git commit -m "feat: add verify-spec workflow skeleton"
```

---

### Task 4: Fulfillment Agents

**Files:**
- Create: `extension/agents/build/spec-fulfillment-auditor.md`
- Create: `extension/agents/build/implementation-mapper.md`
- Modify: `extension/agents/build/spec-guard.md`
- Test: `tests/kernel/test_prompt_references.py`

- [ ] **Step 1: Add agent prompt tests**

Extend `tests/kernel/test_prompt_references.py`:

```python
def test_fulfillment_agents_define_output_blocks():
    for agent in [
        "spec-fulfillment-auditor.md",
        "implementation-mapper.md",
    ]:
        text = (EXTENSION_ROOT / "agents" / "build" / agent).read_text()
        assert "## ALWAYS / NEVER Rules" in text
        assert "## Output Block" in text
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -k fulfillment_agents
```

Expected: missing files.

- [ ] **Step 3: Create SPEC-FULFILLMENT-AUDITOR**

Create `extension/agents/build/spec-fulfillment-auditor.md`:

```markdown
# speckit-echelon-spec-fulfillment-auditor Agent

You are SPEC-FULFILLMENT-AUDITOR. You extract a canonical fulfillment checklist
from a spec without judging implementation.

## ALWAYS / NEVER Rules

ALWAYS preserve source requirement IDs and quote short source snippets.
NEVER merge two requirements into one checklist item.

ALWAYS include acceptance criteria, user stories, edge cases, and measurable NFRs.
NEVER limit the checklist to only `FR-*` rows.

## Work Instructions

Read `spec.md`, `tasks.md`, and `coverage-map.md` if present. Produce checklist
items with fields: id, type, source_text, expected_behavior, acceptance_signal.

## Output Block

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  checklist:
    - id: FR-001
      type: functional
      source_text: "User receives an in-app notification after successful purchase."
      expected_behavior: "Completing a purchase creates one unread notification for the purchaser."
      acceptance_signal: "Integration test completes a purchase and asserts notification persistence."
  blocked_reason: null
```
```

- [ ] **Step 4: Create IMPLEMENTATION-MAPPER**

Create `extension/agents/build/implementation-mapper.md`:

```markdown
# speckit-echelon-implementation-mapper Agent

You are IMPLEMENTATION-MAPPER. You map fulfillment checklist items to concrete
source, test, route, UI, and CodeGraph evidence.

## ALWAYS / NEVER Rules

ALWAYS read fresh verification-local CodeGraph summary before full graph detail.
NEVER use stale brownfield RE artifacts as fulfillment evidence.

ALWAYS distinguish source evidence from executable test evidence.
NEVER mark a requirement implemented only because a similar symbol name exists.

## Work Instructions

Use checklist items from SPEC-FULFILLMENT-AUDITOR. For each item, search source,
tests, routes, and configs. Read `{verify_run_dir}/codegraph-summary.json`; read
full graph only for symbol-level trace.

## Output Block

```yaml
echelon_result:
  verdict: DONE | BLOCKED
  evidence_map:
    - id: FR-001
      source_evidence: []
      test_evidence: []
      graph_evidence: []
      confidence: low | medium | high
      notes: ""
  blocked_reason: null
```
```

- [ ] **Step 5: Add fulfillment mode to SPEC-GUARD**

Modify `extension/agents/build/spec-guard.md` with a compact section:

```markdown
## Fulfillment Mode

When dispatched by `verify-spec-5-judge`, compare the fulfillment checklist and
evidence map. Assign exactly one status per item: IMPLEMENTED, PARTIAL,
UNVERIFIED, MISSING, DEVIATED, or OBSOLETE_SPEC. Write
`fulfillment-report.md` and `fulfillment-gaps.md` when actionable gaps exist.
```

- [ ] **Step 6: Run prompt tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add extension/agents/build/spec-fulfillment-auditor.md extension/agents/build/implementation-mapper.md extension/agents/build/spec-guard.md tests/kernel/test_prompt_references.py
git commit -m "feat: add fulfillment verification agents"
```

---

### Task 5: Reopen Command

**Files:**
- Create: `extension/commands/echelon.reopen.md`
- Create: `extension/workflow/phases/reopen-1-apply-gaps.md`
- Modify: `extension/workflow/definition.yaml`
- Test: `tests/kernel/test_prompt_references.py`

- [ ] **Step 1: Write prompt reference test**

Extend `tests/kernel/test_prompt_references.py`:

```python
def test_reopen_command_and_phase_exist():
    assert (EXTENSION_ROOT / "commands" / "echelon.reopen.md").exists()
    assert (EXTENSION_ROOT / "workflow" / "phases" / "reopen-1-apply-gaps.md").exists()
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -k reopen
```

Expected: missing files.

- [ ] **Step 3: Create command and phase**

Create `extension/commands/echelon.reopen.md`:

```markdown
---
name: speckit.echelon.reopen
description: "Reopen a spec from fulfillment gaps and append harness-ready tasks"
behavior:
  invocation: explicit
---

## Role

You are COMMANDER reopening a spec from verified fulfillment gaps.

Read `agents/control/commander.md`, then `workflow/definition.yaml` `reopen:`.

Allowed writes:
- spec frontmatter/status
- `tasks.md`
- `reopen-{n}.md`

Never modify application source code.

## User Input

$ARGUMENTS
```

Create `extension/workflow/phases/reopen-1-apply-gaps.md`:

```markdown
# Phase: reopen-1-apply-gaps

Parse `spec_id` and optional `from=<path>`. Locate latest `fulfillment-gaps.md`
when `from` is absent.

Set spec status/frontmatter to `In Progress`.

Append tasks to `tasks.md`:

```markdown
## Fulfillment Gap Tasks

- [ ] FG-T1: Add failing test for FG-001 from fulfillment-gaps.md
- [ ] FG-T2: Implement missing behavior for FG-001
- [ ] FG-T3: Update fulfillment evidence by rerunning `echelon verify-spec {spec_id}`
```

Write `reopen-{n}.md` summarizing the gaps converted to tasks.
```

- [ ] **Step 4: Add workflow section**

Add to `extension/workflow/definition.yaml`:

```yaml
reopen:
  phases:
    - id: reopen-1-apply-gaps
      spec_file: workflow/phases/reopen-1-apply-gaps.md
      type: commander_internal
      transitions:
        - to: DONE
          condition: always
```

- [ ] **Step 5: Run tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py tests/kernel/test_phase_graph.py
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add extension/commands/echelon.reopen.md extension/workflow/phases/reopen-1-apply-gaps.md extension/workflow/definition.yaml tests/kernel/test_prompt_references.py
git commit -m "feat: add spec reopen workflow"
```

---

### Task 6: Harness Consumes Fulfillment Gaps

**Files:**
- Modify: `extension/commands/echelon.harness-run.md`
- Test: `tests/kernel/test_prompt_references.py`

- [ ] **Step 1: Write failing test**

Add to `tests/kernel/test_prompt_references.py`:

```python
def test_harness_run_reads_fulfillment_gaps():
    text = (EXTENSION_ROOT / "commands" / "echelon.harness-run.md").read_text()
    assert "fulfillment-gaps.md" in text
    assert "mandatory implementation context" in text
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -k fulfillment_gaps
```

Expected: missing text.

- [ ] **Step 3: Patch harness command**

In `extension/commands/echelon.harness-run.md` Step 5, extend the read list:

```markdown
- `specs/{spec_id}-{spec_name}/fulfillment-gaps.md` — if present, read it as
  mandatory implementation context. These are verified missing spec-coverage
  tasks and must be addressed before convergence.
```

- [ ] **Step 4: Run test**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_prompt_references.py -k fulfillment_gaps
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add extension/commands/echelon.harness-run.md tests/kernel/test_prompt_references.py
git commit -m "feat: pass fulfillment gaps to harness"
```

---

### Task 7: Land Warns or Blocks on Fulfillment Gaps

**Files:**
- Modify: `src/harness/land.py`
- Modify: `tests/unit/test_land.py`

- [ ] **Step 1: Write failing tests**

Add focused tests to `tests/unit/test_land.py` using existing temp repo helpers:

```python
def test_land_warns_when_fulfillment_report_has_missing_gap(tmp_path, capsys):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "fulfillment-report.md").write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | MISSING | none | high | absent |\n"
    )

    # Call the new helper directly.
    from harness.land import _fulfillment_warning

    warning = _fulfillment_warning("001", tmp_path, strict=False)

    assert warning is not None
    assert "MISSING" in warning


def test_land_strict_blocks_unverified(tmp_path):
    spec_dir = tmp_path / "specs" / "001-demo"
    spec_dir.mkdir(parents=True)
    (spec_dir / "fulfillment-report.md").write_text(
        "| ID | Status | Evidence | Confidence | Notes |\n"
        "|---|---|---|---|---|\n"
        "| FR-001 | UNVERIFIED | src/a.py | medium | no test |\n"
    )

    from harness.land import _fulfillment_warning

    assert _fulfillment_warning("001", tmp_path, strict=False) is None
    assert _fulfillment_warning("001", tmp_path, strict=True) is not None
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k fulfillment
```

Expected: missing helper.

- [ ] **Step 3: Implement land helper**

In `src/harness/land.py`, import fulfillment helpers and add:

```python
def _fulfillment_warning(spec_id: str, project_dir: Path, strict: bool = False) -> str | None:
    spec_dir = find_spec_dir(project_dir, spec_id)
    if spec_dir is None:
        return None
    report = latest_fulfillment_report(spec_dir)
    if report is None:
        return None
    if not fulfillment_has_blocking_gaps(report, strict=strict):
        return None
    statuses = ", ".join(sorted(blocking_statuses(strict)))
    return (
        f"fulfillment report has unresolved statuses ({statuses}): {report}. "
        f"Run `echelon reopen {spec_id}` or rerun `echelon verify-spec {spec_id}`."
    )
```

Call this from `land_spec` before final merge. In non-strict mode, print warning. In strict mode, return blocked.

- [ ] **Step 4: Run tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/unit/test_land.py -k fulfillment
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/harness/land.py tests/unit/test_land.py
git commit -m "feat: warn on fulfillment gaps before land"
```

---

### Task 8: Docs and Full Focused Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-02-spec-fulfillment-verification-design.md` if implementation details differ.

- [ ] **Step 1: Update README command table**

Add:

```text
echelon verify-spec <spec_id> [strict=true]  Audit implementation against spec
echelon reopen <spec_id>                    Reopen spec from fulfillment gaps
```

- [ ] **Step 2: Run focused verification**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/echelon-uv-test-env uv run --extra dev pytest tests/kernel/test_fulfillment.py tests/kernel/test_prompt_references.py tests/kernel/test_phase_graph.py tests/unit/test_cli_fulfillment_commands.py tests/unit/test_land.py -k "fulfillment or verify_spec or reopen or phase_graph or prompt"
```

Expected: all selected tests pass.

- [ ] **Step 3: Run RE shell regression**

Run:

```bash
bash tests/integration/re/test-run-analysis-polyrepo.sh
```

Expected: pass, fixtures remain free of `.codegraph/`.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: only intended files changed.

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/specs/2026-06-02-spec-fulfillment-verification-design.md
git commit -m "docs: document spec fulfillment verification"
```

---

## Self-Review

Spec coverage:
- Read-only `verify-spec`: Tasks 2, 3, 4.
- Fresh CodeGraph every verification run: Task 3 phase `verify-spec-2-codegraph`.
- Runtime artifacts under `runs/`: Tasks 1 and 3.
- Fulfillment report/gaps schemas: Tasks 3 and 4.
- Explicit mutation through `reopen`: Task 5.
- Harness consumes gaps: Task 6.
- Land warns/blocks: Task 7.
- User documentation: Task 8.

No full brownfield RE is required. CodeGraph refresh is targeted and verification-local.
