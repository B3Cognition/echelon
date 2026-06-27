# Echelon Grounded Source Review

**Review date:** 2026-06-27
**Reviewed HEAD:** `e7656ae2cba07674a72ba5fbe29976ee0178705c`
**Scope:** Full refreshed review against current `main`, using the original Echelon grounded review prompt.

## Executive Summary

Echelon's core safety posture is materially stronger than in the original grounded review. The previous high-priority issues around result validation, state mutation, continuation recovery, Phase A artifact publication, Lexicon/spec contract drift, workflow transition validation, GitOps secret scanning, sandbox suggestion, and host LLM tool-policy bypass now have source-level fixes and tests. The best evidence remains in `src/harness/echelon_result_schema.py`, `src/harness/workflow_validator.py`, `src/harness/squad.py`, `src/harness/squad_executors.py`, `src/harness/phase_a_readiness.py`, `src/harness/llm_tool_policy.py`, `src/harness/secret_scan.py`, `src/echelon/cli.py`, `src/echelon/artifact_index.py`, and `src/understanding/lexicon.py`.

The refreshed review did not find a new P0. The main new P1 is in the reverse-engineering CodeGraph bridge: Echelon executes a vendored JavaScript CodeGraph distribution from `extension/scripts/node/re/vendor/codegraph/dist`, but the vendored bundle does not have a deterministic provenance/version/integrity contract in the source tree. This is a supply-chain and drift risk because the bridge runs over user repositories during RE analysis, while the adapter, install script, and tests currently protect only parts of the integration wiring.

EGR-009 remains intentionally parked. There is still no first-class RCA pipeline in this source tree, and the user confirmed a separate RCA pipeline exists and should be integrated from its real sources later.

## What Exists Today

Echelon is a spec-kit extension plus Python substrate:

- CLI entrypoint and command dispatch: `src/echelon/cli.py`.
- Workflow graph and phase contracts: `extension/workflow/definition.yaml` with 37 phases.
- Agent prompts: 68 markdown files under `extension/agents/`.
- Registered role catalog: `docs/agent-role-catalog.md` reconciles 53 registered agent roles, 45 active-routed roles, 8 manifest-only roles, 1 workflow-only alias, and 15 support prompt files.
- Thin command wrappers: 41 markdown command files under `extension/commands/`.
- Phase A squad orchestration: `src/harness/squad.py`, `src/harness/squad_executors.py`, `src/harness/squad_state.py`, `src/harness/phase_graph.py`.
- Phase B build/verify/PR harness: `src/harness/coordinator.py`, `src/harness/ralph.py`, `src/harness/docker_provider.py`, `src/harness/gitops.py`, `src/harness/review_loop.py`, `src/harness/state.py`.
- Codegen/SOAR pipeline: `src/codegen/**`.
- Requirements quality and Lexicon validation: `src/understanding/**`.
- Memory/internalization substrate: `src/codegen/memory/**`, `knowledge-base/kb-schema.md`, and learning agents under `extension/agents/learning/`.
- RE CodeGraph bridge: `extension/scripts/node/re/**`, including a vendored CodeGraph dist under `extension/scripts/node/re/vendor/codegraph/`.

The test suite is broad. `pyproject.toml` configures pytest; `tests/run-all.sh` still coordinates pytest plus legacy shell/integration checks where shell behavior matters.

## Architecture Map

The architecture is explicit:

- `src/echelon/cli.py::SKILL_MAP` maps CLI verbs to command files.
- `src/echelon/cli.py::USAGE` documents `run`, `status`, `continue`, `rewind`, `resume`, `artifacts`, `land`, harness commands, and spec target commands.
- `README.md` documents the two independent execution paths: interactive spec-kit skill invocation and terminal CLI subprocess invocation.
- `extension/workflow/definition.yaml` owns routed phase graph, transitions, agents, outputs, and allowed state updates.
- `src/harness/phase_graph.py::PhaseGraph` loads workflow phase nodes.
- `src/harness/workflow_validator.py` validates transition shape, supported keys, target phases, conditions, actions, and state-update blocks.
- `src/harness/squad.py::SquadController` owns Phase A execution, transition evaluation, interrupted-run persistence, terminal blocking, and final artifact publication.
- `src/harness/squad_executors.py` owns phase executor implementations, prompt assembly, result validation, state writes, and journal writes.
- `src/harness/coordinator.py::StrategyCoordinator` owns Phase B strategy fanout and Ralph/review-loop integration.

