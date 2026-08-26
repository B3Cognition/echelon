# RE v2 L3 Semantic Audit and Bounded Closure Design

**Date:** 2026-08-25  
**Findings:** EGR-167 and the L3 increment of EGR-169  
**Status:** Approved

## Summary

RE v2 protocols 2.2 through 2.4 produce reusable L0 inventory, L1 compact
baseline, and selectively deepened L2 behavioral artifacts. Those artifacts are
structurally certified and evidence-bounded, but deliberately remain
semantically unaudited.

This design registers L3 as an immutable semantic-audit overlay. An L3 child
adopts exact L0 through L2 authority, audits each selected domain and selected
source, freezes the resulting finding set into one audit epoch, and attempts to
close only that frozen set under an independent semantic budget. Resolution
adds L3 overlay artifacts; it never rewrites accepted lower layers.

The state transition is strict:

```text
accepted L0 -> accepted L1 -> accepted L2
                                  |
                                  v
                         frozen L3 audit epoch
                                  |
                                  v
                      bounded resolution overlays
                                  |
                                  v
                  target rechecks + source guard
                                  |
                     +------------+------------+
                     |            |            |
                     v            v            v
           selected L3       next epoch     terminal L3
           scope complete     required        blocker
```

An L3 epoch closes only when every frozen finding has a controller-owned closure
receipt after its selected-source guard. The selected L3 scope is complete only
when the epoch closes with no deferred observation requiring another explicit
epoch. Resource exhaustion may pause and continue the same epoch. Semantic
plateau or exhausted fixed attempts terminalizes the child as blocked. A
successor may adopt closed receipts and target only unresolved findings, but an
identical retry performs zero provider calls.

All model-backed work continues through neutral Prosaic prose and Echelon's
existing shared coding-provider path. This design adds no provider adapter,
model mapping, API transport, credential path, or parallel workflow engine.

Workspace synthesis remains deferred to EGR-168. L4 exhaustive depth and
atomic lower-artifact repair remain later work.

## Context

The retained OptaSearch campaign recorded 340 semantic-validator dispatches.
Some domains were audited 22 to 35 times, obsolete domain identities consumed
107 calls and roughly 163.5M tokens, and finding wording changed enough to
defeat repeated-finding detection. Raising a source-generation limit could also
silently raise semantic rounds.

That behavior had four coupled causes:

- every revalidation could discover a new finding set;
- prose wording participated in practical finding identity;
- semantic repair shared generation-oriented loop controls;
- successful sibling work was not an independently adoptable closure; and
- workspace synthesis ran while source outcomes were still changing.

EGR-164 introduced the pinned execution kernel. EGR-165 added reusable L0/L1
artifact identities. Protocol 2.4 added lineal authority adoption and selective
L2 deepening through the normal Prosaic/provider route. L3 must use those
building blocks rather than recreating the v1 validation loop.

## Goals

- Register L3 as a strict layer over exact accepted L0, L1, and L2 authority.
- Audit explicitly selected domains and their selected-source cross-domain
  behavior.
- Freeze one stable finding set per audit epoch.
- Repair and recheck only the frozen set.
- Make finding identity insensitive to diagnostic rewording.
- Preserve accepted lower layers and express semantic corrections as L3
  overlays.
- Give semantic resolution independent token, active-time, round, retry, and
  plateau limits.
- Retain every closed finding when a sibling finding blocks.
- Make identical retry and identical guidance zero-call operations.
- Provide an explicit successor path for resource, evidence, human-decision,
  and semantic-plateau blockers.
- Preserve at-most-once dispatch, content-addressed objects, hash-chained
  events, typed ledger receipts, candidate capture, replay, and materialization.
- Continue using Prosaic frontmatter for model and effort selection across all
  providers.
- Preserve protocol 2.0 through 2.4 bytes and behavior.

## Non-goals

- Rewriting, replacing, or recertifying accepted L0, L1, or L2 artifacts.
- Treating an L3 resolution overlay as a hidden mutation of L2.
- Workspace synthesis, workspace `re/` publication, or source publication;
  EGR-168 owns those transitions.
- L4 exhaustive evidence or exhaustive-domain claims.
- Atomic or whole-domain lower-artifact repair; EGR-170 owns that work.
- Automatically expanding a frozen finding set during closure.
- Automatically creating another audit epoch after closure or plateau.
- Treating a selected-scope L3 closure as full-workspace quality.
- Introducing a second controller, event store, ledger envelope, object store,
  candidate framework, budget engine, status command, active pointer, provider
  adapter, or provider-specific result protocol.
- Making RE v2 the default engine.

## Decisions

### 1. L3 means audit and bounded closure

An immutable audit report with open findings is useful diagnostics, but it is
not L3 completion. The registered L3 goal is `semantic-audit-closure`:

1. audit the selected authority;
2. freeze the normalized finding set;
3. resolve and recheck that exact set within fixed bounds; and
4. terminalize as complete only when all frozen findings close through the
   source guard and no deferred observation requires a next epoch.

An epoch may instead pause for resources or terminal-block with unresolved
findings. Status must never label either state complete.

### 2. Protocol 2.5 uses manifest schema 4

Protocol 2.5 introduces `RunManifestV4`. Protocol 2.4's `RunManifestV3` remains
closed to L2 and is not generalized in place.

Schema dispatch remains exact:

