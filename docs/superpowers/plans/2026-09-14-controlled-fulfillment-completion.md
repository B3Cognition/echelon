# Controlled Fulfillment Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for the user's selected inline execution. Steps use checkbox (`- [x]`) syntax for tracking. Implement sequentially; use scoped independent read-only reviews at phase exits.

**Goal:** Finish the approved controlled fulfillment path through full/scoped execution, recovery, and Ralph integration before live testing.

**Architecture:** Keep admission and refresh policy in `FulfillmentRunner`; add fulfillment-specific semantic and recovery helpers, reusing deterministic preparation, judgment, report, scoped merge and lifecycle functions. Prosaic supplies two semantic-only roles. Both providers use the accepted no-tools inspection operation and host reader.

**Tech Stack:** Python, pytest, Prosaic artifacts, real Git/temp files, scripted external provider and graph processes.

**Spec:** `docs/superpowers/specs/2026-09-13-controlled-fulfillment-ownership-design.md`, including the accepted `2026-09-14-host-serviced-inspection-design.md` amendment.

## Global Constraints

- User requested completion of all remaining implementation phases before live tests; preserve inline execution and separate tested commits.
- Python owns invocation-specific sequencing, exact IDs, writes, publication, completion and accounting. No additional COMMANDER role.
- All role loading goes through `ProsaicPromptLoader`; no native agent-file lookup, provider branches in prose, or AGENTS.md/CLAUDE.md edits.
- Keep generic verify-spec and shared mapper/spec-guard roles intact for legacy/direct CLI callers.
- No active delivery cutover before full, scoped and recovery acceptance. Select only the existing `llm.features.delivery_gate_controller` opt-in; no new public flag/default.
- Preserve banzai/semi/guided policy, observer authority, owner deferrals, exact legacy/six-digit/seven-digit IDs, canonical formats and topology degradation.
- No model tools, direct source working directory, helper execution, tests or delegation. Provider API transport remains permitted by existing adapters.
- No generic execution fallback or automatic semantic repair. Invalid/unknown output blocks and returns to existing Ralph policy.
- Persist semantic intent before dispatch and completion after validation. Never reset an existing run to recover unknown completion.
- Keep previous canonical outputs until validation; persist exact publication intent and refuse conflicting external edits.
- Account failed calls and explicit unknown usage. Enforce remaining budget before dispatch; completed receipt reuse costs zero new tokens.
- Do not install, invoke live models, push, merge, change legacy build, or activate deferred identity work.

Worktree: `/Users/michalbachorik/work/echelon_r/echelon/.worktrees/delivery-controller-contract`, branch `fix/delivery-controller-contract`, baseline `3b104143`.
Python: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python`. Existing environment and linked worktree are retained; no installation needed.

## Task 1 — Neutral semantic contracts and literal artifact rendering

**Files:** Create `src/harness/fulfillment_semantics.py`, `tests/unit/test_fulfillment_semantics.py`, `prosaic/subagents/echelon.fulfillment-mapper.md`, `prosaic/subagents/echelon.fulfillment-judge.md`. Register neutral role IDs in `runtime/workflow/definition.yaml` without changing legacy routing.

**Interfaces:** `FulfillmentAssignment(run_id: str, step: str, dispatch_id: str, input_fingerprint: str, assigned_ids: tuple[str, ...])`, with `identity() -> dict`. `validate_semantic_result(value: object, assignment: FulfillmentAssignment) -> dict`; `render_implementation_map(rows: list[dict]) -> str`; `render_fallback_report(rows: list[dict]) -> str`.

- [x] Write RED tests for exact assignment binding, strict JSON objects, duplicate keys/IDs, omitted/extra IDs, schema version/type, step, invalid enums, booleans, newlines/table separators/control characters, invented TASK-PROGRESS and extra execution fields. Test rendered rows with real `_implementation_rows` and `_fallback_report_rows` consumers.

```python
assignment = FulfillmentAssignment('run', 'judge', 'dispatch', 'a' * 64, ('FR-001', 'FR-1000000'))
value = {**assignment.identity(), 'action': 'final', 'rows': [
    {'id': 'FR-001', 'status': 'MISSING', 'evidence': 'src/app.py has no handler'},
    {'id': 'FR-1000000', 'status': 'UNVERIFIED', 'evidence': 'No measured runtime artifact'}],
    'unmapped_candidates': []}
