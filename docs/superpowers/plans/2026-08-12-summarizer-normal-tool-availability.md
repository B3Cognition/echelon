# SUMMARIZER Normal Tool Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the dedicated fast, low-effort SUMMARIZER agent through every configured provider, including Codex, by using normal provider tool availability instead of a restrictive tool profile.

**Architecture:** Remove the summarizer's `tools: none` metadata and delete backend behavior that interprets that metadata specially. Preserve passive synthesis in the agent prompt and retain the empty temporary working directory, bounded evidence, quiet dispatch, 30-second timeout, strict JSON validation, and deterministic fallback.

**Tech Stack:** Python 3.11+, Prosaic Markdown frontmatter, existing AI CLI backends, pytest.

## Global Constraints

- Apply the same normal tool-availability contract to Claude, Codex, Copilot, OpenCode, and OpenAI-compatible providers.
- Keep `model_tier: fast` and `effort: low` on `echelon.summarizer`.
- Keep the prompt's paired ALWAYS/NEVER rule prohibiting repository inspection, commands, and tool use.
- Keep summary execution in an empty temporary directory with a 12 KiB evidence cap and 30-second timeout.
- Keep quiet provider dispatch, strict JSON validation, and deterministic fallback.
- Do not change normal backend behavior for prompts that explicitly declare another tools profile.

---

### Task 1: Remove the restrictive SUMMARIZER tool profile

**Files:**
- Modify: `prosaic/subagents/echelon.summarizer.md`
- Modify: `tests/unit/test_worked_on_summary.py`
- Modify: `tests/unit/test_ai_cli_backend.py`
- Modify: `src/harness/ai_cli_backends/claude.py`
- Modify: `src/harness/ai_cli_backends/codex.py`
- Modify: `src/harness/ai_cli_backends/copilot.py`
- Modify: `src/harness/ai_cli_backends/openai_compatible.py`
- Modify: `src/harness/ai_cli_backends/opencode.py`

**Interfaces:**
- Consumes: `RenderedProsaicCommand.frontmatter` passed in `request_metadata["prompt_metadata"]`.
- Preserves: `generate_summary(...) -> tuple[str, ...]` and its fallback behavior.
- Produces: a SUMMARIZER invocation with `model_tier=fast`, `effort=low`, and no `tools` override.

- [ ] **Step 1: Write failing provider-neutral metadata tests**

Change the SUMMARIZER dispatch assertion to require normal tool availability:

```python
metadata = call["request_metadata"]["prompt_metadata"]
assert metadata["model_tier"] == "fast"
assert metadata["effort"] == "low"
assert "tools" not in metadata
```

Replace the Codex fail-closed test with a real command-construction test:

```python
def test_codex_backend_runs_prompt_without_tools_override(tmp_path):
    request = CliRunRequest(
        cwd=str(tmp_path),
        prompt="Summarize evidence.",
        env={},
        timeout_s=10,
        metadata={"prompt_metadata": {"model_tier": "fast", "effort": "low"}},
    )
    result = backend.run_prompt(request)
    assert result.exit_code == 0
    popen.assert_called_once()
```

Delete tests asserting `tools: none`, Claude `--tools ""`, Copilot tool exclusion, OpenAI tool-call suppression, and Codex/OpenCode `tool_free_mode_unsupported` results.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_worked_on_summary.py \
  tests/unit/test_ai_cli_backend.py \
  tests/unit/test_prosaic_execution_policy.py
```

Expected: FAIL because the prompt still declares `tools: none` and backend-specific handling still exists.

- [ ] **Step 3: Implement normal provider availability**

Remove `tools: none` from `prosaic/subagents/echelon.summarizer.md`. Retain its passive synthesis rule verbatim:

```markdown
ALWAYS synthesize only the evidence already supplied in this prompt.
NEVER call tools, inspect a repository, execute commands, or request more context.
```

Delete only the backend branches introduced for `prompt_metadata.tools == "none"`:

```python
# Remove special tools_disabled checks and provider_error_code results.
# Let every backend follow its ordinary run_prompt/run_agent path.
```

Do not change the configured global `LlmToolPolicy`; normal provider safety settings continue to apply.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run:

```bash
.venv/bin/pytest -q \
  tests/unit/test_worked_on_summary.py \
  tests/unit/test_cli_worked_on_summary.py \
  tests/unit/test_ai_cli_backend.py \
  tests/unit/test_prosaic_execution_policy.py
bash scripts/bash/dry-run.sh
```

Expected: all tests and all bundle checks pass; Prosaic inspection reports no `tools` key for SUMMARIZER.

- [ ] **Step 5: Commit**

```bash
git add prosaic/subagents/echelon.summarizer.md \
  src/harness/ai_cli_backends/claude.py \
  src/harness/ai_cli_backends/codex.py \
  src/harness/ai_cli_backends/copilot.py \
  src/harness/ai_cli_backends/openai_compatible.py \
  src/harness/ai_cli_backends/opencode.py \
  tests/unit/test_worked_on_summary.py \
  tests/unit/test_ai_cli_backend.py \
  tests/unit/test_prosaic_execution_policy.py
git commit -m "fix: run summarizer with normal provider tools"
```

### Task 2: Prove the live Codex separate-agent path

**Files:**
- Modify only if a defect is reproduced by the live smoke test.
- Test workspace: `/Users/michalbachorik/work/echelon-hello-world-summary-smoke-Sv0TR2`

**Interfaces:**
- Consumes: the existing blocked Hello World run and `echelon spec continue` lifecycle.
- Produces: exactly one validated narrative `Worked on` section generated by the Codex SUMMARIZER path.

- [ ] **Step 1: Redeploy the feature bundle into the smoke workspace**

```bash
PYTHONPATH="$FEATURE_WORKTREE/src" "$ECHELON_VENV/echelon" workspace init \
  --llm codex --no-unsafe-host-execution
```

- [ ] **Step 2: Run the resumable lifecycle command**

```bash
PYTHONPATH="$FEATURE_WORKTREE/src" "$ECHELON_VENV/echelon" spec continue
```

Expected: the lifecycle exits with exactly one `Worked on` section and no raw provider JSON or progress output from SUMMARIZER.

- [ ] **Step 3: Verify the separate-agent dispatch from telemetry or captured provider metadata**

Confirm the summary request used `model_tier=fast`, `effort=low`, an empty temporary working directory, `quiet=true`, and completed rather than returning `tool_free_mode_unsupported`.

- [ ] **Step 4: Run final verification**

```bash
.venv/bin/pytest -q \
  tests/unit/test_worked_on_summary.py \
  tests/unit/test_cli_worked_on_summary.py \
  tests/unit/test_orchestrator.py \
  tests/unit/test_prosaic_prompt_loader.py \
  tests/unit/test_prosaic_execution_policy.py \
  tests/unit/test_run_skill.py \
  tests/unit/test_ai_cli_backend.py \
  tests/kernel/test_agent_role_catalog_docs.py
bash scripts/bash/dry-run.sh
git diff --check
```

Expected: focused tests and bundle validation pass; the worktree contains no uncommitted changes after the final commit.
