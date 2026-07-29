# Phase A Add-Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `echelon spec add-input` so a parked `phase1-investigate` run can append declared evidence, unblock investigation, and continue through the normal requirements and gate flow.

**Architecture:** Add a focused product-input attachment module that snapshots new declarations into immutable revision directories and rebuilds aggregate input contract files. Wire it into a controller-owned CLI command under existing Phase A/run locks. Keep investigation prompt changes small: expose added evidence in the Product Input Contract and tell INVESTIGATOR to extend prior artifacts.

**Tech Stack:** Python 3.11+, pytest, existing Echelon CLI, `echelon.product_inputs`, `harness.squad_state`, `harness.squad_executors`, workflow markdown.

## Global Constraints

- Add `echelon spec add-input --input <role:path>` for a parked active run.
- Permit the command only when `status == "blocked"`, `phase == "phase1-investigate"`, `blocked_reason == "investigation_access_required"`, and `evidence_resolution_status == "access_required"`.
- Preserve the original input snapshot unchanged.
- Append immutable evidence revisions with provenance, content metadata, and best-effort linkage to outstanding evidence requests.
- Update controller-owned Product Input Contract pointers so agents can consume added references through the declared manifest and catalog.
- Keep agents from writing `state.json` or product-input declarations directly.
- Successful non-duplicate attachment must unblock to `status: "running"` at `phase1-investigate` and reset only `phase_dispatch_counts["phase1-investigate"]`.
- Do not skip requirement review, deterministic Understanding, SAGE WHY2, Lexicon derivation, or the deterministic Lexicon gate.
- Do not weaken active-run immutability in `echelon spec run --input`.

---

## File Structure

- `src/echelon/product_inputs.py`: extend input resolution with aggregate/attachment helpers; keep low-level snapshot validation here.
- `src/echelon/spec_add_input.py`: create the high-level locked command workflow, eligibility checks, duplicate handling, state updates, and result summary.
- `src/echelon/cli.py`: add `spec add-input` parser/dispatcher and usage text.
- `src/echelon/cli_app.py`: wire Typer front door to `_cmd_spec_add_input`.
- `src/harness/squad_executors.py`: render added evidence in Product Input Contract.
- `extension/workflow/phases/phase1-investigate.md`: instruct incremental investigation from prior artifacts.
- `tests/unit/test_product_inputs.py`: attachment snapshot, aggregate manifest, provenance, and duplicate behavior.
- `tests/unit/test_cli_add_input.py`: command eligibility, state mutation, cap reset, and idempotent behavior.
- `tests/unit/test_cli_typer_app.py`: front-door routing for `spec add-input`.
- `tests/unit/test_product_inputs.py` or a nearby prompt test: Product Input Contract rendering of added references.
- `tests/kernel/test_phase_graph.py`: no graph regression for `phase1-investigate -> phase1-what -> gates`.

---

### Task 1: Product Input Attachment Snapshot And Aggregate

**Files:**
- Modify: `src/echelon/product_inputs.py`
- Test: `tests/unit/test_product_inputs.py`

**Interfaces:**
- Consumes: `ProductInputDeclaration`, `parse_input_declaration`, `resolve_product_input_revision`.
- Produces:
  - `attach_product_input_revision(project_root: Path, inputs_dir: Path, declarations: Sequence[ProductInputDeclaration], *, command: str, evidence_requests: Mapping[str, object] | None = None) -> ProductInputAttachmentResult`
  - `ProductInputAttachmentResult.state_product_inputs(project_root: Path, current_product_inputs: Mapping[str, object]) -> dict[str, object]`
  - `ProductInputAttachmentResult.state_attachments(project_root: Path) -> list[dict[str, object]]`

- [ ] **Step 1: Write failing tests for a successful attachment**

Add to `tests/unit/test_product_inputs.py`:

```python
def test_product_input_attachment_appends_revision_and_rebuilds_aggregate(tmp_path: Path) -> None:
    from echelon.product_inputs import (
        attach_product_input_revision,
        parse_input_declaration,
        resolve_product_inputs,
    )

    project = tmp_path / "workspace"
    base_source = project / "sources" / "base"
    added_source = project / "sources" / "DE-OPTA-SCHEMA-MAPPING"
    base_source.mkdir(parents=True)
    added_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("Initial requirement\n", encoding="utf-8")
    (added_source / "mapping.csv").write_text(
        "filter_id,table_name,column_name\nPBS-E-57,events,player_id\n",
        encoding="utf-8",
    )
    run_dir = project / "runs" / "run-1"
    base = resolve_product_inputs(
        project,
        run_dir,
        [parse_input_declaration("reference:sources/base")],
    )
    original_snapshot = (base.inputs_dir / "snapshots" / "reference" / "reference-001" / "brief.md").read_bytes()

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/DE-OPTA-SCHEMA-MAPPING")],
        command="echelon spec add-input",
        evidence_requests={"requests": [{"id": "ER-001", "question": "Need mapping"}]},
    )

    assert result.added
    assert result.attachment_id == "001"
    assert (base.inputs_dir / "attachments" / "001" / "manifest.json").is_file()
    assert (base.inputs_dir / "snapshots" / "reference" / "reference-001" / "brief.md").read_bytes() == original_snapshot
    aggregate_manifest = json.loads((base.inputs_dir / "manifest.json").read_text(encoding="utf-8"))
    accepted = [item for item in aggregate_manifest["resources"] if item.get("status") == "accepted"]
    assert any(item["source_locator"].endswith("sources/base/brief.md") for item in accepted)
    assert any(item["source_locator"].endswith("sources/DE-OPTA-SCHEMA-MAPPING/mapping.csv") for item in accepted)
    ledger = json.loads((base.inputs_dir / "attachment-ledger.json").read_text(encoding="utf-8"))
    assert ledger["attachments"][0]["id"] == "001"
    assert ledger["attachments"][0]["command"] == "echelon spec add-input"
    assert ledger["attachments"][0]["linked_evidence_request_ids"] == ["ER-001"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_product_inputs.py::test_product_input_attachment_appends_revision_and_rebuilds_aggregate -v`
Expected: FAIL with import error for `attach_product_input_revision`.

- [ ] **Step 3: Implement minimal attachment snapshot and aggregate rebuild**

In `src/echelon/product_inputs.py`:

```python
@dataclass(frozen=True)
class ProductInputAttachmentResult:
    attachment_id: str
    inputs_dir: Path
    revision: ProductInputResolution | None
    added: tuple[dict[str, object], ...]
    duplicates: tuple[dict[str, object], ...]
    ledger_path: Path

    def state_product_inputs(self, project_root: Path, current_product_inputs: Mapping[str, object]) -> dict[str, object]:
        updated = dict(current_product_inputs)
        updated.update({
            "inputs_dir": _portable(self.inputs_dir, project_root),
            "manifest": _portable(self.inputs_dir / "manifest.json", project_root),
            "catalog": _portable(self.inputs_dir / "catalog.json", project_root),
            "input_context": _portable(self.inputs_dir / "input-context.md", project_root),
            "requirement_context": _portable(self.inputs_dir / "requirement-context.md", project_root),
            "reference_context": _portable(self.inputs_dir / "reference-context.md", project_root),
            "traceability": _portable(self.inputs_dir / "traceability.json", project_root),
            "traceability_markdown": _portable(self.inputs_dir / "traceability.md", project_root),
            "manifest_hash": hashlib.sha256((self.inputs_dir / "manifest.json").read_bytes()).hexdigest(),
        })
        return updated
```

Implement `attach_product_input_revision` by:

1. Reading existing `manifest.json`, `catalog.json`, `traceability.json`, and optional `attachment-ledger.json`.
2. Normalizing declarations and detecting full duplicate declarations before creating a revision.
3. Creating the next `attachments/NNN/inputs` directory with `resolve_product_input_revision`.
4. Marking accepted resources whose `sha256` already exists as duplicates in the revision manifest and excluding those units from aggregate catalog/traceability.
5. Rebuilding root `manifest.json`, `catalog.json`, `requirement-context.md`, `reference-context.md`, `input-context.md`, `traceability.json`, and `traceability.md`.
6. Writing `attachment-ledger.json` atomically with one attachment summary.

- [ ] **Step 4: Run successful attachment test**

Run: `uv run pytest tests/unit/test_product_inputs.py::test_product_input_attachment_appends_revision_and_rebuilds_aggregate -v`
Expected: PASS.

