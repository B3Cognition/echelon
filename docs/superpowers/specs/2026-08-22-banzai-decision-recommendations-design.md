# Banzai Decision Recommendations and Audit Design

## Problem

The centralized autonomy routing introduced in late July correctly sends a
non-external Banzai decision to COMMANDER, but the surrounding contract is
incomplete in two independent ways:

1. A sealed choice may contain no recommended option. The Phase 1 assessment
   gate currently declares both `approve` and `reject` as
   `recommended: false`, so COMMANDER receives a material decision without a
   controller recommendation.
2. COMMANDER must return a rationale and confidence, but the controller converts
   that result to `HumanInputResolution`, which retains only the selected answer
   and resolver. Schema-v2 blocked-decision state therefore cannot explain why
   an automatic choice was made or whether it overrode the recommendation.

The defect became visible after proportional quality debt was added. A run may
have a current, explicit `accepted_with_debt` authorization while the preserved
`quality-gates.md` correctly continues to say `FAIL` for the unresolved debt.
The checkpoint prompt currently exposes the raw artifact but does not synthesize
the authoritative state. With no recommended option, COMMANDER can interpret
that retained debt as a reason to reject the already-authorized candidate. The
run then reaches `terminal-blocked` with only `resolved_by: COMMANDER` and no
durable explanation.

The tests added during the Banzai overhaul verified routing and the strict
provider return envelope. They did not verify that every choice has one
recommendation, that authoritative evidence is synthesized before dispatch, or
that the returned rationale and confidence survive state persistence.

## Goals

- Every newly sealed choice decision has exactly one evidence-backed
  recommended option.
- Every automatic resolution is made against the sealed recommendation and
  durably records its rationale, confidence, evidence references, and whether
  it followed or overrode that recommendation.
- An automatic override is explicit, high-confidence, and attributable to
  controller-registered evidence. A model cannot silently contradict a
  recommendation.
- `accepted_with_debt` is represented truthfully: the underlying quality failure
  remains visible, while the valid debt authorization makes approval the
  checkpoint recommendation.
- If the controller cannot construct a unique recommendation, it does not spend
  provider tokens or guess. It stops with a stable reason and an exact recovery
  recommendation.
- Status and summary output always tell the operator what action is recommended
  for an active or failed decision.
- Existing resolved decisions and content-bound quality-debt authorizations
  remain verifiable without inventing missing historical rationale.

## Non-goals

- Do not auto-approve every checkpoint or remove human/COMMANDER judgment.
- Do not weaken quality gates or translate accepted quality debt into `PASS`.
- Do not let an executor or provider mutate controller-owned workflow options,
  recommendation authority, or evidence identities.
- Do not silently rewrite a previously resolved rejection.
- Do not infer a substantive free-text answer when the available evidence only
  supports asking the user for one.

## Chosen Approach

The fix uses a versioned decision contract and one recommendation-preparation
boundary. Two narrower alternatives were rejected:

- Marking `approve` as statically recommended at `checkpoint-assess` would fix
  this one prompt but would ignore accepted-debt authority, other dynamic
  choices, missing recommendations, and the discarded COMMANDER audit.
- Writing rationale/confidence to an unrelated sibling state field would avoid
  a schema bump but would allow the decision and its audit to diverge under
  retries, rewind, or content-bound debt authorization.

Schema v3 keeps the recommendation and resolution audit inside the same
compare-and-swap authority as the decision. Dedicated preparers synthesize
dynamic recommendations before that authority is sealed.

## Invariants

### Recommendation completeness

A choice is valid only when it has at least one option and exactly one option
whose `recommended` field is `true`. “At most one” is no longer sufficient.
This rule applies to workflow human gates, controller safeguards, dynamically
prepared issue choices, and provider-originated choice escalations before they
can be sealed.

A free-text decision may be sealed without a `recommended_answer` only when it
is not eligible for automatic resolution. A Banzai/COMMANDER or semi-automatic
free-text decision requires a non-empty, evidence-backed recommended answer.
When no answer can be inferred safely, the decision is routed to human input or
to an actionable controller failure; COMMANDER is not asked to invent one.
Recommendation confidence below `medium` also makes a decision ineligible for
automatic resolution.

