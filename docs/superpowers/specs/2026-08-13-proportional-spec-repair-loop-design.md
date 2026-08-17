# Proportional Specification Repair Loop Design

**Status:** Approved

**Date:** 2026-08-13

## Goal

Make proportional specification authoring proportional across validation and
repair, not only during the first CARTOGRAPHER pass. A small, sound
specification must not enter an expensive wording-only loop merely to satisfy
contradictory heuristics. When bounded repair cannot meet every applicable
quality gate, Echelon must present a truthful, evidence-backed decision instead
of retrying indefinitely or silently weakening quality.

## Problem Evidence

A live Codex run for a minimal Python Hello World feature selected
`spec_authoring_mode: proportional`, but dispatched CARTOGRAPHER seven times
and SAGE WHY2 six times over roughly one hour. The specification grew from 13
formal statements on the first assessed candidate to 22 formal statements.

The first candidate already passed cognitive, testability, semantic,
readability, depth, and behavioral thresholds. It failed the overall and
structure gates because the legacy structure analyzer assigned actor-action-
object completeness of zero while the semantic analyzer recognized actors,
actions, and objects in the same statements. Subsequent repairs optimized
different heuristics in turn:

| Iteration | Formal statements | Failed gates |
|---|---:|---|
| 0 | 13 | overall, structure |
| 1 | 19 | overall, structure, testability |
| 2 | 20 | structure, cognitive |
| 3 | 22 | overall, structure, cognitive, behavioral |
| 4 | 22 | overall, structure, cognitive, depth |
| 5 | 22 | structure, cognitive |

Three mechanics allowed the loop to continue:

1. Structure and semantic scoring used different role-detection rules over the
   same normative prose.
2. Linguistic metrics scored traceability and comparator metadata as though it
   were part of the product obligation.
3. The controller treated a material increase in any metric, and any artifact
   rewrite, as progress even when failing dimensions did not converge or the
   specification expanded.

The run did not exhaust its global ten-iteration limit. Its seventh
CARTOGRAPHER dispatch ended separately with a missing controller result
envelope. The repository-trust error observed during the later summary agent
was unrelated to the repair loop.

## Decisions

The solution has two coordinated parts:

1. Correct contradictory requirements-quality analysis without lowering
   configured thresholds.
2. Add a controller-owned proportional repair budget with an explicit,
   autonomy-aware quality-debt decision.

Proportional mode permits three automatic WHAT repairs after the initial
Understanding and WHY2 assessment. After those repairs, the controller restores
the best eligible candidate and presents a sealed decision. One option may
authorize exactly one final repair. That extension can never be offered twice
for the same run.

Perfectionist authoring retains the existing global iteration behavior. This
design does not reinterpret perfectionist mode as cheaper or less exhaustive.

## Quality Analysis Consistency

### Canonical requirement projection

Understanding will parse each formal statement once into a deterministic
projection:

```text
RequirementProjection
  requirement_id
  normative_text
  traceability_references
  constraints
  source_location
```

The parser recognizes canonical requirement identifiers and existing metadata
syntax such as `Constraint:`, `Constraints:`, `Verified by:`, and inline
verification references. It preserves the complete original statement in the
report while giving each metric family only the fields relevant to that
metric.

- Structure, readability, cognitive, semantic, and behavioral language
  analysis consume `normative_text`.
- Testability consumes `normative_text` plus `constraints`.
- Depth consumes real requirement references and dependencies, including
  `traceability_references`; comparator metadata cannot inflate depth.
- Reporting retains the source location and original text so every diagnosis
  remains explainable.

This is a projection, not a new specification format. Existing specifications
remain valid and require no migration.

### Shared role detection

Structure completeness and semantic completeness will use one shared,
deterministic actor/action/object extraction result. Structure may still score
atomicity, passive voice, pronouns, and modal strength independently, but it
must not report a missing actor, action, or object that the semantic analysis
reports as present for the same projected statement.

The shared detector must recognize domain actors from the statement rather than
rely on a fixed vocabulary such as `user`, `system`, or `service`. The original
detector output remains available in evidence for debugging.

### Threshold policy

No default or mode-specific quality threshold is lowered. The existing shared
rule that accepts a below-threshold aggregate when all configured category
floors pass remains unchanged.

