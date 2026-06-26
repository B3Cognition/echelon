# Echelon Grounded Source Review

**Review date:** 2026-06-26
**Reviewed HEAD:** `f73d950700efe02c9ed1caae0bd359bb9d9a802f`
**Scope:** Full refreshed review against current `main`, using the original Echelon grounded review prompt.

## Executive Summary

Echelon has moved from a prompt-heavy agent collection toward a substantially more deterministic harness. The original P0/P1 issues around unvalidated `echelon_result` blocks, unsafe state mutation, incomplete Phase A readiness, host-side LLM permission bypass, blocked-run decisions, sandbox suggestion, and GitOps secret scanning have source-level fixes and tests. The most important evidence is in `src/harness/echelon_result_schema.py`, `src/harness/squad_state.py`, `src/harness/squad_executors.py`, `src/harness/squad.py`, `src/harness/phase_a_readiness.py`, `src/harness/llm_tool_policy.py`, `src/harness/blocked_decision.py`, `src/harness/sandbox_suggestion.py`, `src/harness/secret_scan.py`, and `src/harness/role_contracts.py`.

The refreshed risk profile is narrower. The main remaining reliability gaps are now around whole-workflow validation, documentation drift, journal-entry schema enforcement at the Python writer boundary, and adoption of the new reusable repair loop in existing Ralph/review/squad loops. EGR-009 remains intentionally parked because the team has a separate RCA pipeline that should be integrated from its real sources rather than reconstructed from the review prompt.

## What Exists Today

Echelon is a spec-kit extension plus Python substrate:

- CLI entrypoint and command dispatch: `src/echelon/cli.py`.
- Workflow graph and phase contracts: `extension/workflow/definition.yaml` and `extension/workflow/phases/*.md`.
- Agent prompts: 68 markdown files under `extension/agents/`, with 7 functional layers represented in the README.
- Thin command wrappers: `extension/commands/echelon.run.md`, `extension/commands/echelon.build.md`, `extension/commands/echelon.codegen.md`, and related command files.
- Phase A squad orchestration: `src/harness/squad.py`, `src/harness/squad_executors.py`, `src/harness/squad_state.py`, `src/harness/phase_graph.py`.
- Phase B build/verify/PR harness: `src/harness/coordinator.py`, `src/harness/ralph.py`, `src/harness/docker_provider.py`, `src/harness/gitops.py`, `src/harness/review_loop.py`, `src/harness/state.py`.
- Codegen/SOAR pipeline: `src/codegen/**`.
- Requirements quality CLI: `src/understanding/**`.
- Memory/internalization substrate: `src/codegen/memory/**`, `knowledge-base/kb-schema.md`, and learning agents under `extension/agents/learning/`.

The project has a broad test suite. `pyproject.toml` configures pytest across `tests/`; `tests/run-all.sh` still runs Python suites plus legacy shell tests. The most recent full run before this refresh passed with `2366 passed, 22 skipped`.

## Architecture Map

The architecture is explicit and easier to follow than in the first review:

- `src/echelon/cli.py::SKILL_MAP` maps CLI verbs to skill command files.
- `src/echelon/cli.py::USAGE` documents `run`, `status`, `continue`, `rewind`, `resume`, Phase B harness commands, and spec target commands.
- `README.md` documents two execution paths: interactive spec-kit skill invocation and terminal CLI subprocess invocation.
- `extension/workflow/definition.yaml` owns phase routing, transitions, agents, declared outputs, and `allowed_state_updates`.
- `src/harness/phase_graph.py::PhaseGraph` loads the workflow into typed `PhaseNode` objects.
- `src/harness/squad.py::SquadController` owns the Phase A execution loop, phase dispatch caps, transition evaluation, interrupted-run persistence, terminal blocking, and COMMANDER judgment dispatch.
- `src/harness/squad_executors.py` owns phase executor implementations and prompt assembly.
- `src/harness/coordinator.py::StrategyCoordinator` fans out Phase B strategies and wires Ralph, visual Ralph, and review loop execution.

Responsibilities are clearer than before, but not perfectly separated. `src/echelon/cli.py` remains large and mixes CLI parsing, run recovery, harness command dispatch, skill subprocess invocation, and user-facing output. `src/harness/squad.py` owns both deterministic transition mechanics and fallback LLM judgment. That boundary is workable, but still a production risk because workflow changes can fail at runtime unless validated as a whole.

## Agent Role Inventory

