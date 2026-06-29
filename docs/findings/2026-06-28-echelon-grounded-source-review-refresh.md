# Echelon Grounded Source Review

**Review date:** 2026-06-28
**Reviewed HEAD:** `b0aa12a847efca83793c6b7ed7f489e0e8254954`
**Scope:** Full refreshed review against current `main`, using the original Echelon grounded review prompt.

## Executive Summary

Echelon is in a materially better state than the original grounded review and the 2026-06-27 refresh. EGR-001 through EGR-039 are now fixed in source, with EGR-009 intentionally parked as accepted risk pending integration of the separate RCA pipeline from its real sources.

This refresh did not promote a new P0/P1/P2 EGR. The most recent high-risk regressions around Lexicon/spec ownership, prompt tool invocation guessing, SAGE Understanding JSON shape, missing `echelon_result` recovery, and Phase A artifact publication now have deterministic contracts and targeted tests. The remaining work is less about emergency hardening and more about keeping the pipeline matrix, prompt contracts, and external integrations disciplined as new features land.

One operational watch item remains: an LLM can still fail to emit the required final `echelon_result` block after a long or tool-heavy phase. Source now handles that as a retryable dispatch failure (`src/harness/squad_provider.py`, `src/harness/squad.py`, `src/echelon/cli.py`) and the prompts are statically scanned for result/tool contract drift, but the root behavior is still ultimately model output. Do not treat this as resolved by prompts alone; keep watching live runs after extension updates.

## What Exists Today

Echelon is a spec-kit extension plus deterministic Python substrate:

- CLI entrypoint and command dispatch: `src/echelon/cli.py`.
- Thin command wrappers: `extension/commands/*.md`.
- Externalized workflow graph: `extension/workflow/definition.yaml`.
- Per-phase dispatcher contracts: `extension/workflow/phases/*.md`.
- Agent protocols: `extension/agents/**/*.md`.
- Phase A squad orchestration: `src/harness/squad.py`, `src/harness/squad_executors.py`, `src/harness/squad_state.py`, `src/harness/phase_graph.py`.
- Phase B build/verify/PR harness: `src/harness/coordinator.py`, `src/harness/ralph.py`, `src/harness/docker_provider.py`, `src/harness/gitops.py`, `src/harness/review_loop.py`.
- Codegen/SOAR pipeline: `src/codegen/**`.
- Understanding and Lexicon quality tooling: `src/understanding/**`, `src/lexicon/**`.
- Context and memory reconciliation: `src/echelon/context_builder.py`, `src/echelon/context_metadata.py`, `src/echelon/context_reconciliation.py`, `src/codegen/memory/**`.
- Reverse-engineering bridge and vendored CodeGraph runtime: `extension/scripts/node/re/**`.

The living finding register is `docs/findings/echelon-grounded-review-register.md`. It currently tracks 39 EGRs: 38 fixed and 1 accepted-risk item.

## Architecture Map

The actual architecture is explicit and mostly well-separated:

- `src/echelon/cli.py::SKILL_MAP` maps terminal CLI verbs to command files.
- `README.md` documents the two independent execution paths: interactive spec-kit skill invocation and terminal CLI subprocess invocation.
- `extension/workflow/definition.yaml` owns phase graph, transitions, agent assignment, declared outputs, and allowed `state_updates`.
- `src/harness/workflow_validator.py` validates workflow shape, transitions, conditions, actions, outputs, and state-update contracts.
- `src/harness/squad_executors.py` assembles prompts, injects the canonical `echelon_result` contract, validates results before state/journal writes, and applies phase allowlists.
- `src/harness/squad.py` owns Phase A lifecycle, transition evaluation, blocking/interruption handling, and final artifact publication.
- `src/echelon/artifact_index.py` publishes `ARTIFACTS.md` and now includes `requirements.lexicon.md` as a derived requirements index.
- `src/lexicon/source_contract.py` enforces freshness and ID projection from canonical rich `spec.md` into derived `requirements.lexicon.md`.

The main mixed-responsibility module remains `src/echelon/cli.py`. It owns command parsing, status rendering, run recovery, resume/rewind/continue behavior, artifact helpers, drift warning display, and subprocess skill invocation. This remains a maintainability risk, but current high-risk paths have targeted tests.

## Agent Role Inventory

The role surface is documented rather than inferred:

| Layer | Evidence | Representative roles | Assessment |
|---|---|---|---|
| Control | `extension/agents/control/*.md` | COMMANDER, CHIEF, SCOREKEEPER, STRATEGIST, TRACKER | Central coordination and governance. COMMANDER is still the conceptual dispatcher, but Python is the deterministic state writer. |
| Exploration | `extension/agents/exploration/*.md` | SCOUT, SYNTHESIZER, MODELER, CARTOGRAPHER, SAGE, GOLDDIGGER | Main Phase 1 understanding surface. Tool contracts are stronger after EGR-036 through EGR-038. |
| Feasibility | `extension/agents/feasibility/*.md` | GATEKEEPER, VALIDATOR | Feasibility and structural quality checks. |
| Solution | `extension/agents/solution/*.md` | ARCHITECT, ORCHESTRATOR, SENTINEL | Architecture, test strategy, task planning, and consensus support. |
| Specialists | `extension/agents/specialists/*.md` | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK | Conditional specialist consultation. GUARDIAN config naming is reconciled around `specialists.guardian_mode`. |
| Learning | `extension/agents/learning/*.md` | AUDITOR, REALIST, MIRROR, INTERNALIZER, VETERAN | Partly prompt-level, partly backed by deterministic memory validation. |
| Build | `extension/agents/build/*.md` | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, VERIFICATION | Phase B/build quality gates and repair. |
| Reverse engineering | `extension/agents/re/*.md` | ANALYZER, SPECIFIER, VERIFIER, CONSTITUTER, TASKER | Brownfield extraction/spec reconstruction. CodeGraph vendor contract is now explicit. |

Role output contracts are enforced by `src/harness/role_contracts.py`, `src/harness/echelon_result_schema.py`, `src/harness/journal_entry_validator.py`, `src/harness/verdict_contract_validator.py`, and static prompt tests.

## Triadic Model Assessment

| Stage | Implementation evidence | Inputs | Outputs | Enforcement |
|---|---|---|---|---|
| UNDERSTAND | `phase1-*` workflow nodes, exploration agents, Understanding/Lexicon tooling | User request, repo evidence, context packs, prior canonical specs, MemPalace reconciliation | `spec.md`, `requirements.lexicon.md`, constitution, discovery artifacts, quality gates, journal entries | Stronger than before: result validation, prompt tool contracts, Lexicon source-ref checks, artifact publication, and static prompt scanners all apply. |
| REASON | `phase2-*`, `phase3-*`, `src/harness/condition_evaluator.py`, `src/harness/workflow_validator.py` | Understanding artifacts, feasibility state, architecture/test/task context, specialist outputs | architecture artifacts, plan, tasks, risk/dependency/test artifacts, checkpoint decisions | Enforced by workflow transition validation, verdict-contract validation, state allowlists, and Phase A readiness checks. |
| INTERNALIZE | `src/codegen/memory/**`, `src/echelon/context_builder.py`, `src/echelon/context_reconciliation.py`, `extension/agents/learning/**` | Published canonical specs, memory drawers, run summaries, KB records | context packs, reconciled memory, validated KB records, queue-driven re-extraction | Real but uneven. Codegen memory and context reconciliation are functional; some learning roles remain prompt-level capabilities. |

Internalization is not just a label anymore, but it is still not uniformly applied across all paths.

## Harness Programming Assessment

Implemented harness capabilities include:

- Structured Phase A lifecycle with deterministic blocking and continuation in `src/harness/squad.py` and `src/echelon/cli.py`.
- Required final `echelon_result` extraction/validation in `src/harness/squad_provider.py` and `src/harness/echelon_result_schema.py`.
- Retryable missing-result recovery through `_classify_run_recovery()` and `_last_incomplete_dispatch_phase()` in `src/echelon/cli.py`.
- Per-phase `state_updates` allowlists loaded from `extension/workflow/definition.yaml`.
- Canonical journal entry validation and quarantine in `src/harness/journal_entry_validator.py`.
- Prompt-level executable tool contract scanning in `tests/contract/prompt_tool_contracts.py`.
- Deterministic workflow validation in `src/harness/workflow_validator.py`.
- Phase A artifact readiness and publication in `src/harness/phase_a_readiness.py`, `src/harness/squad.py`, and `src/echelon/artifact_index.py`.
- Phase B Docker verification, GitOps, PR flow, review loop, and secret scan in `src/harness/**`.

The harness can now reject malformed or missing results, block unsafe state writes, and guide retry/rewind/resume flows. It still cannot force an external LLM to produce the final block; it can only constrain prompts, validate output, and recover deterministically.

## Feedback / Ralph Loop Assessment

Feedback loops exist in multiple layers:

- `src/harness/repair_loop.py` provides a bounded generic repair primitive.
- `src/harness/coordinator.py` uses the repair primitive for the Phase 3 review-fix/re-entry cycle.
- `src/harness/ralph.py` owns build-loop behavior.
- `src/harness/review_loop.py` owns PR review polling and repair task creation.

The pattern is now closer to:

```text
Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Escalate
```

Not every loop has been collapsed into `RepairLoop`, but the most important coordinator-owned review re-entry path has been adopted.

