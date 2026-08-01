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
metadata-driven explicit model selection. A request may additionally declare
an Echelon execution policy, such as whether Claude native task-planning tools
are permitted.

It builds the Claude command through `build_llm_cli_command` with
`stream_json=True`. The effective `llm.tool_policy` is authoritative:

- Default policy does not send dangerous-permissions flags.
- `allow_unsafe_host_execution: true`, with its required approval reason,
  sends Claude `--dangerously-skip-permissions`.
- The backend adds `--disallowedTools TaskCreate,TaskUpdate` only when the
  request explicitly declares Echelon's canonical-task execution policy.

The CLI applies that policy only to build execution, where Echelon requires
work to follow canonical rows in `tasks.md`. Review, generic commands, and
Prosaic commands do not receive this restriction by default. This keeps the
build-specific workflow guard while preventing it from becoming a global
Claude-provider behavior.

This preserves the prior CLI command behavior while moving responsibility to
the provider layer.

## CLI Simplification

Remove `_run_claude_streaming` and its local event-printer helper from
`echelon/cli.py`. After source selection, the CLI calls
`AICodingCliProvider.run_prompt_result` for every non-native-OpenCode command
and exits with its result code. The OpenCode legacy-native special command
remains until it has its own provider-backed replacement.

## Scope and Safety

- No changes to tool policy configuration, only faithful backend application.
- No model-tier-to-concrete-model mapping in this change; Claude receives
  Prosaic metadata unchanged and interprets only the already-supported
  explicit `model` field.
- No Prosaic installer or source-bundle changes.
- Remove the accidentally tracked `.superpowers` Task 3 report; process
  reports remain ignored scratch artifacts.

## Tests

- Backend tests assert stream JSON, model metadata, configured config-dir,
  dangerous-permissions behavior, and task-tool restriction only when the
  request declares the canonical-task execution policy.
- CLI tests assert both legacy and Prosaic Claude commands delegate through
  `AICodingCliProvider.run_prompt_result`.
- Existing no-bundle fallback tests remain and prove legacy command selection
  is unchanged.
