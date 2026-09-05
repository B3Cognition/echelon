# RE v2 Guided and Bounded Convergence Design

**Date:** 2026-09-05

**Amends:** `2026-08-25-re-v2-l3-semantic-audit-closure-design.md`

**Status:** Approved direction; implementation pending

## Summary

An L3 semantic plateau currently ends with an opaque instruction:

```text
echelon re resume "<guidance>"
```

The command accepts arbitrary text, but status does not explain what decision
is needed or offer a safe default. More seriously, the successor binds only the
guidance object's hash into resolution work; the guidance text is absent from
the bounded provider context. The user can therefore pay for a successor that
cannot act on the answer that created it.

This amendment makes guidance effective and makes convergence finite. Status
derives a bounded explanation and offers a recommended guided successor, a
custom-guidance path, and an explicit Banzai path. Banzai executes at most one
recommended successor. If valid semantic closure still plateaus, Banzai accepts
every remaining semantic finding as authenticated residual debt and exposes the
result as `complete_with_debt`. It never accepts structural, authority,
snapshot-cleanliness, provider, or audit-completeness failures.

The implementation reuses the existing immutable guidance object, exact-child
reuse, semantic round limits, plateau detection, and `finalize --allow-partial`
concept. It does not add another public protocol number.

## Evidence and problem statement

The real OptaSearch L3 run `re-20260904-065536-022296` completed all 81 audit
targets and finalized seven source roots, then reached a valid semantic plateau
with 111 unresolved findings. Status supplied no finding-class summary and no
actionable guidance beyond the placeholder.

The current path has four distinct gaps:

1. `SemanticContextV1` has no operator-guidance field.
2. Resolution work includes the guidance hash as a dependency but does not load
   the referenced object into the provider context.
3. `echelon re status` does not derive recommended actions from the unresolved
   finding authority already present in the run.
4. RE v2 has no bounded Banzai orchestration. The delivery/spec autonomy mode
   is unrelated and must not be assumed to govern RE.

The existing semantic controller already bounds one child to three rounds per
target and stops after two no-reduction rounds. The missing bound is across
guided successors: different free-text answers can create an unbounded chain,
and the operator is given no basis for choosing an answer.

## Goals

- Put the exact immutable guidance directive in every applicable provider
  context and validate its hash before dispatch.
- Explain a semantic plateau without dumping source evidence or secrets.
- Offer safe, copyable, deterministic next actions.
- Let an operator request one bounded autonomous convergence attempt.
- Convert a remaining semantic plateau to explicit, authenticated residual
  debt rather than pretending that all findings were resolved.
- Guarantee that automatic execution cannot create an unbounded successor
  chain or repeat paid work.
- Preserve complete distinction between full-quality completion and accepted
  partial quality.
- Allow workspace synthesis and later L4 orchestration to consume accepted
  partial L3 authority while retaining debt provenance.
- Keep existing L3 runs readable and resumable.

## Non-goals

- Guessing product decisions or fabricating evidence.
- Reclassifying structural failures as semantic debt.
- Raising token, time, attempt, context, or semantic-round limits.
- Automatically starting workspace synthesis or L4 after L3.
- Adding severity to the frozen `SemanticFindingV1` schema in this change.
- Reusing delivery's COMMANDER or mutable project autonomy configuration as L3
  authority.
- Changing lower-layer L0-L2 artifacts during semantic convergence.
- Introducing a new user-visible protocol version.

## User experience

### Plateau status

Human status output groups the exact unresolved finding set by controller-owned
finding class and source. It shows counts, not evidence excerpts. It also
distinguishes a semantic plateau from an invalid or incomplete run.

Example:

```text
L3 BLOCKED — SEMANTIC PLATEAU
111 findings remain after bounded closure

classes
  contradictory_claim          12
  evidence_scope_gap            37
  requires_deeper_evidence      51
  requires_human_decision       11

recommended
  echelon re resume --recommended

finish with documented debt
  echelon re resume --banzai

custom decision
  echelon re resume "<your guidance>"
```

