# Phase A Provider-Neutral Capability Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve GitHub issue #177 by replacing provider-native tool names in canonical Phase A prose with Echelon capability language and preventing regressions.

**Architecture:** Extend the existing prompt-contract scanner with a Phase A-specific body scanner over both agent files and runtime-appended phase specifications. Migrate only explicit provider API language; preserve ordinary artifact instructions, prompt frontmatter, and controller behavior.

**Tech Stack:** Python 3.11+, pytest, Markdown agent prompts, existing prompt contract utilities.

## Global Constraints

- Preserve Phase A graph routing, artifacts, strict `echelon_result` contracts, and controller ownership.
- Do not add provider-specific OpenAI tool names to canonical prompts.
- Do not absorb issue #178 timing/preflight migration into this change.
- Follow red-green-refactor and keep the scanner conservative enough to allow ordinary prose verbs.

---

### Task 1: Provider-Native Prompt Contract

**Files:**
- Modify: `tests/contract/prompt_tool_contracts.py`
- Modify: `tests/unit/test_prompt_tool_contracts.py`

**Interfaces:**
- Produces: `scan_phase_a_provider_native_language(root, paths=None) -> list[PromptToolContractFinding]`.
- Consumes: parsed Markdown body text from `harness.prompt_markdown.parse_prompt_markdown`.

- [x] Add unit tests that reject `WebSearch`, `WebFetch`, `ToolSearch`, named provider tool phrases, mutation API arguments, and delegated `Agent tool` instructions.
- [x] Add unit tests that accept ordinary read/write/edit verbs and ignore frontmatter tool metadata.
- [x] Add a repository-wide assertion for all canonical Phase A agent bodies.
- [x] Run the focused tests and confirm the repository-wide assertion fails on current prompts.
- [x] Implement the minimal scanner and rerun focused tests until only current prompt violations remain.

### Task 2: Canonical Prompt Migration

**Files:**
- Modify: `extension/agents/exploration/cartographer.md`
- Modify: `extension/agents/exploration/sage.md`
- Modify: `extension/agents/exploration/scout.md`
- Modify: `extension/agents/specialists/investigator.md`
- Modify: `extension/agents/control/commander.md`
- Modify: `extension/agents/learning/auditor.md`
- Modify: `extension/agents/learning/realist.md`
- Modify: `extension/agents/solution/architect.md`
- Modify: `extension/workflow/phases/phase1-*.md`
- Modify: `extension/workflow/phases/phase2-*.md`
- Modify: `extension/workflow/phases/phase3-*.md`
- Modify: `extension/workflow/phases/phase4-document.md`
- Modify: `extension/workflow/phases/phase-exp-constitution-quality.md`

**Interfaces:**
- Consumes: runtime-exposed workspace, research, experiment, and delegation capabilities.
- Preserves: every existing artifact path, evidence grade, output requirement, and fail-closed boundary.

- [x] Replace explicit provider tool APIs with capability-oriented instructions and explicit unavailable-capability behavior.
- [x] Remove provider-native dispatch syntax from phase specifications appended to executing agents.
- [x] Add a structured INVESTIGATOR `BLOCKED` fallback for unavailable required research capabilities.
- [x] Run the repository-wide scanner and confirm no Phase A body violations remain.
- [x] Review the diff for accidental flow, artifact, or output-contract changes.

### Task 3: Regression Verification

**Files:**
- Modify focused tests only if an existing assertion encodes provider-native wording.

**Interfaces:**
- Produces: fresh evidence that prompt and workflow contracts remain valid.

- [x] Run `pytest -q tests/unit/test_prompt_tool_contracts.py tests/kernel/test_prompt_references.py tests/contract`.
- [x] Run `bash scripts/bash/dry-run.sh`.
- [x] Run `git diff --check`.
- [x] Run `pytest -q` and report any unrelated residual failures separately.
