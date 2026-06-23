# Echelon Grounded Review Register

**Last full review snapshot:** `docs/findings/2026-06-23-echelon-grounded-source-review.md`
**Last full review HEAD:** `eeb490899655c0796ec9d9c187eb52fe1195427f`
**Last updated:** 2026-06-23

## Operating Model

This register is the living tracking surface for grounded review findings. Keep
the dated snapshot immutable enough to preserve context, and update this file
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
3. Re-open the full source review only if workflow, harness, state, sandbox,
   memory, or CLI boundaries changed substantially.
4. For each affected finding, update `Evidence`, `Status`, `Next action`, and
   `Review notes`.
5. Confirm any implemented EGR has a corresponding `CHANGELOG.md` entry under
   `[Unreleased]`.
6. Advance `Last delta review HEAD` after the delta review is complete.

Suggested command:

```bash
git diff eeb490899655c0796ec9d9c187eb52fe1195427f..HEAD -- src extension docs tests
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
| EGR-002 | P1 | fixed | Phase A readiness and quality gates are partly deterministic and partly LLM-routed. | `src/harness/phase_a_readiness.py`, `src/harness/squad.py`, `src/echelon/cli.py`, `tests/unit/test_phase_a_readiness.py`, `tests/unit/test_cli_next_step_escalation.py`, `tests/unit/test_cli_continue.py`, `tests/integration/test_squad_controller.py` | Fixed: shared Phase A readiness validation now blocks missing build-input artifacts and blocked/interrupted run states before build-ready guidance or finalization. |
| EGR-003 | P1 | fixed | Host-side LLM tool boundaries are mostly prompt-governed. | `src/harness/llm_tool_policy.py`, `src/harness/config.py`, `src/harness/llm_provider.py`, `src/harness/review_loop.py`, `src/echelon/cli.py`, `extension/config-template.yml`, `tests/unit/test_llm_tool_policy.py`, `tests/unit/test_cli_llm_tool_policy.py`, `tests/unit/test_llm_provider.py`, `tests/unit/test_review_loop.py`, `tests/unit/test_config.py` | Fixed: host-side LLM runs now share deterministic policy command construction, prompt-based dispatches receive the effective policy preamble, and unsafe CLI permission-bypass flags fail closed unless explicit approval metadata is present. |
| EGR-004 | P1 | fixed | Sandboxing exists, but sandbox recommendation should be explicit. | `src/harness/sandbox_suggestion.py`, `src/harness/init.py`, `src/echelon/cli.py`, `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py`, `tests/unit/test_sandbox_suggestion.py`, `tests/unit/test_cli_harness_init_summary.py` | Fixed: `echelon harness init` writes and summarizes an evidence-backed sandbox suggestion report with confidence, commands/strategy, risks, approval point, and fallback path. |
| EGR-005 | P1 | fixed | Human-in-the-loop blocking is real but decision capture can improve. | `src/harness/blocked_decision.py`, `src/harness/squad_state.py`, `src/harness/escalation.py`, `src/echelon/cli.py`, `tests/unit/test_blocked_decision.py`, `tests/unit/test_escalation.py`, `tests/unit/test_cli_resume_escalation_options.py`, `tests/kernel/test_squad_state.py` | Fixed: blocked squad runs persist typed decision data and resume metadata; file-based escalations include JSON decision/resume metadata while preserving Markdown UX. |
| EGR-006 | P2 | fixed | Review loops exist, but generic draft/critique/repair/re-check is not a reusable primitive. | `src/harness/repair_loop.py`, `tests/unit/test_repair_loop.py`, `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/squad.py` | Fixed: introduced a deterministic, bounded repair-loop primitive with structured event logging, repeat-signature blocking, and caller-supplied critique/repair/re-check functions. |
| EGR-007 | P2 | fixed | Internalization is split between real codegen memory and prompt-level learning. | `src/codegen/memory/kb_schema_validator.py`, `tests/unit/test_kb_schema_validator.py`, `knowledge-base/kb-schema.md`, `src/codegen/memory/*`, `extension/agents/learning/*` | Fixed: introduced a deterministic knowledge-base validator for schema versions, append-only markers, provenance, pending-operation checksums, and project scoping for durable pattern/pitfall learnings. |
| EGR-008 | P2 | fixed | Role surface area is high relative to machine-checkable contracts. | `src/harness/role_contracts.py`, `src/harness/phase_graph.py`, `extension/agents/**/*.md`, `extension/workflow/definition.yaml`, `tests/unit/test_role_contracts.py`, `tests/kernel/test_phase_graph.py` | Fixed: routed roles now have a deterministic contract validator for required `echelon_result` fields and declared outputs; shipped routed role templates include explicit empty `state_updates` where applicable. |
| EGR-009 | P3 | open | RCA pipeline is not implemented as a first-class capability. | No dedicated incident/RCA pipeline found under `src/` or `extension/workflow/`. | Defer until core harness safety gates are stronger. |

## Implementation Plan

### Immediate Fixes

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P0 | Add deterministic `echelon_result` validator. | Prevents malformed LLM output from mutating state or routing. | `src/harness/echelon_result_schema.py`, `src/harness/squad_provider.py`, `src/harness/squad.py`, `tests/kernel/test_squad_provider.py` | Stronger central contract for every agent dispatch. |
| P1 | Promote blocked/incomplete Phase A outputs to blockers, not warnings. | Avoids telling operators to build incomplete specs. | `src/echelon/cli.py`, `src/harness/squad.py`, `tests/` | Better trust in CLI status and next-step guidance. |
| P1 | Make blocked-run questions structured. | Improves resume safety and auditability. | `src/harness/escalation.py`, `src/harness/squad.py`, `src/echelon/cli.py` | Cleaner human-in-the-loop UX and recoverability. |

### Short-Term Improvements

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P1 | Add Phase A artifact validators. | Makes spec readiness deterministic. | `src/harness/squad.py`, `src/echelon/cli.py`, `extension/workflow/phases/*.md` | Fewer false-ready and prompt-only gate outcomes. |
| P1 | Add sandbox suggestion report. | Lets users approve environment setup based on evidence. | `src/harness/init.py`, `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py` | Safer setup and clearer harness onboarding. |
| P1 | Add pre-push secret scan gate. | Reduces chance of leaking secrets through GitOps. | `src/harness/gitops.py`, `src/harness/config.py` | Safer PR automation. |

### Medium-Term Architecture Improvements

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P2 | Define per-phase allowed `state_updates` keys. | Prevents role drift and accidental state mutation. | `extension/workflow/phases/*.md`, `extension/workflow/definition.yaml`, validator module | Better traceability and fewer hidden contracts. |
| P2 | Build reusable Ralph-style repair primitive. | Reuses deterministic validation failures for bounded repair. | `src/harness/squad.py`, `src/harness/ralph.py`, new tests | Cleaner retry/revision behavior before state mutation. |
| P2 | Validate and version learning writes. | Prevents polluted memory and stale internalization. | `src/codegen/memory/*`, `extension/scripts/bash/kb-*`, `knowledge-base/kb-schema.md` | More trustworthy internalization. |

### Longer-Term Ideas

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P3 | Add RCA pipeline. | Extends Echelon into incident analysis and learning. | New workflow section, new RCA agents, integrations under `src/` | Incident intake to corrective/preventive action flow. |
| P3 | Model Team Topologies operating modes. | Helps tune agent/team interaction patterns. | `extension/workflow/definition.yaml`, docs, phase specs | Lower cognitive load and clearer role ownership. |
| P3 | Add observability export. | Improves cost, latency, retry, and quality analysis. | `src/harness/state.py`, `src/harness/coordinator.py`, logs/traces module | Better audit trail and production diagnostics. |

## EGR-001 Work Item

**Goal:** Add a deterministic `echelon_result` schema validator and enforce it
for every agent dispatch before applying `state_updates`.

**Proposed branch/thread:** `codex/echelon-result-validator`

**Acceptance criteria:**

- Malformed parsed YAML blocks do not produce state updates.
- Missing or non-string `verdict` is rejected.
- Unsupported `verdict` values are rejected or explicitly classified.
- Missing `state_updates` defaults only when the verdict allows it, otherwise it
  is rejected.
- Non-object `state_updates` is rejected.
- Non-list `journal_entries` is rejected.
- Reserved harness-owned keys, including `last_dispatch`, cannot be set by an
  agent result.
- Validation failure produces a blocked result with a clear reason and raw-output
  debug path when available.
- Tests cover valid output, malformed output, bad types, reserved keys, and
  blocking behavior before `SquadStateStore.advance`.
- `CHANGELOG.md` `[Unreleased]` mentions `EGR-001` and summarizes the validation
  behavior change.

**Likely implementation sequence:**

1. Add `src/harness/echelon_result_schema.py` with a pure validation function.
2. Add unit tests for the validator.
3. Call the validator from the result extraction path or immediately before
   state advance.
4. Ensure validation errors block the run rather than silently dropping updates.
5. Add regression tests around `SquadAgentResult.state_updates` and
   `SquadStateStore.advance`.

## Review Notes

| Date | Reviewed HEAD | Notes |
|---|---|---|
| 2026-06-23 | `eeb490899655c0796ec9d9c187eb52fe1195427f` | Initial grounded review register created from repository evidence. |
| 2026-06-23 | `176da20ace1d485545724467e3c757a7259e760f` | EGR-001 implemented with deterministic `echelon_result` validation in provider and state advance paths. Verification: `pytest tests/kernel -q` passed with 532 tests; pytest cache warnings were caused by restricted worktree cache writes. |
| 2026-06-23 | `working tree on codex/egr-002-phase-a-readiness` | EGR-002 implemented with shared deterministic Phase A readiness validation in CLI next-step/continue paths and the squad `phase4-document` finalization gate. Verification: `pytest tests/unit/test_phase_a_readiness.py tests/unit/test_cli_next_step_escalation.py tests/unit/test_run_readiness.py tests/unit/test_cli_continue.py tests/integration/test_squad_controller.py -q` passed with 83 tests; `pytest tests/kernel -q` passed with 532 tests. Broader `pytest tests/unit tests/kernel tests/integration/test_squad_controller.py -q` collection is blocked in this environment by missing existing dependencies `freezegun` and `lark`. |
| 2026-06-23 | `working tree on codex/egr-005-blocked-decisions` | EGR-005 implemented typed `blocked_decision` persistence, free-text/choice resume metadata, process-restart recoverability coverage, and JSON metadata for file-based escalations. Verification: `pytest tests/unit/test_blocked_decision.py tests/unit/test_escalation.py tests/unit/test_cli_resume_escalation_options.py tests/unit/test_cli_continue.py tests/unit/test_cli_next_step_escalation.py tests/kernel/test_squad_state.py tests/integration/test_squad_controller.py -q` passed with 145 tests; `pytest tests/kernel -q` passed with 534 tests. |
| 2026-06-23 | `working tree on codex/egr-004-sandbox-suggestion` | EGR-004 implemented a deterministic sandbox suggestion report composed from existing verify/app runtime detectors plus repository markers including Docker, devcontainer, package/lockfiles, Python/Java/Go/Rust markers, Makefile, CI workflows, and README setup instructions. The report is persisted under `harness.sandbox_suggestion`, written to `sandbox-suggestion.md`, and surfaced in the harness init summary before dependency install or app execution decisions. Verification: `pytest tests/unit/test_sandbox_suggestion.py tests/unit/test_cli_harness_init_summary.py tests/unit/test_harness_init_verify.py tests/unit/test_harness_init_app_runtime.py tests/unit/test_init.py -q` passed with 20 tests; `pytest tests/kernel -q` passed with 534 tests. |
| 2026-06-23 | `working tree on codex/egr-003-tool-boundaries` | EGR-003 implemented a small deterministic host-side LLM tool policy with config defaults, prompt preamble injection for prompt-based dispatches, shared AI CLI command construction, native opencode command preservation, and fail-closed validation for unsafe host execution bypass without `approval_reason`. Known remaining scope: this gates known host CLI bypass flags; deeper file, network, and individual tool-call enforcement remains runtime-specific to the selected AI CLI. Verification: `pytest tests/unit/test_cli_llm_tool_policy.py tests/unit/test_llm_tool_policy.py tests/unit/test_llm_provider.py tests/unit/test_review_loop.py tests/unit/test_config.py -q` passed with 61 tests; `pytest tests/kernel -q` passed with 534 tests. |
| 2026-06-23 | `working tree on codex/egr-006-repair-loop` | EGR-006 introduced `harness.repair_loop`, a deterministic reusable Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Exhaust primitive. It records structured loop events for later audit/internalization, enforces `max_repairs`, tracks token counts reported by callbacks, and blocks repeated critique signatures before unbounded repair cycles. Verification: `pytest tests/unit/test_repair_loop.py -q` passed with 4 tests; `pytest tests/kernel -q` passed with 534 tests. |
| 2026-06-23 | `working tree on codex/egr-007-memory-validation` | EGR-007 introduced `codegen.memory.kb_schema_validator`, a deterministic validator for durable knowledge-base documents and pending write operations. It checks documented schema versions, append-only markers, provenance, internalization-log gate metadata, pending-operation checksum/provenance requirements, and project scoping for local pattern/pitfall learnings. Verification: `pytest tests/unit/test_kb_schema_validator.py -q` passed with 5 tests; `pytest tests/kernel -q` passed with 534 tests. |
| 2026-06-23 | `working tree on codex/egr-008-role-contracts` | EGR-008 introduced `harness.role_contracts`, a deterministic routed-role validator requiring final `echelon_result` templates to declare `verdict`, `output_files`, `state_updates`, and `journal_entries`, and requiring routed workflow entries to declare outputs. `PhaseGraph` now preserves phase outputs, build workflow nodes declare their expected artifacts, and routed role prompt templates include explicit `state_updates: {}` when no state mutation is expected. Verification: `pytest tests/unit/test_role_contracts.py tests/kernel/test_phase_graph.py -q` passed with 18 tests; `pytest tests/kernel -q` passed with 535 tests. |
