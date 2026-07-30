# Agent Context Budgeting and Benchmark Comparison Design

## Purpose

Echelon agent dispatches currently risk sending oversized prompts because the prompt assembler can inject full `state.json`, full `reasoning-journal.jsonl`, and unbounded directory contents. Some workflow definitions already declare filtered journal context, but the current assembler treats those filters as comments. This design introduces a compatibility-first context budgeting layer that reduces LLM cost and context-limit failures without destabilizing existing Echelon flows.

The default behavior must keep dispatches moving: render bounded context, warn when truncation occurs, and record enough telemetry to compare bounded prompts against the legacy prompt shape. Strict failures are opt-in.

## Goals

- Apply existing context-pack filter declarations instead of ignoring them.
- Stop sending raw full `state.json` in normal agent dispatches.
- Bound journal, state, context file, and directory contributions deterministically.
- Preserve enough context for agents to complete their phase contracts.
- Log legacy-vs-bounded prompt metrics for later evaluation.
- Add benchmark support for running Echelon with legacy or bounded context rendering.
- Avoid blocking normal runs during rollout.

## Non-Goals

- Rewriting `extension/workflow/definition.yaml` in bulk.
- Changing phase routing semantics.
- Sending both legacy and bounded prompts to an LLM during normal execution.
- Storing full legacy prompt text by default.
- Making strict context-budget enforcement the default in the first release.

## Design Summary

Add a central agent context renderer used by normal and staged agent dispatch paths. The renderer produces two local prompt models:

- `legacy`: the prompt Echelon would have sent before this change.
- `bounded`: the prompt selected for dispatch in the default rollout mode.

Only one prompt is sent to the provider. By default, Echelon sends `bounded`, logs warnings when truncation occurs, and writes per-dispatch comparison telemetry. Operators can choose `legacy` for compatibility testing, or strict mode for CI once the bounded behavior is trusted.

## Render Modes

Introduce a render mode controlled by config and environment:

- `bounded`: default. Send bounded prompt, locally measure legacy.
- `legacy`: send legacy prompt, locally measure bounded.

Environment override:

```text
ECHELON_CONTEXT_RENDER_MODE=bounded|legacy
ECHELON_CONTEXT_BUDGET_STRICT=0|1
```

Strict mode does not change rendering. It changes over-budget behavior from warn-and-truncate to fail before provider dispatch.

## Context Rendering

The renderer must not apply one uniform truncation rule to every context-pack item. Echelon phases use context for different purposes: SAGE validates cross-artifact consistency, SENTINEL derives test coverage, INVESTIGATOR repairs evidence, and experimental quality phases audit already-written artifacts. A dumb first-N truncation policy would break those contracts.

Each rendered context section therefore has a phase-aware policy with:

- `criticality`: `must_preserve`, `important`, `history`, or `advisory`
- `renderer`: `full_file`, `compact_json`, `filtered_journal`, `directory_manifest`, `directory_bounded_files`, or `summary_pointer`
- `cap_bytes`: the section cap after higher-priority sections are allocated
- `overflow_action`: `truncate_with_notice`, `summarize_with_notice`, `manifest_only`, or `legacy_fallback_warning`

The default policy is conservative: preserve current normative artifacts before historical material. If a phase needs a more specific rule, the renderer uses the phase id, agent id, mode, and context-pack item path to select it.

### Priority Order

When total context must shrink, drop or summarize in this order:

1. Advisory history: stale memory reports, prior-spec context, calibration history, old journal entries.
2. Filtered journal context beyond the matching-entry cap.
3. Directory bodies after the directory manifest is preserved.
4. Large state ledgers after compact state fields are preserved.
5. Current phase evidence artifacts.
6. Current normative artifacts required by the phase contract.

Current normative artifacts are last to shrink because truncating them is most likely to change agent behavior. Examples include `spec.md` for SAGE and GATEKEEPER, `plan.md` and `data-model.md` for SENTINEL, `tasks.md` and `coverage-map.md` for WHY3 consensus, and the selected repair report for targeted repair dispatches.

### Journal Entries

Context-pack entries such as:

```text
.specify/squad/reasoning-journal.jsonl [type=routing_decision, phase=phase1-what]
.specify/squad/reasoning-journal.jsonl [phase=phase1-*]
.specify/squad/reasoning-journal.jsonl [type=belief_gate_triggered]
```

must be parsed into executable selectors. The renderer will:

1. Resolve the journal path.
2. Parse JSONL safely, skipping malformed entries with a diagnostic count.
3. Filter by declared `phase`, `type`, and supported wildcard phase patterns.
4. Include only a bounded number of matching entries, defaulting to the most recent 20.
5. Render omitted counts and selector metadata before the included entries.

Unfiltered journal references remain supported but are still capped. This protects older workflow entries that name the journal without selectors.

### State

Normal agent prompts will receive a compact state projection instead of raw full `state.json`.

Always include:

- phase and status fields
- run path fields: `squad_dir`, `staging_dir`, `context_dir`, `spec_dir`, `published_spec_dir`
- implementation targets
- active product input pointers
- selected issue or repair context fields relevant to the current phase
- current certified Understanding evidence pointers and summary
- routing fields required by the phase result contract

Summarize:

- quality score history
- issue ledgers
- product input ledgers
- build progress
- token/cost ledgers
- large nested report payloads

The raw state file is only included when a phase explicitly requests a full state context and strict size limits allow it.

### Files and Directories

Single files are included up to a per-section byte limit. Directories are rendered as:

- a manifest of discovered files
- bounded contents for the first relevant files by deterministic sort order
- omitted file and byte counts

This keeps directory context useful without letting `contracts/`, investigation outputs, or generated artifacts dominate the request.

Directory rendering is path-aware:

- `contracts/`: preserve a manifest of every contract file and include bounded bodies for each file in deterministic order. If the directory exceeds its cap, preserve file names and headings so agents can see the interface surface that exists.
- `investigation/`: include the current evidence inventory and a manifest first. Prior investigation reports are treated as retry evidence, not normative truth, and can be summarized before current spec artifacts.
- `adr/`: preserve ADR filenames, titles, status lines, and decision summaries before body text.
- unknown directories: render a manifest first, then bounded file bodies.

Glob-like entries such as `adr/ADR-*.md` should be resolved explicitly and rendered with the same path-aware policy rather than treated as plain unresolved prose.

### Phase and Node Policy

The implementation should ship with an explicit policy table for the high-risk nodes observed in `extension/workflow/definition.yaml`:

- `phase1-why2` / SAGE WHY2: preserve full `spec.md`, constitution snapshot, and assumptions when possible; filter journal to phase1 WHAT routing decisions; compact state to certified Understanding and active issue/repair fields.
- `phase1-investigate`: preserve `spec.md`, `assumptions.md`, `unknowns.md`, and `issues.md`; treat prior `investigation/` and `evidence-resolution.md` as retry context that can be omitted during invalid-inventory repair.
- `phase2-decide` and `phase2-strategic-overview`: preserve current spec and gatekeeper inputs; summarize phase1 journal history.
- `phase3-how`: preserve spec, constitution, requirements overview, gatekeeper constraints, and specialist outputs; journal history is secondary.
- `phase3-sentinel`: preserve plan, data-model, spec acceptance criteria, contracts manifest, and quality-gates testability details; historical journal context is secondary.
- `phase3-plan`: preserve spec, architecture, ADR summaries, and test strategy; calibrations and history are secondary.
- `phase3-consensus` staged agents: preserve the artifact set required by each agent entry. Directory bodies may be bounded, but the artifact manifest must remain complete so missing or inconsistent artifacts remain visible.
- experimental quality phases: preserve the target artifact under audit and summarize full journal context.

If no explicit policy matches a node, use the generic priority order above and record `policy: default` in the context budget report. This makes unknown behavior visible without blocking rollout.

## Telemetry

Each dispatch writes a context budget report under the active squad run directory:

```text
${SQUAD_DIR}/context-budget/dispatch-<sequence>-<phase>-<agent>.json
```

The report includes:

- phase, agent, mode, dispatch timestamp
- selected render mode
- legacy prompt bytes and approximate tokens
- bounded prompt bytes and approximate tokens
- reduction percentage
- top prompt sections by bytes for both renderings
- applied journal selectors
- truncation and omission counts
- strict-mode decision, when enabled

The report must not store full prompt text by default. A separate explicit debug flag may persist prompt bodies for local debugging, but that must stay opt-in because prompts may contain proprietary project context.

## Dispatch Behavior

Default behavior:

1. Build legacy prompt locally.
2. Build bounded prompt locally.
3. Write the context budget report.
4. If bounded prompt required truncation, print a warning and include the report path.
5. Send bounded prompt to the provider.

Legacy compatibility behavior:

1. Build both prompts.
2. Write the same report.
3. Send legacy prompt to the provider.

Strict behavior:

1. Build selected prompt.
2. If selected prompt exceeds the configured hard limit after bounding, block before provider dispatch.
3. Write a context budget report explaining the failure.

## Benchmark Integration

Extend `echelon benchmark run` to support context render selection:

```text
echelon benchmark run <fixture-id> --variant <variant-id> --context-render legacy
echelon benchmark run <fixture-id> --variant <variant-id> --context-render bounded
echelon benchmark run <fixture-id> --variant <variant-id> --context-render both
```

CLI wrappers in `src/echelon/cli_app.py` and legacy argument parsing in `src/echelon/cli.py` should pass this option to `src/echelon/benchmark.py`.

Benchmark behavior:

- `legacy`: run the variant once with `ECHELON_CONTEXT_RENDER_MODE=legacy`.
- `bounded`: run the variant once with `ECHELON_CONTEXT_RENDER_MODE=bounded`.
- `both`: run the same fixture and variant twice from the same baseline snapshot, once legacy and once bounded. Store separate records using stable render-qualified identities, for example `baseline:legacy` and `baseline:bounded`, while preserving the original variant id inside each record.

Benchmark summaries should include context-render fields:

- render mode
- total prompt bytes and approximate prompt tokens
- total reduction percentage for bounded runs
- per-phase truncation counts
- status, blocks, retries, verification failures, wall-clock time
- final artifact score fields already collected today

The `both` mode lets us evaluate whether bounded context changes outcomes, not only cost. It should compare:

- final status
- selected spec id and delivery result
- blocked states
- retry count
- verification failures
- fulfillment gaps
- elapsed seconds
- aggregate prompt-token estimate
- aggregate provider-reported tokens when available

## Safety and Compatibility

- Bounded rendering is deterministic.
- All truncations are visible in telemetry.
- Existing workflow filter syntax remains valid.
- Existing unfiltered context-pack entries continue to work, but are capped.
- Provider dispatch remains single-pass unless the user explicitly runs benchmark `--context-render both`.
- Strict enforcement is opt-in during the rollout.

## Testing

Add unit tests for:

- journal selector parsing and filtering
- wildcard phase filters
- compact state projection excluding oversized ledgers
- directory bounding with manifest and omitted counts
- normal `AgentExecutor` using bounded context
- staged parallel executor using bounded context
- context budget report generation
- benchmark CLI parsing for `--context-render`
- benchmark command environment propagation
- benchmark `both` producing separate legacy and bounded records

Add fixture-style tests using existing Echelon run-shaped artifacts to prove:

- SAGE WHY2 does not receive unrelated journal phases.
- raw full `state.json` is absent from bounded normal prompts.
- bounded prompt size is lower than legacy for a journal-heavy fixture.
- legacy mode still reproduces old prompt behavior for compatibility.

## Rollout Plan

1. Implement renderer and telemetry behind default warn-and-truncate mode.
2. Route normal and staged agent prompt assembly through the renderer.
3. Add benchmark `--context-render legacy|bounded|both`.
4. Run existing tests and focused context-budget tests.
5. Run benchmark fixtures in `both` mode to compare quality and cost.
6. Use collected reports to tune default caps.
7. Enable strict mode only in CI or targeted validation after evidence shows bounded rendering is stable.

## Open Decisions

- Exact default byte/token caps per section.
- Whether full prompt debug persistence should be controlled by config, env var, or both.
- Whether context budget summaries should also become a journal entry after a safe journal type is registered.