| Manifest schema | Protocols | Meaning |
|---|---|---|
| 1 | 2.0, 2.1 | pinned deterministic kernel variants |
| 2 | 2.2, 2.3 | L0/L1 layered baseline |
| 3 | 2.4 | lineal adoption and selective L2 deepening |
| 4 | 2.5 | L3 frozen semantic audit and bounded closure |

The schema-4 manifest pins:

- direct parent and lineage-root authority;
- source snapshot and partition identities;
- normalized selected source/domain scope;
- target layer `L3`;
- run mode `new-audit-epoch`, `audit-successor`, or
  `closure-successor`;
- parent-authority bundle;
- artifact, executor, and audit-policy catalog references;
- frozen-epoch reference for a closure successor;
- optional immutable human-guidance reference;
- semantic request identity;
- run-wide operational budget; and
- independent semantic-closure budget.

No schema-1, schema-2, or schema-3 field changes meaning or becomes optional.

### 3. Completed parents remain immutable

`echelon re deepen --to L3` creates a child. It never appends to a completed L1
or L2 run. A terminal L3 blocker also remains immutable; guided repair creates a
successor child.

The child reuses `ParentLineageV1`. Protocol 2.5 adds
`ParentAuthorityBundleV2`, an additive schema that can carry both the unchanged
protocol-2.4 artifact/receipt closure and protocol-2.5 audit epoch, semantic
certification, finding-closure, deferred-observation, and L3-root authority. An
L1/L2 parent produces a V2 bundle whose semantic section is empty; an L3 parent
must provide its authenticated semantic closure.

The bundle copies exact authenticated object and receipt closures into the
child. It does not rewrite embedded V1 authority or infer authority from
rendered Markdown, mutable state, status JSON, or a parent directory's
continued existence.

Parent validation is mode-specific and fail-closed:

- a new L3 audit accepts a complete L1/L2 parent;
- an `audit-successor` accepts only a terminal pre-epoch L3 parent with
  authenticated accepted audit-target candidates and unresolved audit targets;
- a `closure-successor` accepts only a terminal L3 parent with a frozen epoch,
  authenticated closure root, and unresolved findings;
- `--new-audit-epoch` accepts a complete L3 parent or a
  `next_epoch_required` parent whose frozen findings are all closed; and
- no mode adopts an arbitrary partial, running, resource-paused, corrupt, or
  unauthenticated parent.

### 4. L3 fills missing prerequisites in order

The prerequisite chain remains closed and ascending:

```text
L0 -> L1 -> L2 -> L3
```

An L3 request may start from an accepted L1 or L2 parent. It adopts every exact
accepted prerequisite and schedules only missing selected L2 work through the
registered protocol-2.4 producers before scheduling audit work. L3 never
pretends an unaudited L1 artifact is an L2 prerequisite.

The L3 implementation extends the existing graph builder and prerequisite
planner. It does not add a second planner.

### 5. Scope includes domain and source-level audit targets

For every selected domain, L3 audits the exact selected L2 domain baseline and
its accepted evidence/dependency closure.

For every selected source, L3 also audits one source-level target over:

- the selected L2 source overview;
- the accepted selected L2 domain roots;
- selected cross-domain flows and boundaries;
- failure propagation across selected domains; and
- consistency among selected domain claims.

This source-level pass is required because individually plausible domain claims
can still contradict each other.

When only some domains are selected, the source audit and source L3 root are
selection-relative. They cannot claim full-source L3 coverage. Unselected
domains are `not_requested`, not failures.

## Immutable L3 authorities

### AuditTargetV1

The controller deterministically creates one target descriptor per selected
domain and source. It binds:

- target kind and normalized scope;
- exact audited L2 artifact keys and hashes;
- exact lower-layer dependency closure;
- exact bounded context/evidence object hashes;
- audit-policy hash; and
- auditor authority and response-schema hashes.

Its identity is the audit-target ID.

### FindingKeyV1 and SemanticFindingV1

Provider prose does not define finding identity. The controller normalizes an
accepted audit candidate into a `FindingKeyV1` containing:

- audit-target ID;
- rule ID from the closed audit taxonomy;
- finding class;
- structured subject kind and subject reference;
- normalized claim anchors;
- sorted authorized source-evidence anchors; and
- exact audited artifact hashes.

The finding-key ID is the canonical hash of that object. Diagnostic title,
description, explanation, recommendation, and provider wording are excluded
from identity.

Subject, claim, and evidence references must resolve to controller-issued IDs in
the bounded context. For a missing behavior with no lower-layer claim, the
subject is a controller-issued surface, operation, boundary, or evidence-fact
ID. The model cannot invent a free-form identity component. Equivalent source
citations that the controller has grouped under one evidence-fact authority
therefore do not churn the finding ID merely because the auditor cites a
different supporting line.

`SemanticFindingV1` contains the finding-key ID plus bounded diagnostic prose
and repair context. Two audit records with the same structured key normalize to
one finding; duplicates cannot multiply the repair queue. Two distinct
behaviors must use distinct structured subject references rather than relying
on prose to separate them.

Finding classes are closed for the first release:

- `missing_behavior`;
- `incorrect_behavior`;
- `contradictory_claim`;
- `unsupported_claim`;
- `evidence_scope_gap`;
- `cross_domain_inconsistency`;
- `requires_deeper_evidence`; and
- `requires_human_decision`.

### AuditCandidateV1

