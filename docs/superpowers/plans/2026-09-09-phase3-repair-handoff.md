# Phase 3 Repair Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution, or superpowers:subagent-driven-development if the user selects delegated execution. Execute task-by-task with review checkpoints. Steps use checkbox syntax.

**Goal:** Make Phase 3 repairs resolve current issues autonomously within existing authority and independently validate each repair without requiring the whole gate to pass first.

**Architecture:** Extend the existing selection ledger, prepared results and transactional state updates. Add a small pure contract module for typed review/action validation, while retaining controller-owned routing, existing agents and current quality gates. Integrate staged-review persistence before PLAN2 and invalidate evidence when its reviewed inputs change.

**Tech Stack:** Python, pytest, YAML workflow definitions, Prosaic Markdown instructions; existing Codex/Claude-compatible provider abstraction.

**Spec:** `docs/superpowers/specs/2026-09-09-phase3-repair-handoff-design.md`

## Current completion checkpoint — 2026-09-09

- [x] Tasks 1–3: identity-bound independent reviews, durable closure, and mandatory current context.
- [x] Task 4: bounded durable SAGE classification and sealed existing-owner work routing; no new answer-adoption authority.
- [x] Task 5: submission/review accounting, unchanged global limits, explicit prerequisite/authority/no-progress reporting.
- [x] Cross-layer regression: fake-provider ARCHITECT, WHY3, ASSESS2 and PLAN2, real state transactions and deterministic gates, including restart and revalidation of A after B changes dependencies.
- [x] Independent review findings addressed: complete owned-artifact manifest, reused-label history, legacy receiptless closure, all-receipt final freshness, current-finding replay protection, and non-work blockers.
- [x] Broad/full regression completion and scoped commit (70b51de0; paired-rule correction af87d3bd).
- [x] Install, refresh bundles, and observe preserved spec008 through normal CLI continuation.

The corrected broad regression passes: 1,411 tests, including 102 focused repair
cases. The full suite completed with 11,717 passed, 14 skipped and four failures:
two references to the same unpaired SAGE rule and two outdated SENTINEL diagnostic
assertions. The rule and assertions were corrected; all 151 follow-up checks
passed. The SENTINEL assertion updates remain with the earlier uncommitted
SENTINEL work rather than mixed into the Phase3 commits. The entire full suite
was not repeated after that prose/assertion correction.

Installed with `bash scripts/install.sh`, refreshed the demo with
`echelon workspace migrate-to-prosaic`, and verified installed Python source plus
byte-identical deployed SAGE/consensus files. Normal `echelon spec continue`
resumed the same run on 2026-09-09 at 07:22 CEST and stopped at 07:29 CEST.

Live outcome: ISS-003 independently validated, selected issue cleared, two review
receipts retained (the second after PLAN2 regenerated dependencies), and one
completed classification of ISS-001 as `investigate_or_design`, owned by
`phase3-how`. The next work was correctly not dispatched: the preserved budget
was already exhausted at iteration 10/max_iterations 10. Final reason is
`repair_budget_exhausted`. This verifies the handoff and safeguards, not completed
authoring of spec008. The monitor was paused at the terminal outcome. No manual
demo repair, budget reset/increase, or SOAR execution occurred. Required demo
repair context was 155,781 bytes, within the existing bound.

The detailed task checklists below retain the original execution instructions;
this checkpoint records actual completion. Earlier checkpoint is retained as history.

## Earlier inline execution checkpoint — 2026-09-09

Implementation is **not ready for live continuation**. Completed code slices:

- Identity-bound immutable SAGE review validation and role checks (`780b71e8`).
- Repeated-key journal selector correction (`97022e3d`).
- Durable Stage 1 per-issue review receipts, aggregate-PASS closure removal,
  and one persisted final-candidate revalidation per identity/input manifest
  when PLAN2 changes reviewed content (`74d89ad3`).
- Mandatory current owner context and current consensus journal selection
  (`7641be2a`).
- Pure bounded technical-action assessment contract only (`8a0cd532`);
  this validator does **not** yet schedule work or grant decision authority.
- Retain explicit SAGE assessments when its gate verdict is BLOCKED; include
  mandatory review sections in context-budget reports (`32dbf948`).

Verification: 731 controller/human-input regression tests passed before the
last blocked-SAGE/context-report refinement. After that refinement, all 224
focused context, review, state, staged-executor and action-contract tests passed.
The full suite and fake-provider complete A→B repair lifecycle have not run yet.

