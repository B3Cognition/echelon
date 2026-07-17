# EGR-151 Git Ownership Boundary Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic project-local boundary that can inspect,
disable, and verify spec-kit Git integration without activating the ownership
cutover before Echelon's replacement branch lifecycle exists.

**Architecture:** A focused `echelon.speckit_git` module reads the project-local
spec-kit registry and hook configuration without importing spec-kit internals.
It treats absent Git integration as safe, fails closed on enabled,
inconsistent, or malformed state, and uses the supported spec-kit CLI for an
idempotent disable operation with a verified postcondition. This foundation is
intentionally not wired into `workspace init` or `spec run` yet: activating it
before Echelon creates branches/spec directories would break first-pass WHAT.

**Tech Stack:** Python 3.11+, `json`, PyYAML, `subprocess`, pytest, temporary
project directories.

## Global Constraints

- Echelon is the sole Git authority after the future atomic cutover; spec-kit
  remains responsible for artifact generation.
- `specify extension disable git` is the supported mutation path.
- Inspection and tests require no LLM, Docker, or network access.
- Missing/uninstalled spec-kit Git integration is safe; enabled, inconsistent,
  or malformed integration fails closed.
- The disablement helper must verify the resulting registry and hook state.
- Do not wire disablement into initialization or Phase A until Echelon-owned
  branch/spec bootstrap and checkpoint-gated switching are ready.
- Existing user changes and unrelated EGR register rows must be preserved.

---

### Task 1: Project-Local Spec-Kit Git State

**Files:**
- Create: `src/echelon/speckit_git.py`
- Create: `tests/unit/test_speckit_git.py`

**Interfaces:**
- Produces: `SpecKitGitState`, `SpecKitGitOwnershipError`,
  `inspect_speckit_git(project_root: Path) -> SpecKitGitState`,
  `require_speckit_git_disabled(project_root: Path) -> SpecKitGitState`, and
  `disable_speckit_git(project_root: Path, *, run=...) -> SpecKitGitState`.
- Consumes: `.specify/extensions/.registry`, `.specify/extensions.yml`, and the
  installed `specify extension disable git` command.

- [x] **Step 1: Write failing state-inspection tests**

  Covered absent Git integration, registry-enabled Git, registry-disabled Git,
  enabled hook inconsistency, malformed registry/config, and disabled hook state
  using real temporary files.

- [x] **Step 2: Run the focused tests and verify RED**

  Run: `pytest tests/unit/test_speckit_git.py -q`

  Observed: collection failed with `ModuleNotFoundError: echelon.speckit_git`.

- [x] **Step 3: Implement minimal read-only inspection and fail-closed guard**

  The implementation parses both project-local files and returns a frozen state
  containing `safe`, `installed`, `registry_enabled`, `enabled_hooks`, and
  `reason`. Unsafe state raises `SpecKitGitOwnershipError` with the supported
  recovery command.

- [x] **Step 4: Add disablement tests**

  Covered idempotent absent/disabled state, the exact subprocess command and
  working directory, non-zero CLI failure, and false success that leaves Git
  integration enabled.

- [x] **Step 5: Implement verified disablement and verify GREEN**

  Run: `pytest tests/unit/test_speckit_git.py -q`

  Observed: `10 passed`.

### Task 2: Foundation Verification And Handoff

**Files:**
- Modify: `docs/findings/echelon-grounded-review-register.md`
- Modify: `docs/findings/2026-07-17-egr-151-exclusive-spec-gitops.md`
- Modify: `docs/superpowers/specs/2026-07-17-spec-switch-lifecycle-design.md`

**Interfaces:**
- Consumes: Task 1's tested ownership boundary.
- Produces: EGR-151 tracking and an explicit activation guard for the next
  Echelon-owned branch/spec-bootstrap plan.

- [x] **Step 1: File EGR-151 and link the accepted design**

  The register contains EGR-151 as P1/in-progress and GitHub issue #164 tracks
  the finding.

- [x] **Step 2: Record the atomic-cutover constraint**

  The design states that the inspector/disablement boundary is implemented
  first, but runtime disablement cannot activate until Echelon's replacement
  branch/spec bootstrap and checkpoint-gated switch path are ready.

- [x] **Step 3: Verify the foundation change set**

  Run:

  ```bash
  pytest tests/unit/test_speckit_git.py \
    tests/unit/test_workspace_init_deploy_runtime.py \
    tests/unit/test_cli_mode_args.py \
    tests/unit/test_cli_continue.py \
    tests/unit/test_cli_resume_escalation_options.py -q
  git diff --check
  ```

  Observed: `72 passed`; `git diff --check` reported no errors.

- [x] **Step 4: Commit the foundation on the EGR feature branch**

  Staged only the EGR-151 design/finding/plan, `src/echelon/speckit_git.py`, and
  `tests/unit/test_speckit_git.py`, then committed with:

  ```bash
  git commit -m "feat: start EGR-151 exclusive Git ownership"
  ```

## Next Plan Boundary

The next independently testable plan begins with an Echelon-owned Phase A Git
bootstrap service. It must resolve the default branch, allocate the spec ID and
slug, create the sibling feature branch from the recorded default commit, seed
run state with `spec_id`, `spec_dir`, and `feature_branch`, and pass an explicit
`SPECIFY_FEATURE_DIRECTORY` into artifact-only `speckit.specify`. Checkpoint and
switch safety then land before this plan's disablement helper is activated in
workspace initialization or managed Phase A preflight.