This design does not make a failing category non-blocking merely because the
run is proportional. It fixes the evidence supplied to the category decision,
then bounds how much paid repair may be spent on a remaining failure.

## Proportional Repair State

The controller owns a versioned run-local record:

```json
{
  "phase1_quality_repair": {
    "schema_version": 1,
    "authoring_mode": "proportional",
    "automatic_limit": 3,
    "automatic_consumed": 0,
    "extension_limit": 1,
    "extension_authorized": 0,
    "extension_consumed": 0,
    "baseline_candidate_id": "quality-candidate-0",
    "candidate_ids": ["quality-candidate-0"]
  }
}
```

The limits are controller policy, not agent-authored values. Continue, resume,
prepared-run recovery, and ordinary evidence-resolution routing preserve the
record. Legacy proportional runs initialize it from their current certified
WHY2 history without discarding already consumed work. New perfectionist runs
do not create it.

### Repair accounting

One repair is consumed only when all of the following are true:

- the route is WHY2 quality failure to WHAT;
- CARTOGRAPHER returns a valid completion envelope;
- all mandatory WHAT artifacts are valid; and
- the canonical specification digest changes.

Provider failure, timeout, missing result envelope, state-contract failure,
checkpoint failure, evidence investigation, and user clarification do not
consume the quality-repair budget. They retain their existing operational
recovery behavior.

An unchanged successful WHAT pass does not consume another repair and does not
receive another automatic attempt. It sends the run directly to the
quality-debt decision with `no_artifact_progress` recorded in its evidence.

The ordinary global iteration count remains available to protect the entire
workflow. The dedicated proportional counter determines only the
WHAT/Understanding/WHY2 quality-repair loop and cannot reset the global count.

## Candidate Evidence and Selection

Every completed WHY2 assessment of a structurally valid proportional
specification creates a controller-owned candidate manifest. The manifest
references the existing Phase A checkpoint commit and records digests for:

- `spec.md`;
- `requirements-overview.md`;
- immutable Understanding evidence;
- `quality-gates.md` and `issues.md`;
- normalized scores, thresholds, failing gates, and SAGE finding routes;
- formal-statement count, byte count, and repair number.

Candidates are ineligible if they contain any hard blocker defined below. The
controller ranks eligible candidates deterministically by:

1. fewer failed configured gates;
2. larger worst-gate margin, where margin is `score - threshold`;
3. higher overall score;
4. fewer formal statements;
5. earlier assessment.

The earlier-assessment tie-break prevents later wording churn from winning
without measurable benefit. Formal-statement count is only a tie-break; it is
never a quality threshold or document quota.

Before opening the decision, the controller restores only the candidate-owned
specification artifacts from the recorded checkpoint commit, verifies every
digest against the manifest, and creates a new Phase A checkpoint for the
restoration. It does not rewind unrelated controller state, user decisions, or
Git history. A missing checkpoint, changed digest, or failed restoration is a
state-integrity failure and cannot become quality debt.

## Quality-Debt Decision

### Eligibility

The decision is available only when the current failure consists of residual
quality-gate or non-critical qualitative debt on an otherwise valid,
evidence-backed specification.

Quality-debt continuation is forbidden when the run or selected candidate has
an active:

- CRITICAL SAGE issue or contradiction;
- unresolved evidence request or product-policy decision;
- unsupported product-input mapping or invalid traceability contract;
- missing, malformed, or invalid mandatory artifact;
- provider, timeout, controller-contract, checkpoint, or state-integrity
  failure; or
- other hard structural contract required for safe downstream consumption.

Those cases retain their existing fail-closed recovery routes.

### Sealed policy after automatic repairs

After three automatic repairs, the controller creates a registered
`controller_safeguard` decision with reason
`proportional_quality_budget_exhausted`. It contains these exact options:

| Option | Effect |
|---|---|
| `extend_once` | Authorize one final WHAT repair and return through Understanding and WHY2. |
| `continue_with_debt` | Accept the restored candidate with explicit quality debt and continue to Lexicon. |
| `stop` | Preserve the blocked run without accepting the candidate. |

After the extension is consumed, a failing assessment creates
`proportional_quality_extension_exhausted` with only
`continue_with_debt` and `stop`. `extend_once` is absent rather than rejected
after selection, so neither a human nor COMMANDER can request it again.

The sealed decision includes or references:

- the selected candidate manifest and specification digest;
- automatic and extension repairs consumed;
- current scores, thresholds, and failed gates;
- material SAGE findings and finding routes;
- score history and per-repair deltas;
- formal-statement and byte growth from the baseline candidate; and
- whether the last repair produced no artifact progress.

### Recommendation

The controller recommends `extend_once` only when:

- every remaining gate is within the configured `borderline_margin`;
- the last completed repair improved every still-failing dimension; and
- the repair did not increase the number of formal statements.

Otherwise it recommends `continue_with_debt`. `stop` is always available but
is not automatically recommended by numeric evidence alone. The recommendation
is advisory for a human and bounded evidence for COMMANDER; it is not an
automatic transition.

### Autonomy behavior

- **Guided:** the decision is sealed as `awaiting_human`.
- **Semi:** the material decision uses `require_human` and is sealed as
  `awaiting_human`.
- **Banzai:** the decision is sealed as `pending`; COMMANDER chooses among the
  same exact option identifiers and evidence through the existing bounded
  decision-resolution protocol.

COMMANDER receives no authority to mutate counters, artifacts, state, or
routing. The controller validates and applies its selected option. If
COMMANDER fails the existing two-attempt decision-resolution limit, the run
blocks for diagnosis and never guesses or silently accepts debt.

## Resolution Effects

### Extend once

Selecting `extend_once`:

- marks the first decision resolved with its resolver;
- sets `extension_authorized` to one immediately, so the option cannot be
  selected again;
- routes to `phase1-what` with the selected candidate and exact remaining
  failures as repair context; and
- prevents any later extension authorization for the run.

Operational failure during the extension does not set `extension_consumed` and
remains recoverable as the same already-authorized extension; it does not grant
a second extension. A valid WHAT completion sets `extension_consumed` even when
the specification is unchanged, because the authorized attempt has concluded.
Once that candidate is assessed, a remaining failure opens the two-option
extension-exhausted decision.

### Continue with debt

Selecting `continue_with_debt` creates a separate content-bound authorization:

```yaml
spec_quality_debt_authorization:
  schema_version: 1
  status: accepted_with_debt
  source_path: <project-relative spec.md>
  source_sha256: <sha256>
  understanding_evidence: <immutable report path>
  understanding_evidence_sha256: <sha256>
  candidate_manifest: <run-local manifest path>
  candidate_manifest_sha256: <sha256>
  debt_artifact: <project-relative quality-debt.json>
  debt_artifact_sha256: <sha256>
  decision_id: <sealed decision id>
  resolved_by: user|COMMANDER
  accepted_at: <UTC timestamp>
```

This authorization never changes the Understanding report to passing and never
creates `spec_quality_certificate`. The Lexicon boundary accepts either a
current passing certificate or a current digest-matched debt authorization.
Any amendment to `spec.md`, replacement of the Understanding report, or change
to the candidate or debt artifact invalidates the authorization.

The controller generates `quality-debt.json` beside `spec.md`. It includes the
failed gates, thresholds, scores, findings, repair accounting, candidate
selection rationale, decision identity, resolver, and timestamp. It is
published with the specification and injected into downstream planning and
verification context.

### Stop

Selecting `stop` resolves the decision, retains the restored best candidate and
all evidence, and leaves the run blocked with
`proportional_quality_debt_declined`. It creates neither a passing certificate
nor a debt authorization. Status output explains that the user may start a new
run, including a new run after deliberately changing project quality policy;
ordinary `continue` cannot reopen the exhausted loop.

## Workflow and Certification Boundaries

`phase1-why2` still requires an ordinary passing Understanding result and SAGE
PASS to create `spec_quality_certificate`. Residual eligible failure is
intercepted by the controller before the generic global iteration route once
the proportional budget is exhausted.

The Lexicon derivation precondition becomes:

```text
current spec_quality_certificate
OR current spec_quality_debt_authorization
```

The two paths remain distinguishable throughout Phase A. Later readiness and
publication checks must propagate, rather than collapse, the status
`accepted_with_debt`. Downstream agents receive the exact debt artifact as
context and must not infer that a recorded quality failure is resolved.

## CLI Presentation

At budget exhaustion, the normal result and next-step presentation shows:

- `Specification quality: decision required`;
- `Automatic repairs: 3 of 3`;
- extension state;
- restored candidate identifier;
- failed gate scores and thresholds;
- material SAGE findings;
- formal-statement and byte growth;
- recommendation and rationale; and
- the exact choice syntax accepted by `echelon spec resume`.

