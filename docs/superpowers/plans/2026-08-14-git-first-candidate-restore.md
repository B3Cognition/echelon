# Git-First Candidate Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace file-first candidate restoration with immutable Git-commit authority, prevalidate candidate manifests before side effects, and require authoritative SAGE PASS for ordinary certification while retaining executable qualitative-debt decisions.

**Architecture:** Selection produces pinned manifest and checkpoint-tree snapshots. After state authority, Echelon constructs a verified target commit with an isolated index, materializes owned paths through a deterministic run-local journal, and advances ref/index to the prebuilt commit before recording its receipt. Certification derives from one numeric/provider/SAGE assessment.

**Tech Stack:** Python 3.11+, Git plumbing (`read-tree`, `update-index --cacheinfo`, `write-tree`, `commit-tree`, `update-ref`), POSIX descriptor/no-follow primitives, pytest.

**Spec:** `docs/superpowers/specs/2026-08-14-git-first-candidate-restore-design.md`

## Global Constraints

- Initial candidate plus at most three consumed automatic repairs; the initial assessment is not a repair.
- One optional repair may be authorized and consumed exactly once.
- Operational failures and unchanged normative WHAT results consume no automatic repair.
- Restore only `spec.md`, `requirements-overview.md`, `quality-gates.md`, and `issues.md`; never mutate unrelated paths.
- Preserve exact selected-checkpoint regular-blob mode (`100644` or `100755`) and blob ID.
- No restore path may call `git add -A` or build a checkpoint from mutable worktree bytes.
- Ordinary certification requires deterministic Understanding PASS, provider PASS, and authoritative SAGE PASS.
- Qualitative-only debt has `failed_gates: []` plus nonempty authoritative issues; it creates no numeric failure or passing certificate.
- Preserve schema-v1 outbox compatibility, perfectionist routing, thresholds, sealed choices, one terminal banner, and provider/debt truth.
- Leave deferred Tasks Lexicon recovery-command and false-publication summary defects unchanged.

---

### Task 1: Preflight Candidate and Checkpoint Authority

**Files:**
- Modify: `src/harness/proportional_quality.py`
- Modify: `src/harness/proportional_quality_effects.py`
- Modify: `src/harness/squad.py`
- Modify: `tests/unit/test_proportional_quality.py`
- Modify: `tests/integration/test_squad_controller.py`

**Interfaces:**
- Produces: `CandidateCheckpointEntry(path, mode, blob_oid, sha256, content)`.
- Produces: `load_candidate_checkpoint_entries(project_root: Path, spec_dir: Path, candidate: QualityCandidateManifest) -> tuple[CandidateCheckpointEntry, ...]`.
- Produces: `PreflightedCandidateRestore(snapshot, entries)` for Tasks 2–3.

- [ ] **Step 1: Write RED manifest-slot and pre-mutation tests**

```python
def test_candidate_slot_rejects_another_candidate_id(tmp_path):
    path = tmp_path / "quality-candidate-1.json"
    path.write_bytes(candidate_manifest_bytes(candidate_id="quality-candidate-0"))
    with pytest.raises(QualityCandidateIntegrityError, match="identity mismatch"):
        load_quality_candidate_snapshot(path, expected_candidate_id="quality-candidate-1")


def test_combined_restore_authenticates_selected_manifest_before_any_effect(controller):
    before = controller.capture_git_run_and_spec_state()
    controller.replace_selected_manifest_before_effect()
    with pytest.raises(QualityCandidateIntegrityError):
        controller.reconcile_pending_quality_completion()
    assert controller.capture_git_run_and_spec_state() == before
```

- [ ] **Step 2: Run RED tests**

```bash
.venv/bin/pytest tests/unit/test_proportional_quality.py -k candidate_slot_rejects tests/integration/test_squad_controller.py -k authenticates_selected_manifest_before_any_effect -q
```