The provider writes exactly one bounded `audit.json` candidate for one target.
The controller validates:

- response schema and target identity;
- allowed rule and finding classes;
- exact audited artifact references;
- evidence ownership and line ranges against the immutable snapshot;
- structured subject and claim anchors;
- duplicate and contradictory finding records;
- byte/count limits; and
- candidate inventory and result-contract integrity.

A `PASS` candidate contains zero findings. A `REPAIR` candidate contains one or
more valid findings. The provider cannot write epoch IDs, finding IDs, receipts,
routing, counters, or completion state.

After structural/evidence certification, the normalized candidate is accepted
as the L3 `semantic-audit-findings` artifact for its target, with a null epoch
reference because the aggregate epoch does not yet exist. Its artifact key,
candidate assessment, semantic certification, and acceptance receipt make the
result adoptable by an exact pre-epoch audit successor.

### AuditEpochV1

After every requested audit target has an accepted candidate, the controller
creates one deterministic `AuditEpochV1` containing:

- epoch schema and policy identity;
- selected scope;
- audited target IDs and candidate hashes;
- auditor/executor/verifier authorities;
- sorted normalized findings and finding-key IDs;
- exact audited L2 roots; and
- exact audit-candidate certification/acceptance receipt hashes.

The audit-epoch ID is the canonical hash of that object. The epoch is stored as
a content-addressed object and recorded in the ledger before any semantic
resolution is scheduled.

Run ID, wall-clock timestamp, mutable projection revision, and diagnostic prose
are excluded from epoch identity. Identical accepted audit authority therefore
produces the same epoch object across crash recovery or an audit successor.

Audit candidate certification happens before the epoch exists. Resolution,
closure, and L3-root authorities bind the final audit-epoch ID.

### SemanticResolutionOverlayV1

Resolution never edits L2. For one audit target and semantic round, the resolver
writes exactly one `resolution.json` candidate containing proposed overlay
entries for the target's currently unresolved frozen finding IDs.

Each entry binds:

- one or more frozen finding-key IDs;
- a controlled resolution disposition;
- corrected or qualifying semantic claims;
- authorized evidence references;
- explicit supersession/refinement references to affected lower-layer claims;
- honest unresolved state when bounded evidence is insufficient; and
- no controller-owned verdict.

The accepted `SemanticResolutionOverlayV1` remains keyed by the existing
`ArtifactKeyV2` contract at layer L3. Its dependencies bind the audit epoch,
exact lower-layer hashes, prior accepted overlays for the target,
semantic-round policy, and guidance object when present. Protocol 2.5 does not
introduce a parallel artifact-key family.

An overlay may refine, qualify, or explicitly supersede a lower-layer claim in
the composed view. The lower artifact remains immutable and independently
addressable.

### SemanticCertificationReceiptV1

Existing `CertificationReceiptV2` remains unchanged. Protocol 2.5 introduces a
typed semantic certification receipt for structurally and evidentially valid
audit/resolution artifacts. It binds:

- artifact key and hash;
- verifier identity and implementation digest;
- audit-epoch ID where applicable;
- exact target and evidence scope;
- normalized diagnostics; and
- accepted/rejected outcome.

`CandidateAssessmentReceiptV1`, candidate capture, and the existing artifact
acceptance envelope remain reusable. The protocol-2.5 ledger facade recognizes
the new semantic certification receipt without changing protocol-2.2 through
2.4 ledger decoding.

### TargetClosureAssessmentV1 and SourceCompositionAssessmentV1

A closure recheck first produces a structurally certified
`TargetClosureAssessmentV1`. It covers the target's exact unresolved finding
set and records the proposed open/closed verdict for each ID, the overlay hash,
verifier authority, and any normalized deferred observations. It is durable but
does not itself close a finding.

After all target assessments for one source cycle are durable, the source guard
produces `SourceCompositionAssessmentV1`. It binds the complete proposed
overlay set, target-assessment hashes, selected L2/L3 composed authority,
implicated frozen finding IDs for any overlay-induced regression, normalized
deferred observations, and pass/fail outcome.

Both assessment types are content-addressed ledger authorities. Raw provider
output and mutable projection state cannot substitute for either one.

### FindingClosureReceiptV1

Closure judgment is model-assisted, but routing and persistence remain
controller-owned. After a target recheck and passing selected-source guard, the
controller records one `FindingClosureReceiptV1` per rechecked finding
containing:

- audit-epoch and finding-key IDs;
- audit target;
- resolution-overlay hash;
- closure-verifier authority;
- target-closure-assessment hash;
- passing source-composition-assessment hash;
- exact bounded evidence/context hash;
- semantic round;
- verdict `closed` or `open`;
- controlled reason code; and
- bounded diagnostic explanation.

A closure receipt cannot refer to a finding outside its epoch or to an overlay
that did not target that finding. A later receipt for the same finding must
depend on the preceding receipt and overlay, preserving the full chain.

### AuditClosureRootV1 and L3SourceRootV1

`AuditClosureRootV1` deterministically aggregates every frozen finding and its
latest closure receipt, unresolved set, semantic-round state, plateau state,
and any deferred observations. It distinguishes a closed epoch from a complete
L3 layer claim: deferred observations close neither the current finding set nor
the selected L3 scope.

`L3SourceRootV1` binds a selected source's domain and source-level audit targets,
their closure roots, selected-domain coverage, adopted closure authority, and
terminal scope state. It is `complete` only when every frozen finding in that
selected source scope is closed and the source has no deferred observation
requiring a next epoch.

