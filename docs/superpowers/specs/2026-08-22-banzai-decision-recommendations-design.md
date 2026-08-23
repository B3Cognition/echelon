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
- Every automatic resolution of a newly sealed schema-v3 decision is made
  against the sealed recommendation and durably records its rationale,
  confidence, whether it followed or overrode that recommendation, and the
  sealed evidence behind the recommendation.
- An automatic override is explicit and retains the resolver's rationale. A
  model cannot silently contradict a recommendation.
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
to an actionable controller failure; COMMANDER is not asked to invent one. The
human-only form carries a bounded `recommended_action` explaining what input to
provide and the exact resume command. That action is never treated as the answer.

### Recommendation provenance

The prepared request carries an immutable recommendation snapshot:

- exactly one target: recommended option ID, recommended free-text answer, or
  human-only recommended action;
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
- `recommendation_followed`;
- an `override_reason` when the selected answer differs from the recommendation.

Following the recommendation may use its sealed rationale, confidence, and
evidence without another provider-authored explanation in the deterministic
semi path. COMMANDER continues to return its own explanation. A COMMANDER
override uses that already-required, non-empty rationale as `override_reason`.
The existing `high | medium | low` COMMANDER confidence contract remains
unchanged; this fix persists confidence but does not introduce a new acceptance
threshold.

Human answers remain authoritative. For a recommended option or
`recommended_answer`, the controller records whether a human selection
followed the recommendation, but does not fabricate a human rationale or
confidence when the user did not provide one. A `recommended_action` is
instructions, not an answer, so a human-only free-text resolution records
`recommendation_followed: null` rather than a false comparison.

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

`automatic_eligible` is controller-derived, not provider-controlled. A choice
with one recommendation is eligible under the existing autonomy/risk policy. A
free-text decision is eligible only when it has a non-empty recommended answer;
confidence remains audit metadata and does not change the existing routing
thresholds.

For Banzai, `automatic_eligible: false` selects `awaiting_human` even when the
classification is `material`. The human-resume guard accepts that Banzai answer
only when the sealed decision is explicitly ineligible for automatic
resolution; it continues to reject human injection into an automatically
eligible Banzai decision. This gives recommendation-free `agent_blocked`,
`consecutive_why_fails`, `why2_metric_stagnation`, and provider
`STOP_AND_ASK` requests one valid recovery path without reclassifying them as
external prerequisites. Status renders `echelon spec resume "<answer>"` for
that path.

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
  the current Lexicon pass when that gate is enabled recommends `approve`.
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
- At `checkpoint-plan`, the existing static low-risk `approve` recommendation
  remains unchanged and uses `workflow_policy` provenance. This fix does not
  add another plan/consensus gate.

The COMMANDER prompt renders an `Authoritative Recommendation` section before
raw registered context. It distinguishes an ordinary pass from
`accepted_with_debt`, renders the sealed recommendation evidence, and states
that retained failure evidence is the authorized debt when applicable. The
strict COMMANDER return envelope remains selected answer, rationale, and
confidence; no new provider-return evidence field is introduced.

#### Accepted-debt currentness

The global `blocked_decision` field is the authority for the active or most
recent decision, not the permanent root of a quality-debt authorization. During
the atomic debt-acceptance transaction, the current resolving decision ID and
state revision must match. The transaction canonicalizes one resolved v2/v3
postimage and requires exact equality between the decision written to state and
the snapshot embedded in the authorization; independently constructing two
postimages is forbidden. It stores that snapshot and its digest in both the
state authorization and `quality-debt.json`, then binds them to the existing
durable resolution completion receipt.

After that transaction, debt currentness validates the embedded decision through
the versioned decision validator, its digest, the authorization/artifact match,
the resolution completion receipt, and all existing content-bound candidate,
Understanding, repair-accounting, and spec digests. It does not require the
reusable `state.blocked_decision` slot to remain equal to the embedded debt
decision. A later checkpoint decision may therefore occupy that slot without
invalidating accepted debt. Tampering with either embedded snapshot, its digest,
the completion receipt, or any content-bound input still invalidates the
authorization and triggers the existing Phase 1 guard.

