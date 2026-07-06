# Evolution of Echelon

This document is a meetup-ready narrative of how Echelon evolved. It is intentionally different from the technical dossier: the dossier inventories the current system; this document explains the path from the initial idea to the current architecture.

The short version: Echelon started as a prompt-heavy cognitive squad. Over time, every important failure mode pushed more responsibility into explicit workflow graphs, structured outputs, deterministic Python, state machines, workspaces, and verification gates. The result is not just "more agents." It is a system that moved from prompt engineering toward context engineering, harness engineering, and loop engineering.

## Executive Narrative

The initial version of Echelon was a Cognitive Agent Squad extension. It decomposed AI-assisted software work into specialized roles: discovery, requirements, critique, feasibility, planning, implementation, verification, and learning. The early architecture treated the LLM as the central coordinator: a MANAGER or COMMANDER-style role loaded prompts, dispatched agents, interpreted results, and advanced the workflow.

That worked well enough to prove the core idea: one general AI assistant was not the right unit of design for software delivery. Different parts of the job need different responsibilities, evidence standards, and output formats. But the first versions also exposed the central problem: LLMs are useful reasoners, but weak owners of mandatory state transitions, durable memory, and safety-critical decisions.

Echelon then evolved in layers.

First, the prompt layer became more structured. Agents were renamed, grouped into layers, assigned explicit roles, and made responsible for structured `echelon_result` output rather than loose prose. Understanding CLI was integrated as a requirements-quality gate, making quality less subjective. Knowledge-base files and evolution signals were added so the system could learn from runs.

Second, context moved out of the chat transcript. Echelon added workflow definitions, phase files, reasoning journals, artifact indexes, run directories, and state JSON. This was the context-engineering turn: instead of hoping the active model window remembered the workflow, commands could reconstruct state from files.

Third, orchestration moved out of LLM judgment. The project externalized workflows into `extension/workflow/definition.yaml` and phase specs, then added Python-owned routing, state validation, journal writing, recovery, phase replay, and safe rewind. The LLM still performs semantic work, but Python increasingly decides whether a phase can advance, retry, block, or recover.

Fourth, Echelon grew a build and delivery harness. The harness added isolated worktrees, Docker-compatible sandbox verification, GitOps, PR loops, review reentry, fulfillment checks, and land gates. This turned "the agent implemented it" into an evidence-based loop: build, verify, feed back failures, fix, re-verify, open PR, handle review, prove fulfillment, and land.

Finally, the current version tightened contracts around machine-readable requirements, project topology, provider execution, and technology-stack guidance. Lexicon adds controlled grammar validation as a derived artifact beside human-readable `spec.md`. The workspace/source-root model makes single-repo, polyrepo, and planning-only layouts explicit. The AI CLI backend layer isolates Claude, Codex, GitHub Copilot, and Opencode behavior. Echelon Stacks add schema-backed, opt-in technology capability context with deterministic preflight and brownfield stack detection. Current README state identifies version 3.0.0, 54 registered agent roles, 46 active-routed manifest roles, Understanding gates, MemPalace/codegen integration, native brownfield extraction, delivery commands, and multi-LLM provider support.

The useful story for a brownbag is this: Echelon matured by repeatedly taking authority away from prompts where correctness mattered, and putting that authority into contracts, state, workflow definitions, harnesses, and verification loops.

## Timeline

### March 16, 2026: Cognitive Agent Squad Foundation

Initial commits created the Cognitive Agent Squad design, extension foundation, MANAGER command, core agents, specialist agents, learning agents, YAML knowledge base, templates, scripts, and validation.

The first working model was already more than a single prompt. It had roles for discovery, WHAT/WHY/HOW analysis, planning, specialist review, and learning. But the main orchestration pattern was still prompt-led: the MANAGER/COMMANDER role carried much of the routing burden.

Problem solved:

- A single AI assistant could not reliably discover, critique, plan, implement, verify, and learn in one pass.

Approach:

- Split the cognitive work across named agents and a central manager.

Limitation exposed:

- The LLM was doing too much coordination and state interpretation.

### March 17-18, 2026: From Planning Squad to Lifecycle System

Echelon quickly expanded from planning support into a fuller lifecycle. Commits added a building phase, engineering manager, verification agent, software-engineering standards, internalization, agent scorecards, and self-healing concepts.

Understanding CLI was integrated into the pipeline around this period, including diagram generation and later quality gates. This mattered because it introduced a deterministic evaluation surface for requirements quality instead of relying only on SAGE or human judgment.

Problem solved:

- Requirements quality and coverage needed a more objective gate.

Approach:

- Combine specialist agent review with Understanding CLI metrics.

Limitation exposed:

- Metrics helped, but the workflow still depended heavily on prompt-side discipline.

### March 18-21, 2026: Structure, Naming, Config, Fallback, and Learning

The project reorganized agents into layer-based directories, switched to codename-first prompts, added autonomy modes, centralized the agent registry, externalized many configuration values, and added dry-run validation.

It also added knowledge-base evolution machinery: prompt versions, evolution signals, internalization logs, and validation scripts. This is where Echelon started treating prompt behavior itself as something that could be observed, scored, and improved.

Problem solved:

- Rapid agent growth made the system hard to understand and maintain.

Approach:

- Standardize names, directories, config, validation, and knowledge-base records.

Limitation exposed:

- More prompts and config increased drift risk unless contracts became explicit.

### April 2026: Journal and Context Refactor

The April journal refactor design identified a core failure mode: workflow routing and journal ownership were too entangled with COMMANDER's active context. Agents could write or imply state changes in ways that were hard to reconstruct after compaction or interruption.

The direction changed: agents return structured `echelon_result` blocks, while COMMANDER/runtime code owns journal writes and state updates. Context became something persisted and reconstructed, not just remembered.

Problem solved:

- Long-running AI workflows lost reliability when chat history was the source of truth.

Approach:

- Use structured outputs, single-writer journal ownership, indexes, and state files.

Limitation exposed:

- Prompt contracts needed executable validators and stronger runtime enforcement.

### April to Early May 2026: Codegen, MemPalace, Local Delivery, and Harness Foundations

Design work added MemPalace requirements memory, SOAR/codegen integration, local continuous delivery concepts, and harness foundations.

This changed the project from "write good specs" to "carry requirements into implementation and delivery." MemPalace let requirements be mined and retrieved across runs. Codegen introduced an alternative SOAR-backed build path. Local delivery and harness plans pushed Echelon toward actual build/test/PR automation.

Problem solved:

- Specs alone did not ensure implementation continuity or delivery.

Approach:

- Add memory, build strategies, and delivery infrastructure.

Limitation exposed:

- Multiple implementation paths needed a common evidence and state model.

### May 2026: Revenge Becomes Native Brownfield `re-*`

Brownfield extraction was absorbed into Echelon as native `re-*` commands. The README currently states that native brownfield extraction replaces the standalone `revenge` extension.

The important architectural move was not just renaming. The inherited brownfield flow had been more like a separate imperative pipeline. Echelon externalized it into workflow phases and artifacts: analyze, specify, verify, expand, validate, checklist, constitute, retarget, plan, and tasks.

Problem solved:

- Existing-code reverse engineering needed to feed the same spec/build pipeline as greenfield work.

Approach:

- Fold `revenge`-style extraction into native Echelon commands and phase specs.

Limitation exposed:

- Brownfield workflows were too complex to remain as large standalone prompt scripts.

### May 2026: From LLM-Orchestrated Routing to Workflow and State Machine

The squad harness design captured a decisive lesson: COMMANDER could skip mandatory phases by inventing an escape justification. The fix was to make routing deterministic. Workflow state, phase transitions, and skip/advance/block decisions increasingly moved into Python-owned state machines.

The current command architecture reflects that change. Major command files are thin wrappers. They load COMMANDER behavior, then delegate to `workflow/definition.yaml` and `workflow/phases/*.md`. The workflow graph declares routing conditions, transitions, assigned agents, convergence thresholds, and build-loop state.

Problem solved:

- LLMs were poor final authorities for mandatory state transitions.

Approach:

- Make workflow definition and phase routing explicit, reviewable, and testable.

Limitation exposed:

- Even deterministic routing needed recovery tools for partial, interrupted, or invalid runs.

### May to June 2026: Build/QA Split and Harness Hardening

Echelon separated build and QA responsibilities more clearly. The build side gained implementer, code review, test guard, spec guard, progress tracking, tech writer, integration, verification, and visual validation roles. The harness added the operational substrate around that work.

The delivery loop became: build in an isolated worktree, verify in a sandbox, feed failures back into the implementation prompt, retry with progress tracking, commit, open PR, process review comments, and re-enter the loop when needed.

Problem solved:

- "Agent wrote code" was not enough. The system needed repeatable build, verification, review, and rework.

Approach:

- Add Ralph/harness loop, worktrees, Docker-compatible sandboxing, GitOps, PR review handling, and terminal status.

Limitation exposed:

- Successful builds could still be incomplete if they did not fulfill the spec.

### June 2026: Fulfillment, Evidence, and Landing

Fulfillment verification tightened the meaning of "done." Echelon added verify-spec, task-progress reconciliation, implementation maps, CodeGraph evidence mapping, fulfillment refresh policies, summary-table requirements, and land gates.

Landing also became a state machine. Instead of letting an autonomous run merge casually, Echelon checks fulfillment gaps, branch state, target repo, conflicts, cleanup, and continuation behavior.

Problem solved:

- A passing build could still miss requirements, target the wrong repo, or leave unsafe merge state.

Approach:

- Require evidence connecting spec, tasks, code, verification, and landing state.

Limitation exposed:

- Full fulfillment evidence can be expensive, so refresh needed policy and caching.

### June 2026: Lexicon and Structural Gates

Lexicon was introduced to make requirements machine-checkable. The current pipeline matrix keeps `spec.md` as the canonical human-readable contract and derives `requirements.lexicon.md` when the Lexicon gate is enabled.

That is the important design decision. Echelon did not force humans to write controlled grammar as the primary spec format. Instead, it uses Lexicon as a hard validation artifact generated from the canonical Markdown source, with source-reference checks to prevent drift.

Problem solved:

- Human-readable specs are useful, but Markdown alone is not a hard machine contract.

Approach:

- Keep `spec.md` canonical; derive and validate Lexicon artifacts for hard parsing.

Limitation exposed:

- Derived artifacts must be regenerated and source-checked, or they become another drift source.

### June to July 2026: Workspace/Source-Root Model and Delivery Namespace

Echelon now models every project as a workspace with zero or more source roots. The workspace root owns `.echelon/`, `.specify/`, `runs/`, and `specs/`. Source roots own implementation files. This supports single-repo, polyrepo, and planning-only workflows.

The newer CLI also shifts from older `harness` naming toward `delivery`: `echelon delivery init`, `echelon delivery run`, `echelon delivery resume`, and `echelon delivery land`. Compatibility aliases remain, but the product language is clearer: delivery means build, verify, PR, review, and land.

Problem solved:

- The current directory was not a reliable proxy for the workspace, target repo, or implementation source.

Approach:

- Make workspace/source roots explicit and validate the workspace contract.

Limitation exposed:

- Existing users need migration tools and clear operator guidance.

### July 2026: AI CLI Backends

The provider layer became explicit. Earlier code paths had provider-specific command construction and parsing logic around Claude, Codex, Copilot, and Opencode. The newer implementation routes terminal AI execution through `AICodingCliProvider` and concrete backend classes.

This is the provider-equivalent of the earlier workflow/state-machine lesson: provider quirks should not leak into the workflow graph or build loop. Each backend owns its CLI syntax, JSON/JSONL/event parsing, stderr behavior, permission flags, and final assistant-result extraction.

Problem solved:

- Multi-provider support was real, but provider behavior was too easy to scatter across the CLI, harness, direct skill dispatch, and review loop.

Approach:

- Add concrete AI CLI backend classes for Claude, Codex, GitHub Copilot, and Opencode behind one provider facade.

Limitation exposed:

- Live provider behavior is still less deterministic than local tests; each backend needs focused fixtures and sampled real CLI validation.

### July 2026: Echelon Stacks, Stack Preflight, and Stack Detection

Echelon added schema-backed stack definitions for known internal technology bundles. The first bundled stacks target Stats Perform Playbook, MSA service, and Stark webapp patterns. Selected stacks resolve into deterministic capability/tool context and concise agent-readable Markdown rather than being scattered through agent prose.

Stack preflight then checks whether required commands and declared tools are available before agents depend on them. Stack detection extends the idea to brownfield work: source trees and RE artifacts can produce observed stack evidence, matching Echelon stacks, modernization candidates, and decisions required. Detection is deliberately conservative and does not silently mutate project config.

Problem solved:

- Internal platform guidance needed to be machine-readable and preflightable instead of living as informal prompt instructions.

Approach:

- Add `extension/stacks/`, `src/harness/stacks/*`, `echelon stack list`, `echelon stack preflight`, and `echelon stack detect`.

Limitation exposed:

- Stack recommendation needs governance: observed current stack evidence is not the same as a future modernization decision.

## Core Evolution Pattern

The repeated pattern is:

1. Start with a prompt or agent capability.
2. Observe a real failure mode.
3. Name the failed assumption.
4. Move fragile authority into a contract, state file, validator, or Python state machine.
5. Add recovery and evidence so operators can trust the loop.

