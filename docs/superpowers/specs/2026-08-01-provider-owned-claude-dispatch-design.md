# Provider-Owned Claude Dispatch Design

## Goal

Make `AICodingCliProvider` and `ClaudeCliBackend` the sole execution path for
all Echelon Claude commands. `cli.py` must only load and render command prose;
it must not launch Claude directly.

## Dispatch Flow

Both command sources use one path:

```
command source -> rendered prose -> AICodingCliProvider -> ClaudeCliBackend
```

For a Prosaic command, the provider request includes the inspected neutral
frontmatter as `request_metadata["prompt_metadata"]`. For a legacy command,
Echelon renders the existing provider-native Markdown and sends no Prosaic
metadata. The source-selection fallback remains unchanged: no
`.echelon/prosaic/commands/` directory means legacy command lookup.

## Claude Backend Contract

`ClaudeCliBackend` owns the current stream-JSON process lifecycle: live event
printing, response capture, timeouts, configured `CLAUDE_CONFIG_DIR`, and
metadata-driven explicit model selection.

It builds the Claude command through `build_llm_cli_command` with
`stream_json=True` and without an unconditional task-tool restriction. The
effective `llm.tool_policy` is authoritative:

- Default policy does not send dangerous-permissions flags.
- `allow_unsafe_host_execution: true`, with its required approval reason,
  sends Claude `--dangerously-skip-permissions`.
- The backend does not add `--disallowedTools TaskCreate,TaskUpdate` outside
  that configured policy.

This preserves the prior CLI command behavior while moving responsibility to
the provider layer.

## CLI Simplification

Remove `_run_claude_streaming` and its local event-printer helper from
`echelon/cli.py`. After source selection, the CLI calls
`AICodingCliProvider.run_prompt_result` for every non-native-OpenCode command
and exits with its result code. The OpenCode legacy-native special command
remains until it has its own provider-backed replacement.

## Scope and Safety

- No model-tier-to-concrete-model mapping in this change.
- No changes to tool policy configuration, only faithful backend application.
- No Prosaic installer or source-bundle changes.
- Remove the accidentally tracked `.superpowers` Task 3 report; process
  reports remain ignored scratch artifacts.

## Tests

- Backend tests assert stream JSON, model metadata, configured config-dir, and
  dangerous-permissions behavior without forced task-tool disallowance.
- CLI tests assert both legacy and Prosaic Claude commands delegate through
  `AICodingCliProvider.run_prompt_result`.
- Existing no-bundle fallback tests remain and prove legacy command selection
  is unchanged.