## Audit and closure lifecycle

### Phase 1: prerequisite adoption and generation

The child imports the direct parent's complete accepted root and transitive
authority closure. Missing selected L2 prerequisites are generated through the
existing protocol-2.4 deepener, response schemas, provider renderer, and
controller certification.

No audit target becomes ready before its complete audited L2 dependency closure
is accepted.

### Phase 2: independent audit

Each audit target receives one bounded provider dispatch. Independent targets
may proceed despite a failed sibling, subject to the existing controller's
ready-work behavior.

The auditor receives only controller-supplied immutable context. It cannot
discover the live source workspace, sibling outputs, mutable status, or prior
aggregate findings.

Each audit operation permits:

- one initial dispatch;
- at most one shared retry;
- at most one result-contract or artifact-contract retry within that same
  two-dispatch maximum; and
- zero semantic-resolution rounds.

Malformed output cannot combine retry categories into a third audit dispatch.

### Phase 3: epoch freeze

After all requested audit candidates are accepted, the controller normalizes
and freezes the complete finding set. From this point:

- finding-key membership cannot change;
- audit targets cannot be redispatched within the epoch;
- closure rechecks cannot add repair work;
- wording changes cannot create new IDs; and
- only unresolved frozen findings are eligible for resolution.

An epoch with zero findings proceeds directly to closure-root and L3-source-root
creation without resolver or rechecker calls.

### Phase 4: batched target resolution

All currently unresolved findings for one audit target are batched into one
resolution candidate. This avoids one provider dispatch per finding while
keeping source/domain evidence boundaries explicit.

Resolution may close several findings with one coherent overlay. It cannot
address a sibling target, unselected domain, or finding absent from the epoch.

The controller coordinates these target batches as one semantic cycle per
selected source. It gathers the source's target overlays and recheck
assessments, then runs the single source composition guard. Targets with no
unresolved findings issue no resolution/recheck call but their already active
authority remains part of the source guard context.

### Phase 5: target closure recheck and source composition guard

The validator receives the frozen findings, accepted resolution overlay, exact
audited authority, and bounded evidence. It returns a verdict for every input
finding ID and no other authoritative finding.

Target closure is provisional until the selected source's composed overlay set
passes one source-level consistency guard for that semantic round. The guard
receives:

- every candidate overlay produced for the source in the round;
- the selected L2 domain/source authority;
- the source's frozen domain and source-level findings; and
- the exact target-recheck assessments.

It checks that the overlays jointly close the claimed findings without
introducing a contradiction, unsupported supersession, or selected-scope
regression. An overlay-induced regression is a candidate failure tied to the
frozen finding IDs that authorized the implicated overlays; it does not become
a new epoch finding. Those implicated IDs remain open for the next bounded
round.

The controller records final `closed` finding receipts only after both the
target recheck and source composition guard pass. A structurally accepted
overlay that fails semantic closure remains an immutable attempt artifact, but
no L3 source root treats it as active composed authority. A later overlay may
depend on it for repair context without concealing the failed attempt.

The recheck or composition guard may include bounded
`deferred_observations`. These are normalized diagnostic inputs for a later
explicit audit epoch. They:

- do not join the frozen set;
- do not enter the current repair queue;
- do not count as closed findings;
- are surfaced in status and materialization; and
- cannot be represented as closure findings or receipts.

An output that introduces a new authoritative finding, omits an input finding,
or changes an input finding's identity is contract-invalid.

Each deferred observation uses the same controller-issued subject, rule, and
evidence-anchor vocabulary as a finding, receives a deterministic observation
ID, and becomes a mandatory audit seed for the explicitly requested next epoch.
The controller deduplicates observations by that ID across target and source
assessments. Free-form commentary cannot create an observation or change its
identity.

### Phase 6: progress, plateau, and completion

Progress is reduction in the set of unresolved finding-key IDs. Changed prose,
changed recommendations, a different overlay hash, or reordered findings do
not count as progress.

For each audit target that participates in a source semantic cycle:

- a reducing round resets its consecutive no-reduction counter to zero;
- a non-reducing round increments that counter;
- two consecutive non-reducing rounds terminal-block the target; and
- three semantic-resolution rounds is the absolute first-release maximum.

The target's round counter increments once after the source guard records the
cycle outcome, not once per resolver, rechecker, or source-guard provider call.

The controller continues independent targets when one target blocks. Closed
siblings remain closed and adoptable.

The current epoch is closed when every frozen finding in the requested scope is
closed. The selected L3 scope is complete only when the epoch is closed, every
required L3 source root is accepted, and no deferred observation requires a
next epoch.

If all frozen findings close but deferred observations exist, the child enters
the distinct terminal state `next_epoch_required`. It does not automatically
spend more tokens, and it does not display `L3 SELECTED SCOPE COMPLETE`.

### Authoritative lifecycle states

Replay derives one of these semantic states from events, ledger receipts, and
accepted roots; no mutable status field independently controls routing:

- `running_prerequisites`;
- `running_audit`;
- `epoch_frozen`;
- `running_resolution`;
- `running_closure_recheck`;
- `running_source_guard`;
- `paused_resource`;
- `blocked_incomplete`;
- `blocked_plateau`;
- `next_epoch_required`; or
- `complete`.

