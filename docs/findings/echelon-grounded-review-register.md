# Echelon Grounded Review Register

**Last full review snapshot:** `docs/findings/2026-06-26-echelon-grounded-source-review-refresh.md`
**Last full review HEAD:** `f73d950700efe02c9ed1caae0bd359bb9d9a802f`
**Last delta review snapshot:** `docs/findings/2026-06-24-egr-delta-review-after-egr-011.md`
**Last delta review HEAD:** `34b4857d5f9aa1cb74c30cddae169e77b7552009`
**Last updated:** 2026-06-26

## Operating Model

This register is the living tracking surface for grounded review findings. Keep
dated snapshots immutable enough to preserve context, and update this file
whenever repository contributions change the evidence, priority, owner, or
status of a finding.

### Status Values

- `open`: confirmed and not yet addressed.
- `in-progress`: implementation or design work has started.
- `fixed`: addressed in source and verified.
- `superseded`: replaced by a newer finding or architecture decision.
- `accepted-risk`: intentionally not fixed for now, with rationale.

### Delta Review Protocol

When the repo changes:

1. Compare the new head against `Last full review HEAD`.
2. Review only changed files first.
3. Re-open the full source review if workflow, harness, state, sandbox, memory,
   or CLI boundaries changed substantially.
4. For each affected finding, update `Evidence`, `Status`, `Next action`, and
   `Review notes`.
5. Confirm any implemented EGR has a corresponding `CHANGELOG.md` entry under
   `[Unreleased]`.
6. Advance `Last delta review HEAD` after the delta review is complete.

Suggested command:

```bash
git diff f73d950700efe02c9ed1caae0bd359bb9d9a802f..HEAD -- src extension docs tests
```

### EGR Completion Gate

An EGR implementation is not complete until the same change set includes:

- Source and test changes for the finding.
- A `CHANGELOG.md` `[Unreleased]` entry that names the EGR ID and explains the
  user-visible or operator-visible impact.
- This register updated with the finding status, evidence, and review note.
- Verification commands and outcomes captured in the implementation thread or PR
  description.

This is deliberately part of the EGR contract rather than an optional release
cleanup step: EGR work usually changes safety, harness behavior, or operating
assumptions, so downstream operators need the change surfaced in the changelog at
the same time as the code lands.

## Current Findings

