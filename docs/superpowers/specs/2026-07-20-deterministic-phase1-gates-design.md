# Deterministic Phase 1 Gate Nodes

## Status

Approved design. This document defines the target architecture only; it does not implement it.

## Problem

Phase 1 currently embeds two deterministic checks inside LLM-owned phases:

- CARTOGRAPHER writes `spec.md`, derives `requirements.lexicon.md`, and reports Lexicon status from `phase1-what`.
- SAGE runs formal Understanding validation as part of `phase1-why2`, alongside qualitative specification review.

That combines authoring, command execution, result interpretation, persistent state, and routing. A missing artifact, a command failure, stale agent state, or an incorrect interpretation can therefore be reported as a validation failure and route the run incorrectly.

## Goals

- Make Lexicon and formal Understanding validation independently observable, deterministic, and recoverable.
- Keep CARTOGRAPHER responsible for authoring and SAGE responsible for qualitative challenge.
- Ensure no agent-produced Boolean controls either gate's routing.
- Preserve `spec.md` as the Phase A source of truth and `requirements.lexicon.md` as a derived artifact.
- Avoid additional LLM calls and avoid noisy Git checkpoints for validation-only phases.

## Non-goals

- Changing Lexicon grammar, Understanding metrics, or their configured thresholds.
- Removing SAGE WHY2 review.
- Introducing a user-facing manual gate command in the first release.
- Rewriting completed or historical spec runs.

## Chosen architecture

Introduce two controller-internal workflow node types executed by a deterministic gate executor. They do not dispatch a provider or consume an LLM budget.

```text
phase1-what                 CARTOGRAPHER authors spec + derived Lexicon artifact
        |
        v
phase1-lexicon-gate         deterministic Lexicon validation
        |-- not_ready ------> phase1-what
        |-- failed ---------> phase1-what
        |-- error ----------> terminal-blocked
        '-- passed ---------> phase1-understanding-gate
                                      |
                                      v
                             deterministic Understanding validation
                                      |-- failed --> phase1-what
                                      |-- error ----> terminal-blocked
                                      '-- passed ---> phase1-why2
                                                        |
                                                        v
                                              SAGE qualitative review
                                              |-- amend --> phase1-what
                                              '-- pass --> checkpoint-assess
```

`phase1-what` always flows to `phase1-lexicon-gate`. When the configured Lexicon gate is disabled, that node records `skipped` and advances to `phase1-understanding-gate`; it does not disappear from the run history. Formal Understanding remains mandatory.

## Components and contracts

### DeterministicGateExecutor

Add a controller-owned `deterministic_gate` node type and executor. It receives the active run state, project configuration, and spec directory. It has no provider dependency.

Every invocation returns a normal `SquadAgentResult` whose `state_updates` are created only by the executor. The gate executor writes evidence before it evaluates transitions. Agent `echelon_result` fields are never read for either gate.

### `phase1-lexicon-gate`

Inputs:

- `{spec_dir}/spec.md`
- `{spec_dir}/requirements.lexicon.md`
- `{spec_dir}/glossary.md`
- `lexicon_gate` configuration

Execution:

```text
lexicon validate requirements.lexicon.md --type SPEC \
  --source-ref spec.md --glossary glossary.md --json
```

Canonical state:

```yaml
lexicon_gate:
  status: skipped | not_ready | passed | failed | error
  attempt: <controller incremented integer>
  findings: <integer or null>
  evidence: runs/<run-id>/staging/gates/lexicon-<attempt>.json
  message: <short controller-generated explanation>
```

Semantics:

- `skipped`: the configured gate is disabled.
- `not_ready`: `spec.md`, the derived artifact, or the configured glossary is absent. Route to CARTOGRAPHER; do not claim validation ran.
- `passed`: the CLI ran and returned `ok: true`.
- `failed`: the CLI ran and returned structured findings. Route to CARTOGRAPHER with the exact evidence path.
- `error`: the CLI could not be invoked, returned malformed JSON, or the controller could not write evidence. Block with a concise operational reason; do not re-author the specification.

The EGR-153 fields (`lexicon_evaluation`, `lexicon_pass`, `lexicon_attempts`, and `lexicon_findings`) remain compatibility projections during migration. `lexicon_gate.status` is authoritative for new routing. The Boolean exists only for callers that still consume it and is written only for `passed` or `failed`, never for `not_ready`, `skipped`, or `error`.

### `phase1-understanding-gate`

Inputs:

- `{spec_dir}/spec.md`
- formal Understanding configuration and thresholds from project config

Execution uses the existing formal validation entrypoint, not `understanding scan` and not an agent-created wrapper. The executor captures the complete JSON result unchanged.

Canonical state:

```yaml
understanding_gate:
  status: passed | failed | error
  attempt: <controller incremented integer>
  overall: <float or null>
  failing_gates: [structure, testability]
  evidence: runs/<run-id>/staging/gates/understanding-<attempt>.json
  threshold_source: .echelon/config.yml
  message: <short controller-generated explanation>
```

Semantics:

- `passed`: the formal command ran and every configured gate passed.
- `failed`: the formal command ran and at least one configured gate failed. Route to CARTOGRAPHER with the actual configured thresholds and failing metrics.
- `error`: invocation, JSON parsing, or evidence persistence failed. Terminal-blocked with an operational remediation message.

The gate never accepts a diagnostic `understanding scan` score as a formal result. A scan remains optional CARTOGRAPHER repair feedback only.

### CARTOGRAPHER and SAGE