JSON status includes a typed `guidance` object with the same counts and action
records. Shell commands are fixed templates; provider-authored finding text is
never interpolated into a command.

### Recommended guidance

`echelon re resume --recommended` creates or reuses one ordinary guided
successor. Its canonical directive tells the resolver to:

- use only accepted bounded authority;
- close findings only when evidence supports the correction or qualification;
- preserve honest unresolved state when evidence is insufficient;
- never invent evidence or suppress a finding merely to reach completion; and
- record deeper-evidence and human-decision needs explicitly.

This command does not accept residual debt automatically. If the successor
plateaus, status offers the same explicit choices against that successor.

### Custom guidance

`echelon re resume "<guidance>"` remains supported. Status explains that custom
guidance should provide a product interpretation, resolve an ambiguity, or
authorize a documented assumption. The command rejects an empty answer and
retains the existing 8 KiB normalized-text bound.

### Banzai guidance

`echelon re resume --banzai` is an explicit operator acceptance policy for RE;
it is not inherited from `.echelon` delivery configuration.

The command:

1. creates or reuses exactly one successor carrying the recommended guidance;
2. executes that successor within its already-authorized token/time ceilings;
3. returns full completion if all findings close;
4. if and only if it ends at an authenticated semantic plateau, validates and
   records residual-debt acceptance; and
5. reports `complete_with_debt` with the exact retained finding set.

All remaining semantic finding classes, including
`requires_human_decision`, may be accepted as debt in Banzai because the
operator explicitly chose partial reverse-engineering quality. They remain
visible and are not converted to resolved findings.

## Guidance authority

### GuidanceDirectiveV1

The existing immutable human-guidance payload becomes a typed directive:

```json
{
  "schema_version": 1,
  "kind": "custom | recommended | banzai",
  "answer": "normalized bounded text",
  "accept_residual_debt": false,
  "automatic_successor_limit": 0,
  "automation_root_manifest_hash": null,
  "successor_index": 0
}
```

For `recommended`, the answer is the installed canonical recommendation,
`accept_residual_debt` is false, and the automatic limit is zero. For `banzai`,
the answer is the same canonical recommendation, debt acceptance is true, the
limit is one, the root is the originally blocked manifest, and the index is
one. Custom guidance cannot request automation or debt acceptance.

Legacy `{ "answer": ... }` guidance remains readable as a custom directive with
all automation fields disabled. The manifest continues to bind the content
hash of `human-guidance.json`; no manifest field or public protocol number is
added.

### Provider projection

Post-freeze `SemanticContextV1` gains an optional typed `operator_guidance`
projection containing the exact directive and object hash. Context validation
requires:

- the directive hash equals the manifest reference;
- a successor with guidance projects exactly one directive;
- a new audit epoch projects none;
- the directive's automation root and successor index are valid for its kind;
- the context identity includes the directive bytes; and
- the context remains within the frozen operation-specific byte ceiling.

Resolution, closure recheck, and source-composition guard contexts receive the
directive so every semantic participant applies the same policy. The renderer
adds a short, explicit `Operator guidance` heading before the canonical context
for visibility; the canonical context remains the authority.

Candidate certification continues to bind the guidance hash. Provider output
cannot alter, omit, or broaden the directive.

## Deterministic guidance summary

Status derives guidance information only from authenticated frozen findings,
closure receipts, source roots, and terminal events. It does not call a model.

`GuidanceSummaryV1` contains:

- terminal run and manifest IDs;
- frozen, closed, and unresolved counts;
- unresolved counts by finding class;
- unresolved counts by source;
- whether the run is eligible for recommended resume;
- whether it is eligible for Banzai debt acceptance; and
- fixed action identifiers and commands.

The summary deliberately omits finding explanations, repair contexts, evidence
snippets, and source payloads. A later detailed inspection command may expose
those locally, but it is outside this change.