Expected: candidate-list loading omits the expected ID, and combined restore creates candidate Git/run artifacts before rejecting the selected replacement.

- [ ] **Step 3: Add immutable checkpoint-entry and preflight types**

```python
@dataclass(frozen=True)
class CandidateCheckpointEntry:
    path: str
    mode: str
    blob_oid: str
    sha256: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class PreflightedCandidateRestore:
    snapshot: QualityCandidateSnapshot
    entries: tuple[CandidateCheckpointEntry, ...]
```

`load_candidate_checkpoint_entries()` uses `git ls-tree` and `git cat-file blob`. Require one entry per manifest-owned artifact, mode in `{"100644", "100755"}`, blob type, and SHA-256 equal to the manifest digest.

- [ ] **Step 4: Bind candidate-list paths to exact IDs**

```python
snapshots = tuple(
    load_quality_candidate_snapshot(
        candidate_dir / f"{candidate_id}.json",
        expected_candidate_id=candidate_id,
    )
    for candidate_id in repair["candidate_ids"]
)
```

Ranking, history, recommendation, selected evidence, and selected SHA must use only these snapshots.

- [ ] **Step 5: Preflight selected authority before materializing the current candidate**

```python
selected_restore = preflight_quality_candidate_restore(
    project_root=root,
    spec_dir=spec_dir,
    manifest_path=candidate_dir / f"{restore_id}.json",
    expected_candidate_id=restore_id,
    expected_manifest_sha256=restore_manifest_sha,
)
materialized, candidate_receipt = materialize_quality_candidate(
    project_root=root,
    spec_dir=spec_dir,
    candidate=draft,
    run_id=run_id,
    spec_id=spec_id,
    completion_id=_quality_completion_id(completion_id, "candidate"),
    next_phase=next_phase,
    checkpoint_prestate=effective_prestate,
    require_current_artifacts=False,
    expected_receipt=candidate_expected,
)
```

Pass `selected_restore` forward; do not reload its manifest or selected checkpoint after current-candidate materialization.

- [ ] **Step 6: Run GREEN compatibility tests**

```bash
.venv/bin/pytest tests/unit/test_proportional_quality.py tests/integration/test_squad_controller.py -k 'candidate or manifest or selected or proportional_quality' -q
```

Expected: swapped/replaced manifests fail before Git, candidate-manifest, or spec mutation.

- [ ] **Step 7: Commit Task 1**

```bash
git add src/harness/proportional_quality.py src/harness/proportional_quality_effects.py src/harness/squad.py tests/unit/test_proportional_quality.py tests/integration/test_squad_controller.py
git commit -m "fix: preflight proportional candidate authority"
```

---

### Task 2: Build and Verify an Immutable Target Restore Commit

**Files:**
- Create: `src/harness/git_first_restore.py`
- Create: `tests/unit/test_git_first_restore.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_phase_checkpoints.py`

**Interfaces:**
- Consumes: `CandidateCheckpointEntry` from Task 1.
- Produces: `GitFirstRestorePlan`.
- Produces: `build_git_first_restore_commit(project_root: Path, journal_root: Path, completion_id: str, base_commit: str, selected_candidate_id: str, selected_manifest_sha256: str, selected_entries: tuple[CandidateCheckpointEntry, ...], run_id: str, spec_id: str, next_phase: str) -> GitFirstRestorePlan`.
- Produces: `verify_git_first_restore_commit(project_root: Path, plan: GitFirstRestorePlan) -> None`.
- Produces: `build_phase_checkpoint_message(spec_id: str, phase: str, run_id: str) -> str`.

- [ ] **Step 1: Write RED tree/mode tests**