`phase1-what` owns only authoring:

- write/amend `spec.md`;
- derive `requirements.lexicon.md` when Lexicon is enabled;
- optionally run diagnostics and repair findings;
- report only authoring metadata and product-input evidence.

It must not emit `lexicon_*` gate state.

`phase1-why2` runs after both deterministic gates passed. SAGE reads the immutable evidence files and performs qualitative review: contradictions, missing scenarios, unsafe assumptions, ambiguous requirements, and evidence gaps. It must not invoke formal Understanding validation or publish its scores as a gate verdict.

SAGE may return a separate `sage_spec_assessment: pass | amend | blocked`. `amend` returns to `phase1-what`; `blocked` follows the existing escalation route. This preserves meaningful WHY2 review without competing with deterministic validation.

## Workflow and checkpoint behavior

The new gate nodes are visible in `echelon spec status`, the roadmap, dispatch counters, and Squad Summary.

- Gate nodes create no Git checkpoint because they do not author versioned artifacts.
- `phase1-what` remains the checkpointed authoring boundary.
- Each gate execution creates immutable run-local evidence in `staging/gates/`.
- A gate result carries the evidence path and exact next action in terminal/block summaries.

The phase-level dispatch budget applies independently to each gate. CARTOGRAPHER repair cycles remain bounded by the existing Phase 1 iteration limit. Gate `error` is not a repair attempt and does not consume CARTOGRAPHER's budget.

## Recovery behavior

| State | `echelon spec continue` behavior | User action |
|---|---|---|
| Lexicon `not_ready` | Runs CARTOGRAPHER on the next iteration. | None unless the artifact cannot be authored. |
| Lexicon `failed` | Runs CARTOGRAPHER with the evidence path. | None; inspect evidence if needed. |
| Lexicon `error` | Re-runs the same deterministic gate after the environment is corrected. | Fix CLI/config/filesystem issue, then continue. |
| Understanding `failed` | Runs CARTOGRAPHER with formal failing metrics. | None; amend the spec. |
| Understanding `error` | Re-runs the same deterministic gate after the environment is corrected. | Fix the formal validator/config issue, then continue. |
| SAGE `amend` | Runs CARTOGRAPHER. | None unless SAGE requests clarification. |

`echelon spec rewind phase1-what` remains the explicit way to restore the authoring checkpoint and reset both gate attempt counters. It is not required merely to retry a gate `error`.

## Migration and compatibility

On `echelon spec continue`, runs created before this design are normalized once:

- existing controller-certified `lexicon_pass: true` becomes `lexicon_gate.status: passed`;
- existing controller-certified `lexicon_pass: false` with evidence becomes `failed`;
- a Boolean without evidence becomes `not_ready`, never `failed`;
- absent Lexicon state becomes `not_ready` if the gate is enabled;
- existing WHY2 formal validation output is copied into `understanding_gate` only when its evidence and configured thresholds are recoverable; otherwise Understanding is re-run deterministically.

The migration appends a journal entry and never changes `spec.md`, `requirements.lexicon.md`, or a historical checkpoint.

## CLI presentation

`echelon spec status` and terminal summaries should show, for example:

```text
Phase 1 gates
  Lexicon        failed     attempt 2  64 findings
  Evidence       runs/<run-id>/staging/gates/lexicon-2.json
  Next           CARTOGRAPHER will repair requirements.lexicon.md

  Understanding  not run
```

For an operational error, the output must name the exact failed command or missing dependency and print the concrete retry command. It must never recommend a rewind when retrying the unchanged gate is sufficient.

## Test strategy

Unit tests:

- Lexicon status classification for disabled, missing artifact, pass, findings, malformed output, and subprocess failure.
- Understanding status classification for pass, configured threshold failure, malformed output, and subprocess failure.
- Controller-owned state cannot be emitted by an agent result contract.
- Gate state is accepted at the state-store boundary only after the deterministic executor creates it.
- Compatibility projection never writes a Boolean for `not_ready`, `skipped`, or `error`.

Workflow tests:

- The Phase 1 graph orders WHAT → Lexicon → Understanding → WHY2.
- Each deterministic outcome has a defined transition; no condition routes through COMMANDER due to an absent Boolean.
- Disabled Lexicon records `skipped` and proceeds to mandatory Understanding.
- SAGE cannot be reached after a failed or not-ready formal gate.

Integration tests:

- Neither gate invokes an LLM provider.
- A missing derived artifact re-dispatches CARTOGRAPHER without consuming a validation failure budget.
- A real Lexicon finding re-dispatches CARTOGRAPHER with evidence.
- A formal Understanding threshold failure re-dispatches CARTOGRAPHER with the configured threshold values.
- A gate execution error blocks with an actionable retry and preserves authored files.
- Legacy run normalization preserves artifacts and chooses the correct first gate.

## Rollout

1. Implement the deterministic executor and evidence schema behind the existing Phase A graph.
2. Add the two nodes and migrate result contracts so gate state is controller-owned.
3. Refactor CARTOGRAPHER and SAGE prompts to their narrower responsibilities.
4. Add CLI status/summary rendering and one-time legacy-run normalization.
5. Release as a minor version because the persisted run-state and visible workflow graph change.

## Design self-review

- No placeholders, deferred decisions, or contradictory routing rules remain.
- Gate failures and operational errors are explicitly distinct.
- The design preserves existing authored artifacts and checkpoints.
- Scope is limited to Phase 1 deterministic validation boundaries and their recovery surface.
