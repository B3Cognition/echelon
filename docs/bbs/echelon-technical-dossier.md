# Echelon Technical Dossier for Brownbag Preparation

This document extracts technical material from the repository for later use in designing an internal engineering brownbag or meetup. It is not a presentation. It is source material: architecture notes, implementation details, risks, testing posture, and possible demo/story angles.

## 1. Project Summary

Echelon is a multi-agent system for AI-assisted software development. Instead of asking one AI session to understand, plan, implement, review, and learn all at once, Echelon decomposes that work across specialized roles: discovery, requirements writing, critique, feasibility, architecture, implementation, test strategy, code review, fulfillment verification, and learning.

The project solves a practical problem in AI-assisted engineering: getting from a rough feature request or brownfield codebase to a buildable, testable implementation plan and then through an automated build/verify/PR loop with fewer skipped quality gates. It treats prompts, workflow state, generated artifacts, and deterministic verification as one system rather than a loose collection of chat instructions.

Primary users are engineers using spec-kit, Claude Code, Copilot, Opencode, or Codex-based workflows. The system also supports automated terminal entry points, so it can run outside an interactive AI session.

The main inputs are:

- A feature, bugfix, review, or brownfield-analysis request.
- Existing project files and specs under `specs/<id>-*/`.
- Echelon configuration in `echelon-config.yml`.
- Optional target repository, Docker/devcontainer configuration, CI/test commands, PR URL, and MemPalace requirements memory.

The main outputs are:

- Spec-kit artifacts such as `spec.md`, `plan.md`, `tasks.md`, `research.md`, contracts, test strategy, and artifact indexes.
- Harness state, verification results, implementation runs, fulfillment reports, review-fix tasks, commits, branches, and PRs.
- Knowledge-base updates such as calibration, patterns, pitfalls, and internalization records.

The project exists to make AI-assisted delivery less ad hoc: agents must provide structured results, COMMANDER owns the state machine, deterministic tools enforce quality and verification, and the harness runs implementation in controlled worktrees and Docker sandboxes.

## 2. Technical Context

Echelon sits around spec-kit and one or more AI coding CLIs. The README identifies support for Claude, GitHub Copilot, Opencode, and Codex. The terminal CLI reads installed skill files, strips or adapts frontmatter where needed, adds execution preambles, and invokes the selected LLM CLI. Interactive spec-kit usage injects the same command content into the current AI session.

Important external systems and dependencies:

- `spec-kit` / `specify-cli`: extension installation, project initialization, slash-command integration, config cascade where available.
- AI CLIs: `claude`, `copilot`, `opencode`, and `codex`; selected by `ECHELON_LLM` or harness config.
- Docker: deterministic build/test/verify sandboxing and optional local blue/green deploy.
- Git and GitHub/GitLab CLI: mirror clone, worktrees, commit, push, PR creation, PR review polling, merge.
- MemPalace: ChromaDB-backed semantic memory for mined requirements, scoped by project "wing".
- SOAR: bundled engine used by the `codegen` pipeline.
- Understanding CLI: requirements-quality scanner with 34 metrics.
- Python 3.11+, PyYAML, Typer, Rich, spaCy, Graphviz, Transformers, Torch.

Runtime environment:

- Python package with console scripts declared in `pyproject.toml`: `echelon`, `codegen`, `understanding`, and `hormone-calc`.
- Spec-kit extension files under `extension/`.
- Harness state and runtime extension material under `.specify/extensions/echelon/` in target projects.
- Worktrees, mirrors, strategy state, and build run state under `.specify/extensions/echelon/harness/` or related build directories.

Deployment target:

- The project itself is installed locally by `scripts/install.sh` into `~/.echelon/venv/bin/`.
- Generated target applications can optionally be deployed locally using Docker blue/green deployment, with Traefik for HTTP apps or active-tag wrappers for CLI apps.

Important constraints:

- LLM reasoning runs on the host; deterministic commands run in Docker.
- Sandbox containers must not receive host Git credentials.
- Quality gates and workflow routing are intended to be declarative and reproducible.
- Commands are thin wrappers; real routing lives in `extension/workflow/definition.yaml` and phase specs.
- State must survive compaction, interruption, retry, and parallel strategy runs.

## 3. Architecture Overview

Main components:

- Spec-kit extension: prompt commands, agent definitions, workflow graph, phase specs, templates, presets.
- Echelon CLI: deterministic command entry points, config/init helpers, LLM command invocation, artifact/status/continue/resume/land commands.
- Harness: build/verify/PR execution substrate with strategy fan-out, Docker sandboxing, GitOps, state management, review loops, fulfillment checks, and optional visual tests.
- Codegen pipeline: SOAR-backed alternative build path with requirements memory, phase gates, PSI score, and Tier 1 testing.
- Understanding CLI: requirements-quality scoring used by SAGE and standalone scans.
- Kernel helpers: validation and fulfillment contracts shared by CLI and harness logic.
- Knowledge base: local YAML/Markdown memory for calibration, patterns, pitfalls, feedback, and evolution signals.

Simple architecture diagram:

```text
User request / spec / PR comments
        |
        v
echelon CLI or spec-kit command
        |
        +--> extension/commands/*.md
        |       |
        |       v
        |   COMMANDER + workflow/definition.yaml + workflow/phases/*.md
        |       |
        |       v
        |   agents/* produce echelon_result + artifacts
        |
        +--> harness coordinator
                |
                +--> LLM build provider on host
                +--> GitOps mirror/worktrees/PRs
                +--> Docker sandbox for verify/test/build commands
                +--> ReviewLoopController for PR comments
                +--> StateStore JSON files + locks + backups

Alternative build strategy:

spec artifacts --> codegen CLI --> SOAR pipeline --> MemPalace requirements
                              --> phase gates --> tests/delivery
```

Synchronous parts:

- CLI argument parsing and command dispatch.
- Config loading/validation.
- State reads/writes and transition checks.
- Git operations and PR operations.
- Docker sandbox command execution.
- Test and verification command execution.

Asynchronous or iterative parts:

- Agent dispatches inside the workflow.
- Harness outer/inner loop: build, verify, feedback, fix, re-verify.
- Parallel strategy execution using `ThreadPoolExecutor`.
- PR review polling and re-entry into build.
- Visual test loop when enabled.

State is stored in:

- Spec folders under `specs/<id>-*/`.
- `.specify/squad/state.json` and reasoning journals for squad runs.
- Harness per-strategy JSON files with lockfiles and `.bak` snapshots.
- `codegen-state.json` for SOAR pipeline runs.
- Knowledge-base YAML and JSONL-like files.
- MemPalace backing store under `~/.mempalace/palace/`.
- Deploy state in project-local and global `~/.speckit-deploy/` locations.

Business logic lives in both prompt workflows and Python. The prompt-side logic defines role behavior and expected outputs; the Python-side logic enforces state transitions, config validation, sandbox lifecycle, Git operations, verification loops, and reusable contract checks.