### 3. Other choice producers

Existing proportional-quality helpers already derive a unique option from
sealed score and repair evidence. They will return the recommendation rationale
and evidence through `PreparedHumanInput` instead of writing an unconnected
state-side explanation.

The phase-dispatch-cap helper will recommend the first eligible issue in the
authoritative `issues.md` document order as a deterministic processing choice,
not as a claim that it has higher product or quality priority. Every eligible
entry already carries a single evidence-backed suggested option and evidence
basis; the recommendation rationale states only that the issue is the first
eligible entry. The evidence digest binds both the selected issue and its
suggestion. No SAGE priority field or ordering rule is added. If no eligible
issue exists, the existing manual diagnosis route remains in force and the CLI
recommends the exact repair action; no choice decision is created.

Provider-originated choice escalations must contain exactly one recommended
option. Free-text provider escalations remain eligible for automatic resolution
only when they include the paired recommended answer and risk metadata already
supported by the phase authoring contracts. Without an evidence-backed
recommendation they remain valid human-only requests; they are not permission
for COMMANDER to improvise.

### 4. Durable blocked-decision schema v3

Fresh human-input decisions use blocked-decision schema v3. It retains the v2
identity, status, question, option, routing, attempt, and timestamp fields and
adds exact recommendation and resolution audit fields:

- `recommended_option_id` (choice) or the existing `recommended_answer`
  (automatically resolvable free text), or `recommended_action` (human-only free
  text), with exactly one recommendation target;
- `automatic_eligible`, which is true only when a complete recommended option
  or answer is available and the existing autonomy/risk policy permits automatic
  resolution;
- `recommendation_rationale`, `recommendation_confidence`,
  `recommendation_authority`, and `recommendation_evidence`;
- `resolution_rationale` and `resolution_confidence`;
- `recommendation_followed` and `override_reason`.

The validator cross-checks `recommended_option_id` against the sole option whose
flag is `true`. A choice always has `recommended_option_id`; free text without
an evidence-backed answer has `recommended_action`,
`automatic_eligible: false`, and cannot be routed to semi or COMMANDER.
Unresolved decisions have null resolution audit fields.
Resolved automatic decisions require the complete automatic audit. An automatic
selection different from the recommendation requires the override contract;
one that matches it forbids `override_reason`. Resolved human decisions permit
null rationale/confidence. `recommendation_followed` is Boolean for a
recommended option or `recommended_answer`, and null for a human-only
`recommended_action`, which must never be compared with the supplied answer.

`DecisionResolution` remains the strict provider-return type. A new immutable
`AppliedHumanInputResolution` is the only type accepted by resolution handlers
and the atomic state transaction. It contains the selected option or answer,
`resolved_by`, and nullable rationale/confidence fields. COMMANDER conversion
copies all `DecisionResolution` fields and adds `resolved_by: COMMANDER`; it may
not narrow the result to the current answer-only `HumanInputResolution`.
Deterministic semi resolution copies rationale/confidence from the sealed
recommendation and adds `resolved_by: semi`. Human resolution uses
`resolved_by: user` with null rationale/confidence unless future user input
explicitly supplies them. The state validator enforces those resolver-specific
shapes before route effects are applied.

### 5. Compatibility and migration

The deployed workflow/controller compatibility version increases from 1 to 2.
An old deployed workflow therefore fails the pre-run compatibility guard before
initialization or provider work.

Schema-v2 blocked decisions remain readable, and generic writes cannot mutate
their authority:

- resolved v2 decisions are historical records and are never assigned invented
  rationale or confidence;
- existing quality-debt artifacts may continue to validate their embedded v2
  resolved decision and digest;
- a new quality-debt authorization embeds the v3 decision and validates its
  complete recommendation/resolution audit;