`paused_resource` is nonterminal and continuable. `blocked_incomplete`,
`blocked_plateau`, `next_epoch_required`, and `complete` are terminal for that
child. Only a validated successor/new-epoch operation creates further work from
their retained authority.

## Independent budgets

Protocol 2.5 retains the existing run-wide token and provider-active-time
ceilings. Every provider dispatch consumes them.

It adds an immutable `SemanticClosurePolicyV1`, evaluated by the existing
event-derived accounting engine, containing:

- semantic token limit;
- semantic active-time limit;
- maximum semantic rounds per target: `3`;
- consecutive no-reduction limit: `2`;
- per-operation provider-attempt maximum: `2`;
- shared result/artifact-contract retry maximum: `1`; and
- unknown/untrusted usage charging policy inherited from the shared provider
  reservation calculator.

Resolution, target-recheck, and source-composition-guard dispatches consume the
semantic token/time pool. A semantic round is one controller-owned
resolution/recheck/guard cycle and increments its round counter exactly once;
individual provider calls within the cycle do not each increment the round.
Initial audits and missing L2 generation use their own work-item attempt classes
while still consuming run-wide resources.

The initial semantic pool authorizes one resolution/target-recheck cycle per
selected audit target plus one source-composition guard per selected source,
using the shared conservative reservation calculator. Additional rounds require
remaining measured capacity or explicit resource authorization; they never
receive an implicit budget because earlier rounds made progress.

`echelon re continue` may raise run-wide and semantic token/time ceilings by
appending authenticated budget-authorization events. It cannot raise:

- provider attempts per operation;
- resolution rounds;
- result/artifact-contract retries; or
- the two-round plateau threshold.

Increasing a generation ceiling never changes semantic limits. Increasing only
the run-wide ceiling does not silently increase the semantic pool.

## Blocked repair path

### Resource pause

Token or active-time exhaustion produces `paused_resource`, not terminal
semantic failure. After explicit budget authorization, `echelon re continue`
resumes the same epoch and unresolved set. It does not rerun accepted audits or
closed findings.

### Crash or indeterminate execution

Recovery uses the existing at-most-once rule. A started call with no durable
observation is never silently reissued under the same dispatch ID. The run
reports the indeterminate operation and follows the shared bounded recovery
classification.

### Semantic plateau or fixed-attempt exhaustion

Two no-reduction rounds or exhaustion of fixed semantic attempts terminalizes
the L3 child as blocked. Adding tokens alone cannot reopen it.

The blocked run retains:

- its immutable audit epoch;
- all accepted resolution overlays;
- every closed finding receipt;
- the exact unresolved set;
- plateau/attempt history; and
- an actionable next step per unresolved finding class.

### Pre-epoch audit blocker

If a requested audit target exhausts its fixed contract/provider attempts before
the epoch can freeze, the child terminalizes as `blocked_incomplete`. Accepted
sibling audit candidates remain authenticated and adoptable, but the run cannot
invent a complete epoch from a partial target set.

An explicitly guided `audit-successor` adopts every exact accepted sibling
candidate and schedules only missing audit targets. Its identity binds the
failed parent, accepted-target set, remaining target IDs, auditor/policy
authority, and guidance hash. Identical successor guidance performs zero calls.

### Guided closure successor

The existing user-facing `echelon re resume "<answer>"` command is extended for
a terminal L3 blocker. It creates a new schema-4 `audit-successor` when no epoch
exists, or a `closure-successor` after epoch freeze, rather than mutating the
blocked parent.

The guidance is stored as an immutable object bound to:

- blocked parent manifest and terminal-event hashes;
- accepted audit-candidate set and unresolved target IDs before epoch freeze,
  or parent epoch/closure-root hashes and exact unresolved finding IDs after
  freeze; and
- normalized answer text.

An audit successor adopts accepted sibling audit candidates and schedules only
missing targets. A closure successor adopts the frozen epoch and all closed
receipts, then schedules only unresolved findings. Identical guidance against
the same blocked authority resolves to the existing successor and performs zero
provider calls.

### Evidence and lower-layer blockers

`requires_deeper_evidence` remains unresolved until a later L4 or changed-source
lineage supplies new accepted authority. `requires_human_decision` requires
immutable guidance before successor resolution.

If a finding cannot be represented honestly as an L3 refinement or
supersession and instead requires lower-artifact mutation, status routes it to
the later atomic-repair path. Protocol 2.5 does not weaken lower-layer
immutability to force closure.

### Explicit next audit epoch

A completed L3 epoch is terminal. Deferred observations produce
`next_epoch_required`; an operator request for another independent audit uses
an explicit `--new-audit-epoch` operation from that terminal L3 parent. Without
that option, repeating the original semantic request returns the existing child
and makes zero calls.

The new epoch audits the composed accepted authority, including prior L3
overlays, and has a new policy/parent closure input. It does not rewrite the
prior epoch.

## Semantic request identity and zero-call reuse

The semantic request ID includes:

- lineage-root run and manifest identities;
- direct parent closure authority relevant to L3;
- source snapshot and partition identities;
- normalized selected scope;
- target layer and run mode;
- artifact, executor, and audit-policy catalog hashes;
- accepted audit-target set for audit successors, or frozen epoch and prior
  closure root for closure successors; and
- immutable guidance hash when present.

Creation remains protected by the existing workspace creation lock and active
pointer publication sequence. An exact semantic request finds its existing
child regardless of whether that child is running, paused, complete,
`next_epoch_required`, or blocked. It never creates a duplicate paid run.

