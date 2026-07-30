# Phase 1 Quality Before Lexicon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Phase 1 certify the canonical specification before deriving and validating its Lexicon representation, with every amendment restarting spec-quality certification.

**Architecture:** Reorder the existing controller-owned Understanding and Lexicon nodes and add one narrow provider node, `phase1-lexicon-derive`. Bind the WHY2 quality decision to the current Understanding evidence and `spec.md` digest, route all ordinary Lexicon repair through the narrow node, and reuse the existing content-bound Lexicon report plus completion checkpoint machinery.

**Tech Stack:** Python 3.11+, pytest, YAML workflow definitions, Markdown agent/phase contracts, existing Echelon controller state and checkpoint services.

## Global Constraints

- `spec.md` remains the only semantic source of truth.
- `requirements.lexicon.md` is derived only after the current `spec.md` passes deterministic Understanding and SAGE WHY2.
- Spec-quality and Lexicon repair loops have separate nodes, budgets, and ownership.
- Any `spec.md` amendment invalidates both quality and Lexicon certification by content digest.
- A Lexicon-only change invalidates only Lexicon certification.
- No compatibility switch, warning bypass, Phase 3 redesign, or unrelated refactor is included.
- Existing user changes in `src/echelon/cli.py`, `tests/unit/test_cli_continue.py`, and `tests/unit/test_cli_phase.py` must be preserved and folded into the corrected recovery destination.

---

### Task 1: Executable Phase 1 Graph And Narrow Derivation Contract

**Files:**
- Create: `extension/agents/exploration/lexicon-deriver.md`
- Create: `extension/workflow/phases/phase1-lexicon-derive.md`
- Modify: `extension/extension.yml`
- Modify: `extension/workflow/definition.yaml`
- Modify: `tests/kernel/test_phase_graph.py`
- Modify: `tests/kernel/test_workflow_validator.py`

**Interfaces:**
- Consumes: current `spec.md`, `glossary.md`, controller configuration, optional `spec-lexicon-report.json`.
- Produces: `requirements.lexicon.md` only; no validation or routing state.

- [ ] **Step 1: Write failing graph tests**

Assert the exact Phase 1 topology:

```python
assert graph.get("phase1-what").transitions[-1] == {
    "to": "phase1-understanding",
    "condition": "always",
}
assert graph.get("phase1-understanding").transitions == [
    {"to": "phase1-why2", "condition": "always"},
]
assert graph.get("phase1-why2").transitions[-1] == {
    "to": "phase1-lexicon-derive",
    "condition": "verdict = PASS AND no_CRITICAL_issues AND quality_gates.pass",
}
assert graph.get("phase1-lexicon-derive").transitions == [
    {"to": "phase1-lexicon", "condition": "always"},
]
assert graph.get("phase1-lexicon").transitions[-1] == {
    "to": "checkpoint-assess",
    "condition": "always",
}
```

Also assert the derive node is an agent with `outputs ==
["requirements.lexicon.md"]`, an explicitly empty provider state allowlist, and
only `DONE`/`FAIL` verdicts.

- [ ] **Step 2: Run tests and verify the old ordering fails**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py
```

Expected: failures show WHAT still routes to Lexicon, Lexicon routes to
Understanding, and the derive node is absent.

- [ ] **Step 3: Add the narrow agent and phase**

Register `speckit.echelon.lexicon-deriver` in `extension/extension.yml` with
write-capable artifact tools. Its prompt must state:

```text
Read the controller-supplied source, glossary, and failed report.
Write only the configured requirements.lexicon.md.
Never edit spec.md, 00-overview.md, or controller state.
Never declare specification quality, workflow readiness, or a Lexicon verdict.
Return DONE only after requirements.lexicon.md exists in the active spec directory.
```

The phase contract must require:

```yaml
outputs:
  - requirements.lexicon.md
allowed_state_updates: []
allowed_verdicts: [DONE, FAIL]
transitions:
  - to: phase1-lexicon
    condition: always
```

- [ ] **Step 4: Rewire Phase 1**

Change the graph to:

```yaml
phase1-what -> phase1-understanding -> phase1-why2
phase1-why2 PASS -> phase1-lexicon-derive
phase1-lexicon pending/failed -> phase1-lexicon-derive
phase1-lexicon pass/disabled -> checkpoint-assess
```

Keep evidence-resolution and quality-failure routes to `phase1-investigate` or
`phase1-what` before the passing route.

- [ ] **Step 5: Run graph and workflow validation**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_phase_graph.py tests/kernel/test_workflow_validator.py
```

Expected: PASS.

---

### Task 2: Quality Certificate And Content-Bound Guards