- a v2 `awaiting_human` decision is grandfathered through the existing v2
  human-resume and application path. It remains v2 across restart, may have zero
  recommended choices under the historical contract, and is never promoted to
  provider or semi resolution. This preserves valid guided/external prompts
  without inventing a recommendation or destroying their `spec resume` path;
- a v2 semi decision is also grandfathered through its existing deterministic
  recovery/resolution path. Its already-sealed option or recommended answer is
  applied without provider dispatch, it resolves as v2, and no v3 rationale or
  confidence is invented;
- only a v2 Banzai `pending` decision is upgraded by re-preparing its
  recommendation from current registered policy and authoritative state, then
  replacing it through a dedicated compare-and-swap migration transaction. An
  interrupted Banzai `resolving` decision first follows the existing recovery
  protocol and enters migration only if it returns to `pending`. The
  transaction requires the same decision ID and state revision and preserves
  attempts, creation time, and the unresolved answer/routing contract. It
  preserves `pending` only when the prepared v3 decision remains automatically
  eligible; a now-ineligible Banzai free-text decision changes from `pending`
  to `awaiting_human`. The v3 validator permits that migrated human-wait state
  to retain one prior automatic attempt, so migration cannot reset the provider
  retry budget. This transaction is the only authority allowed to replace an
  active v2 decision with v3. If preparation cannot produce a unique
  recommendation or human-only action, continuation
  uses a separate revision-checked authority transaction to move the v2 decision
  to terminal `failed` with
  `failure_code: decision_recommendation_unavailable`. It preserves the v2
  identity, policy reason, question/options, attempts, and creation time, updates
  the controller-owned blocked reason, and writes the canonical failed-decision
  recovery pair atomically. No generic write may manufacture this postimage.
  Recovery classification checks that failure code before the generic v2
  recovery kind and renders the source-specific rewind/replay action described
  below. Restart therefore exposes the same reason and executable command, and
  no provider dispatch occurs.

Recovery-instruction schema v2 does not change because it already binds status,
reason, phase, and decision ID independently of blocked-decision schema. Its
pair validator will accept either a legacy v2 or current v3 blocked decision.

The currently rejected Phase 1 run is not silently rewritten. After the fix is
deployed, it can be deliberately rewound to its retained Phase 1 Lexicon
checkpoint and continued. Rewind of a resolved rejection preserves that
decision and its display authority while resetting phase progress; in
particular, it must not manufacture `escalation_resolved: false` for the
terminal decision.

The next gate seal may then replace that resolved decision through the existing
human-input authority transaction with a new schema-v3 decision derived from
the still-current debt authorization. A regression test starts from the exact
resolved `gate_rejected` state shape and proves that rewind passes state-authority
validation before the new gate is sealed.

### 6. Operator-facing recovery

Status, run summary, and blocked-decision rendering show:

- the recommended option, answer, or human-only action;
- the recommendation rationale and confidence;
- whether an automatic resolver followed or overrode it;
- the persisted override reason when applicable;
- one exact next command for unresolved, failed, terminal-rejected, or
  recommendation-unavailable states.

The fallback phrase “resolve the reported blocker” is insufficient for a typed
decision failure. Each new stable failure reason maps to a concrete action such
as syncing the runtime, answering the displayed question, rewinding the named
checkpoint, or running the displayed diagnostic command.

For a resolved `gate_rejected` run, the status layer resolves the latest
rewindable checkpoint that precedes the rejected gate from the active checkpoint
ledger and renders the executable rewind command, including `--commit` when the
checkpoint ID is ambiguous. For the reproduced run that command is
`echelon spec rewind phase1-lexicon --confirm`; it must not recommend
`echelon spec continue` while the phase remains `terminal-blocked`.

An exhausted automatic decision also has an executable recovery, not
`MANUAL_DIAGNOSIS` prose:

- a failed human gate uses the same ledger-derived rewind command. Unlike a
  resolved rejection, the failed decision would stop controller bootstrap before
  the gate can reseal. The confirmed rewind therefore includes a dedicated
  human-input-authority transaction that checks state revision, decision ID,
  `status: failed`, `source_kind: human_gate`, Banzai mode, and that the
  selected checkpoint is the registered predecessor of the source gate. It
  validates v3 automatic eligibility or reconstructs the legacy v2 gate policy
  when the failure arose during migration. In the same state commit that resets
  phase progress, it retires the failed decision/recovery/display authority.
  Deployed workflow validation requires every automatically resolvable human
  gate to have that rewindable predecessor;
- a failed Banzai provider escalation or controller safeguard renders
  `echelon phase run <source-phase>`. The existing manual-replay authority
  transaction is extended to accept only a failed automatic decision of those
  two source kinds whose sealed source phase exactly matches the requested
  phase. For legacy v2 it first reconstructs the registered automatic
  eligibility instead of trusting absent metadata. It atomically retires that
  failed authority and replays the source phase. No generic save, `continue`,
  or human answer may reset the exhausted attempts; only this explicit operator
  command starts a fresh decision.

## Data Flow

1. Workflow validation compiles policy and rejects invalid static
   recommendations.
2. A provider or controller-specific preparer constructs a typed request and a
   recommendation snapshot from registered authority.
3. The state store atomically seals a schema-v3 decision plus its existing
   recovery instruction.
4. Guided/external decisions wait for the user. Semi applies only an eligible
   low-risk recommendation. Banzai sends an automatically eligible material
   decision to COMMANDER and sends an ineligible free-text decision to the
   human-resume path.
5. COMMANDER receives the recommendation before raw context and returns the
   existing strict answer, rationale, and confidence envelope.
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
- COMMANDER returns a malformed answer, rationale, or confidence envelope:
  count it as `invalid_resolution_result` under the existing bounded retry
  policy.
- Two invalid provider attempts: preserve the failed v3 decision and its
  recommendation audit. Render a ledger-derived rewind for a human gate or the
  exact source-phase replay command for a provider escalation/controller
  safeguard; never render unactionable diagnosis prose.
- State revision changes between recommendation preparation and sealing or
  resolution: reject through the existing compare-and-swap boundary.
- Legacy v2 decision cannot be safely upgraded: atomically seal the exact
  terminal migration-failure postimage, consume zero provider tokens, and let
  the failure-code classifier render its source-specific recovery command.

## Tests

### Static and preparation contracts

- Workflow validation rejects a static human-gate choice with zero or multiple
  recommendations, and rejects controller mode without a registered preparer.
- Every canonical static choice policy has exactly one recommendation.
- Dynamic helpers cannot reach the seal boundary until they attach exactly one
  recommendation and bounded evidence.
- Provider choices with no recommendation and automatic free-text requests with
  no recommended answer are rejected.
- Banzai free text without a recommended answer seals as `awaiting_human`,
  accepts a human resume answer, and never dispatches COMMANDER; an
  automatically eligible Banzai decision still rejects human injection.
- Human-only free text persists and renders a `recommended_action`, but never
  applies that action as an answer; after the user answers,
  `recommendation_followed` remains null.

### Checkpoint regression

- Ordinary current Phase 1 PASS recommends `approve` at
  `checkpoint-assess`.
- Current `accepted_with_debt` recommends `approve`, names the debt
  authorization, and keeps raw `quality-gates.md` FAIL evidence visible as debt.
- Sealing and resolving the later checkpoint decision replaces
  `state.blocked_decision` without invalidating the embedded quality-debt
  decision, digest, or completion authority.
- Debt acceptance writes one canonical resolved decision postimage to both
  current state and the embedded authorization; injected divergence aborts the
  atomic transaction before the debt artifact is published.
- Tampering with the embedded debt decision, digest, completion receipt, or any
  existing content-bound input still makes the Phase 1 guard invalidate debt.
- Missing or stale Phase 1 authority blocks before a provider call with
  `decision_recommendation_unavailable` and an actionable next command.
- The reproduced proportional Hello World sequence advances from
  `checkpoint-assess` to `phase2-decide` when COMMANDER follows the sealed
  recommendation, including through the downstream Phase 1 quality guard.