### Recommendation provenance

The prepared request carries an immutable recommendation snapshot:

- the recommended option ID or recommended free-text answer;
- a bounded, non-empty rationale;
- `high`, `medium`, or `low` confidence;
- an authority of `workflow_policy`, `controller_evidence`, or
  `provider_evidence`;
- whether the recommendation is eligible for automatic resolution;
- one or more bounded evidence records with stable IDs, kinds, references, and
  controller-computed SHA-256 digests.

The controller constructs and validates this snapshot before state sealing.
Provider-originated evidence is reduced to registered paths/state and digested
by the controller; provider-supplied arbitrary paths or evidence IDs are not
accepted as authority.

### Automatic resolution audit

For `semi` and `COMMANDER` resolutions, durable state records:

- resolution rationale and confidence;
- the registered evidence IDs used by the resolver;
- `recommendation_followed`;
- an `override_reason` when the selected answer differs from the recommendation.

Following the recommendation may use its sealed rationale, confidence, and
evidence without another provider-authored explanation in the deterministic
semi path. COMMANDER continues to return its own explanation. A COMMANDER
override requires `confidence: high`, at least one registered evidence ID, and
a non-empty override rationale. Low-confidence automatic results are not
applied.

Human answers remain authoritative. The controller records whether a human
selection followed the recommendation, but does not fabricate a human rationale
or confidence when the user did not provide one.

## Architecture

### 1. Prepared recommendation boundary

`PreparedHumanInput` becomes the single typed boundary for both the answer
shape and its recommendation metadata. Policy compilation rejects static choice
policies with zero or multiple recommendations. Dynamic policies retain an
unrecommended option template internally, but cannot pass through the general
`prepare`/seal boundary until a dedicated controller helper has selected one
option and attached recommendation evidence.

Each choice policy explicitly declares `recommendation_mode: static` or
`recommendation_mode: controller`. Static mode requires exactly one recommended
option in the compiled policy. Controller mode permits an unrecommended option
template only for a registered controller preparer and requires exactly one
recommendation in the resulting `PreparedHumanInput`. Provider-escalation
choices use their existing provider preparation boundary and must also arrive
there with exactly one recommendation.

This preserves the existing ownership split:

- workflow policy owns the available options and routes;
- controller helpers may select exactly one existing option from authoritative
  state;
- providers may propose values only where a provider-escalation policy already
  permits them;
- no preparation path may add an undeclared route or option.

### 2. Checkpoint recommendation synthesis

The human-gate interceptor uses a checkpoint-specific controller helper instead
of calling the generic registry directly. The helper validates current
controller authority and prepares one recommendation:

- At `checkpoint-assess`, a current ordinary Phase 1 quality certificate plus
  the required Lexicon result recommends `approve`.
- At `checkpoint-assess`, a current `accepted_with_debt` authorization also
  recommends `approve`. Its rationale names the accepted debt, resolver, and
  authorization digest. The preserved `quality-gates.md` `FAIL` remains an
  evidence record describing the debt; it is not presented as an unhandled
  controller failure.
- If Phase 1 lacks either a current passing certificate or a current debt
  authorization, the helper does not create the checkpoint decision. It blocks
  with `decision_recommendation_unavailable` and points to the failed authority
  check. It does not manufacture a `reject` recommendation from malformed or
  stale state.
- At `checkpoint-plan`, successful controller prerequisites recommend `approve`.
  The recommendation evidence binds the completed plan/consensus prerequisites
  and their current artifact digests.

The COMMANDER prompt renders an `Authoritative Recommendation` section before
raw registered context. It distinguishes an ordinary pass from
`accepted_with_debt`, lists the only valid evidence IDs, and states that retained
failure evidence is the authorized debt when applicable.

### 3. Other choice producers

Existing proportional-quality helpers already derive a unique option from
sealed score and repair evidence. They will return the recommendation rationale
and evidence through `PreparedHumanInput` instead of writing an unconnected
state-side explanation.