```python
def test_restore_commit_preserves_selected_modes_and_unowned_tree(repo):
    plan = build_git_first_restore_commit(
        project_root=repo.root,
        journal_root=repo.run_root,
        completion_id="quality-restore-1",
        base_commit=repo.base_commit,
        selected_candidate_id="quality-candidate-0",
        selected_manifest_sha256="a" * 64,
        selected_entries=repo.selected_entries(spec_mode="100755"),
        run_id="spec-run",
        spec_id="001-example",
        next_phase="checkpoint-assess",
    )
    assert repo.tree_entry(plan.target_commit, "specs/001-example/spec.md").mode == "100755"
    assert repo.tree_entry(plan.target_commit, "README.md") == repo.tree_entry(repo.base_commit, "README.md")
    assert repo.head() == repo.base_commit
    assert repo.spec_bytes() == repo.current_bytes
```

Add negatives for symlink/tree entries, missing/extra owned artifacts, wrong digest, dirty/staged base, and changed base HEAD.

- [ ] **Step 2: Run RED unit suite**

```bash
.venv/bin/pytest tests/unit/test_git_first_restore.py -q
```

Expected: collection fails because `harness.git_first_restore` is absent.

- [ ] **Step 3: Implement serializable plan types**

```python
@dataclass(frozen=True)
class RestoreCommitEntry:
    path: str
    base_mode: str
    base_blob_oid: str
    base_sha256: str
    target_mode: str
    target_blob_oid: str
    target_sha256: str


@dataclass(frozen=True)
class GitFirstRestorePlan:
    schema_version: int
    completion_id: str
    ref_name: str
    base_commit: str
    base_tree: str
    target_commit: str
    target_tree: str
    selected_candidate_id: str
    selected_manifest_sha256: str
    entries: tuple[RestoreCommitEntry, ...]
```

Add a module-local Git helper accepting binary stdin and explicit environment for `GIT_INDEX_FILE`, author, committer, and dates; retain the 120-second timeout and bounded errors.

- [ ] **Step 4: Export one checkpoint-message builder**

```python
def build_phase_checkpoint_message(*, spec_id: str, phase: str, run_id: str) -> str:
    return build_echelon_commit_message(
        f"echelon-checkpoint: {spec_id} {phase}",
        EchelonCommitMetadata(
            origin="phase-a", action="checkpoint", spec_id=spec_id,
            run_id=run_id, phase=phase, checkpoint_id=phase,
        ),
    )
```

Make ordinary `create_phase_checkpoint()` call it.

- [ ] **Step 5: Build the target with an isolated index**

```python
with isolated_index(journal_root, completion_id) as index_path:
    git(env={"GIT_INDEX_FILE": str(index_path)}, args=("read-tree", base_commit))
    for entry in selected_entries:
        git(env={"GIT_INDEX_FILE": str(index_path)}, args=(
            "update-index", "--add", "--cacheinfo", entry.mode, entry.blob_oid, entry.path,
        ))
    target_tree = git(env={"GIT_INDEX_FILE": str(index_path)}, args=("write-tree",)).stdout.strip()
    target_commit = commit_tree_deterministically(
        target_tree=target_tree,
        parent=base_commit,
        message=checkpoint_message,
        identity="Echelon <echelon@local>",
        timestamp=base_commit_timestamp,
    )
```

Explicit identity/date makes retry return the same commit even if user Git config changes.

- [ ] **Step 6: Verify the complete target tree**

`verify_git_first_restore_commit()` requires the expected parent/message trailers, exact owned `(mode, blob_oid)` entries, and zero unowned tree differences from `base_commit`. It reads no worktree bytes.

- [ ] **Step 7: Run GREEN unit and checkpoint suites**

```bash
.venv/bin/pytest tests/unit/test_git_first_restore.py tests/unit/test_phase_checkpoints.py -q
```

Expected: exact modes/blobs/unowned tree pass; ordinary checkpoint behavior is unchanged.

- [ ] **Step 8: Commit Task 2**

```bash
git add src/harness/git_first_restore.py src/harness/phase_checkpoints.py tests/unit/test_git_first_restore.py tests/unit/test_phase_checkpoints.py
git commit -m "feat: build immutable candidate restore commits"
```