**Files:**
- Create: `src/harness/phase1_quality.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/integration/test_squad_controller.py`
- Test: `tests/unit/test_phase1_quality.py`

**Interfaces:**
- Produces:

```python
def build_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> dict[str, object] | None: ...

def has_current_phase1_quality_certificate(
    state: Mapping[str, object],
    *,
    project_root: Path,
) -> bool: ...
```

- [ ] **Step 1: Write failing certificate tests**

Cover:

```python
assert has_current_phase1_quality_certificate(current_state, project_root=root)

(spec_dir / "spec.md").write_text("amended")
assert not has_current_phase1_quality_certificate(current_state, project_root=root)
```

Reject missing evidence, tampered Understanding evidence, a non-passing
Understanding score, a non-passing WHY2 completion, and malformed digests.

- [ ] **Step 2: Run tests and verify the helper is absent**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase1_quality.py
```

Expected: import or assertion failure.

- [ ] **Step 3: Implement the certificate helper**

Build a schema-version-1 record from the current content-bound
`understanding_evidence`, its report digest, and the current `spec.md` digest.
Validation must recompute both file digests and call the existing
`has_current_understanding_evidence(..., phase="phase1-why2")`.

- [ ] **Step 4: Certify only a successful WHY2 transition**

In controller enrichment, when `node.id == "phase1-why2"`:

```python
if verdict_is_pass and explicit_quality_pass(state["quality_scores"]) is True:
    updates["spec_quality_certificate"] = certificate
```

If a passing certificate cannot be built, block instead of advancing to
Lexicon derivation.

- [ ] **Step 5: Add a quality guard**

Before dispatching `phase1-lexicon-derive`, `phase1-lexicon`, or any later
Phase 1/Phase 2 consumer, require a current quality certificate. Missing or stale
certification routes to `phase1-understanding`, clears later completion and
dispatch history, and preserves authored files.

- [ ] **Step 6: Invalidate by ownership boundary**

For a successful `phase1-what` result remove:

```python
{
    "spec_quality_certificate",
    "lexicon_evaluation",
    "lexicon_pass",
    "lexicon_findings",
    "lexicon_report",
    "lexicon_warning_waiver",
}
```

For a successful `phase1-lexicon-derive` result remove only Lexicon
certification fields. The following deterministic gate writes fresh evidence.

- [ ] **Step 7: Run focused controller tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_phase1_quality.py tests/integration/test_squad_controller.py -k 'phase1_quality or lexicon'
```

Expected: PASS.

---

### Task 3: Derivation Prompt, Artifact Boundary, And Repair Loop

**Files:**
- Modify: `src/harness/squad_executors.py`
- Modify: `src/harness/squad.py`
- Modify: `extension/agents/exploration/cartographer.md`
- Modify: `extension/workflow/phases/phase1-what.md`
- Modify: `tests/kernel/test_squad_executors_journal.py`
- Modify: `tests/unit/test_cartographer_templates.py`
- Modify: `tests/contract/static_contracts.py`

**Interfaces:**
- `_render_spec_lexicon_context(...)` targets
  `phase1-lexicon-derive`, not `phase1-what`.
- `_lexicon_repair_no_progress_enrichment(...)` observes
  `phase1-lexicon-derive`, not `phase1-what`.

- [ ] **Step 1: Write failing prompt and output tests**

Assert:

```python
assert "Spec Lexicon Repair" not in what_prompt
assert "requirements.lexicon.md" not in what_node.outputs
assert "Spec Lexicon Repair" in derive_prompt
assert "Do not return a generic Phase1-What completion summary" not in derive_prompt
assert derive_result.output_files == ["specs/001-demo/requirements.lexicon.md"]
```

Also prove the derive phase blocks when its sole required artifact is missing.

