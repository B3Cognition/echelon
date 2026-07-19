# SUE Runtime Provider Selection Design

**Date:** 2026-07-19
**Status:** Approved for implementation
**Scope:** `scripts/sue_challenge.py`, `scripts/sue_consensus.py`, `scripts/sue_reproducibility.py`

## Goal

SUE SHALL run its isolated readers through the LLM provider associated with the
environment from which SUE was launched, while preserving an explicit CLI
override for reproducible experiments.

The current conversation is never reused as a reader. Every SUE reader remains
a fresh CLI subprocess with a neutral temporary working directory.

## Provider Resolution

Provider selection SHALL use this precedence:

1. An explicit `--model-cmd PROVIDER=COMMAND` argument.
2. The `ECHELON_LLM` environment variable.
3. A supported runtime marker.
4. The backward-compatible `claude` default.

Supported runtime markers:

- `CODEX_THREAD_ID` or `CODEX_CI` selects `codex`.

Claude remains the fallback because SUE historically defaulted to the Claude
CLI. Process ancestry SHALL NOT be inspected because parent process names are
unstable across shells, desktop applications, wrappers, and CI.

Explicit selection SHALL always override environment detection. This allows
controlled cross-provider experiments from any host environment.

## Supported Providers

### Claude

The command defaults to `claude`. SUE appends `-p` and sends the prompt through
stdin, preserving the existing behavior.

### Codex

The command defaults to `codex`. SUE invokes:

```text
codex exec --ephemeral --skip-git-repo-check --sandbox read-only -
```

The prompt is sent through stdin. `--ephemeral` prevents reader sessions from
being persisted. The neutral temporary working directory and read-only sandbox
prevent project-local instructions or writes from influencing the reader.

### Copilot

The existing argv prompt transport remains unchanged. Large-prompt rejection
and its privacy limitation remain explicit.

## CLI Contract

All three SUE layers SHALL expose the canonical option:

```text
--model-cmd PROVIDER=COMMAND
```

`--claude-cmd` SHALL remain as a compatibility alias.

For SUE v1 and v2, the option is singular. For SUE v3 it remains repeatable so
the model-by-framing matrix can compare multiple provider families.

When no model option is supplied, SUE SHALL resolve one provider command from
the environment. Environment detection SHALL NOT add a second provider to a v3
run.

Supported explicit provider prefixes are:

- `claude=...`
- `codex=...`
- `copilot=...`

An unprefixed command SHALL infer its provider from the executable basename.
Unknown executable names SHALL retain the existing Claude-compatible stdin
protocol for backward compatibility.

## Reporting

SUE v3 SHALL continue to record the resolved provider and executable tag for
every reader. Provider detection changes invocation selection only; it SHALL
NOT merge readers, reuse conversations, or alter the model-by-framing matrix.

SUE v1 and v2 reports SHALL identify the resolved provider so that an automatic
run remains auditable.

## Failure Behavior

- An unsupported explicit provider prefix SHALL fail before any model call.
- A missing resolved executable SHALL fail during preflight.
- Invalid `ECHELON_LLM` values SHALL be ignored and fall through to runtime
  markers or the Claude default.
- Codex subprocess failures and timeouts SHALL use the existing SUE retry and
  diagnostic paths.

## Tests

Regression tests SHALL verify:

1. Explicit model selection overrides all environment signals.
2. `ECHELON_LLM=codex` selects the Codex protocol.
3. `CODEX_THREAD_ID` selects Codex when `ECHELON_LLM` is absent.
4. Claude remains the fallback without recognized signals.
5. Codex invocation uses stdin and the isolated `codex exec` arguments.
6. V1, v2, and v3 accept `--model-cmd`; `--claude-cmd` remains compatible.
7. V3 provider tags identify Codex readers correctly.
8. Unsupported explicit prefixes fail before launching a subprocess.

## Non-Goals

- Reusing the active Codex or Claude conversation.
- Detecting providers from process ancestry.
- Selecting a model name automatically.
- Changing SUE prompts, consensus rules, graph metrics, or report findings.
- Adding OpenCode support in this change.