---

### Task 3: Recover Worktree, Ref, Index, and Outbox Receipt

**Files:**
- Modify: `src/harness/git_first_restore.py`
- Modify: `src/harness/proportional_quality.py`
- Modify: `src/harness/proportional_quality_effects.py`
- Modify: `src/harness/phase_checkpoints.py`
- Modify: `tests/unit/test_git_first_restore.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_squad_completion.py`
- Modify: `tests/unit/test_squad_phase_checkpoints.py`

**Interfaces:**
- Consumes: `GitFirstRestorePlan` from Task 2.
- Produces: `apply_or_recover_git_first_restore(project_root: Path, spec_dir: Path, journal_root: Path, plan: GitFirstRestorePlan, run_id: str, spec_id: str, next_phase: str, expected_receipt: object | None = None) -> GitFirstRestoreReceipt`.
- Produces: `record_prebuilt_completion_checkpoint(project_root: Path, spec_dir: Path, phase: str, next_phase: str, run_id: str, spec_id: str, completion_id: str, expected_parent: str, commit: str, expected_entries: tuple[RestoreCommitEntry, ...], expected_receipt: object | None = None) -> dict[str, object]`.
- Replaces current-schema file-first `materialize_quality_candidate_restore()`.

- [ ] **Step 1: Write RED crash-state matrix**

```python
@pytest.mark.parametrize("crash_point", (
    "after_journal", "after_first_exchange", "after_all_exchanges",
    "after_ref_update", "after_index_update", "before_receipt",
))
def test_public_retry_converges_git_first_restore_once(controller, crash_point):
    controller.inject_restore_crash(crash_point)
    controller.run_until_pending_completion()
    controller.resume()
    assert controller.restore_checkpoint_count() == 1
    assert controller.restore_receipt_count() == 1
    assert controller.head_index_and_worktree_match_target()
    assert controller.restore_journal_entries() == ()
```

Add regular→symlink, same-digest inode swap, mode-only drift, unrelated owned drift, unexplained temp, ref conflict, and unrelated repository-path preservation.

- [ ] **Step 2: Run RED crash/adversarial tests**

```bash
.venv/bin/pytest tests/unit/test_git_first_restore.py tests/integration/test_squad_controller.py -k 'git_first_restore or restore_crash or restore_symlink or restore_mode' -q
```

Expected: file-first flow cannot create the target authority or recover ref/index crash states.

- [ ] **Step 3: Implement canonical journal types**

```python
@dataclass(frozen=True)
class GitFirstRestoreJournal:
    schema_version: int
    completion_id: str
    plan_sha256: str
    ref_name: str
    base_commit: str
    target_commit: str
    entries: tuple[JournalEntry, ...]


@dataclass(frozen=True)
class JournalEntry:
    path: str
    base_mode: str
    base_sha256: str
    target_mode: str
    target_sha256: str
    temporary_name: str


@dataclass(frozen=True)
class GitFirstRestoreReceipt:
    schema_version: int
    completion_id: str
    restore_protocol: str
    plan_sha256: str
    target_commit: str
    checkpoint: Mapping[str, object]
```

Persist canonical JSON with `O_EXCL`, file fsync, directory fsync, and exact-byte idempotence. Deterministic temporaries live under the run artifact root and must share the destination filesystem.

- [ ] **Step 4: Materialize exact target blobs/modes with no-follow exchange**

Write each target blob to its deterministic journal temporary with selected mode. Read destination and temporary through pinned no-follow descriptors. Exchange only an exact sealed base entry with an exact target temporary. Verify the displaced base entry, fsync both directories, and remove it outside checkpoint pathspecs. Unknown type/content/mode/identity fails closed.

- [ ] **Step 5: Advance ref and active index recoverably**