The remaining mixed-responsibility area is `src/echelon/cli.py`, which still combines CLI parsing, recovery UX, status rendering, skill subprocess invocation, harness command dispatch, and artifact helpers. It is acceptable today because tests cover the highest-risk paths, but it remains a future maintainability pressure point.

## Agent Role Inventory

The active role inventory is now documented rather than inferred. `docs/agent-role-catalog.md` is the current reconciliation point.

| Layer | Evidence | Representative roles | Assessment |
|---|---|---|---|
| Control | `extension/agents/control/*.md` | COMMANDER, CHIEF, SCOREKEEPER, STRATEGIST, TRACKER | Central coordination and governance roles. COMMANDER remains the key state writer by contract. |
| Exploration | `extension/agents/exploration/*.md` | SCOUT, GOLDDIGGER, SYNTHESIZER, CARTOGRAPHER, SAGE, MODELER | Phase 1 understanding and brownfield discovery. |
| Feasibility | `extension/agents/feasibility/*.md` | GATEKEEPER, VALIDATOR | Feasibility and structural checks. |
| Solution | `extension/agents/solution/*.md` | ARCHITECT, ORCHESTRATOR, SENTINEL | Architecture, planning, and risk pass. |
| Specialists | `extension/agents/specialists/*.md` | INVESTIGATOR, GUARDIAN, BENCHMARK, ADVOCATE, ORACLE, MAVERICK | Conditional specialist consultation. |
| Learning | `extension/agents/learning/*.md` | AUDITOR, REALIST, MIRROR, INTERNALIZER, VETERAN | Partly active-routed, partly registered platform capability. |
| Build | `extension/agents/build/*.md` | IMPLEMENTER, SPEC GUARD, CODE REVIEWER, TEST GUARDIAN, DEBUGGER, VERIFICATION | Phase B/build quality gates and repair paths. |
| Reverse engineering | `extension/agents/re/*.md` | RE-ANALYZER, RE-SPECIFIER, RE-VERIFIER, RE-CONSTITUTER, RE-TASKER | Brownfield extraction and spec reconstruction. |

Role output contracts are much stronger than in the original review. `src/harness/role_contracts.py`, `src/harness/echelon_result_schema.py`, `src/harness/journal_entry_validator.py`, and `src/harness/workflow_validator.py` now cover the main machine-checkable surfaces.

## Triadic Model Assessment

| Stage | Implementation evidence | Inputs | Outputs | Enforcement assessment |
|---|---|---|---|---|
| UNDERSTAND | `phase1-*` nodes in `extension/workflow/definition.yaml`, phase specs under `extension/workflow/phases/`, exploration/control agents | User request, repo evidence, discovery templates, RE outputs, prior state | `spec.md`, `requirements.lexicon.md`, constitution, discovery artifacts, quality scores, journal entries | Substantially enforced by workflow validation, result schemas, state allowlists, artifact publication, and Lexicon source-ref validation. |
| REASON | `phase2-*`, `phase3-how`, `phase3-specialists`, `phase3-sentinel`, `phase3-plan`, `phase3-consensus`; `src/harness/condition_evaluator.py`; `src/harness/squad.py` | Understanding artifacts, feasibility state, constitution, Lexicon projection, specialist outputs | Architecture, plan, tasks, consensus/checkpoint verdicts | Explicit and much better guarded after EGR-025 through EGR-033. |
| INTERNALIZE | `extension/agents/learning/*`, `src/codegen/memory/*`, `src/codegen/memory/kb_schema_validator.py`, `knowledge-base/kb-schema.md` | Run outputs, durable patterns, pitfalls, feedback, requirements memory | Validated KB records, MemPalace memory, learning artifacts | Real but uneven. Codegen memory is functional; Phase A learning remains partly prompt-level. |