Examples:

- Prompt routing skipped required phases, so workflow phase routing moved into explicit definitions and Python state handling.
- Agents and prompts could imply state changes, so `echelon_result` became the structured output contract.
- Chat context was unreliable after compaction, so journals, indexes, run directories, and state JSON became authoritative.
- Brownfield extraction lived outside the main lifecycle, so `revenge` was folded into native `re-*` workflows.
- Build success was too weak a completion signal, so fulfillment and CodeGraph evidence were added.
- Markdown requirements were too soft for hard gates, so Lexicon became a derived validation artifact.
- Current-directory assumptions were unsafe, so workspace/source-root modeling became explicit.
- Dangerous LLM provider bypass behavior was too easy to enable implicitly, so host tool policy became fail-closed.
- Provider CLI behavior was too scattered, so concrete AI CLI backends now isolate Claude/Codex/Copilot/Opencode differences.
- Internal stack guidance was too informal, so Echelon Stacks now provide schema-backed capability context, preflight, and conservative detection.

## Four Engineering Tracks

### Prompt Engineering

Early Echelon mostly improved prompts: role definitions, specialist decomposition, naming, output formats, codenames, NEVER rules, quality responsibilities, and agent rosters.

This was necessary, but insufficient. Better prompts made agents more useful, but they did not solve state, recovery, evidence, or delivery safety.

### Context Engineering

The next improvement was durable context. Workflow definitions, phase specs, state files, journals, artifact indexes, run directories, workspace manifests, and MemPalace all reduce dependency on the active chat window.

This is the compaction-safety lesson: the model can reason over context, but the system must own context reconstruction.

### Harness Engineering

The harness moved risky operations into controlled execution: worktrees, sandbox verification, GitOps, PR operations, concrete AI CLI backends, review loops, stack preflight, host tool policy, and container runtime support.

This is the safety lesson: the LLM can propose and edit, but the harness owns mutation boundaries, retries, verification, and irreversible operations.

### Loop Engineering

The final maturity layer is feedback and convergence: verify, diagnose, repair, re-verify, reconcile fulfillment, handle review comments, refresh evidence, block on gaps, and land only when the state machine allows it.

This is the reliability lesson: autonomous coding is less about one brilliant generation and more about a bounded loop with evidence and stop conditions.

## What Problems Were Solved Over Time

| Problem | Early Shape | Later Shape |
|---|---|---|
| Too much work in one AI role | General manager prompt | Specialized agents with explicit roles |
| Subjective requirements quality | SAGE/human judgment | Understanding CLI gates plus agent critique |
| Lost context after compaction | Chat transcript as memory | State JSON, journals, run dirs, artifact indexes |
| Unreliable phase routing | COMMANDER decides from prompt | Workflow graph plus Python state machine |
| Brownfield separate from lifecycle | Standalone `revenge` extension | Native `re-*` commands and phase specs |
| Build result over-trusted | Agent says implementation is done | Harness verify/fix loop |
| Spec fulfillment unclear | Build passed | Fulfillment, task progress, CodeGraph evidence |
| Human review disconnected | Manual PR comments | Review comments become rework tasks |
| Markdown too soft for hard gates | `spec.md` only | Canonical `spec.md` plus derived Lexicon |
| Repo topology implicit | Current directory assumptions | Workspace/source-root contract |
| Unsafe provider permissions | CLI-specific behavior | Fail-closed host tool policy |
| Provider behavior scattered | One provider path with special cases | Concrete AI CLI backends |
| Internal stack guidance informal | Prompt prose and repo inference | Schema-backed Echelon Stacks |
| Brownfield stack selection manual | Narrative evidence in RE artifacts | Conservative `stack detect` reports |
| Delivery terminology scattered | harness/run/land variants | `echelon delivery ...` namespace |

## Talk Track

Use this as a 10-15 minute brownbag narrative.

1. Echelon began as a cognitive squad: many roles instead of one overburdened assistant.
2. That proved useful, but the system quickly discovered that orchestration is not just another prompt.
3. Understanding CLI was integrated to make requirements quality more measurable.
4. The first major reliability turn was context engineering: structured outputs, journals, state, and workflow files.
5. The second was deterministic orchestration: workflows and Python state machines took authority away from COMMANDER where correctness mattered.
6. Brownfield `revenge` was absorbed into native `re-*` workflows so reverse engineering could feed the same spec/build lifecycle.
7. The build harness made implementation operational: worktrees, sandbox verification, GitOps, PR loops, and review reentry.
8. Fulfillment and CodeGraph evidence made "done" evidence-based rather than agent-declared.
9. Lexicon added a machine-checkable requirements lane while preserving human-readable `spec.md`.
10. Workspace/source-root modeling made repo topology explicit, which is required for serious polyrepo and planning-only workflows.
11. AI CLI backends made provider differences explicit without polluting workflow logic.
12. Echelon Stacks made internal platform guidance schema-backed, preflightable, and detectable from brownfield evidence.
13. The core lesson: as the stakes went up, Echelon kept the LLM for semantic work and moved correctness-critical authority into contracts, state, and tools.