Still required: Task 4 action provenance, bounded legacy assessment and
controller-owned work routing; Task 5 durable submission/no-progress accounting
and actionable recovery; cross-dispatch stale-receipt validation (not only
in-invocation PLAN2 mutation), malformed legacy-state cases, and Task 6 full
regression/review/live validation. Keep existing caps and permission paths;
do not wire technical work through answer-adoption authority.

No installer, workspace migration, demo artifact edits, or live resume were
performed during this implementation. The CLI uses an editable checkout, so
absence of an installer run does not isolate these Python edits from the CLI.
Earlier unrelated dirty work remains preserved and outside these scoped commits.

## Global Constraints

- No new agents, no SOAR, no demo edits, no quality waivers, no budget increases, no super-banzai, no changes to delivery verification.
- WHY2/proportional decision semantics and semi-mode decision approvals remain unchanged.
- Preserve uncommitted SOAR-disable and SENTINEL work; do not mix unrelated changes into this fix's commits.
- No live resume until the required fixes are installed together.
- Missing, stale or malformed review evidence never closes an issue.
- Every code task follows red test -> minimal implementation -> focused green tests -> scoped diff review -> scoped commit. Do not stage entire overlapping dirty files.

## Preparation and file map

Existing worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/graph-lifecycle-evidence`, branch `fix/disable-soar`. At planning time many files contain previous uncommitted work. Before implementation follow using-git-worktrees guidance, capture `git status --short` and baseline diffs, and preserve existing changes. Do not execute against clean main if doing so omits the fixes this run already exercised. If safe hunk separation is impossible, resolve the commit boundary with the user first.

Primary ownership:

- New `src/harness/phase3_repair.py`: pure identity, action and review-contract validation; no file writes, provider calls or parallel ledger.
- `src/harness/squad.py`: orchestrate selection retirement, current-issue assignment, progress and existing authority routes.
- `src/harness/squad_state.py`: durable review receipts, idempotence and atomic selected-issue changes using existing state transactions.
- `src/harness/prepared_phase_result.py`, `controller_state_contracts.py`, `squad_executors.py`: carry and validate role-specific metadata through existing prepared results; Stage 1 boundary and repair prompts.
- `src/harness/agent_context.py`, `runtime/workflow/definition.yaml`, relevant phase prose: current repair context and journal selectors.
- Existing SAGE/ARCHITECT/SENTINEL/ORCHESTRATOR prose: role boundaries and typed action/review output, no new agents.
- Focused unit/kernel/integration tests below; CLI reporting changes only in existing status/next-step rendering when required by the new reason codes.

## Task 1: Typed issue-review identity and validation

**Files:** Create `src/harness/phase3_repair.py`, `tests/unit/test_phase3_repair.py`; modify `src/harness/prepared_phase_result.py`, `src/harness/controller_state_contracts.py`, `src/harness/squad_executors.py` and their existing kernel tests for validated role metadata.

**Interfaces:** Introduce immutable `RepairIdentity(run_id: str, issue_fingerprint: str, selection_revision: int)`. `validate_issue_review(payload: Mapping[str, object], *, expected: RepairIdentity, expected_manifest: Mapping[str, str]) -> IssueReview` returns immutable `IssueReview(identity, outcome, reviewed_artifacts, rationale)`; outcome is exactly `resolved`, `unresolved`, or `unverifiable`. Invalid input raises `RepairContractError`. `expected_manifest` is harness-generated, not trusted from the agent. Reuse existing issue fingerprint helper rather than adding a competing algorithm.

- [ ] Write a red parametrized validator test with this valid shape, then mutate each identity field, remove an artifact, alter a hash, introduce an unknown path/outcome, and empty the rationale:

```python
identity = RepairIdentity("run-1", "issue-content-hash", 7)
manifest = {"data-model.md": "candidate-content-hash"}
payload = {
    "schema_version": 1,
    "identity": {"run_id": "run-1", "issue_fingerprint": "issue-content-hash", "selection_revision": 7},
    "outcome": "resolved",
    "reviewed_artifacts": manifest,
    "rationale": "The declared enum now includes the transition target.",
}
assert validate_issue_review(payload, expected=identity, expected_manifest=manifest).outcome == "resolved"
```

- [ ] Run `.venv/bin/pytest -q tests/unit/test_phase3_repair.py`; confirm a real missing-interface/validation failure.
- [ ] Implement the pure types/validator. Reject duplicate/conflicting selected assessments during enclosing result validation. Resolve manifest paths through the existing containment rules before calling the pure validator.
- [ ] Extend prepared SAGE WHY3 result metadata only; reject another agent claiming review authority. A provider must not write review receipts directly into `state_updates`. Missing metadata on a legacy response means unvalidated, not accepted.
- [ ] Run the new tests and the existing prepared-result/controller-contract kernel tests discovered by `rg --files tests/kernel`. Confirm old payloads retain their old verdict behavior.
- [ ] Review and commit only Task 1 changes: `feat: validate identity-bound phase3 issue reviews`.

## Task 2: Durable per-issue closure at the Stage 1 boundary

**Files:** Modify `src/harness/squad.py` (`_coordinate_selected_issue_repair_updates`), `src/harness/squad_state.py`, `src/harness/squad_executors.py` (`StagedParallelExecutor`); add `tests/kernel/test_phase3_repair_state.py`, extend `tests/kernel/test_squad_executors_journal.py` and `tests/integration/test_squad_controller.py`.

**Interfaces:** Consume Task 1 `IssueReview`. Add an idempotent state-store operation `commit_phase3_issue_review(*, snapshot, review_dispatch_id: str, review: IssueReview, input_manifest: Mapping[str, str]) -> bool`, following existing attested transaction conventions. It records the receipt and selection/history changes together; false means stale snapshot, never successful closure. Reuse the existing ledger and preserve the immutable issue instance when display IDs are reused.

- [ ] Build a kernel fixture with selected A in `repaired`, overall WHY3 FAIL, and unresolved B. Assert the following state transition using a fresh valid review:

```python
assert store.commit_phase3_issue_review(
    snapshot=snapshot, review_dispatch_id="why3-review-1",
    review=review, input_manifest=manifest,
)
state = store.load()
assert state["issue_resolution_ledger"]["ISS-A"]["status"] == "validated"
assert state["selected_issue_resolution"] is None
assert state["why3_verdict"] == "FAIL"
```

- [ ] Add red cases for omitted assessment, issue-label reuse, duplicate dispatch, crash after commit, stale CAS and changed manifest. Add staged integration: SAGE closes A; PLAN2 returns BLOCKED; reload state and assert closure survived.
- [ ] Run `.venv/bin/pytest -q tests/kernel/test_phase3_repair_state.py tests/kernel/test_squad_executors_journal.py` and the new named integration tests; inspect the failures before implementation.
- [ ] Persist the prepared SAGE assessment after Stage 1 and before PLAN2. Remove aggregate PASS as the prerequisite for identity-bound individual closure. Keep aggregate verdicts unchanged. Do not treat a worker COMPLETE as validation.
- [ ] Before relying on a receipt at subsequent routing/dispatch, compare the relevant current manifest. Mutated reviewed dependencies require revalidation; dispatch the reviewer, not the stale worker instruction. Preserve the existing receipt as history.
- [ ] Run kernel/integration cases plus existing selected-issue Phase 1 tests. Confirm a missing legacy receipt requires fresh review rather than global state migration or auto-closure.
- [ ] Scoped review/commit: `fix: retire independently validated phase3 repairs`.

## Task 3: Current repair context and journal selector correctness

**Files:** Modify `src/harness/agent_context.py`, `src/harness/squad_executors.py`, `runtime/workflow/definition.yaml`, `runtime/workflow/phases/phase3-how.md`; extend `tests/unit/test_agent_context.py`, `tests/kernel/test_squad_executors_journal.py`.

**Interfaces:** Extend same-key selector values as an immutable ordered tuple when repeated; retain scalar values for existing single selectors. Matching is OR within a repeated key, AND across keys. `_render_issue_resolution_context` consumes the current immutable issue instance and phase; the harness assembles mandatory current issue/affected artifact/evidence content through existing bounded renderers.

- [ ] Add red selector and prompt tests:

```python
selector = parse_context_pack_item("journal.jsonl [phase=phase2-decide, phase=phase3-consensus, type=challenge]")
assert selector.filters["phase"] == ("phase2-decide", "phase3-consensus")
assert selector.filters["type"] == "challenge"
# Rendered repair prompt must include the current geometry checklist, not
# the retired enum decision. Initial HOW must retain its creation contract.
```

- [ ] Include wildcard/single-value compatibility, scalar consumers, run-local versus published-spec paths, required-context overflow, missing inputs, and validated/repaired/selected instruction behavior. Test both legacy and bounded render modes.
- [ ] Run `.venv/bin/pytest -q tests/unit/test_agent_context.py tests/kernel/test_squad_executors_journal.py` to establish red tests.
- [ ] Implement explicit mandatory repair sections and role-appropriate submission/review context. Current issues and their referenced checklists cannot depend on optional journal selection. If the budget cannot fit required context, surface `repair_context_incomplete` with missing paths.
- [ ] Correct selector matching and add current consensus challenge history on repairs. Audit all `filters` consumers with `rg` so tuple support does not break old selectors.
- [ ] Verify full prompt fixtures and existing context bounds. Scoped review/commit: `fix: deliver current evidence to phase3 repair owners`.

## Task 4: Typed technical work assignment, not implicit decision permission

**Files:** Extend `src/harness/phase3_repair.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`, prepared contracts; modify `prosaic/subagents/echelon.sage.md`, `echelon.architect.md`, `echelon.sentinel.md`, `echelon.orchestrator.md`, `runtime/workflow/phases/phase3-consensus.md`; extend `tests/unit/test_phase3_repair.py`, `tests/integration/test_squad_controller.py`, `tests/integration/test_human_input_routing.py`.

**Interfaces:** `validate_repair_action(payload: Mapping[str, object], *, expected: RepairIdentity, allowed_owner_phases: frozenset[str], allowed_artifacts: frozenset[str]) -> RepairAction`. Immutable `RepairAction` fields: identity, kind, owner_phase, affected_artifacts, evidence_refs, action, constraints. Kinds exactly `apply_evidenced_resolution`, `investigate_or_design`, `human_decision`, `external_prerequisite`. Pure validation is not authority: controller checks existing scope/policy before dispatch. Existing eligible-option matching remains unchanged.

- [ ] Write red tests for an agent-owned geometry investigation versus an unsupported answer. Reuse the Task 1 identity fixture; instantiate the action with explicit read sources, owned artifacts and requirement-preservation constraints:

```python
payload = {
    "schema_version": 1, "identity": identity_payload,
    "kind": "investigate_or_design", "owner_phase": "phase3-how",
    "affected_artifacts": ["contracts/internal-interfaces.md"],
    "evidence_refs": ["spec.md#NFR-001"],
    "action": "Inspect declared scene fixtures and specify a reproducible observation protocol.",
    "constraints": ["Preserve NFR-001; distinguish measured facts from proposed mechanisms."],
}
action = validate_repair_action(payload, expected=identity,
    allowed_owner_phases=frozenset({"phase3-how"}),
    allowed_artifacts=frozenset({"contracts/internal-interfaces.md"}))