| ID | Priority | Status | Finding | Evidence | Next action |
|---|---|---|---|---|---|
| EGR-001 | P0 | fixed | Missing deterministic `echelon_result` schema validation before state updates. | `src/harness/echelon_result_schema.py`, `src/harness/squad_provider.py`, `src/harness/squad_state.py`, `tests/kernel/test_echelon_result_schema.py`, `tests/kernel/test_squad_provider.py`, `tests/kernel/test_squad_state.py` | Fixed: parsed agent results are validated before state mutation; invalid results block with a clear reason. |
| EGR-002 | P1 | fixed | Phase A readiness and quality gates were partly deterministic and partly LLM-routed. | `src/harness/phase_a_readiness.py`, `src/harness/squad.py`, `src/echelon/cli.py`, `tests/unit/test_phase_a_readiness.py`, `tests/unit/test_cli_next_step_escalation.py`, `tests/unit/test_cli_continue.py`, `tests/integration/test_squad_controller.py` | Fixed: shared Phase A readiness validation blocks incomplete or blocked/interrupted Phase A states before build-ready guidance or finalization. |
| EGR-003 | P1 | fixed | Host-side LLM tool boundaries were mostly prompt-governed. | `src/harness/llm_tool_policy.py`, `src/harness/config.py`, `src/harness/llm_provider.py`, `src/harness/review_loop.py`, `src/echelon/cli.py`, `extension/config-template.yml`, `tests/unit/test_llm_tool_policy.py`, `tests/unit/test_cli_llm_tool_policy.py`, `tests/unit/test_llm_provider.py`, `tests/unit/test_review_loop.py`, `tests/unit/test_config.py` | Fixed: unsafe host CLI permission-bypass flags fail closed unless explicitly configured with approval metadata. |
| EGR-004 | P1 | fixed | Sandboxing existed, but sandbox recommendation needed to be explicit. | `src/harness/sandbox_suggestion.py`, `src/harness/init.py`, `src/echelon/cli.py`, `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py`, `tests/unit/test_sandbox_suggestion.py`, `tests/unit/test_cli_harness_init_summary.py` | Fixed: `echelon harness init` writes and summarizes an evidence-backed sandbox suggestion report. |
| EGR-005 | P1 | fixed | Human-in-the-loop blocking was real but decision capture needed structure. | `src/harness/blocked_decision.py`, `src/harness/squad_state.py`, `src/harness/escalation.py`, `src/echelon/cli.py`, `tests/unit/test_blocked_decision.py`, `tests/unit/test_escalation.py`, `tests/unit/test_cli_resume_escalation_options.py`, `tests/kernel/test_squad_state.py` | Fixed: blocked squad runs persist typed decisions and resume metadata. |
| EGR-006 | P2 | fixed | Review loops existed, but generic draft/critique/repair/re-check was not reusable. | `src/harness/repair_loop.py`, `tests/unit/test_repair_loop.py`, `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/squad.py` | Fixed as a primitive: `RepairLoop` exists; follow-on EGR-019 tracks adoption in existing loops. |
| EGR-007 | P2 | fixed | Internalization was split between real codegen memory and prompt-level learning. | `src/codegen/memory/kb_schema_validator.py`, `tests/unit/test_kb_schema_validator.py`, `knowledge-base/kb-schema.md`, `src/codegen/memory/*`, `extension/agents/learning/*` | Fixed: deterministic KB validation exists for durable pattern/pitfall learning writes. |
| EGR-008 | P2 | fixed | Role surface area was high relative to machine-checkable contracts. | `src/harness/role_contracts.py`, `src/harness/phase_graph.py`, `extension/agents/**/*.md`, `extension/workflow/definition.yaml`, `tests/unit/test_role_contracts.py`, `tests/kernel/test_phase_graph.py` | Fixed: routed roles have contract validation for required `echelon_result` fields, outputs, and allowlists. |
| EGR-009 | P3 | accepted-risk | RCA pipeline is not implemented as a first-class capability in this source tree. | No dedicated incident/RCA pipeline found under `src/` or `extension/workflow/`; user confirmed a separate RCA pipeline already exists and should be integrated later from its actual sources. | Parked pending grounded integration of the separate RCA pipeline; do not implement from the original review alone. |
| EGR-010 | P1 | fixed | GitOps lacked a deterministic pre-push/pre-commit secret scan gate. | `src/harness/secret_scan.py`, `src/harness/gitops.py`, `tests/unit/test_secret_scan.py`, `tests/integration/test_gitops_safety.py`, `tests/integration/test_gitops_commit_push.py` | Fixed: `GitOpsManager.commit()` scans staged files before committing and blocks high-confidence findings. |
| EGR-011 | P2 | fixed | Per-phase `state_updates` allowlists were not enforced. | `extension/workflow/definition.yaml`, `src/harness/echelon_result_schema.py`, `src/harness/phase_graph.py`, `src/harness/role_contracts.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`, `src/harness/squad_state.py`, tests under `tests/kernel/` and `tests/unit/` | Fixed: phases declare `allowed_state_updates`, static validation requires them, and runtime writes enforce them. |
| EGR-012 | P1 | fixed | Pre-dispatch agent `state_updates` bypassed per-phase allowlists. | `src/harness/squad_executors.py::_run_pre_dispatch()`, `tests/kernel/test_squad_executors_journal.py` | Fixed: pre-dispatch agents validate through the parent phase allowlist before state mutation. |
| EGR-013 | P1 | fixed | COMMANDER judgment state updates bypassed allowlists. | `src/harness/squad.py::JUDGMENT_STATE_UPDATE_KEYS`, `src/harness/squad.py::_apply_judgment_state_updates()`, `tests/integration/test_squad_controller.py::TestCommanderJudgmentStateUpdates` | Fixed: COMMANDER judgment writes use a narrow deterministic allowlist. |
| EGR-014 | P2 | fixed | Allowed `state_updates` were enforced but not fully injected into agent prompts. | `src/harness/squad_executors.py::_allowed_state_updates_contract()`, prompt assembly tests in `tests/kernel/test_squad_executors_journal.py` | Fixed: normal, pre-dispatch, staged, and conditional prompts disclose allowed state-update keys. |
| EGR-015 | P1 | fixed | Normal agent dispatch wrote journal entries before allowlist validation could block invalid state updates. | `src/harness/squad_executors.py::AgentExecutor.execute()`, `src/harness/echelon_result_schema.py`, `extension/workflow/definition.yaml`, `tests/kernel/test_squad_executors_journal.py` | Fixed: normal agent dispatch validates before journal, cost, recovery, or state handling. |
| EGR-016 | P1 | fixed | Whole-workflow contract validation was incomplete. | `src/harness/workflow_validator.py`, `scripts/bash/dry-run.sh`, `tests/kernel/test_workflow_validator.py`, `tests/kernel/test_phase_graph.py` | Fixed: executable workflow transitions now have deterministic validation for shape, supported keys, target phases, condition syntax, actions, and `state_update` blocks; dry-run runs the validator when the Python harness source is available. |
| EGR-017 | P1 | open | Safety documentation drift: README still describes unconditional Claude permission bypass. | `README.md` describes `claude -p <prompt> --dangerously-skip-permissions`; actual policy in `src/harness/llm_tool_policy.py` only adds bypass flags when explicitly approved. | Update README and any related help text to match EGR-003's fail-closed tool-policy contract. |
| EGR-018 | P1 | open | Python journal writers do not enforce the canonical journal-entry schema. | `extension/scripts/bash/validate-journal-entry.sh` and `extension/workflow/journal-entry-types.yaml` exist; `src/harness/squad.py::_write_journal_entries()` and `src/harness/squad_executors.py::_write_journal_entries()` append dict entries without schema validation. | Add a Python journal-entry validator at the actual write boundary. |
| EGR-019 | P2 | open | The reusable repair-loop primitive is not yet adopted by existing Ralph/review/squad loops. | `src/harness/repair_loop.py` exists; `src/harness/ralph.py` and `src/harness/review_loop.py` still own bespoke loop logic. | Pilot `RepairLoop` in one existing loop and preserve existing termination semantics. |
| EGR-020 | P2 | open | Active role catalog and public architecture narrative need reconciliation. | README describes a 41-agent architecture; the source tree has 68 agent markdown files under `extension/agents/`. | Document which roles are active-routed, auxiliary, RE-only, build-only, deprecated, or spec-kit-only. |
| EGR-021 | P2 | open | Extension/deployed-copy drift is still a common operator footgun. | CLI and README note that terminal runs read installed extension content under `.specify/extensions/echelon`, while developers edit this checkout. | Add a deterministic drift check to `dry-run`, `status`, or `run` preflight. |
| EGR-022 | P2 | open | Core shell contract tests remain outside pytest collection. | `tests/run-all.sh`, `tests/unit/*.sh`, `tests/integration/*.sh`, and `tests/README.md` show legacy shell tests alongside pytest. | Move core deterministic contract checks to Python where feasible; keep true shell integration tests as shell. |