- The exact accepted-debt → checkpoint rejection → rewind → fresh checkpoint
  approval sequence retains debt currentness at every boundary and reaches
  `phase2-decide` without routing back to `phase1-understanding`.

### Resolution audit

- Semi resolution persists recommendation rationale/confidence/evidence and
  `recommendation_followed: true`.
- COMMANDER following the recommendation persists its returned rationale,
  confidence, and `recommendation_followed: true`.
- A COMMANDER override at any already-valid confidence level persists
  `recommendation_followed: false` and an explicit override reason.
- A valid `low`-confidence COMMANDER result remains accepted and persists as
  `low`; this change adds no confidence threshold.
- Malformed override envelopes are rejected without applying route effects.
- Restart and interrupted-claim recovery preserve all recommendation fields.

### Compatibility and presentation

- Fresh decisions are schema v3; legacy resolved v2 decisions remain readable.
- Pending Banzai v2 decisions migrate only through the dedicated
  revision-checked transaction; interrupted Banzai `resolving` decisions first
  use existing recovery.
- A pending v2 Banzai free-text decision that has no recommended answer migrates
  to v3 `awaiting_human` without resetting a prior attempt.
- Legacy guided/external v2 choices already in `awaiting_human`, including
  choices with zero recommendations, remain v2 across restart and resolve
  successfully through `echelon spec resume` without provider dispatch.
- A legacy semi v2 pending/resolving fixture remains v2 across restart, follows
  its already-sealed recommendation through the existing deterministic path,
  and resolves without requiring reconstructable v3 metadata or inventing
  rationale/confidence.
- A v2 migration that cannot reconstruct a recommendation/action atomically
  becomes the exact terminal migration-failure postimage. Restart preserves its
  failure-code recovery priority, makes no provider call, and executing the
  displayed source-specific command recovers it.
- Both legacy-v2 and current-v3 debt authorizations retain content/digest
  validation.
- Rewinding the reproduced resolved `gate_rejected` state preserves its
  terminal decision/display authority, passes generic state validation, and
  permits the next gate seal to replace it with a fresh v3 decision.
- Status for that terminal rejection derives and renders
  `echelon spec rewind phase1-lexicon --confirm` from the retained checkpoint
  ledger and does not recommend `echelon spec continue`.
- Failed human-gate and provider/safeguard fixtures render their respective
  rewind/replay commands, and executing each displayed command performs the
  authority-valid recovery. Mismatched phase, source kind, non-Banzai mode, or
  non-failed status cannot retire a decision.
- The failed-human-gate rewind retires its exact decision in the rewind state
  transaction; the following `echelon spec continue` reaches and seals a fresh
  gate. The resolved-`gate_rejected` rewind instead preserves its historical
  decision until the fresh gate seal replaces it.
- The replay transaction trusts v3 `automatic_eligible` only after schema
  validation; for a failed legacy v2 decision it reconstructs the registered
  policy and eligibility before permitting replay.
- Deployed compatibility version 1 is rejected before run side effects after
  the controller requires version 2.
- CLI status and summaries display the recommendation, automatic decision
  rationale, override state, and exact next action.

## Acceptance Criteria

A Banzai choice cannot reach COMMANDER unless exactly one recommendation and its
evidence are sealed in durable state. If COMMANDER resolves it, the final state
answers what was recommended, what was selected, why, with what confidence,
which evidence supported the recommendation, and whether it was overridden.

For a current `accepted_with_debt` Phase 1 candidate, the checkpoint recommends
`approve` and explicitly explains why the retained `FAIL` artifact represents
authorized debt rather than a new rejection signal. The authorization remains
current when the checkpoint decision replaces the reusable decision slot, while
its embedded snapshot and completion proof remain fail-closed. A missing
recommendation or invalid authority consumes zero provider tokens and leaves the
operator with one concrete recovery command. A resolved or failed decision
never recommends an inoperative `continue`; it names an executable,
authority-valid rewind or source-phase replay.