The repository contains 68 agent markdown files under `extension/agents/`. The README describes the public architecture as a 41-agent, 7-layer model, while the filesystem includes additional RE/build/control/specialist files. This is not necessarily wrong, but it means the README count and the deployed role surface should be periodically reconciled.

| Layer | Evidence | Representative roles | Comments |
|---|---|---|---|
| Control | `extension/agents/control/*.md` | COMMANDER, CHIEF, CHECKPOINT, SCOREKEEPER, STRATEGIST, TRACKER | COMMANDER remains central; CHIEF owns constitution creation/update. |
| Exploration | `extension/agents/exploration/*.md` | SCOUT, SYNTHESIZER, MODELER, CARTOGRAPHER, SAGE, GOLDDIGGER | Phase 1 understanding and brownfield extraction support. |
| Feasibility | `extension/agents/feasibility/*.md` | GATEKEEPER, VALIDATOR | Used for feasibility and structural checks. |
| Requirements engineering | `extension/agents/re/*.md` | ANALYZER, SPECIFIER, TASKER, CONSTITUTER, VERIFIER | Supports brownfield/spec repair workflows beyond the original triad. |
| Solution | `extension/agents/solution/*.md` | ARCHITECT, SENTINEL, ORCHESTRATOR | Phase 3 architecture, risk, and task planning. |
| Build | `extension/agents/build/*.md` | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, DEBUGGER, VERIFICATION | Build quality gates and implementation loop. |
| Learning | `extension/agents/learning/*.md` | INTERNALIZER, AUDITOR, ADAPTIVE, MIRROR, VETERAN, CONSOLIDATOR | Internalization is partly prompt-level and partly backed by codegen memory. |
| Specialists | `extension/agents/specialists/*.md` | INVESTIGATOR, GUARDIAN, ORACLE, BENCHMARK, ADVOCATE, MAVERICK | Conditional specialist dispatch is configured in `definition.yaml`. |

Role output contracts are significantly stronger after EGR-008 through EGR-015. `src/harness/role_contracts.py` validates routed roles for required `echelon_result` fields, declared outputs, and state update allowlists. The remaining issue is not individual role contracts; it is validating the workflow graph and transition language as one artifact.

## Triadic Model Assessment

| Stage | Implementation evidence | Inputs | Outputs | Enforcement assessment |
|---|---|---|---|---|
| UNDERSTAND | `phase1-discover`, `phase1-synthesizer`, `phase1-modeler`, `phase1-tracker`, `phase1-why1`, `phase1-constitution`, `phase1-what`, `phase1-why2` in `extension/workflow/definition.yaml`; phase specs under `extension/workflow/phases/`; agents under `extension/agents/exploration/` and `extension/agents/control/chief.md` | User message, repo evidence, templates, brownfield extraction artifacts, staged outputs | Domain artifacts, constitution, spec amendments, quality scores, journal entries | Now partially enforced by phase routing, schema validation, output checks, and readiness gates. Still not fully spec-first until every transition and output contract is statically validated. |
| REASON | `phase2-*`, `phase3-how`, `phase3-specialists`, `phase3-sentinel`, `phase3-plan`, `phase3-consensus`; `src/harness/condition_evaluator.py`; `src/harness/squad.py::_evaluate_transitions()` | Understanding artifacts, constitution, feasibility/quality state | Architecture artifacts, tasks, consensus verdicts, checkpoint decisions | More explicit than before. Consensus routing was recently hardened, but the transition language is still only partially validated before runtime. |
| INTERNALIZE | `extension/agents/learning/*`, `src/codegen/memory/*`, `src/codegen/memory/kb_schema_validator.py`, `knowledge-base/kb-schema.md`, MemPalace wing logic in `src/codegen/memory/context.py` and `collision.py` | Run outputs, requirements, memory records, feedback/pattern/pitfall entries | Validated KB entries, codegen memory drawers, learning artifacts | Real but uneven. Codegen memory and KB validation are functional; Phase A learning agents are still more prompt-driven than deterministic. |

Internalization is no longer just a conceptual label, because codegen memory and KB schema validation exist. It is not yet a fully trusted memory system across all Echelon runs because learning writes, journal types, and run summaries are not uniformly validated by the Python writers.

## Harness Programming Assessment

Implemented harness capabilities:

- Structured Phase A run lifecycle in `src/harness/squad.py`.
- Deterministic `echelon_result` validation in `src/harness/echelon_result_schema.py`.
- Per-phase state update allowlists loaded through `src/harness/phase_graph.py`.
- Pre-dispatch, normal dispatch, staged consensus, conditional dispatch, state advance, and COMMANDER judgment validation paths in `src/harness/squad_executors.py`, `src/harness/squad_state.py`, and `src/harness/squad.py`.
- Run recovery UX for `continue`, `rewind`, and `resume` in `src/echelon/cli.py`.
- Phase A readiness validation in `src/harness/phase_a_readiness.py`.
- Phase B Docker verify and worktree orchestration in `src/harness/docker_provider.py`, `src/harness/gitops.py`, and `src/harness/ralph.py`.
- Review loop support in `src/harness/review_loop.py`.
- GitOps secret scan before commit in `src/harness/secret_scan.py` and `src/harness/gitops.py`.

Missing or partial capabilities:

- There is no single workflow-definition validator that rejects unsupported transition keys, unknown transition fields, invalid target phases, or condition expressions before a run starts.
- The reusable `src/harness/repair_loop.py` primitive exists but is not yet the common implementation behind Ralph, review loop, or squad repair paths.
- Journal entry type validation exists as a shell helper under `extension/scripts/bash/validate-journal-entry.sh`, but the Python journal writers in `src/harness/squad.py` and `src/harness/squad_executors.py` only check that entries are dicts before appending.

## Feedback / Ralph Loop Assessment

The review-loop concept exists in multiple forms:

- Phase B Ralph loop: `src/harness/ralph.py::RalphController`.
- PR review loop: `src/harness/review_loop.py::ReviewLoopController`.
- Generic bounded repair primitive: `src/harness/repair_loop.py::RepairLoop`.
- Squad transition fallback judgment: `src/harness/squad.py::_judgment_dispatch()`.

This means Echelon has the building blocks for `Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Escalate`, but the primitive is not yet uniformly adopted. The next best improvement is not to invent a new Ralph loop; it is to pilot `RepairLoop` inside one existing path, probably review-loop repair or a deterministic Phase A artifact repair gate.

## Sandboxing Assessment

Sandboxing is materially implemented for Phase B:

- `src/harness/docker_provider.py` provides Docker-backed sandbox execution, resource limits, timeout handling, output truncation, resource stats, network policy hooks, and credential leak checks.
- `src/harness/devcontainer.py`, `src/harness/verify_detection.py`, and `src/harness/app_runtime_detection.py` support environment detection.
- `src/harness/sandbox_suggestion.py` produces an evidence-backed sandbox suggestion report with confidence, strategy, commands, risks, approval point, and fallback path.
- `src/echelon/cli.py` and `src/harness/init.py` surface this during harness initialization.

The important boundary remains: Phase A agent reasoning and skill subprocesses run on the host LLM CLI; Phase B verification runs in Docker. Host-side LLM tool policy now avoids adding unsafe CLI bypass flags unless explicitly configured, but deeper enforcement depends on the selected AI CLI runtime.

## Human-in-the-Loop Assessment

Human-in-the-loop support is real:

- `src/harness/blocked_decision.py` creates typed blocked-decision records and resume metadata.
- `src/echelon/cli.py::_cmd_resume()` records answers and continues.
- `src/echelon/cli.py::_cmd_continue()` now distinguishes active/interrupted retry, failed dispatch retry, human-resume, safe rewind, and manual recovery.
- `src/echelon/cli.py::_cmd_rewind()` supports a narrow safe checkpoint set.
- `src/harness/squad.py` records interrupted phases and blocks deterministic executor failures without marking the phase complete.

The current contract is much clearer after the recent recovery hardening. Remaining risk is coverage: the contract should be model-tested across all terminal statuses and phase-transition combinations, not only the cases that have already failed in practice.

## GitOps and Quality Gates Assessment

GitOps support exists in `src/harness/gitops.py`:

- Mirror clone/fetch and worktree operations.
- Branch creation, commit, push, PR creation, PR updates, promote ready, merge, and cleanup.
- Never-push-default and self-targeting safety.
- Degraded branch-push-only behavior when PR CLIs are unavailable.
- Secret scan before commit via `scan_git_staged()`.

Quality gates exist across Phase A readiness, build verification, spec fulfillment, code review, test guard, and GitOps. The strongest deterministic gates are now in Python. The weaker gates are still the prompt-level role expectations unless backed by a validator.

## RCA Pipeline Assessment