Internalization is no longer just a conceptual label. It has real code in the codegen memory and KB validation paths. It is not yet uniformly applied across all Echelon workflows.

## Harness Programming Assessment

Implemented capabilities:

- Structured Phase A lifecycle in `src/harness/squad.py`.
- Deterministic `echelon_result` validation in `src/harness/echelon_result_schema.py`.
- Workflow graph validation in `src/harness/workflow_validator.py`.
- Per-phase state-update allowlists through `extension/workflow/definition.yaml`, `src/harness/phase_graph.py`, and runtime writers.
- Python journal validation/quarantine through `src/harness/journal_entry_validator.py`.
- Continuation, rewind, resume, blocked-decision, interrupted-run, and done-but-unpublished recovery paths in `src/echelon/cli.py`.
- Phase A readiness and final artifact publication in `src/harness/phase_a_readiness.py`, `src/harness/squad.py`, and `src/echelon/artifact_index.py`.
- Phase B Docker verification, worktree handling, GitOps commit/push/PR, and secret scanning in `src/harness/docker_provider.py`, `src/harness/gitops.py`, and `src/harness/secret_scan.py`.
- Reusable repair primitive in `src/harness/repair_loop.py`, already adopted in the coordinator-owned Phase 3 review-fix/re-entry cycle.

The main remaining harness gap found in this refresh is the RE CodeGraph dependency contract. The bridge is deterministic code, but its vendored executable dependency is not represented with enough provenance and version-integrity metadata.

## Feedback / Ralph Loop Assessment

The Ralph/review-loop pattern exists in several forms:

- Build Ralph loop: `src/harness/ralph.py`.
- Review loop: `src/harness/review_loop.py`.
- Generic bounded repair primitive: `src/harness/repair_loop.py`.
- Coordinator review-fix/re-entry path: `src/harness/coordinator.py`.

The model is now closer to `Draft output -> Critique -> Repair -> Re-check -> Accept / Block / Escalate`, but not every historical loop has been unified under `RepairLoop`. This is no longer the top backlog item because the highest-risk integration path has one adoption point.

## Sandboxing Assessment

Sandboxing is implemented for Phase B:

- `src/harness/docker_provider.py` owns Docker-backed execution, timeouts, output limits, resource stats, cleanup, and credential leak checks.
- `src/harness/devcontainer.py`, `src/harness/verify_detection.py`, and `src/harness/app_runtime_detection.py` support environment detection.
- `src/harness/sandbox_suggestion.py` produces evidence-backed sandbox suggestions with confidence, strategy, commands, risks, approval point, and fallback.
- `src/harness/llm_tool_policy.py` prevents unsafe host LLM permission-bypass flags unless explicitly configured with approval metadata.

The boundary is still important: Phase A reasoning and selected LLM subprocesses run on the host; Phase B verification runs in Docker. Echelon's own policy is fail-closed, but final tool enforcement depends on the selected external AI CLI.

## Human-in-the-Loop Assessment

Human-in-the-loop support is real:

- Typed blocked decisions and resume metadata: `src/harness/blocked_decision.py`.
- Resume answer recording and continuation: `src/echelon/cli.py::_cmd_resume()`.
- Continue recovery across active, interrupted, failed, blocked, unpublished, and done states: `src/echelon/cli.py::_cmd_continue()`.
- Safe checkpoint rewind: `src/echelon/cli.py::_cmd_rewind()`.
- Interrupted dispatch persistence and blocking without false completion: `src/harness/squad.py`.

The recent EGR-027/EGR-029 work addressed the observed "continue into the wrong phase" and stale artifact publication problems. The remaining UX backlog from live use is lower priority: clearer guidance when a continued run ends in another non-terminal state.

## GitOps and Quality Gates Assessment

GitOps support is implemented in `src/harness/gitops.py`:

- Mirror clone/fetch and worktrees.
- Branch creation, commit, push, PR creation, PR updates, ready promotion, merge, and cleanup.
- Default-branch/self-targeting safety.
- Degraded branch-push-only behavior when PR tooling is unavailable.
- Staged-file secret scan before commit through `src/harness/secret_scan.py`.