Configuration lives primarily in `extension/config-template.yml`, `extension/extension.yml`, target-project `echelon-config.yml`, local overrides, and environment variables. Harness config explicitly documents a four-layer cascade: defaults, project config, local config, and `SPECKIT_HARNESS_*` env vars.

## 4. Repository / Codebase Structure

Important directories:

- `extension/`: spec-kit extension contents. This is the prompt/workflow product: agents, commands, workflow definitions, phase specs, templates, presets, config, and scripts.
- `extension/agents/`: 41 agent definitions grouped by layer: control, exploration, feasibility, solution, specialists, learning, and build.
- `extension/commands/`: thin command wrappers such as `echelon.run.md`, `echelon.build.md`, `echelon.codegen.md`, `echelon.review.md`, and re-* brownfield commands.
- `extension/workflow/`: declarative workflow graph and phase-level prompt specs. `definition.yaml` is especially important.
- `src/echelon/`: main CLI entry point, target detection, UI helpers, orchestrator, artifact index.
- `src/harness/`: build harness implementation. Key files include `coordinator.py`, `ralph.py`, `docker_provider.py`, `gitops.py`, `state.py`, `config.py`, `review_loop.py`, `visual_ralph.py`, and `llm_provider.py`.
- `src/codegen/`: SOAR codegen pipeline, memory integration, phase gates, requirement mining/search, constitution extraction, security utilities, LSP gate, and CI helpers.
- `src/understanding/`: requirements quality analyzer and metric modules.
- `src/kernel/`: shared contracts and validation helpers for plans, tasks, fulfillment, state loading, schema validation, and accessors.
- `src/hormone_calc/`: motivation/trigger calculation system used by the agent workflow.
- `knowledge-base/`: calibration, patterns, pitfalls, marketplace index, estimates, prompt versions, feedback, evolution signals, and agent scores.
- `templates/` and `extension/templates/`: reusable output formats and process templates.
- `docs/`: design notes, run analyses, RE docs, fallback-mode docs, calibration guides, plans/specs.
- `specs/`: local specs for Echelon features and hardening work.
- `tests/`: unit, integration, contract, kernel, e2e, shim, validation, benchmark, fixtures, mocks, and manual tests.
- `.github/workflows/ci.yml`: GitHub Actions CI.
- `.ci/pipeline.yml`: additional pipeline config, not deeply analyzed here.
- `network/`: Squid proxy configuration for sandbox network policy.
- `scripts/`: install/uninstall, Docker sandbox/network/GC helpers, KB management, dry-run validation, internalization scripts.

Entry points:

- `src/echelon/cli.py`: `echelon` CLI.
- `src/codegen/cli/codegen_cli.py`: `codegen` CLI.
- `src/understanding/cli.py`: `understanding` CLI.
- `src/hormone_calc/cli.py`: `hormone-calc` CLI.
- `src/harness/__main__.py`: harness module entry point.

Most important files for quick understanding:

- `README.md`: product model, command model, architecture, agents, harness, local CD, quality gates.
- `pyproject.toml`: package shape, dependencies, console scripts, pytest config.
- `extension/workflow/definition.yaml`: phase graph and routing contract.
- `src/harness/coordinator.py`: strategy fan-out and Phase 1/2/3 orchestration.
- `src/harness/ralph.py`: core build/verify/feedback loop.
- `src/harness/state.py`: state invariants and atomic writes.
- `src/harness/docker_provider.py`: sandbox security and execution model.
- `src/harness/gitops.py`: mirror/worktree/branch/PR operations.
- `src/codegen/pipeline/pipeline_engine.py`: SOAR pipeline lifecycle.
- `src/understanding/cli.py`: quality-gate metric surface.

## 5. Key Technical Decisions

Multi-agent decomposition:

- Decision: split software delivery cognition across specialized agents.
- Likely reason: force critique, test strategy, implementation, review, learning, and feasibility into separate passes.
- Trade-off: better separation of concerns, but many prompts and transitions to maintain.
- Visible alternative: one larger general-purpose AI command or a smaller fixed pipeline.

Declarative workflow graph:

- Decision: route through `extension/workflow/definition.yaml` plus phase-specific Markdown specs.
- Likely reason: keep command wrappers small and make phase routing reviewable and editable.
- Trade-off: powerful but config/prompt/schema drift becomes a risk.
- Visible alternative: hard-code routing in Python or in a single COMMANDER prompt.

Python control plane around prompt workflows:

- Decision: deterministic orchestration, config, state, Git, Docker, and CLI behavior live in Python.
- Likely reason: retries, locks, subprocesses, atomic writes, and validation are safer in code than in prompts.
- Trade-off: the system has two kinds of logic: executable Python and executable prompt instructions.
- Visible alternative: all-shell orchestration or pure spec-kit prompt execution.

Host LLM, Docker verification:

- Decision: LLM CLI runs on host while build/test/verify run in Docker.
- Likely reason: preserve AI tool access while isolating deterministic project execution.
- Trade-off: host/sandbox boundary must be carefully managed.
- Visible alternative: run everything in container, or run everything on host.

Git mirror and worktree model:

- Decision: use bare mirror clones and per-run worktrees.
- Likely reason: isolate strategy attempts, support cleanup and branch management, enable polyrepo workflows.
- Trade-off: GitOps code is non-trivial and must protect default branches.
- Visible alternative: mutate the working tree directly.

Parallel strategy execution:

- Decision: `StrategyCoordinator` can fan out multiple strategies and optionally cancel losing strategies.
- Likely reason: compare build approaches such as default squad vs SOAR codegen.
- Trade-off: budget slicing, cancellation, state isolation, and result comparison add complexity.
- Visible alternative: only one build path at a time.

SOAR/codegen as alternative to agent squad:

- Decision: provide a SOAR-powered pipeline with phase gates and PSI thresholds.
- Likely reason: some workflows need more explicit rule-based gating than agent review.
- Trade-off: another pipeline with its own state, memory, and failure modes.
- Visible alternative: use the agent build path exclusively.

MemPalace requirements memory:

- Decision: mine and retrieve requirements from shared semantic memory scoped by wing.
- Likely reason: improve cross-run continuity and targeted context retrieval.
- Trade-off: memory collision, stale requirements, cleanup, and wing portability must be handled.
- Visible alternative: always pass full specs in prompt context.

Understanding quality gates:

- Decision: quantify requirements quality using research-backed metrics and thresholds.
- Likely reason: avoid subjective “looks good” requirement reviews.
- Trade-off: metrics can be gamed or misaligned with domain nuance.
- Visible alternative: purely human/agent qualitative review.

Atomic state files:

- Decision: per-strategy JSON state with lockfiles, monotonic counters, valid transitions, `.bak` snapshots.
- Likely reason: survive interruption and prevent corrupted or conflicting loops.
- Trade-off: state evolution requires migrations and invariant discipline.
- Visible alternative: in-memory state or loosely written JSON.

