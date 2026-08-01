# Task 3 Report: Prosaic Metadata Through Generic Provider Dispatch

## Summary

Task 3 preserves `RenderedProsaicCommand.frontmatter` through CLI dispatch and
sends it only for a Prosaic-loaded command as
`request_metadata={"prompt_metadata": frontmatter}`. Native dispatch remains
on `exec_prompt` when no project `.echelon/prosaic/commands` directory exists.

## Changed Files

- `src/echelon/cli.py`
  - Replaced `_load_prosaic_command_prompt` with `_load_prosaic_command`, which
    returns `RenderedProsaicCommand | None`.
  - Sends a rendered Prosaic prompt through `run_prompt_result` with the
    frontmatter under `request_metadata["prompt_metadata"]`.
  - Leaves OpenCode's native fallback, the native generic `exec_prompt`
    fallback, model resolution, tool policies, and `_run_claude_streaming`
    unchanged.
- `tests/unit/test_cli_llm_tool_policy.py`
  - Added a direct no-Prosaic-bundle regression that records the legacy
    `exec_prompt` call and verifies it receives no keyword metadata.
  - Updated the Prosaic dispatch fake to expose only `run_prompt_result` and
    verify the complete frontmatter metadata envelope.

## TDD Evidence

### Red

Command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_llm_tool_policy.py -q
```

Result: `1 failed, 8 passed`.

The new Prosaic dispatch test failed in
`_load_prosaic_command_prompt` because it supplied `artifact.body` to the
Task 2 `render_command(artifact, arguments)` interface. This demonstrated
that the CLI had discarded the artifact/frontmatter boundary and could not
perform metadata-aware dispatch.

### Green

Focused command:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_cli_llm_tool_policy.py -q
```

Result: `9 passed in 0.31s`.

Focused regression suite:

```sh
/Users/michalbachorik/work/echelon_r/echelon/.venv/bin/pytest tests/unit/test_prosaic_export.py tests/unit/test_prosaic_prompt_loader.py tests/unit/test_cli_llm_tool_policy.py tests/unit/test_cli_typer_app.py tests/unit/test_llm_provider.py -q
```

Result: `85 passed in 1.52s`.

`git diff --check` also completed with no output.

## Commit

Implementation commit: `6bf549a28c12e27cf1e80e0e24bb89e4399da9f4`
(`Pass Prosaic command metadata to providers`).

## Self-Review

- The Prosaic-specific branch occurs after the OpenCode native fallback check
  and before the Claude/native generic branches, so any rendered Prosaic
  command uses the generic provider metadata path.
- The native no-bundle test starts without a Prosaic commands directory and
  confirms `exec_prompt` is called with an empty keyword-argument mapping.
- The Prosaic-loaded test uses only `run_prompt_result`; it verifies all five
  expected frontmatter keys below `prompt_metadata` and would fail if dispatch
  regressed to `exec_prompt`.
- No changes were made to model resolution, tool policies, Prosaic source
  installation, native fallback prompt construction, or `_run_claude_streaming`.

## Concerns

None identified within the requested scope. The generic provider metadata
handling is already covered by `test_llm_provider.py`; this task validates the
CLI handoff boundary rather than provider backend behavior.
