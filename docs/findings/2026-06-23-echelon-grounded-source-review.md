# Echelon Grounded Source Review Snapshot

**Date:** 2026-06-23
**Reviewed repository HEAD:** `eeb490899655c0796ec9d9c187eb52fe1195427f`
**Branch observed:** `main`
**Status:** open - source review snapshot and planning baseline.
**Companion register:** `docs/findings/echelon-grounded-review-register.md`

## Purpose

This document preserves the grounded source-review findings for Echelon at a
specific repository head. Treat it as the review baseline: future review updates
should diff from the reviewed HEAD above and update the companion register rather
than re-reviewing the whole repository from scratch.

## How To Keep This Review Current

Use a delta review workflow:

1. Record the last reviewed commit from this file or the register.
2. Review only changed files with `git diff <last-reviewed-head>..HEAD`.
3. Re-check any findings whose evidence files changed.
4. Mark findings as `open`, `in-progress`, `fixed`, `superseded`, or `accepted-risk`.
5. Add a short review note with the new reviewed HEAD and changed conclusions.

For broad architecture changes, run a fresh full review and create a new dated
snapshot. For routine contributions, update only the register.

## What Exists Today

Echelon is implemented as two related systems:

- Phase A spec authoring through thin command wrappers in `extension/commands/`,
  workflow routing in `extension/workflow/definition.yaml`, phase contracts in
  `extension/workflow/phases/*.md`, and agent prompts in `extension/agents/`.
- Phase B build and verification through deterministic Python harness code under
  `src/harness/`, including strategy coordination, Docker-backed verification,
  review loops, Git mirror/worktree handling, state persistence, and PR support.

The README and repository instructions describe Echelon as a spec-kit extension
with a multi-agent software engineering squad. The source tree supports that
description: agent roles and workflow phases are present, and the Python harness
implements substantial deterministic substrate around the LLM-driven agents.

## Architecture Evidence Map

| Area | Evidence | Finding |
|---|---|---|
| CLI entry points | `src/echelon/cli.py` | Owns command dispatch for `echelon`, `harness`, `land`, `spec target`, `resume`, `continue`, `status`, and related commands. |
| Skill command wrappers | `extension/commands/echelon.run.md`, `extension/commands/echelon.build.md`, `extension/commands/echelon.codegen.md` | Wrappers are intentionally thin and delegate behavior to COMMANDER plus workflow definitions. |
| Workflow graph | `extension/workflow/definition.yaml` | Phase graph, routing conditions, phase assignments, convergence thresholds, build-task-loop, re-extraction, verify-spec, and reopen flows are explicit. |
| Agent prompts | `extension/agents/**/*.md` | Primary role prompts exist across control, exploration, feasibility, solution, build, learning, specialists, and re-extraction. |
| Result protocol | `extension/agents/control/commander.md`, `src/harness/squad_provider.py`, `src/harness/squad_state.py` | Agents are expected to emit `echelon_result`; the harness extracts YAML and applies `state_updates`, but there is no central deterministic schema validator yet. |
| State persistence | `src/harness/state.py`, `src/harness/squad_state.py` | State is persisted with atomic writes, locks, transition guards, dispatch counters, and last-dispatch recovery. |
| Harness lifecycle | `src/harness/coordinator.py`, `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/visual_ralph.py` | Build, verify, fix/reverify, visual, and PR review loops are real code rather than prompt-only concepts. |
| Sandbox | `src/harness/docker_provider.py`, `src/harness/init.py`, `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py` | Docker/Podman-oriented sandbox initialization, verify command detection, app runtime detection, and egress controls exist. |
| GitOps | `src/harness/gitops.py` | Git mirror, worktrees, default-branch push refusal, force-with-lease push, PR creation, and review polling exist. |
| Requirements quality | `src/understanding/cli.py` | Deterministic requirements-quality CLI exists with many metrics and quality gates. |
| Codegen memory | `src/codegen/memory/*` | MemPalace/ChromaDB-backed memory exists for the SOAR codegen path and is isolated by wing. |

## Primary Findings

### EGR-001: Missing deterministic `echelon_result` schema validation

**Priority:** P0
**Status:** open

Agents return routing-critical data through a trailing `echelon_result:` YAML
block. `src/harness/squad_provider.py` extracts the last YAML or fenced block and
returns it as a dictionary. `src/harness/squad_state.py` then applies
`result.state_updates` during `SquadStateStore.advance`. The existing tests in
`tests/kernel/test_squad_provider.py` focus on extraction behavior, and
`tests/kernel/test_squad_state.py` focuses on state transition behavior.

What is missing is a deterministic validator that proves the parsed result has
the expected shape before any `state_updates` are applied. The current boundary
is therefore too permissive for a system where LLM output can alter routing,
blocked state, escalation fields, and task status.

Recommended first implementation:

- Add a small validator module, likely `src/harness/echelon_result_schema.py`.
- Validate required top-level structure, allowed verdict values, `state_updates`
  object type, `journal_entries` list type, and reserved state keys.