Security boundaries:

- Decision: detect Git credentials in sandbox env/mounts, use network allowlists through Squid, validate paths/YAML in codegen security modules.
- Likely reason: AI-driven code execution is high-risk.
- Trade-off: sandbox setup and allowlist maintenance can block legitimate builds.
- Visible alternative: unrestricted Docker/network execution.

Observability through artifacts:

- Decision: status commands, artifact indexes, reasoning journals, run history, fulfillment reports, deploy state, and review state.
- Likely reason: make long-running autonomous work resumable and explainable.
- Trade-off: many artifacts to keep consistent.
- Visible alternative: console logs only.

## 6. Interesting Implementation Details

`extension/workflow/definition.yaml`:

- What it does: declares the workflow graph, phase node metadata, transitions, quality gates, evidence hierarchy, and routing language.
- Why interesting: it turns prompt orchestration into data that can be reviewed and tested.
- How it works: COMMANDER reads it before routing, checks current state, executes the current phase spec, evaluates transitions, writes updated state, and repeats.

`src/harness/ralph.py`:

- What it does: implements the outer/inner build loop.
- Why interesting: it formalizes autonomous implementation as build, verify, feedback, retry, escalation, and termination.
- How it works: creates worktrees and sandboxes, runs an LLM build command, verifies in Docker, detects repeated failures/no progress, writes state, and finalizes with a `LoopResult`.

`src/harness/coordinator.py`:

- What it does: coordinates one or more strategy runs.
- Why interesting: parallel strategy execution is a practical way to compare different AI build approaches.
- How it works: loads strategy specs, slices token budgets, creates one `RalphController` per strategy, runs them in threads, and optionally cancels peers once a strategy converges.

`src/harness/state.py`:

- What it does: owns per-strategy JSON state.
- Why interesting: it gives a simple filesystem state store real operational properties.
- How it works: writes via tempfile/fsync/rename, keeps `.bak`, uses lockfiles with PID checks, validates state transitions, forbids mode changes, and enforces monotonic counters.

`src/harness/docker_provider.py`:

- What it does: provides Docker-backed sandbox lifecycle.
- Why interesting: it contains concrete safety controls for AI-driven execution.
- How it works: checks env/secrets for Git credential patterns, creates an isolated Docker network and Squid sidecar, starts a resource-limited sandbox container, truncates large output with tail preservation, and gathers resource stats.

`src/harness/gitops.py`:

- What it does: centralizes Git operations.
- Why interesting: it avoids scattering dangerous branch/push/PR behavior across the system.
- How it works: manages mirror clones, worktrees, commits, pushes, PRs, and degraded modes when PR CLIs are absent. It also contains runtime skill-wrapper generation logic for synced commands.

`src/harness/review_loop.py`:

- What it does: automates PR review feedback handling.
- Why interesting: it maps human review comments back into the implementation loop instead of treating review as a separate manual phase.
- How it works: fetches unresolved comments, filters blocking language, invokes `echelon.review`, records processed comment IDs, resolves threads when configured, then re-enters the build loop.

`src/codegen/pipeline/pipeline_engine.py`:

- What it does: drives the SOAR codegen pipeline.
- Why interesting: it provides a non-agent-squad implementation strategy with explicit phase gates.
- How it works: initializes `codegen-state.json`, runs RE requirement lookup through MemPalace, delegates phase decisions to `PhaseGateRunner`, tracks PSI/Tier 1 gate status, and only delivers after gates pass.

`src/codegen/memory/*`:

- What it does: mines, writes, reads, repairs, and cleans requirement memory.
- Why interesting: it shows a pragmatic pattern for semantic memory with project scoping and collision handling.
- How it works: requirement IDs are parsed from spec-like Markdown, associated with source paths and wing metadata, stored in MemPalace, retrieved for relevant intents, and filtered to avoid delivered requirements.

`src/understanding/cli.py`:

- What it does: scans specs for requirements quality using 34 metrics.
- Why interesting: it operationalizes requirements quality as a CLI gate.
- How it works: auto-discovers `spec.md`, supports enhanced/basic scans, JSON/CSV output, per-requirement analysis, diagrams, energy metrics, and validation exits.

`src/echelon/artifact_index.py`:

- What it does: generates human-readable artifact maps for spec folders.
- Why interesting: it makes autonomous runs easier to inspect without reading every generated file.
- How it works: deterministic artifact indexing summarizes known outputs, lifecycle stage expectations, and missing files.

`tests/run-all.sh`:

- What it does: orchestrates shell, pytest, validation, shim, e2e, and benchmark suites.
- Why interesting: it mirrors the project’s hybrid nature: prompts and scripts need tests alongside Python.
- How it works: discovers shell tests by directory, runs pytest suites, gathers suite summaries, and exits nonzero if any suite fails.

## 7. Difficult or Risky Parts

Prompt/code contract drift:

The system depends on alignment between command wrappers, agent prompts, workflow definitions, templates, Python validators, tests, and docs. Drift can make a command appear valid while producing artifacts that later phases cannot consume.

State recovery:

Runs can be interrupted by terminal exits, compaction, failed subprocesses, repeated verification failures, parallel strategy cancellation, or human escalation. The state layer is strong, but the number of paths makes recovery logic intrinsically risky.

Sandbox security:

Running AI-generated changes and project build commands requires careful boundary management. Credential leakage, overly broad network access, host bind mounts, and Docker socket assumptions are all operational risks.

Git and PR safety:

Automated worktrees, commits, pushes, branch updates, and merges need strict safeguards. The repository has explicit logic around mirrors, default-branch protection, degraded PR modes, and fulfillment checks, which suggests this is a known risk area.

Config complexity:

The README mentions 76 configurable values across 20 sections. That allows flexibility but raises risk of invalid combinations, hidden defaults, local override surprises, and CI/local divergence.

Memory staleness and collisions:

MemPalace wings solve project scoping, but shared semantic memory can still accumulate stale or incorrect requirements if mining/cleanup discipline fails.

Quality metric overconfidence:

Understanding metrics provide useful gates, but requirements quality cannot be completely reduced to numeric thresholds. False confidence or metric gaming are practical risks.

LLM provider variability:

Different CLIs have different invocation syntax, streaming behavior, permission models, tool availability, and output formats. Provider abstraction reduces friction but cannot eliminate behavioral differences.

Review-loop false positives:

The review loop detects blocking comments using text patterns. Words like “should” or “change” can be contextual; nits and questions may be skipped, but there is still risk of misclassification.

Scale/performance:

Long autonomous runs can involve large prompts, many artifacts, multiple strategies, Docker builds, tests, and PR cycles. Token budgets, timeouts, buffer truncation, and GC are present because resource pressure is real.

Test environment dependencies:

Some tests need Docker, Git, GitHub/GitLab CLIs, SOAR, MemPalace, or local models. CI may cover many paths, but local parity can be hard.