- [ ] **Step 5: Write duplicate/idempotency tests**

Add:

```python
def test_product_input_attachment_all_duplicate_source_is_idempotent(tmp_path: Path) -> None:
    from echelon.product_inputs import attach_product_input_revision, parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    source = project / "sources" / "base"
    source.mkdir(parents=True)
    (source / "brief.md").write_text("Same evidence\n", encoding="utf-8")
    base = resolve_product_inputs(project, project / "runs" / "run-1", [parse_input_declaration("reference:sources/base")])
    before = (base.inputs_dir / "manifest.json").read_text(encoding="utf-8")

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/base")],
        command="echelon spec add-input",
    )

    assert not result.added
    assert result.duplicates
    assert not (base.inputs_dir / "attachments" / "001").exists()
    assert (base.inputs_dir / "manifest.json").read_text(encoding="utf-8") == before


def test_product_input_attachment_duplicate_content_is_reported_without_duplicate_catalog_unit(tmp_path: Path) -> None:
    from echelon.product_inputs import attach_product_input_revision, parse_input_declaration, resolve_product_inputs

    project = tmp_path / "workspace"
    first = project / "sources" / "first"
    second = project / "sources" / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "a.md").write_text("Same evidence\n", encoding="utf-8")
    (second / "b.md").write_text("Same evidence\n", encoding="utf-8")
    base = resolve_product_inputs(project, project / "runs" / "run-1", [parse_input_declaration("reference:sources/first")])

    result = attach_product_input_revision(
        project,
        base.inputs_dir,
        [parse_input_declaration("reference:sources/second")],
        command="echelon spec add-input",
    )

    assert not result.added
    assert result.duplicates[0]["reason"] == "duplicate content"
    catalog = json.loads((base.inputs_dir / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["units"]) == 1
```

- [ ] **Step 6: Run duplicate tests and full product-input unit file**

Run: `uv run pytest tests/unit/test_product_inputs.py -k "attachment or product_input_revision or requirement_folder" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/echelon/product_inputs.py tests/unit/test_product_inputs.py
git commit -m "Add product input attachment snapshots"
```

---

### Task 2: Locked `spec add-input` Command Workflow

**Files:**
- Create: `src/echelon/spec_add_input.py`
- Modify: `src/echelon/cli.py`
- Modify: `src/echelon/cli_app.py`
- Test: `tests/unit/test_cli_add_input.py`
- Test: `tests/unit/test_cli_typer_app.py`

**Interfaces:**
- Consumes: `attach_product_input_revision(...)` from Task 1.
- Produces:
  - `add_input_to_active_run(project_root: Path, input_values: Sequence[str], *, command: str = "echelon spec add-input") -> SpecAddInputResult`
  - `_cmd_spec_add_input(args: list[str]) -> None`

- [ ] **Step 1: Write failing eligibility and success tests**