Quality gates now exist across Phase A readiness, build verification, Lexicon freshness/ID projection, spec fulfillment, code review, test guard, and GitOps. The new gap is not missing GitOps gates; it is dependency provenance for a vendored RE executable dependency.

## RCA Pipeline Assessment

No first-class automated incident/RCA pipeline is implemented in this source tree. There are debugging, review, and bugfix flows, but no dedicated incident intake, evidence collection, timeline reconstruction, symptom clustering, hypothesis testing, corrective-action tracking, or post-incident learning pipeline.

This remains EGR-009 and stays parked until the separate RCA pipeline can be integrated from its actual sources.

## Team Topologies Assessment

Echelon maps reasonably to Team Topologies concepts:

- Platform capabilities: harness, Docker provider, GitOps, workflow validator, role contracts, Lexicon validation, MemPalace wing management.
- Enabling capabilities: SAGE, GUARDIAN, BENCHMARK, ORACLE, AUDITOR, REALIST.
- Stream-aligned execution roles: IMPLEMENTER, SPECIFIER, TASKER, ARCHITECT, ORCHESTRATOR.
- Complex subsystem capabilities: SOAR/codegen, MemPalace, RE CodeGraph bridge, polyrepo orchestration.

The role catalog cleanup reduced cognitive load. The next Team Topologies risk is not role count; it is overlapping pipeline surfaces: standard spec pipeline, Lexicon derived artifact, standard build harness, codegen/SOAR build path, and RE pipeline need explicit pipeline-matrix documentation and contract tests as they evolve.

## Spec-Kit / Cognitive Squad Assessment

The workflow is now meaningfully spec-first:

- `spec.md` remains the canonical rich spec-kit feature specification.
- `requirements.lexicon.md` is a deterministic derived requirements index, not a replacement for `spec.md`.
- `lexicon validate --source-ref spec.md` enforces freshness and REQ/AC/ERROR ID projection.
- `plan.md` and `tasks.md` are produced downstream and should reference the canonical spec plus Lexicon IDs where useful.
- `ARTIFACTS.md` is generated by `src/echelon/artifact_index.py` and now includes derived artifacts.
- Phase 4 publishes run-local Phase A artifacts to project-visible spec directories before build-ready guidance.

The current contract between `spec.md`, `requirements.lexicon.md`, `plan.md`, and `tasks.md` is much clearer after EGR-030 and EGR-033. Future changes should preserve `spec.md` as semantic source of truth and avoid letting derived artifacts become parallel truth surfaces.

## Memory and Internalization Assessment

Memory exists in three forms:

- Codegen memory and MemPalace wing management under `src/codegen/memory/`.
- Durable KB schema validation in `src/codegen/memory/kb_schema_validator.py` and `knowledge-base/kb-schema.md`.
- Prompt-level learning agents under `extension/agents/learning/`.

Memory is partially structured and more trustworthy than in the first review. The primary remaining memory risk is scope and reuse consistency, not raw absence of storage. RCA integration should eventually write validated learning records through the same durable schema boundary.

## Developer Experience Assessment

The CLI and docs are materially better:

- `README.md` documents quick start, terminal/interactive execution paths, recovery commands, harness flow, and the dual-artifact spec/Lexicon model.
- `src/echelon/cli.py::USAGE` distinguishes `continue`, `rewind`, and `resume`.
- `echelon status` derives the roadmap from `extension/workflow/definition.yaml` instead of a stale hardcoded list.
- Terminal drift warnings help users notice when installed extension files differ from checkout sources.
- Box rendering was updated to wrap long text at a wider terminal-oriented width.

The main DX risk is now pipeline multiplication. The docs should keep `docs/pipeline-matrix.md`, README, and command help aligned whenever a new spec/build/RE path is added.

## Production Readiness Risks