assert action.kind == "investigate_or_design"
```

- [ ] Add controller tests that malicious/out-of-root paths, unsupported owner, invented external fact, scope expansion, policy waiver and human-decision payloads cannot become automatic adoption. Assert semi and WHY2 behavior unchanged. Do not use a domain-word blacklist to pass tests; assert preservation of the existing authority boundary and routing contracts.
- [ ] Add restart tests for one legacy reclassification per stable identity/input manifest, not per process or rewritten issue label. Identical malformed output must terminate with a specific reason, not dispatch SAGE indefinitely.
- [ ] Run the focused tests red. Implement typed assessment plumbing and existing-owner dispatch; preserve mandatory independent review. Give legacy contradictory guidance a bounded existing-SAGE assessment request. Unknown classifications fail closed with actionable evidence.
- [ ] Update role prose: derive evidence or propose technical mechanisms without claiming unsupported facts; cross-owner artifact amendments require handoff; acceptance weakening requires existing authority. Do not broaden `Banzai eligible: yes`.
- [ ] Run focused and existing human-input tests green. Scoped review/commit: `fix: distinguish autonomous repair work from decision approval`.

## Task 5: Repair progress receipts, bounded failure and accurate status

**Files:** Modify `src/harness/squad.py`, `src/harness/squad_state.py`, `src/harness/squad_executors.py`, `src/harness/recovery_instruction.py`, relevant renderers in `src/echelon/cli.py`; extend `tests/unit/test_cli_next_step_escalation.py`, `tests/unit/test_cli_continue.py`, `tests/kernel/test_phase3_repair_state.py`, `tests/integration/test_squad_controller.py`.

**Interfaces:** Persist attempt count and consecutive reviewed-unresolved submissions per immutable issue cycle, using existing telemetry/evidence stores. Add reason codes `repair_no_progress`, `repair_context_incomplete`, and `repair_action_unclassified` to existing recovery/report validation. These reasons never imply accepted debt or automatic budget reset.

- [ ] Write red scenario tests: COMPLETE without relevant edits consumes an attempt; two reviewed-unresolved submissions stop; a restart preserves the count; unrelated file changes and issue renumbering do not reset it; cancellation or an existing stricter cap wins first.

```python
# Integration assertions after two submitted/reviewed attempts:
state = store.load()
assert state["blocked_reason"] == "repair_no_progress"
assert state["why3_verdict"] == "FAIL"
assert state["selected_issue_resolution"] is not None
```

- [ ] Add final-PLAN2 BLOCKED fixtures preserving producer, owner, current issue, attempted action and missing prerequisite in rendered status. Assert it does not advise unconditional continue or present human-free work as an unanswered question.
- [ ] Run focused tests red. Implement persisted progress decisions from explicit reviews and content-bound evidence, not mere mtime or whole-run scores. Retain existing global counters and limits.
- [ ] Run CLI/contract/state tests green; inspect output for actionable next steps and absence of secrets/source dumps. Scoped review/commit: `fix: report ineffective phase3 repairs with durable evidence`.

## Task 6: Cross-layer regression and preserved-workspace validation

**Files:** Add `tests/integration/test_phase3_repair_handoff.py`; update `CHANGELOG.md` and the approved design's validation notes with actual outcomes. No demo artifacts are edited manually.

- [ ] Write a deterministic end-to-end fake-provider scenario reproducing the observed sequence: A repaired; B open; aggregate FAIL; PLAN2 BLOCKED; A closure durable; B assigned to existing owner; owner submits; independent SAGE validates; final gate advances only after all required findings pass. Assert the second worker prompt names B, not A. Add restart and downstream-artifact-regeneration variants.
- [ ] Run it red before final integration adjustments, then green. No test may bypass prepared-result validation or fabricate a global PASS to make the scenario converge.
- [ ] Run the broad relevant suites:

```bash
.venv/bin/pytest -q tests/unit/test_agent_context.py tests/unit/test_phase3_repair.py tests/unit/test_phase_a_readiness.py tests/unit/test_coverage_contract.py tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py tests/kernel/test_squad_state.py tests/kernel/test_phase3_repair_state.py tests/kernel/test_squad_executors_journal.py tests/integration/test_squad_controller.py tests/integration/test_phase3_repair_handoff.py tests/integration/test_human_input_routing.py
.venv/bin/pytest -q
git diff --check
```

- [ ] Compare full-suite failures with the pre-change baseline, keep SOAR disabled, and diagnose newly introduced failures before installation. Do not rewrite unrelated tests to hide failures. Request independent implementation review using requesting-code-review skill.
- [ ] Confirm clean scoped commits and the approved deployment source. With authorization to execute the live test, install and refresh bundles before continuing the same run:

```bash
# In the implementation checkout:
bash scripts/install.sh
# In /Users/michalbachorik/work/browser-3d-game-stack-smoke:
echelon workspace migrate-to-prosaic
echelon spec status
echelon spec continue
```

- [ ] Before the final command confirm spec008 is still active, blocked, has no running execution, and the installed Python/prose/runtime correspond to this implementation. If another run is active, stop and ask; never resume a different run. Use normal CLI migration/continuation, not direct state edits, reset, or manually written geometry answers.
- [ ] Observe via the existing five-minute heartbeat when authorized. Verify current issue context, per-issue closure, no stale selection, preserved budgets and independent acceptance. Stop monitoring on terminal outcome. If blocked, report the precise prerequisite and whether it is genuinely external or a remaining harness defect.
- [ ] Record actual test counts, source revision, run identity and terminal outcome. Success is convergence or a precise legitimate prerequisite, not just another started dispatch. Commit scoped tests/docs; do not claim merge, install or live completion without evidence.

## Self-review / design coverage

Identity, fresh evidence and staged durability: Tasks 1–2. Context and selector semantics: Task 3. Technical work versus authority and legacy compatibility: Task 4. Progress, limits and CLI guidance: Task 5. Cross-layer and live acceptance: Task 6. All new contract signatures used by later tasks are defined above; remaining integration changes deliberately reuse existing prepared-result and transaction APIs rather than introducing parallel persistence.