Create `tests/unit/test_cli_add_input.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_current_run(project: Path, state: dict) -> Path:
    run_dir = project / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (project / "runs" / ".current").write_text("run-1\n", encoding="utf-8")
    (run_dir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    return run_dir


def _base_state(run_dir: Path, inputs_dir: Path) -> dict:
    return {
        "run_id": "run-1",
        "status": "blocked",
        "phase": "phase1-investigate",
        "blocked_reason": "investigation_access_required",
        "evidence_resolution_status": "access_required",
        "escalation_question": "Need Data Engineering evidence.",
        "evidence_requests": {"requests": [{"id": "ER-001", "question": "Need mapping"}]},
        "phase_dispatch_counts": {"phase1-investigate": 5, "phase1-what": 2},
        "product_inputs": {
            "inputs_dir": str(inputs_dir),
            "manifest": str(inputs_dir / "manifest.json"),
            "catalog": str(inputs_dir / "catalog.json"),
            "input_context": str(inputs_dir / "input-context.md"),
            "requirement_context": str(inputs_dir / "requirement-context.md"),
            "reference_context": str(inputs_dir / "reference-context.md"),
            "traceability": str(inputs_dir / "traceability.json"),
            "traceability_markdown": str(inputs_dir / "traceability.md"),
            "declarations": [{"role": "reference", "location": "sources/base"}],
            "manifest_hash": "old",
        },
    }


def test_spec_add_input_unblocks_investigation_and_resets_only_investigation_cap(tmp_path: Path) -> None:
    from echelon.product_inputs import parse_input_declaration, resolve_product_inputs
    from echelon.spec_add_input import add_input_to_active_run

    project = tmp_path / "workspace"
    base_source = project / "sources" / "base"
    added_source = project / "sources" / "DE-RESOLVER-BENCHMARK"
    base_source.mkdir(parents=True)
    added_source.mkdir(parents=True)
    (base_source / "brief.md").write_text("base\n", encoding="utf-8")
    (added_source / "benchmarks.csv").write_text("filters,p95\n10,42\n", encoding="utf-8")
    resolution = resolve_product_inputs(project, project / "runs" / "run-1", [parse_input_declaration("reference:sources/base")])
    run_dir = _write_current_run(project, _base_state(project / "runs" / "run-1", resolution.inputs_dir))

    result = add_input_to_active_run(project, ["reference:sources/DE-RESOLVER-BENCHMARK"])

    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    assert result.added_count == 1
    assert state["status"] == "running"
    assert state["phase"] == "phase1-investigate"
    assert state["blocked_reason"] is None
    assert state["escalation_question"] is None
    assert state["escalation_resolver"] == "echelon spec add-input"
    assert state["phase_dispatch_counts"] == {"phase1-what": 2}
    assert state["add_input_recovery"]["previous_phase1_investigate_dispatch_count"] == 5
    assert state["evidence_requests"]["requests"][0]["id"] == "ER-001"
    assert state["product_input_attachments"][0]["id"] == "001"


@pytest.mark.parametrize(
    ("status", "phase", "reason", "evidence_status"),
    [
        ("running", "phase1-investigate", "investigation_access_required", "access_required"),
        ("blocked", "phase1-what", "investigation_access_required", "access_required"),
        ("blocked", "phase1-investigate", "human_clarification_required", "access_required"),
        ("blocked", "phase1-investigate", "investigation_access_required", "pending"),
    ],
)
def test_spec_add_input_rejects_non_eligible_run(tmp_path: Path, status: str, phase: str, reason: str, evidence_status: str) -> None:
    from echelon.spec_add_input import SpecAddInputError, add_input_to_active_run

    project = tmp_path / "workspace"
    inputs_dir = project / "runs" / "run-1" / "inputs"
    inputs_dir.mkdir(parents=True)
    for name in ("manifest.json", "catalog.json", "traceability.json"):
        (inputs_dir / name).write_text("{}\n", encoding="utf-8")
    for name in ("input-context.md", "requirement-context.md", "reference-context.md", "traceability.md"):
        (inputs_dir / name).write_text("", encoding="utf-8")
    state = _base_state(project / "runs" / "run-1", inputs_dir)
    state.update({"status": status, "phase": phase, "blocked_reason": reason, "evidence_resolution_status": evidence_status})
    _write_current_run(project, state)

    with pytest.raises(SpecAddInputError, match="parked investigation access checkpoint"):
        add_input_to_active_run(project, ["reference:sources/new"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_cli_add_input.py -v`
Expected: FAIL with module import error for `echelon.spec_add_input`.

- [ ] **Step 3: Implement `src/echelon/spec_add_input.py`**

Implement:

```python
class SpecAddInputError(RuntimeError):
    pass

@dataclass(frozen=True)
class SpecAddInputResult:
    run_dir: Path
    attachment_id: str
    added_count: int
    duplicate_count: int
    next_command: str = "echelon spec continue"
```

`add_input_to_active_run` must:

1. Parse input declarations.
2. Locate active run using the same current pointer layout as `_find_current_run_dir` without importing CLI internals.
3. Acquire `PhaseAExecutionLock` then `SpecRunExecutionLock`.
4. Load state through `SquadStateStore`.
5. Validate eligibility exactly from Global Constraints.
6. Call `attach_product_input_revision`.
7. If `result.added` is empty, leave state unchanged and return duplicate-only summary.
8. If added, update `product_inputs`, append `product_input_attachments`, set retryable investigation state, preserve `evidence_requests`, remove only `phase_dispatch_counts["phase1-investigate"]`, and save through `SquadStateStore.save`.