No first-class automated incident/RCA pipeline is implemented in the reviewed source tree. There is a DEBUGGER role for build failures (`extension/agents/build/debugger.md`) and review/bugfix workflows that use root-cause language, but no pipeline for incident intake, logs/metrics/traces, timeline reconstruction, hypothesis testing, corrective actions, and post-incident learning.

This should remain parked as EGR-009 until the separate RCA pipeline source is available. The right next step is integration design from that actual implementation, not creating a parallel Echelon-only RCA pipeline from the old review prompt.

## Team Topologies Assessment

Echelon can be mapped to Team Topologies concepts, but the interaction modes are still implicit:

- Platform-team capabilities: harness, Docker provider, GitOps, role contracts, state validators, MemPalace wing management.
- Enabling-team capabilities: SAGE, GUARDIAN, BENCHMARK, ORACLE, REALIST, AUDITOR, INTERNALIZER.
- Stream-aligned execution roles: IMPLEMENTER, SPECIFIER, TASKER, ARCHITECT, ORCHESTRATOR.
- Complex-subsystem roles: codegen/SOAR pipeline, MemPalace memory, sandbox/runtime detection.

The risk is cognitive load. The system advertises 41 agents in README while 68 agent files exist on disk. That can be okay if many are internal or auxiliary, but the role catalog should be reconciled so users and contributors know which roles are active, routed, deprecated, or spec-kit-only.

## Spec-Kit / Cognitive Squad Assessment

Echelon is closer to spec-first than it was in the original review:

- Phase A produces spec/plan/tasks/constitution artifacts through workflow phases.
- `echelon artifacts` generates `ARTIFACTS.md` for spec folders.
- `echelon verify-spec` and fulfillment reports link implementation back to spec coverage.
- Phase A readiness validation blocks incomplete artifacts before build-ready guidance.
- Polyrepo `targets:` frontmatter is handled in `src/echelon/cli.py::_cmd_harness_run()` before local harness config can short-circuit target dispatch.

The remaining weak point is not absence of spec artifacts; it is traceability quality. More of the workflow graph, transition rules, journal entries, and role outputs should be statically validated as source-of-truth contracts.

## Memory and Internalization Assessment

Memory exists in three forms:

- Codegen memory and MemPalace wing management under `src/codegen/memory/`.
- Durable KB schema validation in `src/codegen/memory/kb_schema_validator.py` and `knowledge-base/kb-schema.md`.
- Prompt-level learning agents under `extension/agents/learning/`.

Memory is partially structured and more trustworthy after EGR-007. The pollution risk is lower for codegen KB writes, but still present for journal entries and prompt-level learning artifacts unless the Python journal writers enforce `extension/workflow/journal-entry-types.yaml` or a generated Python equivalent.

## Developer Experience Assessment

The CLI is much better documented:

- `README.md` includes quick start, typical workflow, active run recovery, execution paths, command table, and harness flow.
- `src/echelon/cli.py::USAGE` distinguishes `continue`, `rewind`, and `resume`.
- `echelon status` is documented as the orientation command.

There is still documentation drift. `README.md` says the terminal CLI invokes Claude with `--dangerously-skip-permissions`, but `src/harness/llm_tool_policy.py`, `src/harness/config.py`, and tests show the current contract is fail-closed: permission-bypass flags are only added when `llm.tool_policy.allow_unsafe_host_execution: true` has an `approval_reason`.

## Production Readiness Risks

| Priority | Risk | Evidence | Assessment |
|---|---|---|---|
| P1 | Whole-workflow contract validation is incomplete. | `PhaseGraph` loads fields but does not validate transition shape; `SquadController._evaluate_transitions()` consumes `condition` and `to` at runtime. | PR #18-style transition mistakes can survive until runtime unless a workflow validator is added. |
| P1 | README/help drift can mislead operators about safety behavior. | `README.md` line describing Claude `--dangerously-skip-permissions`; actual policy in `src/harness/llm_tool_policy.py`. | Operator-visible, easy to fix, and important for trust. |
| P1 | Journal entries are not schema-validated by Python writers. | `extension/scripts/bash/validate-journal-entry.sh` exists; Python writers append dicts in `src/harness/squad.py` and `src/harness/squad_executors.py`. | Allows malformed but syntactically dict-shaped journal entries. |
| P2 | `RepairLoop` exists but existing loops are still bespoke. | `src/harness/repair_loop.py`, `src/harness/ralph.py`, `src/harness/review_loop.py`. | Duplicated loop behavior makes termination and logging harder to standardize. |
| P2 | Role catalog is larger than the public architecture narrative. | README says 41-agent architecture; filesystem has 68 agent files. | Not a runtime bug, but onboarding and maintenance risk. |
| P2 | Legacy shell tests remain outside pytest collection. | `tests/run-all.sh`, `tests/unit/*.sh`, `tests/integration/*.sh`. | Acceptable for integration scripts, but core contract checks should continue moving into Python. |
| P3 | RCA is not first-class in this source tree. | No dedicated incident/RCA workflow under `src/` or `extension/workflow/`. | Accepted risk pending external RCA pipeline integration. |

