# Additive Prosaic Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare Echelon to export and consume neutral Prosaic command metadata while leaving all legacy Spec-Kit dispatch behavior intact when no Prosaic command bundle is present.

**Architecture:** The migration exporter translates legacy extension behavior into canonical Prosaic frontmatter, notably `capability` to `model_tier`, and removes the legacy key. The command loader already obtains a complete inspected artifact; the dispatch boundary will preserve its frontmatter and pass it only with Prosaic-loaded prompts into the existing provider request-metadata API. Concrete provider model-tier mapping is explicitly out of scope for this preparation.

**Tech Stack:** Python 3.11, pytest, PyYAML, Typer, Prosaic CLI JSON `inspect` output.

## Global Constraints

- Keep `.specify/extensions/echelon` and provider-native Spec-Kit command lookup operational and unchanged as the fallback.
- Prosaic activation remains directory-presence opt-in through `.echelon/prosaic/commands/`; add no configuration setting.
- Treat `extension.yml` and legacy Markdown as migration input only; generated canonical source contains no legacy `capability` or provider-specific `model` frontmatter.
- Preserve `effort`, `tools`, `color`, and `invocation` verbatim in canonical source and provider request metadata.
- Do not add a Prosaic target, concrete model mapping, or provider tool-policy behavior in this plan.
- Follow TDD: every production behavior begins with a focused failing test.

---

### Task 1: Normalize legacy capability into canonical model tier

**Files:**
- Modify: `src/harness/prosaic_export.py:91-137`
- Modify: `tests/unit/test_prosaic_export.py:12-104`

**Interfaces:**
- Consumes: manifest entries with `behavior: dict[str, object]`.
- Produces: `_normalized_artifact(entry, artifact_id_from_name) -> tuple[str, Path, dict]`, whose frontmatter has `model_tier` and never has `capability`.

- [ ] **Step 1: Write the failing export tests**

  Replace the expected agent frontmatter in the existing agent test and add a command that verifies all portable metadata survives:

  ```python
  assert yaml.safe_load(chief_frontmatter) == {
      "name": "speckit.echelon.chief",
      "description": "Canonical chief",
      "execution": "agent",
      "model_tier": "balanced",
      "tools": "full",
  }
  assert "capability:" not in chief_frontmatter

  assert yaml.safe_load(frontmatter) == {
      "name": "speckit.echelon.bugfix",
      "description": "Canonical bugfix",
      "execution": "command",
      "model_tier": "strong",
      "effort": "high",
      "tools": ["read", "edit"],
      "color": "blue",
      "invocation": "automatic",
  }
  ```

- [ ] **Step 2: Run the export tests to verify the expected failure**

  Run: `.venv/bin/pytest tests/unit/test_prosaic_export.py -q`

  Expected: FAIL because output still contains `capability` and lacks `model_tier`.

- [ ] **Step 3: Implement the minimal normalization**

  In `_normalized_artifact`, normalize only the legacy behavior copy before building frontmatter:

  ```python
  normalized_behavior = dict(behavior)
  if normalized_behavior.get("execution") == "isolated":
      normalized_behavior["execution"] = "command"
  capability = normalized_behavior.pop("capability", None)
  if capability is not None:
      normalized_behavior["model_tier"] = capability
  ```

  Do not read or merge the source Markdown frontmatter; `_markdown_body` continues to remove it.

- [ ] **Step 4: Run the export tests to verify they pass**

  Run: `.venv/bin/pytest tests/unit/test_prosaic_export.py -q`

  Expected: PASS.

- [ ] **Step 5: Commit the independent export change**

  ```bash
  git add src/harness/prosaic_export.py tests/unit/test_prosaic_export.py
  git commit -m "Normalize Prosaic model tiers"
  ```

### Task 2: Represent rendered Prosaic commands with their metadata

**Files:**
- Modify: `src/harness/prosaic_prompt_loader.py:20-76`
- Modify: `tests/unit/test_prosaic_prompt_loader.py:12-78`

**Interfaces:**
- Consumes: `ProsaicCommandArtifact(frontmatter: dict[str, Any], body: str)` from `prosaic inspect`.
- Produces: `RenderedProsaicCommand(prompt: str, frontmatter: dict[str, Any])` and `ProsaicPromptLoader.render_command(artifact, arguments) -> RenderedProsaicCommand`.

- [ ] **Step 1: Write the failing rendering test**

  Add an import for `ProsaicCommandArtifact`, then test that the render operation preserves metadata while substituting arguments:

  ```python
  artifact = ProsaicCommandArtifact(
      frontmatter={"model_tier": "balanced", "effort": "high", "color": "blue"},
      body="Fix {{args}}.",
  )

  rendered = ProsaicPromptLoader.render_command(artifact, "the regression")

  assert "Fix the regression." in rendered.prompt
  assert rendered.frontmatter == artifact.frontmatter
  ```

- [ ] **Step 2: Run the loader tests to verify the expected failure**

  Run: `.venv/bin/pytest tests/unit/test_prosaic_prompt_loader.py -q`

  Expected: FAIL because `render_command` accepts a body string and returns a string.