## 8. Testing and Quality

Testing is broad and multi-layered.

Visible test structure:

- `tests/unit`: Python unit tests plus shell tests for templates, KB scripts, state schema, endocrine behavior, prompt budgets, etc.
- `tests/integration`: Docker provider, GitOps, state store atomicity, MemPalace mine/search, endocrine integration, build/QA contracts, network policy, visual runtime smoke tests.
- `tests/contract`: sandbox provider contract.
- `tests/kernel`: kernel-level contracts and state/fulfillment logic.
- `tests/e2e`: end-to-end shell scenarios.
- `tests/echelon-validation`: validation suite for extension behavior.
- `tests/shim`: compatibility or wrapper tests.
- `tests/benchmarks`: benchmark shell tests.
- `tests/fixtures`, `tests/mocks`, `tests/manual`: fixtures, mocked CLIs/responses, and manual checklists.

Approximate discovered test file distribution:

- 204 unit test files
- 49 integration test files
- 20 e2e files
- 15 kernel files
- 6 validation files
- 5 shim files
- 2 benchmark files
- 1 contract file

Quality mechanisms:

- Pytest configuration in `pyproject.toml` with unit, contract, integration, system, e2e, docker, and slow markers.
- GitHub Actions runs `bash tests/run-all.sh` plus a dedicated Python unit test job.
- Shell tests validate prompt/template/schema behavior that normal Python tests might miss.
- Understanding quality gates apply to requirements artifacts.
- Harness fulfillment checks block landing unless gaps are handled or explicitly overridden.
- Spec artifact indexes make missing lifecycle artifacts visible.

Testing gaps or weak areas visible from the repo:

- No type checker or linter is visible in `pyproject.toml` or CI.
- CI installs with `pip install -e ".[dev]"`; heavy optional tools such as Docker-dependent flows may still depend on runner capabilities.
- Rollback strategy for Git/PR operations is partially visible through safeguards, but full disaster recovery is harder to infer.
- LLM behavior is difficult to test deterministically; the repo uses mocks and templates, but live provider variance remains a residual risk.
- Security testing exists in pieces, but a full threat-model-driven test suite is not obvious from the quick scan.

## 9. CI/CD and Deployment

Build process:

- Python package built with setuptools.
- Install command in CI: `pip install -e ".[dev]"`.
- Local install path: `scripts/install.sh`, which installs CLIs into `~/.echelon/venv/bin/` and downloads/bundles SOAR.

CI:

- `.github/workflows/ci.yml` runs on pushes and PRs to `main`.
- Job `shell-tests`: checkout, setup Python 3.11, install dev deps, run `bash tests/run-all.sh`.
- Job `python-unit-tests`: checkout, setup Python 3.11, install dev deps, run `pytest tests/unit/ -q --tb=short`.

Deployment:

- Echelon itself is mostly a local CLI/spec-kit extension install.
- Target projects can use Echelon’s local CD after merge.
- HTTP apps use Docker blue/green containers behind a shared local Traefik router.
- CLI apps use Docker image blue/green tags and optional wrapper scripts.
- Deploy state is mirrored in project-local and global locations.

Rollback:

- HTTP rollback restarts the stopped inactive container and flips routing.
- CLI rollback flips the active image tag pointer.
- Landing has an emergency `--allow-fulfillment-gaps` override, but normal landing blocks on unresolved fulfillment gaps.

Infrastructure as code:

- Dockerfiles may be generated for target apps.
- `network/` contains Squid proxy config generation.
- `extension/config-template.yml` and workflow files are effectively extension infrastructure.

Secrets/configuration management:

- Harness supports `secrets_env_file`.
- Sandbox checks block Git credential leakage into containers.
- Config cascade supports local gitignored config and env var overrides.

Versioning:

- `README.md` states version 1.5.0, while `pyproject.toml` project version is 1.5.0 and `src/echelon/cli.py` has `CLI_VERSION = "2.2.0"`. That split may reflect CLI protocol versioning vs package versioning and should be clarified before presenting.

## 10. Observability and Operations

Operational signals visible in the repo:

- `echelon status`: re-orients users around run state, artifacts, open issues, cost, and next step.
- `echelon artifacts <id>`: generates `ARTIFACTS.md` for a spec folder.
- Harness per-strategy state files track status, iterations, token usage, PR URL, termination reason, and final verify result.
- `StateStore` writes backups and lockfiles.
- `RalphController` tracks termination reasons such as convergence, budget exhaustion, same failure, no progress, interruption, and cancellation.
- `ReviewLoopController` has persisted review state for processed comment IDs.
- Docker provider collects resource stats when available and truncates large output predictably.
- Codegen state tracks pipeline phase, PSI score, Tier 1 gate, SOAR model, retries, impasse count, and MemPalace wing.
- Knowledge-base files preserve calibration, patterns, pitfalls, feedback, and evolution signals.
- Local deploy state tracks active slot/image/ports and supports status/rollback.

Logs and debugging:

- Python modules use `logging`.
- CLI commands print banners and summaries.
- LLM streaming output for Claude is parsed as `stream-json` by `AICodingCliProvider`.
- Build prompts, review-fix files, task progress, and fulfillment reports are artifacts useful for debugging.

Retries and recovery:

- Build loop has outer and inner retry caps.
- Same-failure and no-progress detection can trigger escalation.
- Blocked runs can be resumed with answers.
- Interrupted harness runs can resume.
- Stale state locks can be reclaimed if PID is gone.
- Fallback mode lets COMMANDER continue when spec-kit skill invocations fail, but marks fallback artifacts as unvalidated.

Useful brownbag showpieces:

- A `state.json` before/after a phase transition.
- An `ARTIFACTS.md` index for a spec folder.
- A failed verify result feeding back into a second build iteration.
- A review comment becoming a `review-fix-{n}.md` task.
- A codegen `codegen-state.json` moving through RE/DECOMPOSE/IMPLEMENT/GATE/TEST/DELIVER.

## 11. Security and Compliance Considerations

Visible security controls:

- Docker sandbox refuses env/secrets with Git credential-like variable names.
- Docker sandbox checks known host credential mount patterns such as `.ssh/`, `.gitconfig`, `.git-credentials`, and Docker config.
- Sandbox network is routed through a Squid proxy sidecar with an allowlist.
- Resource limits include memory, CPU, PID, and storage defaults.
- GitOps protects against dangerous repo operations such as default-branch pushes and self-targeting, based on file comments and contracts.
- Codegen includes security modules for secret scrubbing, schema validation, YAML safety, path safety, LSP subprocess safety, and language allowlisting.
- GUARDIAN is always-on by default according to README.
- Brownfield compliance preset includes GDPR/HIPAA/SOC2 checklists and risk templates.

Authentication/authorization:

- Not much product authentication is involved; Echelon relies on user-installed AI CLIs, Git CLIs, and local credentials.
- PR operations depend on `gh` or `glab` authentication when enabled.
- The sandbox is designed not to receive Git credentials.