## Prosaic and shared provider path

Protocol 2.5 preserves the adapter contract, shared CLI provider, request
capture, usage normalization, reservation calculator, and provider capability
handling used by protocol 2.4.

### Auditor and closure rechecker

`echelon.re-validator` gains explicit bounded v2 modes:

- `AUDIT_EPOCH_TARGET`; and
- `CLOSURE_RECHECK`.

Its existing v1 phase contract remains unchanged. The v2 request renderer
supplies the mode, closed response schema, target descriptor, and bounded
immutable context. In v2 mode the validator writes exactly `audit.json` or
`closure.json` inside the isolated candidate root and reads no live workspace.

### Resolver

A new neutral `echelon.re-resolver` Prosaic role authors exactly one bounded
`resolution.json` candidate for the controller-supplied unresolved finding set.
It cannot edit lower artifacts, inspect the live source, select additional
findings, write receipts, or claim closure.

Both agents use paired ALWAYS/NEVER rules. Their model tier and effort remain
neutral Prosaic frontmatter interpreted by the existing provider machinery.

### No provider fork

Protocol 2.5 may register new agent, response-schema, producer-policy, and
verifier hashes in the existing executor catalog. It does not add:

- a provider adapter or adapter ID;
- an OpenAI/Anthropic/provider-specific transport;
- direct model calls from the controller;
- a provider-specific result parser;
- an L3 model selector; or
- a fallback that bypasses Prosaic.

## Controller and durable state

The protocol-2.5 controller is a narrow extension of `Protocol24Controller` and
the shared protocol-2.2 controller. It specializes only registered L3 candidate,
epoch, closure, and terminal transitions.

The event envelope, hash chain, sequence numbers, projection replay, locking,
candidate store, object store, ledger envelope, and fsync rules remain shared.

Protocol 2.5 adds closed event payloads for:

- `audit_candidate_accepted`;
- `audit_epoch_frozen`;
- `semantic_resolution_started`;
- `semantic_resolution_accepted`;
- `closure_recheck_started`;
- `source_composition_guard_started`;
- `finding_closure_recorded`;
- `semantic_progress_recorded`;
- `semantic_plateau_reached`;
- `l3_source_root_accepted`; and
- successor guidance/adoption.

Events are routing/audit history, not parallel receipt authority. Accepted
artifact and finding state still derives from typed ledger receipts and object
hashes.

## Recovery

Recovery must be idempotent at these new durable boundaries:

1. audit result captured but candidate inventory incomplete;
2. audit candidate committed but not certified;
3. all audits accepted but epoch root absent;
4. epoch object stored but ledger/event record absent;
5. resolution dispatch started without durable observation;
6. resolution captured but candidate inventory incomplete;
7. resolution certified but artifact not accepted;
8. accepted overlay present but closure recheck not scheduled;
9. target closure recheck captured but source composition guard absent;
10. composition guard captured but closure receipts incomplete;
11. some finding receipts durable but aggregate progress event absent;
12. progress durable but plateau/next-round projection absent;
13. all findings closed but deferred-observation routing or source L3 roots
    absent;
14. all required roots accepted but terminal event absent;
15. terminal event durable but active pointer stale; and
16. successor inputs published but parent closure adoption incomplete.

Recovery validates manifest, graph, adopted authority, candidate commits,
receipts, events, and object hashes before advancing. It never reconstructs
authority from materialized files or reissues a provider call merely because a
projection is missing.

## Materialization

Accepted L3 authority materializes below the run only:

```text
runs/<run-id>/re/l3/
  epoch.json
  epoch.md
  findings/<finding-id>.json
  resolutions/<target-id>/<round>.json
  closure/<finding-id>.json
  sources/<source-id>/root.json
  sources/<source-id>/overview.md
```

Materialization extends the existing layer-aware materializer, lock,
altered-projection quarantine, and atomic publication rules. Deleting a
projection and rebuilding it from accepted objects/receipts must produce
byte-identical output.

The composed Markdown view makes lower-layer refinement explicit. It does not
silently edit rendered L2 files. Raw L2, raw L3 overlay, and composed L3 view
remain separately inspectable.

Protocol 2.5 does not write workspace `re/`, run workspace synthesis, publish
source artifacts, or make synthesis a dependency of L3.

## Status and terminal banner

`echelon re status` and `--json` extend the current manifest router and
protocol-2.4 status pattern. No second status command or cache is added.

Status reports:

- protocol, schema, run mode, parent, and lineage;
- target layer and normalized selection;
- adopted/generated artifacts by layer;
- selected domain and source audit-target state;
- frozen, closed, unresolved, and deferred observation counts;
- current semantic round and no-reduction count by target;
- audit, resolution, recheck, and source-guard dispatch counts;
- known, unknown, trusted, and conservatively reserved usage by operation;
- run-wide and semantic token/time authorization;
- accepted overlays and closure receipts;
- blocked finding classes and exact next action;
- selected versus full-source/domain coverage; and
- zero-call reuse/adoption facts.

Human output ends with one prominent banner:

```text
L3 SELECTED SCOPE COMPLETE
L3 PAUSED - CONTINUABLE
L3 BLOCKED - FROZEN FINDINGS UNRESOLVED
L3 EPOCH CLOSED - NEXT AUDIT EPOCH REQUIRED
```