| Priority | Risk | Evidence | Assessment |
|---|---|---|---|
| P1 | Vendored RE CodeGraph dist lacks deterministic provenance/version/integrity contract. | `extension/scripts/node/re/codegraph-adapter.js` imports `./vendor/codegraph/dist/index`; `extension/scripts/node/re/vendor/codegraph/package.json` reports `@colbymchenry/codegraph` `0.7.2`; 290 tracked dist files are vendored; no vendor lockfile/LICENSE/NOTICE was found under the vendored package at shallow depth; tests only assert install wiring and optional global CLI version `1.0.1`. | New EGR-034. Supply-chain, version drift, and maintainability risk for code that executes over user repos. |
| P2 | Repair-loop standardization remains partial. | `src/harness/repair_loop.py`, `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/coordinator.py`. | Reduced risk after EGR-019, but still not uniform. |
| P2 | CLI module remains broad. | `src/echelon/cli.py` owns many unrelated surfaces. | Maintainability risk, not an immediate correctness issue. |
| P2 | Pipeline-matrix drift can return as features are added. | Recent EGR-030/EGR-033 and `docs/pipeline-matrix.md`. | Needs ongoing contract tests and doc updates. |
| P3 | RCA remains out of tree. | No dedicated RCA workflow under `src/` or `extension/workflow/`; EGR-009 accepted risk. | Deferred pending external pipeline integration. |

## Recommended Roadmap

| Priority | Recommendation | Why it matters | Suggested files/modules to change | Expected impact |
|---|---|---|---|---|
| P1 | EGR-034: Add a deterministic RE CodeGraph vendor/dependency contract. | The RE bridge executes vendored JS over user repositories; provenance, version, license, and integrity should be explicit and testable. | `extension/scripts/node/re/vendor/codegraph/`, `extension/scripts/node/re/package.json`, `extension/scripts/node/re/codegraph-adapter.js`, `scripts/install.sh`, `tests/kernel/test_codegraph_integration_contract.py`, new manifest/test as needed | Reduces supply-chain and drift risk; makes future CodeGraph upgrades deliberate. |
| P2 | Continue standardizing repair loops where they still matter. | Keeps bounded retry, termination, and logging semantics consistent. | `src/harness/ralph.py`, `src/harness/review_loop.py`, `src/harness/repair_loop.py` | Fewer bespoke loop behaviors. |
| P2 | Keep pipeline-matrix contract tests current. | Prevents a repeat of spec/Lexicon/task/plan contract drift. | `docs/pipeline-matrix.md`, `tests/contract/static_contracts.py`, README/phase prompts | Easier operator and contributor understanding. |
| P3 | EGR-009: Integrate external RCA pipeline from source. | Adds RCA capability without inventing duplicate behavior. | Future RCA integration adapter, workflow namespace, docs/tests after source is available | Source-grounded RCA flow tied into Echelon. |

## Highest-Value Next Changes

The highest-value next implementation is EGR-034.

The smallest useful fix should:

- Add an explicit vendor manifest for `extension/scripts/node/re/vendor/codegraph` with package name, version, source, license, expected package hash or dist hash, and update procedure.
- Add tests asserting the adapter imports the expected vendored package, the vendored package version matches the manifest, and the license/provenance files exist.
- Resolve or document the version split between optional global `CODEGRAPH_CLI_VERSION="1.0.1"` in `scripts/install.sh` and vendored `@colbymchenry/codegraph` `0.7.2`.
- Decide whether the bridge should continue vendoring dist files or move to a normal pinned npm dependency once the package is public and stable enough.

This should be addressed before more RE behavior is built on top of the current bridge, because every follow-on RE feature will otherwise inherit an underspecified executable dependency boundary.

## Open Questions

- Should the RE bridge continue to vendor CodeGraph, or should it depend on a pinned npm package through `package-lock.json`?
- If vendoring continues, what hash granularity is acceptable: full directory hash, npm tarball integrity, or per-file manifest?
- Should Echelon require Node 20 for the RE bridge because `commander@14` declares `node >=20`, or should the dependency be pinned to preserve Node 18 compatibility with the bridge runtime guard?
- Should EGR-009 remain accepted-risk until the external RCA pipeline is checked into this repo, or should there be a separate integration-design EGR earlier?