## Recommended Roadmap

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P1 | EGR-016: Add a workflow-definition validator. | Catches unsupported transition keys, missing `to`, invalid targets, invalid condition expressions, and missing allowlists before a run starts. | `src/harness/workflow_validator.py`, `src/harness/phase_graph.py`, `src/echelon/cli.py`, `tests/kernel/`, `tests/unit/` | Prevents PR #18-class routing defects from becoming runtime surprises. |
| P1 | EGR-017: Fix safety documentation drift. | README currently contradicts the implemented LLM tool-policy contract. | `README.md`, maybe `docs/findings/echelon-grounded-review-register.md` after fix | Operators get correct guidance for configuring unsafe host execution. |
| P1 | EGR-018: Enforce journal-entry schema in Python writers. | Prevents polluted reasoning journals and improves internalization trust. | `src/harness/journal_entry_validator.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`, `extension/workflow/journal-entry-types.yaml`, tests | Durable journal entries become machine-checkable at the actual write boundary. |
| P2 | EGR-019: Pilot `RepairLoop` adoption in one existing loop. | Standardizes bounded critique/repair/re-check semantics and event logging. | `src/harness/review_loop.py` or a focused Phase A artifact repair gate; `src/harness/repair_loop.py` tests | Reduces bespoke retry behavior and improves auditability. |
| P2 | EGR-020: Reconcile role catalog and active-route inventory. | Reduces cognitive load and makes the 41-agent narrative match the source tree. | `README.md`, `extension/extension.yml`, `extension/workflow/definition.yaml`, `docs/` | Clearer contributor and operator model. |
| P2 | EGR-021: Improve extension/deployed-copy drift checks. | Users edit checkout files but terminal CLI may read installed extension copies. | `scripts/bash/dry-run.sh`, `src/echelon/cli.py`, docs | Fewer confusing “fixed in repo but not in run” situations. |
| P2 | EGR-022: Continue migrating core shell contract tests to pytest. | Python tests are easier to collect, parametrize, and run in CI. | `tests/unit/*.sh`, `tests/integration/*.sh`, `tests/kernel/` | Better test portability while keeping true shell integration tests where useful. |
| P3 | EGR-009: Integrate the external RCA pipeline from actual sources. | Adds incident/RCA capability without inventing a duplicate design. | Future integration adapter and workflow files after RCA source is available | Source-grounded RCA pipeline with evidence collection and learning updates. |

## Highest-Value Next Changes

The best next implementation is EGR-016, the workflow-definition validator. The recent consensus-routing issue demonstrated that a workflow change can be conceptually wrong while still looking plausible in YAML. Echelon now validates agent results and state mutations well; the next safety boundary is validating the graph that tells those agents where to go.

The smallest useful version should:

- Load `extension/workflow/definition.yaml` through `PhaseGraph`.
- Verify every transition is an object with only supported keys.
- Require `to` for every transition and ensure it targets a known phase.
- Reject unknown keys such as stale `guard` fields unless explicitly supported.
- Evaluate or parse every `condition` expression enough to reject unsupported syntax.
- Run in tests and optionally in `echelon status` or `echelon run` preflight.

EGR-017 is the quick follow-up: update README so it no longer says unsafe Claude permissions are always used.

## Open Questions

- Should workflow validation be a standalone command, a `dry-run.sh` enhancement, an automatic CLI preflight, or all three?
- Should unknown transition conditions remain a COMMANDER judgment path at runtime, or should all transition syntax be deterministic for routed phases?
- Should journal-entry schema validation block unknown entry types, warn, or allow them with an explicit `schema_warning` entry?
- Which loop should pilot `RepairLoop` first: PR review repair, Phase A artifact repair, or Ralph inner-loop fix/re-verify?
- How should the external RCA pipeline be versioned and integrated: as a new command, a Phase B strategy, or a separate workflow namespace?
