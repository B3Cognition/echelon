# Visible Spec Lexicon Node Design

## Goal

Make spec Lexicon validation a visible, provider-free Phase A node without changing artifact ownership, repair limits, or downstream Understanding behavior.

## Architecture

Insert `phase1-lexicon` between `phase1-what` and `phase1-understanding`. The node uses a new `deterministic_lexicon` executor that invokes the existing Lexicon Python modules in process. CARTOGRAPHER continues to author `spec.md`, `00-overview.md`, and the configured derived requirements artifact; the deterministic node alone validates and certifies the derived artifact.

The tasks Lexicon gate remains in its current controller boundary. Its eventual migration can reuse the executor pattern but is outside this change.

## Flow

```text
phase1-what
    -> phase1-lexicon
        -> phase1-understanding  when passed or disabled
        -> phase1-what           when pending and iterations remain
        -> phase1-what           when failed and repair attempts remain
        -> phase1-understanding  when exhausted under warn policy
        -> terminal-blocked      when exhausted under block policy
```

The node does not dispatch an LLM. It receives state and resolved configuration, validates the exact run-local paths, writes `spec-lexicon-report.json` atomically, and returns controller-owned state updates. The normal controller loop records dispatch telemetry, phase timing, state advancement, checkpoints, and CLI phase output.

## State Contract

`phase1-lexicon` owns:

- `lexicon_evaluation`: `pending`, `passed`, or `failed`
- `lexicon_pass`: Boolean, present only after validation or disabled-gate bypass
- `lexicon_attempts`: controller-counted failed validations
- `lexicon_findings`: complete finding count after validation
- `lexicon_report`: absolute report path after validation
- `lexicon_warning_waiver`: true only when an exhausted `warn` policy explicitly permits downstream review

`phase1-what` no longer owns or mutates these fields. It always advances to `phase1-lexicon` after its required artifacts pass executor checks.

## Compatibility

Existing runs currently at `phase1-what` naturally enter the new node. A controller guard accepts current passing evidence throughout the remaining Phase A artifact path and routes missing, stale, or non-passing evidence through `phase1-lexicon`. That migration removes downstream completion and dispatch counters, resets convergence state, and prevents a saved phase recommendation from skipping certification. Disabled gates and explicit warning waivers bypass successfully without requiring a passing artifact.

## Error And Exhaustion Semantics

- Missing derived artifact, missing source, report-write failure, or validator execution failure produces `pending`, never a fabricated failed verdict.
- A real failed report increments `lexicon_attempts` exactly once.
- A passing report resets attempts to zero.
- Passing evidence is bound to the effective artifact type, configured paths, and SHA-256 digests of the source, derived artifact, and optional glossary.
- Existing `max_repair_attempts`, `max_iterations`, and `on_exhausted` behavior remains authoritative.
- A hard exhausted gate blocks at the deterministic node; warning policy persists an explicit waiver and proceeds to Understanding.
- OpenAI-compatible artifact agents receive a scoped `sha256_file` tool so source metadata can be calculated after the final source write without shell access.

## Testing

- Graph tests prove the visible node and exact edges.
- Executor tests prove provider-free pass, failure, pending, disabled, local path, report, and attempt behavior.
- Controller tests prove visible CLI dispatch, repair routing, hard exhaustion, warning fallthrough, active-run compatibility, checkpointing, and no provider invocation for the node.
- Prompt tests continue proving CARTOGRAPHER receives repair evidence but never controller verdict ownership.
