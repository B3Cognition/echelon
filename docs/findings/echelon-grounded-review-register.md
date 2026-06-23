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
5. Advance `Last delta review HEAD` after the delta review is complete.

Suggested command:

```bash
git diff eeb490899655c0796ec9d9c187eb52fe1195427f..HEAD -- src extension docs tests
```

## Current Findings

| ID | Priority | Status | Finding | Evidence | Next action |
|---|---|---|---|---|---|
| EGR-001 | P0 | open | Missing deterministic `echelon_result` schema validation before state updates. | `src/harness/squad_provider.py`, `src/harness/squad_state.py`, `src/harness/squad.py`, `tests/kernel/test_squad_provider.py`, `tests/kernel/test_squad_state.py` | Implement schema validator and enforce it before applying `state_updates`. |
| EGR-002 | P1 | open | Phase A readiness and quality gates are partly deterministic and partly LLM-routed. | `extension/workflow/definition.yaml`, `src/harness/squad.py`, `src/echelon/cli.py` | Add deterministic Phase A artifact/readiness validators. |
| EGR-003 | P1 | open | Host-side LLM tool boundaries are mostly prompt-governed. | `extension/agents/**/*.md`, `src/harness/llm_provider.py`, `src/harness/skill_loader.py` | Define enforceable tool/file/network permission boundaries. |
| EGR-004 | P1 | open | Sandboxing exists, but sandbox recommendation should be explicit. | `src/harness/docker_provider.py`, `src/harness/init.py`, `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py` | Add sandbox suggestion report with evidence, confidence, risks, and approval point. |
| EGR-005 | P1 | open | Human-in-the-loop blocking is real but decision capture can improve. | `src/harness/squad.py`, `src/harness/escalation.py`, `src/echelon/cli.py` | Store typed blocked decisions and resume metadata. |
| EGR-006 | P2 | open | Review loops exist, but generic draft/critique/repair/re-check is not a reusable primitive. | `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/squad.py` | Introduce reusable repair loop after schema and artifact validators exist. |
| EGR-007 | P2 | open | Internalization is split between real codegen memory and prompt-level learning. | `src/codegen/memory/*`, `extension/agents/learning/*`, `knowledge-base/kb-schema.md` | Version, validate, and scope durable learnings. |
| EGR-008 | P2 | open | Role surface area is high relative to machine-checkable contracts. | `extension/agents/**/*.md`, `extension/workflow/definition.yaml` | Require result-schema compliance and declared output keys for routed roles. |
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