## Next EGR Backlog

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P1 | EGR-017: Fix LLM tool-policy documentation drift. | README currently contradicts the implemented unsafe-permissions contract. | `README.md`, maybe `extension/config-template.yml` examples if needed | Operators know exactly where and how unsafe host execution is configured. |
| P1 | EGR-018: Enforce journal-entry schema in Python writers. | Reasoning journal entries feed audit and internalization; malformed entries should not be silently persisted. | `src/harness/journal_entry_validator.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`, `extension/workflow/journal-entry-types.yaml`, tests | More trustworthy audit trail and learning data. |
| P2 | EGR-019: Pilot `RepairLoop` adoption. | Reduces bespoke retry behavior and standardizes repair-loop logging. | `src/harness/review_loop.py` or a focused Phase A artifact repair gate, `src/harness/repair_loop.py`, tests | Cleaner bounded repair behavior with reusable audit events. |
| P2 | EGR-020: Reconcile role catalog. | Reduces contributor/operator cognitive load. | `README.md`, `extension/extension.yml`, `extension/workflow/definition.yaml`, docs | Clear active-role inventory. |
| P2 | EGR-021: Add extension drift check. | Prevents confusion when repo edits are not installed into the active extension copy. | `scripts/bash/dry-run.sh`, `src/echelon/cli.py`, `README.md` | Fewer “fixed in checkout, stale in run” failures. |
| P2 | EGR-022: Continue shell-to-Python test migration. | Pytest collection is easier to run consistently in CI and local workflows. | `tests/unit/*.sh`, `tests/integration/*.sh`, `tests/kernel/` | Better portability and fewer separate test paths. |
| P3 | EGR-009: Integrate external RCA pipeline from source. | Adds incident/RCA capability without inventing duplicate behavior. | Future RCA integration adapter, workflow namespace, docs/tests after source is available | Source-grounded RCA flow tied into Echelon. |