```python
if current_ref == plan.base_commit:
    git("update-ref", plan.ref_name, plan.target_commit, plan.base_commit)
elif current_ref != plan.target_commit:
    raise GitFirstRestoreError("restore ref authority changed")

index_tree = git("write-tree").stdout.strip()
if index_tree == plan.base_tree:
    git("read-tree", plan.target_commit)
elif index_tree != plan.target_tree:
    raise GitFirstRestoreError("restore index authority changed")
```

Reverify ref, index tree, target commit, owned worktree mode/blob entries, and journal absence before receipt construction.

- [ ] **Step 6: Record the prebuilt checkpoint without staging**

```python
checkpoint = record_prebuilt_completion_checkpoint(
    project_root=project_root,
    spec_dir=spec_dir,
    phase="phase1-quality-candidate-restored",
    next_phase=next_phase,
    run_id=run_id,
    spec_id=spec_id,
    completion_id=completion_id,
    expected_parent=plan.base_commit,
    commit=plan.target_commit,
    expected_entries=plan.entries,
    expected_receipt=checkpoint_expected,
)
```

Verify parent/message/tree, ref, index, and worktree, then idempotently record the ledger. Do not call `_commit_spec_changes()`.

- [ ] **Step 7: Integrate current and legacy effect paths**

Combined restore consumes Task 1 preflight, uses current candidate checkpoint as base, and writes receipt fields `restore_protocol: "git_first_v1"`, `target_commit`, and plan digest. Standalone restore uses sealed checkpoint prestate as base. Exact pending legacy file-first effects retain their handler only if original schema/digest and residue are safely classifiable; otherwise fail closed with explicit legacy-recovery guidance.

- [ ] **Step 8: Run GREEN recovery regressions**

```bash
.venv/bin/pytest tests/unit/test_git_first_restore.py tests/unit/test_squad_completion.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_squad_controller.py -k 'restore or candidate or completion or checkpoint' -q
```

Expected: every crash converges to one target commit/receipt; drift fails without unrelated mutation; legacy outbox tests stay green.

- [ ] **Step 9: Commit Task 3**

```bash
git add src/harness/git_first_restore.py src/harness/proportional_quality.py src/harness/proportional_quality_effects.py src/harness/phase_checkpoints.py tests/unit/test_git_first_restore.py tests/unit/test_squad_completion.py tests/unit/test_squad_phase_checkpoints.py tests/integration/test_squad_controller.py
git commit -m "fix: recover candidate restore from immutable git authority"
```

---

### Task 4: Require Authoritative SAGE Certification

**Files:**
- Modify: `src/harness/squad.py`
- Modify: `src/harness/phase1_quality.py`
- Modify: `src/harness/phase1_quality_debt.py`
- Modify: `tests/integration/test_squad_controller.py`
- Modify: `tests/unit/test_phase1_quality.py`
- Modify: `tests/unit/test_phase1_quality_debt.py`
- Modify: `tests/integration/test_human_input_routing.py`

**Interfaces:**
- Produces: `AuthoritativeQualityAssessment`.
- Produces: `_authoritative_proportional_assessment(prepared, eval_state, spec_dir) -> AuthoritativeQualityAssessment`.
- Produces: `_coordinate_proportional_failure(assessment, prepared, snapshot, eval_state) -> tuple[str | None, dict[str, object], PreparedHumanInput | None]`.
- Produces: schema-v2 passing certificates bound to `issues.md` path, SHA-256, and authoritative `PASS`; legacy schema-v1 certificates retain their existing compatibility path.
- Consumed by candidate capture, certificate creation, debt eligibility, guided resolution, and COMMANDER resolution.

- [ ] **Step 1: Write RED certification tests**