## Sandboxing Assessment

Sandboxing exists for Phase B:

- Docker worktree execution: `src/harness/docker_provider.py`.
- Sandbox suggestion: `src/harness/sandbox_suggestion.py`.
- Runtime/dependency detection: `src/harness/verify_detection.py`, `src/harness/app_runtime_detection.py`, `src/harness/devcontainer.py`.
- Host LLM permission policy: `src/harness/llm_tool_policy.py`.

Phase A still executes host-side LLM subprocesses. The deterministic substrate gates known unsafe CLI bypass flags, but true file/network/tool isolation ultimately depends on the selected external AI CLI runtime.

## Human-in-the-Loop Assessment

The human-in-loop model is functional:

- Blocked decisions: `src/harness/blocked_decision.py`.
- Resume handling: `src/echelon/cli.py::_cmd_resume()`.
- Continue classification: `src/echelon/cli.py::_classify_run_recovery()`.
- Rewind checkpoints: `src/echelon/cli.py::_cmd_rewind()`.
- Interrupted dispatch persistence: `src/harness/squad.py`.

The source now distinguishes:

- `resume`: answer a human gate.
- `continue`: advance or retry without new input.
- `rewind`: reset to a safe checkpoint before continuing.

The live UX can still look odd when `echelon continue` ends in a retryable blocked state that also suggests `echelon continue`. That is not a contract violation in source; it reflects the command being both the executor and the retry command. If this continues to confuse users, it should become a UX-focused EGR, not a correctness EGR.

## GitOps and Quality Gates Assessment

GitOps and quality gates are materially stronger than in the first review:

- GitOps manager: `src/harness/gitops.py`.
- Secret scan gate: `src/harness/secret_scan.py`.
- Phase A readiness: `src/harness/phase_a_readiness.py`.
- Lexicon derived-artifact freshness and ID projection: `src/lexicon/source_contract.py`.
- Workflow/role/verdict/prompt static contracts: `src/harness/workflow_validator.py`, `src/harness/role_contracts.py`, `src/harness/verdict_contract_validator.py`, `tests/contract/static_contracts.py`, `tests/contract/prompt_tool_contracts.py`.
- RUNNABLE wording now matches implemented static composition evidence in `extension/workflow/phases/codegen-6c-runnable.md` and related tests.

The current quality-gate concern is not absence of gates. It is keeping newly added pipeline surfaces connected to these existing gates.

## RCA Pipeline Assessment

No first-class RCA pipeline exists in this source tree. There are bugfix, debugging, review, and learning mechanisms, but no dedicated incident intake, evidence collection, timeline reconstruction, hypothesis testing, corrective/preventive action tracking, or RCA knowledge update workflow.

This remains EGR-009 and stays accepted-risk until the separate RCA pipeline is integrated from its real source tree.

## Team Topologies Assessment

Echelon maps reasonably to Team Topologies:

- Platform capabilities: harness, Docker provider, GitOps, workflow validator, role contracts, Lexicon validation, MemPalace wing handling.
- Enabling capabilities: SAGE, GUARDIAN, BENCHMARK, ORACLE, AUDITOR, REALIST.
- Stream-aligned roles: CARTOGRAPHER, ARCHITECT, ORCHESTRATOR, IMPLEMENTER, SPECIFIER, TASKER.
- Complex subsystem capabilities: SOAR/codegen, MemPalace, RE CodeGraph, polyrepo orchestration.

The current cognitive-load risk is no longer raw role count; it is pipeline multiplication. The spec pipeline, Lexicon derived artifact, build harness, codegen/SOAR path, and RE path need continued pipeline-matrix discipline.

## Spec-Kit / Cognitive Squad Assessment

The current intended contract is:

- `spec.md` is the canonical rich spec-kit feature specification.
- `requirements.lexicon.md` is a derived validation/index artifact compiled from `spec.md`.
- `plan.md` and `tasks.md` consume canonical spec semantics and may use Lexicon IDs for deterministic traceability.
- `ARTIFACTS.md` describes published artifacts for users and downstream build paths.
- `lexicon validate --source-ref spec.md` proves the derived artifact is fresh and does not invent/drop requirement, acceptance, or error IDs.

This contract is now represented in `extension/echelon-config.yml`, `extension/config-template.yml`, `extension/workflow/phases/phase1-what.md`, `extension/agents/exploration/cartographer.md`, `extension/agents/solution/orchestrator.md`, `docs/pipeline-matrix.md`, `src/echelon/artifact_index.py`, `src/lexicon/source_contract.py`, and related tests.

## Memory and Internalization Assessment

What Echelon remembers today:

- Canonical feature metadata for finalized specs through `src/echelon/context_metadata.py`.
- Prior/current context packs through `src/echelon/context_builder.py`.
- Reconciled MemPalace drawers through `src/echelon/context_reconciliation.py`.
- Codegen memory records under `src/codegen/memory/**`.
- Validated durable KB records through `src/codegen/memory/kb_schema_validator.py`.

Memory trust improved after EGR-035: stale or out-of-project memory drawers can be rejected before entering prompt context. Failed attempts and human decisions are still more fragmented across run state, journal entries, and learning prompts than a mature production audit trail would ideally provide.

## Developer Experience Assessment

Developer UX improved:

- `README.md` explains the two execution paths and the Phase A/Phase B split.
- `src/echelon/cli.py::USAGE` distinguishes `continue`, `rewind`, and `resume`.
- `echelon status` derives roadmap state from `extension/workflow/definition.yaml`.
- `echelon status/run/continue/resume` warn about installed-extension drift via `src/harness/extension_drift.py`.
- Banner rendering now wraps instead of truncating long messages in the normal 78-column style.

Remaining DX pressure:

- The user-facing command surface is broad.
- `src/echelon/cli.py` is still large.
- Some recovery guidance is technically correct but still cognitively awkward, especially retryable blocked states that recommend running `continue` again.

## Production Readiness Risks

| Priority | Risk | Evidence | Status |
|---|---|---|---|
| P1 | Malformed/missing agent result can corrupt state or produce misleading continuation. | `src/harness/echelon_result_schema.py`, `src/harness/squad_provider.py`, `src/harness/squad.py`, `src/echelon/cli.py`. | Fixed through EGR-001, EGR-015, EGR-027, EGR-039. |
| P1 | Prompt-level tool guessing can break validation flows. | `tests/contract/prompt_tool_contracts.py`, `tests/contract/static_contracts.py`, CARTOGRAPHER/SAGE prompt contracts. | Fixed through EGR-036, EGR-037, EGR-038; keep scanning. |
| P1 | Lexicon/spec artifact ownership drift can destroy rich spec output. | `src/lexicon/source_contract.py`, `src/echelon/artifact_index.py`, `docs/pipeline-matrix.md`. | Fixed through EGR-030 and EGR-033. |
| P2 | CLI module concentration creates future regression risk. | `src/echelon/cli.py`. | Open maintainability risk; not a new EGR in this pass. |
| P2 | Pipeline-matrix drift can return when new pipelines land. | `docs/pipeline-matrix.md`, workflow phase specs, config templates. | Watch item. |
| P3 | RCA remains out of tree. | No dedicated RCA workflow in `src/` or `extension/workflow/`. | EGR-009 accepted-risk. |

## Recommended Roadmap

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P3 | EGR-009: Integrate the external RCA pipeline from source. | Adds incident/RCA capability without inventing duplicate behavior. | Future RCA integration adapter, workflow namespace, docs/tests after source is available. | Source-grounded RCA flow tied into Echelon. |
| P2 | Keep prompt tool-contract scanning mandatory for agent/phase changes. | Prevents recurring command guessing in live LLM phases. | `tests/contract/prompt_tool_contracts.py`, `tests/unit/test_prompt_tool_contracts.py`, affected prompts. | Fewer live tool-contract regressions. |
| P2 | Consider splitting `src/echelon/cli.py` recovery/status helpers into focused modules. | Reduces future accidental coupling in continue/resume/rewind/status behavior. | `src/echelon/cli.py`, new `src/echelon/recovery.py` or `src/echelon/status.py`, existing CLI tests. | Better maintainability without changing CLI UX. |
| P2 | Add a UX-focused recovery wording pass if users keep hitting `continue -> continue` loops. | The behavior is currently correct but can read as nonsense during blocked retries. | `src/echelon/cli.py`, `tests/unit/test_cli_next_step_escalation.py`. | Clearer operator guidance. |

## Highest-Value Next Changes

The highest-value next move is not a new source fix; it is operational validation:

1. Update a test project to the current installed extension.
2. Re-run the recently failing `run -> resume -> continue` path.
3. Confirm that `missing_echelon_result` blocks now route to the failed `last_dispatch.phase_id`.
4. Confirm SAGE still emits valid final `echelon_result` blocks with the current Understanding/Lexicon prompt contracts.

If SAGE continues to miss final result blocks after the installed extension is current, file the next EGR against that specific phase/output contract with raw-output evidence and source-grounded prompt gaps.

## Open Questions

- When will the separate RCA pipeline source be available for EGR-009 integration?
- Should recovery UX treat retryable blocked states with a distinct command label such as "retry" while still executing through `echelon continue` internally?
- Should `src/echelon/cli.py` be decomposed before the next large recovery/status feature lands?
- Should repeated model failure to emit `echelon_result` after long tool output become a deterministic compaction/output-budget EGR if it recurs under current prompts?