Data and PII:

- The project can analyze arbitrary codebases and specs. If those contain secrets or PII, prompts/artifacts/memory may capture sensitive information unless guarded.
- MemPalace stores mined requirements under a shared local database; wing scoping helps but does not replace data classification.

Auditability:

- Reasoning journals, artifact indexes, state files, codegen state, review-fix artifacts, and knowledge-base logs provide an audit trail.
- The exact completeness of audit trails in live use depends on commands writing structured `echelon_result` blocks and COMMANDER correctly processing them.

Dependency security:

- Dependencies include direct references to GitHub-hosted MemPalace and spaCy model wheels.
- No visible dependency vulnerability scanning was found in CI during this pass.

## 12. Before / After Comparison

Before Echelon, the likely baseline is manual or semi-manual AI-assisted engineering:

- Engineers ask an AI to inspect code, write specs, implement, run tests, and fix issues in one conversation.
- Quality gates are informal.
- State is mostly conversational.
- Review feedback is handled manually.
- Build/test execution may happen directly in the user’s working tree.
- Requirements memory is prompt-local or document-local.

After Echelon:

- Work is broken into named phases and specialized agents.
- Requirements quality, spec coverage, fulfillment, and verification become explicit gates.
- The build loop happens in isolated worktrees and Docker sandboxes.
- PR review feedback can be transformed into tasks and re-entered into the build loop.
- Artifacts and state make long-running work resumable.
- Requirements can be mined into MemPalace and retrieved by later codegen runs.
- Local deployment and rollback can be standardized for target apps.

What became simpler, safer, or more automated:

- Re-orientation after a break via status/artifact commands.
- Repeated build/verify/fix loops.
- PR review triage.
- Spec artifact discovery.
- Requirements quality scanning.
- Sandbox verification and local CD.

New complexity introduced:

- Many agents, workflow phases, templates, and config values.
- Dual logic plane: prompts and Python.
- Provider compatibility across AI CLIs.
- More artifacts and state files to understand.
- More operational dependencies: Docker, Git CLI, PR CLI, SOAR, MemPalace, spec-kit.

## 13. Problems Solved Over Time and Evolution of the Approach

The git history tells a useful meetup story: Echelon did not start as the current Python-guarded harness. It appears to have evolved by repeatedly finding places where prompt-only orchestration was too fragile, then moving the brittle part into explicit contracts, deterministic files, or Python-owned state machines.

### Timeline of the Evolution

March 16-18, 2026: cognitive squad foundation.

- The first commits add the Cognitive Agent Squad design, extension foundation, MANAGER command, core agents, specialist agents, learning agents, YAML knowledge base, and README/validation.
- The architecture quickly grows from an understanding/planning helper into a full lifecycle system with a build phase, engineering manager, verification agent, triadic/internalization model, and Understanding CLI diagram integration.
- Problem being solved: one AI role could not reliably discover, critique, plan, test, implement, verify, and learn. The first answer was separation of concerns through agents.

March 18-21, 2026: structure, naming, configuration, and fallback hardening.

- History shows a large refactor into layer-based directories, codename-first agent naming, autonomy modes, a central agent registry, 76 externalized config values, dry-run validation, fallback mode, KB management, and test infrastructure.
- Problem being solved: rapid agent growth made the system hard to operate unless names, directories, config, and validation were standardized.
- Approach shift: from "many useful prompts" toward an installable extension with conventions, validation, and explicit operational modes.

Late March through April 2026: journal ownership and compaction safety.

- The April 9 journal refactor design identifies three coupled failures: workflow routing embedded in COMMANDER's prompt, many agents writing directly to `reasoning-journal.json`, and positional journal queries that lose critical context after compaction.
- The proposed solution externalizes workflow definition, makes agents return `echelon_result` blocks, and turns COMMANDER into the sole journal writer with an index.
- Problem being solved: autonomous AI workflows lose reliability when the current conversation window is the source of truth.
- Approach shift: context should be reconstructed from files, not remembered from chat.

April to early May 2026: local delivery, MemPalace, codegen, and harness foundations.

- Design docs and plans cover local CD, MemPalace integration, codegen/Echelon integration, polyrepo harness support, and run refactors.
- Problem being solved: specifications are not enough unless the system can build, verify, remember requirements, and move work through delivery.
- Approach shift: Echelon expands from spec authoring into an execution substrate with memory, build strategies, and deployment hooks.

May 17-18, 2026: brownfield extraction and deterministic squad routing.

- The re-* workflow externalization design says inherited brownfield commands were large imperative scripts, invisible to `workflow/definition.yaml`, missing `echelon_result`, and not resumable after compaction.
- The squad harness design identifies a concrete failure: COMMANDER skipped mandatory `phase3-consensus` by inventing an escape justification. The fix was to apply the same pattern as the build harness: Python owns phase routing, while LLM agents perform the phase work.
- Problem being solved: LLMs are poor final authorities for mandatory state transitions.
- Approach shift: prompts still do reasoning, but Python decides whether a phase can be skipped, advanced, retried, or blocked.

May 19-31, 2026: resumability, run directories, status, and harness hardening.

- Commit history repeatedly mentions blocked-state recovery, resume commands, sticky escalation blocks, phase progress streaming, exact spec ID display, actual branch reporting, worktree preservation, marker/status files, and routing runtime artifacts into run directories.
- Problems being solved: users needed to recover after budget exhaustion, invalid phases, missing target config, timeouts, incomplete harness builds, and confusing terminal output.
- Approach shift: the system grows better "operator ergonomics": status commands, banners, exact next actions, preserved work, and idempotent resume behavior.

June 1-5, 2026: landing, fulfillment, polyrepo targeting, and artifact maps.

- Autonomous land design addresses unsafe merge behavior, semantic conflicts, branch preparation, verification, push, cleanup, and idempotent continuation.
- Fulfillment verification and reconciliation commits add gates before land, fulfillment refresh in the harness loop, progress integrity artifacts, task contracts, and safe reconciliation of implemented work back into `tasks.md`.
- Polyrepo target preflight fixes a concrete unsafe class: the LLM could find the correct nested repo and commit there, while harness state still treated the wrapper repo as the build target.
- Deterministic artifact index design addresses human review friction: spec folders accumulate many files, and reviewers need a generated "read this first" map.
- Problems being solved: "done" was not strong enough unless the right repo was targeted, the implementation matched the spec, task progress was truthful, artifacts were readable, and landing could be made safe.
- Approach shift: convergence becomes evidence-based and target-aware rather than just "the build command exited and the agent said done."

June 8-12, 2026: recovery and convergence tighten further.