Recommendation eligibility requires a valid terminal `blocked_plateau` or
semantic `blocked_incomplete` parent with authenticated retained authority.
Banzai debt acceptance is narrower: the child must reach
`blocked_plateau` after all selected audit targets were accepted and all seven
source roots (or the selected source-root set) were durably constructed.

## Residual debt acceptance

### Verified partial finalization

The existing partial-finalization concept is extended to v2 L3 authority. A
`ResidualDebtAcceptanceV1` record binds:

- accepted run manifest and authenticated terminal-event hashes;
- frozen audit epoch and closure-root hashes;
- exact selected source-root hashes;
- exact unresolved finding IDs grouped by source and finding class;
- deferred observation IDs;
- guidance directive hash;
- acceptance policy ID;
- source snapshot and selection identities; and
- the deterministic operation ID.

The record is written atomically and its content digest becomes the debt
manifest hash. Repeating finalization validates and returns the existing record;
it never creates a second acceptance.

Public status is `complete_with_debt`, while the underlying immutable L3 child
remains truthfully `blocked_plateau`. Human output always states both facts:

```text
L3 COMPLETE WITH DEBT
semantic child: blocked_plateau
accepted residual findings: 111
quality: partial
```

This avoids rewriting semantic history or claiming that unresolved findings
were closed.

### Fail-closed eligibility

Residual debt acceptance is rejected when any of these is true:

- the event or object chain is invalid;
- the source snapshot no longer matches or any selected source is dirty;
- any selected audit target lacks an accepted candidate;
- the epoch or final closure root is absent or unauthenticated;
- any selected source root is absent;
- a provider operation is indeterminate, active, or failed before semantic
  closure reached a plateau;
- the stop was caused by resource exhaustion, context projection, schema,
  implementation-authority, or contract failure;
- the guidance directive did not explicitly authorize debt acceptance; or
- the exact debt set cannot be reconstructed.

These failures remain blocked and actionable. Banzai does not reinterpret them.

## Bounded execution and idempotency

Automatic convergence has a hard lineage bound of one paid successor.

The Banzai directive binds the original blocked manifest and
`successor_index=1`. Preparation rejects an index greater than its limit. A
Banzai successor cannot automatically create another Banzai successor.

The existing semantic limits remain unchanged inside the successor:

- at most three semantic rounds per audit target;
- plateau after two consecutive no-reduction rounds;
- fixed provider and contract retry limits; and
- existing run-wide and semantic resource ceilings.

The deterministic progress vector is:

```text
(unresolved finding count, unresolved finding ID tuple)
```

The successor may close findings but may not add or replace frozen finding IDs.
If the vector does not shrink within the existing plateau bound, the child
stops. There is no automatic “try again” branch.

Exact request identity includes the directive hash and blocked-parent
authority. Repeating `resume --recommended` or `resume --banzai` finds the exact
existing child. If that child is terminal, the command performs no provider
calls and only completes or validates the idempotent finalization step.

## Downstream authority

Workspace synthesis and L4 may consume `complete_with_debt` only when their
requests explicitly bind the residual-debt acceptance hash. They must:

- label input quality `partial`;
- preserve all unresolved finding and deferred observation IDs;
- include the debt manifest hash in their root authority;
- prevent generated prose from claiming exhaustive or full-quality L3 input;
  and
- keep full-quality and partial publication paths distinct.

The existing protocol-2.7 partial-source acceptance model is reused. A blocked
L3 source root becomes eligible as a partial source only through the verified
residual-debt record. No raw blocked root is directly adoptable.

L4 does not silently resolve accepted debt. It may produce deeper evidence that
supports a later explicit L3 epoch, but the original debt record remains
immutable provenance.

## CLI contracts

### Resume parsing

Exactly one of these is accepted:

```text
echelon re resume "<custom guidance>"
echelon re resume --recommended
echelon re resume --banzai
```

Budget overrides remain available and retain absolute-ceiling semantics.
`--recommended` and `--banzai` are mutually exclusive with positional guidance.