```python
def test_numeric_and_provider_pass_cannot_certify_sage_fail(controller):
    controller.write_understanding(pass_=True)
    controller.write_provider_result(verdict="PASS", routes=[])
    controller.write_issues(verdict="FAIL", issues=[low_issue("SAGE-001")])
    result = controller.run_why2()
    assert result.route != "phase1-lexicon-derive"
    assert "spec_quality_certificate" not in result.state


def test_critical_issue_blocks_when_other_verdicts_pass(controller):
    controller.write_understanding(pass_=True)
    controller.write_provider_result(verdict="PASS", routes=[])
    controller.write_issues(verdict="FAIL", issues=[critical_issue("SAGE-001")])
    assert controller.run_why2().blocked_reason == "proportional_quality_candidate_integrity_failed"
```

Add provider/SAGE mismatch, missing/duplicate/empty/non-`spec_repair` routes, guided qualitative debt, banzai qualitative debt, and restart currentness tests.

- [ ] **Step 2: Run RED certification slice**

```bash
.venv/bin/pytest tests/integration/test_squad_controller.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py -k 'sage_fail or qualitative_only or certification_integrity' -q
```

Expected: numeric/provider PASS currently creates passing checkpoints despite authoritative SAGE FAIL.

- [ ] **Step 3: Add one combined assessment type**

```python
@dataclass(frozen=True)
class AuthoritativeQualityAssessment:
    numeric_pass: bool
    provider_verdict: str
    sage_verdict: str
    authoritative_issues: tuple[Mapping[str, object], ...]
    exact_routes: tuple[Mapping[str, object], ...]
    ordinary_pass: bool
    proportional_failure: bool
    hard_blockers: tuple[str, ...]
```

Construct it once from deterministic report, provider envelope, and pinned issues snapshot.

- [ ] **Step 4: Bind new passing certificates to authoritative SAGE evidence**

For new proportional passes, `build_phase1_quality_certificate()` emits schema version 2 and adds:

```python
{
    "sage_evidence": project_relative_issues_path,
    "sage_evidence_sha256": sha256_of_exact_issues_bytes,
    "sage_verdict": "PASS",
}
```

`has_current_phase1_quality_certificate()` reopens the exact path safely, requires the stored digest and authoritative PASS verdict, and compares the complete rebuilt v2 record. Existing completed schema-v1 certificates keep the pre-change compatibility validator; any amendment or newly completed WHY2 writes v2.

- [ ] **Step 5: Route proportional certificates through the combined assessment**

```python
assessment = self._authoritative_proportional_assessment(prepared, eval_state, spec_dir)
if assessment.ordinary_pass:
    certificate = build_phase1_quality_certificate(
        state_copy,
        project_root=self._project_root,
        authoritative_sage_assessment=assessment,
    )
    if certificate is None:
        return PHASE_TERMINAL_BLOCKED, {
            "status": "blocked",
            "blocked_reason": "spec_quality_certificate_unavailable",
        }, None
    updates["spec_quality_certificate"] = certificate
elif assessment.hard_blockers:
    return PHASE_TERMINAL_BLOCKED, {
        "status": "blocked",
        "blocked_reason": "proportional_quality_candidate_integrity_failed",
    }, None
else:
    return self._coordinate_proportional_failure(
        assessment=assessment,
        prepared=prepared,
        snapshot=snapshot,
        eval_state=eval_state,
    )
```

For proportional WHY2, suppress the earlier numeric/provider-only certificate block in `_controller_enrichment`; the transition coordinator is the sole certificate writer. Perfectionist keeps the existing block. Provider/SAGE mismatch is integrity failure. Remove the fallback that certifies while authoritative SAGE FAIL eligibility reasons are present.

- [ ] **Step 6: Keep qualitative debt executable**

Require one unique `spec_repair` route per authoritative issue and no extras. Allow debt only if numeric gates or qualitative issues are nonempty:

```python
if not failed_gates and not qualitative_debt:
    raise QualityDebtIntegrityError("quality debt has no residual failure")
```

Retain `failed_gates: []` for qualitative-only debt and verify exact issues/routes/digests through build, currentness, publication, status, and summary.

- [ ] **Step 7: Run GREEN certification/perfectionist regressions**