- Call the validator in `src/harness/squad_provider.py` immediately after parse,
  or in `src/harness/squad.py` before any state advance. The safest placement is
  before `SquadStateStore.advance` consumes `result.state_updates`.
- Block the run with a clear validation error if the result is malformed.
- Add focused tests in `tests/kernel/test_squad_provider.py` and
  `tests/kernel/test_squad_state.py`.

Why this should be first: it protects the central contract shared by every
agent, COMMANDER, the journal, and the state machine. It is smaller than
sandboxing or role refactors and has high leverage.

### EGR-002: Phase A gates are partly deterministic and partly LLM-routed

**Priority:** P1
**Status:** open

`extension/workflow/definition.yaml` defines explicit Phase A routing and
quality loops. `src/harness/squad.py` evaluates many routing conditions and has
terminal blocked states. However, important signals still arrive through
agent-written `state_updates`, which makes validation of artifact completeness
and gate outcomes uneven.

Recommended direction: factor deterministic artifact validators for Phase A
readiness, including required files, required sections, expected phase outputs,
and gate status. Route on validator results before accepting "ready to build".

### EGR-003: Host-side LLM tool boundaries are mostly prompt-governed

**Priority:** P1
**Status:** open

The harness verifies in Docker, and `src/harness/docker_provider.py` has real
container isolation and optional proxy controls. However, Phase A and many build
LLM steps still execute through host LLM tooling and prompt contracts. Tool
permissions, file boundaries, and prompt-injection resistance are therefore not
fully deterministic at the orchestration layer.

Recommended direction: separate prompt-level rules from enforceable tool policy,
especially for file writes, shell execution, network access, and secret exposure.

### EGR-004: Sandboxing exists, but sandbox recommendation should be explicit

**Priority:** P1
**Status:** open

Docker-backed verification exists in `src/harness/docker_provider.py`, and
environment detection exists in `src/harness/verify_detection.py` and
`src/harness/app_runtime_detection.py`. The review found enough substrate for
automatic sandbox suggestion, but the UX should expose a deterministic
"suggested sandbox plan" before risky dependency install or app execution.

Recommended direction: add a sandbox suggestion report at harness init time with
detection evidence, confidence, suggested commands, risks, human approval, and a
fallback path.

### EGR-005: Human-in-the-loop blocking is real but decision capture can improve

**Priority:** P1
**Status:** open

`src/harness/squad.py` can block on missing `echelon_result`, terminal states,
phase dispatch limits, token budgets, and escalation questions. `src/harness/escalation.py`
persists escalation records and resume answers. The remaining gap is richer,
typed decision capture: multiple-choice decisions, free-text answers, default
recommendations, and durable linkage from decision to later state changes.

Recommended direction: make blocked-run questions structured data with answer
type, choices, default, risk level, and resume command.

### EGR-006: Review loops exist, but generic Ralph-style draft critique repair is incomplete

**Priority:** P2
**Status:** open

`src/harness/ralph.py` implements a real build/verify/fix loop. `src/harness/review_loop.py`
implements a PR review loop. These are concrete Ralph-like loops for build and
review. A generic pre-state-update loop of `Draft output -> Critique -> Repair
-> Re-check -> Accept / Block / Escalate` is not yet a central reusable
primitive.

Recommended direction: after EGR-001, reuse schema validation failures and
artifact validation failures as the first deterministic critique inputs.

### EGR-007: Internalization is split between real memory and prompt-level learning

**Priority:** P2
**Status:** open

The codegen path has real persistent memory under `src/codegen/memory/*`.
Learning agents and KB scripts exist under `extension/agents/learning/` and
`extension/scripts/bash/`, and `knowledge-base/kb-schema.md` defines a schema.
However, internalization is not uniformly enforced across the main Echelon run
flow. It is partly functional and partly conceptual/prompt-driven.

Recommended direction: define which learnings are allowed into durable memory,
validate them, version them, and record failed attempts and human decisions.

### EGR-008: Role surface area is high for the current contract maturity

**Priority:** P2
**Status:** open

The repository contains many primary roles across `extension/agents/`. The
workflow graph names many of them explicitly, and several roles have clear
contracts. The risk is that role proliferation outruns machine-checkable output
contracts, making the system harder to operate and debug.

Recommended direction: keep the roles, but require every role that participates
in state routing to pass the same result validator and declare expected
`state_updates` keys in the phase spec.

### EGR-009: RCA pipeline is not implemented as a first-class capability

**Priority:** P3
**Status:** open

The review did not find a first-class incident/RCA pipeline with logs, metrics,
traces, alert correlation, hypothesis testing, corrective actions, and
post-incident knowledge updates. Existing debugging, verification, and learning
agents could support this later.

Recommended direction: add RCA as a separate pipeline after the core result,
state, sandbox, and audit contracts are stronger.

## Update Notes

- This snapshot should not be edited for routine status changes. Update the
  companion register instead.
- Create a new dated snapshot only when the architecture or review conclusions
  materially change.
- When a contribution lands, first run a delta review against
  `eeb490899655c0796ec9d9c187eb52fe1195427f`, then advance the reviewed HEAD in
  the register.