The complete banner requires zero unresolved findings and zero deferred
observations. It states:

- this selected audit epoch is closed;
- whether coverage is full-source or intentionally scoped;
- that deferred observations are zero;
- workspace synthesis is not run;
- L4 exhaustive depth is not run; and
- unselected domains remain unaudited.

The next-epoch banner reports the closed epoch, retained closure receipts,
deferred-observation count, and exact explicit command. It never collapses that
state into complete or blocked semantic repair.

A plateau banner includes, for example:

```text
L3 BLOCKED - 3/17 FROZEN FINDINGS UNRESOLVED
reason: semantic plateau after 2 no-reduction rounds
closed findings retained: 14
next action: provide repair guidance or deepen affected evidence
identical continuation will issue zero provider calls
```

## Telemetry

Existing provider and RE v2 telemetry remains authoritative. Protocol 2.5 adds
dimensions, not another telemetry stream:

- audit epoch and policy IDs;
- audit target kind and scope;
- frozen findings by class/rule/source/domain;
- resolution batch size, target-recheck outcome, source-guard outcome, and
  semantic round;
- finding IDs before and after each recheck;
- closed/unresolved/deferred-observation counts;
- progress and no-reduction outcomes;
- plateau and terminal blocker reasons;
- audit versus resolution versus recheck calls;
- token/reservation/active duration by operation class;
- adopted closed receipts and unresolved findings in successors;
- immutable guidance identity, never raw guidance content in telemetry; and
- zero-dispatch exact-reuse counts.

The analyzer must be able to answer:

- how many findings the epoch froze;
- how many closed on each round;
- how much audit and semantic closure cost separately;
- whether usage is complete or conservatively reserved;
- why a target stopped; and
- how much a successor reused.

## CLI behavior

The registered operation remains:

```text
echelon re deepen --to L3 --all
echelon re deepen --to L3 --source SOURCE
echelon re deepen --to L3 --source SOURCE --domain DOMAIN
```

The existing `--from-run`, token, and active-time controls remain. Protocol 2.5
adds explicit semantic token/time authorization without reusing
`--re-max-inner`; v2 fixed semantic rounds are not an inner-loop override.

Resource continuation uses:

```text
echelon re continue [run-wide and/or semantic resource overrides]
```

Guided repair uses the established human-input UX:

```text
echelon re resume "<answer>"
```

For a terminal L3 blocker this creates or reuses an audit-successor or
closure-successor child according to whether the epoch was frozen.

Another independent audit uses an explicit option from a completed L3 parent:

```text
echelon re deepen --to L3 --from-run RUN_ID --new-audit-epoch ...
```

No automatic next epoch is scheduled.

## Security and evidence boundary

- Source preflight remains clean-Git only.
- Audit and resolution use the immutable captured snapshot, never live source.
- Candidate roots retain the existing isolated write boundary.
- The validator and resolver receive only controller-selected bounded context.
- Evidence paths and ranges are resolved beneath the declared source/domain
  roots and validated against immutable bytes.
- Symlinks, hardlinks, special files, path traversal, and unregistered object
  references fail closed through existing primitives.
- Guidance is immutable authority but not source evidence.
- A model verdict cannot write events, receipts, state, budgets, completion, or
  active pointers.

## Reuse map

| Concern | Reused Echelon building block |
|---|---|
| Layer prerequisites | protocol-2.4 graph and protocol-2.2 work templates |
| Parent/lineage authority | `ParentLineageV1`, unchanged V1 closure embedded by `ParentAuthorityBundleV2`, adoption validation |
| Immutable input publication | manifest-last protocol-2.4 input store pattern |
| Provider execution | Prosaic prompt loader, executor catalog, shared CLI adapter and renderer |
| Model/effort | neutral Prosaic frontmatter and existing provider interpretation |
| Candidate isolation | shared execution capture and candidate commit store |
| Object authority | existing run-local content-addressed object store |
| Events | `EventStore` with a protocol-2.5 `EventProtocol` extension |
| Ledger | `DurableLedger` and protocol-2.5 typed receipt facade |
| Attempts/resources | shared event-derived budget accounting with semantic dimensions |
| Recovery | protocol-2.2 recovery and protocol-2.4 authority validation seams |
| Materialization | existing layer-aware materializer and projection replay |
| Status | `render_v2_status` manifest routing and protocol-2.4 document pattern |
| Human input | existing `echelon re resume` UX, routed to immutable successor creation |

## Rejected parallel machinery

Implementation must stop for redesign if it appears to require:

- a mutable findings file as routing authority;
- a second run-state database;
- a new event/ledger envelope;
- a second candidate or object store;
- a new active-run pointer;
- a provider-direct audit or repair call;
- a provider-specific L3 adapter;
- a generic arbitrary-goal framework;
- implicit new audit epochs;
- lower-layer mutation to achieve closure; or
- workspace synthesis inside the L3 controller.

## Verification strategy

### Schema and identity

- Canonical round trips for every schema-4 input and receipt.
- Exact rejection of unknown, missing, unsafe, duplicate, or unsorted fields.
- Finding-key identity remains stable across diagnostic rewording and ordering.
- Different structured subject/evidence authority produces a different ID.
- Epoch identity binds exact findings, targets, policies, and audited hashes.
- Protocol 2.0 through 2.4 canonical bytes remain unchanged.

### Graph and scope

