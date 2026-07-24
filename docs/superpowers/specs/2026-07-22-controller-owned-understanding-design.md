# Controller-Owned Understanding Analysis

## Status

Approved design for GitHub issue #175.

This design extends the approved deterministic Phase 1 gate architecture in
`2026-07-20-deterministic-phase1-gates-design.md` to both formal SAGE
spec-validation passes. It also preserves the default-off diagram policy from
`2026-07-17-optional-understanding-diagrams-design.md`.

## Problem

SAGE currently invokes Understanding through provider-native skills and shell
commands during WHY2 and WHY3. It parses temporary JSON files, resolves quality
thresholds, calculates pass/fail, optionally generates diagrams, and publishes
`quality_scores` in its model-authored result.

This makes deterministic evidence depend on the selected provider's tool
support and on the model following a long operational protocol. A missing tool
call, malformed temporary file, stale threshold, or invented score can change
workflow routing.

## Goals

- Make all Understanding execution and metric certification provider-neutral.
- Use one public Understanding Python API for the CLI and squad harness.
- Run deterministic analysis before SAGE WHY2 and WHY3.
- Give SAGE the complete certified report for qualitative interpretation.
- Prevent an agent result from supplying or overriding Understanding scores.
- Preserve SAGE's ability to reject a specification for qualitative reasons.
- Preserve default-off, non-blocking automatic diagram generation.
- Persist immutable evidence for every analysis attempt.

## Non-Goals

- Changing Understanding metrics or their configured thresholds.
- Removing SAGE's contradiction, completeness, or pre-mortem review.
- Moving CARTOGRAPHER's diagnostic scan behavior in issue #176.
- Replacing standalone Understanding commands.
- Changing build-side or post-build Understanding behavior.

## Workflow

Add two provider-free deterministic nodes:

```text
phase1-what
    -> phase1-understanding
         error -> terminal-blocked
         valid -> phase1-why2 (SAGE interprets passed or failed metrics)

phase3-plan
    -> phase3-understanding
         error -> terminal-blocked
         valid -> phase3-consensus (WHY3 interprets passed or failed metrics)
```

A quality-gate failure is valid analysis, not an operational error. SAGE still
runs so it can turn the certified findings into `quality-gates.md`, `issues.md`,
and actionable qualitative guidance. Routing after SAGE uses the controller's
certified score. An invocation, parsing, or evidence-write failure blocks before
provider dispatch and never falls back to heuristic scoring.

The phase3 consensus graph evaluates certified Understanding failure before an
ordinary consensus success or `accept_with_risk` transition. The existing
iteration-cap convergence policy remains the only explicit route that may move
past repeated quality failure.

## Public Understanding API

Create a reusable service API under `src/understanding/` and make the existing
CLI delegate to it. The API accepts a spec path, resolved thresholds, and
diagram policy, and returns a serializable analysis bundle containing:

- full-spec enhanced metrics;
- all eight configured gate values and per-gate verdicts;
- one certified aggregate pass Boolean;
- requirement count and per-requirement metrics;
- EARS classification and constraint diagnostics;
- entity analysis and behavioral transitions;
- optional diagram paths and status;
- an explicit operational error when analysis could not complete.

The service must not discover project configuration. Configuration resolution
belongs to the caller. This keeps analysis deterministic and makes unit tests
independent of filesystem layout.

The CLI retains its current command-line and JSON contracts. It resolves its
configuration as it does today, calls the service, renders the returned bundle,
and preserves exit code 1 for completed analysis with failed gates.

## Evidence Contract

Each deterministic node writes one immutable report under the active squad run:

```text
${SQUAD_DIR}/evidence/understanding/
  phase1-why2-iter-<N>.json
  phase3-consensus-iter-<N>.json
```

The report contains:

```yaml
schema_version: 1
phase: phase1-why2 | phase3-consensus
iteration: <integer>
spec:
  path: <project-relative path>
  sha256: <content digest>
thresholds: {overall: 0.0, structure: 0.0, ...}
scores: {overall: 0.0, structure: 0.0, ...}
gates:
  overall: {score: 0.0, threshold: 0.0, pass: true}
pass: true | false
requirement_count: <integer>
per_requirement: []
entity_analysis: {}
behavioral_analysis: {}
diagrams:
  enabled: false
  status: skipped | written | failed
  outputs: []
findings: []
generated_at: <UTC timestamp>
```

The report path, digest, status, and concise failing-gate summary are stored as
controller-owned state. Large per-requirement data is not copied into
`state.json`.

Zero parsed requirements is a completed deterministic analysis with
`pass: false` and a structured `zero-requirements` finding. It is not classified
as an unavailable dependency.

## Controller Integration