### Status routing

- `blocked_incomplete` with missing audit targets: recommended/custom only;
  Banzai debt acceptance is unavailable.
- `blocked_plateau` with complete audit/root authority: recommended, custom, and
  Banzai.
- `complete_with_debt`: no resume action; show synthesis/publication/L4 actions
  that explicitly retain partial quality.
- resource pause: continue with the exact required absolute ceilings.
- provider/structural failure: show the specific repair action, never guidance.

### Exit behavior

Banzai returns success when it reaches either `complete` or a validated
`complete_with_debt`. It returns nonzero for every fail-closed blocker. Output
names the quality level and never renders a blocked semantic child as fully
complete.

## Telemetry

Add deterministic lifecycle telemetry for:

- guidance kind and directive hash, never raw guidance text;
- recommended successor created/reused;
- Banzai successor created/reused;
- starting and ending unresolved counts;
- automatic successor count and limit;
- residual-debt acceptance ID and count;
- zero-call exact reuse; and
- Banzai rejection reason.

Token and active-time telemetry remains attributed to the actual provider
successor. Debt finalization consumes zero provider tokens.

## Compatibility and deployment

- Existing guidance payloads decode as non-automatic custom guidance.
- Existing terminal L3 runs can use the new recommended or Banzai path without
  rebuilding L0-L2 or accepted L3 authority.
- New semantic contexts use the installed corrected context schema and executor
  implementation digest. Compatibility is exact and fail-closed; no wildcard
  implementation alias is allowed.
- Public status uses the installed Echelon version and one current RE label. It
  does not expose internal protocol patch versions as user choices.
- Installation must precede live continuation because the PATH command runs
  from `~/.echelon/venv`.

## Testing

### Guidance projection

- A successor context contains exact guidance text and matching hash.
- Removing, changing, or substituting guidance fails before provider dispatch.
- Legacy guidance decodes as custom and is projected.
- New audit contexts reject guidance.
- Resolution, recheck, and source-guard prompts all carry the directive.

### Status and CLI

- Plateau status reports exact class/source counts and fixed commands.
- No provider-authored text is interpolated into commands.
- Recommended/custom/Banzai parsing is mutually exclusive and actionable.
- Incomplete audit and structural failures never offer Banzai debt acceptance.

### Banzai convergence

- One Banzai invocation creates at most one paid successor.
- Full closure returns `complete` without debt acceptance.
- A valid successor plateau returns `complete_with_debt` with exact debt.
- A second identical invocation creates no child and makes zero provider calls.
- A Banzai successor cannot automatically spawn another successor.
- Different manual guidance remains possible and explicit.

### Partial downstream use

- Every selected blocked source requires a matching verified acceptance entry.
- Synthesis/L4 requests bind the exact debt manifest.
- Missing, altered, or incomplete debt authority fails closed.
- Partial input cannot be rendered or published as full quality.

### Regression and real workspace

- Existing protocol-2.5/2.6 recovery, exact-child reuse, and budget tests remain
  green.
- The full Python suite passes.
- Reinstall Echelon.
- Exercise `status`, `resume --recommended`, and `resume --banzai` on a
  synthetic plateau first.
- Continue the preserved OptaSearch run only after synthetic verification,
  keeping all stashes and requiring every selected source repository to remain
  clean.

## Acceptance criteria

The change is complete when:

1. User guidance is present in authenticated provider context and demonstrably
   changes the successor request.
2. Plateau output explains the remaining finding classes and offers usable
   commands without requiring protocol knowledge.
3. Banzai makes no more than one paid successor and cannot loop across lineage.
4. A valid remaining plateau becomes `complete_with_debt` with an exact,
   validated debt manifest.
5. Invalid, incomplete, dirty, or indeterminate runs remain blocked.
6. Downstream consumers preserve partial-quality and debt authority.
7. Existing runs remain readable and exact retries remain zero-call.
8. Telemetry makes every automatic action and debt acceptance visible.
