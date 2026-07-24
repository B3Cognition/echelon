# Documentation Evidence Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make delivery documentation evidence include committed post-task changes and require a complete, independently verified mapping from delivered functionality to README and CHANGELOG coverage.

**Architecture:** Ralph will compute a cumulative, commit-aware delivery path set from the delivery baseline to `HEAD`, union it with dirty-worktree paths, and pass that evidence to the existing documentation gate. Version-2 impact and verification reports will carry a change coverage map; Python will validate structural completeness and evidence paths while TECH WRITER and DOCS VERIFIER retain semantic judgment.

**Tech Stack:** Python 3.11, Git subprocess integration, PyYAML, pytest, Markdown workflow/agent contracts.

## Global Constraints

- Preserve external spec-artifact mode and containment boundaries.
- Do not use the most recent task checkpoint as the documentation baseline.
- Keep fulfillment scoping on its existing narrow per-turn change list.
- New required-documentation deliveries must use schema version 2.
- Schema-version-1 reports remain readable for historical recovery but do not satisfy the new required-documentation coverage gate.
- Do not modify unrelated dirty files already present in the checkout.

---

### Task 1: Commit-aware delivery provenance

**Files:**
- Modify: `src/harness/ralph.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: existing `_git_merge_base()`, `_git_changed_files_between()`, `_changed_files_since_head()`, and `target_default_branch`.
- Produces: `RalphController._documentation_delivery_changes(worktree_path: Path) -> Optional[List[str]]`, used only by the documentation gate.

- [ ] **Step 1: Write the failing committed-docs regression test**

Add a test that initializes `main`, creates a feature branch, commits implementation work, commits valid `README.md` and `CHANGELOG.md` updates, leaves the worktree clean, invokes `_apply_documentation_gate()`, and asserts that the gate receives both documentation paths. Stub only the semantic gate result so this test isolates provenance collection.

```python
def test_documentation_gate_includes_docs_committed_after_task_progress(
    self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, *_ = _make_controller(tmp_path)
    worktree = tmp_path / "worktree"
    _init_git_repo(worktree)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=worktree, check=True)
    (worktree / "src").mkdir()
    (worktree / "src" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(worktree, "implement feature")
    (worktree / "README.md").write_text("# Feature\n", encoding="utf-8")
    (worktree / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    _commit_all(worktree, "document feature")
    seen: dict[str, object] = {}

    def fake_gate(worktree_path: Path, spec_dir: Path, *, changed_files=None):
        seen["changed_files"] = changed_files
        return DocumentationGateResult(passed=True)

    monkeypatch.setattr("harness.ralph.evaluate_documentation_gate", fake_gate)
    result = controller._apply_documentation_gate(VerifyResult(passed=True), str(worktree))

    assert result.passed
    assert {"README.md", "CHANGELOG.md"} <= set(seen["changed_files"])
```

- [ ] **Step 2: Run the regression test and verify RED**

Run: `pytest tests/unit/test_ralph_outer.py::TestRalphController::test_documentation_gate_includes_docs_committed_after_task_progress -q`

Expected: FAIL because `_apply_documentation_gate()` forwards only dirty-worktree paths or `None`, omitting committed docs.

- [ ] **Step 3: Implement cumulative provenance**

Add `_documentation_delivery_changes()` using the merge base with `upstream/<default>`, `origin/<default>`, or the local default branch, falling back to the repository root commit. Union committed paths from `base..HEAD` with `_changed_files_since_head()`, normalize and sort them, and return `None` only when no baseline can be resolved. In `_apply_documentation_gate()`, use this cumulative list for documentation validation while leaving caller-supplied `changed_files` untouched for other gates.

```python
def _documentation_delivery_changes(self, worktree_path: Path) -> Optional[List[str]]:
    committed = self._cumulative_target_delivery_changes(worktree_path)
    if committed is None:
        return None
    dirty = self._changed_files_since_head(str(worktree_path))
    return sorted(set(committed) | set(dirty))
```

- [ ] **Step 4: Add dirty-path and baseline-isolation tests**

Cover staged, unstaged, and untracked docs, plus a feature branch where README changed before the branch point and must not count as delivery evidence.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `pytest tests/unit/test_ralph_outer.py -q -k 'documentation_gate or documentation_delivery'`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/harness/ralph.py tests/unit/test_ralph_outer.py
git commit -m "fix: include committed docs in delivery evidence"
```

---

### Task 2: Versioned documentation coverage contract

**Files:**
- Modify: `src/harness/documentation_gate.py`
- Test: `tests/unit/test_documentation_gate.py`

**Interfaces:**
- Consumes: impact-report YAML frontmatter, documentation-verification YAML frontmatter, and cumulative `changed_files`.
- Produces: deterministic failures `documentation-coverage-incomplete`, `documentation-evidence-invalid`, and `documentation-claim-unsupported`.

- [ ] **Step 1: Write failing schema-version-2 coverage tests**

Add fixtures with `schema_version: 2`, `delivery_change_ids`, and `documented_changes`. Test that required docs fail when a delivery change lacks a disposition, an evidence path does not exist, or the verifier reports unsupported claims. Assert exact failure IDs and missing change IDs in messages.

```python
def test_gate_rejects_uncovered_delivery_change(tmp_path: Path) -> None:
    # Arrange valid docs and reports where FR-004 is in delivery_change_ids
    # but only FR-003 appears in documented_changes.
    result = evaluate_documentation_gate(
        tmp_path,
        spec_dir,
        changed_files=["README.md", "CHANGELOG.md"],
    )
    assert result.failure is not None
    assert result.failure.id == "documentation-coverage-incomplete"
    assert "FR-004" in result.failure.error
```

- [ ] **Step 2: Run new tests and verify RED**

Run: `pytest tests/unit/test_documentation_gate.py -q -k 'coverage or evidence_invalid or claim_unsupported'`

Expected: FAIL because version-2 coverage fields are not validated.

- [ ] **Step 3: Implement report validation helpers**

Add focused helpers that:

- require `schema_version == 2` when `docs_required: true`;
- parse unique non-empty `delivery_change_ids`;
- validate one disposition for every change ID;
- accept only `covered` or `not_applicable` dispositions;
- require non-empty reasons for `not_applicable`;
- require covered entries to cite README and CHANGELOG sections;
- resolve evidence paths beneath the worktree and require them to exist;
- reject duplicates and unknown extra change IDs;
- validate verifier `reviewed_change_ids`, `uncovered_change_ids`, and `unsupported_claims` against the impact report.

Keep path normalization containment-safe using `Path.resolve()` and `is_relative_to(worktree.resolve())`.

- [ ] **Step 4: Add complete and not-applicable passing cases**

Add one complete covered map and one internal-only delivery with justified `not_applicable` entries. Ensure required docs still demand both README and CHANGELOG changes.

- [ ] **Step 5: Preserve historical schema-version-1 readability**

Add a test showing a schema-version-1 `docs_required: false` report remains valid, and a required-docs version-1 report fails with `documentation-impact-report-invalid` and an upgrade message.

- [ ] **Step 6: Run documentation gate tests and verify GREEN**

Run: `pytest tests/unit/test_documentation_gate.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 2**

```bash
git add src/harness/documentation_gate.py tests/unit/test_documentation_gate.py
git commit -m "feat: enforce documentation coverage evidence"
```

---

### Task 3: Deterministic verifier and agent contracts

**Files:**
- Modify: `src/harness/docs_verifier.py`
- Modify: `extension/agents/build/tech-writer.md`
- Modify: `extension/agents/build/docs-verifier.md`
- Modify: `extension/workflow/phases/build-8-documentation.md`
- Modify: `extension/workflow/phases/build-8-verify-docs.md`
- Test: `tests/unit/test_docs_verifier.py`
- Test: `tests/unit/test_tech_writer_contract.py`

**Interfaces:**
- Consumes: version-2 impact report and existing repository evidence.
- Produces: version-2 `docs-verification-report.md` with `reviewed_change_ids`, `uncovered_change_ids`, and `unsupported_claims`.

- [ ] **Step 1: Write failing verifier-output tests**

Require `verify_docs()` to preserve the delivery inventory, report uncovered IDs, count invalid evidence citations as blocking findings, and serialize the new frontmatter fields.

```python
assert metadata["schema_version"] == 2
assert metadata["reviewed_change_ids"] == ["FR-003", "FR-004"]
assert metadata["uncovered_change_ids"] == ["FR-004"]
assert metadata["unsupported_claims"] == []
assert result.blocking_findings == 1
```

- [ ] **Step 2: Run verifier tests and verify RED**

Run: `pytest tests/unit/test_docs_verifier.py tests/unit/test_tech_writer_contract.py -q`

Expected: FAIL because reports and prompts do not contain the version-2 contract.

- [ ] **Step 3: Extend deterministic verifier output**

Parse the impact coverage map, generate structured findings for missing coverage and bad citations, and include the reviewed/uncovered/unsupported fields in report frontmatter. Keep existing first-run README, changelog-format, and planned-work checks unchanged.

- [ ] **Step 4: Strengthen TECH WRITER protocol**

Replace the version-1 examples with the approved version-2 schema. Require a disposition for every harness-supplied `delivery_change_id`, evidence paths, audience impact, README sections, CHANGELOG sections, and a reason for `not_applicable`. Add paired ALWAYS/NEVER rules forbidding silent inventory omission.

- [ ] **Step 5: Strengthen DOCS VERIFIER protocol**

Require independent inspection of every change ID; comparison against source, public API/CLI/config surfaces, tests, and runtime evidence; and structured unsupported-claim and uncovered-change output. Require precise repair findings instead of prose-only approval.

- [ ] **Step 6: Update phase prompts**

Explicitly pass the Ralph-owned delivery inventory from the context pack and require the version-2 outputs. Keep context assembly owned by Ralph.

- [ ] **Step 7: Run verifier and contract tests and verify GREEN**

Run: `pytest tests/unit/test_docs_verifier.py tests/unit/test_tech_writer_contract.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/harness/docs_verifier.py extension/agents/build/tech-writer.md extension/agents/build/docs-verifier.md extension/workflow/phases/build-8-documentation.md extension/workflow/phases/build-8-verify-docs.md tests/unit/test_docs_verifier.py tests/unit/test_tech_writer_contract.py
git commit -m "feat: verify documentation coverage and claims"
```

---

### Task 4: Blocked-run recovery evidence

**Files:**
- Modify: `src/harness/ralph.py`
- Modify: `src/harness/recovery.py`
- Test: `tests/unit/test_harness_recovery.py`
- Test: `tests/unit/test_ralph_outer.py`

**Interfaces:**
- Consumes: delivery baseline, current `HEAD`, checkpoint state, and salvage branch metadata.
- Produces: persisted `documentation_evidence` state and a reachable recovery head before worktree cleanup.

- [ ] **Step 1: Write a failing blocked-run preservation test**

Simulate a documentation-gate escalation after a docs-only commit and assert state retains:

```python
assert state["documentation_evidence"]["baseline"] == base_sha
assert state["documentation_evidence"]["head"] == docs_sha
assert state["documentation_evidence"]["changed_files"] == ["CHANGELOG.md", "README.md"]
assert state["salvage_branch"]
```

- [ ] **Step 2: Run recovery test and verify RED**

Run: `pytest tests/unit/test_harness_recovery.py tests/unit/test_ralph_outer.py -q -k 'documentation_evidence or docs_only_commit'`

Expected: FAIL because documentation head/provenance is not persisted before cleanup.

- [ ] **Step 3: Persist evidence at verification and escalation**

Record baseline, head, changed paths, and timestamp whenever the documentation gate runs. On blocking finalization, ensure the current head is referenced by the existing salvage mechanism before worktree deletion. Do not create a second recovery implementation if `_salvage_build_worktree()` can preserve the ref.

- [ ] **Step 4: Teach recovery to prefer the saved documentation head**

When it exists and is reachable, resume from `documentation_evidence.head`; otherwise use the existing latest checkpoint fallback and leave the documentation failure active so the bounded docs phase recreates the changes.

- [ ] **Step 5: Add reachable and missing-head recovery tests**

Verify both direct resume from a saved docs head and graceful fallback when that object is unavailable.

- [ ] **Step 6: Run recovery tests and verify GREEN**

Run: `pytest tests/unit/test_harness_recovery.py tests/unit/test_ralph_outer.py -q -k 'recovery or documentation'`

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add src/harness/ralph.py src/harness/recovery.py tests/unit/test_harness_recovery.py tests/unit/test_ralph_outer.py
git commit -m "fix: preserve documentation evidence across blocked runs"
```

---

### Task 5: Integrated verification and recovery handoff

**Files:**
- Modify if required by test evidence: `docs/soar-delivery.md`
- Test: focused and full harness unit suites.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: verified harness behavior and operator recovery instructions.

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
pytest \
  tests/unit/test_documentation_gate.py \
  tests/unit/test_docs_verifier.py \
  tests/unit/test_tech_writer_contract.py \
  tests/unit/test_harness_recovery.py \
  tests/unit/test_ralph_outer.py -q
```

Expected: PASS.

- [ ] **Step 2: Run all unit tests**

Run: `pytest -m unit -q`

Expected: PASS. Investigate any failure before claiming completion; do not overwrite unrelated user changes.

- [ ] **Step 3: Run extension wiring validation**

Run: `bash scripts/bash/dry-run.sh`

Expected: PASS with no missing workflow or agent references.

- [ ] **Step 4: Document recovery behavior if existing operator docs omit it**

If `docs/soar-delivery.md` lacks blocked documentation recovery, add the exact `echelon delivery resume` flow and explain that the harness restores the saved delivery head or reruns only the documentation phase when the head is unavailable.

- [ ] **Step 5: Inspect the final diff**

Run: `git diff --check` and `git status --short`.

Expected: no whitespace errors; only task-owned paths are staged or committed by this work.

- [ ] **Step 6: Commit any operator documentation update**

```bash
git add docs/soar-delivery.md
git commit -m "docs: explain blocked delivery recovery"
```

- [ ] **Step 7: Reinstall the local CLI only after tests pass**

Run: `bash scripts/install.sh`

Expected: successful installation into `~/.echelon/venv`. This updates the executable used to recover `/Users/michalbachorik/work/md_distribution`; it does not resume that delivery automatically.