Add a `deterministic_understanding` phase executor. It has no provider
dependency and performs these steps:

1. Resolve `spec_dir` and require `spec.md`.
2. Resolve all eight quality thresholds through the standard configuration
   cascade.
3. Call the public Understanding API exactly once.
4. Optionally generate diagrams only when
   `understanding.diagram.enabled: true`.
5. Persist immutable evidence before returning a result.
6. Append a controller-certified `quality_scores` entry with provenance.

The score entry preserves the existing state shape:

```yaml
- pass: true | false
  pass_id: WHY2-iter-<N> | WHY3-iter-<N>
  overall: <float>
  structure: <float>
  testability: <float>
  readability: <float>
  cognitive: <float>
  semantic: <float>
  behavioral: <float>
  depth: <float>
  source: harness:understanding
  evidence: <report path>
```

The controller appends to the existing score series rather than replacing its
history. Re-executing the same phase, iteration, and spec digest reuses the
existing immutable report and does not duplicate the score entry.

## SAGE Contract

WHY1 remains unchanged and never receives or runs Understanding analysis.

For WHY2 and WHY3, the harness injects the report path and a concise certified
summary into the prompt. SAGE reads the report and owns only qualitative work:

- identify contradictions, ambiguity, omissions, and unsafe assumptions;
- explain failed metrics and per-requirement findings;
- author `quality-gates.md` and `issues.md` from certified values;
- perform cross-artifact and pre-mortem review;
- return journal evidence and a qualitative verdict.

Remove from SAGE prose and appendices:

- Skill-tool Understanding invocation;
- Understanding CLI and temporary-file commands;
- `jq` extraction and threshold loading commands;
- diagram commands and retries;
- permission to emit `quality_scores`.

SAGE may make the outcome stricter through CRITICAL qualitative findings or a
FAIL verdict. It cannot make a failed deterministic metric pass. Workflow
conditions continue to combine qualitative findings with the certified
`quality_gates` projection.

## Diagram Policy

Automatic diagrams remain controlled by:

```yaml
understanding:
  diagram:
    enabled: false
```

When disabled, the report records an intentional `skipped` status without a
journal warning. When enabled, the deterministic executor requests the existing
SVG and PNG outputs. Graphviz or rendering failure records `failed` evidence but
does not change the quality verdict or block SAGE. Standalone diagram commands
remain unchanged.

## Error and Recovery Semantics

| Condition | Classification | Behavior |
|---|---|---|
| Configured metric below threshold | completed failure | Persist report, dispatch SAGE, then route repair from certified state. |
| Zero parsed requirements | completed failure | Persist finding, dispatch SAGE, then route repair. |
| Missing `spec.md` | operational error | Persist error evidence and block before SAGE. |
| Analysis exception or malformed result | operational error | Persist error evidence and block before SAGE. |
| Evidence cannot be written | operational error | Block before SAGE with the exact filesystem error. |
| Diagram disabled | intentional skip | Continue without warning. |
| Diagram generation fails | non-blocking auxiliary failure | Record failure and continue. |

`echelon spec continue` retries an operational error at the deterministic node.
It does not require a rewind and does not consume an authoring repair attempt.

## Migration

- Existing runs entering WHY2 or phase3 consensus are routed through the new
  deterministic node before another SAGE dispatch.
- Existing model-authored score history remains readable but is not accepted as
  evidence for a new dispatch.
- New entries are distinguishable by `source: harness:understanding` and an
  immutable evidence path.
- SAGE-provided `quality_scores` becomes an unexpected state update and is
  quarantined during compatibility rollout.

## Verification

Unit tests cover:

- public API and CLI output parity;
- all eight configured thresholds;
- per-requirement, EARS, constraints, entities, and transitions;
- zero-requirement deterministic failure;
- diagram disabled, success, and non-blocking failure;
- evidence schema and idempotent reuse.

Workflow and integration tests cover:

- both deterministic nodes invoke no provider;
- WHY1 never analyzes Understanding;
- WHY2 and WHY3 each receive exactly one certified report;
- failed metric gates still dispatch SAGE for interpretation;
- operational errors block before SAGE;
- model-provided scores cannot override certified state;
- phase3 consensus cannot normally advance past a certified metric failure;
- SAGE can still fail a metric-clean spec for qualitative reasons;
- canonical SAGE prose contains no Understanding, shell, temporary-file, or
  provider-native execution instructions.

## Design Self-Review

- The design has no placeholder decisions.
- Deterministic failure and operational error have distinct routing.
- SAGE retains qualitative authority without owning deterministic evidence.
- Diagram behavior matches the existing approved default-off contract.
- The scope is limited to issue #175; CARTOGRAPHER and build-side cleanup remain
  separate issues.