- L3 from L1 schedules missing L2 before audit.
- L3 from L2 adopts exact prerequisites and schedules no L2 provider calls.
- Domain selection schedules its domain audit plus a selection-relative source
  audit.
- All-source selection audits every non-empty domain and each source.
- Unselected domains remain `not_requested`.
- Source roots cannot claim unselected coverage.
- Domain closure remains provisional until the selected-source composition
  guard passes.

### Frozen epoch and closure

- Audits cannot be redispatched after epoch freeze.
- Closure output must cover every requested unresolved ID exactly once.
- A new authoritative finding in closure output is rejected.
- Overlay-induced regressions keep their authorizing frozen findings open and
  do not expand the epoch.
- Closed receipts are written only after target and source-level guards pass.
- Deferred observations remain non-authoritative, do not mutate the queue, and
  force `next_epoch_required` instead of L3 completion.
- Resolution cannot target a sibling or non-epoch finding.
- Closed findings never re-enter later rounds.
- Zero-finding epochs issue no resolver/rechecker calls.

### Budget and plateau

- Audit attempts do not consume semantic rounds.
- Resolution/recheck/source-guard usage consumes both run-wide and semantic
  pools while incrementing the semantic round once per cycle.
- Raising run-wide generation resources does not raise semantic authorization.
- Resource authorization cannot raise attempts, rounds, retries, or plateau
  threshold.
- Unchanged unresolved IDs count as no reduction despite changed prose/overlay.
- Any reduction resets only the consecutive no-reduction counter.
- Two no-reduction rounds block; three rounds is the absolute maximum.

### Successor and reuse

- Pre-epoch audit successors adopt accepted sibling audit candidates and
  schedule only unresolved audit targets.
- Plateau blockers retain all accepted overlays and closed receipts.
- Guided successor adopts closed receipts and schedules only unresolved IDs.
- Identical L3 request returns the existing
  complete/next-epoch-required/paused/blocked child with zero calls.
- Identical guidance returns the same successor with zero calls.
- Changed guidance changes semantic request identity.
- A new audit epoch requires explicit authorization.

### Recovery

Inject a crash at every listed durable boundary and prove:

- no accepted audit or closure is lost;
- no provider dispatch is duplicated;
- missing projections rebuild from authority;
- partial closure receipts reconcile idempotently;
- terminal replay is stable; and
- active-pointer repair does not alter run authority.

### Provider and isolation

- Fake-executor tests cover all state transitions deterministically.
- Loopback provider tests prove request/result contracts and usage accounting.
- A real Codex pilot uses the installed Prosaic roles and shared adapter.
- Provider-specific tests prove Claude, Codex, Copilot, and OpenCode routing
  remains the shared path where configured.
- Dirty source preflight fails before child creation.
- Source Git status and bytes remain unchanged after audit, repair, recovery,
  and materialization.

### Compatibility and full gate

- Protocol 2.0 through 2.4 continuation/status/materialization remain green.
- v1 RE remains isolated and default.
- Existing L0/L1/L2 real-workspace pilots remain readable and adoptable.
- Run-local L3 projections rebuild byte-identically.
- Full repository tests pass before merge.

## Real workspace pilot

Before merge, install Echelon and run a small clean-Git Codex pilot that:

1. starts from a completed L1 or L2 parent;
2. selects at least two domains in one source;
3. proves missing L2 scheduling or exact L2 adoption;
4. freezes at least one domain and one source-level audit target;
5. exercises a zero-finding target and a repairable finding target;
6. records one accepted resolution and closure receipt;
7. repeats the identical request and proves zero additional dispatches;
8. inspects status, events, ledger, candidates, materialization, and telemetry;
9. verifies source Git is byte-for-byte clean; and
10. if practical, injects one crash boundary and proves recovery.

The pilot is evidence for the registered selected scope only. It does not claim
workspace synthesis, publication, L4 exhaustiveness, or default-engine
readiness.

## Success criteria

The L3 increment is complete when:

1. protocol 2.5/schema 4 is registered without changing older protocols;
2. `--to L3` layers over exact L0/L1/L2 authority;
3. domain and selected-source audits freeze a stable finding epoch;
4. finding identity excludes mutable diagnostic prose;
5. resolution produces immutable L3 overlays rather than lower-layer edits;
6. closure rechecks cannot expand the finding set;
7. selected-source composition guards prevent overlay-induced contradictions
   from being certified as closure;
8. deferred observations require an explicit next epoch and cannot produce an
   L3-complete claim;
9. semantic resources and rounds are independently bounded;
10. two no-reduction rounds and the three-round ceiling stop repair;
11. closed receipts survive blockers and are adoptable by successors;
12. exact retry and exact guidance issue zero provider calls;
13. status gives a prominent truthful terminal banner and next action;
14. workspace synthesis, L4, and atomic repair remain out of scope;
15. the implementation reuses Echelon's shared controller/provider/durability
    patterns; and
16. focused, compatibility, full-suite, and real-workspace pilot gates pass.

## Deferred work

- EGR-168: synthesize only accepted source outcomes, including explicit partial
  outcomes, through a separate workspace dependency graph.
- EGR-169 L4: register explicitly selected exhaustive-depth goals over accepted
  L3 authority.
- EGR-170: revise and implement atomic lower-artifact repair against the stable
  L0 through L4 interfaces.
- Default-engine cutover only after the layered RE program and production
  evidence support it.