- [ ] **Step 3: Implement the metadata-preserving value object**

  Add the immutable data class next to `ProsaicCommandArtifact` and update rendering:

  ```python
  @dataclass(frozen=True)
  class RenderedProsaicCommand:
      prompt: str
      frontmatter: dict[str, Any]

  @staticmethod
  def render_command(
      artifact: ProsaicCommandArtifact, arguments: str
  ) -> RenderedProsaicCommand:
      body = artifact.body
      content = body.replace("{{args}}", arguments) if "{{args}}" in body else f"{body}\n\n## Arguments\n{arguments}"
      return RenderedProsaicCommand(
          prompt=COMMANDER_PREAMBLE + content,
          frontmatter=artifact.frontmatter,
      )
  ```

- [ ] **Step 4: Run the loader tests to verify they pass**

  Run: `.venv/bin/pytest tests/unit/test_prosaic_prompt_loader.py -q`

  Expected: PASS.

- [ ] **Step 5: Commit the loader boundary change**

  ```bash
  git add src/harness/prosaic_prompt_loader.py tests/unit/test_prosaic_prompt_loader.py
  git commit -m "Preserve Prosaic command metadata"
  ```

### Task 3: Pass Prosaic metadata through generic provider dispatch only

**Files:**
- Modify: `src/echelon/cli.py:8827-8840,8988-9042`
- Modify: `tests/unit/test_cli_llm_tool_policy.py:159-200`

**Interfaces:**
- Consumes: `RenderedProsaicCommand` or `None` from `_load_prosaic_command`.
- Produces: generic `AICodingCliProvider.run_prompt_result(worktree_path, prompt, request_metadata={"prompt_metadata": frontmatter})` dispatch only for a Prosaic-loaded command.
- Legacy contract: no bundle still calls `AICodingCliProvider.exec_prompt(worktree_path, prompt)` exactly as before.

- [ ] **Step 1: Write the failing dispatch tests**

  Extend the existing Prosaic dispatch fake provider to capture keyword arguments and assert metadata is passed:

  ```python
  def run_prompt_result(self, worktree_path, prompt, *, request_metadata=None):
      calls.append((worktree_path, prompt, request_metadata))
      return SimpleNamespace(exit_code=0)

  assert calls[0][2] == {
      "prompt_metadata": {
          "model_tier": "balanced",
          "effort": "high",
          "tools": "full",
          "color": "blue",
          "invocation": "automatic",
      }
  }
  ```

  Keep the existing native-Codex dispatch test and assert it invokes `exec_prompt` without request metadata.

- [ ] **Step 2: Run the dispatch tests to verify the expected failure**

  Run: `.venv/bin/pytest tests/unit/test_cli_llm_tool_policy.py -q`

  Expected: FAIL because command loading discards frontmatter and generic dispatch calls `exec_prompt`.

- [ ] **Step 3: Implement an explicit Prosaic dispatch branch**

  Change `_load_prosaic_command_prompt` into `_load_prosaic_command` returning `RenderedProsaicCommand | None`. In `_dispatch_skill_command`, keep `prompt` as a plain string for native fallback and add the metadata call only when a rendered Prosaic command was returned:

  ```python
  prosaic_command = _load_prosaic_command(skill_base, arguments, project_dir)
  prompt = prosaic_command.prompt if prosaic_command else None

  if prosaic_command is not None:
      result = AICodingCliProvider(config).run_prompt_result(
          str(project_dir),
          prosaic_command.prompt,
          request_metadata={"prompt_metadata": prosaic_command.frontmatter},
      )
      sys.exit(result.exit_code)
  ```

  Place this after the OpenCode native fallback branch and before the existing Claude/native generic branches. Do not alter `_run_claude_streaming` or native skill dispatch in this task.

- [ ] **Step 4: Run the dispatch tests to verify they pass**

  Run: `.venv/bin/pytest tests/unit/test_cli_llm_tool_policy.py -q`

  Expected: PASS. The no-bundle tests demonstrate legacy behavior remains available.

- [ ] **Step 5: Run the focused regression suite**

  Run: `.venv/bin/pytest tests/unit/test_prosaic_export.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_typer_app.py tests/unit/test_llm_provider.py -q`

  Expected: PASS.

- [ ] **Step 6: Commit the opt-in metadata plumbing**

  ```bash
  git add src/echelon/cli.py tests/unit/test_cli_llm_tool_policy.py
  git commit -m "Pass Prosaic command metadata to providers"
  ```

### Task 4: Verify the preparation boundary

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-prosaic-additive-preparation-design.md` only if behavior materially differs from the approved design.

**Interfaces:**
- Consumes: the completed Tasks 1-3 implementation.
- Produces: verified, additive Prosaic preparation with no new source bundle installed by default.

- [ ] **Step 1: Run the full test suite**

  Run: `.venv/bin/pytest`

  Expected: PASS.

- [ ] **Step 2: Run static and repository checks**

  Run:

  ```bash
  .venv/bin/python -m compileall -q src
  git diff --check
  git status --short
  ```

  Expected: compilation succeeds, no whitespace errors, and only the intended uncommitted verification/doc changes (if any) remain.

- [ ] **Step 3: Commit any resulting design correction**

  ```bash
  git add docs/superpowers/specs/2026-08-01-prosaic-additive-preparation-design.md
  git commit -m "Document Prosaic preparation behavior"
  ```

  Skip this command when the approved design remains accurate and there is no documentation diff.