- [ ] **Step 4: Wire CLI parser**

In `src/echelon/cli.py`:

1. Add usage line: `spec add-input --input <role:path>...`.
2. Add `_cmd_spec_add_input(args: list[str]) -> None`.
3. Parse repeatable `--input value` and `--input=value`.
4. On missing input print usage and exit 2.
5. On `SpecAddInputError` or `ProductInputError`, print `✗ echelon spec add-input: <error>` and exit 1.
6. On success print a concise banner with run, attachment, added, duplicate, original declarations, attached declarations, and `Next`.
7. Dispatch it in `_cmd_spec`.

In `src/echelon/cli_app.py`, add a Typer wrapper that calls `_cmd_spec_add_input`.

- [ ] **Step 5: Run CLI tests**

Run: `uv run pytest tests/unit/test_cli_add_input.py tests/unit/test_cli_typer_app.py -k "add_input or add-input" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/echelon/spec_add_input.py src/echelon/cli.py src/echelon/cli_app.py tests/unit/test_cli_add_input.py tests/unit/test_cli_typer_app.py
git commit -m "Add spec add-input command"
```

---

### Task 3: Prompt Rendering And Investigation Incrementality

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `extension/workflow/phases/phase1-investigate.md`
- Test: `tests/unit/test_product_inputs.py`
- Test: `tests/unit/test_investigator_templates.py`

**Interfaces:**
- Consumes: `state["product_input_attachments"]` from Task 2.
- Produces: Added Reference Material section in `_render_product_input_context(state)`.

- [ ] **Step 1: Write failing prompt-rendering test**

Add to `tests/unit/test_product_inputs.py`:

```python
def test_product_input_context_renders_added_reference_material() -> None:
    from harness.squad_executors import _render_product_input_context

    prompt = _render_product_input_context({
        "product_inputs": {
            "manifest": "runs/run-1/inputs/manifest.json",
            "catalog": "runs/run-1/inputs/catalog.json",
            "traceability": "runs/run-1/inputs/traceability.json",
            "requirement_context": "runs/run-1/inputs/requirement-context.md",
            "reference_context": "runs/run-1/inputs/reference-context.md",
        },
        "product_input_attachments": [
            {
                "id": "001",
                "declarations": [{"role": "reference", "location": "sources/DE-OPTA-SCHEMA-MAPPING"}],
                "resources": [{"snapshot": "attachments/001/inputs/snapshots/reference/reference-001/mapping.csv"}],
                "linked_evidence_request_ids": ["ER-001"],
            }
        ],
        "evidence_requests": {"requests": [{"id": "ER-001", "question": "Need mapping"}]},
    })

    assert "## Added Reference Material" in prompt
    assert "sources/DE-OPTA-SCHEMA-MAPPING" in prompt
    assert "ER-001" in prompt
    assert "Preserve and extend prior investigation artifacts" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_product_inputs.py::test_product_input_context_renders_added_reference_material -v`
Expected: FAIL because the section is not rendered.

- [ ] **Step 3: Implement prompt rendering**

In `_render_product_input_context`, after the existing Product Input Contract lines, append:

```python
attachments = state.get("product_input_attachments")
if isinstance(attachments, list) and attachments:
    lines.extend(["", "## Added Reference Material"])
    lines.append("- Preserve and extend prior investigation artifacts; do not restart evidence collection from scratch.")
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_id = str(attachment.get("id") or "").strip()
        request_ids = ", ".join(str(item) for item in attachment.get("linked_evidence_request_ids", []) if str(item).strip()) or "outstanding evidence requests"
        lines.append(f"- Attachment {attachment_id}: intended for {request_ids}.")
        for declaration in attachment.get("declarations", []):
            if isinstance(declaration, dict):
                lines.append(f"  - {declaration.get('role')}: {declaration.get('location')}")
        for resource in attachment.get("resources", [])[:10]:
            if isinstance(resource, dict) and resource.get("snapshot"):
                lines.append(f"  - snapshot: {resource['snapshot']}")
```

- [ ] **Step 4: Update investigation phase instructions**

In `extension/workflow/phases/phase1-investigate.md`, add a short subsection after "Missing-Output Recovery":