- Recent commits focus on deterministic spec paths, stale worktree recreation, worktree escape detection, partial-build recovery, clean markerless builds, command skill syncing into harness worktrees, extended autonomous build timeout, CodeGraph evidence mapping, completed-task IDs, build progress slices, and blocking convergence on fulfillment summary tables.
- Problems being solved: edge cases where work existed but markers were missing, paths were ambiguous, builds partially succeeded, tasks were reported without stable IDs, or fulfillment summaries were absent.
- Approach shift: every successful run needs durable markers and auditable evidence, not merely side effects in a worktree.

### Evolution Pattern

The repeated pattern is:

1. Start with an agent/prompt capability.
2. Observe a failure mode in real or fixture-driven use.
3. Name the failed assumption.
4. Move the fragile decision into a deterministic contract, state file, helper, or Python state machine.
5. Add tests and explicit user-facing recovery paths.

Examples:

- Prompt routing skipped a mandatory phase, so phase routing moved into `SquadController`, `PhaseGraph`, and `ConditionEvaluator`.
- Agents writing journals directly made history unreliable, so `echelon_result` became the contract and COMMANDER became the sole journal writer.
- Brownfield extraction commands were fat scripts, so re-* workflows were externalized into graph nodes, phase files, and agents.
- Build convergence could be claimed without truthful progress, so harness convergence became gated on task progress, fulfillment, and later fulfillment summary tables.
- Polyrepo builds could target the wrong repo, so target detection/preflight became Python-owned and spec frontmatter became the source of truth.
- Spec folders became hard to review, so artifact indexing became deterministic and regenerated without LLM tokens.
- Landing could leave users in unsafe merge states, so `echelon land` gained a state machine with prepare, verify, push, continue, and conflict policies.

### Problems Solved That Make Good Meetup Stories

Reducing prompt authority where correctness matters:

- Early Echelon relied heavily on COMMANDER as a router. Later designs repeatedly remove authority from prompt prose and give it to workflow graphs and Python.
- Meetup angle: "The LLM can reason, but it should not be the lock, clock, transaction manager, branch protection system, or final state machine."

Making long-running AI work resumable:

- The project adds state files, journals, indexes, lockfiles, `last_dispatch` concepts, resume commands, blocked banners, run directories, and preserved worktrees.
- Meetup angle: "Autonomous coding is mostly failure recovery once the happy path works."

Turning "done" into evidence:

- The history moves from agent verdicts toward progress integrity, fulfillment reports, task contracts, implementation maps, CodeGraph evidence, and blocking gates.
- Meetup angle: "A build is not complete because the agent says it is complete; it is complete when the evidence connects spec, tasks, code, and verification."

Handling brownfield and polyrepo reality:

- Brownfield extraction was absorbed, renamed, externalized, and wired into the main workflow. Polyrepo target selection became explicit because prompt-side target selection was unsafe.
- Meetup angle: "Real engineering automation has to know which repo, which spec, which branch, and which artifact it is touching."

Improving human operability:

- Status commands, artifact maps, banners, exact next commands, preserve-work messages, and review-fix artifacts all show a shift toward making the system understandable while it works.
- Meetup angle: "The operator experience is not decoration; it is how engineers trust an autonomous loop."

### Suggested Narrative Arc for the Meetup

The clean story is not "we built 41 agents." The stronger story is:

1. We started by splitting AI engineering work into specialized agents.
2. That exposed the real problem: coordination, memory, state, and verification.
3. We externalized workflows and made agent outputs contractual.
4. We moved routing, Git, sandboxing, progress, fulfillment, and landing into deterministic Python.
5. We kept the AI where it is valuable: interpreting requirements, proposing designs, implementing code, explaining failures, and synthesizing review feedback.
6. The project matured by converting every observed failure into a guardrail.

## 14. Best-Practice Lens and Four Engineering Tracks

This section frames Echelon against current OpenAI/Anthropic-style agent engineering guidance. It is intentionally balanced: what the project does well, what is still risky, and how to explain its evolution as prompt engineering -> context engineering -> harness engineering -> loop engineering.

External references used for this assessment:

- OpenAI prompt engineering guidance: https://developers.openai.com/api/docs/guides/prompt-engineering
- OpenAI Agents SDK guardrails guidance: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI context compaction guidance: https://developers.openai.com/api/docs/guides/compaction
- Anthropic prompt engineering overview: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- Anthropic context window guidance: https://platform.claude.com/docs/en/build-with-claude/context-windows
- Anthropic prompting best practices for long-context work: https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices
- Anthropic "Building Effective Agents": https://www.anthropic.com/engineering/building-effective-agents

### What Echelon Does Well

Workflow before autonomy:

- Anthropic draws a useful distinction between workflows, where LLMs and tools follow predefined code paths, and agents, where the model dynamically controls process and tool use. Echelon's strongest recent direction matches the workflow side: Python routes phases, owns state transitions, and leaves LLMs to perform bounded reasoning/work inside those phases.
- This is especially visible in the move from COMMANDER-as-router to `SquadController`, `PhaseGraph`, `ConditionEvaluator`, `StateStore`, and harness-owned build/verify/land flows.

Clear role decomposition:

- The agent-layer model maps well to prompt-engineering guidance that asks developers to define role, task, context, output format, and constraints explicitly.
- Echelon does this through agent files, command wrappers, phase files, named verdicts, output contracts, and layer-specific responsibilities.
- Strong examples: SCOUT discovers, SAGE critiques, CARTOGRAPHER writes requirements, SENTINEL handles test architecture, IMPLEMENTER writes code, SPEC GUARD verifies compliance, VERIFICATION backpropagates coverage.

Structured outputs instead of prose-only results:

- `echelon_result` is a good implementation of the "make outputs parseable and contract-shaped" principle.
- It reduces ambiguity around verdicts, state updates, journal entries, and artifacts written.
- This also makes later validation, indexing, and recovery possible.

Context is treated as an engineered resource:

- Anthropic's context guidance warns that more context is not automatically better and calls out context degradation in long sessions. Echelon has clearly converged on the same lesson.
- The project moves durable context into files: workflow graphs, state JSON, artifact indexes, reasoning journals, run directories, MemPalace requirements, and generated reports.
- Instead of trusting chat history, commands reconstruct context from authoritative artifacts.

Guardrails exist at multiple levels:

- OpenAI's guardrails guidance separates input, output, and tool-call checks. Echelon has analogous layers even though it is not using that SDK directly: preflight checks, prompt contracts, output contracts, deterministic helper validation, Docker sandboxing, GitOps safeguards, fulfillment gates, land gates, and security specialist review.
- The better pattern is not one giant "be safe" instruction; it is checks at the point where damage can happen.

The harness separates reasoning from execution:

- Running LLM reasoning on the host while executing deterministic build/test/verify steps in isolated worktrees and Docker is a strong architecture.
- It recognizes that code execution, Git state, network access, credentials, and filesystem mutation are infrastructure problems, not just prompt problems.

The system has recovery paths:

- Sticky escalation blocks, `resume`, `continue`, state backups, preserved worktrees, exact next-step banners, and artifact indexes make failures operational instead of mysterious.
- This aligns with production-agent thinking: agentic systems need observability, stop conditions, and repair paths.

### What Is Not Yet Ideal or Needs Care

Complexity is high:

- Anthropic recommends starting with the simplest solution and adding agentic complexity only when it pays for itself. Echelon has many agents, workflows, config values, templates, and state files.
- For a meetup, this should be framed honestly: the current architecture is justified by complex software-delivery workflows, but the same pattern would be too heavy for many simpler automation tasks.

Some prompts are still large:

- Internal best-practices docs still list large prompt files such as `agents/exploration/sage.md`, `workflow/phases/build-8-finalize.md`, and `agents/learning/auditor.md`.
- Large prompts increase token cost, make instructions harder to audit, and can hide conflicting rules.
- The repo has already started extracting templates and appendices, but mode splits and workflow-phase splits remain risky unless the loader explicitly supports them.

Historical prompts show credential stacking and overconfidence:

- The prompt-engineering review identifies invented biography-style claims such as "200+ threat models" or "50+ outages prevented" in some specialist prompts.
- This is weak by OpenAI/Anthropic standards: prompts should establish role and standards without unverifiable authority claims.
- Better framing: "Use STRIDE and OWASP; grade evidence; state uncertainty; cite artifacts."

Some guardrails live in prompts where code would be stronger:

- The history shows many fixes where prompt rules had to be paired, repeated, or hardened.
- That is useful, but repeated "NEVER" rules are usually a smell that the invariant belongs in code, schema validation, or a deterministic helper.
- Echelon's evolution already recognizes this; the remaining risk is uneven migration.

Evaluation is broad but could be more outcome-oriented:

- The repo has many tests and validation suites, but the dossier did not find a single clear eval dashboard tying prompt/workflow changes to longitudinal task success, cost, latency, rework, or human intervention rate.
- For agentic systems, unit tests are necessary but not enough. A strong next step would be scenario evals that measure end-to-end outcomes across representative specs.

Review-loop classification is heuristic:

- Text-pattern detection for blocking PR comments is pragmatic but can misclassify.
- This is acceptable as a first layer, but should be paired with human override, audit logs, and ideally eval data showing precision/recall.

Security posture is promising but not complete from visible evidence:

- Docker isolation, credential checks, network allowlists, GUARDIAN, path/YAML safety modules, and land safeguards are good.
- Missing or unclear from this pass: dependency scanning, formal threat model coverage, AI-provider data handling policy, and operational audit expectations for autonomous merges.

### Evolution Through Four Engineering Tracks

Prompt engineering: from big instructions to role and output contracts.

- Early phase: agent prompts encode roles, behaviors, quality gates, and "NEVER" rules directly.
- Improvements: codename-first naming, role separation, ALWAYS/NEVER pairing, output templates, `echelon_result`, evidence grades, structured verdicts.
- Good: clear specialist responsibilities and parseable outputs.
- Risk: large prompts, repeated prohibitions, and occasional unverifiable persona claims.
- Meetup artifact to show: an agent prompt before/after `echelon_result`, or the best-practices review around paired rules and extracted templates.

Context engineering: from conversation memory to reconstructable state.

- Early phase: routing and journal context depended too much on what COMMANDER remembered in the active conversation.
- Improvements: externalized `workflow/definition.yaml`, phase files, reasoning journal, journal index, state JSON, run directories, artifact indexes, MemPalace wing-scoped requirements, deterministic spec paths.
- Good: context becomes portable across compaction, resume, and new sessions.
- Risk: many files can drift unless ownership and regeneration rules stay crisp.
- Meetup artifact to show: `workflow/definition.yaml`, `state.json`, `ARTIFACTS.md`, and the journal refactor design.

Harness engineering: from "agent runs commands" to controlled execution substrate.

- Early phase: AI-driven build work could mutate a repo and then depend on prompt-side discipline to cleanly report status.
- Improvements: worktrees, Docker sandbox, provider abstraction, GitOps manager, config cascade, resource limits, network allowlist, credential leak detection, target preflight, land state machine.
- Good: the harness owns irreversible or risky operations.
- Risk: Docker/Git/provider dependencies make setup and debugging more operationally demanding.
- Meetup artifact to show: `src/harness/ralph.py`, `src/harness/docker_provider.py`, `src/harness/gitops.py`, and polyrepo target preflight.

Loop engineering: from one-shot generation to measured convergence.

- Early phase: success could be interpreted as an agent verdict or a build command result.
- Improvements: outer/inner Ralph loop, same-failure detection, no-progress escalation, fulfillment refresh, progress integrity, review-fix reentry, verify-spec reconciliation, artifact refresh on convergence, block-on-summary-table gates.
- Good: Echelon turns AI coding into a feedback system.
- Risk: loops need strong stopping criteria; otherwise they can spend tokens without meaningful progress.
- Meetup artifact to show: a failed verify result feeding the next iteration, a fulfillment report blocking land, or a review comment becoming `review-fix-{n}.md`.

### Suggested Slide Framing

Use a four-column slide:

| Track | What changed | Engineering value | Demo file |
|---|---|---|---|
| Prompt engineering | Roles, contracts, structured outputs | Less ambiguous agent behavior | `extension/agents/...`, `echelon_result` |
| Context engineering | State/artifacts over chat memory | Resumable, compaction-safe workflows | `workflow/definition.yaml`, `ARTIFACTS.md` |
| Harness engineering | Worktrees/Docker/GitOps | Safer execution and delivery | `src/harness/ralph.py`, `docker_provider.py` |
| Loop engineering | Verify/retry/reconcile/land gates | Evidence-based convergence | fulfillment reports, review-fix tasks |

The talk track can be: "We did not just improve prompts. We progressively moved from prompt engineering to system engineering around the prompt."

## 15. Reusable Lessons for Other Teams

Patterns worth copying:

- Put AI workflow routing in a versioned, reviewable graph instead of burying it in one prompt.
- Treat prompt outputs as structured contracts, not prose.
- Keep state transitions deterministic and validated.
- Use isolated worktrees for autonomous implementation attempts.
- Run untrusted or AI-generated build/test commands in a constrained sandbox.
- Generate artifact indexes for humans.
- Separate requirements-quality checks from implementation-quality checks.
- Model PR review feedback as new work items that re-enter the build loop.
- Keep command wrappers thin and centralize shared behavior.
- Provide fallback modes, but mark fallback artifacts clearly.

Mistakes to avoid:

- Letting many prompt files drift without tests.
- Assuming memory is always current.
- Treating LLM provider CLIs as interchangeable.
- Hiding too much behavior behind automation without status/debug artifacts.
- Over-trusting numeric quality gates.
- Making sandbox allowlists too narrow or too broad without feedback.

Good conventions visible here:

- File-based artifacts over ephemeral chat state.
- Explicit agent codenames and layers.
- Structured state JSON with backups.
- Test suites for shell/prompt/template logic as well as Python.
- Clear separation between interactive spec-kit path and terminal CLI path.

## 16. Potential Demo Flow

Demo goal: show how Echelon turns an engineering request into controlled artifacts and a build loop without trying to demo every registered agent role.

Suggested 5-10 minute flow:

1. Start with `README.md` architecture or a prepared diagram.
   - Show the four-phase model and the harness diagram.
   - Explain: prompts decide and write artifacts; Python enforces state, Git, Docker, and verification.

2. Open `extension/workflow/definition.yaml`.
   - Show that routing is data-driven.
   - Point at `init`, `phase1-discover`, evidence hierarchy, and quality-gate references.

3. Open `src/harness/ralph.py`.
   - Show the core loop: build, verify, feedback, termination.
   - Highlight same-failure/no-progress escalation and state transitions.

4. Open `src/harness/state.py`.
   - Show atomic writes, lockfiles, valid transitions, and monotonic counters.
   - Tell the story: autonomous systems need boring state discipline.

5. Open `src/harness/docker_provider.py`.
   - Show credential checks and Docker sandbox creation.
   - Connect it to the risk of running AI-generated build commands.

6. Optional branch based on audience:
   - For AI workflow audience: show an agent file and `echelon_result` contract from README.
   - For systems audience: show `src/harness/coordinator.py` parallel strategy fan-out.
   - For requirements audience: show `src/understanding/cli.py` and quality gates.
   - For memory audience: show codegen requirement mining/search and `PipelineEngine.run_re_phase`.

7. End with a simulated or recorded output.
   - Show `ARTIFACTS.md`, a harness state file, a fulfillment report, or a review-fix task.
   - Avoid a live long-running AI build during a short meetup.

Recommended demo input:

- A small spec folder or fixture already in the repo.
- A deliberately failing verify command, if showing loop behavior.
- A mocked PR comment, if showing review-loop behavior.

What not to demo live:

- Full `echelon run` with multiple agents.
- Real PR merge automation.
- Docker setup from scratch.
- First-run model downloads for Understanding energy metrics.

## 17. Suggested Brownbag Angles

### Angle 1: "Prompts as Workflows, Python as Guardrails"

Main story: Echelon succeeds by splitting creative/semantic work from deterministic orchestration. Prompts own roles and artifacts; Python owns state, retries, sandboxes, Git, and verification.

Why engineers care: this is a reusable architecture for AI tools that need to be more reliable than a chat transcript.

Show:

- `extension/workflow/definition.yaml`
- `src/harness/ralph.py`
- `src/harness/state.py`
- An example `echelon_result` contract from README

Avoid:

- Listing all 41 agents in detail.
- Over-selling full autonomy.

### Angle 2: "Building a Safe Autonomous Build Loop"

Main story: the core engineering challenge is not getting an AI to write code once; it is safely looping through build, verify, feedback, retry, and escalation.

Why engineers care: this applies to any autonomous coding or CI-repair tool.

Show:

- `RalphController`
- Docker sandbox credential/network/resource controls
- GitOps worktree isolation
- State termination reasons

Avoid:

- Long philosophical discussion of agents.
- Live unbounded build execution.

### Angle 3: "From Requirements to Code Without Losing Traceability"

Main story: Echelon treats requirements as first-class artifacts with quality metrics, artifact indexes, fulfillment checks, and memory.

Why engineers care: traceability is usually where AI-assisted coding gets fuzzy.

Show:

- `understanding` CLI quality gates
- `artifact_index.py`
- `kernel.fulfillment`
- MemPalace requirements mining/search

Avoid:

- Deep SOAR internals unless the audience already knows SOAR.

### Angle 4: "Review Feedback as an Automated Rework Loop"

Main story: PR comments are not just messages; they can become structured tasks that re-enter the build/verify loop.

Why engineers care: many teams lose time translating review feedback into concrete fixes.

Show:

- `src/harness/review_loop.py`
- Blocking-comment pattern matching
- `echelon.review` command purpose
- `review-fix-{n}.md` task flow from README

Avoid:

- Claiming it replaces human review.
- Demoing real reviewer credentials.

### Angle 5: "Engineering an AI System That Can Resume"

Main story: long AI workflows fail in mundane ways: interruptions, compaction, partial writes, stale locks, token budgets, repeated failures. Echelon’s interesting work is making those recoverable.

Why engineers care: reliability is mostly about failure modes.

Show:

- `StateStore`
- `StrategyCoordinator` blocked-run checks
- `RalphController` resume/termination handling
- README journal compaction-safety explanation

Avoid:

- Too much product narrative.
- Deep-diving every state file format.

### Angle 6: "From Prompt Engineering to Loop Engineering"

Main story: Echelon started with better prompts, but the real progress came from engineering the environment around the prompts: durable context, deterministic harnesses, and feedback loops.

Why engineers care: this is a practical maturity model for AI-assisted software delivery.

Show:

- Prompt engineering: role files and `echelon_result`
- Context engineering: `workflow/definition.yaml`, state files, `ARTIFACTS.md`
- Harness engineering: `RalphController`, Docker provider, GitOps
- Loop engineering: fulfillment gates, review-fix reentry, verify-spec reconciliation

Avoid:

- Presenting "prompt engineering" as the whole solution.
- Making the talk provider-specific; use OpenAI/Anthropic best practices as an external lens, not as the main subject.

## 18. Missing Information

Questions for engineers:

- Which workflow path is used most in practice: interactive spec-kit commands, terminal `echelon`, harness, or codegen?
- Which parts are stable production paths vs experimental or research paths?
- What are the most common failure modes in real runs?
- How often does the review loop successfully fix comments without manual intervention?
- Which tests are required before release, and which are optional/local?
- Is CLI version `2.2.0` intentionally separate from package version `1.5.0`?
- How often are agent prompts reviewed, and what process prevents prompt drift?

Questions for product / stakeholders:

- What is the main value proposition to emphasize: speed, quality, safety, traceability, or learning?
- Who is the target internal audience: AI-tool builders, product engineers, platform engineers, or managers?
- What project example can be shown without exposing sensitive data?
- What outcome should attendees leave believing or trying?

Questions for operations / support:

- What are the real deployment environments for Echelon itself beyond local install?
- What is the support process when a harness run blocks?
- How are stale Docker containers, worktrees, and memory stores cleaned in normal usage?
- Are there dashboards or only file/CLI-based observability?
- What is the known-good setup path for a fresh engineer machine?

Questions for security / infrastructure:

- What code/data may be sent to AI provider CLIs in current policy?
- Are MemPalace contents considered sensitive, and how are they cleaned or backed up?
- Is dependency vulnerability scanning used outside the visible GitHub Actions workflow?
- Are sandbox network allowlists centrally reviewed?
- How are `gh`/`glab` credentials scoped for automated PR operations?
- Are there audit requirements for autonomous merges or local deploys?
