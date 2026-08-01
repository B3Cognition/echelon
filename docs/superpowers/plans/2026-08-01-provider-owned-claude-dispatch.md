# Provider-Owned Claude Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route every Echelon Claude command through `AICodingCliProvider` while retaining live stream output, honoring configured dangerous permissions, and limiting Claude task-tool restriction to build execution.

**Architecture:** Add a request-scoped `canonical_task_execution` metadata flag consumed by `ClaudeCliBackend` when building its stream-JSON command. Simplify `echelon/cli.py` so it only selects and renders command prose, then delegates every non-native-OpenCode execution to `AICodingCliProvider.run_prompt_result`.

**Tech Stack:** Python 3.11, pytest, Echelon AI CLI backend protocol.

## Global Constraints

- `.echelon/prosaic/commands/` remains directory-presence opt-in; absence retains legacy source lookup.
- Only build execution sets `canonical_task_execution`; review, generic commands, and Prosaic commands do not.
- `allow_unsafe_host_execution` with approval reason must emit `--dangerously-skip-permissions` for Claude.
- No global `--disallowedTools TaskCreate,TaskUpdate`; it is emitted only for canonical build execution.
- Preserve Claude stream-JSON live output, configured `CLAUDE_CONFIG_DIR`, model metadata, timeout handling, and result exit codes.
- Do not add model-tier/effort mapping, installer behavior, or Prosaic target rendering.
- Remove the mistakenly tracked `.superpowers/sdd/.../task-3-report.md` from Git; leave the ignored local scratch copy intact.

---

### Task 1: Make Claude task-tool restriction request-scoped

**Files:**
- Modify: `src/harness/ai_cli_backends/claude.py:22-34`
- Modify: `tests/unit/test_ai_cli_backend.py:2884-3000`
- Modify: `tests/unit/test_llm_provider.py:150-180`

**Interfaces:**
- Consumes: `CliRunRequest.metadata["canonical_task_execution"]: bool`.
- Produces: `ClaudeCliBackend.run_prompt()` with `--disallowedTools TaskCreate,TaskUpdate` only when that metadata value is `True`.

- [ ] **Step 1: Write failing backend tests**

  Add tests that capture the Claude command from `subprocess.Popen`:

  ```python
  def test_claude_backend_allows_task_tools_without_canonical_task_metadata(...):
      result = backend.run_prompt(CliRunRequest(..., metadata={}))
      assert result.exit_code == 0
      assert "--disallowedTools" not in captured["command"]

  def test_claude_backend_restricts_task_tools_for_canonical_task_execution(...):
      result = backend.run_prompt(
          CliRunRequest(..., metadata={"canonical_task_execution": True})
      )
      assert result.exit_code == 0
      assert captured["command"][captured["command"].index("--disallowedTools") + 1] == "TaskCreate,TaskUpdate"
  ```

  Preserve the existing dangerous-permissions test and assert it still sees
  `--dangerously-skip-permissions` when `allow_unsafe_host_execution=True`.

- [ ] **Step 2: Verify the expected red failure**

  Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py -q`

  Expected: the no-metadata test fails because the backend currently always
  disallows task tools.

- [ ] **Step 3: Implement the explicit metadata gate**

  In `ClaudeCliBackend.run_prompt`, derive a strict boolean and pass it to the
  existing command builder:

  ```python
  canonical_task_execution = request.metadata.get("canonical_task_execution") is True
  cmd = build_llm_cli_command(
      "claude",
      self._bin,
      request.prompt,
      self._config.llm.tool_policy,
      stream_json=True,
      disallow_claude_task_tools=canonical_task_execution,
  )
  ```

- [ ] **Step 4: Verify the focused tests pass**

  Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py -q`

  Expected: PASS.

- [ ] **Step 5: Commit Task 1**

  ```bash
  git add src/harness/ai_cli_backends/claude.py tests/unit/test_ai_cli_backend.py tests/unit/test_llm_provider.py
  git commit -m "Scope Claude task tool restrictions"
  ```

