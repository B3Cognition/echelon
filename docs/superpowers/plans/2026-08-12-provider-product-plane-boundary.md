# Provider Product-Plane Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Echelon control prose available to the host while preventing dispatched providers from discovering it as workspace content.

**Architecture:** A shared provider-boundary helper injects an explicit prompt contract and forbidden-root metadata at the provider facade. Companion assembly removes path breadcrumbs before invocation, installation removes transient package staging, and delivery synchronization stops generating provider-native prose copies.

**Tech Stack:** Python 3, pytest, Prosaic CLI, existing AI CLI backend adapters

## Global Constraints

- Keep `.echelon/prosaic` and `.echelon/runtime` as deployed control-plane sources.
- Preserve unrelated dirty changes in runtime configuration, squad control, and their tests.
- Never widen an existing dispatch-specific read or write scope.
- Do not claim hard containment for a provider without a verified mechanism.

---

### Task 1: Remove instruction breadcrumbs from assembled prompts

**Files:**
- Modify: `src/harness/prompt_companions.py`
- Test: `tests/unit/test_prosaic_prompt_loader.py`

**Interfaces:**
- Consumes: package Markdown references recognized by `prompt_companion_references()`
- Produces: `append_prompt_companions(body, roots) -> str` with recursively embedded, path-free companion sections

- [x] Add tests requiring resolved references to disappear, neutral embedded headings to be present, recursive references to be sanitized, and unresolved references to raise.
- [x] Run the focused tests and verify the new assertions fail for the current implementation.
- [x] Implement deterministic recursive resolution and sanitization without changing the public loader API.
- [x] Run the focused tests and verify they pass.

### Task 2: Apply the product-plane contract at the provider facade

**Files:**
- Create: `src/harness/provider_workspace_scope.py`
- Modify: `src/harness/llm_provider.py`
- Test: `tests/unit/test_llm_provider.py`

**Interfaces:**
- Produces: `apply_product_plane_boundary(cwd, prompt, request_metadata) -> tuple[str, dict[str, object]]`
- Preserves: all caller metadata, including narrower `tool_read_roots` and `tool_write_paths`

- [x] Add parameterized tests for prompt and agent entry points, contract idempotence, absolute forbidden roots, and preservation of existing metadata.
- [x] Run the focused tests and verify failure before implementation.
- [x] Implement the helper and invoke it before every backend dispatch.
- [x] Run the focused tests and verify they pass.

### Task 3: Enforce forbidden roots in supported backends

**Files:**
- Modify: `src/harness/ai_cli_backends/claude.py`
- Modify: `src/harness/ai_cli_backends/openai_compatible.py`
- Test: `tests/unit/test_ai_cli_backend.py`

**Interfaces:**
- Consumes: `prompt_metadata.tool_forbidden_roots`
- Consumes: narrow operational roots, literal config inputs, and metadata-only
  workspace-root detection paths
- Produces: hard rejection for OpenAI-compatible filesystem tools and Claude host containment when available

- [x] Add tests for direct reads, broad list/grep traversal, and ordinary Claude fallback when `sandbox-exec` is unavailable.
- [x] Run the focused tests and verify the expected failures.
- [x] Reject forbidden paths in the OpenAI-compatible registry and make ordinary Claude enforcement best-effort while retaining explicit fail-closed scopes.
- [x] Embed referenced runtime templates and schemas before dispatch; verify the
  real ORCHESTRATOR prompt contains all six planning templates without paths.
- [x] Permit explicitly named runtime helpers with read-only scripts access,
  literal config-file inputs, and metadata-only `.echelon` root detection.
- [x] Run the focused tests and verify they pass.

### Task 4: Remove redundant prose materialization

**Files:**
- Modify: `src/echelon/prosaic_packages.py`
- Modify: `src/harness/gitops.py`
- Modify: `tests/unit/test_prosaic_package_install.py`
- Modify: `tests/unit/test_gitops_worktree.py`
- Delete: `tests/unit/test_prosaic_provider_deployment.py`

**Interfaces:**
- Preserves: deployed `.echelon/prosaic` and `.echelon/runtime`
- Removes: `.echelon/packages` staging and provider-native delivery prose deployment

- [x] Change installation tests to require staging cleanup on success and failure.
- [x] Change delivery tests to require no provider-native deployment for any provider.
- [x] Run the focused tests and verify failure against current behavior.
- [x] Remove staging in `finally` and remove the provider deployment path from GitOps.
- [x] Run the focused tests and verify they pass.

### Task 5: Regression verification

**Files:**
- Verify only

**Interfaces:**
- Consumes: all behavior from Tasks 1-4
- Produces: evidence that prompt loading, provider dispatch, package installation, and delivery worktrees remain functional

- [x] Run the focused unit suites for prompt loading, providers, package installation, and GitOps.
- [x] Run the complete unit suite.
- [x] Inspect `git diff --check` and the final diff, confirming unrelated dirty files were not modified.