```bash
.venv/bin/pytest tests/integration/test_squad_controller.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py tests/kernel/test_phase_graph.py -k 'proportional or quality or sage or perfectionist' -q
```

Expected: authoritative SAGE FAIL never certifies; eligible qualitative debt works for user and COMMANDER; blockers/perfectionist remain unchanged.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/harness/squad.py src/harness/phase1_quality.py src/harness/phase1_quality_debt.py tests/integration/test_squad_controller.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py
git commit -m "fix: require authoritative sage certification"
```

---

### Task 5: Full Recovery Verification and Evidence

**Files:**
- Modify: `.superpowers/sdd/2026-08-13-proportional-spec-repair-loop/progress.md`
- Create: `.superpowers/sdd/2026-08-14-git-first-candidate-restore/final-report.md`
- Modify only after a new failing test: files listed in Tasks 1–4.

**Interfaces:**
- Consumes completed Tasks 1–4.
- Produces final evidence and merge-review package.

- [ ] **Step 1: Run focused recovery matrix**

```bash
.venv/bin/pytest tests/unit/test_git_first_restore.py tests/unit/test_proportional_quality.py tests/unit/test_phase_checkpoints.py tests/unit/test_squad_completion.py tests/unit/test_squad_phase_checkpoints.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py -q
```

Expected: zero failures across crash/race/ref/index/certification states.

- [ ] **Step 2: Run expanded feature suite**

```bash
.venv/bin/pytest tests/unit/test_requirement_projection.py tests/unit/test_understanding_service.py tests/unit/test_requirements_metrics.py tests/unit/test_semantic_metrics.py tests/unit/test_proportional_quality.py tests/unit/test_phase1_quality.py tests/unit/test_phase1_quality_debt.py tests/unit/test_phase_checkpoints.py tests/integration/test_human_input_routing.py tests/integration/test_squad_controller.py tests/unit/test_squad_phase_checkpoints.py tests/unit/test_squad_publication.py tests/unit/test_run_summary.py tests/unit/test_cli_status.py tests/unit/test_cli_continue.py tests/kernel/test_squad_state.py tests/kernel/test_phase_graph.py tests/unit/test_squad_completion.py tests/unit/test_state_transaction_namespace.py -q
```

Expected: zero feature failures.

- [ ] **Step 3: Run repository/deployment verification**

```bash
bash tests/run-all.sh
.venv/bin/pytest tests/unit/test_prosaic_package_install.py tests/unit/test_workspace_init_deploy_runtime.py tests/kernel/test_phase_graph.py -q
bash scripts/bash/dry-run.sh
.venv/bin/pytest -q --tb=short
```

Expected: run-all, deployment, and nine bundle checks pass; full pytest has only the same three capability-policy failures reproduced at base `057b0a7d`.

- [ ] **Step 4: Run hygiene**

```bash
.venv/bin/python -m compileall -q src/harness tests/unit tests/integration
git diff --check
git status --short
```

Expected: compile/diff exit zero; status contains only report/ledger updates before commit.

- [ ] **Step 5: Record exact evidence**

The report records command totals, crash points, target ref/index/tree verification, guided/banzai qualitative debt, full-pytest failure identities, and unchanged deferred Tasks Lexicon defects.

- [ ] **Step 6: Commit evidence**

```bash
git add -f .superpowers/sdd/2026-08-13-proportional-spec-repair-loop/progress.md .superpowers/sdd/2026-08-14-git-first-candidate-restore/final-report.md
git commit -m "test: verify git-first candidate recovery"
```

- [ ] **Step 7: Request final whole-branch review**

Generate the review package from `057b0a7d408c11ca63640c8a52b04bea80677af4` to `HEAD`. Require explicit verdicts for target commit/tree/modes, crash recovery around ref/index transitions, manifest preflight before mutation, SAGE PASS certification, qualitative debt, legacy outbox, and perfectionist behavior.