assert validate_semantic_result(value, assignment)['rows'][1]['id'] == 'FR-1000000'
```

- [x] Run `python -m pytest tests/unit/test_fulfillment_semantics.py -xq`; confirm missing boundary RED.
- [x] Implement versioned assignment validation, closed result schemas, explicit blocked/read/final envelopes and literal safe cell rendering. Mapper rows use the existing ten columns; judge statuses exclude model-owned DEFERRED_SCOPE. Host-owned deterministic leads/semantics remain separate from new verified citations.
- [x] Author the two neutral roles with paired ALWAYS/NEVER rules. Transfer existing evidence, threshold, deferred/observer and bounded-inspection semantics. Request JSON replies, not file writes or phase dispatch. Include no invocation-specific delivery branch.
- [x] Run new tests plus `test_judgment_prepass.py`, `test_prosaic_prompt_loader.py`; commit `feat: define neutral fulfillment semantic contracts`.

## Task 2 — Host-serviced semantic sequence and staged full result

**Files:** Create `src/harness/controlled_fulfillment.py`, `tests/unit/test_controlled_fulfillment.py`; extend semantic helpers if required by real consumers. Reuse `fulfillment_preparation.py` without duplicating its writers.

**Interfaces:** `ControlledFulfillment(executor, project_dir: Path)`; `run(context: FulfillmentPreparationContext, *, forbidden_paths: tuple[Path, ...] = (), token_budget: float | None = None) -> ControlledFulfillmentResult`. Result includes `exit_code`, `reason`, `report_path`, `gaps_path`, `token_usage: int | None`, and dispatch evidence. Outputs stay in the explicit selected run; no canonical publication in this task.

- [x] Write RED consuming tests using `preparation_context` and `scripted_graph_tools` from the preparation tests. Script only external Prosaic/provider execution. Assert actual prepass/report row sets, exact IDs and unchanged source/spec outputs.

```python
result = ControlledFulfillment(executor, context.workspace_root).run(context)
assert result.exit_code == 0
assert result.report_path.parent == context.verify_run_dir
assert not (context.spec_dir / 'fulfillment-report.md').exists()
```

- [x] Run the new tests RED; implement preparation → mapper → mechanical prepass → optional judge → existing assembler. Bind prompt/role/evidence fingerprints and exact assigned IDs; use new private cwd for each no-tools turn. Permit only host-named worktree/spec/evidence roots and supplied exclusions. Use bounded structured reads, maximum 32 reads per semantic role, 300-second total role deadline, existing provider caps, and explicit failure at exhaustion.
- [x] Preserve graph candidates and their evidence semantics in host materialization; require direct-read citations for claimed verified evidence. Keep active deferred IDs out of model authority. No fallback IDs means no judge dispatch. Use existing `summarize_task_progress` for host-owned TASK-PROGRESS eligibility, retaining task/case context in gaps.
- [x] Test malformed/tool/provider/timeout/overflow/denied-read failure, absent roles, unsupported providers, input mutation, strict observation, graph degradation, finite/unknown budget and unsuccessful usage. All invalid paths retain prior canonical outputs.
- [x] Run new tests with preparation, judgment, inspection and triage regressions; obtain scoped independent read-only review; commit `feat: stage Python-owned fulfillment results`.

## Task 3 — Durable semantic recovery and exact publication

**Files:** Create `src/harness/fulfillment_recovery.py`, `tests/unit/test_fulfillment_recovery.py`; modify `controlled_fulfillment.py` and its tests.

**Interfaces:** A fulfillment-local recovery record in the selected run owns binding, preparation digest, per-turn intent/result/usage and pending publication. Use existing `write_json_atomic` with the trusted workspace/run. Controller result adds cumulative `token_usage`, no reset on resumed calls. `publish_fulfillment_outputs(run_dir: Path, spec_dir: Path, outputs: dict[str, str]) -> None` admits exactly report/gaps names and replays exact pending bytes only.

- [ ] Write RED tests for interrupted dispatch, validated receipt replay, changed role/profile/source/spec/evidence/scope, corrupt receipt and legacy in-flight state. Restart must neither reset state nor redispatch known/unknown completion.

```python
first = controller.run(context)
second = controller.run(context)
assert second.token_usage == first.token_usage
assert executor.dispatch_count == first.dispatch_count
```

- [ ] Persist run/step/dispatch identity, input fingerprints, admitted read transcript and token usage before moving to the next step. Refuse unknown completion and changed inputs. Preserve preparation outputs after their accepted digest rather than invoking the initializer or rerunning graphs on recovery.
- [ ] Persist publication originals, exact intended bytes/hashes and state before the first canonical write. Accept each destination only at its original or pending hash; conflict blocks. Finish report and gaps before lifecycle/ledger acceptance. Test interruption before/after each write and pending-record corruption with real files.
- [ ] Test zero-budget, unknown usage under finite budget, tightened budget on resume, and failed-call usage retention. Confirm recovery does not replenish read/turn/time allowances.
- [ ] Run recovery plus Task 2 and durable JSON/lifecycle regressions; review and commit `feat: recover controlled fulfillment without redispatch`.

## Task 4 — Full/scoped runner integration with cache separation

**Files:** Modify `src/harness/fulfillment_runner.py`, `controlled_fulfillment.py`, `fulfillment_recovery.py`; create `tests/unit/test_controlled_fulfillment_runner.py`.

**Interfaces:** `FulfillmentRunner(prompt_executor, *, controlled: bool = False)` keeps existing constructor behavior. `refresh` accepts optional containment-policy/budget/accounting context only for the controlled route. `FulfillmentRefreshResult` gains defaulted cumulative usage and operation identity fields without altering legacy consumers.

- [ ] Write RED full/scoped tests through real `FulfillmentRunner.refresh`, using real reports, scoped plan/merge, lifecycle, ledger and cache. Controlled calls cannot resolve/execute legacy verify-spec prose.
- [ ] Add early explicit controlled dispatch after existing common admission. Reuse full/scoped impact planning, full fallback, report validation, deferred-scope handling, reconciliation, stamping and ledger helpers. A controlled contract identity must separate both cache and ledger reuse from legacy evidence.
- [ ] Select and durably bind the exact run before work; inspect existing recovery/state before any call to `init_verify_spec_run`. Keep explicit caller-run validation and source/workspace binding. Do not discover another run using “latest” during recovery.
- [ ] Stage scoped rows, merge them over a pinned full-report snapshot and validate exact canonical IDs before publication. Preserve unaffected rows and base-full provenance. Full fallback still uses the controlled route. Test no-impact/cache and strict observer paths.
- [ ] Test explicit reconciliation/dry-run, lifecycle completion only after publication, old cache rejection, changed input and publication conflicts. Feature-off and standalone CLI stay on their original path.
- [ ] Run all fulfillment runner/reconciliation/ledger/scoped/judgment and prior new tests; review and commit `feat: integrate controlled full and scoped fulfillment`.

## Task 5 — Ralph opt-in, accounting and closure acceptance

**Files:** Modify `src/harness/ralph.py`; create `tests/unit/test_controlled_fulfillment_delivery.py`; update parent design and convergence boundary receipts.

- [ ] Write RED tests through real Ralph verification/refresh with both provider facades and guided/semi/banzai modes. Existing `delivery_gate_controller` selects the controlled runner; feature-off and standalone calls remain legacy.
- [ ] Pass existing source, containment, remaining-budget and durable operation/accounted-usage context. Persist only newly unaccounted cumulative usage once in Ralph state; unknown usage remains explicit. Test interruption between runner completion and Ralph accounting, resumed replay and failed refresh charges.
- [ ] Exercise full/scoped/no-judge/cache/non-passing fulfillment, restart and completed PR-fix batch re-entry through verification and post-verification effects without mocking controller decisions. Preserve banzai deferral and convergence gating.
- [ ] Run affected Ralph, delivery documentation/finalization/re-entry, provider, direct-CLI and all new fulfillment tests. Repeat active prompt-ownership audit: no controlled fulfillment COMMANDER/legacy phase dispatch, no provider-specific role files.
- [ ] Obtain independent read-only final review, fix only demonstrated in-scope defects with RED tests, run final affected batch and `git diff --check`, record exact receipts and remaining live/installed/merge gates. Commit `test: accept controlled fulfillment delivery integration`.

## Execution / self-review

The tasks cover semantic contracts/full staging (Phase 2), scoped/recovery/publication
and usage (Phase 3), and the existing Ralph opt-in (Phase 4). There is no separate
workflow engine or publisher shared with unrelated systems. Tests keep semantic
decisions/host reads/validation real and script only external boundaries. The user
has selected inline completion; there is no new execution-choice or live-test
approval gate between these already-approved phases. A required design expansion
still stops for direction. Preserve branch/worktree; do not push or merge.

## Receipts

- Baseline: 152 affected fulfillment/preparation/judgment/inspection tests passed
  in 4.07s. Task 1: missing module RED; 53 new semantic tests passed, followed by
  97 affected tests in 0.77s. Both new artifacts were successfully inspected by
  the real installed Prosaic CLI without deployment. Commit `fb234103`.
- Task 2: missing controller RED, then actual staged report/prepass consumption.
  Ten safety RED cases covered unsafe staged destinations, final-turn evidence
  mutation and unknown usage on a lost process response. Independent review
  found judge-citation admission, selected-run-state binding and host-created
  evidence-listing drift; eight RED cases reproduced these before correction.
  Focused re-review independently reproduced the fixes and found no remaining
  findings. Additional RED cases retained runtime threshold classification when
  CodeGraph degrades and coverage test-case IDs in repair context.
- Final Tasks 1–2 affected batch: **417 passed in 11.72s**, including 41 new
  controller cases and six real Claude/Codex adapter/capture cases with scripted
  model processes. This is staged, inactive acceptance only; no canonical
  publication, recovery, Ralph integration or live-provider claim.
- A final review reproduction showed the legacy audit parser omits literal
  `---` inside requirement text. Threshold classification now consumes canonical
  structured rows through the existing classifier. The original reproduction
  and degraded-threshold test pass; focused review reported no remaining findings.