The phase-dispatch-cap helper will recommend the first eligible issue in the
authoritative `issues.md` order. That order is the existing bounded recovery
queue, and every eligible entry already carries a single evidence-backed
suggested option and evidence basis. The evidence digest binds both the selected
issue and its suggestion. If no eligible issue exists, the existing manual
diagnosis route remains in force and the CLI recommends the exact repair action;
no choice decision is created.

Provider-originated choice escalations must contain exactly one recommended
option. Free-text provider escalations remain eligible for automatic resolution
only when they include the paired recommended answer and risk metadata already
required by the phase authoring contracts. Missing recommendation metadata is a
contract error, not permission for COMMANDER to improvise.

### 4. Durable blocked-decision schema v3

Fresh human-input decisions use blocked-decision schema v3. It retains the v2
identity, status, question, option, routing, attempt, and timestamp fields and
adds exact recommendation and resolution audit fields:

- `recommended_option_id` (choice) or the existing `recommended_answer`
  (automatically resolvable free text), with at most one answer shape;
- `automatic_eligible`, which is true only when a complete recommended answer
  is available to the active autonomy route;
- `recommendation_rationale`, `recommendation_confidence`,
  `recommendation_authority`, and `recommendation_evidence`;
- `resolution_rationale`, `resolution_confidence`, and
  `resolution_evidence_ids`;
- `recommendation_followed` and `override_reason`.

The validator cross-checks `recommended_option_id` against the sole option whose
flag is `true`. A choice always has `recommended_option_id`; free text without
an evidence-backed answer has `automatic_eligible: false` and cannot be routed
to semi or COMMANDER. Unresolved decisions have null resolution audit fields.
Resolved automatic decisions require the complete automatic audit. An automatic
selection different from the recommendation requires the override contract;
one that matches it forbids `override_reason`. Resolved human decisions permit
null rationale/confidence but still record the mechanically derived
`recommendation_followed` value.

The controller passes the full `DecisionResolution` through application and
atomic persistence. It no longer narrows the object to an answer-only
`HumanInputResolution` before the state transaction. Deterministic semi
resolution constructs the same complete resolution type from the sealed
recommendation.

### 5. Compatibility and migration

The deployed workflow/controller compatibility version increases from 1 to 2.
An old deployed workflow therefore fails the pre-run compatibility guard before
initialization or provider work.

Schema-v2 blocked decisions remain readable and immutable:

- resolved v2 decisions are historical records and are never assigned invented
  rationale or confidence;
- existing quality-debt artifacts may continue to validate their embedded v2
  resolved decision and digest;
- a new quality-debt authorization embeds the v3 decision and validates its
  complete recommendation/resolution audit;
- an active v2 decision is upgraded only by re-preparing its recommendation
  from current registered policy and authoritative state. If that cannot be
  done uniquely, continuation stops with
  `decision_recommendation_unavailable` before provider dispatch.

Recovery-instruction schema v2 does not change because it already binds status,
reason, phase, and decision ID independently of blocked-decision schema. Its
pair validator will accept either a legacy v2 or current v3 blocked decision.

The currently rejected Phase 1 run is not silently rewritten. After the fix is
deployed, it can be deliberately rewound to its retained Phase 1 Lexicon
checkpoint and continued. The new checkpoint decision is then created under
schema v3 from the still-current debt authorization.

### 6. Operator-facing recovery

Status, run summary, and blocked-decision rendering show:

- the recommended option or answer;
- the recommendation rationale and confidence;
- whether an automatic resolver followed or overrode it;
- the persisted override reason when applicable;
- one exact next command for unresolved, failed, or recommendation-unavailable
  states.

The fallback phrase “resolve the reported blocker” is insufficient for a typed
decision failure. Each new stable failure reason maps to a concrete action such
as syncing the runtime, answering the displayed question, rewinding the named
checkpoint, or running the displayed diagnostic command.

## Data Flow

1. Workflow validation compiles policy and rejects invalid static
   recommendations.