### Task 2: Remove direct Claude execution from the CLI

**Files:**
- Modify: `src/echelon/cli.py:8790-9060`
- Modify: `tests/unit/test_cli_llm_tool_policy.py:70-240`
- Delete from Git: `.superpowers/sdd/2026-08-01-prosaic-additive-preparation/task-3-report.md`

**Interfaces:**
- Consumes: `RenderedProsaicCommand | None` from `_load_prosaic_command` and `AICodingCliProvider.run_prompt_result(..., request_metadata=...)`.
- Produces: provider-owned Claude dispatch. Legacy build requests use `request_metadata={"canonical_task_execution": True}`; Prosaic metadata remains nested under `prompt_metadata`.

- [ ] **Step 1: Write failing CLI dispatch tests**

  Add one legacy-Claude test and one Prosaic-Claude test using a fake provider:

  ```python
  def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
      calls.append((worktree_path, prompt, request_metadata))
      return SimpleNamespace(exit_code=0)

  assert calls[0][2] is None  # legacy review
  assert calls[0][2] == {"prompt_metadata": {"model_tier": "balanced"}}  # Prosaic review
  ```

  Add a legacy build assertion:

  ```python
  assert calls[0][2] == {"canonical_task_execution": True}
  ```

  Ensure the Prosaic Claude test would fail if `run_prompt_result` is bypassed.

- [ ] **Step 2: Verify the expected red failure**

  Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_llm_tool_policy.py -q`

  Expected: legacy Claude still calls `_run_claude_streaming`, rather than the
  fake provider’s `run_prompt_result`.

- [ ] **Step 3: Simplify CLI dispatch**

  Remove `_print_event`, `_run_claude_streaming`, and their now-unused imports.
  After the native OpenCode fallback, route every command through one provider
  call:

  ```python
  metadata = None
  if prosaic_command is not None:
      metadata = {"prompt_metadata": prosaic_command.frontmatter}
  elif command == "build":
      metadata = {"canonical_task_execution": True}

  result = AICodingCliProvider(config).run_prompt_result(
      str(project_dir), prompt, request_metadata=metadata
  )
  sys.exit(result.exit_code)
  ```

  For native non-build commands, keep `metadata=None`. Retain legacy prompt
  rendering and OpenCode native command execution exactly as before.

- [ ] **Step 4: Remove the tracked scratch report only**

  Run:

  ```bash
  git rm --cached .superpowers/sdd/2026-08-01-prosaic-additive-preparation/task-3-report.md
  ```

  Do not delete the local ignored report file.

- [ ] **Step 5: Verify the focused suite passes**

  Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_prosaic_export.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_typer_app.py tests/unit/test_llm_provider.py tests/unit/test_ai_cli_backend.py -q`

  Expected: PASS.

- [ ] **Step 6: Commit Task 2**

  ```bash
  git add src/echelon/cli.py tests/unit/test_cli_llm_tool_policy.py
  git commit -m "Route Claude commands through provider backend"
  ```

### Task 3: Verify the consolidated provider boundary

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-provider-owned-claude-dispatch-design.md` only if implementation reveals a material contract difference.

- [ ] **Step 1: Run the full suite**

  Run: `/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest`

  Expected: PASS.

- [ ] **Step 2: Run static checks**

  Run:

  ```bash
  /Users/michalbachorik/work/echelon_r/echelon/.venv/bin/python -m compileall -q src
  git diff --check
  git status --short
  ```

  Expected: compilation and whitespace checks pass; no tracked process report
  remains.

- [ ] **Step 3: Commit a material design correction if needed**

  ```bash
  git add docs/superpowers/specs/2026-08-01-provider-owned-claude-dispatch-design.md
  git commit -m "Document Claude provider dispatch"
  ```

  Do not create this commit when the design remains accurate.