- [ ] **Step 2: Run tests and observe failure**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_squad_executors_journal.py tests/unit/test_cartographer_templates.py tests/unit/test_static_contracts_pytest.py
```

Expected: failures show Lexicon authoring and repair still belong to
CARTOGRAPHER/WHAT.

- [ ] **Step 3: Move injected configuration and findings**

Render controller configuration and repair findings only for
`phase1-lexicon-derive`. The injected contract must include the source path,
derived path, glossary path, report path, attempt count, grouped finding
counts, and concrete examples.

- [ ] **Step 4: Enforce the single-output boundary**

Add `phase1-lexicon-derive` to the executor's required-output mapping with only
`requirements.lexicon.md`. Reject claimed output paths outside the configured
derived artifact through the phase result/output contract tests.

- [ ] **Step 5: Move no-progress detection**

Apply artifact SHA comparison after `phase1-lexicon-derive`. An unchanged
artifact produces `lexicon_repair_no_artifact_progress` and terminal block
without consuming another deterministic validation attempt.

- [ ] **Step 6: Remove Lexicon responsibility from WHAT**

Delete Lexicon creation, repair, validation, and routing prose from
`cartographer.md` and `phase1-what.md`. Retain canonical spec and overview
authoring only.

- [ ] **Step 7: Run prompt and executor tests**

Run:

```bash
.venv/bin/pytest -q tests/kernel/test_squad_executors_journal.py tests/unit/test_cartographer_templates.py tests/unit/test_static_contracts_pytest.py
```

Expected: PASS.

---

### Task 4: Recovery, Manual Replay, Rewind, And Operator Documentation

**Files:**
- Modify: `src/echelon/cli.py`
- Modify: `tests/unit/test_cli_continue.py`
- Modify: `tests/unit/test_cli_phase.py`
- Modify: `tests/unit/test_cli_rewind.py`
- Modify: `docs/echelon-workflow-controller-hardening.md`

**Interfaces:**
- Exhausted/no-progress recovery command:

```text
echelon phase run phase1-lexicon-derive
```

- Successful derivation replay next command:

```text
echelon phase run phase1-lexicon
```

- [ ] **Step 1: Change existing recovery tests first**

Update the already modified tests to require
`phase1-lexicon-derive` and explicitly reject both `phase1-what` and blind
`phase1-lexicon` certification.

- [ ] **Step 2: Add manual replay guard tests**

Prove a manual derive replay with stale/missing spec-quality certification is
routed through `phase1-understanding`; a current certificate allows the narrow
derive node.

- [ ] **Step 3: Update CLI phase labels and recovery classification**

Name the narrow phase `Lexicon derivation/repair` and point all
`lexicon_gate_exhausted` and `lexicon_repair_no_artifact_progress` guidance to
it. After a successful manual derive replay, print the deterministic gate as the
next step.

- [ ] **Step 4: Update rewind/reset behavior**

Ensure rewinding to WHAT or any earlier phase clears the quality certificate
and Lexicon evidence. Rewinding to derivation preserves current quality
certification but clears Lexicon evidence and attempts according to the selected
checkpoint epoch.

- [ ] **Step 5: Update the workflow hardening document**

Document the two independent loops and the hash-bound amendment rule. Remove the
old `phase1-lexicon -> phase1-what` repair description.

- [ ] **Step 6: Run CLI and rewind tests**

Run:

```bash
.venv/bin/pytest -q tests/unit/test_cli_continue.py tests/unit/test_cli_phase.py tests/unit/test_cli_rewind.py tests/unit/test_status_roadmap.py
```

Expected: PASS.

---

### Task 5: End-To-End Verification And Release Commit

**Files:**
- Modify only files already listed if verification reveals a defect directly caused by this change.

**Interfaces:**
- Complete initial route:

```text
WHAT -> Understanding -> WHY2 -> Derive -> Lexicon -> checkpoint-assess
```

- Complete amendment route:

```text
WHAT amendment -> Understanding -> WHY2 -> Derive -> Lexicon
```

- [ ] **Step 1: Run the focused Phase 1 matrix**

Run:

```bash
.venv/bin/pytest -q \
  tests/kernel/test_phase_graph.py \
  tests/kernel/test_workflow_validator.py \
  tests/kernel/test_squad_executors_journal.py \
  tests/integration/test_squad_controller.py \
  tests/unit/test_phase1_quality.py \
  tests/unit/test_cli_continue.py \
  tests/unit/test_cli_phase.py \
  tests/unit/test_cli_rewind.py \
  tests/unit/test_cartographer_templates.py \
  tests/unit/test_static_contracts_pytest.py
```

Expected: PASS.

- [ ] **Step 2: Run static verification**

Run:

```bash
python -m py_compile \
  src/harness/phase1_quality.py \
  src/harness/squad.py \
  src/harness/squad_executors.py \
  src/echelon/cli.py
git diff --check
```

Expected: no output and exit status 0.

- [ ] **Step 3: Run the complete repository suite**

Run:

```bash
bash tests/run-all.sh
```

Expected: all test groups pass.

- [ ] **Step 4: Review scope and persisted-state safety**

Confirm:

```bash
git diff --stat
git status --short
rg -n "phase1-lexicon.*phase1-what|phase1-what.*requirements.lexicon" \
  extension src docs/echelon-workflow-controller-hardening.md
```

Expected: remaining matches are historical documentation or explicit
source-defect routes, not executable ordinary repair routing.

- [ ] **Step 5: Commit and push**

```bash
git add <all files changed by this implementation>
git commit -m "fix: certify spec quality before lexicon derivation"
git push origin main
```

Expected: local `HEAD` and `origin/main` resolve to the same commit and the
working tree is clean.