After debt acceptance, `echelon spec status`, the final run summary, published
specification metadata, and downstream status consistently say
`accepted with quality debt` and reference `quality-debt.json`. They must not
display a generic PASS, fully certified, or debt-free completion claim.

The run summary remains concise: it names the accepted debt and the most
important failed gates, while `echelon spec status` and the artifact carry the
full evidence. Banzai output identifies COMMANDER as the resolver.

## Compatibility and Migration

- Existing specifications require no format migration.
- Existing and legacy missing authoring mode still normalize to proportional.
- A legacy active proportional run derives consumed automatic repairs from its
  immutable WHY2 candidate history, capped at three; it never receives three
  fresh repairs merely because the software was upgraded.
- A legacy run without trustworthy candidate history starts the bounded record
  at its current global iteration count, capped at three, and records the
  migration basis.
- Perfectionist runs retain the existing quality thresholds, global iteration
  budget, SAGE behavior, and fail-closed terminal semantics.
- Project-configured quality thresholds and `borderline_margin` remain
  authoritative.
- The quality-debt option is a controller workflow decision, not a new CLI
  authoring mode, provider capability, or threshold override.

## Verification Strategy

### Requirements-quality analysis

Focused tests prove:

- projection separates normative prose, traceability, and constraints without
  losing the original statement;
- structure and semantic categories consume the same role extraction;
- metadata does not distort structure, readability, cognitive, or behavioral
  scores;
- constraints and references still contribute to testability and depth;
- existing Lexicon controlled-grammar analysis remains compatible; and
- the retained Hello World first candidate no longer receives contradictory
  structure and semantic role judgments.

### Controller routing and state

Integration tests prove:

- a proportional run performs at most three automatic changed repairs;
- the initial assessment is not counted as a repair;
- provider and controller failures do not consume repair allowance;
- an unchanged WHAT pass routes directly to the decision;
- counters survive continue, resume, interruption, and prepared-run recovery;
- candidate ranking and tie-breaks are deterministic;
- restoration checks checkpoint and artifact hashes and cannot rewind unrelated
  state;
- hard-blocked candidates cannot enter quality-debt routing;
- the extension is offered and authorized at most once; and
- perfectionist routing remains unchanged.

### Decision and authorization

Decision tests prove:

- guided and semi wait for a human choice;
- banzai dispatches COMMANDER with the identical sealed option set;
- COMMANDER cannot mutate state or choose an undeclared option;
- exhausted COMMANDER resolution fails closed;
- recommendations follow the borderline, failing-dimension improvement, and
  no-growth rules;
- accepted debt produces digest-bound authorization and artifact;
- any source or evidence change invalidates authorization;
- ordinary PASS still produces only the existing passing certificate; and
- `stop` cannot be resumed into another automatic loop.

### CLI and publication

CLI, package, and deployment tests prove:

- the decision shows counts, gates, growth, recommendation, and valid commands;
- accepted debt remains visible in status and the final run summary;
- publication includes `quality-debt.json` and preserves debt status;
- downstream prompts receive the debt artifact;
- no output calls debt a passing certification; and
- Prosaic/runtime bundle installation deploys any changed workflow contracts.

### Live benchmark

A fresh isolated Codex workspace runs the exact minimal Hello World request
with proportional authoring. It must either pass or reach the sealed decision
after no more than three automatic repairs. The benchmark records duration,
provider dispatch counts, scores, selected candidate, formal-statement growth,
and final decision. It must not reach a fourth automatic repair or grow through
unbounded metric-driven requirement creation.

The live benchmark is required before declaring the feature operationally
validated. Provider availability may prevent it from being a deterministic CI
gate, but inability to run it must be reported rather than replaced by a claim
of live verification.

## Non-Goals

This design does not:

- lower proportional quality thresholds;
- automatically accept quality debt in any autonomy mode;
- give COMMANDER authority beyond selecting a sealed option;
- permit debt for contradictions, evidence gaps, CRITICAL findings, invalid
  traceability, or operational failures;
- add more than one repair extension;
- change perfectionist repair semantics;
- make requirement count or line count a quality target;
- redesign all Understanding metrics; or
- merge the specification repair loop with terminal run summarization.