## Review Notes

| Date | Reviewed HEAD | Notes |
|---|---|---|
| 2026-06-23 | `eeb490899655c0796ec9d9c187eb52fe1195427f` | Initial grounded review register created from repository evidence. |
| 2026-06-23 | `176da20ace1d485545724467e3c757a7259e760f` | EGR-001 implemented with deterministic `echelon_result` validation in provider and state advance paths. Verification: `pytest tests/kernel -q` passed with 532 tests. |
| 2026-06-23 | `working tree on codex/egr-002-phase-a-readiness` | EGR-002 implemented shared deterministic Phase A readiness validation in CLI next-step/continue paths and the squad `phase4-document` finalization gate. |
| 2026-06-23 | `working tree on codex/egr-005-blocked-decisions` | EGR-005 implemented typed blocked decisions and resume metadata. |
| 2026-06-23 | `working tree on codex/egr-004-sandbox-suggestion` | EGR-004 implemented deterministic sandbox suggestion reports. |
| 2026-06-23 | `working tree on codex/egr-003-tool-boundaries` | EGR-003 implemented deterministic host-side LLM tool policy and fail-closed unsafe bypass. |
| 2026-06-23 | `working tree on codex/egr-006-repair-loop` | EGR-006 introduced `harness.repair_loop`. |
| 2026-06-23 | `working tree on codex/egr-007-memory-validation` | EGR-007 introduced deterministic KB schema validation. |
| 2026-06-23 | `working tree on codex/egr-008-role-contracts` | EGR-008 introduced deterministic routed-role contract validation. |
| 2026-06-23 | `665c7acbd3a6a2fae60a617e39c4a1aa7abfd808` | Delta review after EGR-008 completed; EGR-010 and EGR-011 were promoted. |
| 2026-06-23 | `working tree on codex/egr-010-secret-scan` | EGR-010 implemented deterministic staged-file secret scanning in GitOps. |
| 2026-06-24 | `working tree on codex/egr-011-state-update-allowlists` | EGR-011 implemented per-phase `allowed_state_updates` declarations and enforcement. |
| 2026-06-24 | `34b4857d5f9aa1cb74c30cddae169e77b7552009` | Delta review after EGR-011 completed; EGR-012, EGR-013, and EGR-014 were promoted. |
| 2026-06-24 | `working tree on codex/egr-012-pre-dispatch-allowlist` | EGR-012 implemented pre-dispatch allowlist validation. |
| 2026-06-24 | `working tree on codex/egr-013-judgment-allowlist` | EGR-013 implemented COMMANDER judgment update validation. |
| 2026-06-24 | `working tree on codex/egr-014-allowed-updates-prompts` | EGR-014 disclosed allowed state-update keys in dispatch prompts. Verification included full `pytest` with 2318 passed and 22 skipped. |
| 2026-06-25 | `working tree on codex/egr-015-agent-executor-validation` | EGR-015 moved normal agent result validation before journal writes. Verification included full `pytest` with 2320 passed and 22 skipped plus `bash tests/run-all.sh` passing on retry. |
| 2026-06-26 | `f73d950700efe02c9ed1caae0bd359bb9d9a802f` | Full refreshed source review completed after recovery/consensus hardening. EGR-001 through EGR-015 remain fixed, EGR-009 remains accepted-risk, and EGR-016 through EGR-022 define the refreshed next backlog. Most recent full suite before this review: `pytest` passed with 2366 passed and 22 skipped. |
| 2026-06-26 | `working tree on main` | EGR-016 implemented deterministic workflow-definition validation and dry-run preflight wiring. Verification: `pytest tests/kernel/test_workflow_validator.py tests/kernel/test_phase_graph.py -q` passed with 35 tests; direct validator reported `workflow definition valid`; `bash -n scripts/bash/dry-run.sh` passed. |