```markdown
## Added Reference Material Recovery

When the Product Input Contract includes **Added Reference Material**, read the
prior `evidence-inventory.json`, `evidence-resolution.md`,
`evidence-grades.md`, and `investigation/` reports before expanding sources.
Preserve conclusions that are still supported. Expand only the newly declared
material and any directly relevant linked sources needed to resolve outstanding
`ER-*` requests. Do not restart evidence collection from scratch merely because
new references were attached.
```

- [ ] **Step 5: Run prompt/template tests**

Run: `uv run pytest tests/unit/test_product_inputs.py::test_product_input_context_renders_added_reference_material tests/unit/test_investigator_templates.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/harness/squad_executors.py extension/workflow/phases/phase1-investigate.md tests/unit/test_product_inputs.py tests/unit/test_investigator_templates.py
git commit -m "Expose added inputs to investigator"
```

---

### Task 4: Continuation Route And Regression Coverage

**Files:**
- Modify: `tests/unit/test_cli_add_input.py`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/unit/test_product_inputs.py`

**Interfaces:**
- Consumes: `add_input_to_active_run` from Task 2 and prompt rendering from Task 3.
- Produces: Regression proof that `add-input` resumes investigation without bypassing gates or mutating initial run input behavior.

- [ ] **Step 1: Add graph route regression test**

Add to `tests/kernel/test_phase_graph.py`:

```python
def test_phase1_investigate_validated_routes_back_to_requirements_before_gates(self):
    investigate = self.graph.get("phase1-investigate")
    assert investigate.transitions[0] == {
        "to": "phase1-what",
        "condition": "evidence_resolution_status in [validated, conflicting]",
    }
    what = self.graph.get("phase1-what")
    assert any(transition["to"] == "phase1-understanding" for transition in what.transitions)
    why2 = self.graph.get("phase1-why2")
    assert any(transition["to"] == "phase1-lexicon-derive" for transition in why2.transitions)
    lexicon = self.graph.get("phase1-lexicon")
    assert lexicon.type == "deterministic_lexicon"
```

- [ ] **Step 2: Add immutable `spec run --input` regression if not already present**

Add or keep a focused test that calls `_cmd_run` with different `--input` values against an active state and asserts stderr includes:

```text
product inputs are immutable for an active run
```

Use existing monkeypatch patterns from `tests/unit/test_cli_mode_args.py` to avoid dispatching real agents.

- [ ] **Step 3: Run red/green verification**

Run before implementation if the tests are new: `uv run pytest tests/kernel/test_phase_graph.py::TestPhaseGraph::test_phase1_investigate_validated_routes_back_to_requirements_before_gates -v`
Expected before adding/adjusting implementation is PASS if current graph already satisfies this; this is a characterization regression test.

- [ ] **Step 4: Run targeted suite**

Run:

```bash
uv run pytest \
  tests/unit/test_product_inputs.py \
  tests/unit/test_cli_add_input.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_investigator_templates.py \
  tests/kernel/test_phase_graph.py \
  -k "product_input or add_input or add-input or investigator or phase1_investigate" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_cli_add_input.py tests/kernel/test_phase_graph.py tests/unit/test_product_inputs.py
git commit -m "Cover add-input continuation flow"
```

---

### Task 5: Final Verification

**Files:**
- No production edits expected.
- Verify all files changed by Tasks 1-4.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: final evidence that the feature works and does not regress nearby behavior.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest \
  tests/unit/test_product_inputs.py \
  tests/unit/test_cli_add_input.py \
  tests/unit/test_cli_typer_app.py \
  tests/unit/test_investigator_templates.py \
  tests/kernel/test_phase_graph.py -v
```

Expected: PASS.

- [ ] **Step 2: Run broader CLI/product-input checks**

Run:

```bash
uv run pytest \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_resume_escalation_options.py \
  tests/unit/test_cli_mode_args.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/kernel/test_prompt_references.py -v
```

Expected: PASS.

- [ ] **Step 3: Inspect diff for unrelated changes**

Run: `git diff --stat HEAD`
Expected: only add-input/product-input/prompt/test files from this plan plus the plan doc.

- [ ] **Step 4: Final commit if any verification-only edits were needed**

```bash
git status --short
git add <only files changed by this feature>
git commit -m "Verify add-input recovery flow"
```