2. A provider or controller-specific preparer constructs a typed request and a
   recommendation snapshot from registered authority.
3. The state store atomically seals a schema-v3 decision plus its existing
   recovery instruction.
4. Guided/external decisions wait for the user. Semi applies only an eligible
   low-risk recommendation. Banzai sends a material, recommended decision to
   COMMANDER.
5. COMMANDER receives the recommendation before raw context and may return only
   a registered answer and evidence IDs.
6. The controller validates follow/override semantics, computes
   `recommendation_followed`, runs the closed resolution handler, and atomically
   persists both routing effects and the complete audit.
7. On restart, the decision/recovery pair is validated before any retry. A
   partially claimed decision preserves the recommendation and follows the
   existing bounded two-attempt recovery protocol.

## Error Handling

- Zero or multiple recommendations: fail workflow validation for static policy,
  or fail request preparation for dynamic/provider policy.
- Missing, stale, malformed, or contradictory recommendation authority: record
  `decision_recommendation_unavailable`; do not dispatch COMMANDER.
- COMMANDER returns an unknown evidence ID, low-confidence result, or malformed
  override: count it as `invalid_resolution_result` under the existing bounded
  retry policy.
- Two invalid provider attempts: preserve the failed v3 decision and its
  recommendation audit, then render a concrete manual recovery action.
- State revision changes between recommendation preparation and sealing or
  resolution: reject through the existing compare-and-swap boundary.
- Legacy v2 decision cannot be safely upgraded: preserve it and stop with the
  explicit migration/recovery recommendation.

## Tests

### Static and preparation contracts

- Workflow validation rejects a static human-gate choice with zero or multiple
  recommendations, and rejects controller mode without a registered preparer.
- Every canonical static choice policy has exactly one recommendation.
- Dynamic helpers cannot reach the seal boundary until they attach exactly one
  recommendation and bounded evidence.
- Provider choices with no recommendation and automatic free-text requests with
  no recommended answer are rejected.

### Checkpoint regression

- Ordinary current Phase 1 PASS recommends `approve` at
  `checkpoint-assess`.
- Current `accepted_with_debt` recommends `approve`, names the debt
  authorization, and keeps raw `quality-gates.md` FAIL evidence visible as debt.
- Missing or stale Phase 1 authority blocks before a provider call with
  `decision_recommendation_unavailable` and an actionable next command.
- The reproduced proportional Hello World sequence advances from
  `checkpoint-assess` to `phase2-decide` when COMMANDER follows the sealed
  recommendation.

### Resolution audit

- Semi resolution persists recommendation rationale/confidence/evidence and
  `recommendation_followed: true`.
- COMMANDER following the recommendation persists its returned rationale,
  confidence, and evidence IDs.
- A high-confidence COMMANDER override persists
  `recommendation_followed: false` and an explicit override reason.
- Low-confidence, evidence-free, or malformed overrides are rejected without
  applying route effects.
- Restart and interrupted-claim recovery preserve all recommendation fields.

### Compatibility and presentation

- Fresh decisions are schema v3; legacy resolved v2 decisions remain readable.
- Active v2 decisions migrate only when a current unique recommendation can be
  reconstructed.
- Both legacy-v2 and current-v3 debt authorizations retain content/digest
  validation.
- Deployed compatibility version 1 is rejected before run side effects after
  the controller requires version 2.
- CLI status and summaries display the recommendation, automatic decision
  rationale, override state, and exact next action.

## Acceptance Criteria

A Banzai choice cannot reach COMMANDER unless exactly one recommendation and its
evidence are sealed in durable state. If COMMANDER resolves it, the final state
answers what was recommended, what was selected, why, with what confidence,
which registered evidence was used, and whether the recommendation was
overridden.

For a current `accepted_with_debt` Phase 1 candidate, the checkpoint recommends
`approve` and explicitly explains why the retained `FAIL` artifact represents
authorized debt rather than a new rejection signal. A missing recommendation
or invalid authority consumes zero provider tokens and leaves the operator with
one concrete recovery command.