## Suggested Slide Sequence

1. **Initial Idea:** one AI is too broad; split work into a squad.
2. **First Success:** agents improve discovery, critique, planning, implementation, and learning.
3. **First Failure:** the model cannot be trusted as the sole workflow/state owner.
4. **Context Engineering:** `echelon_result`, journals, state files, artifact indexes.
5. **Workflow Engineering:** thin commands, `workflow/definition.yaml`, phase specs.
6. **Revenge Integration:** brownfield reverse engineering becomes native `re-*`.
7. **Harness Engineering:** worktrees, sandbox, GitOps, PR loop.
8. **Loop Engineering:** verify, repair, fulfill, review, land.
9. **Lexicon:** derived hard grammar beside canonical `spec.md`.
10. **Workspace Model:** explicit workspace and source roots.
11. **AI CLI Backends:** Claude, Codex, Copilot, and Opencode behind one provider facade.
12. **Echelon Stacks:** schema-backed platform context, preflight, and detection.
13. **Current State:** version 3.0.0, delivery namespace, 54 registered roles, 46 routed roles.
14. **Takeaway:** prompt engineering was the start; system engineering made it reliable.

## Source Map

Use these files when preparing slides or validating claims:

- `README.md`: current architecture, command model, agent roster, Understanding gate, delivery namespace, brownfield extraction, workspace contract summary, provider policy, and Docker/Podman setup.
- `docs/bbs/echelon-technical-dossier.md`: broader technical inventory and a longer version of the evolution timeline.
- `docs/pipeline-matrix.md`: Phase A/Phase B split and Lexicon strategy.
- `docs/workspace-model.md`: workspace/source-root model and migration guidance.
- `docs/re-overview.md`: brownfield reverse-engineering workflow.
- `docs/superpowers/plans/2026-07-05-codex-cli-backend.md`: Codex and AI CLI backend abstraction.
- `docs/superpowers/plans/2026-07-05-egr-097-opencode-copilot-backends.md`: Opencode and GitHub Copilot backend implementation.
- `docs/superpowers/specs/2026-07-05-echelon-stacks-design.md`: Echelon Stacks model.
- `docs/superpowers/specs/2026-07-06-stack-detection-design.md`: deterministic stack detection.
- `docs/superpowers/specs/2026-04-09-echelon-journal-refactor-design.md`: journal/context/state ownership refactor.
- `docs/superpowers/specs/2026-04-15-codegen-echelon-integration-design.md`: SOAR/codegen integration.
- `docs/superpowers/specs/2026-04-27-mempalace-integration-fix-design.md`: MemPalace integration.
- `docs/superpowers/specs/2026-05-17-re-workflow-externalization-design.md`: brownfield workflow externalization.
- `docs/superpowers/specs/2026-05-18-squad-harness-design.md`: deterministic squad harness and Python-owned routing.
- `docs/superpowers/specs/2026-04-29-polyrepo-multi-target-harness-design.md`: polyrepo harness targeting.
- `docs/superpowers/specs/2026-06-22-codegen-runnable-composition-gate-design.md`: RUNNABLE/codegen delivery evidence.
- `docs/findings/echelon-grounded-review-register.md`: Echelon Grounded Review issue register.
- `knowledge-base/evolution-signals.yaml`: knowledge-base signals for prompt/system evolution.

## Open Questions for the Meetup

- Which transition was most important in practice: workflow externalization, harness introduction, fulfillment gates, or workspace modeling?
- Should the talk frame `revenge` integration as a product consolidation story or as an architectural externalization story?
- Which demo artifact best makes the LLM-to-state-machine transition visible?
- Is Lexicon currently a default operating path for the audience, or should it be presented as an emerging hard-gate capability?
- Should the delivery namespace be presented as current user-facing terminology, with `harness` treated as implementation history?
- Should provider backends be shown as an implementation detail or as a key reliability step?
- Should Echelon Stacks be presented as product direction, internal platform governance, or a brownfield modernization aid?
